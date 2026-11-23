from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from matchedge.engine.accumulator import build, efficiency, evaluate_ticket, final_opinion
from matchedge.engine.plan import SLOTS, default_weekend_competitions, parse_targets, week_monday
from tests.conftest import make_dataset
from tests.test_accumulator import leg


def next_saturday() -> date:
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    return d


def test_slot_definitions_match_the_weekly_routine():
    by_id = {s["id"]: s for s in SLOTS}
    assert by_id["ucl"]["weekdays"] == [1, 2] and by_id["ucl"]["competitions"] == ["UEFA_1_champions-league"]
    assert by_id["uel_uecl"]["weekdays"] == [3]
    assert set(by_id["uel_uecl"]["competitions"]) == {"UEFA_1_europa-league", "UEFA_1_conference-league"}
    assert by_id["weekend"]["weekdays"] == [5, 6]


def test_targets_and_week_start():
    assert parse_targets("110, 50") == [50.0, 110.0]
    assert parse_targets("") == [50.0, 110.0]
    with pytest.raises(ValueError):
        parse_targets("1,50")
    assert week_monday(date(2026, 11, 26)) == date(2026, 11, 23)  # Thursday -> Monday
    assert week_monday(date(2026, 11, 29)) == date(2026, 11, 23)  # Sunday -> same week


def test_default_weekend_leagues_are_european_top_divisions():
    comps = {"ENG_1_premier-league": {"kind": "league", "tier": "1"}, "ENG_2_championship": {"kind": "league", "tier": "2"},
             "USA_1_mls": {"kind": "league", "tier": "1"}, "UEFA_1_champions-league": {"kind": "international", "tier": "1"},
             "ENG_CUP_fa-cup": {"kind": "cup", "tier": "CUP"}}
    assert default_weekend_competitions(comps) == ["ENG_1_premier-league"]


def test_builder_prefers_cheapest_probability_per_unit_of_odds():
    short = leg("s", odds=1.30, p=0.80, home="A", away="B", score=90)   # cost 0.85
    longer = leg("l", odds=1.90, p=0.70, home="C", away="D", score=70)  # cost 0.56
    assert efficiency(longer) < efficiency(short)
    out = build([short, longer], [], target=1.8, max_legs=5)
    assert [x["match_id"] for x in out["main"]] == ["l"]


def test_leg_limit_is_reported_not_hidden():
    good = [leg(f"g{i}", odds=1.3, home=f"H{i}", away=f"A{i}") for i in range(12)]
    out = build(good, [], target=110, max_legs=5)
    assert out["limit_hit"] and not out["target_reached"] and len(out["main"]) == 5
    op = final_opinion(evaluate_ticket(out["main"], 110), 110, None, None, out["limit_hit"], 5)
    assert "maximum of 5 legs" in op


def test_week_plan_endpoint(tmp_path):
    from matchedge.main import create_app
    sat = next_saturday()
    root = make_dataset(tmp_path / "om", fixture_day=sat)
    c = TestClient(create_app(tmp_path / "plan.sqlite3"))
    assert c.post("/api/import", json={"local_path": str(root)}).status_code == 200
    plan = c.get("/api/plan", params={"week_start": week_monday(sat).isoformat()}).json()
    assert plan["targets"] == [50.0, 110.0]
    slots = {s["id"]: s for s in plan["slots"]}
    assert slots["ucl"]["status"] == "no_fixtures" and slots["uel_uecl"]["status"] == "no_fixtures"
    wk = slots["weekend"]
    assert wk["status"] == "ok" and wk["fixtures"] >= 3 and wk["dates"][0] == sat.isoformat()
    assert [t["target"] for t in wk["tickets"]] == [50.0, 110.0]
    for t in wk["tickets"]:
        assert "final_opinion" in t["report"]
        assert all(leg["odds"] for leg in t["report"]["legs"])  # no unpriced legs ever
    # custom targets and validation
    assert c.get("/api/plan", params={"targets": "30"}).json()["targets"] == [30.0]
    assert c.get("/api/plan", params={"targets": "abc"}).status_code == 422
    # settings: weekend competitions saved as a list
    r = c.put("/api/settings", json={"plan_weekend_competitions": ["ENG_1_premier-league"], "plan_targets": "110,50"})
    assert r.json()["values"]["plan_weekend_competitions"] == "ENG_1_premier-league"
    assert r.json()["values"]["plan_targets"] == "50,110"
    assert c.get("/api/plan/weekend-competitions").json() == ["ENG_1_premier-league"]


def test_model_check_is_walk_forward(loaded):
    _, engine = loaded
    from matchedge.engine.backtest import model_check
    r = model_check(engine.store, engine.db.get_settings(), min_history=3)
    assert r["matches"] > 0
    names = {m["market"] for m in r["markets"]}
    assert {"Over 2.5 goals", "Both teams to score", "Home win"} <= names
    for m in r["markets"]:
        assert 0 <= m["predicted"] <= 1 and 0 <= m["actual"] <= 1
