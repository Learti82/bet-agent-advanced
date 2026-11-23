"""Basic independent-Poisson goal model with explicit safeguards.

Method (documented in docs/MODEL.md):

1. League baseline: mean home goals ``μH`` and away goals ``μA`` of the competition's finished
   matches *before* the fixture date. Fewer than ``min_league_matches`` → pooled baseline from
   all competitions (flagged).
2. Team ratings, venue-adjusted and relative to the competition each match was played in:
       attack  = Σ wᵢ · min(goals_forᵢ, cap) / μ(venue, compᵢ)
       defence = Σ wᵢ · min(goals_againstᵢ, cap) / μ(opposite venue, compᵢ)
   with recency weights ``wᵢ = 0.5^(i / half_life)`` (i = 0 is the latest match).
3. Shrinkage toward league average (1.0) with ``prior_weight`` pseudo-matches:
       rating = (Σ wᵢ·ratioᵢ + k) / (Σ wᵢ + k)
   which protects small samples, newly promoted teams and early-season noise.
4. Expected goals:  λ_home = att_H · def_A · μH ,  λ_away = att_A · def_H · μA.
5. Cross-league fixtures (UEFA, cups between tiers): ratings measured in different leagues are not
   directly comparable, so their deviation from 1.0 is multiplied by ``cross_league_shrink`` and the
   output is labelled an approximation.
6. Uncertainty: each λ gets a relative error ``e = sqrt(1/(G_for+kμ) + 1/(G_against+kμ))`` from the
   (weighted) goal counts behind it plus the prior's pseudo-goals; every probability is re-evaluated at λ·(1±e) and reported as a
   range. Point estimates are rounded to whole percentages.

These are *model estimates*, not facts or validated betting probabilities.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product

import numpy as np

from .data import MatchStore, TeamRow

MAX_GOALS = 10


@dataclass
class Baseline:
    home: float
    away: float
    n: int
    source: str  # competition code or "pooled"


def league_baseline(store: MatchStore, code: str, before, min_matches: int) -> Baseline:
    key = ("baseline", code, before, min_matches)
    if key not in store.memo:
        store.memo[key] = _league_baseline(store, code, before, min_matches)
    return store.memo[key]


def _league_baseline(store: MatchStore, code: str, before, min_matches: int) -> Baseline:
    rows = store.comp_results(code, before)
    if len(rows) >= min_matches:
        return Baseline(sum(m["ft_home"] for m in rows) / len(rows),
                        sum(m["ft_away"] for m in rows) / len(rows), len(rows), code)
    pooled = [m for ms in store.by_comp.values() for m in ms if m["date_obj"] < before]
    if not pooled:
        return Baseline(1.45, 1.15, 0, "default")
    return Baseline(sum(m["ft_home"] for m in pooled) / len(pooled),
                    sum(m["ft_away"] for m in pooled) / len(pooled), len(pooled), "pooled")


def first_half_share(store: MatchStore, code: str, before, min_matches: int) -> tuple[float | None, int, str]:
    """Share of goals scored before half-time, from matches with half-time scores."""
    key = ("ht_share", code, before, min_matches)
    if key not in store.memo:
        store.memo[key] = _first_half_share(store, code, before, min_matches)
    return store.memo[key]


def _first_half_share(store: MatchStore, code: str, before, min_matches: int) -> tuple[float | None, int, str]:
    def share(rows):
        rows = [m for m in rows if m.get("ht_home") is not None and m.get("ht_away") is not None]
        ft = sum(m["ft_home"] + m["ft_away"] for m in rows)
        ht = sum(m["ht_home"] + m["ht_away"] for m in rows)
        return (ht / ft if ft else None), len(rows)

    s, n = share(store.comp_results(code, before))
    if s is not None and n >= min_matches:
        return s, n, code
    s, n = share([m for ms in store.by_comp.values() for m in ms if m["date_obj"] < before])
    if s is not None and n >= min_matches:
        return s, n, "pooled"
    return None, n, "unavailable"


def team_rating(rows: list[TeamRow], store: MatchStore, before, settings: dict,
                cache: dict[str, Baseline]) -> dict:
    half_life = float(settings["recency_half_life"])
    k = float(settings["prior_weight"])
    cap = int(settings["goal_cap"])
    min_league = int(settings["min_league_matches"])
    sw = sw2 = att_num = def_num = g_for = g_against = 0.0
    capped = 0
    for i, r in enumerate(rows):
        if r.competition not in cache:
            cache[r.competition] = league_baseline(store, r.competition, before, min_league)
        b = cache[r.competition]
        mu_for, mu_against = (b.home, b.away) if r.venue == "H" else (b.away, b.home)
        w = 0.5 ** (i / half_life) if half_life > 0 else 1.0
        gf, ga = min(r.gf, cap), min(r.ga, cap)
        capped += int(r.gf > cap) + int(r.ga > cap)
        att_num += w * gf / mu_for
        def_num += w * ga / mu_against
        g_for += w * gf
        g_against += w * ga
        sw += w
        sw2 += w * w
    n_eff = (sw * sw / sw2) if sw2 else 0.0
    return {
        "n": len(rows),
        "n_eff": round(n_eff, 2),
        "attack": (att_num + k) / (sw + k),
        "defence": (def_num + k) / (sw + k),
        "attack_raw": att_num / sw if sw else None,
        "defence_raw": def_num / sw if sw else None,
        "weighted_goals_for": g_for,
        "weighted_goals_against": g_against,
        "capped_scores": capped,
    }


def score_matrix(lh: float, la: float, max_goals: int = MAX_GOALS) -> np.ndarray:
    i = np.arange(max_goals + 1)
    ph = np.exp(-lh) * lh ** i / np.array([math.factorial(x) for x in i])
    pa = np.exp(-la) * la ** i / np.array([math.factorial(x) for x in i])
    m = np.outer(ph, pa)
    return m / m.sum()


def market_probs(m: np.ndarray) -> dict[str, float]:
    n = m.shape[0]
    hg, ag = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    tot = hg + ag
    p = {
        "home": float(m[hg > ag].sum()), "draw": float(np.trace(m)), "away": float(m[hg < ag].sum()),
        "btts_yes": float(m[(hg > 0) & (ag > 0)].sum()),
    }
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        p[f"over_{line}"] = float(m[tot > line].sum())
    for line in (0.5, 1.5, 2.5):
        p[f"home_over_{line}"] = float(m[hg > line].sum())
        p[f"away_over_{line}"] = float(m[ag > line].sum())
    p["btts_no"] = 1 - p["btts_yes"]
    p["dc_1X"], p["dc_X2"], p["dc_12"] = p["home"] + p["draw"], p["away"] + p["draw"], p["home"] + p["away"]
    nd = 1 - p["draw"]
    p["dnb_home"] = p["home"] / nd if nd > 0 else 0.0
    p["dnb_away"] = p["away"] / nd if nd > 0 else 0.0
    return p


def settlement(m: np.ndarray, kind: str, side: str, line: float) -> dict[str, float]:
    """Outcome distribution for Asian handicap (kind='AH') or goal totals (kind='OU').

    Handles half, whole and quarter lines. Returns probabilities of win/half_win/push/half_loss/loss.
    """
    n = m.shape[0]
    out = {"win": 0.0, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "loss": 0.0}
    frac = round(abs(line) * 4) % 4  # 0 whole, 2 half, 1/3 quarter
    lines = [line] if frac in (0, 2) else [line - 0.25 * math.copysign(1, line or 1), line + 0.25 * math.copysign(1, line or 1)]
    for h, a in product(range(n), range(n)):
        p = float(m[h, a])
        if p == 0:
            continue
        res = []
        for ln in lines:
            if kind == "AH":
                margin = (h - a if side == "home" else a - h) + ln
            else:
                margin = (h + a - ln) if side == "over" else (ln - (h + a))
            res.append(1 if margin > 1e-9 else -1 if margin < -1e-9 else 0)
        if len(res) == 1:
            out["win" if res[0] == 1 else "loss" if res[0] == -1 else "push"] += p
        else:
            s = sum(res)
            out[{2: "win", 1: "half_win", 0: "push", -1: "half_loss", -2: "loss"}[s]] += p
    return out


def expected_return(dist: dict[str, float], odds: float) -> float:
    """Expected profit per unit stake."""
    return (dist["win"] * (odds - 1) + dist["half_win"] * (odds - 1) / 2
            - dist["half_loss"] / 2 - dist["loss"])


@dataclass
class GoalModel:
    available: bool
    reason: str | None
    lambda_home: float | None = None
    lambda_away: float | None = None
    rel_error_home: float | None = None
    rel_error_away: float | None = None
    probs: dict[str, float] | None = None
    ranges: dict[str, tuple[float, float]] | None = None
    first_half: dict | None = None
    details: dict | None = None
    matrix: np.ndarray | None = None
    variants: list | None = None  # score matrices at λ·(1±e), for uncertainty of any market

    def to_dict(self) -> dict:
        def pct(x):
            return None if x is None else round(100 * x)

        return {
            "available": self.available,
            "reason": self.reason,
            "label": "Model estimate (independent Poisson) — not a verified probability",
            "expected_goals": None if not self.available else {
                "home": round(self.lambda_home, 2), "away": round(self.lambda_away, 2),
                "total": round(self.lambda_home + self.lambda_away, 2),
                "home_range": [round(self.lambda_home * (1 - self.rel_error_home), 2),
                               round(self.lambda_home * (1 + self.rel_error_home), 2)],
                "away_range": [round(self.lambda_away * (1 - self.rel_error_away), 2),
                               round(self.lambda_away * (1 + self.rel_error_away), 2)],
            },
            "probabilities_pct": None if not self.probs else {k: pct(v) for k, v in self.probs.items()},
            "ranges_pct": None if not self.ranges else {k: [pct(a), pct(b)] for k, (a, b) in self.ranges.items()},
            "first_half": self.first_half,
            "details": self.details,
        }


def fit_match(store: MatchStore, home_rows: list[TeamRow], away_rows: list[TeamRow], comp: str, before,
              settings: dict, cross_league: bool) -> GoalModel:
    min_n = int(settings["min_matches_model"])
    if len(home_rows) < min_n or len(away_rows) < min_n:
        return GoalModel(False, f"Insufficient data: model needs ≥{min_n} matches per team "
                                f"(home {len(home_rows)}, away {len(away_rows)}).")
    cache: dict[str, Baseline] = {}
    base = league_baseline(store, comp, before, int(settings["min_league_matches"]))
    rh = team_rating(home_rows, store, before, settings, cache)
    ra = team_rating(away_rows, store, before, settings, cache)
    s = float(settings["cross_league_shrink"]) if cross_league else 1.0
    att_h, def_h = 1 + s * (rh["attack"] - 1), 1 + s * (rh["defence"] - 1)
    att_a, def_a = 1 + s * (ra["attack"] - 1), 1 + s * (ra["defence"] - 1)
    lh = att_h * def_a * base.home
    la = att_a * def_h * base.away
    # Relative standard error of each λ: Poisson counting error of the (weighted) goals behind each
    # rating, including the k pseudo-matches of the shrinkage prior (Gamma-Poisson posterior).
    kh, ka = float(settings["prior_weight"]) * base.home, float(settings["prior_weight"]) * base.away
    eh = min(0.6, math.sqrt(1 / (rh["weighted_goals_for"] + kh) + 1 / (ra["weighted_goals_against"] + kh)))
    ea = min(0.6, math.sqrt(1 / (ra["weighted_goals_for"] + ka) + 1 / (rh["weighted_goals_against"] + ka)))
    mat = score_matrix(lh, la)
    probs = market_probs(mat)
    variant_mats = [score_matrix(lh * fh, la * fa) for fh in (1 - eh, 1 + eh) for fa in (1 - ea, 1 + ea)]
    variants = [market_probs(vm) for vm in variant_mats]
    ranges = {k: (min(v[k] for v in variants + [probs]), max(v[k] for v in variants + [probs])) for k in probs}

    share, n_ht, ht_src = first_half_share(store, comp, before, int(settings["min_league_matches"]))
    first_half = None
    if share is not None:
        m1 = score_matrix(lh * share, la * share)
        p1 = market_probs(m1)
        first_half = {
            "available": True, "share_of_goals_before_ht": round(share, 3), "n_matches": n_ht,
            "baseline_source": ht_src,
            "expected_goals": round((lh + la) * share, 2),
            "over_0.5_pct": round(100 * p1["over_0.5"]), "over_1.5_pct": round(100 * p1["over_1.5"]),
            "probs": {"over_0.5": p1["over_0.5"], "over_1.5": p1["over_1.5"]},
            "note": "First-half λ = full-match λ × competition first-half goal share (approximation).",
        }
    else:
        first_half = {"available": False, "reason": "Not enough half-time scores to estimate first-half goals."}

    notes = []
    if base.source != comp:
        notes.append(f"Competition has fewer than {settings['min_league_matches']} results; "
                     f"baseline uses {base.source} data ({base.n} matches).")
    if cross_league:
        notes.append("Teams' ratings come from different leagues; strengths were shrunk by "
                     f"{int(100 * (1 - s))}% toward average because cross-league strength is not calibrated.")
    if rh["capped_scores"] or ra["capped_scores"]:
        notes.append(f"Extreme scores capped at {settings['goal_cap']} goals when estimating ratings "
                     f"({rh['capped_scores'] + ra['capped_scores']} team-scores affected).")
    if min(rh["n"], ra["n"]) < 8:
        notes.append("Small sample: ratings are heavily shrunk toward league average.")

    details = {
        "baseline": {"home_goals": round(base.home, 2), "away_goals": round(base.away, 2),
                     "n_matches": base.n, "source": base.source},
        "home": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in rh.items()},
        "away": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in ra.items()},
        "applied": {"home_attack": round(att_h, 3), "home_defence": round(def_h, 3),
                    "away_attack": round(att_a, 3), "away_defence": round(def_a, 3)},
        "cross_league": cross_league,
        "settings": {k: settings[k] for k in ("recency_half_life", "prior_weight", "goal_cap",
                                              "min_matches_model", "cross_league_shrink")},
        "notes": notes,
    }
    return GoalModel(True, None, lh, la, eh, ea, probs, ranges, first_half, details, mat, variant_mats)
