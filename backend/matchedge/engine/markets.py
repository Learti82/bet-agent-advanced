"""Market comparison engine.

For each fixture we build candidate selections across 1X2, double chance, draw no bet, goal
totals, BTTS, team goals, first-half goals, corners, cards and Asian handicap (only when a price
exists). Each candidate gets:

* a model probability (Poisson for goals, negative binomial for corners/cards) with a range;
* historical hit rates in the home team's home matches and away team's away matches;
* the best available price and its source (manual entry preferred; dataset snapshot labelled);
* bookmaker implied probability (raw 1/odds, and margin-free when the full market is priced);
* a transparent selection score (see docs/SCORING.md).

A candidate without the data it needs is marked ``supported=False`` and can never become a
ticket selection.
"""
from __future__ import annotations

from typing import Callable

from .data import TeamRow
from .poisson import GoalModel, expected_return, settlement

SELECTION_LABELS = {
    ("1X2", "home"): "{home} to win", ("1X2", "draw"): "Draw", ("1X2", "away"): "{away} to win",
    ("DC", "1X"): "Double chance 1X ({home} or draw)", ("DC", "X2"): "Double chance X2 ({away} or draw)",
    ("DC", "12"): "Double chance 12 (no draw)",
    ("DNB", "home"): "{home} draw no bet", ("DNB", "away"): "{away} draw no bet",
    ("BTTS", "yes"): "Both teams to score — Yes", ("BTTS", "no"): "Both teams to score — No",
}
FAMILY = {"1X2": "result", "DC": "result", "DNB": "result", "AH": "handicap", "OU": "goals",
          "BTTS": "btts", "TG_HOME": "team_goals", "TG_AWAY": "team_goals", "1H_OU": "first_half",
          "CORNERS_OU": "corners", "CARDS_OU": "cards"}
MARKET_NAMES = {"1X2": "Match result (1X2)", "DC": "Double chance", "DNB": "Draw no bet",
                "AH": "Asian handicap", "OU": "Total goals", "BTTS": "Both teams to score",
                "TG_HOME": "Home team goals", "TG_AWAY": "Away team goals", "1H_OU": "First-half goals",
                "CORNERS_OU": "Total corners", "CARDS_OU": "Total cards"}
VALID_SELECTIONS = {
    "1X2": {"home", "draw", "away"}, "DC": {"1X", "X2", "12"}, "DNB": {"home", "away"},
    "AH": {"home", "away"}, "OU": {"over", "under"}, "BTTS": {"yes", "no"},
    "TG_HOME": {"over", "under"}, "TG_AWAY": {"over", "under"}, "1H_OU": {"over", "under"},
    "CORNERS_OU": {"over", "under"}, "CARDS_OU": {"over", "under"},
}
LINE_MARKETS = {"AH", "OU", "TG_HOME", "TG_AWAY", "1H_OU", "CORNERS_OU", "CARDS_OU"}


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def selection_key(market: str, selection: str, line: float | None) -> str:
    return f"{market}|{selection}|{'' if line is None else f'{float(line):g}'}"


def label_for(market: str, selection: str, line: float | None, home: str, away: str) -> str:
    if (market, selection) in SELECTION_LABELS:
        return SELECTION_LABELS[(market, selection)].format(home=home, away=away)
    ln = "" if line is None else f"{float(line):g}"
    if market == "AH":
        team = home if selection == "home" else away
        return f"{team} {'+' if line and line > 0 else ''}{ln} (Asian handicap)"
    noun = {"OU": "goals", "TG_HOME": f"{home} goals", "TG_AWAY": f"{away} goals",
            "1H_OU": "first-half goals", "CORNERS_OU": "corners", "CARDS_OU": "cards"}[market]
    return f"{selection.capitalize()} {ln} {noun}"


def is_half_line(line: float | None) -> bool:
    return line is None or abs((abs(line) * 2) % 2 - 1) < 1e-9


