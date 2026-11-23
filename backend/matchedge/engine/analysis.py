"""Analysis orchestrator: builds the full, deterministic research object for a fixture."""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .. import config
from ..db import Database
from ..importer import dataset_age_days
from ..timeutil import local_input_to_utc, local_str, parse_iso, time_certainty, to_local
from . import explain
from .countmodel import count_model
from .data import MatchStore
from .markets import evaluate_candidates
from .poisson import fit_match, league_baseline
from .rejection import RESULT_MARKETS, closely_matched, decide, evaluate_rules
from .scoring import data_quality, research_score, risk_assessment
from .stats import team_profile

INELIGIBLE_STATUSES = {"finished", "postponed", "cancelled", "abandoned", "missing_from_source"}


class Engine:
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.RLock()
        self.store: MatchStore | None = None
        self.strengths: dict | None = None
        self.version = 0
        self._cache: dict[str, dict] = {}
        self.refresh()

    # ------------------------------------------------------------------ state
    def refresh(self) -> None:
        with self._lock:
            matches = self.db.query("SELECT * FROM matches")
            settings = self.db.get_settings()
            if settings.get("history_enabled", True):
                from ..history import history_rows
                matches = matches + history_rows(self.db)
            comps = self.db.query("SELECT * FROM competitions")
            for c in comps:
                c["coverage"] = json.loads(c["coverage"]) if c.get("coverage") else {}
            self.store = MatchStore.build(matches, comps)
            from .strength import fit_strengths
            try:
                self.strengths = fit_strengths(self.store, settings)
            except Exception:  # noqa: BLE001 - never block the app; cross-league falls back to shrinkage
                self.strengths = None
            self.invalidate()

    def invalidate(self) -> None:
        with self._lock:
            self.version += 1
            self._cache.clear()

    def latest_import(self) -> dict | None:
        return self.db.one("SELECT * FROM import_runs WHERE status='ok' ORDER BY id DESC LIMIT 1")

    def dataset_age(self) -> float | None:
        run = self.latest_import()
        return dataset_age_days(run["dataset_generated_utc"]) if run else None

    def overrides(self) -> dict[str, dict]:
        return {r["match_id"]: r for r in self.db.query("SELECT * FROM fixture_overrides")}

    # ------------------------------------------------------------------ fixtures
    def fixture_view(self, m: dict, ov: dict | None, settings: dict, now: datetime | None = None,
                     counts: dict | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        zone = str(settings["timezone"])
        comp = self.store.competitions.get(m["competition"], {})
        ds_utc = None
        if m.get("time"):
            from ..timeutil import dataset_kickoff_utc
            ds_utc = dataset_kickoff_utc(m["date"], m["time"])
        snap_utc = m["kickoff_dt"] if m.get("time_source", "").startswith("snapshot") else None
        label, notes = time_certainty(m["date"], m.get("time"), snap_utc, ds_utc, zone)
        kickoff = m["kickoff_dt"]
        if ov and ov.get("kickoff_local"):
            kickoff = local_input_to_utc(ov["kickoff_local"], zone)
            label, notes = "user_corrected", [f"Kickoff corrected by you ({ov['kickoff_local']} {zone})."]
        status = (ov or {}).get("status") or m["status"]
        verified = bool((ov or {}).get("verified"))
        eligible, pre = prematch_status(status, kickoff, m["date"], now, zone, verified)
        counts = counts or {}
        return {
            "id": m["id"], "competition": m["competition"], "competition_name": comp.get("name", m["competition"]),
            "country": comp.get("country"), "kind": comp.get("kind"), "gw": m.get("gw"),
            "date": m["date"], "home": m["home"], "away": m["away"],
            "home_id": m["home_key"], "away_id": m["away_key"],
            "kickoff_utc": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ") if kickoff else None,
            "kickoff_local": local_str(kickoff, zone) if kickoff else None,
            "local_date": to_local(kickoff, zone).date().isoformat() if kickoff else m["date"],
            "timezone": zone, "time_certainty": label, "time_notes": notes,
            "dataset_status": m["status"], "status": status, "prematch_eligible": eligible, "prematch_status": pre,
            "verified": verified, "verification_url": (ov or {}).get("verification_url"),
            "override_note": (ov or {}).get("note"),
            "score": None if m.get("ft_home") is None else f"{m['ft_home']}-{m['ft_away']}",
            "manual_odds": counts.get("manual", 0), "snapshot_odds": counts.get("snapshot", 0),
            "research_count": counts.get("research", 0),
            "source": "open-matchday" + (f" ({m['source']})" if m.get("source") else ""),
        }

    def list_fixtures(self, date_from: str, date_to: str, competitions: list[str] | None = None,
                      team: str | None = None, include_ineligible: bool = True) -> list[dict]:
        settings = self.db.get_settings()
        ov = self.overrides()
        counts = self._counts()
        start = (date.fromisoformat(date_from) - timedelta(days=1)).isoformat()
        end = (date.fromisoformat(date_to) + timedelta(days=1)).isoformat()
        out = []
        team_l = (team or "").strip().lower()
        for m in self.store.matches.values():
            if m["id"].startswith("FD|") or not (start <= m["date"] <= end):
                continue
            if competitions and m["competition"] not in competitions:
                continue
            if team_l and team_l not in m["home"].lower() and team_l not in m["away"].lower():
                continue
            v = self.fixture_view(m, ov.get(m["id"]), settings, counts=counts.get(m["id"]))
            if not (date_from <= v["local_date"] <= date_to):
                continue
            if not include_ineligible and not v["prematch_eligible"]:
                continue
            out.append(v)
        out.sort(key=lambda v: (v["kickoff_utc"] or v["date"] + "T99", v["competition"]))
        return out

    def _counts(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for r in self.db.query("SELECT match_id, source, COUNT(*) n FROM odds GROUP BY match_id, source"):
            out.setdefault(r["match_id"], {})["manual" if r["source"] == "manual" else "snapshot"] = r["n"]
        for r in self.db.query("SELECT match_id, COUNT(*) n FROM research_sources GROUP BY match_id"):
            out.setdefault(r["match_id"], {})["research"] = r["n"]
        return out

    # ------------------------------------------------------------------ analysis
    def analyze(self, match_id: str, use_cache: bool = True) -> dict:
        with self._lock:
            if use_cache and match_id in self._cache:
                return self._cache[match_id]
            result = self._analyze(match_id)
            self._cache[match_id] = result
            return result

    def _select_history(self, team_id: str, comp: str, before: date, settings: dict,
                        season: str) -> tuple[list, list, bool]:
        """(rows for the model, current-season rows for descriptive stats, same-competition flag).

        League fixtures use the same competition; the model also sees the previous season's matches in
        that competition (down-weighted). Cups/UEFA use all of the current season's competitions.
        """
        from .data import prev_season
        kind = self.store.competitions.get(comp, {}).get("kind")
        if kind == "league":
            cur = self.store.history(team_id, before, {comp}, {season})
            if len(cur) >= int(settings["min_matches_model"]) or settings.get("history_enabled", True):
                model = self.store.history(team_id, before, {comp}, {season, prev_season(season)})
                if len(cur) >= int(settings["min_matches_model"]) or len(model) >= int(settings["min_matches_model"]) + 4:
                    return model, cur, True
        cur = self.store.history(team_id, before, None, {season})
        return cur, cur, False

    def _analyze(self, match_id: str) -> dict:
        store = self.store
        m = store.matches.get(match_id)
        if m is None:
            raise KeyError(match_id)
        settings = self.db.get_settings()
        ov = self.overrides().get(match_id)
        counts = self._counts().get(match_id)
        fixture = self.fixture_view(m, ov, settings, counts=counts)
        comp = m["competition"]
        before = m["date_obj"]
        season = m.get("season") or config.SEASON
        home_model, home_rows, same_h = self._select_history(m["home_key"], comp, before, settings, season)
        away_model, away_rows, same_a = self._select_history(m["away_key"], comp, before, settings, season)
        kind = store.competitions.get(comp, {}).get("kind")
        prim_h, prim_a = store.primary_league(m["home_key"], season), store.primary_league(m["away_key"], season)
        cross_league = kind != "league" and (prim_h is None or prim_a is None or prim_h != prim_a)
        unlinked = [t for t, tid in ((m["home"], m["home_key"]), (m["away"], m["away_key"]))
                    if tid.startswith("UEFA:")]
        min_stat = int(settings["min_matches_stat"])
        home_p = team_profile(home_rows, "H", min_stat)
        away_p = team_profile(away_rows, "A", min_stat)

        strength = None
        if cross_league and kind == "international" and prim_h and prim_a and self.strengths \
                and prim_h in self.strengths["index"] and prim_a in self.strengths["index"]:
            from .data import prev_season
            from .strength import strength_delta
            dom_h = store.history(m["home_key"], before, {prim_h}, {season, prev_season(season)})
            dom_a = store.history(m["away_key"], before, {prim_a}, {season, prev_season(season)})
            if sum(r.season == season for r in dom_h) >= 3 and sum(r.season == season for r in dom_a) >= 3:
                strength = strength_delta(self.strengths, prim_h, prim_a)
                home_model, away_model = dom_h, dom_a
        goals = fit_match(store, home_model, away_model, comp, before, settings, cross_league, season, strength)
        corners = count_model("corners", store, home_rows, away_rows, comp, before, settings)
        cards = count_model("cards", store, home_rows, away_rows, comp, before, settings)
        goals_d = goals.to_dict()

        odds_rows = self.db.query("SELECT * FROM odds WHERE match_id=?", (match_id,))
        research = self.db.query("SELECT * FROM research_sources WHERE match_id=? ORDER BY checked_at DESC",
                                 (match_id,))
        if not settings["allow_snapshot_odds"]:
            odds_rows = [o for o in odds_rows if o["source"] == "manual"]
        candidates = evaluate_candidates(home=m["home"], away=m["away"], home_rows=home_rows,
                                         away_rows=away_rows, goals=goals, corners=corners, cards=cards,
                                         odds_rows=odds_rows, research=research, settings=settings,
                                         cross_league=cross_league)
        if closely_matched(goals_d, home_p, away_p, settings):
            for c in candidates:
                if c["market"] in RESULT_MARKETS and c["qualifies"]:
                    c["qualifies"] = False
                    c["gates_failed"].append("Teams closely matched: match-result markets excluded.")
            candidates.sort(key=lambda c: (c["qualifies"], c["score"]["evidence"]), reverse=True)

        age = self.dataset_age()
        base = league_baseline(store, comp, before, int(settings["min_league_matches"]))
        coverage = store.competitions.get(comp, {}).get("coverage", {})
        if not same_h or not same_a:
            # blend coverage of the competitions actually used
            coverage = _sample_coverage(home_rows + away_rows)
        rscore = research_score(home_p, away_p, goals_d, corners, cards, base.home + base.away, age, before,
                                home_rows[0].date if home_rows else None, away_rows[0].date if away_rows else None)
        dq = data_quality(home_p, away_p, coverage, age, fixture["time_certainty"], fixture["verified"],
                          same_h and same_a, bool(unlinked) and min(len(home_rows), len(away_rows)) <
                          int(settings["min_matches_model"]), settings)
        factors = evaluate_rules(home=m["home"], away=m["away"], home_p=home_p, away_p=away_p, goals=goals_d,
                                 candidates=candidates, research=research, settings=settings,
                                 dataset_age_days=age, fixture_date=before,
                                 home_last=home_rows[0].date if home_rows else None,
                                 away_last=away_rows[0].date if away_rows else None,
                                 cross_league=cross_league, unlinked=unlinked,
                                 time_label=fixture["time_certainty"], verified=fixture["verified"])
        if not fixture["prematch_eligible"]:
            factors.insert(0, {"code": "not_prematch", "severity": "high", "action": "reject",
                               "message": f"Not available for a pre-match ticket: {fixture['prematch_status']}."})
        status = "ineligible" if not fixture["prematch_eligible"] else decide(factors)
        risk = risk_assessment([f for f in factors if f["action"] != "info" or f["severity"] != "low"])

        qualifying = [c for c in candidates if c["qualifies"]]
        recommendation = None
        if qualifying and status != "rejected" and status != "ineligible":
            best = qualifying[0]
            recommendation = {"key": best["key"], "label": best["label"],
                              "comparison": explain.compare_markets(best, candidates)}
        for c in candidates:
            c["confidence"] = confidence(c, dq["score"], risk["level"], settings)
            if cross_league and c["confidence"] == "high":
                c["confidence"] = "medium"  # cross-league strength comparison is approximate

        analysis = {
            "fixture": fixture,
            "samples": {
                "home": _sample_info(home_rows, same_h, prim_h, m["home_key"]),
                "away": _sample_info(away_rows, same_a, prim_a, m["away_key"]),
                "cross_league": cross_league, "unlinked": unlinked,
            },
            "league": {"code": comp, "avg_home_goals": round(base.home, 2), "avg_away_goals": round(base.away, 2),
                       "avg_total_goals": round(base.home + base.away, 2), "n_matches": base.n,
                       "baseline_source": base.source, "coverage": store.competitions.get(comp, {}).get("coverage", {})},
            "profiles": {"home": home_p, "away": away_p},
            "model": goals_d, "corners": corners, "cards": cards,
            "candidates": candidates,
            "recommendation": recommendation,
            "research_score": rscore, "data_quality": dq, "risk": risk,
            "decision": {"status": status, "factors": factors,
                         "missing_information": missing_information(home_p, away_p, corners, cards, goals_d,
                                                                    odds_rows, research, fixture),
                         "alternatives": [c["label"] for c in qualifying[1:4]]},
            "evidence": research,
            "dataset": {"generated_utc": (self.latest_import() or {}).get("dataset_generated_utc"),
                        "age_days": age, "attribution": config.ATTRIBUTION},
            "settings_used": {k: settings[k] for k in ("recency_half_life", "prior_weight", "goal_cap",
                                                        "min_matches_model", "min_leg_probability",
                                                        "min_selection_score")},
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        analysis["explanation"] = explain.match_explanation(analysis)
        return analysis

    def summary(self, match_id: str) -> dict:
        a = self.analyze(match_id)
        rec = next((c for c in a["candidates"] if a["recommendation"] and c["key"] == a["recommendation"]["key"]), None)
        return {
            "fixture": a["fixture"], "status": a["decision"]["status"],
            "reasons": [f["message"] for f in a["decision"]["factors"] if f["action"] in ("reject", "flag")],
            "factors": a["decision"]["factors"],
            "recommendation": None if rec is None else _brief(rec),
            "qualifying": [_brief(c) for c in a["candidates"] if c["qualifies"]][:6],
            "research_score": a["research_score"]["score"], "data_quality": a["data_quality"]["score"],
            "data_quality_label": a["data_quality"]["label"], "risk_level": a["risk"]["level"],
            "expected_goals": (a["model"] or {}).get("expected_goals"),
            "missing_information": a["decision"]["missing_information"],
            "alternatives": a["decision"]["alternatives"],
        }

    def analyze_window(self, date_from: str, date_to: str, competitions: list[str] | None = None,
                       eligible_only: bool = True, limit: int = 400) -> list[dict]:
        fixtures = self.list_fixtures(date_from, date_to, competitions, include_ineligible=not eligible_only)
        return [self.summary(f["id"]) for f in fixtures[:limit]]


# ---------------------------------------------------------------------- helpers
def prematch_status(status: str, kickoff: datetime | None, date_str: str, now: datetime, zone: str,
                    verified: bool) -> tuple[bool, str]:
    if status == "finished":
        return False, "completed"
    if status in ("postponed", "cancelled", "abandoned"):
        return False, status
    if status == "missing_from_source" and not verified:
        return False, "removed from the latest dataset (possibly postponed or moved) — verify officially"
    if kickoff is not None:
        if now >= kickoff:
            hours = (now - kickoff).total_seconds() / 3600
            return False, "started / in progress" if hours < 2.5 else "kickoff passed — result not yet imported"
        return True, "scheduled"
    from ..timeutil import tz
    today = now.astimezone(tz(zone)).date().isoformat()
    if date_str < today:
        return False, "date passed — result not yet imported"
    if date_str == today:
        return False, "kickoff time unknown and the match is today — set the time manually to include it"
    return True, "scheduled (kickoff time unknown)"


def confidence(c: dict, dq: float, risk_level: str, settings: dict) -> str:
    if not c["supported"]:
        return "none"
    s = c["score"]["total"] if c["price"] else c["score"]["evidence"] + 7.5
    if s >= float(settings["strong_selection_score"]) and dq >= 70 and risk_level != "high":
        return "high"
    if s >= float(settings["min_selection_score"]) and dq >= 50:
        return "medium"
    return "low"


def _brief(c: dict) -> dict:
    return {k: c[k] for k in ("key", "label", "market", "market_name", "family", "selection", "line",
                              "probability_pct", "range_pct", "price", "implied_probability", "edge",
                              "tier", "qualifies", "needs_price", "win_probability", "void_probability")} | {
        "score": c["score"]["total"], "evidence": c["score"]["evidence"], "confidence": c.get("confidence")}


def _sample_info(rows, same_comp: bool, primary: str | None, team_id: str) -> dict:
    comps: dict[str, int] = {}
    for r in rows:
        comps[r.competition] = comps.get(r.competition, 0) + 1
    return {"team_id": team_id, "n": len(rows), "same_competition": same_comp, "primary_league": primary,
            "competitions": comps, "last_played": rows[0].date.isoformat() if rows else None,
            "first_in_sample": rows[-1].date.isoformat() if rows else None}


def _sample_coverage(rows) -> dict:
    n = len(rows)
    if not n:
        return {}

    def share(fn):
        return round(sum(1 for r in rows if fn(r) is not None) / n, 3)

    return {"half_time": share(lambda r: r.f["ht_goals"]), "shots": share(lambda r: r.f["shots"]),
            "corners": share(lambda r: r.f["corners"]), "cards": share(lambda r: r.f["yellow"])}


def missing_information(home_p, away_p, corners, cards, goals, odds_rows, research, fixture) -> list[str]:
    out = []
    if not goals.get("available"):
        out.append(goals.get("reason") or "Goal model unavailable.")
    if not corners.get("available"):
        out.append(corners.get("reason") or "Corner statistics unavailable.")
    if not cards.get("available"):
        out.append(cards.get("reason") or "Card statistics unavailable.")
    if goals.get("available") and not (goals.get("first_half") or {}).get("available"):
        out.append("Half-time scores unavailable: first-half markets not modelled.")
    if not any(o["source"] == "manual" for o in odds_rows):
        out.append("No manually entered odds for this match.")
    if not any(r["category"] in ("lineup", "injury") for r in research):
        out.append("Lineups and injuries: not in the dataset and not researched.")
    out.append("Referee: not in the dataset.")
    if not fixture["verified"]:
        out.append("Fixture not verified against the official competition website.")
    if fixture["time_certainty"] in ("unknown", "uncertain", "conflict"):
        out.append("Kickoff time uncertain.")
    return out
