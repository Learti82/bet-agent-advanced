"""Train and validate the machine-learning models (walk-forward, out-of-sample).

Data: every finished match in the football-data.co.uk seasons on this computer (22 European
divisions). Targets: match result (home/draw/away), Over 2.5 goals, both teams to score.

Two model variants per target, both gradient-boosted trees (scikit-learn HistGradientBoosting):
  * "stats"  — walk-forward team features + the statistical engine's own Poisson probabilities;
  * "market" — the same plus Bet365's pre-match prices (margin removed). Used only when a Bet365
               price for the fixture is available.

Validation: for each test season S (default the three latest completed seasons) the models are
trained only on seasons before S and scored on S. Benchmarks on exactly the same matches: the
statistical engine and Bet365's margin-free probabilities. Reported: log loss, Brier score,
accuracy, calibration, a value-betting simulation with Bet365 pre-match and closing prices, and
permutation feature importance. The final models are then retrained on every season and saved
in data/models/. Out-of-sample predictions are stored for the plan backtest (no leakage).
"""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

import numpy as np

from .. import config
from ..db import Database
from ..timeutil import iso, now_utc
from .features import MARKET_FEATURES, STAT_FEATURES, build_rows, matrix

MODEL_DIR = config.DATA_DIR / "models"
MODEL_PATH = MODEL_DIR / "matchedge_ml.joblib"
ENGINE_FEATURES = ["eng_h", "eng_d", "eng_a", "eng_o25", "eng_btts", "eng_lh", "eng_la"]
VARIANTS = {"stats": STAT_FEATURES + ENGINE_FEATURES, "market": STAT_FEATURES + ENGINE_FEATURES + MARKET_FEATURES}
TARGETS = {"y_1x2": "Match result", "y_o25": "Over 2.5 goals", "y_btts": "Both teams to score"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS ml_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
    status TEXT, progress TEXT, result TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS ml_oos (match_id TEXT NOT NULL, season TEXT, variant TEXT NOT NULL, p_h REAL, p_d REAL,
    p_a REAL, p_o25 REAL, p_btts REAL, PRIMARY KEY (match_id, variant));
"""
_lock = threading.Lock()


def ensure_schema(db: Database) -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)


def make_model():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(learning_rate=0.03, max_iter=600, max_leaf_nodes=12, min_samples_leaf=150,
                                          l2_regularization=2.0, early_stopping=True, validation_fraction=0.15,
                                          random_state=0)


# ---------------------------------------------------------------------- data
def add_engine_features(rows: list[dict], store, settings: dict, progress=lambda m: None) -> None:
    """Attach the statistical engine's walk-forward probabilities as features (stacking)."""
    from datetime import date, timedelta
    from ..engine.data import prev_season
    from ..engine.poisson import fit_match
    s = dict(settings, min_matches_model=3)
    # current-season football-data rows are not in the store (Open-Matchday holds that season):
    # find the same match there (same competition and teams, date ±1 day)
    om_index: dict[tuple, list[dict]] = {}
    for m in store.matches.values():
        if not m["id"].startswith("FD|") and m["status"] == "finished":
            om_index.setdefault((m["competition"], m["home_key"], m["away_key"]), []).append(m)
    for k, r in enumerate(rows):
        if k % 2000 == 0:
            progress(f"engine probabilities {k}/{len(rows)}")
        m = store.matches.get(r["id"])
        if m is None:
            d0 = date.fromisoformat(r["date"])
            cands = [x for x in om_index.get((r["competition"], *r["id"].split("|")[4:6]), [])
                     if abs((x["date_obj"] - d0).days) <= 1]
            m = cands[0] if len(cands) == 1 else None
        if m is None:
            continue
        season, comp, d = m["season"], m["competition"], m["date_obj"]
        hr = store.history(m["home_key"], d, {comp}, {season, prev_season(season)})
        ar = store.history(m["away_key"], d, {comp}, {season, prev_season(season)})
        if len(hr) < 3 or len(ar) < 3:
            continue
        g = fit_match(store, hr, ar, comp, d, s, False, season)
        if g.available:
            r["features"].update(engine_feature_values(g))


def engine_feature_values(g) -> dict:
    p = g.probs
    return {"eng_h": p["home"], "eng_d": p["draw"], "eng_a": p["away"], "eng_o25": p["over_2.5"],
            "eng_btts": p["btts_yes"], "eng_lh": g.lambda_home, "eng_la": g.lambda_away}


def training_rows(db: Database, store, settings: dict, progress=lambda m: None) -> list[dict]:
    from ..history import ensure_schema as hist_schema
    hist_schema(db)
    hist = db.query("SELECT * FROM hist_matches")
    if not hist:
        raise RuntimeError("No historical seasons on this computer. Run the import (Data sources) first.")
    progress("building walk-forward features")
    rows = build_rows(hist)
    add_engine_features(rows, store, settings, progress)
    return rows


def _y(rows, t):
    return np.array([r[t] for r in rows])


def _has_market(r) -> bool:
    f = r["features"]
    return f["mkt_ph"] == f["mkt_ph"] and f["mkt_po25"] == f["mkt_po25"]


# ---------------------------------------------------------------------- metrics
def _ll(y, p, multi):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    if multi:
        return float(-np.mean(np.log(p[np.arange(len(y)), y])))
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _brier(y, p, multi):
    if multi:
        oh = np.eye(3)[y]
        return float(np.mean(np.sum((p - oh) ** 2, axis=1)))
    return float(np.mean((p - y) ** 2))


def _acc(y, p, multi):
    return float(np.mean(p.argmax(1) == y)) if multi else float(np.mean((p >= 0.5) == y))


def _calibration(y, p, multi):
    """Bins of predicted probability vs observed frequency (home win for 1X2)."""
    if multi:
        y, p = (y == 0).astype(int), p[:, 0]
    out = []
    for lo in np.arange(0.1, 0.9, 0.1):
        mask = (p >= lo) & (p < lo + 0.1)
        if mask.sum() >= 50:
            out.append({"bin": f"{int(100 * lo)}–{int(100 * lo + 10)}%", "n": int(mask.sum()),
                        "predicted": round(float(p[mask].mean()), 3), "actual": round(float(y[mask].mean()), 3)})
    return out


def _bets(rows, preds, thresholds=(0.02, 0.05, 0.10)):
    """Flat 1-unit value bets where model probability × Bet365 pre-match odds − 1 > threshold."""
    out = []
    for thr in thresholds:
        n = profit = 0.0
        wins = 0
        clv = []
        for r, p in zip(rows, preds):
            o = r["odds"]
            sels = [("h", p.get("p_h"), o.get("b365_h"), o.get("b365c_h"), r["y_1x2"] == 0),
                    ("d", p.get("p_d"), o.get("b365_d"), o.get("b365c_d"), r["y_1x2"] == 1),
                    ("a", p.get("p_a"), o.get("b365_a"), o.get("b365c_a"), r["y_1x2"] == 2),
                    ("o", p.get("p_o25"), o.get("b365_o25"), o.get("b365c_o25"), r["y_o25"] == 1),
                    ("u", None if p.get("p_o25") is None else 1 - p["p_o25"], o.get("b365_u25"), o.get("b365c_u25"),
                     r["y_o25"] == 0)]
            for _, prob, odds, close, won in sels:
                if prob is None or not odds or odds <= 1 or prob * odds - 1 <= thr:
                    continue
                n += 1
                wins += int(won)
                profit += (odds - 1) if won else -1
                if close and close > 1:
                    clv.append(odds / close - 1)
        out.append({"edge_threshold": thr, "bets": int(n), "win_rate": round(wins / n, 3) if n else None,
                    "profit_units": round(profit, 1), "roi": round(profit / n, 4) if n else None,
                    "avg_clv": round(float(np.mean(clv)), 4) if clv else None,
                    "beat_close": round(float(np.mean([c > 0 for c in clv])), 3) if clv else None})
    return out


# ---------------------------------------------------------------------- training
def _fit(rows, target, variant):
    model = make_model()
    model.fit(matrix(rows, VARIANTS[variant]), _y(rows, target))
    return model


def _predict(model, rows, variant, target):
    p = model.predict_proba(matrix(rows, VARIANTS[variant]))
    return p if target == "y_1x2" else p[:, 1]


def evaluate(rows: list[dict], test_seasons: list[str], progress=lambda m: None,
             min_train: int = 5000) -> tuple[dict, list[tuple]]:
    report: dict = {"seasons": {}, "pooled": {}}
    oos: list[tuple] = []
    pooled: dict = {}
    for season in test_seasons:
        train = [r for r in rows if r["season"] < season and "eng_h" in r["features"]]
        test = [r for r in rows if r["season"] == season and "eng_h" in r["features"] and _has_market(r)]
        if len(train) < min_train or not test:
            continue
        sres: dict = {"train_rows": len(train), "test_rows": len(test), "targets": {}}
        preds = {v: [dict() for _ in test] for v in VARIANTS}
        for target, label in TARGETS.items():
            progress(f"{season}: training {label}")
            multi = target == "y_1x2"
            y = _y(test, target)
            cand = {}
            for variant in VARIANTS:
                tr = train if variant == "stats" else [r for r in train if _has_market(r)]
                cand[f"ml_{variant}"] = _predict(_fit(tr, target, variant), test, variant, target)
            if multi:
                cand["engine"] = np.array([[r["features"]["eng_h"], r["features"]["eng_d"], r["features"]["eng_a"]] for r in test])
                cand["bet365"] = np.array([[r["features"]["mkt_ph"], r["features"]["mkt_pd"], r["features"]["mkt_pa"]] for r in test])
            elif target == "y_o25":
                cand["engine"] = np.array([r["features"]["eng_o25"] for r in test])
                cand["bet365"] = np.array([r["features"]["mkt_po25"] for r in test])
            else:
                cand["engine"] = np.array([r["features"]["eng_btts"] for r in test])
            sres["targets"][target] = {name: {"log_loss": round(_ll(y, p, multi), 4), "brier": round(_brier(y, p, multi), 4),
                                              "accuracy": round(_acc(y, p, multi), 4)} for name, p in cand.items()}
            sres["targets"][target]["calibration_ml_market"] = _calibration(y, cand["ml_market"], multi)
            sres["targets"][target]["calibration_ml_stats"] = _calibration(y, cand["ml_stats"], multi)
            for name, p in cand.items():
                pooled.setdefault(target, {}).setdefault(name, [[], []])
                pooled[target][name][0].append(y)
                pooled[target][name][1].append(p)
            for variant in VARIANTS:
                p = cand[f"ml_{variant}"]
                for k in range(len(test)):
                    if multi:
                        preds[variant][k].update(p_h=float(p[k, 0]), p_d=float(p[k, 1]), p_a=float(p[k, 2]))
                    else:
                        preds[variant][k]["p_o25" if target == "y_o25" else "p_btts"] = float(p[k])
        eng_preds = [{"p_h": r["features"]["eng_h"], "p_d": r["features"]["eng_d"], "p_a": r["features"]["eng_a"],
                      "p_o25": r["features"]["eng_o25"]} for r in test]
        sres["betting"] = {"engine": _bets(test, eng_preds), "ml_stats": _bets(test, preds["stats"]),
                           "ml_market": _bets(test, preds["market"])}
        for variant in VARIANTS:
            for r, p in zip(test, preds[variant]):
                oos.append((r["id"], season, variant, p.get("p_h"), p.get("p_d"), p.get("p_a"), p.get("p_o25"),
                            p.get("p_btts")))
        report["seasons"][season] = sres
    for target, by in pooled.items():
        multi = target == "y_1x2"
        report["pooled"][target] = {}
        for name, (ys, ps) in by.items():
            y = np.concatenate(ys)
            p = np.concatenate(ps)
            report["pooled"][target][name] = {"log_loss": round(_ll(y, p, multi), 4), "brier": round(_brier(y, p, multi), 4),
                                              "accuracy": round(_acc(y, p, multi), 4), "n": int(len(y))}
    return report, oos


def feature_importance(rows: list[dict], season: str, top: int = 15) -> list[dict]:
    from sklearn.inspection import permutation_importance
    train = [r for r in rows if r["season"] < season and "eng_h" in r["features"]]
    test = [r for r in rows if r["season"] == season and "eng_h" in r["features"]][:4000]
    if not train or not test:
        return []
    model = _fit(train, "y_1x2", "stats")
    res = permutation_importance(model, matrix(test, VARIANTS["stats"]), _y(test, "y_1x2"), scoring="neg_log_loss",
                                 n_repeats=3, random_state=0)
    order = np.argsort(-res.importances_mean)[:top]
    return [{"feature": VARIANTS["stats"][i], "importance": round(float(res.importances_mean[i]), 5)} for i in order]


def train_all(db: Database, store, settings: dict, test_seasons: list[str] | None = None,
              progress=lambda m: None, save_path: Path = MODEL_PATH, min_train: int = 5000) -> dict:
    import joblib
    import sklearn
    t0 = time.time()
    ensure_schema(db)
    rows = training_rows(db, store, settings, progress)
    seasons = sorted({r["season"] for r in rows if r["season"] != config.SEASON})
    test_seasons = test_seasons or seasons[-3:]
    report, oos = evaluate(rows, test_seasons, progress, min_train)
    progress("feature importance")
    report["feature_importance"] = feature_importance(rows, test_seasons[-1]) if test_seasons else []
    # decide, per target, whether each ML variant beats the statistical engine out of sample
    use = {}
    for target, by in report["pooled"].items():
        eng = by.get("engine", {}).get("log_loss")
        use[target] = {v: bool(eng is not None and by.get(f"ml_{v}", {}).get("log_loss", 9) < eng) for v in VARIANTS}
    report["use_ml"] = use
    progress("training final models on every season")
    final_rows = [r for r in rows if "eng_h" in r["features"]]
    models = {}
    for target in TARGETS:
        for variant in VARIANTS:
            tr = final_rows if variant == "stats" else [r for r in final_rows if _has_market(r)]
            models[(target, variant)] = _fit(tr, target, variant)
    meta = {"trained_at": iso(now_utc()), "rows": len(final_rows), "seasons": sorted({r["season"] for r in final_rows}),
            "test_seasons": test_seasons, "variants": {k: v for k, v in VARIANTS.items()},
            "sklearn": sklearn.__version__, "use_ml": use, "seconds": round(time.time() - t0, 1)}
    save_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"models": models, "meta": meta}, save_path)
    with db.tx() as c:
        c.execute("DELETE FROM ml_oos")
        c.executemany("INSERT OR REPLACE INTO ml_oos VALUES(?,?,?,?,?,?,?,?)", oos)
    report["meta"] = meta
    return report


