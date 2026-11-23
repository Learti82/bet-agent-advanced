from matchedge.engine.data import TeamRow
from matchedge.engine.markets import fair_implied, hit_predicate, index_odds, is_half_line
from datetime import date


def row(gf, ga, venue="H"):
    return TeamRow("m", "X", date(2026, 1, 1), venue, "t", "o", "Opp",
                   {"goals": gf, "ht_goals": None, "corners": None, "yellow": None, "red": None},
                   {"goals": ga, "ht_goals": None, "corners": None, "yellow": None, "red": None})


def test_hit_predicates_respect_fixture_side():
    win = row(2, 0)
    # home team won its past match -> counts for "home win" from the home side's perspective
    assert hit_predicate("1X2", "home", None, "home")(win) is True
    # the away team's past win counts for "away win" in this fixture
    assert hit_predicate("1X2", "away", None, "away")(win) is True
    assert hit_predicate("TG_AWAY", "over", 0.5, "away")(win) is True
    assert hit_predicate("TG_AWAY", "over", 0.5, "home")(win) is False  # away side of fixture = opponent
    assert hit_predicate("DNB", "home", None, "home")(row(1, 1)) is None  # void ignored
    assert hit_predicate("OU", "over", 2.0, "home")(row(1, 1)) is None  # push ignored
    assert hit_predicate("CORNERS_OU", "over", 9.5, "home")(win) is None  # missing data is not a loss


def test_fair_implied_removes_margin():
    rows = [{"market": "OU", "selection": s, "line": 2.5, "odds": o, "bookmaker": "bet365", "source": "manual",
             "checked_at": "2026-01-01T00:00:00Z"} for s, o in (("over", 1.80), ("under", 2.00))]
    idx = index_odds(rows)
    fair, over = fair_implied("OU", "over", 2.5, rows[0], idx)
    raw = 1 / 1.8
    assert fair < raw
    assert fair == pytest_approx(raw / (1 / 1.8 + 1 / 2.0))
    assert over > 0


def pytest_approx(x):
    import pytest
    return pytest.approx(x, rel=1e-6)


def test_half_lines():
    assert is_half_line(2.5) and is_half_line(-1.5) and is_half_line(None)
    assert not is_half_line(2.0) and not is_half_line(2.25)
