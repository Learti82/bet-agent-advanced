"""Prediction tracking: settlement against imported results and performance summaries.

Settlement uses only real result data. If the statistic a market needs is missing (e.g. corners in
a league without corner coverage), the prediction stays pending and is marked for manual
settlement — it is never guessed.
"""
from __future__ import annotations

import math
from datetime import timedelta

from ..db import Database
from ..timeutil import iso, now_utc, parse_iso


def settle_market(market: str, selection: str, line: float | None, m: dict) -> str | None:
    """Return won/lost/void/half_won/half_lost, or None if the required data is missing."""
    h, a = m.get("ft_home"), m.get("ft_away")
    if h is None or a is None:
        return None

    def ou(total: int | None) -> str | None:
        if total is None or line is None:
            return None
        return _line_result((total - line) if selection == "over" else (line - total), line)

    if market == "1X2":
        res = "home" if h > a else "draw" if h == a else "away"
        return "won" if res == selection else "lost"
    if market == "DC":
        res = "home" if h > a else "draw" if h == a else "away"
        return "won" if {"1X": res != "away", "X2": res != "home", "12": res != "draw"}[selection] else "lost"
    if market == "DNB":
        if h == a:
            return "void"
        return "won" if (h > a) == (selection == "home") else "lost"
    if market == "BTTS":
        return "won" if (h > 0 and a > 0) == (selection == "yes") else "lost"
    if market == "OU":
        return ou(h + a)
    if market == "TG_HOME":
        return ou(h)
    if market == "TG_AWAY":
        return ou(a)
    if market == "1H_OU":
        hh, ha = m.get("ht_home"), m.get("ht_away")
        return None if hh is None or ha is None else ou(hh + ha)
    if market == "CORNERS_OU":
        ch, ca = m.get("home_corners"), m.get("away_corners")
        return None if ch is None or ca is None else ou(ch + ca)
    if market == "CARDS_OU":
        vals = [m.get(k) for k in ("home_yellow", "away_yellow", "home_red", "away_red")]
        return None if any(v is None for v in vals) else ou(sum(vals))
    if market == "AH" and line is not None:
        margin = (h - a if selection == "home" else a - h)
        return _line_result(margin + line, line)
    return None


def _line_result(margin: float, line: float) -> str:
    frac = round(abs(line) * 4) % 4
    if frac in (1, 3):  # quarter line: split stake on the two neighbouring lines
        r1 = _line_result(margin - 0.25, 0.5)
        r2 = _line_result(margin + 0.25, 0.5)
        pair = {r1, r2}
        if pair == {"won"}:
            return "won"
        if pair == {"lost"}:
            return "lost"
        if pair == {"won", "void"}:
            return "half_won"
        if pair == {"lost", "void"}:
            return "half_lost"
    return "won" if margin > 1e-9 else "lost" if margin < -1e-9 else "void"


def find_result(db: Database, pred: dict) -> dict | None:
    row = db.one("SELECT * FROM matches WHERE id=? AND status='finished'", (pred["match_id"],))
    if row:
        return row
    ko = parse_iso(pred.get("kickoff_utc"))
    lo = (ko - timedelta(days=2)).date().isoformat() if ko else "0000"
    hi = (ko + timedelta(days=45)).date().isoformat() if ko else "9999"
    return db.one("SELECT * FROM matches WHERE status='finished' AND competition=? AND home_key=? AND away_key=? "
                  "AND date BETWEEN ? AND ? ORDER BY date LIMIT 1",
                  (pred["competition"], pred["home_key"], pred["away_key"], lo, hi))


def auto_settle(db: Database) -> dict:
    pending = db.query("SELECT * FROM predictions WHERE status='pending'")
    settled, manual = 0, 0
    for p in pending:
        m = find_result(db, p)
        if not m:
            continue
        res = settle_market(p["market"], p["selection"], p["line"], m)
        if res is None:
            manual += 1
            db.execute("UPDATE predictions SET result_detail=? WHERE id=?",
                       (f"Result {m['ft_home']}-{m['ft_away']} imported, but the statistic this market needs is "
                        "missing — settle manually.", p["id"]))
            continue
        detail = f"FT {m['ft_home']}-{m['ft_away']}"
        if m.get("ht_home") is not None:
            detail += f" (HT {m['ht_home']}-{m['ht_away']})"
        if m.get("home_corners") is not None:
            detail += f", corners {m['home_corners']}-{m['away_corners']}"
        db.execute("UPDATE predictions SET status=?, settled_at=?, result_detail=?, settled_by='auto' WHERE id=?",
                   (res, iso(now_utc()), detail, p["id"]))
        settled += 1
    return {"checked": len(pending), "settled": settled, "needs_manual": manual}


