"""Machine-learning pipeline: no look-ahead, missing data, probability mapping, training and prediction."""
import copy
import random
from datetime import date, timedelta

import pytest

from matchedge.ml.features import FeatureBuilder, build_rows
from matchedge.ml.predict import apply_ml, fit_lambdas, odds_market_features


def synthetic_rows(n_seasons=3, teams=8, seed=3, comp="ENG_1_premier-league", start=date(2023, 8, 1), odds=True):
    rng = random.Random(seed)
    names = [f"ENG:t{k}" for k in range(teams)]
    strength = {t: 0.8 + 0.15 * k for k, t in enumerate(names)}
    rows, i = [], 0
    for s in range(n_seasons):
        season = f"{23 + s}{24 + s}"
        d = start + timedelta(days=365 * s)
        for h in names:
            for a in names:
                if h == a:
                    continue
                lh, la = 1.3 * strength[h] / strength[a] ** 0.5, 1.0 * strength[a] / strength[h] ** 0.5
                fh = sum(rng.random() < lh / 6 for _ in range(6))
                fa = sum(rng.random() < la / 6 for _ in range(6))
                d += timedelta(days=1)
                ph = min(0.85, max(0.1, 0.45 + 0.2 * (strength[h] - strength[a])))
                rows.append({"id": f"FD|{season}|E0|{d.isoformat()}|{h}|{a}", "season": season, "division": "E0",
                             "competition": comp, "date": d.isoformat(), "home": h, "away": a, "home_key": h, "away_key": a,
                             "ft_home": fh, "ft_away": fa, "home_shots": 8 + 2 * fh, "away_shots": 7 + 2 * fa,
                             "home_target": 2 + fh, "away_target": 2 + fa,
                             "home_corners": None if i % 5 == 0 else 5, "away_corners": None if i % 5 == 0 else 4,
                             "home_yellow": 1, "away_yellow": 2,
                             "b365_h": round(1 / ph * 0.95, 2) if odds else None, "b365_d": 3.4 if odds else None,
                             "b365_a": round(1 / max(0.1, 0.75 - ph) * 0.95, 2) if odds else None,
                             "b365_o25": 1.9 if odds else None, "b365_u25": 1.9 if odds else None, "ah_line": -0.5 if odds else None})
                i += 1
    return rows


def test_features_never_see_the_match_or_the_future():
    rows = synthetic_rows(n_seasons=2)
    base = {r["id"]: r for r in build_rows(rows, min_history=0)}
    k = len(rows) // 2
    changed = copy.deepcopy(rows)
    changed[k]["ft_home"], changed[k]["ft_away"] = 9, 0  # alter one result
    after = {r["id"]: r for r in build_rows(changed, min_history=0)}
    target = rows[k]["id"]
    assert after[target]["features"] == base[target]["features"]  # its own features are unaffected
    assert after[target]["y_hg"] == 9  # only its label changes
    later = [r["id"] for r in rows[k + 1:] if rows[k]["home_key"] in (r["home_key"], r["away_key"])]
    assert any(after[x]["features"]["elo_h"] != base[x]["features"]["elo_h"] or
               after[x]["features"]["elo_a"] != base[x]["features"]["elo_a"] for x in later)


def test_missing_statistics_are_skipped_not_zero():
    fb = FeatureBuilder()
    r = synthetic_rows(n_seasons=1)[1]  # corners present
    fb.update(r)
    before = fb.teams[r["home_key"]].ew["cf"]
    r2 = dict(r, id="x", date=(date.fromisoformat(r["date"]) + timedelta(days=3)).isoformat(),
              home_corners=None, away_corners=None)
    fb.update(r2)
    assert fb.teams[r["home_key"]].ew["cf"] == before  # unchanged, not pulled toward 0


def test_market_features_remove_the_margin():
    rows = build_rows(synthetic_rows(n_seasons=1), min_history=0)
    f = rows[-1]["features"]
    assert f["mkt_ph"] + f["mkt_pd"] + f["mkt_pa"] == pytest.approx(1.0)
    assert f["mkt_po25"] == pytest.approx(0.5)


def test_fit_lambdas_reproduces_the_targets():
    from matchedge.engine.poisson import market_probs, score_matrix
    lh, la = fit_lambdas(0.20, 0.55, 1.3, 1.1)
    p = market_probs(score_matrix(lh, la))
    assert p["home"] - p["away"] == pytest.approx(0.20, abs=1e-3)
    assert p["over_2.5"] == pytest.approx(0.55, abs=1e-3)


def test_apply_ml_uses_ml_values_and_keeps_markets_consistent(loaded):
    _, engine = loaded
    mid = next(k for k, m in engine.store.matches.items() if m["status"] == "scheduled" and m["home"] == "Alpha FC")
    from matchedge.engine.data import prev_season
    from matchedge.engine.poisson import fit_match
    m = engine.store.matches[mid]
    h = engine.store.history(m["home_key"], m["date_obj"], {m["competition"]})
    a = engine.store.history(m["away_key"], m["date_obj"], {m["competition"]})
    g = fit_match(engine.store, h, a, m["competition"], m["date_obj"], engine.db.get_settings(), False)
    ml = {"p_h": 0.5, "p_d": 0.25, "p_a": 0.25, "p_o25": 0.6, "p_btts": 0.55, "variant": "stats"}
    g2 = apply_ml(g, ml)
    assert g2.probs["home"] == 0.5 and g2.probs["over_2.5"] == 0.6 and g2.probs["btts_yes"] == 0.55
    assert g2.probs["dc_1X"] == pytest.approx(0.75) and g2.probs["dnb_home"] == pytest.approx(0.5 / 0.75)
    assert g2.probs["over_1.5"] > g2.probs["over_2.5"] > g2.probs["over_3.5"]
    for k, (lo, hi) in g2.ranges.items():
        assert lo <= g2.probs[k] <= hi
    assert g2.details["engine"] == "ml" and g.details.get("engine") is None  # original untouched


