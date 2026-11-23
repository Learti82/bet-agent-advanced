"""Walk-forward model check on this season's finished league matches.

For each finished match, the goal model is fitted using only matches played *before* it, exactly as
it would have been pre-match, and its probabilities are compared with what happened. This measures
calibration (does "80%" happen 80% of the time?) without any look-ahead. It says nothing about
profitability against bookmaker prices, which are not available historically in the dataset.
"""
from __future__ import annotations

import math

from .poisson import fit_match, settlement

MARKETS = {
    "Over 2.5 goals": (lambda g: g.probs["over_2.5"], lambda h, a: h + a > 2.5),
    "Under 3.5 goals": (lambda g: 1 - g.probs["over_3.5"], lambda h, a: h + a < 3.5),
    "Under 4.5 goals": (lambda g: 1 - g.probs["over_4.5"], lambda h, a: h + a < 4.5),
    "Both teams to score": (lambda g: g.probs["btts_yes"], lambda h, a: h > 0 and a > 0),
    "Home win": (lambda g: g.probs["home"], lambda h, a: h > a),
    "Away win": (lambda g: g.probs["away"], lambda h, a: a > h),
    "Double chance 1X": (lambda g: g.probs["dc_1X"], lambda h, a: h >= a),
    "Double chance X2": (lambda g: g.probs["dc_X2"], lambda h, a: a >= h),
    "Away +1.5 handicap": (lambda g: settlement(g.matrix, "AH", "away", 1.5)["win"], lambda h, a: a - h + 1.5 > 0),
}
BINS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0001)]


def model_check(store, settings: dict, min_history: int = 6, season: str | None = None,
                use_history: bool = True) -> dict:
    """Walk-forward predictions for ``season`` (default: the current one)."""
    from .. import config
    from .data import prev_season
    season = season or config.SEASON
    seasons = {season, prev_season(season)} if use_history else {season}
    data: dict[str, list[tuple[float, bool]]] = {k: [] for k in MARKETS}
    n_matches = 0
    for code, ms in store.by_comp.items():
        if store.competitions.get(code, {}).get("kind", "league") != "league":
            continue
        for m in ms:
            if m.get("season") != season:
                continue
            cur_h = store.history(m["home_key"], m["date_obj"], {code}, {season})
            cur_a = store.history(m["away_key"], m["date_obj"], {code}, {season})
            if len(cur_h) < min_history or len(cur_a) < min_history:
                continue
            hr = store.history(m["home_key"], m["date_obj"], {code}, seasons)
            ar = store.history(m["away_key"], m["date_obj"], {code}, seasons)
            g = fit_match(store, hr, ar, code, m["date_obj"], settings, False, season)
            if not g.available:
                continue
            n_matches += 1
            for k, (pf, of) in MARKETS.items():
                data[k].append((pf(g), bool(of(m["ft_home"], m["ft_away"]))))
    markets = []
    all_pairs: list[tuple[float, bool]] = []
    for k, pairs in data.items():
        all_pairs += pairs
        if not pairs:
            continue
        bins = []
        for lo, hi in BINS:
            b = [(p, o) for p, o in pairs if lo <= p < hi]
            if len(b) < 20:
                continue
            act = sum(o for _, o in b) / len(b)
            se = math.sqrt(max(act * (1 - act), 1e-9) / len(b))
            bins.append({"range": f"{round(100 * lo)}–{min(100, round(100 * hi))}%", "n": len(b),
                         "predicted": round(sum(p for p, _ in b) / len(b), 3), "actual": round(act, 3),
                         "actual_low": round(max(0.0, act - 1.96 * se), 3), "actual_high": round(min(1.0, act + 1.96 * se), 3)})
        markets.append({"market": k, "n": len(pairs), "predicted": round(sum(p for p, _ in pairs) / len(pairs), 3),
                        "actual": round(sum(o for _, o in pairs) / len(pairs), 3), "bins": bins})
    hi = [(p, o) for p, o in all_pairs if p >= 0.8]
    ll = (sum(-math.log(min(max(p, 1e-4), 1 - 1e-4) if o else 1 - min(max(p, 1e-4), 1 - 1e-4)) for p, o in all_pairs)
          / len(all_pairs)) if all_pairs else None
    return {
        "matches": n_matches,
        "log_loss": None if ll is None else round(ll, 4),
        "high_confidence": None if not hi else {
            "n": len(hi), "predicted": round(sum(p for p, _ in hi) / len(hi), 3),
            "actual": round(sum(o for _, o in hi) / len(hi), 3)},
        "markets": markets,
        "season": season, "uses_previous_season": use_history,
        "settings": {k: settings.get(k) for k in ("prior_weight", "recency_half_life", "goal_cap", "history_carryover")},
        "note": "Walk-forward: each prediction uses only earlier matches. In-season data only; bookmaker prices "
                "are not available historically, so this checks calibration, not profitability.",
    }
