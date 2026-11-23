"""Open-Matchday importer.

Download order (all free, no keys):
  1. GitHub ZIP archive (one request; the ZIP comment carries the commit SHA)
  2. raw.githubusercontent.com per file (folder list from build_summary.json)
  3. jsDelivr CDN mirror per file
  4. a local folder (``git clone`` of the repository) via ``import_from_directory``

Each CSV is validated against the documented header. Missing columns abort that file; blank
cells stay NULL (never zero). Team names are normalised, fixtures and results are written to
SQLite, and dataset freshness (``build_summary.json`` → ``generated_utc``) is recorded.

Odds snapshot files (Flashscore pre-match quotes for bet365/Betway/Betano, published by the
dataset) are imported as *reference snapshots* only, labelled with their snapshot time.
"""
from __future__ import annotations

import csv
import io
import json
import re
import shutil
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from . import config
from .db import Database
from .teamnames import SEED_ALIASES, TeamResolver, country_of, is_domestic_league, team_key
from .timeutil import dataset_kickoff_utc, iso, now_utc, parse_iso

RESULTS_COLUMNS = [
    "gw", "date", "time", "home", "away", "ft_home", "ft_away", "ft_result", "ht_home", "ht_away",
    "ht_result", "home_shots", "away_shots", "home_target", "away_target", "home_fouls",
    "away_fouls", "home_corners", "away_corners", "home_corners_1h", "away_corners_1h",
    "home_corners_2h", "away_corners_2h", "home_yellow", "away_yellow", "home_red", "away_red",
    "goal_minutes", "source",
]
FIXTURES_COLUMNS = ["gw", "date", "time", "home", "away"]
ODDS_FIXTURES_COLUMNS = ["date", "time", "home", "away", "match_id", "kickoff_utc", "update_utc"]
ODDS_MARKETS_COLUMNS = ["match_id", "bookmaker", "market", "scope", "line", "selection", "odds"]
INT_STATS = [c for c in RESULTS_COLUMNS if c not in ("date", "time", "home", "away", "ft_result",
                                                     "ht_result", "goal_minutes", "source")]
CORE_FILES = ["results", "fixtures", "goals"]
ODDS_FILES = ["odds_fixtures", "odds_markets"]
USER_AGENT = "MatchEdgeLocal/1.0 (personal research tool)"

COUNTRY_NAMES = {
    "ARG": "Argentina", "AUS": "Australia", "AUT": "Austria", "BEL": "Belgium", "BRA": "Brazil",
    "CHN": "China", "CRO": "Croatia", "CYP": "Cyprus", "CZE": "Czechia", "DEN": "Denmark",
    "ENG": "England", "ESP": "Spain", "FIN": "Finland", "FRA": "France", "GER": "Germany",
    "GRE": "Greece", "IRE": "Ireland", "ITA": "Italy", "JPN": "Japan", "KAZ": "Kazakhstan",
    "MEX": "Mexico", "NED": "Netherlands", "NOR": "Norway", "POL": "Poland", "POR": "Portugal",
    "ROU": "Romania", "RUS": "Russia", "SCO": "Scotland", "SUI": "Switzerland", "SVK": "Slovakia",
    "SVN": "Slovenia", "SWE": "Sweden", "TUR": "Türkiye", "UEFA": "UEFA", "UKR": "Ukraine",
    "USA": "USA", "WAL": "Wales",
}


class ImportErrorMatchEdge(RuntimeError):
    pass


@dataclass
class ImportReport:
    method: str = ""
    commit_sha: str | None = None
    generated_utc: str | None = None
    competitions: int = 0
    results: int = 0
    fixtures: int = 0
    snapshot_prices: int = 0
    archived_prices: int = 0
    warnings: list[str] = field(default_factory=list)
    unlinked_teams: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------- download
def _http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed public URLs)
        return resp.read()


