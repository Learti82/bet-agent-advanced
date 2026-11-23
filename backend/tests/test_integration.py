"""End-to-end through the HTTP API with a synthetic dataset (no network)."""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from matchedge.importer import ImportErrorMatchEdge, import_from_directory
from tests.conftest import make_dataset


@pytest.fixture()
def client(tmp_path, dataset):
    from matchedge.main import create_app
    app = create_app(tmp_path / "api.sqlite3")
    c = TestClient(app)
    r = c.post("/api/import", json={"local_path": str(dataset)})
    assert r.status_code == 200, r.text
    return c


def fixture_id(c, home):
    day = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
    fx = c.get("/api/fixtures", params={"date_from": day, "date_to": day}).json()
    return next(f for f in fx if f["home"] == home)


def test_status_and_freshness(client):
    s = client.get("/api/status").json()
    assert s["dataset"]["results"] > 30 and s["dataset"]["age_days"] < 1
    assert s["timezone"] == "Europe/Belgrade"
    assert "open-matchday" in s["attribution"]


def test_fixture_listing_and_exclusions(client):
    f = fixture_id(client, "Alpha FC")
    assert f["kickoff_local"].endswith("21:00") and f["prematch_eligible"]
    assert f["verified"] is False
    unknown = fixture_id(client, "Bravo United")
    assert unknown["kickoff_local"] is None and unknown["time_certainty"] == "unknown"
    yday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    past = client.get("/api/fixtures", params={"date_from": yday, "date_to": yday}).json()
    cf = next(x for x in past if x["home"] == "Charlie City")
    assert cf["prematch_eligible"] is False
    only_eligible = client.get("/api/fixtures", params={"date_from": yday, "date_to": yday, "include_ineligible": False}).json()
    assert all(x["home"] != "Charlie City" for x in only_eligible)


def test_analysis_odds_and_ticket_flow(client):
    f = fixture_id(client, "Alpha FC")
    mid = quote(f["id"], safe="")
    a = client.get(f"/api/matches/{mid}/analysis").json()
    assert a["model"]["available"]
    assert a["decision"]["status"] in ("candidate", "flagged", "rejected")
    assert a["research_score"]["score"] >= 0 and a["data_quality"]["score"] >= 0
    assert a["links"] and any("footiqo" in l["url"] for l in a["links"])
    # no prices yet: nothing can go on a ticket
    assert all(c["price"] is None for c in a["candidates"])
    # enter a manual Bet365 price
    r = client.post("/api/odds", json={"match_id": f["id"], "bookmaker": "Bet365", "market": "OU",
                                       "selection": "over", "line": 1.5, "odds": 1.45, "checked_at": "2026-11-23 10:15"})
    assert r.status_code == 200 and "not a verified live price" in r.json()["notice"]
    assert client.post("/api/odds", json={"match_id": f["id"], "bookmaker": "Bet365", "market": "OU",
                                          "selection": "sideways", "line": 1.5, "odds": 1.45}).status_code == 422
    a = client.get(f"/api/matches/{mid}/analysis").json()
    c = next(x for x in a["candidates"] if x["key"] == "OU|over|1.5")
    assert c["price"]["source"] == "manual" and c["implied_probability"] == pytest.approx(1 / 1.45, abs=1e-4)
    # evaluate / duplicate / save
    legs = [{"match_id": f["id"], "key": "OU|over|1.5"}]
    ev = client.post("/api/accumulator/evaluate", json={"legs": legs, "target": 10}).json()["evaluation"]
    assert ev["combined_odds"] == 1.45
    ev = client.post("/api/accumulator/evaluate", json={"legs": legs * 2, "target": 10}).json()["evaluation"]
    assert not ev["valid"]
    r = client.post("/api/tickets", json={"legs": legs, "target": 10, "name": "t"})
    assert r.status_code == 200
    preds = client.get("/api/predictions").json()
    assert preds[0]["odds"] == 1.45 and preds[0]["status"] == "pending"
    rep = client.post("/api/accumulator/report", json={"date_from": f["local_date"], "target": 110}).json()
    assert "final_opinion" in rep and rep["summary"]["requested_odds"] == 110


def test_research_and_lineup_rejection(client):
    f = fixture_id(client, "Delta Rovers")
    mid = quote(f["id"], safe="")
    r = client.post("/api/research", json={"match_id": f["id"], "url": "https://footiqo.com/match", "category": "injury",
                                            "statistic": "Two starters doubtful", "reliability": "high"})
    assert r.status_code == 200
    a = client.get(f"/api/matches/{mid}/analysis").json()
    assert a["decision"]["status"] == "rejected"
    assert any(x["code"] == "lineup_uncertainty" for x in a["decision"]["factors"])
    assert a["evidence"][0]["url"] == "https://footiqo.com/match"
    assert client.post("/api/research", json={"match_id": f["id"], "url": "ftp://x", "statistic": "s"}).status_code == 422


def test_override_verification_and_postponement(client):
    f = fixture_id(client, "Bravo United")
    mid = quote(f["id"], safe="")
    assert client.put(f"/api/matches/{mid}/override", json={"verified": True}).status_code == 422  # URL required
    r = client.put(f"/api/matches/{mid}/override", json={"kickoff_local": f"{f['date']} 16:00", "verified": True,
                                                         "verification_url": "https://www.premierleague.com/"})
    v = r.json()
    assert v["verified"] and v["time_certainty"] == "user_corrected" and v["kickoff_local"].endswith("16:00")
    client.put(f"/api/matches/{mid}/override", json={"status": "postponed"})
    a = client.get(f"/api/matches/{mid}/analysis").json()
    assert a["decision"]["status"] == "ineligible"


