"""Profit backtest of the weekend plan on past seasons (football-data.co.uk results + Bet365 prices).

For every Saturday/Sunday of each season, every match in the weekend leagues is analysed exactly as
the live app would (same model, gates, rejection rules and builder), using only matches played
before it. Prices are Bet365's pre-match odds of the time (1X2, Over/Under 2.5, the main Asian
handicap line — the only markets with historical prices), so the backtest cannot use markets such as
Under 3.5, BTTS, double chance, corners or cards that the live app also considers. Each weekend's
ticket for each target is staked at 1 unit and settled with the real result.

What it shows: whether the selection rules would have made or lost money, how often tickets won,
the longest losing run, and whether the chosen legs beat Bet365's closing price (CLV).
What it cannot show: UEFA midweek slots (not in the historical files), your own manual prices.
"""
from __future__ import annotations

import json
import math
import threading
from collections import defaultdict
from datetime import date, timedelta

from ..db import Database
from ..history import DIVISIONS
from ..timeutil import iso, now_utc
from .accumulator import build, combined_odds
from .countmodel import count_model
from .data import MatchStore, prev_season
from .markets import evaluate_candidates
from .poisson import fit_match
from .rejection import RESULT_MARKETS, closely_matched, decide, evaluate_rules
from .scoring import data_quality, risk_assessment
from .stats import team_profile
from .tracking import settle_market

PAYOUT = {"won": lambda o: o, "half_won": lambda o: (o + 1) / 2, "void": lambda o: 1.0,
          "half_lost": lambda o: 0.5, "lost": lambda o: 0.0}


def historical_prices(m: dict) -> list[dict]:
    rows = []

    def add(market, sel, line, odds):
        if odds and odds > 1:
            rows.append({"id": 0, "market": market, "selection": sel, "line": line, "odds": float(odds),
                         "bookmaker": "bet365", "source": "historical", "checked_at": m["date"]})
    add("1X2", "home", None, m.get("b365_h"))
    add("1X2", "draw", None, m.get("b365_d"))
    add("1X2", "away", None, m.get("b365_a"))
    add("OU", "over", 2.5, m.get("b365_o25"))
    add("OU", "under", 2.5, m.get("b365_u25"))
    if m.get("ah_line") is not None:
        add("AH", "home", m["ah_line"], m.get("b365_ahh"))
        add("AH", "away", -m["ah_line"], m.get("b365_aha"))
    return rows


def closing_for(m: dict, market: str, selection: str, line) -> float | None:
    from .clv import fd_closing
    return fd_closing(m, market, selection, line)


def analyse_historical(store: MatchStore, m: dict, settings: dict, ml_oos: dict | None = None) -> dict | None:
    season, comp, day = m["season"], m["competition"], m["date_obj"]
    min_n = int(settings["min_matches_model"])
    legs_out = []
    rows = {}
    for side in ("home", "away"):
        tid = m[f"{side}_key"]
        cur = store.history(tid, day, {comp}, {season})
        model = store.history(tid, day, {comp}, {season, prev_season(season)})
        if len(cur) < min_n and len(model) < min_n + 4:
            return None
        rows[side] = (cur, model)
    (hc, hm), (ac, am) = rows["home"], rows["away"]
    min_stat = int(settings["min_matches_stat"])
    hp, ap = team_profile(hc, "H", min_stat), team_profile(ac, "A", min_stat)
    goals = fit_match(store, hm, am, comp, day, settings, False, season)
    if not goals.available:
        return None
    if ml_oos is not None:
        pred = ml_oos.get(m["id"])
        if pred is None:
            return None  # ML backtest: only matches with an out-of-sample ML prediction
        from ..ml.predict import apply_ml
        goals = apply_ml(goals, pred)
    corners = count_model("corners", store, hc, ac, comp, day, settings)
    cards = count_model("cards", store, hc, ac, comp, day, settings)
    cands = evaluate_candidates(home=m["home"], away=m["away"], home_rows=hc, away_rows=ac, goals=goals,
                                corners=corners, cards=cards, odds_rows=historical_prices(m), research=[],
                                settings=settings, cross_league=False)
    gd = goals.to_dict()
    if closely_matched(gd, hp, ap, settings):
        for c in cands:
            if c["market"] in RESULT_MARKETS and c["qualifies"]:
                c["qualifies"] = False
    factors = evaluate_rules(home=m["home"], away=m["away"], home_p=hp, away_p=ap, goals=gd, candidates=cands,
                             research=[], settings=settings, dataset_age_days=0.5, fixture_date=day,
                             home_last=hc[0].date if hc else None, away_last=ac[0].date if ac else None,
                             cross_league=False, unlinked=[], time_label="corroborated", verified=True)
    status = decide(factors)
    if status == "rejected":
        return {"status": status, "legs": []}
    dq = data_quality(hp, ap, {"half_time": 1, "shots": 1, "corners": 1, "cards": 1}, 0.5, "corroborated",
                      True, True, False, settings)["score"]
    risk = risk_assessment([f for f in factors if f["action"] != "info" or f["severity"] != "low"])["level"]
    from .analysis import confidence
    for c in cands:
        if not (c["qualifies"] and c["price"]):
            continue
        conf = confidence(c, dq, risk, settings)
        legs_out.append({
            "match_id": m["id"], "key": c["key"], "label": c["label"], "match_label": f"{m['home']} vs {m['away']}",
            "home_id": m["home_key"], "away_id": m["away_key"], "market": c["market"], "selection": c["selection"],
            "line": c["line"], "odds": c["price"]["odds"], "probability": c["win_probability"],
            "void_probability": c["void_probability"], "score": c["score"]["total"], "tier": c["tier"],
            "confidence": conf, "match_status": status, "competition": comp, "date": m["date"],
            "good": c["tier"] in ("strong", "acceptable") and conf in ("high", "medium"),
        })
    return {"status": status, "legs": legs_out}


