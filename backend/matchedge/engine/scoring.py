"""Match research score, data-quality score and risk assessment.

These are deliberately separate quantities (docs/SCORING.md):

* **Match research score** (0-100): how clear and well-evidenced the statistical picture is.
  It is *not* a probability and says nothing about which side wins.
* **Data quality score** (0-100): how much the inputs can be trusted (sample, completeness,
  freshness, fixture certainty, team identity).
* **Risk assessment**: a list of named risk factors with severities.

Model probabilities and bookmaker implied probabilities live in markets.py / poisson.py.
"""
from __future__ import annotations

import math
from datetime import date

from .markets import clamp


def research_score(home_p: dict, away_p: dict, goals_model: dict, corners: dict, cards: dict,
                   league_avg_total: float | None, dataset_age_days: float | None,
                   fixture_date: date, home_last: date | None, away_last: date | None) -> dict:
    comp: dict[str, dict] = {}

    def add(name, points, max_points, why):
        comp[name] = {"points": round(points, 1), "max": max_points, "why": why}

    f5h, f5a = home_p["form5"], away_p["form5"]
    if f5h["ppg"] is not None and f5a["ppg"] is not None:
        diff = abs(f5h["ppg"] - f5a["ppg"])
        add("recent_form", 15 * clamp(diff / 1.5), 15,
            f"Last-5 points per game {f5h['ppg']} vs {f5a['ppg']} (gap {diff:.2f}; 1.5+ scores full marks).")
    else:
        add("recent_form", 0, 15, "Recent form unavailable.")

    vh, va = home_p["venue_form"], away_p["venue_form"]
    if vh["ppg"] is not None and va["ppg"] is not None:
        diff = abs(vh["ppg"] - va["ppg"])
        add("home_away", 15 * clamp(diff / 1.5), 15,
            f"Home side at home {vh['ppg']} ppg ({vh['n']} m) vs away side away {va['ppg']} ppg ({va['n']} m).")
    else:
        add("home_away", 0, 15, "Venue split unavailable.")

    xg = (goals_model or {}).get("expected_goals")
    if xg and league_avg_total:
        dev = abs(xg["total"] - league_avg_total)
        add("goals_signal", 15 * clamp(dev / 1.0), 15,
            f"Model total {xg['total']} vs competition average {league_avg_total:.2f} (distance {dev:.2f}).")
        det = goals_model["details"]["applied"]
        mismatch = abs(math.log(det["home_attack"] * det["away_defence"]) -
                       math.log(det["away_attack"] * det["home_defence"]))
        add("attack_defence", 10 * clamp(mismatch / 0.8), 10,
            f"Attack×defence mismatch (log ratio {mismatch:.2f}; 0.8+ scores full marks).")
    else:
        add("goals_signal", 0, 15, "Goal model unavailable.")
        add("attack_defence", 0, 10, "Goal model unavailable.")

    sec = (5 if corners.get("available") else 0) + (5 if cards.get("available") else 0)
    add("secondary_stats", sec, 10, f"Corners {'available' if corners.get('available') else 'missing'}, "
                                    f"cards {'available' if cards.get('available') else 'missing'}.")

    n = min(home_p["matches"], away_p["matches"])
    add("sample_size", 15 * clamp(n / 10), 15, f"Smallest team sample: {n} matches (10+ scores full marks).")

    fresh = 10.0
    why = []
    if dataset_age_days is None:
        fresh -= 4
        why.append("dataset build time unknown")
    elif dataset_age_days > 1:
        fresh -= min(5, 2 * (dataset_age_days - 1))
        why.append(f"dataset {dataset_age_days:.1f} days old")
    for lbl, last in (("home", home_last), ("away", away_last)):
        if last is None:
            fresh -= 3
            why.append(f"{lbl} team has no results")
        else:
            gap = (fixture_date - last).days
            if gap > 14:
                fresh -= min(3, (gap - 14) / 7)
                why.append(f"{lbl} team last result {gap} days before kickoff")
    add("freshness", max(0, fresh), 10, "; ".join(why) or "Dataset and team results are recent.")

    # consistency: low volatility in goals and last-5 vs season agreement
    def volatility(p):
        g = p["goals_all"]["gf"]
        return (g["sd"] / (g["mean"] + 0.5)) if g["sd"] is not None and g["mean"] is not None else None

    vols = [v for v in (volatility(home_p), volatility(away_p)) if v is not None]
    agree = []
    for p in (home_p, away_p):
        if p["form5"]["ppg"] is not None and p["form10"]["ppg"] is not None:
            agree.append(abs(p["form5"]["ppg"] - p["form10"]["ppg"]))
    if vols and agree:
        c = 5 * clamp(1 - (sum(vols) / len(vols) - 0.4) / 0.6) + 5 * clamp(1 - max(agree) / 1.2)
        add("consistency", c, 10, f"Goal volatility {sum(vols) / len(vols):.2f}; last-5 vs last-10 ppg "
                                  f"drift {max(agree):.2f}.")
    else:
        add("consistency", 0, 10, "Not enough matches to judge consistency.")

    total = sum(v["points"] for v in comp.values())
    return {"score": round(total, 1), "components": comp,
            "note": "Research score measures how clear the statistical picture is — it is not a probability."}


