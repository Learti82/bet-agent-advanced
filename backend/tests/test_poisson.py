import math

import numpy as np
import pytest

from matchedge.config import DEFAULT_SETTINGS
from matchedge.engine.poisson import expected_return, market_probs, score_matrix, settlement


def test_matrix_sums_to_one_and_zero_zero_closed_form():
    m = score_matrix(1.4, 1.1)
    assert m.sum() == pytest.approx(1.0)
    assert m[0, 0] == pytest.approx(math.exp(-2.5), rel=1e-3)


def test_market_probability_identities():
    p = market_probs(score_matrix(1.7, 0.9))
    assert p["home"] + p["draw"] + p["away"] == pytest.approx(1.0)
    assert p["btts_yes"] + p["btts_no"] == pytest.approx(1.0)
    assert p["over_0.5"] == pytest.approx(1 - math.exp(-2.6), rel=1e-3)
    assert p["over_1.5"] > p["over_2.5"] > p["over_3.5"] > p["over_4.5"]
    assert p["dc_1X"] == pytest.approx(p["home"] + p["draw"])
    assert p["dnb_home"] == pytest.approx(p["home"] / (1 - p["draw"]))
    # home team total goals > 0.5 is 1 - P(home scores 0)
    assert p["home_over_0.5"] == pytest.approx(1 - math.exp(-1.7), rel=1e-3)


def test_total_goals_is_poisson_of_sum():
    # sum of independent Poissons is Poisson(λh+λa)
    lam = 2.6
    p = market_probs(score_matrix(1.5, 1.1))
    under25 = sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(3))
    assert p["over_2.5"] == pytest.approx(1 - under25, rel=1e-3)


def test_settlement_half_line_equals_simple_probability():
    m = score_matrix(1.5, 1.2)
    p = market_probs(m)
    d = settlement(m, "AH", "home", -0.5)
    assert d["win"] == pytest.approx(p["home"])
    assert d["push"] == 0
    d = settlement(m, "OU", "over", 2.5)
    assert d["win"] == pytest.approx(p["over_2.5"])


def test_settlement_whole_and_quarter_lines():
    m = score_matrix(1.5, 1.2)
    p = market_probs(m)
    d0 = settlement(m, "AH", "home", 0.0)  # draw no bet
    assert d0["push"] == pytest.approx(p["draw"])
    assert d0["win"] == pytest.approx(p["home"])
    dq = settlement(m, "AH", "home", -0.25)  # draw -> half loss
    assert dq["half_loss"] == pytest.approx(p["draw"])
    assert dq["win"] == pytest.approx(p["home"])
    assert sum(dq.values()) == pytest.approx(1.0)
    ou = settlement(m, "OU", "over", 2.25)  # exactly 2 goals -> half loss
    two = sum(m[h, 2 - h] for h in range(3))
    assert ou["half_loss"] == pytest.approx(two)


def test_expected_return():
    assert expected_return({"win": 0.5, "half_win": 0, "push": 0, "half_loss": 0, "loss": 0.5}, 2.0) == pytest.approx(0)
    assert expected_return({"win": 0, "half_win": 0, "push": 1, "half_loss": 0, "loss": 0}, 3.0) == 0


def test_fit_requires_minimum_sample(loaded):
    _, engine = loaded
    from matchedge.engine.poisson import fit_match
    store = engine.store
    m = next(x for x in store.matches.values() if x["status"] == "scheduled" and x["home"] == "Alpha FC")
    rows = store.history(m["home_key"], m["date_obj"])
    settings = dict(DEFAULT_SETTINGS)
    gm = fit_match(store, rows[:3], store.history(m["away_key"], m["date_obj"]), m["competition"],
                   m["date_obj"], settings, False)
    assert not gm.available
    assert "Insufficient data" in gm.reason


def test_shrinkage_and_ranges(loaded):
    _, engine = loaded
    from matchedge.engine.poisson import fit_match
    store = engine.store
    m = next(x for x in store.matches.values() if x["status"] == "scheduled" and x["home"] == "Alpha FC")
    h, a = store.history(m["home_key"], m["date_obj"]), store.history(m["away_key"], m["date_obj"])
    s = dict(DEFAULT_SETTINGS)
    loose = fit_match(store, h, a, m["competition"], m["date_obj"], s | {"prior_weight": 0.0}, False)
    tight = fit_match(store, h, a, m["competition"], m["date_obj"], s | {"prior_weight": 50.0}, False)
    # a strong home side vs weak away side: heavier shrinkage pulls the expectation toward average
    assert loose.lambda_home - loose.lambda_away > tight.lambda_home - tight.lambda_away
    for k, (lo, hi) in loose.ranges.items():
        assert lo - 1e-9 <= loose.probs[k] <= hi + 1e-9
    cross = fit_match(store, h, a, m["competition"], m["date_obj"], s, True)
    assert abs(cross.lambda_home - cross.lambda_away) < abs(fit_match(store, h, a, m["competition"], m["date_obj"], s, False).lambda_home -
                                                            fit_match(store, h, a, m["competition"], m["date_obj"], s, False).lambda_away)
    assert any("different leagues" in n for n in cross.details["notes"])


def test_goal_cap_limits_extreme_results(loaded):
    _, engine = loaded
    from matchedge.engine.poisson import team_rating
    store = engine.store
    m = next(x for x in store.matches.values() if x["status"] == "scheduled" and x["home"] == "Alpha FC")
    rows = store.history(m["home_key"], m["date_obj"])
    import copy
    blown = copy.deepcopy(rows)
    blown[0].f["goals"] = 12
    s = dict(DEFAULT_SETTINGS)
    before = team_rating(rows, store, m["date_obj"], s, {})
    capped = team_rating(blown, store, m["date_obj"], s, {})
    uncapped = team_rating(blown, store, m["date_obj"], s | {"goal_cap": 99}, {})
    assert capped["attack"] < uncapped["attack"]
    assert capped["capped_scores"] == before["capped_scores"] + 1
