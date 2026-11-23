"""Final accumulator report assembly."""
from __future__ import annotations

from datetime import datetime, timezone

from . import explain
from .accumulator import build, evaluate_ticket, final_opinion, leg_from_candidate, ticket_pool


def _selection_detail(engine, leg: dict) -> dict:
    a = engine.analyze(leg["match_id"])
    cand = next(c for c in a["candidates"] if c["key"] == leg["key"])
    risks = explain.failure_modes(cand, a)
    return {
        **{k: leg[k] for k in ("match_id", "key", "match_label", "competition_name", "kickoff_local", "label",
                                "market_name", "odds", "bookmaker", "odds_source", "odds_checked_at",
                                "probability_pct", "range_pct", "implied_probability", "confidence", "tier",
                                "score", "time_certainty", "verified")},
        "data_quality": a["data_quality"]["score"], "data_quality_label": a["data_quality"]["label"],
        "match_status": a["decision"]["status"],
        "reasoning": explain.selection_reasoning(cand, a),
        "main_risk": risks[1] if len(risks) > 1 else (risks[0] if risks else "No specific risk identified."),
        "risks": risks,
        "flags": [f["message"] for f in a["decision"]["factors"] if f["action"] == "flag"],
    }


def _summary(engine, legs: list[dict], ev: dict, target: float) -> dict:
    run = engine.latest_import() or {}
    return {
        "requested_odds": target, "combined_odds": ev["combined_odds"], "n_selections": ev["n_selections"],
        "competitions": sorted({leg["competition_name"] for leg in legs}),
        "dates": sorted({leg["local_date"] for leg in legs}),
        "price_sources": ev["price_sources"],
        "price_note": "Manually entered prices are what you typed in; they are not verified live odds. "
                      "Dataset snapshot prices are Flashscore pre-match quotes captured at the time shown.",
        "data_freshness": {"dataset_generated_utc": run.get("dataset_generated_utc"),
                           "age_days": engine.dataset_age()},
        "model_probability_all_win": ev["model_probability_all_win"],
        "bookmaker_implied_probability": ev["bookmaker_implied_probability"],
        "model_probability_note": ev["model_probability_note"],
        "target_reached": ev["target_reached"],
    }


def biggest_risks(details: list[dict]) -> list[dict]:
    ranked = sorted(details, key=lambda d: ((d["probability_pct"] or 0), d["score"]))
    return [{"match_label": d["match_label"], "label": d["label"], "probability_pct": d["probability_pct"],
             "score": d["score"], "why": d["main_risk"]} for d in ranked[:3]]


def build_report(engine, *, date_from: str, date_to: str, target: float, competitions=None,
                 legs_in: list[dict] | None = None, max_legs: int | None = None) -> dict:
    settings = engine.db.get_settings()
    max_legs = int(max_legs or settings["max_legs"])
    summaries = engine.analyze_window(date_from, date_to, competitions, eligible_only=True)
    padded = alt = None
    good: list = []
    weak: list = []
    if legs_in is None:
        good, weak = ticket_pool(summaries, engine.analyze, settings)
        built = build(good, weak, target, max_legs)
        legs, padded, alt = built["main"], built["padded"], built["alternative"]
        limit_hit = built["limit_hit"]
        mode = "auto"
    else:
        legs = legs_in
        mode = "manual"
        limit_hit = False
        if len(legs) >= 3:
            alt = sorted(legs, key=lambda x: x["score"], reverse=True)[:max(2, min(4, len(legs) // 2))]
    for x in legs + (padded or []) + (alt or []):
        x.pop("_rank", None)
    ev = evaluate_ticket(legs, target)
    pev = evaluate_ticket(padded, target) if padded else None
    aev = evaluate_ticket(alt, target) if alt else None
    details = [_selection_detail(engine, leg) for leg in legs]
    chosen = {leg["match_id"] for leg in legs}
    rejected = [{"match_label": f"{s['fixture']['home']} vs {s['fixture']['away']}",
                 "match_id": s["fixture"]["id"], "competition": s["fixture"]["competition_name"],
                 "kickoff_local": s["fixture"]["kickoff_local"], "status": s["status"],
                 "reasons": s["reasons"][:4], "missing": s["missing_information"][:4],
                 "alternatives": s["alternatives"]}
                for s in summaries if s["fixture"]["id"] not in chosen and s["status"] in ("rejected", "flagged")]
    not_selected = [s for s in summaries if s["fixture"]["id"] not in chosen and s["status"] == "candidate"]
    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode, "window": {"from": date_from, "to": date_to, "competitions": competitions or "all"},
        "analysed_matches": len(summaries),
        "summary": _summary(engine, legs, ev, target),
        "evaluation": ev,
        "selections": details,
        "legs": legs,
        "rejected_matches": rejected,
        "candidates_not_used": [{"match_label": f"{s['fixture']['home']} vs {s['fixture']['away']}",
                                 "match_id": s["fixture"]["id"],
                                 "reason": "No priced qualifying selection yet — enter odds to use it."
                                 if not s["recommendation"] or not s["recommendation"]["price"] else
                                 "Not needed to reach the target, or a better-ranked selection was preferred.",
                                 "recommendation": s["recommendation"]} for s in not_selected][:60],
        "biggest_risks": biggest_risks(details),
        "padded_version": None if not padded else {
            "legs": padded, "evaluation": pev,
            "warning": "Shown only to make the trade-off visible. These extra legs are weak; not recommended."},
        "alternative_ticket": None if not alt else {"legs": alt, "evaluation": aev},
        "final_opinion": final_opinion(ev, target, pev, aev, limit_hit, max_legs),
        "pool": {"well_supported": len(good) if legs_in is None else None,
                 "weak": len(weak) if legs_in is None else None,
                 "selection_rule": "Only well-supported legs (strong/acceptable tier, high/medium confidence). Among "
                                   "them, legs are chosen to give the whole ticket the best model-estimated chance of "
                                   "reaching the target (lowest probability cost per unit of odds)."},
        "attribution": "Data: open-matchday (non-commercial). Estimates are model outputs, not verified probabilities.",
    }
    return report


def legs_from_request(engine, items: list[dict]) -> list[dict]:
    """Resolve [{match_id, key}] into full legs using current analysis and prices."""
    legs = []
    for it in items:
        a = engine.analyze(it["match_id"])
        cand = next((c for c in a["candidates"] if c["key"] == it["key"]), None)
        if cand is None:
            raise KeyError(f"Selection {it['key']} not available for {it['match_id']}")
        legs.append(leg_from_candidate(a, cand))
    return legs