# ----------------------------------------------------------------------------- hit predicates
def hit_predicate(market: str, selection: str, line: float | None, side: str) -> Callable[[TeamRow], bool | None]:
    """Condition evaluated on a team-perspective row. ``side`` is the fixture side of that team."""
    def my_opp(r: TeamRow):
        # goals of fixture-home team and fixture-away team in that past match
        return (r.gf, r.ga) if side == "home" else (r.ga, r.gf)

    def settle(margin: float) -> bool | None:
        return True if margin > 1e-9 else False if margin < -1e-9 else None

    if market in ("1X2", "DC", "DNB"):
        def f(r: TeamRow):
            h, a = my_opp(r)
            res = "home" if h > a else "draw" if h == a else "away"
            if market == "1X2":
                return res == selection
            if market == "DC":
                return {"1X": res != "away", "X2": res != "home", "12": res != "draw"}[selection]
            return None if res == "draw" else res == selection
        return f
    if market == "BTTS":
        return lambda r: (r.gf > 0 and r.ga > 0) == (selection == "yes")
    if market == "OU":
        return lambda r: settle((r.gf + r.ga - line) * (1 if selection == "over" else -1))
    if market in ("TG_HOME", "TG_AWAY"):
        target = "home" if market == "TG_HOME" else "away"

        def f(r: TeamRow):
            h, a = my_opp(r)
            g = h if target == "home" else a
            return settle((g - line) * (1 if selection == "over" else -1))
        return f
    if market == "1H_OU":
        def f(r: TeamRow):
            t = r.total("ht_goals")
            return None if t is None else settle((t - line) * (1 if selection == "over" else -1))
        return f
    if market == "CORNERS_OU":
        def f(r: TeamRow):
            t = r.total("corners")
            return None if t is None else settle((t - line) * (1 if selection == "over" else -1))
        return f
    if market == "CARDS_OU":
        def f(r: TeamRow):
            t = r.cards_total()
            return None if t is None else settle((t - line) * (1 if selection == "over" else -1))
        return f
    if market == "AH":
        def f(r: TeamRow):
            h, a = my_opp(r)
            margin = (h - a if selection == "home" else a - h) + line
            return settle(margin)
        return f
    raise ValueError(market)


def hit_rate(rows: list[TeamRow], pred) -> dict:
    vals = [pred(r) for r in rows]
    usable = [v for v in vals if v is not None]
    n = len(usable)
    k = sum(1 for v in usable if v)
    return {"k": k, "n": n, "of": len(rows), "rate": round(k / n, 3) if n else None}


# ----------------------------------------------------------------------------- odds handling
def choose_price(rows: list[dict], preferred_bookmaker: str) -> tuple[dict | None, list[dict]]:
    """Manual entries beat snapshots; preferred bookmaker beats others; newest check wins."""
    if not rows:
        return None, []
    pref = preferred_bookmaker.lower()

    def rank(r):
        return (r["source"] == "manual", r["bookmaker"].lower() == pref, r["checked_at"] or "")

    ordered = sorted(rows, key=rank, reverse=True)
    return ordered[0], ordered


COMPLEMENTS = {
    "1X2": lambda sel, line: [("home", None), ("draw", None), ("away", None)],
    "BTTS": lambda sel, line: [("yes", None), ("no", None)],
    "DNB": lambda sel, line: [("home", None), ("away", None)],
    "AH": lambda sel, line: [(sel, line), ("away" if sel == "home" else "home", -line)],
}
for _m in ("OU", "TG_HOME", "TG_AWAY", "1H_OU", "CORNERS_OU", "CARDS_OU"):
    COMPLEMENTS[_m] = lambda sel, line: [("over", line), ("under", line)]


def fair_implied(market: str, selection: str, line: float | None, price: dict,
                 odds_index: dict[tuple, list[dict]]) -> tuple[float | None, float | None]:
    """Margin-free implied probability using the same bookmaker/source, plus the overround."""
    comp = COMPLEMENTS.get(market)
    if comp is None:
        return None, None
    inv = []
    for sel, ln in comp(selection, line):
        same = [r for r in odds_index.get((market, sel, _ln(ln)), [])
                if r["bookmaker"] == price["bookmaker"] and r["source"] == price["source"]]
        if not same:
            return None, None
        inv.append((sel, ln, 1 / max(same, key=lambda r: r["checked_at"] or "")["odds"]))
    total = sum(x for *_, x in inv)
    mine = next(x for s, ln, x in inv if s == selection and _ln(ln) == _ln(line))
    return mine / total, total - 1


