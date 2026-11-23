"""football-data.co.uk importer (free historical results, statistics and bookmaker odds).

Used for:
  * previous-season form in the rating model (with a carry-over discount),
  * a profit backtest of the weekend plan with the real Bet365 prices of the time,
  * Bet365 closing odds for closing-line value of your own bets (current season).

Terms: football-data.co.uk is free for personal, non-commercial use; credit the site. Files are
downloaded to this computer only (data/football-data/, git-ignored) and never redistributed.

Team names differ from Open-Matchday ("Man United" vs "Man Utd"). Names are linked by finding the
*same matches* in both datasets for the current season (same competition, date ±1 day and score) and
taking the majority mapping; teams that cannot be linked keep their own identity (used only in
historical backtests). Completed seasons are downloaded once; the current season is refreshed.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.error
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from . import config
from .db import Database
from .importer import _http_get, nullable_int
from .teamnames import team_key
from .timeutil import iso, now_utc

BASE = "https://football-data.co.uk/mmz4281"
CURRENT_SEASON = config.SEASON  # "2627"
ATTRIBUTION = "Historical results and odds: football-data.co.uk (free for personal, non-commercial use)."

DIVISIONS = {
    "E0": "ENG_1_premier-league", "E1": "ENG_2_championship", "E2": "ENG_3_league-one", "E3": "ENG_4_league-two",
    "EC": "ENG_5_national-league", "SC0": "SCO_1_premiership", "SC1": "SCO_2_championship",
    "SC2": "SCO_3_league-one", "SC3": "SCO_4_league-two", "D1": "GER_1_bundesliga", "D2": "GER_2_2-bundesliga",
    "I1": "ITA_1_serie-a", "I2": "ITA_2_serie-b", "SP1": "ESP_1_la-liga", "SP2": "ESP_2_segunda-division",
    "F1": "FRA_1_ligue-1", "F2": "FRA_2_ligue-2", "N1": "NED_1_eredivisie", "B1": "BEL_1_pro-league",
    "P1": "POR_1_primeira-liga", "T1": "TUR_1_super-lig", "G1": "GRE_1_super-league",
}

# column in file -> column in hist_matches
INT_COLS = {"FTHG": "ft_home", "FTAG": "ft_away", "HTHG": "ht_home", "HTAG": "ht_away", "HS": "home_shots",
            "AS": "away_shots", "HST": "home_target", "AST": "away_target", "HF": "home_fouls", "AF": "away_fouls",
            "HC": "home_corners", "AC": "away_corners", "HY": "home_yellow", "AY": "away_yellow", "HR": "home_red",
            "AR": "away_red"}
ODDS_COLS = {"B365H": "b365_h", "B365D": "b365_d", "B365A": "b365_a", "B365CH": "b365c_h", "B365CD": "b365c_d",
             "B365CA": "b365c_a", "B365>2.5": "b365_o25", "B365<2.5": "b365_u25", "B365C>2.5": "b365c_o25",
             "B365C<2.5": "b365c_u25", "AHh": "ah_line", "B365AHH": "b365_ahh", "B365AHA": "b365_aha",
             "AHCh": "ahc_line", "B365CAHH": "b365c_ahh", "B365CAHA": "b365c_aha", "AvgCH": "avgc_h",
             "AvgCD": "avgc_d", "AvgCA": "avgc_a", "AvgC>2.5": "avgc_o25", "AvgC<2.5": "avgc_u25"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS hist_matches (
    id TEXT PRIMARY KEY, season TEXT NOT NULL, division TEXT NOT NULL, competition TEXT NOT NULL,
    date TEXT NOT NULL, time TEXT, home TEXT NOT NULL, away TEXT NOT NULL, home_key TEXT NOT NULL,
    away_key TEXT NOT NULL, referee TEXT,
    ft_home INTEGER, ft_away INTEGER, ht_home INTEGER, ht_away INTEGER, home_shots INTEGER, away_shots INTEGER,
    home_target INTEGER, away_target INTEGER, home_fouls INTEGER, away_fouls INTEGER, home_corners INTEGER,
    away_corners INTEGER, home_yellow INTEGER, away_yellow INTEGER, home_red INTEGER, away_red INTEGER,
    b365_h REAL, b365_d REAL, b365_a REAL, b365c_h REAL, b365c_d REAL, b365c_a REAL, b365_o25 REAL, b365_u25 REAL,
    b365c_o25 REAL, b365c_u25 REAL, ah_line REAL, b365_ahh REAL, b365_aha REAL, ahc_line REAL, b365c_ahh REAL,
    b365c_aha REAL, avgc_h REAL, avgc_d REAL, avgc_a REAL, avgc_o25 REAL, avgc_u25 REAL
);
CREATE INDEX IF NOT EXISTS ix_hist_comp_date ON hist_matches(competition, date);
CREATE INDEX IF NOT EXISTS ix_hist_keys ON hist_matches(home_key, away_key);
CREATE TABLE IF NOT EXISTS hist_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT, status TEXT, seasons TEXT,
    files INTEGER, rows INTEGER, name_links TEXT, warnings TEXT, error TEXT
);
"""