def test_odds_market_features_prefer_manual_and_main_asian_line():
    rows = [
        {"market": "1X2", "selection": "home", "line": None, "odds": 2.0, "bookmaker": "bet365", "source": "dataset_snapshot", "checked_at": "a"},
        {"market": "1X2", "selection": "home", "line": None, "odds": 2.1, "bookmaker": "Bet365", "source": "manual", "checked_at": "b"},
        {"market": "AH", "selection": "home", "line": -0.5, "odds": 1.95, "bookmaker": "bet365", "source": "dataset_snapshot", "checked_at": "a"},
        {"market": "AH", "selection": "away", "line": 0.5, "odds": 1.9, "bookmaker": "bet365", "source": "dataset_snapshot", "checked_at": "a"},
        {"market": "AH", "selection": "home", "line": -1.5, "odds": 3.4, "bookmaker": "bet365", "source": "dataset_snapshot", "checked_at": "a"},
        {"market": "AH", "selection": "away", "line": 1.5, "odds": 1.3, "bookmaker": "bet365", "source": "dataset_snapshot", "checked_at": "a"},
    ]
    f = odds_market_features(rows)
    assert f["b365_h"] == 2.1 and f["ah_line"] == -0.5 and f["b365_o25"] is None


def test_train_save_load_and_predict(loaded, tmp_path):
    db, engine = loaded
    from matchedge.history import HIST_COLUMNS, ensure_schema
    from matchedge.ml.predict import MLPredictor
    from matchedge.ml.train import train_all
    ensure_schema(db)
    # two synthetic past seasons for the same teams as the Open-Matchday test league
    teams = sorted({m["home_key"] for m in engine.store.matches.values()})
    rows = synthetic_rows(n_seasons=2, teams=len(teams), start=date.today() - timedelta(days=800))
    rename = {f"ENG:t{k}": t for k, t in enumerate(teams)}
    for r in rows:
        r["home_key"], r["away_key"] = rename[r["home_key"]], rename[r["away_key"]]
        r["id"] = "|".join(r["id"].split("|")[:4] + [r["home_key"], r["away_key"]])
    with db.tx() as c:
        c.executemany(f"INSERT INTO hist_matches({','.join(HIST_COLUMNS)}) VALUES({','.join('?' * len(HIST_COLUMNS))})",
                      [tuple(r.get(k) for k in HIST_COLUMNS) for r in rows])
    engine.refresh()
    path = tmp_path / "m.joblib"
    seasons = sorted({r["season"] for r in rows})
    rep = train_all(db, engine.store, engine.db.get_settings(), test_seasons=[seasons[-1]], save_path=path, min_train=20)
    assert path.exists() and rep["meta"]["rows"] > 50
    assert set(rep["pooled"]) == {"y_1x2", "y_o25", "y_btts"}
    assert {"engine", "ml_stats", "ml_market", "bet365"} <= set(rep["pooled"]["y_1x2"])
    assert db.one("SELECT COUNT(*) n FROM ml_oos")["n"] > 0
    pred = MLPredictor.load(db, engine.store, path)
    mid = next(k for k, m in engine.store.matches.items() if m["status"] == "scheduled" and m["home"] == "Alpha FC")
    a = engine.analyze(mid)
    from matchedge.engine.data import prev_season  # noqa: F401
    m = engine.store.matches[mid]
    from matchedge.engine.poisson import fit_match
    h = engine.store.history(m["home_key"], m["date_obj"], {m["competition"]})
    aw = engine.store.history(m["away_key"], m["date_obj"], {m["competition"]})
    g = fit_match(engine.store, h, aw, m["competition"], m["date_obj"], engine.db.get_settings(), False)
    out = pred.predict(m, g, [], engine.db.get_settings())
    assert out is not None and out["variant"] == "stats"  # no Bet365 prices for this fixture
    assert out["p_h"] + out["p_d"] + out["p_a"] == pytest.approx(1.0, abs=1e-6)
    assert a["fixture"]["id"] == mid


def test_ml_endpoints_without_history(client_no_hist):
    r = client_no_hist.post("/api/ml/train")
    assert r.status_code == 400 and "historical" in r.json()["detail"]
    st = client_no_hist.get("/api/ml").json()
    assert st["model_loaded"] is False


@pytest.fixture()
def client_no_hist(tmp_path, dataset, monkeypatch):
    from fastapi.testclient import TestClient
    from matchedge.ml import train as train_mod
    monkeypatch.setattr(train_mod, "MODEL_PATH", tmp_path / "none.joblib")
    from matchedge.main import create_app
    c = TestClient(create_app(tmp_path / "x.sqlite3"))
    c.post("/api/import", json={"local_path": str(dataset)})
    return c
