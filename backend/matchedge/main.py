"""MatchEdge Local — FastAPI application (local only, binds to 127.0.0.1 by default)."""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .ai.ollama import OllamaClient, ai_match_explanation, ai_ticket_summary
from .db import Database
from .engine.analysis import Engine
from .engine.markets import LINE_MARKETS, MARKET_NAMES, VALID_SELECTIONS, selection_key
from .engine.report import build_report, legs_from_request
from .engine.accumulator import evaluate_ticket
from .engine.backtest import model_check
from .engine.plan import build_week_plan, parse_targets, weekend_competitions
from .engine.tracking import auto_settle, performance
from .importer import ImportErrorMatchEdge, dataset_age_days, import_from_directory, run_import
from .links import research_links
from .schemas import (AliasIn, BuildIn, EvalIn, LegRef, OddsIn, OverrideIn, ResearchIn, SaveIn,
                      SettleIn)
from .teamnames import team_key
from .timeutil import iso, local_input_to_utc, now_utc, tz


def _default(o: Any):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(type(o).__name__)


def _clean(o: Any):
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o


class SafeJSON(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(_clean(content), default=_default, ensure_ascii=False).encode("utf-8")


def run_history_import(db: Database, logs: list[str] | None = None) -> dict:
    """football-data.co.uk refresh; failures never break the main import."""
    s = db.get_settings()
    if not s.get("history_enabled", True):
        return {"skipped": True}
    try:
        from .history import import_history
        out = import_history(db, int(s["history_seasons"]), log=(logs.append if logs is not None else print))
        return {k: v for k, v in out.items() if k != "warnings"} | {"warnings": out["warnings"][:10]}
    except Exception as exc:  # noqa: BLE001 - reported to the user, main import still succeeds
        return {"error": f"Historical data import failed: {exc}"}


def create_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title=config.APP_NAME, default_response_class=SafeJSON)
    db = Database(db_path)
    engine = Engine(db)
    app.state.db, app.state.engine = db, engine

    def require_match(match_id: str) -> dict:
        m = engine.store.matches.get(match_id)
        if not m:
            raise HTTPException(404, f"Unknown match {match_id}")
        return m

    def now_local_str() -> str:
        s = db.get_settings()
        return datetime.now(timezone.utc).astimezone(tz(str(s["timezone"]))).strftime("%Y-%m-%d %H:%M")

    # ------------------------------------------------------------------ status & import
    @app.get("/api/status")
    def status():
        run = engine.latest_import()
        last = db.one("SELECT * FROM import_runs ORDER BY id DESC LIMIT 1")
        s = db.get_settings()
        counts = db.one("SELECT SUM(status='finished') results, SUM(status='scheduled') fixtures, "
                        "COUNT(DISTINCT competition) comps FROM matches") or {}
        manual = db.one("SELECT COUNT(*) n FROM odds WHERE source='manual'")["n"]
        research = db.one("SELECT COUNT(*) n FROM research_sources")["n"]
        preds = db.one("SELECT COUNT(*) n, SUM(status='pending') pending FROM predictions")
        warnings = []
        age = dataset_age_days(run["dataset_generated_utc"]) if run else None
        if run is None:
            warnings.append("No dataset imported yet. Open Data sources and run the importer.")
        elif age is None:
            warnings.append("Dataset build time unknown.")
        elif age > float(s["max_dataset_age_days"]):
            warnings.append(f"Dataset is {age:.1f} days old. Re-import for fresh fixtures and results.")
        if last and last["status"] == "failed":
            warnings.append(f"Last import failed: {last['error']}")
        return {
            "app": config.APP_NAME, "now_utc": iso(now_utc()), "now_local": now_local_str(),
            "timezone": s["timezone"], "bookmaker": s["bookmaker"],
            "dataset": None if not run else {
                "generated_utc": run["dataset_generated_utc"], "age_days": age, "imported_at": run["finished_at"],
                "method": run["method"], "commit_sha": run["commit_sha"], "results": run["n_results"],
                "fixtures": run["n_fixtures"], "competitions": run["n_competitions"]},
            "counts": counts | {"manual_odds": manual, "research": research,
                                "predictions": preds["n"], "pending_predictions": preds["pending"] or 0},
            "ai": {"enabled": bool(s["ai_enabled"]), "model": s["ollama_model"]},
            "warnings": warnings, "attribution": config.ATTRIBUTION,
        }

    @app.post("/api/import")
    def do_import(body: dict = Body(default={})):
        logs: list[str] = []
        try:
            if body.get("local_path"):
                rep = import_from_directory(db, Path(body["local_path"]).expanduser(), method="local")
            else:
                rep = run_import(db, log=logs.append)
        except (ImportErrorMatchEdge, OSError) as exc:
            raise HTTPException(502, f"Import failed: {exc}. Logs: {' | '.join(logs)}")
        # a local-folder import is an offline action: do not download historical seasons with it
        hist = {"skipped": True} if body.get("local_path") else run_history_import(db, logs)
        engine.refresh()
        settle = auto_settle(db)
        return {"ok": True, "history": hist, "method": rep.method, "commit_sha": rep.commit_sha, "generated_utc": rep.generated_utc,
                "competitions": rep.competitions, "results": rep.results, "fixtures": rep.fixtures,
                "snapshot_prices": rep.snapshot_prices, "archived_prices": rep.archived_prices,
                "warnings": rep.warnings[:50],
                "unlinked_teams": rep.unlinked_teams, "log": logs, "settlement": settle}

    @app.post("/api/history/import")
    def history_import():
        out = run_history_import(db)
        if "error" in out:
            raise HTTPException(502, out["error"])
        engine.refresh()
        return out

    @app.get("/api/history/status")
    def history_status():
        from .history import status as hstatus
        return hstatus(db)

    @app.get("/api/import/runs")
    def import_runs():
        rows = db.query("SELECT * FROM import_runs ORDER BY id DESC LIMIT 20")
        for r in rows:
            r["warnings"] = json.loads(r["warnings"]) if r.get("warnings") else None
        return rows

    @app.get("/api/competitions")
    def competitions():
        rows = db.query("SELECT * FROM competitions ORDER BY code")
        for r in rows:
            r["coverage"] = json.loads(r["coverage"]) if r.get("coverage") else {}
        return rows

    # ------------------------------------------------------------------ fixtures
    @app.get("/api/fixtures")
    def fixtures(date_from: str | None = None, date_to: str | None = None, competitions: str | None = None,
                 team: str | None = None, include_ineligible: bool = True):
        today = datetime.now(timezone.utc).astimezone(tz(str(db.get_settings()["timezone"]))).date()
        df = date_from or today.isoformat()
        dt = date_to or df
        comps = [c for c in (competitions or "").split(",") if c]
        return engine.list_fixtures(df, dt, comps or None, team, include_ineligible)

    @app.get("/api/window")
    def window(date_from: str, date_to: str | None = None, competitions: str | None = None,
               eligible_only: bool = True):
        comps = [c for c in (competitions or "").split(",") if c]
        return engine.analyze_window(date_from, date_to or date_from, comps or None, eligible_only)

    @app.get("/api/matches/{match_id:path}/analysis")
    def analysis(match_id: str, ai: bool = False):
        require_match(match_id)
        a = engine.analyze(match_id)
        out = dict(a)
        if ai:
            out["explanation"] = ai_match_explanation(a, db.get_settings())
        out["links"] = research_links(a["fixture"])
        return out


    @app.put("/api/matches/{match_id:path}/override")
    def set_override(match_id: str, body: OverrideIn):
        require_match(match_id)
        if body.verified and not body.verification_url:
            raise HTTPException(422, "Give the official URL you used to verify the fixture.")
        db.execute("INSERT INTO fixture_overrides VALUES(?,?,?,?,?,?,?) ON CONFLICT(match_id) DO UPDATE SET "
                   "kickoff_local=excluded.kickoff_local, status=excluded.status, verified=excluded.verified, "
                   "verification_url=excluded.verification_url, note=excluded.note, updated_at=excluded.updated_at",
                   (match_id, body.kickoff_local, body.status, int(body.verified), body.verification_url,
                    body.note, iso(now_utc())))
        engine.invalidate()
        return engine.fixture_view(engine.store.matches[match_id], engine.overrides().get(match_id),
                                   db.get_settings())

    @app.delete("/api/matches/{match_id:path}/override")
    def del_override(match_id: str):
        db.execute("DELETE FROM fixture_overrides WHERE match_id=?", (match_id,))
        engine.invalidate()
        return {"ok": True}

    @app.get("/api/matches/{match_id:path}/links")
    def links(match_id: str):
        m = require_match(match_id)
        return research_links(engine.fixture_view(m, None, db.get_settings()))

    # ------------------------------------------------------------------ odds (manual)

    @app.get("/api/odds")
    def list_odds(match_id: str | None = None, source: str | None = None):
        sql, params = "SELECT * FROM odds WHERE 1=1", []
        if match_id:
            sql += " AND match_id=?"
            params.append(match_id)
        if source:
            sql += " AND source=?"
            params.append(source)
        return db.query(sql + " ORDER BY created_at DESC LIMIT 2000", tuple(params))

    def insert_odds(body: OddsIn) -> int:
        require_match(body.match_id)
        if body.market not in VALID_SELECTIONS:
            raise HTTPException(422, f"Unknown market {body.market}. Use one of {sorted(VALID_SELECTIONS)}")
        if body.selection not in VALID_SELECTIONS[body.market]:
            raise HTTPException(422, f"Selection must be one of {sorted(VALID_SELECTIONS[body.market])}")
        if body.market in LINE_MARKETS and body.line is None:
            raise HTTPException(422, f"{MARKET_NAMES[body.market]} needs a line (e.g. 2.5).")
        if body.market not in LINE_MARKETS:
            body.line = None
        if body.line is not None and abs(body.line * 4 - round(body.line * 4)) > 1e-9:
            raise HTTPException(422, "Lines must be in steps of 0.25.")
        zone = str(db.get_settings()["timezone"])
        checked = local_input_to_utc(body.checked_at, zone) if body.checked_at else now_utc()
        return db.execute("INSERT INTO odds(match_id, bookmaker, market, selection, line, odds, checked_at, source, "
                          "note, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (body.match_id, body.bookmaker.strip(), body.market, body.selection, body.line, body.odds,
                           iso(checked), "manual", body.note, iso(now_utc())))

    @app.post("/api/odds")
    def add_odds(body: OddsIn):
        oid = insert_odds(body)
        engine.invalidate()
        return db.one("SELECT * FROM odds WHERE id=?", (oid,)) | {
            "key": selection_key(body.market, body.selection, body.line),
            "notice": "Saved as a manually entered price. It is not a verified live price."}

    @app.post("/api/odds/parse")
    def parse_odds(body: dict = Body(...)):
        from .oddsparse import Fixture, parse_odds_text
        text = str(body.get("text") or "")
        if len(text) > 200_000:
            raise HTTPException(413, "Text too long.")
        settings_ = db.get_settings()
        zone = str(settings_["timezone"])
        if body.get("match_id"):
            m = require_match(body["match_id"])
            fixtures = [Fixture(m["id"], m["home"], m["away"])]
        else:
            from .engine.plan import today_local
            d0 = body.get("date_from") or today_local(zone).isoformat()
            d1 = body.get("date_to") or (date.fromisoformat(d0) + timedelta(days=7)).isoformat()
            fixtures = [Fixture(f["id"], f["home"], f["away"])
                        for f in engine.list_fixtures(d0, d1, include_ineligible=False)]
        res = parse_odds_text(text, fixtures, body.get("match_id"))
        return {"rows": res.rows, "ignored": res.ignored, "warnings": res.warnings, "fixtures_considered": len(fixtures),
                "notice": "Review every row before saving. Prices are saved as manual entries checked at the time you give."}

    @app.post("/api/odds/bulk")
    def bulk_odds(body: dict = Body(...)):
        rows = body.get("rows") or []
        if not rows:
            raise HTTPException(422, "No rows to save.")
        saved, errors = 0, []
        for k, r in enumerate(rows):
            try:
                insert_odds(OddsIn(match_id=r["match_id"], bookmaker=body.get("bookmaker") or "Bet365",
                                   market=r["market"], selection=r["selection"], line=r.get("line"),
                                   odds=float(r["odds"]), checked_at=body.get("checked_at"),
                                   note="pasted from bookmaker text"))
                saved += 1
            except (HTTPException, ValueError, KeyError) as exc:
                errors.append(f"Row {k + 1}: {getattr(exc, 'detail', exc)}")
        engine.invalidate()
        return {"saved": saved, "errors": errors}

    @app.get("/api/odds/history")
    def odds_history(match_id: str):
        return db.query("SELECT * FROM odds_history WHERE match_id=? ORDER BY market, selection, line, captured_at",
                        (match_id,))

    @app.delete("/api/odds/{odds_id}")
    def del_odds(odds_id: int):
        row = db.one("SELECT * FROM odds WHERE id=?", (odds_id,))
        if not row:
            raise HTTPException(404, "Not found")
        if row["source"] != "manual":
            raise HTTPException(400, "Dataset snapshot prices are replaced on each import and cannot be deleted.")
        db.execute("DELETE FROM odds WHERE id=?", (odds_id,))
        engine.invalidate()
        return {"ok": True}

    @app.get("/api/markets")
    def markets():
        return [{"market": m, "name": MARKET_NAMES[m], "selections": sorted(VALID_SELECTIONS[m]),
                 "needs_line": m in LINE_MARKETS} for m in VALID_SELECTIONS]

    # ------------------------------------------------------------------ research

    @app.get("/api/research")
    def list_research(match_id: str | None = None):
        if match_id:
            return db.query("SELECT * FROM research_sources WHERE match_id=? ORDER BY checked_at DESC", (match_id,))
        return db.query("SELECT * FROM research_sources ORDER BY created_at DESC LIMIT 500")

    @app.post("/api/research")
    def add_research(body: ResearchIn):
        m = require_match(body.match_id)
        if not (body.statistic or body.notes or body.value):
            raise HTTPException(422, "Add the statistic, value or notes you found.")
        zone = str(db.get_settings()["timezone"])
        checked = local_input_to_utc(body.checked_at, zone) if body.checked_at else now_utc()
        rid = db.execute(
            "INSERT INTO research_sources(match_id, url, match_label, category, statistic, value, notes, checked_at, "
            "reliability, impact, related_market, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (body.match_id, body.url, f"{m['home']} vs {m['away']}", body.category, body.statistic, body.value,
             body.notes, iso(checked), body.reliability, body.impact, body.related_market or None, iso(now_utc())))
        engine.invalidate()
        return db.one("SELECT * FROM research_sources WHERE id=?", (rid,))

    @app.delete("/api/research/{rid}")
    def del_research(rid: int):
        db.execute("DELETE FROM research_sources WHERE id=?", (rid,))
        engine.invalidate()
        return {"ok": True}

    # ------------------------------------------------------------------ accumulator


    @app.post("/api/accumulator/evaluate")
    def acc_evaluate(body: EvalIn):
        try:
            legs = legs_from_request(engine, [x.model_dump() for x in body.legs])
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        return {"legs": legs, "evaluation": evaluate_ticket(legs, body.target)}


    @app.post("/api/accumulator/report")
    def acc_report(body: BuildIn):
        legs = None
        if body.legs is not None:
            try:
                legs = legs_from_request(engine, [x.model_dump() for x in body.legs])
            except KeyError as exc:
                raise HTTPException(404, str(exc))
        rep = build_report(engine, date_from=body.date_from, date_to=body.date_to or body.date_from,
                           target=body.target, competitions=body.competitions or None, legs_in=legs,
                           max_legs=body.max_legs)
        rep["ai"] = ai_ticket_summary(rep, db.get_settings()) if body.ai else {"used": False, "reason": "Not requested."}
        return rep


    @app.post("/api/tickets")
    def save_ticket(body: SaveIn):
        legs = legs_from_request(engine, [x.model_dump() for x in body.legs])
        ev = evaluate_ticket(legs, body.target)
        if not ev["valid"]:
            raise HTTPException(422, {"message": "Ticket has errors", "errors": ev["errors"]})
        created = iso(now_utc())
        with db.tx() as c:
            cur = c.execute("INSERT INTO tickets(created_at, name, target_odds, combined_odds, n_selections, kind, report) "
                            "VALUES(?,?,?,?,?,?,?)", (created, body.name, body.target, ev["combined_odds"], len(legs),
                                                    body.kind, json.dumps({"evaluation": ev, "legs": legs,
                                                                           "report": body.report}, default=_default)))
            tid = cur.lastrowid
            for leg in legs:
                c.execute("INSERT INTO predictions(ticket_id, created_at, match_id, competition, match_label, home_key, "
                          "away_key, kickoff_utc, market, selection, line, odds, odds_source, model_probability, "
                          "implied_probability, selection_score, data_quality, confidence) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (tid, created, leg["match_id"], leg["competition"], leg["match_label"], leg["home_id"],
                           leg["away_id"], leg["kickoff_utc"], leg["market"], leg["selection"], leg["line"],
                           leg["odds"], f"{leg['bookmaker']} ({leg['odds_source']})", leg["probability"],
                           leg["implied_probability"], leg["score"], leg["data_quality"], leg["confidence"]))
        return {"id": tid, "evaluation": ev}

    @app.get("/api/tickets")
    def tickets():
        return db.query("SELECT id, created_at, name, target_odds, combined_odds, n_selections, kind FROM tickets "
                        "ORDER BY id DESC")

    @app.get("/api/tickets/{tid}")
    def ticket(tid: int):
        t = db.one("SELECT * FROM tickets WHERE id=?", (tid,))
        if not t:
            raise HTTPException(404, "Not found")
        t["report"] = json.loads(t["report"]) if t["report"] else None
        t["predictions"] = db.query("SELECT * FROM predictions WHERE ticket_id=?", (tid,))
        return t

    @app.delete("/api/tickets/{tid}")
    def del_ticket(tid: int):
        with db.tx() as c:
            c.execute("DELETE FROM predictions WHERE ticket_id=?", (tid,))
            c.execute("DELETE FROM tickets WHERE id=?", (tid,))
        return {"ok": True}

    # ------------------------------------------------------------------ weekly plan
    @app.get("/api/plan")
    def plan(week_start: str | None = None, targets: str | None = None):
        try:
            ws = date.fromisoformat(week_start) if week_start else None
            tg = parse_targets(targets) if targets else None
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return build_week_plan(engine, ws, tg)

    @app.get("/api/plan/weekend-competitions")
    def plan_weekend():
        return weekend_competitions(db.get_settings(), engine.store.competitions)

    # ------------------------------------------------------------------ tracking
    @app.get("/api/predictions")
    def predictions(status: str | None = None):
        if status:
            return db.query("SELECT * FROM predictions WHERE status=? ORDER BY created_at DESC", (status,))
        return db.query("SELECT * FROM predictions ORDER BY created_at DESC LIMIT 1000")


    @app.post("/api/predictions/{pid}/settle")
    def settle(pid: int, body: SettleIn):
        if not db.one("SELECT id FROM predictions WHERE id=?", (pid,)):
            raise HTTPException(404, "Not found")
        db.execute("UPDATE predictions SET status=?, settled_at=?, result_detail=COALESCE(?, result_detail), "
                   "settled_by='manual' WHERE id=?",
                   (body.status, None if body.status == "pending" else iso(now_utc()), body.note, pid))
        return db.one("SELECT * FROM predictions WHERE id=?", (pid,))

    @app.post("/api/predictions/settle-auto")
    def settle_auto():
        return auto_settle(db)

    @app.get("/api/performance")
    def perf():
        return performance(db)

    @app.get("/api/league-strength")
    def league_strength():
        from .engine.strength import table
        if not engine.strengths:
            return {"leagues": [], "n_matches": 0}
        names = {c: v.get("name", c) for c, v in engine.store.competitions.items()}
        return {"leagues": table(engine.strengths, names), "n_matches": engine.strengths["n_matches"],
                "sigma": engine.strengths["sigma"],
                "note": "Learned from this season's Champions/Europa/Conference League matches. Strength is on a log "
                        "goal scale: the goal factor is how many more goals an average team from that league would "
                        "score against an average team from a 0.00 league, all else equal. Few matches = close to 0 "
                        "and wide uncertainty.",
                "validation": "Walk-forward on 124 UEFA matches this season: log loss 1.658 (league strength) vs "
                              "1.678 (previous 50% shrinkage); lower is better."}

    @app.post("/api/backtest")
    def backtest_start(body: dict = Body(default={})):
        from .engine.plan_backtest import backtest_competitions, start_backtest
        from .history import season_codes
        s = db.get_settings()
        seasons = body.get("seasons") or [x for x in season_codes(int(s["history_seasons"])) if x != config.SEASON]
        targets = parse_targets(body.get("targets") or s["plan_targets"])
        comps, skipped = backtest_competitions(weekend_competitions(s, engine.store.competitions))
        if not comps:
            raise HTTPException(400, "None of the weekend leagues are covered by football-data.co.uk.")
        if not any(m.get("season") in seasons for c in comps for m in engine.store.by_comp.get(c, [])):
            raise HTTPException(400, "No historical seasons loaded. Run the import (Data sources) first.")
        ml_oos = None
        if body.get("engine") == "ml":
            from .ml.train import ensure_schema as ml_schema
            ml_schema(db)
            rows = db.query("SELECT * FROM ml_oos WHERE variant='market'")
            if not rows:
                raise HTTPException(400, "Train the ML model first (Model lab).")
            ml_oos = {r["match_id"]: {"p_h": r["p_h"], "p_d": r["p_d"], "p_a": r["p_a"], "p_o25": r["p_o25"],
                                      "p_btts": r["p_btts"], "variant": "market"} for r in rows}
            seasons = [x for x in seasons if x in {r["season"] for r in rows}]
        try:
            rid = start_backtest(db, engine.store, s, sorted(seasons), targets, comps, ml_oos)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return {"id": rid, "competitions": comps, "not_covered": skipped}

    # ------------------------------------------------------------------ machine learning
    @app.post("/api/ml/train")
    def ml_train():
        from .ml.train import start_training
        from .history import ensure_schema as hist_schema
        hist_schema(db)
        if not db.one("SELECT 1 x FROM hist_matches LIMIT 1"):
            raise HTTPException(400, "No historical seasons on this computer yet. Run the import (Data sources) first.")
        try:
            rid = start_training(db, engine.store, db.get_settings(), on_done=lambda: (engine.load_ml(), engine.invalidate()))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return {"id": rid}

    @app.get("/api/ml")
    def ml_status():
        from .ml import train as train_mod
        run = train_mod.latest_run(db)
        return {"run": run, "model_loaded": engine.ml is not None, "load_error": engine.ml_error,
                "model_meta": engine.ml.meta if engine.ml else None, "model_file": str(train_mod.MODEL_PATH),
                "prediction_engine": db.get_settings().get("prediction_engine")}

    @app.get("/api/backtest")
    def backtest_latest():
        from .engine.plan_backtest import latest_backtest
        return latest_backtest(db) or {}

    _check_cache: dict = {}

    @app.get("/api/model-check")
    def model_check_ep():
        s = db.get_settings()
        key = (engine.version, s["prior_weight"], s["recency_half_life"], s["goal_cap"])
        if key not in _check_cache:
            _check_cache.clear()
            _check_cache[key] = model_check(engine.store, s)
        return _check_cache[key]

    # ------------------------------------------------------------------ teams / aliases
    @app.get("/api/teams/links")
    def team_links():
        run = engine.latest_import()
        info = json.loads(run["warnings"]) if run and run.get("warnings") else {}
        aliases = db.query("SELECT * FROM team_aliases ORDER BY origin, alias_key")
        return {"links": info.get("links", []), "unlinked": info.get("unlinked_teams", []), "aliases": aliases}

    @app.get("/api/teams/search")
    def team_search(q: str = Query(min_length=2)):
        k = team_key(q)
        ids = sorted({tid for tid in engine.store.by_team if k in tid and not tid.startswith("UEFA:")})
        return ids[:30]


    @app.post("/api/teams/aliases")
    def add_alias(body: AliasIn):
        if body.target_team_id not in engine.store.by_team:
            raise HTTPException(422, "Unknown target team id (use the search).")
        db.execute("INSERT INTO team_aliases VALUES(?,?,?,?,?) ON CONFLICT(alias_key, scope) DO UPDATE SET "
                   "target_team_id=excluded.target_team_id, origin='user', created_at=excluded.created_at",
                   (team_key(body.alias_name), "*", body.target_team_id, "user", iso(now_utc())))
        return {"ok": True, "notice": "Saved. Re-run the import (or 'Re-process local data') to apply the link."}

    @app.delete("/api/teams/aliases/{alias_key}")
    def del_alias(alias_key: str):
        db.execute("DELETE FROM team_aliases WHERE alias_key=? AND origin='user'", (alias_key,))
        return {"ok": True}

    @app.post("/api/import/reprocess")
    def reprocess():
        if not (config.RAW_DIR / "data").is_dir():
            raise HTTPException(400, "No downloaded dataset yet. Run the importer first.")
        rep = import_from_directory(db, config.RAW_DIR, method="reprocess")
        engine.refresh()
        return {"ok": True, "results": rep.results, "fixtures": rep.fixtures, "unlinked_teams": rep.unlinked_teams}

    # ------------------------------------------------------------------ settings & AI
    @app.get("/api/settings")
    def get_settings():
        return {"values": db.get_settings(), "defaults": config.DEFAULT_SETTINGS, "target_presets": config.TARGET_PRESETS}

    @app.put("/api/settings")
    def put_settings(values: dict = Body(...)):
        try:
            if "timezone" in values:
                tz(str(values["timezone"]))
            if "plan_targets" in values:
                values["plan_targets"] = ",".join(f"{t:g}" for t in parse_targets(values["plan_targets"]))
            if isinstance(values.get("plan_weekend_competitions"), list):
                values["plan_weekend_competitions"] = ",".join(values["plan_weekend_competitions"])
            out = db.update_settings(values)
        except (KeyError, ValueError) as exc:
            raise HTTPException(422, str(exc))
        engine.invalidate()
        return {"values": out}

    @app.get("/api/ai/status")
    def ai_status():
        return OllamaClient(db.get_settings()).status()

    # ------------------------------------------------------------------ frontend
    dist = config.FRONTEND_DIST
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "Not found")
            f = dist / path
            if path and f.is_file():
                return FileResponse(f)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend():
            return {"message": "Frontend not built. Run ./start.sh (or: cd frontend && npm install && npm run build)."}

    return app


app = None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