HIST_COLUMNS = ["id", "season", "division", "competition", "date", "time", "home", "away", "home_key", "away_key",
                "referee", *INT_COLS.values(), *ODDS_COLS.values()]


def ensure_schema(db: Database) -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)


def season_codes(n_completed: int, current: str = CURRENT_SEASON) -> list[str]:
    """['2627', '2526', ...] — the current season plus ``n_completed`` previous ones."""
    start = int(current[:2])
    return [f"{(start - i) % 100:02d}{(start - i + 1) % 100:02d}" for i in range(n_completed + 1)]


def _date(v: str) -> str | None:
    v = (v or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _float(v: str | None) -> float | None:
    try:
        f = float(v) if v not in (None, "") else None
    except ValueError:
        return None
    return f


def parse_file(text: str, season: str, division: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or not {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"} <= set(reader.fieldnames):
        raise ValueError(f"{season}/{division}: unexpected header")
    comp = DIVISIONS[division]
    out = []
    for r in reader:
        d = _date(r.get("Date", ""))
        if not d or not r.get("HomeTeam") or not r.get("AwayTeam") or r.get("FTHG", "") == "":
            continue
        row = {"season": season, "division": division, "competition": comp, "date": d,
               "time": (r.get("Time") or "").strip() or None, "home": r["HomeTeam"].strip(),
               "away": r["AwayTeam"].strip(), "referee": (r.get("Referee") or "").strip() or None}
        for src, dst in INT_COLS.items():
            row[dst] = nullable_int(r.get(src))
        for src, dst in ODDS_COLS.items():
            row[dst] = _float(r.get(src))
        out.append(row)
    return out


def download(seasons: list[str], dest: Path = config.DATA_DIR / "football-data",
             fetch: Callable[[str], bytes] = _http_get, log: Callable[[str], None] = lambda m: None,
             refresh_current: bool = True) -> tuple[dict[tuple[str, str], str], list[str]]:
    texts: dict[tuple[str, str], str] = {}
    warnings: list[str] = []
    for season in seasons:
        for div in DIVISIONS:
            path = dest / season / f"{div}.csv"
            if path.exists() and not (refresh_current and season == CURRENT_SEASON):
                texts[(season, div)] = path.read_text(encoding="utf-8", errors="replace")
                continue
            try:
                blob = fetch(f"{BASE}/{season}/{div}.csv")
            except urllib.error.HTTPError as exc:
                warnings.append(f"{season}/{div}: HTTP {exc.code}")
                continue
            except (urllib.error.URLError, OSError) as exc:
                if path.exists():
                    warnings.append(f"{season}/{div}: download failed ({exc}); using cached file")
                    texts[(season, div)] = path.read_text(encoding="utf-8", errors="replace")
                    continue
                raise
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
            texts[(season, div)] = blob.decode("utf-8", errors="replace")
        log(f"football-data {season}: {sum(1 for (s, _) in texts if s == season)} divisions")
    return texts, warnings


def learn_name_links(db: Database, current_rows: list[dict]) -> dict[str, str]:
    """Map football-data team keys to Open-Matchday team ids using identical current-season matches."""
    om = db.query("SELECT competition, date, home_key, away_key, ft_home, ft_away FROM matches "
                  "WHERE status='finished'")
    idx: dict[tuple, list[dict]] = defaultdict(list)
    for m in om:
        idx[(m["competition"], m["ft_home"], m["ft_away"])].append(m)
    votes: dict[str, Counter] = defaultdict(Counter)
    for r in current_rows:
        d = date.fromisoformat(r["date"])
        cands = [m for m in idx.get((r["competition"], r["ft_home"], r["ft_away"]), [])
                 if abs((date.fromisoformat(m["date"]) - d).days) <= 1]
        if len(cands) != 1:
            continue
        m = cands[0]
        country = r["competition"].split("_")[0]
        votes[f"{country}:{team_key(r['home'])}"][m["home_key"]] += 1
        votes[f"{country}:{team_key(r['away'])}"][m["away_key"]] += 1
    links: dict[str, str] = {}
    for fd_key, c in votes.items():
        target, n = c.most_common(1)[0]
        if n >= 2 and n >= 0.8 * sum(c.values()):
            links[fd_key] = target
    # a target may only be claimed once
    claimed = Counter(links.values())
    return {k: v for k, v in links.items() if claimed[v] == 1}


def import_history(db: Database, n_completed: int = 5, fetch: Callable[[str], bytes] = _http_get,
                   log: Callable[[str], None] = print, dest: Path | None = None) -> dict:
    ensure_schema(db)
    seasons = season_codes(n_completed)
    run = db.execute("INSERT INTO hist_imports(started_at, status, seasons) VALUES(?,?,?)",
                     (iso(now_utc()), "running", ",".join(seasons)))
    try:
        texts, warnings = download(seasons, dest or config.DATA_DIR / "football-data", fetch, log)
        rows: list[dict] = []
        for (season, div), text in texts.items():
            try:
                rows += parse_file(text, season, div)
            except ValueError as exc:
                warnings.append(str(exc))
        links = learn_name_links(db, [r for r in rows if r["season"] == CURRENT_SEASON])
        for r in rows:
            country = r["competition"].split("_")[0]
            hk, ak = f"{country}:{team_key(r['home'])}", f"{country}:{team_key(r['away'])}"
            r["home_key"], r["away_key"] = links.get(hk, hk), links.get(ak, ak)
            r["id"] = f"FD|{r['season']}|{r['division']}|{r['date']}|{r['home_key']}|{r['away_key']}"
        dedup = {r["id"]: r for r in rows}
        with db.tx() as c:
            c.execute("DELETE FROM hist_matches")
            c.executemany(f"INSERT INTO hist_matches({','.join(HIST_COLUMNS)}) VALUES({','.join('?' * len(HIST_COLUMNS))})",
                          [tuple(r.get(k) for k in HIST_COLUMNS) for r in dedup.values()])
        current_names = {f"{r['competition'].split('_')[0]}:{team_key(n)}" for r in rows
                         if r["season"] == CURRENT_SEASON for n in (r["home"], r["away"])}
        unlinked = sorted(k for k in current_names if k not in links)
        summary = {"seasons": seasons, "files": len(texts), "rows": len(dedup), "linked_teams": len(links),
                   "unlinked_current_teams": unlinked, "warnings": warnings[:100]}
        db.execute("UPDATE hist_imports SET finished_at=?, status='ok', files=?, rows=?, name_links=?, warnings=? "
                   "WHERE id=?", (iso(now_utc()), len(texts), len(dedup), json.dumps(links),
                                  json.dumps({"unlinked": unlinked, "warnings": warnings[:100]}), run))
        return summary
    except Exception as exc:
        db.execute("UPDATE hist_imports SET finished_at=?, status='failed', error=? WHERE id=?",
                   (iso(now_utc()), str(exc), run))
        raise


def history_rows(db: Database, exclude_season: str | None = CURRENT_SEASON) -> list[dict]:
    """Historical matches as Open-Matchday-shaped finished rows (for the in-memory store)."""
    ensure_schema(db)
    rows = db.query("SELECT * FROM hist_matches" + (" WHERE season != ?" if exclude_season else ""),
                    (exclude_season,) if exclude_season else ())
    for r in rows:
        r["status"] = "finished"
        r["kickoff_utc"] = None
        r["source"] = "football-data"
    return rows


def status(db: Database) -> dict:
    ensure_schema(db)
    last = db.one("SELECT * FROM hist_imports ORDER BY id DESC LIMIT 1")
    counts = db.query("SELECT season, COUNT(*) n, SUM(b365_h IS NOT NULL) odds, SUM(b365c_h IS NOT NULL) closing "
                      "FROM hist_matches GROUP BY season ORDER BY season DESC")
    if last and last.get("warnings"):
        last["warnings"] = json.loads(last["warnings"])
    if last:
        last.pop("name_links", None)
    return {"last_import": last, "seasons": counts, "attribution": ATTRIBUTION}


def closing_row(db: Database, competition: str, home_key: str, away_key: str, day: str) -> dict | None:
    """Current-season football-data row for a match (for Bet365 closing odds)."""
    ensure_schema(db)
    d = date.fromisoformat(day)
    return db.one("SELECT * FROM hist_matches WHERE competition=? AND home_key=? AND away_key=? AND date BETWEEN ? AND ? "
                  "ORDER BY date LIMIT 1", (competition, home_key, away_key, (d - timedelta(days=1)).isoformat(),
                                            (d + timedelta(days=1)).isoformat()))