def data_quality(home_p: dict, away_p: dict, coverage: dict, dataset_age_days: float | None,
                 time_label: str, verified: bool, same_comp_sample: bool, unlinked: bool,
                 settings: dict) -> dict:
    comp: dict[str, dict] = {}
    n = min(home_p["matches"], away_p["matches"])
    comp["sample"] = {"points": round(30 * clamp(n / 10), 1), "max": 30,
                      "why": f"{n} matches in the smallest team sample."}
    wanted = {"half_time": 0.2, "shots": 0.2, "corners": 0.3, "cards": 0.3}
    cov = sum(w * float(coverage.get(k, 0) or 0) for k, w in wanted.items())
    comp["completeness"] = {"points": round(10 + 15 * cov, 1), "max": 25,
                            "why": "Goals always present; half-time/shots/corners/cards coverage "
                                   f"{', '.join(f'{k} {round(100 * float(coverage.get(k, 0) or 0))}%' for k in wanted)}."}
    max_age = float(settings["max_dataset_age_days"])
    if dataset_age_days is None:
        fp, why = 8.0, "Dataset build time unknown."
    else:
        fp = 20 * clamp(1 - max(0.0, dataset_age_days - 1) / max_age)
        why = f"Dataset built {dataset_age_days:.1f} days ago."
    comp["freshness"] = {"points": round(fp, 1), "max": 20, "why": why}
    tp = 15 if verified else {"corroborated": 11, "single_source": 8, "conflict": 4, "uncertain": 5,
                              "unknown": 0}.get(time_label, 0)
    comp["fixture_certainty"] = {"points": tp, "max": 15,
                                 "why": "Verified by you against an official source." if verified else
                                 f"Kickoff time status: {time_label}; fixture not verified."}
    ip = 0 if unlinked else (10 if same_comp_sample else 6)
    comp["identity"] = {"points": ip, "max": 10,
                        "why": "A team could not be linked to its domestic data." if unlinked else
                        "Sample from the same competition." if same_comp_sample else
                        "Sample mixes competitions (linked by team-name mapping)."}
    total = sum(v["points"] for v in comp.values())
    label = "good" if total >= 70 else "fair" if total >= 50 else "poor"
    return {"score": round(total, 1), "label": label, "components": comp}


def risk_assessment(factors: list[dict]) -> dict:
    high = sum(1 for f in factors if f["severity"] == "high")
    med = sum(1 for f in factors if f["severity"] == "medium")
    level = "high" if high or med >= 3 else "medium" if med else "low"
    return {"level": level, "factors": factors}
