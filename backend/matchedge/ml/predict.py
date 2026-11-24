"""Use the trained models in the live analysis and in the plan backtest.

For a domestic-league fixture in a covered division, the ML model gives P(home/draw/away),
P(over 2.5) and P(both teams score). To keep every other goal market consistent (Over 1.5/3.5, team
totals, Asian handicaps, double chance…), the expected goals (λ_home, λ_away) are re-fitted so that the
Poisson score matrix reproduces the ML's home-minus-away probability and Over 2.5 probability; the
directly modelled markets then use the ML values exactly.

Uncertainty range = ML value ± max(2 points, half the gap between ML and the statistical engine),
i.e. it widens when the two methods disagree. These are model estimates, not verified probabilities.
"""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, timedelta

import numpy as np

from .. import config
from ..history import DIVISIONS
from .features import FeatureBuilder, fair_probs
from .train import ENGINE_FEATURES, VARIANTS, engine_feature_values

COVERED = set(DIVISIONS.values())


def fit_lambdas(target_diff: float, target_o25: float, lh0: float, la0: float) -> tuple[float, float]:
    from ..engine.poisson import market_probs, score_matrix

    def f(x):
        p = market_probs(score_matrix(math.exp(x[0]), math.exp(x[1])))
        return np.array([p["home"] - p["away"] - target_diff, p["over_2.5"] - target_o25])

    x = np.log([max(0.05, lh0), max(0.05, la0)])
    for _ in range(25):
        fx = f(x)
        if np.max(np.abs(fx)) < 1e-5:
            break
        J = np.zeros((2, 2))
        for j in range(2):
            d = np.zeros(2)
            d[j] = 1e-4
            J[:, j] = (f(x + d) - fx) / 1e-4
        try:
            step = np.linalg.solve(J, fx)
        except np.linalg.LinAlgError:
            break
        x = x - np.clip(step, -0.5, 0.5)
    return float(math.exp(x[0])), float(math.exp(x[1]))


def apply_ml(goals, ml: dict):
    """Return a copy of a GoalModel whose probabilities come from the ML prediction ``ml``."""
    from ..engine.poisson import market_probs, score_matrix
    if not goals.available:
        return goals
    old = goals.probs
    ph, pd, pa = ml.get("p_h"), ml.get("p_d"), ml.get("p_a")
    po = ml.get("p_o25")
    if None in (ph, pd, pa, po):
        return goals
    lh, la = fit_lambdas(ph - pa, po, goals.lambda_home, goals.lambda_away)
    mat = score_matrix(lh, la)
    probs = market_probs(mat)
    direct = {"home": ph, "draw": pd, "away": pa, "over_2.5": po}
    if ml.get("p_btts") is not None:
        direct["btts_yes"] = ml["p_btts"]
    probs.update(direct)
    probs["btts_no"] = 1 - probs["btts_yes"]
    probs["dc_1X"], probs["dc_X2"], probs["dc_12"] = ph + pd, pa + pd, ph + pa
    probs["dnb_home"], probs["dnb_away"] = ph / (1 - pd), pa / (1 - pd)
    ranges = {}
    for k, v in probs.items():
        w = max(0.02, abs(v - old.get(k, v)) / 2)
        ranges[k] = (max(0.0, v - w), min(1.0, v + w))
    details = dict(goals.details or {})
    details["engine"] = "ml"
    details["ml"] = {"variant": ml.get("variant"), "lambda_home": round(lh, 2), "lambda_away": round(la, 2),
                     "statistical_engine": {k: round(old[k], 3) for k in ("home", "draw", "away", "over_2.5", "btts_yes")},
                     "ml": {k: round(probs[k], 3) for k in ("home", "draw", "away", "over_2.5", "btts_yes")}}
    details["notes"] = list(details.get("notes", [])) + [
        f"Probabilities from the trained ML model ({'statistics + Bet365 prices' if ml.get('variant') == 'market' else 'statistics only'}); "
        f"other goal markets derived from re-fitted expected goals {lh:.2f}–{la:.2f}. Range = gap to the statistical engine."]
    fh = goals.first_half
    if fh and fh.get("available"):
        share = fh["share_of_goals_before_ht"]
        p1 = market_probs(score_matrix(lh * share, la * share))
        fh = dict(fh, expected_goals=round((lh + la) * share, 2), probs={"over_0.5": p1["over_0.5"], "over_1.5": p1["over_1.5"]},
                  **{"over_0.5_pct": round(100 * p1["over_0.5"]), "over_1.5_pct": round(100 * p1["over_1.5"])})
    return replace(goals, lambda_home=lh, lambda_away=la, probs=probs, ranges=ranges, details=details, matrix=mat,
                   variants=[goals.matrix, mat], first_half=fh)