def _ln(line):
    return None if line is None else round(float(line), 2)


def index_odds(rows: list[dict]) -> dict[tuple, list[dict]]:
    idx: dict[tuple, list[dict]] = {}
    for r in rows:
        idx.setdefault((r["market"], r["selection"], _ln(r["line"])), []).append(r)
    return idx


# ----------------------------------------------------------------------------- candidates
def model_probability(market: str, selection: str, line: float | None, goals: GoalModel,
                      corners: dict, cards: dict) -> tuple[float | None, tuple | None, str | None, dict | None]:
    """Returns (point, (lo, hi), unsupported_reason, settlement_dist)."""
    if market in ("1X2", "DC", "DNB", "BTTS", "OU", "TG_HOME", "TG_AWAY", "AH"):
        if not goals.available:
            return None, None, goals.reason, None
        key = None
        if market == "1X2":
            key = selection
        elif market == "DC":
            key = f"dc_{selection}"
        elif market == "DNB":
            key = f"dnb_{selection}"
        elif market == "BTTS":
            key = f"btts_{selection}"
        elif market in ("OU", "TG_HOME", "TG_AWAY") and is_half_line(line) and line in (0.5, 1.5, 2.5, 3.5, 4.5):
            prefix = {"OU": "over", "TG_HOME": "home_over", "TG_AWAY": "away_over"}[market]
            k = f"{prefix}_{line}"
            if k in goals.probs:
                p, (lo, hi) = goals.probs[k], goals.ranges[k]
                return (p, (lo, hi), None, None) if selection == "over" else (1 - p, (1 - hi, 1 - lo), None, None)
        if key:
            return goals.probs[key], goals.ranges[key], None, None
        # general settlement over the score matrix (AH and non-standard totals)
        if market == "AH":
            dist = settlement(goals.matrix, "AH", selection, float(line))
        elif market == "OU":
            dist = settlement(goals.matrix, "OU", selection, float(line))
        else:
            return None, None, "Unsupported team-goals line.", None
        p_win = dist["win"] + dist["half_win"]
        kind = "AH" if market == "AH" else "OU"
        alt = [settlement(vm, kind, selection, float(line)) for vm in (goals.variants or [])]
        vals = [d["win"] + d["half_win"] for d in alt] + [p_win]
        return p_win, (min(vals), max(vals)), None, dist
    if market == "1H_OU":
        fh = goals.first_half if goals.available else None
        if not fh or not fh.get("available"):
            return None, None, (fh or {}).get("reason") or goals.reason or "First-half data unavailable.", None
        k = f"over_{float(line)}"
        if k not in fh["probs"]:
            return None, None, "Only first-half lines 0.5 and 1.5 are modelled.", None
        p = fh["probs"][k]
        # first-half range: inherit relative width of the full-match equivalent market
        p = p if selection == "over" else 1 - p
        return p, (max(0, p - 0.06), min(1, p + 0.06)), None, None
    if market in ("CORNERS_OU", "CARDS_OU"):
        cm = corners if market == "CORNERS_OU" else cards
        if not cm.get("available"):
            return None, None, cm.get("reason"), None
        k = str(float(line))
        if k not in cm["probs"]:
            return None, None, "Line outside modelled range.", None
        p, (lo, hi) = cm["probs"][k], cm["ranges"][k]
        return (p, (lo, hi), None, None) if selection == "over" else (1 - p, (1 - hi, 1 - lo), None, None)
    return None, None, "Unknown market.", None


