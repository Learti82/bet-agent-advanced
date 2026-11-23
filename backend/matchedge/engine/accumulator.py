"""Accumulator calculator, validator and builder.

Combined decimal odds = o₁ × o₂ × … × oₙ.

Rules:
* duplicates are rejected; two legs from the same match are rejected (strongly correlated —
  bookmakers price those as bet builders, not accumulators);
* the same team in two different matches, and legs in the same competition on the same day,
  are reported as (weaker) correlations;
* started / completed / postponed fixtures cannot be on a pre-match ticket;
* the builder only uses selections that pass the evidence gates and stops when the target is
  reached — it never pads a ticket with weak selections to reach the target. If the target is
  unreachable with well-supported legs, it says so and shows what padding would cost.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Callable

from ..timeutil import parse_iso


def combined_odds(odds: list[float]) -> float:
    if any(o is None or o <= 1.0 for o in odds):
        raise ValueError("Every decimal price must be greater than 1.00")
    return math.prod(odds) if odds else 1.0


def leg_from_candidate(analysis: dict, cand: dict) -> dict:
    fx = analysis["fixture"]
    price = cand.get("price") or {}
    return {
        "match_id": fx["id"], "key": cand["key"], "label": cand["label"],
        "match_label": f"{fx['home']} vs {fx['away']}", "home": fx["home"], "away": fx["away"],
        "home_id": fx["home_id"], "away_id": fx["away_id"],
        "competition": fx["competition"], "competition_name": fx["competition_name"],
        "kickoff_utc": fx["kickoff_utc"], "kickoff_local": fx["kickoff_local"], "local_date": fx["local_date"],
        "time_certainty": fx["time_certainty"], "verified": fx["verified"],
        "prematch_eligible": fx["prematch_eligible"], "prematch_status": fx["prematch_status"],
        "market": cand["market"], "market_name": cand["market_name"], "family": cand["family"],
        "selection": cand["selection"], "line": cand["line"],
        "odds": price.get("odds"), "bookmaker": price.get("bookmaker"), "odds_source": price.get("source"),
        "odds_checked_at": price.get("checked_at"),
        "probability": cand.get("win_probability"), "void_probability": cand.get("void_probability") or 0.0,
        "probability_pct": cand.get("probability_pct"), "range_pct": cand.get("range_pct"),
        "implied_probability": cand.get("implied_probability"), "edge": cand.get("edge"),
        "score": cand["score"]["total"], "evidence": cand["score"]["evidence"], "tier": cand["tier"],
        "confidence": cand.get("confidence"), "qualifies": cand["qualifies"],
        "gates_failed": cand["gates_failed"], "data_quality": analysis["data_quality"]["score"],
        "match_status": analysis["decision"]["status"], "risk_level": analysis["risk"]["level"],
    }


def evaluate_ticket(legs: list[dict], target: float | None = None,
                    now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    errors: list[str] = []
    warnings: list[str] = []
    correlations: list[dict] = []

    seen_keys: set[tuple] = set()
    by_match: dict[str, list[dict]] = {}
    for leg in legs:
        k = (leg["match_id"], leg["key"])
        if k in seen_keys:
            errors.append(f"Duplicate selection: {leg['label']} ({leg['match_label']}).")
        seen_keys.add(k)
        by_match.setdefault(leg["match_id"], []).append(leg)
        if leg.get("odds") is None:
            errors.append(f"No price for {leg['label']} ({leg['match_label']}). Enter the bookmaker odds first.")
        if not leg.get("prematch_eligible", True):
            errors.append(f"{leg['match_label']} cannot be on a pre-match ticket: {leg.get('prematch_status')}.")
        else:
            ko = parse_iso(leg.get("kickoff_utc"))
            if ko is not None and ko <= now:
                errors.append(f"{leg['match_label']} has already kicked off.")
        if leg.get("match_status") == "rejected":
            warnings.append(f"{leg['match_label']} was rejected by the analysis — see the Rejected matches page.")
        if not leg.get("qualifies", True):
            warnings.append(f"{leg['label']} ({leg['match_label']}) fails evidence gates: "
                            f"{'; '.join(leg.get('gates_failed') or [])}")
        if leg.get("tier") == "weak":
            warnings.append(f"Weak selection: {leg['label']} ({leg['match_label']}), score {leg.get('score')}.")
        if leg.get("odds_source") == "dataset_snapshot":
            warnings.append(f"Price for {leg['label']} is a dataset snapshot ({leg.get('bookmaker')}, "
                            f"{leg.get('odds_checked_at')}), not a live price. Re-check it at the bookmaker.")
        if not leg.get("verified"):
            warnings.append(f"{leg['match_label']}: fixture not verified against an official source.")
        if leg.get("time_certainty") in ("unknown", "uncertain", "conflict"):
            warnings.append(f"{leg['match_label']}: kickoff time is uncertain.")

    for mid, ls in by_match.items():
        if len(ls) > 1:
            errors.append(f"{len(ls)} selections from the same match ({ls[0]['match_label']}): "
                          + ", ".join(x["label"] for x in ls)
                          + ". Same-match selections are strongly correlated; keep one.")
            correlations.append({"type": "same_match", "strength": "strong",
                                 "legs": [x["key"] for x in ls], "match_label": ls[0]["match_label"],
                                 "note": "Outcomes depend on the same game state (e.g. Over 2.5 and BTTS rise and fall together)."})

    # cross-match correlations
    team_legs: dict[str, list[dict]] = {}
    for leg in legs:
        for t in (leg.get("home_id"), leg.get("away_id")):
            if t:
                team_legs.setdefault(t, []).append(leg)
    for t, ls in team_legs.items():
        mids = {x["match_id"] for x in ls}
        if len(mids) > 1:
            correlations.append({"type": "same_team", "strength": "moderate", "legs": [x["key"] for x in ls],
                                 "note": f"The same team appears in {len(mids)} matches; form, rotation or injuries "
                                         "affect both legs."})
            warnings.append(f"Same team in several matches: {', '.join(x['match_label'] for x in ls)}.")
    groups: dict[tuple, list[dict]] = {}
    for leg in legs:
        groups.setdefault((leg.get("competition"), leg.get("local_date"), leg.get("family")), []).append(leg)
    for (comp, day, fam), ls in groups.items():
        if len({x["match_id"] for x in ls}) >= 3:
            correlations.append({"type": "same_round_same_market", "strength": "weak",
                                 "legs": [x["key"] for x in ls],
                                 "note": f"{len(ls)} {fam} selections in {comp} on {day}: shared conditions "
                                         "(weather, refereeing trends, round-wide scoring) weakly link them."})

    priced = [leg for leg in legs if leg.get("odds")]
    try:
        combo = combined_odds([leg["odds"] for leg in priced]) if priced else None
    except ValueError as exc:
        errors.append(str(exc))
        combo = None
    probs = [leg.get("probability") for leg in priced]
    naive = None
    no_loss = None
    if priced and all(p is not None for p in probs):
        naive = math.prod(probs)
        no_loss = math.prod((leg.get("probability") or 0) + (leg.get("void_probability") or 0) for leg in priced)
    weak = [leg for leg in legs if leg.get("tier") == "weak" or not leg.get("qualifies", True)]
    return {
        "n_selections": len(legs),
        "combined_odds": None if combo is None else round(combo, 2),
        "target_odds": target,
        "target_reached": None if combo is None or target is None else combo >= target,
        "bookmaker_implied_probability": None if not combo else round(1 / combo, 5),
        "model_probability_all_win": None if naive is None else round(naive, 5),
        "model_probability_no_loss": None if no_loss is None else round(no_loss, 5),
        "model_probability_note": "Naive model estimate: product of leg estimates, assumes independence. "
                                  "Not a verified probability.",
        "weak_legs": len(weak),
        "errors": errors, "warnings": _dedupe(warnings), "correlations": correlations,
        "valid": not errors,
        "price_sources": sorted({f"{leg.get('bookmaker')} ({'manual entry' if leg.get('odds_source') == 'manual' else 'dataset snapshot'})"
                                 for leg in priced}),
    }


def _dedupe(xs: list[str]) -> list[str]:
    out, seen = [], set()
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def ticket_pool(summaries: list[dict], analyze: Callable[[str], dict], settings: dict) -> tuple[list[dict], list[dict]]:
    """Best priced, qualifying selection per eligible match → (strong/acceptable legs, weak legs)."""
    good, weak = [], []
    for s in summaries:
        if s["status"] in ("rejected", "ineligible"):
            continue
        a = analyze(s["fixture"]["id"])
        priced = [c for c in a["candidates"] if c["qualifies"] and c["price"]]
        if not settings.get("allow_snapshot_odds", True):
            priced = [c for c in priced if c["price"]["source"] == "manual"]
        if not priced:
            continue
        best = max(priced, key=lambda c: c["score"]["total"])
        leg = leg_from_candidate(a, best)
        leg["_rank"] = (s["status"] == "candidate", best["score"]["total"])
        (good if best["tier"] in ("strong", "acceptable") and best.get("confidence") in ("high", "medium")
         else weak).append(leg)
    good.sort(key=lambda x: x["_rank"], reverse=True)
    weak.sort(key=lambda x: x["_rank"], reverse=True)
    return good, weak


def build(good: list[dict], weak: list[dict], target: float, max_legs: int) -> dict:
    def greedy(pool: list[dict], start: list[dict]) -> list[dict]:
        legs = list(start)
        teams = {t for leg in legs for t in (leg["home_id"], leg["away_id"])}
        for leg in pool:
            if combined_odds([x["odds"] for x in legs] or [1.01]) >= target and legs:
                break
            if len(legs) >= max_legs:
                break
            if leg["home_id"] in teams or leg["away_id"] in teams:
                continue
            legs.append(leg)
            teams |= {leg["home_id"], leg["away_id"]}
        return legs

    main = greedy(good, [])
    reached = bool(main) and combined_odds([x["odds"] for x in main]) >= target
    # trim: drop the weakest legs while the target is still met
    if reached:
        changed = True
        while changed and len(main) > 1:
            changed = False
            weakest = min(main, key=lambda x: x["score"])
            rest = [x for x in main if x is not weakest]
            if combined_odds([x["odds"] for x in rest]) >= target:
                main, changed = rest, True
    padded = None
    if not reached and weak:
        padded_legs = greedy(weak, main)
        if padded_legs and combined_odds([x["odds"] for x in padded_legs]) >= target:
            padded = padded_legs
    alt = None
    if len(main) >= 2:
        k = max(2, min(4, math.ceil(len(main) / 2)))
        if k < len(main):
            alt = sorted(main, key=lambda x: x["score"], reverse=True)[:k]
    return {"main": main, "target_reached": reached, "padded": padded, "alternative": alt}


def final_opinion(main_eval: dict, target: float, padded_eval: dict | None, alt_eval: dict | None) -> str:
    n = main_eval["n_selections"]
    if n == 0:
        return ("No ticket: none of the analysed matches produced a priced selection that passes the evidence gates. "
                "That is a valid outcome — enter Bet365 prices for the qualifying markets, widen the date range, "
                "or skip this round.")
    combo = main_eval["combined_odds"]
    p = main_eval["model_probability_all_win"]
    imp = main_eval["bookmaker_implied_probability"]
    p_txt = f"{100 * p:.1f}%" if p is not None else "n/a"
    parts = []
    if main_eval["target_reached"]:
        if main_eval["weak_legs"]:
            parts.append(f"The ticket reaches {combo:.2f} but includes {main_eval['weak_legs']} weak selection(s): "
                         "it has been made riskier to hit the target.")
        else:
            parts.append(f"The ticket reaches {combo:.2f} using only selections that pass the evidence gates. "
                         "Each leg is individually defensible.")
        parts.append(f"Even so, {n} legs compound: the naive model estimate that every leg wins is {p_txt} "
                     f"(the bookmaker price implies {100 * imp:.2f}%). Treat it as a long shot, not a forecast.")
    else:
        parts.append(f"The {target:g} target is not reachable with well-supported selections. The honest ticket is "
                     f"{combo:.2f} with {n} legs (naive all-win estimate {p_txt}).")
        if padded_eval:
            pp = padded_eval["model_probability_all_win"]
            parts.append(f"Reaching {target:g} would need {padded_eval['n_selections'] - n} weak selection(s), "
                         f"cutting the estimate to {100 * pp:.2f}% — not recommended." if pp is not None else
                         "Reaching the target would require weak selections — not recommended.")
    if alt_eval and alt_eval.get("combined_odds"):
        ap = alt_eval["model_probability_all_win"]
        parts.append(f"A smaller alternative ({alt_eval['n_selections']} legs, {alt_eval['combined_odds']:.2f}) "
                     f"keeps only the best-supported legs (naive estimate {100 * ap:.1f}%)." if ap is not None else "")
    if any("dataset snapshot" in s for s in main_eval["price_sources"]):
        parts.append("Some prices are dataset snapshots, not live Bet365 prices — re-check every price before staking.")
    return " ".join(x for x in parts if x)
