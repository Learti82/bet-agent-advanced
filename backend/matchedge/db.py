"""SQLite storage (standard library only).

Tables
------
import_runs        one row per dataset import (freshness, commit, coverage, warnings)
competitions       competition metadata and per-statistic coverage
matches            fixtures and results from Open-Matchday (re-written on each import)
fixture_overrides  user corrections: kickoff time, status, verification against official sites
odds               prices: manually entered (primary) or dataset snapshots (labelled as such)
research_sources   manual research entries (URL, statistic, notes, time checked, reliability)
team_aliases       name mappings (seeded + user-defined) used to link teams across competitions
tickets            saved accumulator tickets with their full report
predictions        one row per saved selection; settled against later results
settings           key/value JSON settings
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    method TEXT,
    commit_sha TEXT,
    dataset_generated_utc TEXT,
    n_competitions INTEGER,
    n_results INTEGER,
    n_fixtures INTEGER,
    warnings TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS competitions (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT,
    country_code TEXT,
    tier TEXT,
    kind TEXT,
    sources TEXT,
    n_results INTEGER,
    n_fixtures INTEGER,
    latest_result TEXT,
    coverage TEXT,
    has_odds INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    competition TEXT NOT NULL,
    gw INTEGER,
    date TEXT NOT NULL,
    time TEXT,
    kickoff_utc TEXT,
    time_source TEXT,
    status TEXT NOT NULL,
    home TEXT NOT NULL,
    away TEXT NOT NULL,
    home_key TEXT NOT NULL,
    away_key TEXT NOT NULL,
    ft_home INTEGER, ft_away INTEGER, ht_home INTEGER, ht_away INTEGER,
    home_shots INTEGER, away_shots INTEGER, home_target INTEGER, away_target INTEGER,
    home_fouls INTEGER, away_fouls INTEGER, home_corners INTEGER, away_corners INTEGER,
    home_corners_1h INTEGER, away_corners_1h INTEGER, home_corners_2h INTEGER, away_corners_2h INTEGER,
    home_yellow INTEGER, away_yellow INTEGER, home_red INTEGER, away_red INTEGER,
    goal_minutes TEXT,
    source TEXT,
    dataset_match_id TEXT,
    import_run_id INTEGER,
    in_latest_import INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_matches_comp ON matches(competition);
CREATE INDEX IF NOT EXISTS ix_matches_date ON matches(date);
CREATE INDEX IF NOT EXISTS ix_matches_keys ON matches(home_key, away_key);

CREATE TABLE IF NOT EXISTS fixture_overrides (
    match_id TEXT PRIMARY KEY,
    kickoff_local TEXT,
    status TEXT,
    verified INTEGER DEFAULT 0,
    verification_url TEXT,
    note TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS odds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    line REAL,
    odds REAL NOT NULL,
    checked_at TEXT NOT NULL,
    source TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_odds_match ON odds(match_id);
CREATE TABLE IF NOT EXISTS research_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    url TEXT,
    match_label TEXT,
    category TEXT NOT NULL,
    statistic TEXT,
    value TEXT,
    notes TEXT,
    checked_at TEXT NOT NULL,
    reliability TEXT NOT NULL,
    impact TEXT NOT NULL DEFAULT 'neutral',
    related_market TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_research_match ON research_sources(match_id);
CREATE TABLE IF NOT EXISTS team_aliases (
    alias_key TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '*',
    target_team_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (alias_key, scope)
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT,
    target_odds REAL,
    combined_odds REAL,
    n_selections INTEGER,
    kind TEXT,
    report TEXT
);
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER,
    created_at TEXT NOT NULL,
    match_id TEXT NOT NULL,
    competition TEXT,
    match_label TEXT,
    home_key TEXT,
    away_key TEXT,
    kickoff_utc TEXT,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    line REAL,
    odds REAL,
    odds_source TEXT,
    model_probability REAL,
    implied_probability REAL,
    selection_score REAL,
    data_quality REAL,
    confidence TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    settled_at TEXT,
    result_detail TEXT,
    settled_by TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_lock = threading.RLock()


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = Path(path or config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class Database:
    """Thin wrapper; one connection guarded by a lock (single local user)."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or config.DB_PATH)
        self.conn = connect(self.path)
        with _lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with _lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with _lock:
            cur = self.conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self.tx() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    # ---- settings -------------------------------------------------------------
    def get_settings(self) -> dict[str, Any]:
        out = dict(config.DEFAULT_SETTINGS)
        for row in self.query("SELECT key, value FROM settings"):
            if row["key"] in out:
                try:
                    out[row["key"]] = json.loads(row["value"])
                except json.JSONDecodeError:
                    pass
        return out

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        current = self.get_settings()
        with self.tx() as c:
            for k, v in values.items():
                if k not in config.DEFAULT_SETTINGS:
                    raise KeyError(f"Unknown setting: {k}")
                default = config.DEFAULT_SETTINGS[k]
                if isinstance(default, bool):
                    v = bool(v)
                elif isinstance(default, int):
                    v = int(v)
                elif isinstance(default, float):
                    v = float(v)
                elif isinstance(default, str):
                    v = str(v)
                current[k] = v
                c.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, json.dumps(v)),
                )
        return current
