"""Kickoff-time handling.

Open-Matchday convention (DATA_DICTIONARY.md): ``date`` + ``time`` use a *fixed* UTC+1 offset
("CET-1", football-data.co.uk style). The dataset itself warns summer fixtures may be an hour
off. We therefore:

* convert ``date``+``time`` as UTC+1 -> UTC -> the display timezone (Europe/Belgrade);
* mark the time as *uncertain* whenever Belgrade is on summer time (UTC+2) on that date, or the
  time is blank;
* prefer an explicit ``kickoff_utc`` timestamp from the odds snapshot file when present, and
  record whether the two sources agree.

Nothing here ever upgrades a dataset time to "verified" — only a user verification does that.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

DATASET_OFFSET = timezone(timedelta(hours=1))
DEFAULT_TZ = "Europe/Belgrade"


def tz(name: str | None = None) -> ZoneInfo:
    return ZoneInfo(name or DEFAULT_TZ)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dataset_kickoff_utc(date_str: str, time_str: str | None) -> datetime | None:
    """Convert a dataset ``date``/``time`` pair (fixed UTC+1) to an aware UTC datetime.

    Returns ``None`` when the time is unknown — a date alone is not a kickoff time.
    """
    if not date_str or not time_str or not str(time_str).strip():
        return None
    d = date.fromisoformat(date_str.strip())
    hh, mm = str(time_str).strip().split(":")[:2]
    local = datetime.combine(d, time(int(hh), int(mm)), tzinfo=DATASET_OFFSET)
    return local.astimezone(timezone.utc)


def is_summer_time(d: date, zone: str = DEFAULT_TZ) -> bool:
    noon = datetime.combine(d, time(12, 0), tzinfo=tz(zone))
    return bool(noon.dst() and noon.dst() != timedelta(0))


def to_local(dt_utc: datetime | None, zone: str = DEFAULT_TZ) -> datetime | None:
    if dt_utc is None:
        return None
    return dt_utc.astimezone(tz(zone))


def local_str(dt_utc: datetime | str | None, zone: str = DEFAULT_TZ) -> str | None:
    if isinstance(dt_utc, str):
        dt_utc = parse_iso(dt_utc)
    loc = to_local(dt_utc, zone)
    return loc.strftime("%Y-%m-%d %H:%M") if loc else None


def local_input_to_utc(value: str, zone: str = DEFAULT_TZ) -> datetime:
    """Parse a user-entered local time 'YYYY-MM-DD HH:MM' (or ISO with 'T') in ``zone``."""
    v = value.strip().replace("T", " ")
    if v.endswith("Z") or "+" in v[10:]:
        return parse_iso(v.replace(" ", "T"))  # type: ignore[return-value]
    dt = datetime.strptime(v[:16], "%Y-%m-%d %H:%M").replace(tzinfo=tz(zone))
    return dt.astimezone(timezone.utc)


def local_date_bounds(day: str, zone: str = DEFAULT_TZ) -> tuple[datetime, datetime]:
    """UTC bounds [start, end) of a calendar day in ``zone``."""
    d = date.fromisoformat(day)
    start = datetime.combine(d, time(0, 0), tzinfo=tz(zone))
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def time_certainty(date_str: str, time_str: str | None, snapshot_utc: datetime | None,
                   dataset_utc: datetime | None, zone: str = DEFAULT_TZ) -> tuple[str, list[str]]:
    """Classify how much a kickoff time can be trusted. Returns (label, notes)."""
    notes: list[str] = []
    if dataset_utc is None and snapshot_utc is None:
        return "unknown", ["Kickoff time not supplied by the dataset."]
    if snapshot_utc is not None and dataset_utc is not None:
        if abs((snapshot_utc - dataset_utc).total_seconds()) < 60:
            notes.append("Kickoff agrees across fixture file and odds snapshot.")
            return "corroborated", notes
        diff = (snapshot_utc - dataset_utc).total_seconds() / 3600
        notes.append(f"Fixture file and odds snapshot disagree by {diff:+.1f} h; using the explicit UTC "
                     "timestamp from the snapshot. Verify on the official competition website.")
        return "conflict", notes
    if snapshot_utc is not None:
        notes.append("Kickoff from odds snapshot (explicit UTC); not cross-checked.")
        return "single_source", notes
    try:
        summer = is_summer_time(date.fromisoformat(date_str), zone)
    except ValueError:
        summer = False
    if summer:
        notes.append("Dataset uses a fixed UTC+1 convention; on summer-time dates the time may be 1 hour off.")
        return "uncertain", notes
    notes.append("Dataset time (fixed UTC+1 convention); not independently verified.")
    return "single_source", notes