def download_dataset(dest: Path = config.RAW_DIR, fetch: Callable[[str], bytes] = _http_get,
                     log: Callable[[str], None] = lambda m: None) -> tuple[Path, str, str | None]:
    """Download the dataset into ``dest`` and return (directory, method, commit_sha)."""
    tmp = dest.with_name(dest.name + ".download")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    errors: list[str] = []

    # 1) ZIP archive
    try:
        log("Downloading ZIP archive from GitHub…")
        blob = fetch(config.OPEN_MATCHDAY_ZIP)
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            sha = zf.comment.decode("ascii", "ignore").strip() or None
            for info in zf.infolist():
                parts = Path(info.filename).parts
                if len(parts) < 2 or info.is_dir():
                    continue
                rel = Path(*parts[1:])
                if rel.suffix not in (".csv", ".json", ".md", ".cff"):
                    continue
                target = tmp / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info))
        _swap(tmp, dest)
        return dest, "github-zip", sha if sha and re.fullmatch(r"[0-9a-f]{40}", sha) else None
    except (urllib.error.URLError, zipfile.BadZipFile, OSError, ValueError) as exc:
        errors.append(f"ZIP: {exc}")
        log(f"ZIP download unavailable ({exc}); falling back to per-file download.")

    # 2/3) per-file from raw GitHub, then jsDelivr
    for base, method in ((config.OPEN_MATCHDAY_RAW, "github-raw"), (config.OPEN_MATCHDAY_CDN, "jsdelivr")):
        try:
            summary = fetch(f"{base}/build_summary.json")
            (tmp / "build_summary.json").write_bytes(summary)
            for extra in ("LEAGUE_INDEX.md", "DATA_DICTIONARY.md", "DISCLAIMER.md"):
                try:
                    (tmp / extra).write_bytes(fetch(f"{base}/{extra}"))
                except (urllib.error.URLError, OSError):
                    pass
            folders = [lg["folder"] for lg in json.loads(summary)["leagues"]]
            log(f"Downloading {len(folders)} competitions via {method}…")
            for folder in folders:
                (tmp / folder).mkdir(parents=True, exist_ok=True)
                for name in CORE_FILES + ODDS_FILES:
                    rel = f"{folder}/{name}_{config.SEASON}.csv"
                    try:
                        (tmp / rel).write_bytes(fetch(f"{base}/{rel}"))
                    except urllib.error.HTTPError as exc:
                        if exc.code != 404:
                            raise
                        # optional files legitimately do not exist for every competition
            _swap(tmp, dest)
            return dest, method, None
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            errors.append(f"{method}: {exc}")
            log(f"{method} failed: {exc}")
    shutil.rmtree(tmp, ignore_errors=True)
    raise ImportErrorMatchEdge("All download methods failed: " + " | ".join(errors))


def _swap(tmp: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)


# --------------------------------------------------------------------------- parsing
def _read_csv(path: Path, required: Iterable[str]) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        missing = [c for c in required if c not in header]
        if missing:
            raise ImportErrorMatchEdge(f"{path.name}: missing columns {missing}")
        return [{k: (v or "").strip() for k, v in row.items() if k is not None} for row in reader]


