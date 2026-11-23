"""football-data importer, name linking, previous-season history, CLV and the profit backtest (offline)."""
import csv
import io
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from matchedge.engine.analysis import Engine
from matchedge.history import CURRENT_SEASON, import_history, parse_file, season_codes
from matchedge.importer import import_from_directory
from tests.conftest import TEAMS, make_dataset

FD_HEADER = ["Div", "Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "HTHG", "HTAG", "HS", "AS", "HST",
             "AST", "HC", "AC", "HY", "AY", "HR", "AR", "B365H", "B365D", "B365A", "B365>2.5", "B365<2.5", "AHh",
             "B365AHH", "B365AHA", "B365CH", "B365CD", "B365CA", "B365C>2.5", "B365C<2.5", "AHCh", "B365CAHH", "B365CAHA"]
RENAME = {"Bravo United": "Bravo Utd", "Golf Wanderers": "Golf W"}  # football-data spells some clubs differently


def fd_csv(rows):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(FD_HEADER)
    for r in rows:
        w.writerow(r)
    return out.getvalue().encode()


def fd_row(d, h, a, fh, fa, odds=True):
    dd = date.fromisoformat(d).strftime("%d/%m/%Y")
    o = [1.9, 3.4, 4.2, 1.85, 1.95, -0.5, 1.92, 1.92, 1.95, 3.3, 4.0, 1.8, 2.0, -0.5, 1.9, 1.95] if odds else [""] * 16
    return ["E0", dd, "15:00", h, a, fh, fa, "H" if fh > fa else "D" if fh == fa else "A", "", "", 10, 9, 4, 3, 5, 4,
            1, 2, 0, 0, *o]


@pytest.fixture()
def hist_setup(tmp_path, db):
    root = make_dataset(tmp_path / "om")
    import_from_directory(db, root)
    om = db.query("SELECT * FROM matches WHERE status='finished' AND competition='ENG_1_premier-league'")
    current = [fd_row(m["date"], RENAME.get(m["home"], m["home"]), RENAME.get(m["away"], m["away"]), m["ft_home"],
                      m["ft_away"]) for m in om]
    rng = random.Random(7)
    prev_start = date.fromisoformat(min(m["date"] for m in om)) - timedelta(days=300)
    prev = []
    for k in range(60):
        h, a = rng.sample(TEAMS, 2)
        prev.append(fd_row((prev_start + timedelta(days=3 * k)).isoformat(), RENAME.get(h, h), RENAME.get(a, a),
                           rng.randint(0, 3), rng.randint(0, 3)))
    files = {f"{CURRENT_SEASON}/E0.csv": fd_csv(current), f"{season_codes(1)[1]}/E0.csv": fd_csv(prev)}

    def fetch(url):
        import urllib.error
        key = "/".join(url.split("/")[-2:])
        if key in files:
            return files[key]
        raise urllib.error.HTTPError(url, 404, "nf", None, None)

    summary = import_history(db, 1, fetch=fetch, log=lambda m: None, dest=tmp_path / "fd")
    return db, summary, om


def test_season_codes():
    assert season_codes(2, "2627") == ["2627", "2526", "2425"]


def test_parse_file_keeps_blanks_null():
    rows = parse_file(fd_csv([fd_row("2026-08-20", "A", "B", 1, 0, odds=False)]).decode(), "2627", "E0")
    assert rows[0]["b365_h"] is None and rows[0]["ht_home"] is None and rows[0]["home_corners"] == 5


def test_names_linked_by_identical_matches(hist_setup):
    db, summary, _ = hist_setup
    assert summary["unlinked_current_teams"] == []
    keys = {r["home_key"] for r in db.query("SELECT home_key FROM hist_matches")}
    assert "ENG:bravo united" in keys and "ENG:bravo utd" not in keys
    assert "ENG:golf wanderers" in keys


def test_previous_season_feeds_the_model(hist_setup):
    db, _, _ = hist_setup
    engine = Engine(db)
    mid = next(k for k, m in engine.store.matches.items() if m["status"] == "scheduled" and m["home"] == "Alpha FC")
    a = engine.analyze(mid)
    assert any("previous-season matches" in n for n in a["model"]["details"]["notes"])
    # descriptive stats stay current-season only
    assert all(r["date"] >= min(m["date"] for m in db.query("SELECT date FROM matches")) for r in a["profiles"]["home"]["recent"])
    # football-data rows never appear as fixtures
    day = (datetime.now(timezone.utc) - timedelta(days=400)).date().isoformat()
    assert all(not f["id"].startswith("FD|") for f in engine.list_fixtures(day, date.today().isoformat()))


def test_clv_from_bet365_closing(hist_setup):
    db, _, om = hist_setup
    from matchedge.engine.tracking import auto_settle
    m = om[-1]
    db.execute("INSERT INTO predictions(created_at, match_id, competition, match_label, home_key, away_key, kickoff_utc, "
               "market, selection, line, odds) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               ("2026-01-01T00:00:00Z", m["id"], m["competition"], "x", m["home_key"], m["away_key"], m["kickoff_utc"],
                "1X2", "home", None, 2.10))
    auto_settle(db)
    p = db.one("SELECT * FROM predictions")
    assert p["closing_odds"] == 1.95 and p["closing_source"].startswith("Bet365 closing")
    assert p["clv"] == pytest.approx(2.10 / 1.95 - 1, abs=1e-4)


def test_clv_falls_back_to_archived_snapshot(db, dataset):
    import_from_directory(db, dataset)
    m = db.one("SELECT * FROM matches WHERE status='finished' LIMIT 1")
    db.execute("INSERT INTO odds_history(match_id, bookmaker, market, selection, line, odds, captured_at, source) "
               "VALUES(?,?,?,?,?,?,?,?)", (m["id"], "bet365", "BTTS", "yes", None, 1.8, "2000-01-01T00:00:00Z", "dataset_snapshot"))
    from matchedge.engine.clv import closing_price
    c = closing_price(db, {"match_id": m["id"], "competition": m["competition"], "home_key": m["home_key"],
                           "away_key": m["away_key"], "kickoff_utc": m["kickoff_utc"], "market": "BTTS",
                           "selection": "yes", "line": None})
    assert c[0] == 1.8 and "approximate" in c[1]


def test_backtest_replays_weekends_with_real_prices(hist_setup):
    db, _, _ = hist_setup
    from matchedge.engine.plan_backtest import historical_prices, run_backtest
    engine = Engine(db)
    row = db.one("SELECT * FROM hist_matches LIMIT 1")
    prices = historical_prices(row)
    assert {(p["market"], p["selection"]) for p in prices} >= {("1X2", "home"), ("OU", "over"), ("AH", "home")}
    ah = [p for p in prices if p["market"] == "AH"]
    assert ah[0]["line"] == -ah[1]["line"]  # home handicap and the mirrored away line
    s = dict(engine.db.get_settings(), min_matches_model=2)
    r = run_backtest(engine.store, s, [season_codes(1)[1]], [50.0, 110.0], ["ENG_1_premier-league"])
    assert r["seasons"] == [season_codes(1)[1]] and "tickets" in r and "legs" in r
    for t in r["tickets"]:
        if t.get("tickets"):
            assert t["won"] <= t["tickets"] and t["longest_losing_run"] <= t["tickets"]
