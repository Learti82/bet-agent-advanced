from matchedge.engine.stats import rate, stat
from matchedge.importer import nullable_int


def test_missing_values_are_never_zero():
    s = stat([5, None, 7], min_n=3, label="corners")
    assert s["mean"] == 6.0  # not (5+0+7)/3 = 4
    assert s["n"] == 2 and s["of"] == 3
    assert s["completeness"] == 0.667
    assert "Insufficient sample" in s["warning"]


def test_all_missing_returns_none_with_warning():
    s = stat([None, None], label="corners")
    assert s["mean"] is None
    assert "not provided" in s["warning"]


def test_rate_skips_unevaluable_rows():
    class R:
        def __init__(self, v):
            self.v = v
    r = rate([R(1), R(None), R(0), R(1)], lambda x: None if x.v is None else x.v == 1, min_n=2)
    assert (r["k"], r["n"], r["of"]) == (2, 3, 4)
    assert r["rate"] == 0.667


def test_nullable_int():
    assert nullable_int("") is None
    assert nullable_int("  ") is None
    assert nullable_int(None) is None
    assert nullable_int("0") == 0
    assert nullable_int("7") == 7


def test_imported_blank_stats_stay_null(loaded):
    db, _ = loaded
    rows = db.query("SELECT home_corners, away_corners, home_corners_1h FROM matches WHERE status='finished'")
    assert any(r["home_corners"] is None for r in rows)
    assert all(r["home_corners_1h"] is None for r in rows)
    assert not any(r["home_corners"] == 0 and r["away_corners"] is None for r in rows)


def test_profile_reports_sample_sizes(loaded):
    _, engine = loaded
    mid = next(k for k, m in engine.store.matches.items() if m["status"] == "scheduled" and m["home"] == "Alpha FC")
    a = engine.analyze(mid)
    cf = a["profiles"]["home"]["misc_all"]["corners_for"]
    assert cf["n"] < cf["of"]  # some matches lack corners
    assert 0 < cf["completeness"] < 1