def candidate_specs(goals: GoalModel, corners: dict, cards: dict, odds_index: dict[tuple, list[dict]],
                    settings: dict) -> list[tuple[str, str, float | None]]:
    specs: list[tuple[str, str, float | None]] = []
    for sel in ("home", "draw", "away"):
        specs.append(("1X2", sel, None))
    for sel in ("1X", "X2", "12"):
        specs.append(("DC", sel, None))
    specs += [("DNB", "home", None), ("DNB", "away", None), ("BTTS", "yes", None), ("BTTS", "no", None)]
    for ln in (1.5, 2.5, 3.5):
        specs += [("OU", "over", ln), ("OU", "under", ln)]
    for m in ("TG_HOME", "TG_AWAY"):
        specs += [(m, "over", 0.5), (m, "over", 1.5), (m, "under", 1.5)]
    specs += [("1H_OU", "over", 0.5), ("1H_OU", "over", 1.5), ("1H_OU", "under", 1.5)]
    for cm, m in ((corners, "CORNERS_OU"), (cards, "CARDS_OU")):
        if cm.get("available"):
            mu = cm["expected_total"]
            base = int(mu)
            for ln in sorted({base - 1.5, base - 0.5, base + 0.5, base + 1.5}):
                if ln > 0 and str(float(ln)) in cm["probs"]:
                    specs += [(m, "over", ln), (m, "under", ln)]
        else:
            specs += [(m, "over", 9.5 if m == "CORNERS_OU" else 3.5)]
    # priced selections not already listed: every manual entry; snapshot lines only within a useful
    # price band (each match has ~30 snapshot handicap/total lines, most of them irrelevant)
    lo, hi = float(settings["min_leg_odds"]), float(settings["max_snapshot_candidate_odds"])
    for (market, sel, ln), rows in odds_index.items():
        if market not in VALID_SELECTIONS or (market, sel, ln) in specs:
            continue
        if any(r["source"] == "manual" for r in rows):
            specs.append((market, sel, ln))
        elif any(lo <= r["odds"] <= hi for r in rows) and not (market == "AH" and ln is not None and abs(ln) > 1.5):
            # snapshot handicaps beyond ±1.5 are skipped: independent Poisson is weakest in blowout tails
            specs.append((market, sel, ln))
    seen, out = set(), []
    for s in specs:
        k = (s[0], s[1], _ln(s[2]))
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def evaluate_candidates(*, home: str, away: str, home_rows: list[TeamRow], away_rows: list[TeamRow],
                        goals: GoalModel, corners: dict, cards: dict, odds_rows: list[dict],
                        research: list[dict], settings: dict, cross_league: bool) -> list[dict]:
    odds_index = index_odds(odds_rows)
    home_venue = [r for r in home_rows if r.venue == "H"]
    away_venue = [r for r in away_rows if r.venue == "A"]
    out = []
    min_leg_p = float(settings["min_leg_probability"])
    thr = float(settings["conflict_threshold"])
    for market, sel, line in candidate_specs(goals, corners, cards, odds_index, settings):
        p, rng, reason, dist = model_probability(market, sel, line, goals, corners, cards)
        hv_h = hit_rate(home_venue, hit_predicate(market, sel, line, "home"))
        hv_a = hit_rate(away_venue, hit_predicate(market, sel, line, "away"))
        h10 = hit_rate(home_rows[:10], hit_predicate(market, sel, line, "home"))
        a10 = hit_rate(away_rows[:10], hit_predicate(market, sel, line, "away"))
        if market == "1H_OU" and p is not None:
            n_ht = min(hit_rate(home_rows, hit_predicate(market, sel, line, "home"))["n"],
                       hit_rate(away_rows, hit_predicate(market, sel, line, "away"))["n"])
            if n_ht < int(settings["min_matches_stat"]):
                p, rng, dist = None, None, None
                reason = (f"Insufficient half-time data for these teams ({n_ht} matches); "
                          "first-half markets are not supported.")
        price, prices = choose_price(odds_index.get((market, sel, _ln(line)), []), str(settings["bookmaker"]))
        cand = {
            "key": selection_key(market, sel, line), "market": market, "market_name": MARKET_NAMES[market],
            "family": FAMILY[market], "selection": sel, "line": line,
            "label": label_for(market, sel, line, home, away),
            "supported": p is not None, "unsupported_reason": reason,
            "probability": None if p is None else round(p, 4),
            "probability_pct": None if p is None else round(100 * p),
            "range_pct": None if rng is None else [round(100 * rng[0]), round(100 * rng[1])],
            "probability_source": None if p is None else (
                "negative binomial" if market in ("CORNERS_OU", "CARDS_OU") else "Poisson"),
            "settlement": None if dist is None else {k: round(v, 4) for k, v in dist.items()},
            "hit_rates": {"home_team_home": hv_h, "away_team_away": hv_a,
                          "home_team_last10": h10, "away_team_last10": a10},
            "price": price, "prices": prices[:6],
            "implied_probability": None, "fair_probability": None, "overround": None,
            "edge": None, "expected_value": None,
            "accumulator_ok": is_half_line(line),
            "flags": [], "research": [],
            # probability the leg wins / is voided (DNB voids on a draw) — used for ticket estimates
            "win_probability": None if p is None else round(p, 4),
            "void_probability": 0.0,
        }
        if market == "DNB" and goals.available:
            cand["win_probability"] = round(goals.probs[sel], 4)
            cand["void_probability"] = round(goals.probs["draw"], 4)
            cand["flags"].append("Stake returned on a draw (leg settles at 1.00 in an accumulator).")
        if dist:
            cand["void_probability"] = round(dist["push"], 4)
        if not cand["accumulator_ok"]:
            cand["flags"].append("Whole/quarter line: push or half-settlement possible, not used in accumulators.")
        if price:
            imp = 1 / price["odds"]
            cand["implied_probability"] = round(imp, 4)
            fair, over = fair_implied(market, sel, line, price, odds_index)
            cand["fair_probability"] = None if fair is None else round(fair, 4)
            cand["overround"] = None if over is None else round(over, 4)
            if p is not None:
                cand["edge"] = round(p - imp, 4)
                ev = expected_return(dist, price["odds"]) if dist else p * price["odds"] - 1
                cand["expected_value"] = round(float(ev), 4)
        # research entries tied to this market
        for rs in research:
            rm = (rs.get("related_market") or "").strip()
            if rm and rm in (cand["key"], market, f"{market}|{sel}"):
                cand["research"].append({"id": rs["id"], "impact": rs["impact"], "reliability": rs["reliability"],
                                         "statistic": rs.get("statistic"), "url": rs.get("url")})
        score_candidate(cand, settings, cross_league, thr)
        # eligibility as a ticket leg
        gates = []
        if not cand["supported"]:
            gates.append(reason or "No model probability.")
        else:
            if p < min_leg_p:
                gates.append(f"Model probability {round(100 * p)}% below the {round(100 * min_leg_p)}% leg minimum.")
            if rng and rng[0] < min_leg_p - 0.08:
                gates.append(f"Lower end of the probability range ({round(100 * rng[0])}%) is too low.")
            if "conflict" in cand["score"]["flags"]:
                gates.append("Model and historical hit rates disagree.")
            min_odds = float(settings["min_leg_odds"])
            if price and price["odds"] < min_odds:
                gates.append(f"Price {price['odds']:.2f} too short to add value to a ticket (< {min_odds:.2f}).")
            if not price and p > 0 and 1 / p < min_odds:
                gates.append(f"Fair price ≈{1 / p:.2f} would be below the {min_odds:.2f} minimum leg price.")
            if cand["edge"] is not None and cand["edge"] > 0.20:
                gates.append(f"Model ({round(100 * p)}%) exceeds the price's implied {round(100 * cand['implied_probability'])}% "
                             "by more than 20 points — the market probably knows something the dataset does not "
                             "(team news, motivation, a stale price). Verify before considering.")
            if cand["edge"] is not None and cand["edge"] < -0.10:
                gates.append(f"Price implies {round(100 * cand['implied_probability'])}%, well above the model's "
                             f"{round(100 * p)}% — poor value.")
            if cand["score"]["evidence"] < float(settings["min_evidence_score"]):
                gates.append(f"Evidence score {cand['score']['evidence']} below the "
                             f"{float(settings['min_evidence_score']):g} minimum.")
            if any(r["impact"] == "contradicts" and r["reliability"] in ("high", "medium") for r in cand["research"]):
                gates.append("Your research notes contradict this selection.")
        if not cand["accumulator_ok"]:
            gates.append("Whole/quarter line.")
        cand["gates_failed"] = gates
        cand["qualifies"] = not gates
        cand["needs_price"] = cand["qualifies"] and price is None
        tier_total = cand["score"]["total"]
        cand["tier"] = ("strong" if tier_total >= float(settings["strong_selection_score"]) else
                        "acceptable" if tier_total >= float(settings["min_selection_score"]) else "weak")
        out.append(cand)
    out.sort(key=lambda c: (c["qualifies"], c["score"]["evidence"]), reverse=True)
    return out


