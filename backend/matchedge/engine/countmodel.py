"""Corners and cards model (negative binomial on match totals).

Expected count for each side = average of (team's own "for" rate) and (opponent's "against" rate),
each shrunk toward the competition average with ``prior_weight`` pseudo-matches. Only matches
where the statistic exists are used (missing ≠ 0).

The total is modelled with a negative binomial whose variance/mean ratio is measured from the
competition's own match totals (corners and cards are over-dispersed relative to Poisson). If
the competition sample is too small, a Poisson is used and the output is flagged.

Card counting rule used here: total cards = yellow + red cards as listed in the dataset (a second
yellow that produces a red may be double counted by some sources). Bookmakers often use
different rules (e.g. booking points); check the bookmaker's settlement rule before betting.
"""
from __future__ import annotations

import math

from .data import MatchStore, TeamRow


def _mean(vals):
    v = [x for x in vals if x is not None]
    return (sum(v) / len(v), len(v)) if v else (None, 0)


def nb_sf(line: float, mu: float, var: float) -> float:
    """P(X > line) for X ~ NegBin(mean mu, variance var) (Poisson if var <= mu)."""
    k_max = int(math.floor(line))
    if var <= mu * 1.0001:
        cdf, term = 0.0, math.exp(-mu)
        for k in range(k_max + 1):
            if k > 0:
                term *= mu / k
            cdf += term
        return max(0.0, min(1.0, 1 - cdf))
    r = mu * mu / (var - mu)
    p = r / (r + mu)  # success prob
    cdf = 0.0
    term = p ** r
    for k in range(k_max + 1):
        if k > 0:
            term *= (k - 1 + r) / k * (1 - p)
        cdf += term
    return max(0.0, min(1.0, 1 - cdf))


def _league_profile(store: MatchStore, code: str, before, getter, min_league: int):
    key = ("count", getter.__name__, code, before, min_league)
    if key not in store.memo:
        store.memo[key] = _league_profile_uncached(store, code, before, getter, min_league)
    return store.memo[key]


def _league_profile_uncached(store: MatchStore, code: str, before, getter, min_league: int):
    rows = store.comp_results(code, before)
    vals = [(getter(m, "home"), getter(m, "away")) for m in rows]
    vals = [(h, a) for h, a in vals if h is not None and a is not None]
    src = code
    if len(vals) < min_league:
        pooled = [m for ms in store.by_comp.values() for m in ms if m["date_obj"] < before]
        vals = [(getter(m, "home"), getter(m, "away")) for m in pooled]
        vals = [(h, a) for h, a in vals if h is not None and a is not None]
        src = "pooled"
    if len(vals) < 10:
        return None
    totals = [h + a for h, a in vals]
    mean_t = sum(totals) / len(totals)
    var_t = sum((t - mean_t) ** 2 for t in totals) / (len(totals) - 1)
    return {"home": sum(h for h, _ in vals) / len(vals), "away": sum(a for _, a in vals) / len(vals),
            "total_mean": mean_t, "total_var": var_t, "dispersion": var_t / mean_t if mean_t else 1.0,
            "n": len(vals), "source": src}


def _corner_get(m, side):
    return m.get(f"{side}_corners")


def _card_get(m, side):
    y, r = m.get(f"{side}_yellow"), m.get(f"{side}_red")
    return None if y is None or r is None else y + r


def count_model(kind: str, store: MatchStore, home_rows: list[TeamRow], away_rows: list[TeamRow],
                comp: str, before, settings: dict) -> dict:
    """kind: 'corners' or 'cards'."""
    k = float(settings["prior_weight"])
    min_n = int(settings["min_matches_stat"])
    getter = _corner_get if kind == "corners" else _card_get
    league = _league_profile(store, comp, before, getter, int(settings["min_league_matches"]))

    def f_(r: TeamRow):
        return r.f["corners"] if kind == "corners" else r.cards_for()

    def a_(r: TeamRow):
        return r.a["corners"] if kind == "corners" else r.cards_against()

    h_for, n1 = _mean(f_(r) for r in home_rows if r.venue == "H")
    h_against, n2 = _mean(a_(r) for r in home_rows if r.venue == "H")
    a_for, n3 = _mean(f_(r) for r in away_rows if r.venue == "A")
    a_against, n4 = _mean(a_(r) for r in away_rows if r.venue == "A")
    # fall back to all-venue samples when venue samples are thin
    used_venue = True
    if min(n1, n3) < min_n:
        used_venue = False
        h_for, n1 = _mean(f_(r) for r in home_rows)
        h_against, n2 = _mean(a_(r) for r in home_rows)
        a_for, n3 = _mean(f_(r) for r in away_rows)
        a_against, n4 = _mean(a_(r) for r in away_rows)
    n_home, n_away = min(n1, n2), min(n3, n4)
    label = "corners" if kind == "corners" else "cards"
    if league is None or n_home < min_n or n_away < min_n:
        return {"available": False, "kind": kind,
                "reason": f"Insufficient {label} data: home {n_home}, away {n_away} usable matches "
                          f"(need ≥{min_n}){'' if league else '; no competition baseline'}.",
                "n_home": n_home, "n_away": n_away}

    def shrink(x, n, prior):
        return (n * x + k * prior) / (n + k)

    exp_home = 0.5 * (shrink(h_for, n1, league["home"]) + shrink(a_against, n4, league["home"]))
    exp_away = 0.5 * (shrink(a_for, n3, league["away"]) + shrink(h_against, n2, league["away"]))
    mu = exp_home + exp_away
    var = mu * max(1.0, league["dispersion"])
    lines = [x + 0.5 for x in range(2, 16)] if kind == "corners" else [x + 0.5 for x in range(0, 9)]
    probs = {str(ln): nb_sf(ln, mu, var) for ln in lines}
    # uncertainty: standard error of the expected total from sample sizes
    se = math.sqrt(var / max(1, min(n_home, n_away)))
    ranges = {str(ln): (nb_sf(ln, max(0.1, mu - se), var), nb_sf(ln, mu + se, var)) for ln in lines}
    return {
        "available": True, "kind": kind,
        "label": f"Model estimate (negative binomial on total {label}) — not a verified probability",
        "expected_home": round(exp_home, 2), "expected_away": round(exp_away, 2),
        "expected_total": round(mu, 2), "expected_total_range": [round(mu - se, 2), round(mu + se, 2)],
        "dispersion": round(league["dispersion"], 2),
        "n_home": n_home, "n_away": n_away, "venue_specific": used_venue,
        "league": {k2: (round(v, 2) if isinstance(v, float) else v) for k2, v in league.items()},
        "probs": probs, "ranges": ranges,
        "inputs": {"home_for": round(h_for, 2), "home_against": round(h_against, 2),
                   "away_for": round(a_for, 2), "away_against": round(a_against, 2)},
        "rule_note": None if kind == "corners" else
        "Total cards = yellow + red as listed in the dataset; check the bookmaker's card-counting rule.",
        "referee": "Referee data is not available in the dataset; add it via manual research if relevant.",
    }