# ---------------------------------------------------------------------- background job
def start_training(db: Database, store, settings: dict, on_done=lambda: None) -> int:
    ensure_schema(db)
    if not _lock.acquire(blocking=False):
        raise RuntimeError("Training is already running.")
    run_id = db.execute("INSERT INTO ml_runs(started_at, status, progress) VALUES(?,?,?)",
                        (iso(now_utc()), "running", "starting"))

    def work():
        try:
            def prog(msg):
                db.execute("UPDATE ml_runs SET progress=? WHERE id=?", (msg, run_id))
            res = train_all(db, store, settings, progress=prog)
            prog("loading the new model into the app")
            on_done()  # load before reporting success, so the UI never sees results without the model
            db.execute("UPDATE ml_runs SET status='ok', finished_at=?, result=? WHERE id=?",
                       (iso(now_utc()), json.dumps(res), run_id))
        except Exception as exc:  # noqa: BLE001 - shown in the UI
            db.execute("UPDATE ml_runs SET status='failed', finished_at=?, error=? WHERE id=?",
                       (iso(now_utc()), f"{type(exc).__name__}: {exc}", run_id))
        finally:
            _lock.release()

    threading.Thread(target=work, daemon=True).start()
    return run_id


def latest_run(db: Database) -> dict | None:
    ensure_schema(db)
    row = db.one("SELECT * FROM ml_runs ORDER BY id DESC LIMIT 1")
    if row and row.get("result"):
        row["result"] = json.loads(row["result"])
    return row


def nan_safe(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x
