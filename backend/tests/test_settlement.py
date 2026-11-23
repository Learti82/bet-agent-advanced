from matchedge.engine.tracking import settle_market

M = {"ft_home": 2, "ft_away": 1, "ht_home": 1, "ht_away": 0, "home_corners": 6, "away_corners": 4,
     "home_yellow": 2, "away_yellow": 3, "home_red": 0, "away_red": 1}


def test_goal_and_result_markets():
    assert settle_market("1X2", "home", None, M) == "won"
    assert settle_market("1X2", "draw", None, M) == "lost"
    assert settle_market("DC", "X2", None, M) == "lost"
    assert settle_market("OU", "over", 2.5, M) == "won"
    assert settle_market("OU", "under", 3.5, M) == "won"
    assert settle_market("OU", "over", 3.0, M) == "void"
    assert settle_market("BTTS", "yes", None, M) == "won"
    assert settle_market("TG_AWAY", "over", 1.5, M) == "lost"
    assert settle_market("1H_OU", "over", 0.5, M) == "won"
    assert settle_market("CORNERS_OU", "over", 9.5, M) == "won"
    assert settle_market("CARDS_OU", "over", 5.5, M) == "won"


def test_handicaps_and_void():
    draw = {**M, "ft_home": 1, "ft_away": 1}
    assert settle_market("DNB", "home", None, draw) == "void"
    assert settle_market("AH", "home", -0.25, draw) == "half_lost"
    assert settle_market("AH", "away", 0.25, draw) == "half_won"
    assert settle_market("AH", "home", -1.0, M) == "void"
    assert settle_market("AH", "home", -0.75, M) == "half_won"
    assert settle_market("AH", "away", 1.5, M) == "won"


def test_missing_statistic_is_not_guessed():
    no_corners = {**M, "home_corners": None}
    assert settle_market("CORNERS_OU", "over", 9.5, no_corners) is None
    assert settle_market("1H_OU", "over", 0.5, {**M, "ht_home": None}) is None
