"""League strength from cross-league matches (UEFA competitions, domestic cups between divisions).

Team ratings are measured inside each team's own domestic league, so a 1.5 attack rating in the
Eredivisie and in the Premier League mean different things. Each league L gets a strength S_L (log
goal scale). For a match between team i (league Li) and team j (league Lj):

    λ_i = μ_home · att_i · def_j · exp( (S_Li − S_Lj) / 2 )
    λ_j = μ_away · att_j · def_i · exp( (S_Lj − S_Li) / 2 )

S is fitted by penalised Poisson maximum likelihood on all cross-league results before the cut-off
date, with a Normal(0, σ²) prior on every S_L (leagues with few cross-league matches stay near 0 and
carry large uncertainty). The posterior covariance feeds the probability ranges.

Data limitation: the free datasets only contain this season's European matches, so strengths are
re-learned each season from a few hundred matches.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np

from .data import MatchStore, prev_season
from .poisson import league_baseline, team_rating

SIGMA = 0.35


def _ratings(store: MatchStore, tid: str, league: str, before: date, season: str, settings: dict,
             cache: dict) -> dict | None:
    key = (tid, league, before)
    if key not in cache:
        rows = store.history(tid, before, {league}, {season, prev_season(season)})
        cur = [r for r in rows if r.season == season]
        cache[key] = (team_rating(rows, store, before, settings, {}, season)
                      if len(cur) >= 3 or len(rows) >= 8 else None)
    return cache[key]


def cross_matches(store: MatchStore, before: date | None = None,
                  kinds: tuple[str, ...] = ("international",)) -> list[tuple[dict, str, str]]:
    out = []
    for code, ms in store.by_comp.items():
        kind = store.competitions.get(code, {}).get("kind")
        if kind not in kinds:
            continue
        for m in ms:
            if before is not None and m["date_obj"] >= before:
                continue
            season = m.get("season")
            li = store.primary_league(m["home_key"], season)
            lj = store.primary_league(m["away_key"], season)
            if li and lj and li != lj:
                out.append((m, li, lj))
    return out


def fit_strengths(store: MatchStore, settings: dict, before: date | None = None, sigma: float = SIGMA,
                  cache: dict | None = None, kinds: tuple[str, ...] = ("international",)) -> dict:
    cache = {} if cache is None else cache
    rows = []
    for m, li, lj in cross_matches(store, before, kinds):
        season = m.get("season")
        ri = _ratings(store, m["home_key"], li, m["date_obj"], season, settings, cache)
        rj = _ratings(store, m["away_key"], lj, m["date_obj"], season, settings, cache)
        if not ri or not rj:
            continue
        b = league_baseline(store, m["competition"], m["date_obj"], int(settings["min_league_matches"]))
        ci = math.log(b.home * ri["attack"] * rj["defence"])
        cj = math.log(b.away * rj["attack"] * ri["defence"])
        rows.append((li, lj, ci, cj, m["ft_home"], m["ft_away"]))
    leagues = sorted({x for r in rows for x in r[:2]})
    idx = {lg: k for k, lg in enumerate(leagues)}
    n = len(leagues)
    S = np.zeros(n)
    prec = 1 / sigma ** 2
    H = -prec * np.eye(n)
    for _ in range(25):
        g = -prec * S
        H = -prec * np.eye(n)
        for li, lj, ci, cj, yi, yj in rows:
            a, b_ = idx[li], idx[lj]
            x = (S[a] - S[b_]) / 2
            lam_i, lam_j = math.exp(ci + x), math.exp(cj - x)
            r = (yi - lam_i) - (yj - lam_j)
            g[a] += r / 2
            g[b_] -= r / 2
            w = (lam_i + lam_j) / 4
            H[a, a] -= w
            H[b_, b_] -= w
            H[a, b_] += w
            H[b_, a] += w
        step = np.linalg.solve(H, g) if n else np.zeros(0)
        S = S - step
        if n == 0 or np.max(np.abs(step)) < 1e-7:
            break
    cov = np.linalg.inv(-H) if n else np.zeros((0, 0))
    counts: dict[str, int] = {}
    for li, lj, *_ in rows:
        counts[li] = counts.get(li, 0) + 1
        counts[lj] = counts.get(lj, 0) + 1
    return {"leagues": leagues, "S": {lg: float(S[idx[lg]]) for lg in leagues},
            "sd": {lg: float(math.sqrt(cov[idx[lg], idx[lg]])) for lg in leagues},
            "cov": cov, "index": idx, "n_matches": len(rows), "matches_per_league": counts, "sigma": sigma}


def strength_delta(fit: dict, home_league: str, away_league: str) -> dict | None:
    """Δ = S_home − S_away with its variance; leagues without cross-league data count as 0 ± σ."""
    if not fit:
        return None
    idx, cov, sig2 = fit["index"], fit["cov"], fit["sigma"] ** 2

    def s(lg):
        return fit["S"].get(lg, 0.0)

    def var(lg):
        return cov[idx[lg], idx[lg]] if lg in idx else sig2

    c = cov[idx[home_league], idx[away_league]] if home_league in idx and away_league in idx else 0.0
    return {"delta": s(home_league) - s(away_league), "var": max(0.0, var(home_league) + var(away_league) - 2 * c),
            "home_league": home_league, "away_league": away_league,
            "home_s": s(home_league), "away_s": s(away_league),
            "home_n": fit["matches_per_league"].get(home_league, 0), "away_n": fit["matches_per_league"].get(away_league, 0)}


def table(fit: dict, names: dict[str, str]) -> list[dict]:
    return sorted(({"league": lg, "name": names.get(lg, lg), "strength": round(fit["S"][lg], 3),
                    "sd": round(fit["sd"][lg], 3), "matches": fit["matches_per_league"].get(lg, 0),
                    "goal_factor": round(math.exp(fit["S"][lg]), 2)} for lg in fit["leagues"]),
                  key=lambda r: -r["strength"])
