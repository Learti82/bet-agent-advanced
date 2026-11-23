from datetime import datetime, timedelta, timezone

import pytest

from matchedge.engine.accumulator import build, combined_odds, evaluate_ticket, final_opinion

FUTURE = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")


def leg(mid, key="OU|over|2.5", odds=1.5, p=0.7, tier="strong", home="A", away="B", comp="L1", score=70.0,
        **kw):
    base = dict(match_id=mid, key=key, label=key, match_label=f"{home} vs {away}", home=home, away=away,
                home_id=f"X:{home}", away_id=f"X:{away}", competition=comp, competition_name=comp,
                kickoff_utc=FUTURE, kickoff_local="", local_date="2026-12-01", time_certainty="corroborated",
                verified=True, prematch_eligible=True, prematch_status="scheduled", market="OU", family="goals",
                selection="over", line=2.5, odds=odds, bookmaker="Bet365", odds_source="manual",
                odds_checked_at="", probability=p, void_probability=0.0, score=score, tier=tier, qualifies=True,
                gates_failed=[], confidence="high", match_status="candidate", data_quality=80)
    base.update(kw)
    return base


def test_combined_odds_is_product():
    assert combined_odds([1.5, 2.0, 1.25]) == pytest.approx(3.75)
    assert combined_odds([]) == 1.0
    with pytest.raises(ValueError):
        combined_odds([1.5, 1.0])
    with pytest.raises(ValueError):
        combined_odds([1.5, None])


def test_evaluate_reports_probabilities():
    ev = evaluate_ticket([leg("m1", odds=1.5, p=0.7), leg("m2", odds=2.0, p=0.55, home="C", away="D")], 3.0)
    assert ev["combined_odds"] == 3.0
    assert ev["target_reached"] is True
    assert ev["model_probability_all_win"] == pytest.approx(0.385)
    assert ev["bookmaker_implied_probability"] == pytest.approx(1 / 3, abs=1e-5)
    assert ev["valid"]


def test_duplicates_and_same_match_are_errors():
    ev = evaluate_ticket([leg("m1"), leg("m1")], 10)
    assert any("Duplicate" in e for e in ev["errors"])
    ev = evaluate_ticket([leg("m1", key="OU|over|2.5"), leg("m1", key="BTTS|yes|")], 10)
    assert any("same match" in e for e in ev["errors"])
    assert any(c["type"] == "same_match" and c["strength"] == "strong" for c in ev["correlations"])
    assert not ev["valid"]


def test_cross_match_correlations():
    ev = evaluate_ticket([leg("m1", home="A", away="B"), leg("m2", home="A", away="C")], 10)
    assert any(c["type"] == "same_team" for c in ev["correlations"])
    legs = [leg(f"m{i}", home=f"H{i}", away=f"A{i}") for i in range(3)]
    ev = evaluate_ticket(legs, 10)
    assert any(c["type"] == "same_round_same_market" and c["strength"] == "weak" for c in ev["correlations"])


def test_started_or_unpriced_legs_are_rejected():
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev = evaluate_ticket([leg("m1", kickoff_utc=past)], 10)
    assert any("kicked off" in e for e in ev["errors"])
    ev = evaluate_ticket([leg("m1", prematch_eligible=False, prematch_status="completed")], 10)
    assert any("cannot be on a pre-match ticket" in e for e in ev["errors"])
    ev = evaluate_ticket([leg("m1", odds=None)], 10)
    assert any("No price" in e for e in ev["errors"])


def test_snapshot_prices_are_never_called_live():
    ev = evaluate_ticket([leg("m1", odds_source="dataset_snapshot")], 10)
    assert any("not a live price" in w for w in ev["warnings"])
    assert ev["price_sources"] == ["Bet365 (dataset snapshot)"]


def test_builder_never_pads_to_reach_target():
    good = [leg(f"g{i}", odds=1.5, home=f"H{i}", away=f"A{i}", score=80 - i) for i in range(3)]  # 3.375
    weak = [leg(f"w{i}", odds=3.0, p=0.35, tier="weak", home=f"WH{i}", away=f"WA{i}", score=40) for i in range(4)]
    out = build(good, weak, target=110, max_legs=10)
    assert not out["target_reached"]
    assert all(x["tier"] == "strong" for x in out["main"])
    assert combined_odds([x["odds"] for x in out["main"]]) < 110
    assert out["padded"] is not None and combined_odds([x["odds"] for x in out["padded"]]) >= 110
    op = final_opinion(evaluate_ticket(out["main"], 110), 110, evaluate_ticket(out["padded"], 110), None)
    assert "not reachable" in op and "not recommended" in op


def test_builder_trims_and_offers_smaller_alternative():
    good = [leg(f"g{i}", odds=2.0, home=f"H{i}", away=f"A{i}", score=90 - i) for i in range(8)]
    out = build(good, [], target=10, max_legs=10)
    combo = combined_odds([x["odds"] for x in out["main"]])
    assert out["target_reached"] and combo >= 10 and len(out["main"]) == 4
    assert out["alternative"] and len(out["alternative"]) < len(out["main"])


def test_builder_avoids_same_team_twice():
    good = [leg("g1", home="A", away="B", score=90), leg("g2", home="A", away="C", score=85),
            leg("g3", home="D", away="E", score=80)]
    out = build(good, [], target=100, max_legs=10)
    ids = {x["match_id"] for x in out["main"]}
    assert ids == {"g1", "g3"}


def test_empty_ticket_opinion_is_honest():
    assert "No ticket" in final_opinion(evaluate_ticket([], 110), 110, None, None)
