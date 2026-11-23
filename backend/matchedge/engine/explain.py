"""Deterministic explanation engine (used always; the optional local LLM only rephrases).

Every sentence is built from fields in the analysis object. Qualitative statements are tagged
"[qualitative]". Nothing here invents injuries, lineups, odds or statistics.
"""
from __future__ import annotations


def poss(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _pct(x) -> str:
    return "n/a" if x is None else f"{round(100 * x)}%"


def _hr(h: dict) -> str:
    return "no data" if not h or not h.get("n") else f"{h['k']}/{h['n']}"


def compare_markets(best: dict, candidates: list[dict]) -> list[dict]:
    """Why the chosen market beats the alternatives (match winner always included)."""
    out = []
    seen = {best["key"]}
    winners = [c for c in candidates if c["market"] == "1X2" and c["selection"] != "draw" and c["supported"]]
    pool = sorted(winners, key=lambda c: c["probability"] or 0, reverse=True)[:1]
    others = [c for c in candidates if c["supported"] and c["key"] not in seen]
    by_family: dict[str, dict] = {}
    for c in sorted(others, key=lambda c: c["score"]["evidence"], reverse=True):
        by_family.setdefault(c["family"], c)
    pool += [c for c in by_family.values() if c["family"] != best["family"]][:4]
    for c in pool:
        if c["key"] in seen:
            continue
        seen.add(c["key"])
        if not c["qualifies"]:
            why = c["gates_failed"][0] if c["gates_failed"] else "Did not pass the selection gates."
        else:
            why = (f"Lower evidence score ({c['score']['evidence']} vs {best['score']['evidence']}).")
        out.append({"label": c["label"], "probability_pct": c["probability_pct"], "range_pct": c["range_pct"],
                    "evidence": c["score"]["evidence"], "why_not": why})
    return out


def failure_modes(c: dict, a: dict) -> list[str]:
    home, away = a["fixture"]["home"], a["fixture"]["away"]
    gm = a["model"] or {}
    probs = gm.get("probabilities_pct") or {}
    hp, ap = a["profiles"]["home"], a["profiles"]["away"]
    out: list[str] = []
    fam, sel = c["family"], c["selection"]
    if c["probability"] is not None:
        out.append(f"By the model's own estimate this selection loses about {100 - c['probability_pct']}% of the time.")
    if fam == "goals" and sel == "over":
        out.append(f"{home} kept clean sheets in {_hr(hp['goals_venue']['clean_sheet'])} home matches and "
                   f"{away} failed to score in {_hr(ap['goals_venue']['failed_to_score'])} away matches — "
                   "a cagey game or an early red card can kill the total.")
    elif fam == "goals" and sel == "under":
        out.append(f"One early goal changes the game state; {poss(home)} home matches went Over 2.5 in "
                   f"{_hr(hp['goals_venue']['over25'])} and {poss(away)} away matches in {_hr(ap['goals_venue']['over25'])}.")
    elif fam == "btts" and sel == "yes":
        out.append(f"{home} home clean sheets {_hr(hp['goals_venue']['clean_sheet'])}; {away} away "
                   f"failed-to-score {_hr(ap['goals_venue']['failed_to_score'])}. One side blanking is enough to lose.")
    elif fam == "btts" and sel == "no":
        out.append(f"{home} scored in {_hr(hp['scoring_consistency'])} of their matches and {away} in "
                   f"{_hr(ap['scoring_consistency'])}; a single goal each settles it against you.")
    elif fam == "result":
        if probs.get("draw") is not None:
            out.append(f"The draw is the main threat (model ≈{probs['draw']}%)" +
                       ("; draw no bet / double chance would protect against it." if c["market"] == "1X2" else "."))
        out.append("Late team news (rotation, injuries) is not in the dataset and moves result markets most. [qualitative]")
    elif fam == "team_goals":
        out.append("Team-goal lines depend on one side's finishing; a goalkeeper performance or early lead "
                   "that leads to game management can leave it short. [qualitative]")
    elif fam == "first_half":
        out.append("First-half goals are estimated from the competition's first-half goal share, "
                   "not from team-specific half-time patterns.")
    elif fam == "corners":
        cm = a["corners"]
        out.append(f"Corners are volatile (competition variance/mean ratio {cm.get('dispersion')}); "
                   "a side that takes an early lead often stops attacking. [qualitative]")
    elif fam == "cards":
        out.append("The referee is unknown (not in the dataset) and drives card counts more than team history. "
                   "Bookmaker card-counting rules also differ from the dataset's yellow+red total.")
    if a["samples"]["cross_league"]:
        out.append("Ratings compare teams from different leagues, which the model can only approximate.")
    if not any(r["category"] in ("lineup", "injury") for r in a["evidence"]):
        out.append("No lineup/injury information has been checked for this match.")
    return out


def selection_reasoning(c: dict, a: dict) -> list[str]:
    home, away = a["fixture"]["home"], a["fixture"]["away"]
    hp, ap = a["profiles"]["home"], a["profiles"]["away"]
    gm = a["model"] or {}
    xg = gm.get("expected_goals")
    lines: list[str] = []
    f5h, f5a = hp["form5"], ap["form5"]
    lines.append(f"Form (last 5): {home} {f5h['sequence'] or '–'} ({f5h['gf']}-{f5h['ga']} goals, "
                 f"{f5h['ppg']} ppg); {away} {f5a['sequence'] or '–'} ({f5a['gf']}-{f5a['ga']}, {f5a['ppg']} ppg).")
    vh, va = hp["venue_form"], ap["venue_form"]
    gvh, gva = hp["goals_venue"], ap["goals_venue"]
    lines.append(f"Venue split: {home} at home {vh['w']}W-{vh['d']}D-{vh['l']}L in {vh['n']}, scoring "
                 f"{gvh['gf']['mean']} and conceding {gvh['ga']['mean']} per game; {away} away "
                 f"{va['w']}W-{va['d']}D-{va['l']}L in {va['n']}, scoring {gva['gf']['mean']} and conceding "
                 f"{gva['ga']['mean']}.")
    if xg:
        lines.append(f"Model expected goals: {home} {xg['home']} (range {xg['home_range'][0]}–{xg['home_range'][1]}), "
                     f"{away} {xg['away']} ({xg['away_range'][0]}–{xg['away_range'][1]}); total {xg['total']} vs "
                     f"competition average {a['league']['avg_total_goals']}.")
    hr = c["hit_rates"]
    lines.append(f"History for this exact selection: {home} home matches {_hr(hr['home_team_home'])}, "
                 f"{away} away matches {_hr(hr['away_team_away'])}; last ten overall {_hr(hr['home_team_last10'])} "
                 f"and {_hr(hr['away_team_last10'])}.")
    if c["probability_pct"] is not None:
        lines.append(f"Model estimate {c['probability_pct']}% (range {c['range_pct'][0]}–{c['range_pct'][1]}%)"
                     + (f"; the price {c['price']['odds']:.2f} implies {_pct(c['implied_probability'])}"
                        f"{' (' + _pct(c['fair_probability']) + ' without margin)' if c['fair_probability'] else ''}."
                        if c["price"] else "; no price entered yet."))
    if c["family"] == "corners" and a["corners"].get("available"):
        cm = a["corners"]
        lines.append(f"Corners: expected {cm['expected_home']} + {cm['expected_away']} = {cm['expected_total']} "
                     f"(samples {cm['n_home']}/{cm['n_away']} matches).")
    if c["family"] == "cards" and a["cards"].get("available"):
        cm = a["cards"]
        lines.append(f"Cards: expected total {cm['expected_total']} (samples {cm['n_home']}/{cm['n_away']}).")
    if c["family"] in ("goals", "btts"):
        sh, sa = hp["misc_venue"]["sot_for"], ap["misc_venue"]["sot_for"]
        if sh["mean"] is not None and sa["mean"] is not None:
            lines.append(f"Shots on target per game: {home} at home {sh['mean']} (n={sh['n']}), "
                         f"{away} away {sa['mean']} (n={sa['n']}).")
    for r in c["research"]:
        lines.append(f"Your research ({r['reliability']} reliability) {r['impact']} this selection: "
                     f"{r.get('statistic') or ''} {('— ' + r['url']) if r.get('url') else ''}".strip())
    return lines


def match_explanation(a: dict) -> dict:
    fx = a["fixture"]
    status = a["decision"]["status"]
    rec = a["recommendation"]
    title = f"{fx['home']} vs {fx['away']}"
    if rec:
        c = next(x for x in a["candidates"] if x["key"] == rec["key"])
        why = [f"{x['label']}: {x['why_not']}" for x in rec["comparison"]]
        verdict = (f"{c['label']} is the most defensible market here, but the match is flagged — read the risks."
                   if status == "flagged" else f"{c['label']} is the most defensible market on the available evidence.")
        return {"engine": "deterministic", "title": title, "selected_market": c["label"], "verdict": verdict,
                "reasoning": selection_reasoning(c, a), "why_not_other_markets": why,
                "how_it_could_fail": failure_modes(c, a),
                "flags": [f["message"] for f in a["decision"]["factors"] if f["action"] == "flag"]}
    reasons = [f["message"] for f in a["decision"]["factors"] if f["action"] in ("reject", "flag")]
    top = sorted([x for x in a["candidates"] if x["supported"]], key=lambda x: x["score"]["evidence"], reverse=True)[:3]
    return {"engine": "deterministic", "title": title, "selected_market": None,
            "verdict": "No selection. " + (reasons[0] if reasons else "No market passes the gates."),
            "reasoning": reasons,
            "why_not_other_markets": [f"{x['label']} ({x['probability_pct']}%): "
                                      f"{x['gates_failed'][0] if x['gates_failed'] else 'match-level rejection'}"
                                      for x in top],
            "how_it_could_fail": [], "flags": []}