def settle_leg(leg: dict, m: dict) -> str:
    return settle_market(leg["market"], leg["selection"], leg["line"], m) or "void"


def run_backtest(store: MatchStore, settings: dict, seasons: list[str], targets: list[float],
                 competitions: list[str], progress=lambda done, total, msg: None,
                 ml_oos: dict | None = None) -> dict:
    max_legs = int(settings["plan_max_legs"])
    by_season: dict[str, dict] = {}
    all_weekends = []
    for season in seasons:
        matches = [m for code in competitions for m in store.by_comp.get(code, [])
                   if m.get("season") == season and m["date_obj"].weekday() in (5, 6) and m.get("b365_h")]
        weekends: dict[date, list[dict]] = defaultdict(list)
        for m in matches:
            weekends[m["date_obj"] - timedelta(days=m["date_obj"].weekday() - 5)].append(m)
        all_weekends += [(season, wk, ms) for wk, ms in sorted(weekends.items())]
    total = len(all_weekends)
    tickets: list[dict] = []
    legs_used: dict[str, dict] = {}
    for i, (season, wk, ms) in enumerate(all_weekends):
        progress(i, total, f"{season} weekend {wk.isoformat()}")
        pool_good, pool_weak, by_id = [], [], {m["id"]: m for m in ms}
        for m in ms:
            a = analyse_historical(store, m, settings, ml_oos)
            if not a or not a["legs"]:
                continue
            best = max(a["legs"], key=lambda x: x["score"])
            (pool_good if best["good"] else pool_weak).append(best)
        for t in targets:
            out = build(pool_good, pool_weak, t, max_legs)
            legs = out["main"]
            if not legs:
                continue
            ret = 1.0
            leg_res = []
            for leg in legs:
                res = settle_leg(leg, by_id[leg["match_id"]])
                ret *= PAYOUT[res](leg["odds"])
                leg_res.append(res)
                key = leg["match_id"] + leg["key"]
                if key not in legs_used:
                    close = closing_for(by_id[leg["match_id"]], leg["market"], leg["selection"], leg["line"])
                    legs_used[key] = {"season": season, "market": leg["market"], "odds": leg["odds"],
                                      "probability": leg["probability"], "result": res,
                                      "clv": None if not close else leg["odds"] / close - 1}
            tickets.append({"season": season, "weekend": wk.isoformat(), "target": t, "legs": len(legs),
                            "odds": round(combined_odds([x["odds"] for x in legs]), 2),
                            "reached": out["target_reached"], "return": round(ret, 4),
                            "won": ret > 1,
                            "model_p": math.prod(x["probability"] for x in legs)})
    progress(total, total, "summarising")
    summary = []
    for season in seasons + ["all"]:
        for t in targets:
            ts = [x for x in tickets if x["target"] == t and (season == "all" or x["season"] == season)]
            for subset, items in (("all tickets", ts), ("only when target reached", [x for x in ts if x["reached"]])):
                summary.append({"season": season, "target": t, "subset": subset, **_ticket_stats(items)})
    legs = list(legs_used.values())
    leg_stats = []
    for season in seasons + ["all"]:
        ls = [x for x in legs if season == "all" or x["season"] == season]
        leg_stats.append({"season": season, **_leg_stats(ls)})
    by_market = {mk: _leg_stats([x for x in legs if x["market"] == mk]) for mk in sorted({x["market"] for x in legs})}
    return {"engine": "ml" if ml_oos is not None else "statistical",
            "seasons": seasons, "targets": targets, "competitions": competitions, "weekends": total,
            "tickets": summary, "legs": leg_stats, "legs_by_market": by_market,
            "ticket_log": tickets[-400:], "settings": {k: settings.get(k) for k in (
                "prior_weight", "recency_half_life", "history_carryover", "min_leg_probability", "min_leg_odds",
                "min_evidence_score", "plan_max_legs")}}


