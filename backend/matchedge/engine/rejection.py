"""Match rejection rules.

Every rule returns a factor ``{code, severity, action, message}``. ``action='reject'`` removes the
match from ticket consideration; ``'flag'`` keeps it but surfaces the risk; ``'info'`` is context.
The engine never treats every fixture as a betting opportunity.
"""
from __future__ import annotations

from datetime import date


def _f(code, severity, action, message):
    return {"code": code, "severity": severity, "action": action, "message": message}


RESULT_MARKETS = {"1X2", "DNB", "AH"}


def closely_matched(goals: dict, home_p: dict, away_p: dict, settings: dict) -> bool:
    xg = goals.get("expected_goals") if goals.get("available") else None
    p5h, p5a = home_p["form5"]["ppg"], away_p["form5"]["ppg"]
    if not xg or p5h is None or p5a is None:
        return False
    return abs(xg["home"] - xg["away"]) < float(settings["close_match_xg_gap"]) and abs(p5h - p5a) < 0.6


def evaluate_rules(*, home: str, away: str, home_p: dict, away_p: dict, goals: dict, candidates: list[dict],
                   research: list[dict], settings: dict, dataset_age_days: float | None,
                   fixture_date: date, home_last: date | None, away_last: date | None,
                   cross_league: bool, unlinked: list[str], time_label: str, verified: bool) -> list[dict]:
    out: list[dict] = []
    min_model = int(settings["min_matches_model"])
    n_h, n_a = home_p["matches"], away_p["matches"]

    # small samples
    if min(n_h, n_a) < min_model:
        out.append(_f("small_sample", "high", "reject",
                      f"Sample too small: {home} {n_h} and {away} {n_a} usable matches (minimum {min_model})."))
    elif min(n_h, n_a) < 8:
        out.append(_f("limited_sample", "medium", "flag",
                      f"Limited sample ({min(n_h, n_a)} matches); estimates rely heavily on shrinkage."))
    for team in unlinked:
        out.append(_f("unlinked_team", "medium", "flag",
                      f"{team} could not be linked to domestic-league data; only this competition's matches are used."))

    # model availability
    if not goals.get("available"):
        out.append(_f("no_model", "high", "reject", goals.get("reason") or "Goal model unavailable."))

    # closely matched teams
    if closely_matched(goals, home_p, away_p, settings):
        xg = goals["expected_goals"]
        out.append(_f("closely_matched", "medium", "flag",
                      f"Closely matched: expected goals {xg['home']} vs {xg['away']}, last-5 ppg "
                      f"{home_p['form5']['ppg']} vs {away_p['form5']['ppg']}. Match-result markets are excluded."))

    # inconsistent recent results
    for team, p in ((home, home_p), (away, away_p)):
        seq = p["form5"]["sequence"]
        changes = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        swing = (abs(p["form5"]["ppg"] - p["form10"]["ppg"])
                 if p["form5"]["ppg"] is not None and p["form10"]["ppg"] is not None else 0)
        if len(seq) >= 5 and changes >= 4:
            out.append(_f("inconsistent_form", "medium", "flag",
                          f"{team} results are erratic (last five: {seq})."))
        elif swing >= 0.8:
            out.append(_f("form_swing", "low", "flag",
                          f"{team} last-5 form ({p['form5']['ppg']} ppg) differs sharply from last-10 "
                          f"({p['form10']['ppg']} ppg)."))

    # conflicting evidence among the strongest supported markets
    supported = [c for c in candidates if c["supported"]]
    top = sorted(supported, key=lambda c: c["probability"], reverse=True)[:6]
    conflicts = [c for c in top if "conflict" in c["score"]["flags"]]
    if len(conflicts) >= 2:
        out.append(_f("conflicting_evidence", "medium", "flag",
                      "Model and historical hit rates disagree on: " + ", ".join(c["label"] for c in conflicts[:3]) + "."))

    # lineup / injury uncertainty from user research
    for r in research:
        if r["category"] in ("lineup", "injury") and r["impact"] != "supports" and r["reliability"] != "low":
            out.append(_f("lineup_uncertainty", "high", "reject",
                          f"Your research flags {r['category']} uncertainty: {r.get('statistic') or r.get('notes') or ''}".strip()))
    if not any(r["category"] in ("lineup", "injury") for r in research):
        out.append(_f("no_lineup_info", "low", "info",
                      "No lineup or injury information recorded (the dataset has none). Check team news before betting."))

    # unpredictable market
    min_p = float(settings["min_leg_probability"])
    if supported and max(c["probability"] for c in supported) < min_p:
        out.append(_f("unpredictable", "high", "reject",
                      f"No market reaches the {round(100 * min_p)}% model-probability minimum."))

    # outdated data
    max_age = float(settings["max_dataset_age_days"])
    if dataset_age_days is None:
        out.append(_f("freshness_unknown", "medium", "flag", "Dataset build time unknown."))
    elif dataset_age_days > max_age:
        out.append(_f("dataset_outdated", "high", "reject",
                      f"Dataset is {dataset_age_days:.1f} days old (limit {max_age:g}). Re-import before analysing."))
    stale = int(settings["team_stale_days"])
    for team, last in ((home, home_last), (away, away_last)):
        if last is not None and (fixture_date - last).days > stale:
            out.append(_f("team_data_stale", "medium", "flag",
                          f"{team}{chr(39) if team.endswith('s') else chr(39) + 's'} latest result in the dataset is {(fixture_date - last).days} days before kickoff."))

    if cross_league:
        out.append(_f("cross_league", "medium", "flag",
                      "Teams' ratings come from different leagues; strength comparison is approximate."))
    if time_label in ("unknown", "conflict", "uncertain"):
        out.append(_f("kickoff_uncertain", "medium", "flag",
                      {"unknown": "Kickoff time unknown in the dataset.",
                       "conflict": "Kickoff times disagree between sources.",
                       "uncertain": "Kickoff may be one hour off (fixed UTC+1 dataset convention)."}[time_label]
                      + " Verify on the official competition website."))
    if not verified:
        out.append(_f("unverified_fixture", "low", "info",
                      "Fixture not verified against an official source (dataset only)."))

    qualifying = [c for c in candidates if c["qualifies"]]
    if not qualifying:
        out.append(_f("no_market", "high", "reject", "No market passes the evidence, probability and price gates."))
    elif not any(c["price"] for c in qualifying):
        out.append(_f("no_price", "low", "info",
                      "Qualifying markets exist but no odds are entered for them yet."))
    return out


def decide(factors: list[dict]) -> str:
    if any(f["action"] == "reject" for f in factors):
        return "rejected"
    if any(f["action"] == "flag" and f["severity"] in ("medium", "high") for f in factors):
        return "flagged"
    return "candidate"