ODDS_BUCKETS = [(1.0, 1.5), (1.5, 1.8), (1.8, 2.2), (2.2, 3.0), (3.0, 1000.0)]
FAMILY_OF_MARKET = {"1X2": "result", "DC": "result", "DNB": "result", "AH": "handicap", "OU": "goals",
                    "BTTS": "goals", "TG_HOME": "goals", "TG_AWAY": "goals", "1H_OU": "goals",
                    "CORNERS_OU": "corners", "CARDS_OU": "cards"}


def _group(rows: list[dict]) -> dict:
    settled = [r for r in rows if r["status"] in ("won", "lost", "void", "half_won", "half_lost")]
    decided = [r for r in settled if r["status"] != "void"]
    won = sum(1 for r in decided if r["status"] == "won") + 0.5 * sum(1 for r in decided if r["status"] == "half_won")
    profit = 0.0
    for r in settled:
        o = r["odds"] or 1.0
        profit += {"won": o - 1, "half_won": (o - 1) / 2, "void": 0.0, "half_lost": -0.5, "lost": -1.0}[r["status"]]
    with_p = [r for r in decided if r["model_probability"] is not None]
    brier = (sum((r["model_probability"] - (1.0 if r["status"] in ("won", "half_won") else 0.0)) ** 2
                 for r in with_p) / len(with_p)) if with_p else None
    return {
        "total": len(rows), "settled": len(settled), "pending": len(rows) - len(settled),
        "won": won, "lost": len(decided) - won, "void": len(settled) - len(decided),
        "hit_rate": round(won / len(decided), 3) if decided else None,
        "avg_odds": round(sum(r["odds"] or 0 for r in settled) / len(settled), 2) if settled else None,
        "avg_model_probability": round(sum(r["model_probability"] for r in with_p) / len(with_p), 3) if with_p else None,
        "flat_stake_profit_units": round(profit, 2),
        "roi": round(profit / len(settled), 3) if settled else None,
        "brier_score": None if brier is None else round(brier, 4),
    }


def performance(db: Database) -> dict:
    rows = db.query("SELECT * FROM predictions ORDER BY created_at")
    overall = _group(rows)
    by_family = {}
    for fam in ("goals", "corners", "cards", "result", "handicap"):
        by_family[fam] = _group([r for r in rows if FAMILY_OF_MARKET.get(r["market"]) == fam])
    by_odds = []
    for lo, hi in ODDS_BUCKETS:
        g = _group([r for r in rows if r["odds"] and lo <= r["odds"] < hi])
        by_odds.append({"range": f"{lo:.2f}–{hi:.2f}" if hi < 100 else f"{lo:.2f}+"} | g)
    calibration = []
    for lo in range(50, 100, 5):
        bucket = [r for r in rows if r["model_probability"] is not None and lo <= 100 * r["model_probability"] < lo + 5
                  and r["status"] in ("won", "lost", "half_won", "half_lost")]
        if not bucket:
            continue
        hits = sum(1 for r in bucket if r["status"] in ("won", "half_won"))
        n = len(bucket)
        se = math.sqrt(max(1e-9, (hits / n) * (1 - hits / n) / n))
        calibration.append({"bucket": f"{lo}–{lo + 5}%", "n": n,
                            "predicted": round(sum(r["model_probability"] for r in bucket) / n, 3),
                            "actual": round(hits / n, 3), "actual_low": round(max(0, hits / n - 1.96 * se), 3),
                            "actual_high": round(min(1, hits / n + 1.96 * se), 3)})
    tickets = db.query("SELECT id, created_at, name, target_odds, combined_odds, n_selections, kind FROM tickets "
                       "ORDER BY id DESC")
    tstat = []
    for t in tickets:
        legs = [r for r in rows if r["ticket_id"] == t["id"]]
        sts = {r["status"] for r in legs}
        status = ("lost" if sts & {"lost"} else "pending" if "pending" in sts else
                  "won" if legs else "empty")
        tstat.append(t | {"status": status})
    n_settled = overall["settled"]
    note = ("Fewer than 50 settled selections: these numbers are dominated by luck and say nothing reliable "
            "about the model yet." if n_settled < 50 else
            "Sample is still modest; compare predicted vs actual with the confidence bands before drawing conclusions."
            if n_settled < 300 else "Larger sample; calibration bands are becoming informative.")
    return {"overall": overall, "by_family": by_family, "by_odds": by_odds, "calibration": calibration,
            "tickets": tstat, "sample_note": note,
            "disclaimer": "Historical tracking only. No claim is made that the model is improving unless the data shows it."}