def _ticket_stats(ts: list[dict]) -> dict:
    if not ts:
        return {"tickets": 0}
    profit = sum(x["return"] - 1 for x in ts)
    streak = worst = 0
    bank = peak = drawdown = 0.0
    for x in ts:
        streak = streak + 1 if x["return"] < 1 else 0
        worst = max(worst, streak)
        bank += x["return"] - 1
        peak = max(peak, bank)
        drawdown = max(drawdown, peak - bank)
    won = sum(1 for x in ts if x["return"] > 1)
    return {"tickets": len(ts), "won": won, "hit_rate": round(won / len(ts), 4),
            "avg_odds": round(sum(x["odds"] for x in ts) / len(ts), 2),
            "avg_legs": round(sum(x["legs"] for x in ts) / len(ts), 1),
            "model_expected_wins": round(sum(x["model_p"] for x in ts), 1),
            "profit_units": round(profit, 2), "roi": round(profit / len(ts), 4),
            "longest_losing_run": worst, "max_drawdown_units": round(drawdown, 2)}


def _leg_stats(ls: list[dict]) -> dict:
    if not ls:
        return {"legs": 0}
    decided = [x for x in ls if x["result"] != "void"]
    wins = sum(1 for x in decided if x["result"] in ("won", "half_won"))
    profit = sum(PAYOUT[x["result"]](x["odds"]) - 1 for x in ls)
    clv = [x["clv"] for x in ls if x["clv"] is not None]
    return {"legs": len(ls), "win_rate": round(wins / len(decided), 4) if decided else None,
            "model_avg": round(sum(x["probability"] for x in decided) / len(decided), 4) if decided else None,
            "implied_avg": round(sum(1 / x["odds"] for x in decided) / len(decided), 4) if decided else None,
            "singles_profit_units": round(profit, 2), "singles_roi": round(profit / len(ls), 4),
            "avg_clv": round(sum(clv) / len(clv), 4) if clv else None,
            "beat_close_share": round(sum(1 for c in clv if c > 0) / len(clv), 3) if clv else None}


# ---------------------------------------------------------------------- background job
SCHEMA = """CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT, status TEXT,
    progress TEXT, params TEXT, result TEXT, error TEXT)"""
_job_lock = threading.Lock()


def backtest_competitions(weekend_codes: list[str]) -> tuple[list[str], list[str]]:
    covered = set(DIVISIONS.values())
    return [c for c in weekend_codes if c in covered], [c for c in weekend_codes if c not in covered]


def start_backtest(db: Database, store: MatchStore, settings: dict, seasons: list[str], targets: list[float],
                   competitions: list[str], ml_oos: dict | None = None) -> int:
    with db.tx() as c:
        c.execute(SCHEMA)
    if not _job_lock.acquire(blocking=False):
        raise RuntimeError("A backtest is already running.")
    run_id = db.execute("INSERT INTO backtest_runs(started_at, status, progress, params) VALUES(?,?,?,?)",
                        (iso(now_utc()), "running", "starting",
                         json.dumps({"seasons": seasons, "targets": targets, "competitions": competitions,
                                     "engine": "ml" if ml_oos is not None else "statistical"})))

    def work():
        try:
            def prog(done, total, msg):
                db.execute("UPDATE backtest_runs SET progress=? WHERE id=?", (f"{done}/{total} · {msg}", run_id))
            res = run_backtest(store, settings, seasons, targets, competitions, prog, ml_oos)
            db.execute("UPDATE backtest_runs SET status='ok', finished_at=?, result=? WHERE id=?",
                       (iso(now_utc()), json.dumps(res), run_id))
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            db.execute("UPDATE backtest_runs SET status='failed', finished_at=?, error=? WHERE id=?",
                       (iso(now_utc()), str(exc), run_id))
        finally:
            _job_lock.release()

    threading.Thread(target=work, daemon=True).start()
    return run_id


def latest_backtest(db: Database) -> dict | None:
    with db.tx() as c:
        c.execute(SCHEMA)
    row = db.one("SELECT * FROM backtest_runs ORDER BY id DESC LIMIT 1")
    if row and row.get("result"):
        row["result"] = json.loads(row["result"])
    if row and row.get("params"):
        row["params"] = json.loads(row["params"])
    return row