def score_candidate(c: dict, settings: dict, cross_league: bool, conflict_threshold: float) -> None:
    """Transparent heuristic score (0-100). See docs/SCORING.md for rationale."""
    comp: dict[str, float] = {"probability": 0.0, "agreement": 0.0, "sample": 0.0, "completeness": 0.0,
                              "price": 0.0}
    penalties: list[dict] = []
    flags: list[str] = []
    hr = c["hit_rates"]
    hh, ha = hr["home_team_home"], hr["away_team_away"]
    if min(hh["n"], ha["n"]) < 3:  # venue samples too thin, use last 10 overall
        hh, ha = hr["home_team_last10"], hr["away_team_last10"]
    n_min = min(hh["n"], ha["n"])
    if c["supported"]:
        p = c["probability"]
        lo = c["range_pct"][0] / 100 if c["range_pct"] else p
        conservative = p - 0.5 * (p - lo)  # halfway toward the lower end of the uncertainty range
        comp["probability"] = 40 * clamp((conservative - 0.50) / 0.35)
        if hh["rate"] is not None and ha["rate"] is not None and n_min >= 3:
            mean_hr = (hh["rate"] + ha["rate"]) / 2
            level = clamp((min(hh["rate"], ha["rate"]) - 0.45) / 0.40)
            disagreement = abs(p - mean_hr)
            comp["agreement"] = 20 * level * (1 - clamp((disagreement - 0.10) / 0.25))
            if disagreement > conflict_threshold:
                flags.append("conflict")
                penalties.append({"reason": f"Model {round(100 * p)}% vs historical {round(100 * mean_hr)}%",
                                  "points": -10})
        else:
            flags.append("no_history")
        comp["sample"] = 15 * clamp(n_min / 10)
        of = max(1, min(hh["of"], ha["of"]))
        comp["completeness"] = 10 * clamp(n_min / of) if of else 0
        if c["edge"] is not None:
            comp["price"] = 15 * clamp((c["edge"] + 0.05) / 0.15)
            if c["edge"] > 0.15:
                flags.append("large_disagreement")
                penalties.append({"reason": f"Model exceeds the market by {round(100 * c['edge'])} points — the "
                                            "price may reflect information the dataset lacks (e.g. team news)",
                                  "points": -5})
        if cross_league:
            penalties.append({"reason": "Cross-league strength comparison (approximate)", "points": -8})
        sup = sum(1 for r in c["research"] if r["impact"] == "supports" and r["reliability"] != "low")
        con = sum(1 for r in c["research"] if r["impact"] == "contradicts" and r["reliability"] != "low")
        if sup:
            penalties.append({"reason": f"{sup} research note(s) support this selection", "points": min(6, 3 * sup)})
        if con:
            penalties.append({"reason": f"{con} research note(s) contradict this selection", "points": -10 * con})
    pen = sum(x["points"] for x in penalties)
    evidence = max(0.0, comp["probability"] + comp["agreement"] + comp["sample"] + comp["completeness"] + pen)
    c["score"] = {
        "components": {k: round(v, 1) for k, v in comp.items()},
        "adjustments": penalties,
        "evidence": round(min(85.0, evidence), 1),
        "total": round(min(100.0, evidence + comp["price"]), 1),
        "flags": flags,
        "hit_sample": n_min,
    }
