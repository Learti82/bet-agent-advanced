"""Shared fixtures: a small, deterministic synthetic Open-Matchday-shaped dataset (no network)."""
from __future__ import annotations

import os
import tempfile

# Tests must never read or write the user's real data (database, downloads, trained model):
# point the data directory at a throwaway folder before any matchedge module is imported.
os.environ["MATCHEDGE_DATA_DIR"] = tempfile.mkdtemp(prefix="matchedge-test-")

import csv
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from matchedge.importer import FIXTURES_COLUMNS, RESULTS_COLUMNS

TEAMS = ["Alpha FC", "Bravo United", "Charlie City", "Delta Rovers", "Echo Athletic", "Foxtrot Town",
         "Golf Wanderers", "Hotel Albion"]
STRENGTH = {"Alpha FC": 1.9, "Bravo United": 1.6, "Charlie City": 1.4, "Delta Rovers": 1.2,
            "Echo Athletic": 1.1, "Foxtrot Town": 1.0, "Golf Wanderers": 0.8, "Hotel Albion": 0.6}


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth
    import math
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def make_dataset(root: Path, *, n_rounds: int = 12, fixture_day: date | None = None,
                 extra_results: list[dict] | None = None, drop_corners_every: int = 4,
                 generated_utc: str | None = None) -> Path:
    rng = random.Random(42)
    today = datetime.now(timezone.utc).date()
    fixture_day = fixture_day or (today + timedelta(days=3))
    start = fixture_day - timedelta(days=7 * (n_rounds + 1))
    folder = root / "data" / "ENG_1_premier-league"
    folder.mkdir(parents=True, exist_ok=True)
    pairs = [(h, a) for h in TEAMS for a in TEAMS if h != a]
    rng.shuffle(pairs)
    results, i = [], 0
    for rnd in range(n_rounds):
        d = start + timedelta(days=7 * rnd)
        used: set[str] = set()
        for h, a in pairs:
            if h in used or a in used:
                continue
            if (h, a) in {(r["home"], r["away"]) for r in results}:
                continue
            used |= {h, a}
            fh = _poisson(rng, STRENGTH[h] * 1.15)
            fa = _poisson(rng, STRENGTH[a] * 0.9)
            hh, ha = min(fh, _poisson(rng, fh * 0.45)), min(fa, _poisson(rng, fa * 0.45))
            i += 1
            missing = drop_corners_every and i % drop_corners_every == 0
            results.append({
                "gw": rnd + 1, "date": d.isoformat(), "time": "15:00", "home": h, "away": a,
                "ft_home": fh, "ft_away": fa, "ft_result": "H" if fh > fa else "D" if fh == fa else "A",
                "ht_home": hh, "ht_away": ha, "ht_result": "H" if hh > ha else "D" if hh == ha else "A",
                "home_shots": 10 + fh * 2, "away_shots": 8 + fa * 2, "home_target": 3 + fh, "away_target": 2 + fa,
                "home_fouls": 11, "away_fouls": 12,
                "home_corners": "" if missing else 4 + rng.randint(0, 5),
                "away_corners": "" if missing else 3 + rng.randint(0, 4),
                "home_corners_1h": "", "away_corners_1h": "", "home_corners_2h": "", "away_corners_2h": "",
                "home_yellow": rng.randint(0, 4), "away_yellow": rng.randint(0, 4), "home_red": 0, "away_red": 0,
                "goal_minutes": "", "source": "fixturedl",
            })
            if len(used) == len(TEAMS):
                break
    results += extra_results or []
    fixtures = [
        {"gw": n_rounds + 1, "date": fixture_day.isoformat(), "time": "21:00", "home": "Alpha FC", "away": "Hotel Albion"},
        {"gw": n_rounds + 1, "date": fixture_day.isoformat(), "time": "18:30", "home": "Delta Rovers", "away": "Echo Athletic"},
        {"gw": n_rounds + 1, "date": fixture_day.isoformat(), "time": "", "home": "Bravo United", "away": "Golf Wanderers"},
        {"gw": n_rounds + 1, "date": (today - timedelta(days=1)).isoformat(), "time": "20:00",
         "home": "Charlie City", "away": "Foxtrot Town"},  # kickoff passed, no result yet
    ]
    with open(folder / "results_2627.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RESULTS_COLUMNS)
        w.writeheader()
        w.writerows(results)
    with open(folder / "fixtures_2627.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIXTURES_COLUMNS)
        w.writeheader()
        w.writerows(fixtures)
    gen = generated_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (root / "build_summary.json").write_text(json.dumps({
        "season": "2627", "generated_utc": gen,
        "leagues": [{"league": "Premier League", "folder": "data/ENG_1_premier-league", "results": len(results),
                     "fixtures": len(fixtures), "errors": [], "latest": results[-1]["date"]}]}))
    (root / "LEAGUE_INDEX.md").write_text(
        "| Folder | League | Country | Sources | Goal minutes | Fixture spine |\n|---|---|---|---|---|---|\n"
        "| `ENG_1_premier-league` | Premier League | England | test | ❌ | full season |\n")
    return root


@pytest.fixture()
def dataset(tmp_path: Path) -> Path:
    return make_dataset(tmp_path / "om")


@pytest.fixture()
def db(tmp_path: Path):
    from matchedge.db import Database
    return Database(tmp_path / "test.sqlite3")


@pytest.fixture()
def loaded(db, dataset):
    from matchedge.engine.analysis import Engine
    from matchedge.importer import import_from_directory
    import_from_directory(db, dataset)
    return db, Engine(db)