def test_settings_roundtrip_and_validation(client):
    r = client.put("/api/settings", json={"min_leg_probability": 0.65})
    assert r.json()["values"]["min_leg_probability"] == 0.65
    assert client.put("/api/settings", json={"not_a_setting": 1}).status_code == 422
    assert client.put("/api/settings", json={"timezone": "Mars/Base"}).status_code == 422


def test_auto_settlement_after_result_import(tmp_path, db):
    from matchedge.engine.analysis import Engine
    from matchedge.engine.report import legs_from_request
    from matchedge.engine.tracking import auto_settle
    day = (datetime.now(timezone.utc) + timedelta(days=3)).date()
    root = make_dataset(tmp_path / "v1", fixture_day=day)
    import_from_directory(db, root)
    engine = Engine(db)
    mid = next(k for k, m in engine.store.matches.items() if m["home"] == "Alpha FC" and m["status"] == "scheduled")
    db.execute("INSERT INTO odds(match_id, bookmaker, market, selection, line, odds, checked_at, source, created_at) "
               "VALUES(?,?,?,?,?,?,?,?,?)", (mid, "Bet365", "OU", "over", 1.5, 1.5, "2026-01-01T00:00:00Z", "manual",
                                              "2026-01-01T00:00:00Z"))
    engine.invalidate()
    leg = legs_from_request(engine, [{"match_id": mid, "key": "OU|over|1.5"}])[0]
    db.execute("INSERT INTO predictions(created_at, match_id, competition, match_label, home_key, away_key, kickoff_utc, "
               "market, selection, line, odds) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               ("2026-01-01T00:00:00Z", mid, leg["competition"], leg["match_label"], leg["home_id"], leg["away_id"],
                leg["kickoff_utc"], "OU", "over", 1.5, 1.5))
    # later import: the fixture now has a result (3-1)
    played = {"gw": 13, "date": day.isoformat(), "time": "21:00", "home": "Alpha FC", "away": "Hotel Albion",
              "ft_home": 3, "ft_away": 1, "ft_result": "H", "ht_home": "", "ht_away": "", "ht_result": "",
              **{k: "" for k in ("home_shots", "away_shots", "home_target", "away_target", "home_fouls", "away_fouls",
                                 "home_corners", "away_corners", "home_corners_1h", "away_corners_1h",
                                 "home_corners_2h", "away_corners_2h", "home_yellow", "away_yellow", "home_red",
                                 "away_red", "goal_minutes")}, "source": "fixturedl"}
    root2 = make_dataset(tmp_path / "v2", fixture_day=day, extra_results=[played])
    import_from_directory(db, root2)
    out = auto_settle(db)
    assert out["settled"] == 1
    p = db.one("SELECT * FROM predictions")
    assert p["status"] == "won" and "3-1" in p["result_detail"]


def test_importer_rejects_missing_columns(tmp_path, db):
    root = make_dataset(tmp_path / "bad")
    f = root / "data" / "ENG_1_premier-league" / "results_2627.csv"
    lines = f.read_text().splitlines()
    lines[0] = lines[0].replace("ft_home", "fthome")
    f.write_text("\n".join(lines))
    rep = import_from_directory(db, root)
    assert any("missing columns" in w for w in rep.warnings)
    assert rep.results == 0


def test_importer_requires_data_folder(tmp_path, db):
    with pytest.raises(ImportErrorMatchEdge):
        import_from_directory(db, tmp_path)


def test_outdated_dataset_rejects_matches(tmp_path, db):
    from matchedge.engine.analysis import Engine
    old = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    root = make_dataset(tmp_path / "old", generated_utc=old)
    import_from_directory(db, root)
    engine = Engine(db)
    mid = next(k for k, m in engine.store.matches.items() if m["home"] == "Alpha FC" and m["status"] == "scheduled")
    a = engine.analyze(mid)
    assert a["decision"]["status"] == "rejected"
    assert any(f["code"] == "dataset_outdated" for f in a["decision"]["factors"])


def test_download_fallback_order(tmp_path, monkeypatch):
    """ZIP fails -> raw per-file download is used; optional files may 404."""
    import json as _json
    import urllib.error
    from matchedge import config
    from matchedge.importer import download_dataset
    src = make_dataset(tmp_path / "src")
    calls = []

    def fake_fetch(url: str) -> bytes:
        calls.append(url)
        if url.endswith(".zip"):
            raise urllib.error.URLError("blocked")
        rel = url.split(f"{config.OPEN_MATCHDAY_BRANCH}/", 1)[1]
        p = src / rel
        if not p.exists():
            raise urllib.error.HTTPError(url, 404, "nf", None, None)
        return p.read_bytes()

    dest, method, sha = download_dataset(tmp_path / "dest", fetch=fake_fetch)
    assert method == "github-raw" and sha is None
    assert (dest / "data" / "ENG_1_premier-league" / "results_2627.csv").exists()
    assert _json.loads((dest / "build_summary.json").read_text())["season"] == "2627"
    assert calls[0].endswith(".zip")
