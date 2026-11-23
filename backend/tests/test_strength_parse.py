from datetime import date, timedelta

import pytest

from matchedge.engine.data import MatchStore
from matchedge.engine.strength import fit_strengths, strength_delta
from matchedge.config import DEFAULT_SETTINGS
from matchedge.oddsparse import Fixture, parse_odds_text, to_decimal


def _m(i, comp, d, h, a, fh, fa):
    return {"id": f"{comp}|{i}", "competition": comp, "date": d.isoformat(), "status": "finished", "home": h, "away": a,
            "home_key": h, "away_key": a, "ft_home": fh, "ft_away": fa, "season": "2627"}


def test_league_strength_learns_from_cross_league_results():
    start = date(2026, 8, 1)
    rows, i = [], 0
    strong, weak = [f"S:{k}" for k in range(4)], [f"W:{k}" for k in range(4)]
    for teams, comp in ((strong, "AAA_1_strong"), (weak, "BBB_1_weak")):
        for r in range(6):
            for k in range(0, 4, 2):
                h, a = teams[(k + r) % 4], teams[(k + r + 1) % 4]
                rows.append(_m(i, comp, start + timedelta(days=7 * r), h, a, 1, 1))
                i += 1
    for r in range(8):  # strong-league teams beat weak-league teams in Europe
        rows.append(_m(i, "UEFA_1_cup", start + timedelta(days=60 + 7 * r), strong[r % 4], weak[r % 4], 3, 0))
        i += 1
    comps = [{"code": "AAA_1_strong", "kind": "league"}, {"code": "BBB_1_weak", "kind": "league"},
             {"code": "UEFA_1_cup", "kind": "international"}]
    store = MatchStore.build(rows, comps)
    fit = fit_strengths(store, dict(DEFAULT_SETTINGS, min_league_matches=5))
    assert fit["n_matches"] == 8
    assert fit["S"]["AAA_1_strong"] > 0.2 > -0.2 > fit["S"]["BBB_1_weak"]
    d = strength_delta(fit, "AAA_1_strong", "BBB_1_weak")
    assert d["delta"] > 0 and d["var"] > 0
    unknown = strength_delta(fit, "AAA_1_strong", "ZZZ_1_none")
    assert unknown["var"] > d["var"]  # a league without cross-league data is uncertain


FX = [Fixture("m1", "Arsenal", "B. Dortmund"), Fixture("m2", "Man Utd", "Brentford")]


def test_price_conversion():
    assert to_decimal("1.80") == 1.8
    assert to_decimal("13/8") == pytest.approx(2.625)
    assert to_decimal("EVS") == 2.0
    assert to_decimal("1.00") is None


def test_single_market_page_layout():
    text = "Arsenal v Dortmund\nFull Time Result\nArsenal\n1.65\nDraw\n4.00\nDortmund\n5.00\nGoals Over/Under\n2.5\nOver\n1.80\nUnder\n2.00"
    r = parse_odds_text(text, FX)
    got = {(x["market"], x["selection"], x["line"]): x["odds"] for x in r.rows}
    assert got == {("1X2", "home", None): 1.65, ("1X2", "draw", None): 4.0, ("1X2", "away", None): 5.0,
                   ("OU", "over", 2.5): 1.8, ("OU", "under", 2.5): 2.0}
    assert all(x["match_id"] == "m1" for x in r.rows)


def test_coupon_layout_and_fractional_prices():
    r = parse_odds_text("Man Utd\nBrentford\n4/5\n11/4\nEVS", FX)
    assert [(x["selection"], x["odds"]) for x in r.rows] == [("home", 1.8), ("draw", 3.75), ("away", 2.0)]


def test_asian_lines_double_chance_btts_and_unsupported():
    text = ("Arsenal v Dortmund\nAsian Handicap\nArsenal -0.5,-1.0 1.95\nDortmund +1.0 1.75\nDouble Chance\n"
            "Arsenal or Draw 1.20\nBoth Teams to Score\nYes 1.72\nCorrect Score\n1-0 7.00")
    r = parse_odds_text(text, FX)
    got = {(x["market"], x["selection"], x["line"]) for x in r.rows}
    assert ("AH", "home", -0.75) in got and ("AH", "away", 1.0) in got
    assert ("DC", "1X", None) in got and ("BTTS", "yes", None) in got
    assert any("Correct Score" in w for w in r.warnings)
    assert any(x["text"] == "1-0 7.00" for x in r.ignored)


def test_nothing_is_guessed_without_a_match():
    r = parse_odds_text("Full Time Result\nArsenal 1.65", FX)
    assert r.rows == [] and r.ignored


def test_parse_and_bulk_save_through_api(tmp_path, dataset):
    from fastapi.testclient import TestClient
    from matchedge.main import create_app
    c = TestClient(create_app(tmp_path / "p.sqlite3"))
    c.post("/api/import", json={"local_path": str(dataset)})
    fx = c.get("/api/fixtures", params={"date_from": (date.today() + timedelta(days=3)).isoformat()}).json()
    f = next(x for x in fx if x["home"] == "Alpha FC")
    parsed = c.post("/api/odds/parse", json={"text": "Match Result\nAlpha 1.50\nDraw 4.20\nHotel 6.00\nTotal Goals\nOver 2.5 1.70",
                                              "match_id": f["id"]}).json()
    assert len(parsed["rows"]) == 4
    saved = c.post("/api/odds/bulk", json={"rows": parsed["rows"] + [{**parsed["rows"][0], "odds": 0.5}],
                                           "bookmaker": "Bet365", "checked_at": "2026-11-23 10:00"}).json()
    assert saved["saved"] == 4 and len(saved["errors"]) == 1
    odds = c.get("/api/odds", params={"match_id": f["id"], "source": "manual"}).json()
    assert {o["odds"] for o in odds} == {1.5, 4.2, 6.0, 1.7}