def odds_market_features(odds_rows: list[dict], bookmaker: str = "bet365") -> dict:
    """Bet365 1X2 / Over-Under 2.5 / main Asian line for a fixture, manual entries first."""
    def best(market, sel, line=None):
        rows = [r for r in odds_rows if r["market"] == market and r["selection"] == sel and r["bookmaker"].lower() == bookmaker
                and (line is None or (r["line"] is not None and abs(r["line"] - line) < 1e-9))]
        if not rows:
            return None
        rows.sort(key=lambda r: (r["source"] == "manual", r["checked_at"] or ""), reverse=True)
        return rows[0]["odds"]

    out = {"b365_h": best("1X2", "home"), "b365_d": best("1X2", "draw"), "b365_a": best("1X2", "away"),
           "b365_o25": best("OU", "over", 2.5), "b365_u25": best("OU", "under", 2.5), "ah_line": None}
    ah_home = [r for r in odds_rows if r["market"] == "AH" and r["selection"] == "home" and r["bookmaker"].lower() == bookmaker]
    best_gap = None
    for r in ah_home:
        away = best("AH", "away", -r["line"]) if r["line"] is not None else None
        if away and (best_gap is None or abs(r["odds"] - away) < best_gap):
            best_gap, out["ah_line"] = abs(r["odds"] - away), r["line"]
    return out


class MLPredictor:
    def __init__(self, bundle: dict, builder: FeatureBuilder):
        self.models = bundle["models"]
        self.meta = bundle["meta"]
        self.builder = builder

    @classmethod
    def load(cls, db, store, path=None) -> "MLPredictor | None":
        from . import train as train_mod
        path = path or train_mod.MODEL_PATH  # resolved at call time (tests and custom data dirs)
        if not path.exists():
            return None
        import joblib
        bundle = joblib.load(path)
        return cls(bundle, live_builder(db, store))

    def covers(self, m: dict) -> bool:
        return m["competition"] in COVERED

    def predict(self, m: dict, goals, odds_rows: list[dict], settings: dict) -> dict | None:
        if not self.covers(m) or not goals.available:
            return None
        row = {"competition": m["competition"], "season": m.get("season") or config.SEASON, "date": m["date"],
               "home_key": m["home_key"], "away_key": m["away_key"], **odds_market_features(odds_rows)}
        f = self.builder.features(row)
        if f["n_h"] < 3 or f["n_a"] < 3:
            return None
        f.update(engine_feature_values(goals))
        has_market = fair_probs(row["b365_h"], row["b365_d"], row["b365_a"]) and fair_probs(row["b365_o25"], row["b365_u25"])
        variant = "market" if has_market else "stats"
        use = self.meta.get("use_ml", {})
        x = np.array([[f.get(n, float("nan")) for n in VARIANTS[variant]]], dtype=float)
        out = {"variant": variant}
        if use.get("y_1x2", {}).get(variant):
            p = self.models[("y_1x2", variant)].predict_proba(x)[0]
            out.update(p_h=float(p[0]), p_d=float(p[1]), p_a=float(p[2]))
        else:
            out.update(p_h=goals.probs["home"], p_d=goals.probs["draw"], p_a=goals.probs["away"])
        out["p_o25"] = (float(self.models[("y_o25", variant)].predict_proba(x)[0, 1]) if use.get("y_o25", {}).get(variant)
                        else goals.probs["over_2.5"])
        out["p_btts"] = (float(self.models[("y_btts", variant)].predict_proba(x)[0, 1]) if use.get("y_btts", {}).get(variant)
                         else goals.probs["btts_yes"])
        return out


def live_builder(db, store) -> FeatureBuilder:
    """Feature state after every finished match: football-data seasons, topped up with newer
    Open-Matchday results of the current season that football-data does not have yet."""
    fb = FeatureBuilder()
    hist = db.query("SELECT * FROM hist_matches")
    seen = {(r["competition"], r["home_key"], r["away_key"], r["date"]) for r in hist}
    extra = []
    for m in store.matches.values():
        if (m["status"] == "finished" and not m["id"].startswith("FD|") and m["competition"] in COVERED
                and m.get("ft_home") is not None):
            d = date.fromisoformat(m["date"])
            near = {(d + timedelta(days=k)).isoformat() for k in (-1, 0, 1)}
            if not any((m["competition"], m["home_key"], m["away_key"], x) in seen for x in near):
                extra.append({**m, "season": m.get("season") or config.SEASON})
    for r in sorted(hist + extra, key=lambda x: (x["date"], x["id"])):
        if r.get("ft_home") is not None and r.get("ft_away") is not None:
            fb.update(r)
    return fb


__all__ = ["MLPredictor", "apply_ml", "fit_lambdas", "odds_market_features", "ENGINE_FEATURES"]