def nullable_int(value: str | None) -> int | None:
    """Blank -> None. Never coerce a missing statistic to zero."""
    if value is None:
        return None
    v = str(value).strip()
    if v == "":
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def parse_league_index(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*`([^`]+)`\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|", line)
        if m:
            out[m.group(1)] = {"name": m.group(2).strip(), "country": m.group(3).strip(),
                               "sources": m.group(4).strip()}
    return out


def competition_kind(code: str) -> str:
    if code.startswith("UEFA_"):
        return "international"
    if "_CUP_" in code:
        return "cup"
    if "_U21_" in code:
        return "reserve"
    return "league"


def match_id(code: str, date: str, home_key: str, away_key: str) -> str:
    return f"{code}|{date}|{home_key}|{away_key}"


# --------------------------------------------------------------------------- import
def import_from_directory(db: Database, root: Path, method: str = "local",
                          commit_sha: str | None = None) -> ImportReport:
    root = Path(root)
    data_dir = root / "data"
    if not data_dir.is_dir():
        raise ImportErrorMatchEdge(f"No data/ folder in {root}")
    report = ImportReport(method=method, commit_sha=commit_sha)
    started = iso(now_utc())
    run_id = db.execute("INSERT INTO import_runs(started_at, status, method) VALUES(?,?,?)",
                        (started, "running", method))
    try:
        summary = {}
        if (root / "build_summary.json").exists():
            summary = json.loads((root / "build_summary.json").read_text(encoding="utf-8"))
            report.generated_utc = summary.get("generated_utc")
        else:
            report.warnings.append("build_summary.json missing: dataset freshness unknown.")
        summary_by_folder = {Path(lg["folder"]).name: lg for lg in summary.get("leagues", [])}
        index = parse_league_index(root / "LEAGUE_INDEX.md")

        folders = sorted(p for p in data_dir.iterdir() if p.is_dir())
        raw: dict[str, dict[str, list[dict[str, str]]]] = {}
        for folder in folders:
            code = folder.name
            files: dict[str, list[dict[str, str]]] = {}
            for name, cols in (("results", RESULTS_COLUMNS), ("fixtures", FIXTURES_COLUMNS),
                               ("odds_fixtures", ODDS_FIXTURES_COLUMNS),
                               ("odds_markets", ODDS_MARKETS_COLUMNS)):
                path = folder / f"{name}_{config.SEASON}.csv"
                if not path.exists():
                    if name in ("results", "fixtures"):
                        report.warnings.append(f"{code}: {path.name} not found")
                    continue
                try:
                    files[name] = _read_csv(path, cols)
                except ImportErrorMatchEdge as exc:
                    report.warnings.append(str(exc))
            if "results" in files or "fixtures" in files:
                raw[code] = files

        # team identities: domestic league keys first, then link international names
        domestic: dict[str, set[str]] = {}
        for code, files in raw.items():
            if not is_domestic_league(code):
                continue
            for row in files.get("results", []) + files.get("fixtures", []):
                for nm in (row["home"], row["away"]):
                    k = team_key(nm)
                    domestic.setdefault(k, set()).add(f"{country_of(code)}:{k}")
        aliases = dict(SEED_ALIASES)
        for row in db.query("SELECT alias_key, target_team_id FROM team_aliases WHERE origin='user'"):
            aliases[row["alias_key"]] = row["target_team_id"]
        all_ids = {t for s in domestic.values() for t in s}
        for k, tid in SEED_ALIASES.items():
            if tid not in all_ids:
                report.warnings.append(f"Seed alias '{k}' -> {tid} not found in this dataset; ignored.")
        resolver = TeamResolver(domestic, aliases)

        rows_out: list[tuple] = []
        snapshot_rows: list[tuple] = []
        comps_out: list[tuple] = []
        imported_at = iso(now_utc())
        for code, files in raw.items():
            results = files.get("results", [])
            fixtures = files.get("fixtures", [])
            snap_index = _snapshot_index(code, files.get("odds_fixtures", []), resolver)
            seen: set[str] = set()
            for status, rows in (("finished", results), ("scheduled", fixtures)):
                for r in rows:
                    if not r.get("date") or not r.get("home") or not r.get("away"):
                        report.warnings.append(f"{code}: skipped row without date/teams")
                        continue
                    hk, ak = resolver.resolve(code, r["home"]), resolver.resolve(code, r["away"])
                    mid = match_id(code, r["date"], hk, ak)
                    if mid in seen:
                        if status == "scheduled":
                            continue  # already present as a result
                        report.warnings.append(f"{code}: duplicate result row {mid}")
                        continue
                    seen.add(mid)
                    ds_utc = dataset_kickoff_utc(r["date"], r.get("time"))
                    snap = snap_index.get((r["date"], hk)) or snap_index.get((r["date"], ak))
                    snap_utc = parse_iso(snap["kickoff_utc"]) if snap and snap.get("kickoff_utc") else None
                    kickoff = snap_utc or ds_utc
                    time_source = ("snapshot+dataset" if snap_utc and ds_utc else
                                   "snapshot" if snap_utc else "dataset" if ds_utc else "none")
                    stats = {c: nullable_int(r.get(c)) for c in INT_STATS} if status == "finished" else {}
                    rows_out.append((
                        mid, code, nullable_int(r.get("gw")), r["date"], r.get("time") or None,
                        iso(kickoff), time_source, status, r["home"], r["away"], hk, ak,
                        stats.get("ft_home"), stats.get("ft_away"), stats.get("ht_home"), stats.get("ht_away"),
                        stats.get("home_shots"), stats.get("away_shots"), stats.get("home_target"),
                        stats.get("away_target"), stats.get("home_fouls"), stats.get("away_fouls"),
                        stats.get("home_corners"), stats.get("away_corners"), stats.get("home_corners_1h"),
                        stats.get("away_corners_1h"), stats.get("home_corners_2h"), stats.get("away_corners_2h"),
                        stats.get("home_yellow"), stats.get("away_yellow"), stats.get("home_red"),
                        stats.get("away_red"), r.get("goal_minutes") or None, r.get("source") or None,
                        snap["match_id"] if snap else None, run_id, 1,
                    ))
                    if status == "scheduled" and snap:
                        snap["_mid"] = mid
            # snapshot prices (labelled), only for scheduled fixtures we could match
            markets = files.get("odds_markets", [])
            by_snap = {s["match_id"]: s for s in snap_index.values() if s.get("_mid")}
            for m in markets:
                s = by_snap.get(m["match_id"])
                if not s or m.get("scope") != "full_time":
                    continue
                price = _float(m.get("odds"))
                if price is None or price <= 1.0:
                    continue
                mk = _normalise_snapshot_market(m["market"], m["selection"], m.get("line"))
                if mk is None:
                    continue
                market, selection, line = mk
                snapshot_rows.append((s["_mid"], m["bookmaker"], market, selection, line, price,
                                      s.get("update_utc") or report.generated_utc or imported_at,
                                      "dataset_snapshot", "open-matchday odds snapshot (Flashscore pre-match quote)",
                                      imported_at))
            meta = index.get(code, {})
            summ = summary_by_folder.get(code, {})
            comps_out.append((
                code, meta.get("name") or summ.get("league") or code, meta.get("country") or
                COUNTRY_NAMES.get(country_of(code), country_of(code)), country_of(code),
                code.split("_")[1] if "_" in code else "", competition_kind(code), meta.get("sources"),
                len(results), len(fixtures), summ.get("latest"),
                json.dumps(_coverage(results)), 1 if files.get("odds_markets") else 0,
            ))

        with db.tx() as c:
            # Results are fully re-written. Scheduled rows that vanish from the source are kept and
            # marked 'missing_from_source' (possibly postponed/moved) so linked odds/notes survive.
            c.execute("DELETE FROM matches WHERE status='finished'")
            c.execute("UPDATE matches SET in_latest_import=0")
            c.executemany(
                "INSERT INTO matches VALUES(" + ",".join(["?"] * 37) + ") ON CONFLICT(id) DO UPDATE SET "
                "competition=excluded.competition, gw=excluded.gw, date=excluded.date, time=excluded.time, "
                "kickoff_utc=excluded.kickoff_utc, time_source=excluded.time_source, status=excluded.status, "
                "home=excluded.home, away=excluded.away, home_key=excluded.home_key, away_key=excluded.away_key, "
                "ft_home=excluded.ft_home, ft_away=excluded.ft_away, ht_home=excluded.ht_home, ht_away=excluded.ht_away, "
                "home_shots=excluded.home_shots, away_shots=excluded.away_shots, home_target=excluded.home_target, "
                "away_target=excluded.away_target, home_fouls=excluded.home_fouls, away_fouls=excluded.away_fouls, "
                "home_corners=excluded.home_corners, away_corners=excluded.away_corners, "
                "home_corners_1h=excluded.home_corners_1h, away_corners_1h=excluded.away_corners_1h, "
                "home_corners_2h=excluded.home_corners_2h, away_corners_2h=excluded.away_corners_2h, "
                "home_yellow=excluded.home_yellow, away_yellow=excluded.away_yellow, home_red=excluded.home_red, "
                "away_red=excluded.away_red, goal_minutes=excluded.goal_minutes, source=excluded.source, "
                "dataset_match_id=excluded.dataset_match_id, import_run_id=excluded.import_run_id, in_latest_import=1",
                rows_out,
            )
            # scheduled rows no longer in the source: keep, but mark (they may be postponed/moved)
            c.execute("UPDATE matches SET status='missing_from_source' WHERE in_latest_import=0 AND status='scheduled'")
            c.execute("DELETE FROM competitions")
            c.executemany("INSERT INTO competitions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", comps_out)
            # archive: keep every distinct snapshot price over time (for price history and closing-line value)
            latest = {(r[0], r[1], r[2], r[3], r[4]): r[5] for r in c.execute(
                "SELECT h.match_id, h.bookmaker, h.market, h.selection, h.line, h.odds FROM odds_history h JOIN "
                "(SELECT match_id, bookmaker, market, selection, IFNULL(line, -999) l, MAX(id) mid FROM odds_history "
                "GROUP BY match_id, bookmaker, market, selection, IFNULL(line, -999)) x ON h.id = x.mid")}
            archive = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], "dataset_snapshot") for r in snapshot_rows
                       if latest.get((r[0], r[1], r[2], r[3], r[4])) != r[5]]
            c.executemany("INSERT INTO odds_history(match_id, bookmaker, market, selection, line, odds, captured_at, "
                          "source) VALUES(?,?,?,?,?,?,?,?)", archive)
            report.archived_prices = len(archive)
            c.execute("DELETE FROM odds WHERE source='dataset_snapshot'")
            c.executemany("INSERT INTO odds(match_id, bookmaker, market, selection, line, odds, checked_at, "
                          "source, note, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", snapshot_rows)
            c.execute("DELETE FROM team_aliases WHERE origin='seed'")
            c.executemany("INSERT OR IGNORE INTO team_aliases VALUES(?,?,?,?,?)",
                          [(k, "*", v, "seed", imported_at) for k, v in SEED_ALIASES.items() if v in all_ids])

        report.competitions = len(comps_out)
        report.results = sum(1 for r in rows_out if r[7] == "finished")
        report.fixtures = sum(1 for r in rows_out if r[7] == "scheduled")
        report.snapshot_prices = len(snapshot_rows)
        report.unlinked_teams = [v for v in resolver.links.values() if v["method"] in ("unlinked", "ambiguous")]
        db.execute(
            "UPDATE import_runs SET finished_at=?, status=?, commit_sha=?, dataset_generated_utc=?, "
            "n_competitions=?, n_results=?, n_fixtures=?, warnings=? WHERE id=?",
            (iso(now_utc()), "ok", commit_sha, report.generated_utc, report.competitions, report.results,
             report.fixtures, json.dumps({"warnings": report.warnings[:200],
                                          "unlinked_teams": report.unlinked_teams,
                                          "links": list(resolver.links.values()),
                                          "snapshot_prices": report.snapshot_prices}), run_id),
        )
        return report
    except Exception as exc:
        db.execute("UPDATE import_runs SET finished_at=?, status='failed', error=? WHERE id=?",
                   (iso(now_utc()), str(exc), run_id))
        raise


def run_import(db: Database, log: Callable[[str], None] = print,
               fetch: Callable[[str], bytes] = _http_get) -> ImportReport:
    path, method, sha = download_dataset(config.RAW_DIR, fetch=fetch, log=log)
    return import_from_directory(db, path, method=method, commit_sha=sha)


# --------------------------------------------------------------------------- helpers
def _float(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _snapshot_index(code: str, rows: list[dict[str, str]], resolver: TeamResolver) -> dict:
    """Index odds-snapshot fixtures by (date, team id) — a team plays at most once per day."""
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        if not r.get("date"):
            continue
        rec = dict(r)
        for nm in (r.get("home", ""), r.get("away", "")):
            out[(r["date"], resolver.resolve(code, nm))] = rec
    return out


_SNAPSHOT_MARKETS = {
    ("home_draw_away", "home"): ("1X2", "home"), ("home_draw_away", "draw"): ("1X2", "draw"),
    ("home_draw_away", "away"): ("1X2", "away"),
    ("double_chance", "1X"): ("DC", "1X"), ("double_chance", "X2"): ("DC", "X2"),
    ("double_chance", "12"): ("DC", "12"),
    ("draw_no_bet", "home"): ("DNB", "home"), ("draw_no_bet", "away"): ("DNB", "away"),
    ("both_teams_to_score", "yes"): ("BTTS", "yes"), ("both_teams_to_score", "no"): ("BTTS", "no"),
    ("over_under", "over"): ("OU", "over"), ("over_under", "under"): ("OU", "under"),
    ("asian_handicap", "home"): ("AH", "home"), ("asian_handicap", "away"): ("AH", "away"),
}


def _normalise_snapshot_market(market: str, selection: str, line: str | None):
    key = _SNAPSHOT_MARKETS.get((market, selection))
    if key is None:
        return None
    ln = _float(line)
    if key[0] in ("OU", "AH") and ln is None:
        return None
    return key[0], key[1], ln


def _coverage(results: list[dict[str, str]]) -> dict[str, float]:
    n = len(results)
    if n == 0:
        return {}
    fields = {"half_time": "ht_home", "shots": "home_shots", "shots_on_target": "home_target",
              "fouls": "home_fouls", "corners": "home_corners", "corners_split": "home_corners_1h",
              "cards": "home_yellow", "kickoff_time": "time", "goal_minutes": "goal_minutes"}
    return {k: round(sum(1 for r in results if r.get(col)) / n, 3) for k, col in fields.items()}


def dataset_age_days(generated_utc: str | None) -> float | None:
    dt = parse_iso(generated_utc) if generated_utc else None
    if dt is None:
        return None
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 86400, 2)
