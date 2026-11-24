"""Application configuration and user-adjustable analysis settings.

Everything runs locally. Paths default to the repository's ``data/`` folder and can be
overridden with the ``MATCHEDGE_DATA_DIR`` environment variable.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MATCHEDGE_DATA_DIR", ROOT_DIR / "data"))
RAW_DIR = DATA_DIR / "open-matchday"
DB_PATH = Path(os.environ.get("MATCHEDGE_DB", DATA_DIR / "matchedge.sqlite3"))
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

APP_NAME = "MatchEdge Local"
SEASON = "2627"

OPEN_MATCHDAY_REPO = "https://github.com/oladeeayo/open-matchday"
OPEN_MATCHDAY_BRANCH = "master"
OPEN_MATCHDAY_ZIP = f"{OPEN_MATCHDAY_REPO}/archive/refs/heads/{OPEN_MATCHDAY_BRANCH}.zip"
OPEN_MATCHDAY_RAW = f"https://raw.githubusercontent.com/oladeeayo/open-matchday/{OPEN_MATCHDAY_BRANCH}"
OPEN_MATCHDAY_CDN = f"https://cdn.jsdelivr.net/gh/oladeeayo/open-matchday@{OPEN_MATCHDAY_BRANCH}"

ATTRIBUTION = (
    "Match data: open-matchday (https://github.com/oladeeayo/open-matchday), compiled from "
    "football-data.co.uk, ESPN, FotMob, Soccerway, OpenLigaDB and fixturedownload. "
    "Informational, non-commercial use only; provider rights remain with the providers."
)

# Default analysis settings. Stored in SQLite and editable from the Settings page.
DEFAULT_SETTINGS: dict[str, object] = {
    "timezone": "Europe/Belgrade",
    "bookmaker": "Bet365",
    # --- model ---
    # recency/shrinkage chosen by a walk-forward check on 2026/27 results (Historical performance →
    # Model check): prior 12 / half-life 16 gave the lowest log loss and cut overconfidence on 80%+
    # predictions from ~3 points (prior 4 / half-life 8) to ~1 point.
    "recency_half_life": 16.0,  # matches; weight halves every N matches back in time
    "prior_weight": 12.0,  # pseudo-matches of league-average shrinkage per rating
    "min_matches_model": 5,  # per team, below this the model returns "Insufficient data"
    "min_matches_stat": 5,  # per team, below this a statistic is flagged as a small sample
    "goal_cap": 5,  # goals per team per match counted when estimating ratings (extreme results)
    "min_league_matches": 30,  # competition matches needed for a reliable league baseline
    "cross_league_shrink": 0.5,
    # --- trained ML model ---
    # "auto": use the trained model for covered domestic-league fixtures when it beat the statistical engine
    # out of sample (per market); "statistical": never; "ml": same as auto (ML is only used where it validated)
    "prediction_engine": "auto",
    # --- historical seasons (football-data.co.uk) ---
    "history_enabled": True,
    "history_seasons": 5,  # completed seasons to download
    # weight of a previous-season match relative to a current-season one; 0.75 gave the lowest walk-forward
    # log loss on 2025/26 and 2026/27 (no history: 0.6528 early-season log loss in 2025/26 → 0.6459)
    "history_carryover": 0.75,  # how much domestic ratings are trusted in cross-league fixtures
    # --- selection / rejection ---
    "min_leg_probability": 0.60,
    "min_leg_odds": 1.30,  # shorter prices add almost nothing to a ticket but still carry full risk
    "max_snapshot_candidate_odds": 3.5,  # snapshot lines outside [min_leg_odds, this] are not candidates
    "min_evidence_score": 35.0,  # evidence (0-85) a market needs before it can be recommended
    "min_selection_score": 55.0,
    "strong_selection_score": 68.0,
    "max_dataset_age_days": 3,
    "team_stale_days": 21,
    "close_match_xg_gap": 0.30,
    "conflict_threshold": 0.22,  # model vs historical hit-rate disagreement that counts as conflict
    # --- accumulator ---
    "default_target_odds": 110.0,
    "allow_snapshot_odds": True,  # allow dataset snapshot prices (clearly labelled) in auto-build
    "max_legs": 10,
    # --- weekly plan ---
    "plan_targets": "50,110",  # one ticket per target for each slot
    "plan_max_legs": 14,  # leg limit for weekly-plan tickets (a 110 ticket from ~1.4 prices needs ~13 legs)
    "plan_weekend_competitions": "",  # comma-separated codes; empty = European top divisions
    # --- optional local AI ---
    "ai_enabled": False,
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "llama3.1:8b",
    "allow_non_local_ai_host": False,
    "ai_timeout_seconds": 90,
}

TARGET_PRESETS = [10.0, 30.0, 50.0, 110.0, 150.0, 300.0]
