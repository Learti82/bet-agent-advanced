"""Weekly betting plan: one ticket set per slot, each built for every target (default 50 and 110).

Slots (Europe/Belgrade dates, Monday-based week):
  * Champions League        — Tuesday + Wednesday
  * Europa + Conference     — Thursday
  * Weekend leagues         — Saturday + Sunday (domestic leagues; editable list)

Every ticket goes through the normal builder: only well-supported legs, stop at the target, never
pad. A slot with no fixtures (e.g. a week without European matches) or with no priced, qualifying
selections says so instead of producing a ticket.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ..timeutil import tz
from .report import build_report

NON_EUROPEAN = {"ARG", "AUS", "BRA", "CHN", "JPN", "MEX", "USA"}

SLOTS = [
    {"id": "ucl", "name": "Champions League", "days_label": "Tuesday & Wednesday", "weekdays": [1, 2],
     "competitions": ["UEFA_1_champions-league"]},
    {"id": "uel_uecl", "name": "Europa League + Conference League", "days_label": "Thursday", "weekdays": [3],
     "competitions": ["UEFA_1_europa-league", "UEFA_1_conference-league"]},
    {"id": "weekend", "name": "Weekend leagues", "days_label": "Saturday & Sunday", "weekdays": [5, 6],
     "competitions": None},  # resolved from settings
]


def parse_targets(value: str | list | None) -> list[float]:
    if isinstance(value, list):
        raw = value
    else:
        raw = [x for x in str(value or "").replace(";", ",").split(",") if x.strip()]
    out = []
    for x in raw:
        t = float(x)
        if t <= 1.0:
            raise ValueError("Target odds must be greater than 1.00")
        out.append(t)
    return sorted(set(out)) or [50.0, 110.0]


def week_monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def today_local(zone: str) -> date:
    return datetime.now(timezone.utc).astimezone(tz(zone)).date()


def default_weekend_competitions(competitions: dict[str, dict]) -> list[str]:
    """European top divisions by default."""
    return sorted(code for code, c in competitions.items()
                  if c.get("kind") == "league" and str(c.get("tier")) == "1"
                  and code.split("_")[0] not in NON_EUROPEAN)


def weekend_competitions(settings: dict, competitions: dict[str, dict]) -> list[str]:
    chosen = [c.strip() for c in str(settings.get("plan_weekend_competitions") or "").split(",") if c.strip()]
    chosen = [c for c in chosen if c in competitions]
    return chosen or default_weekend_competitions(competitions)


def build_week_plan(engine, week_start: date | None = None, targets: list[float] | None = None) -> dict:
    settings = engine.db.get_settings()
    zone = str(settings["timezone"])
    today = today_local(zone)
    monday = week_monday(week_start or today)
    targets = targets or parse_targets(settings.get("plan_targets"))
    comps = engine.store.competitions
    slots_out = []
    for slot in SLOTS:
        days = [monday + timedelta(days=d) for d in slot["weekdays"]]
        codes = slot["competitions"] or weekend_competitions(settings, comps)
        codes = [c for c in codes if c in comps]
        d_from, d_to = days[0].isoformat(), days[-1].isoformat()
        fixtures = engine.list_fixtures(d_from, d_to, codes, include_ineligible=True)
        fixtures = [f for f in fixtures if date.fromisoformat(f["local_date"]).weekday() in slot["weekdays"]]
        eligible = [f for f in fixtures if f["prematch_eligible"]]
        out = {
            "id": slot["id"], "name": slot["name"], "days_label": slot["days_label"],
            "dates": [d.isoformat() for d in days], "competitions": codes,
            "competition_names": [comps[c]["name"] for c in codes],
            "fixtures": len(fixtures), "eligible_fixtures": len(eligible),
            "priced_fixtures": sum(1 for f in eligible if f["manual_odds"] or f["snapshot_odds"]),
            "manual_priced_fixtures": sum(1 for f in eligible if f["manual_odds"]),
            "tickets": [], "status": "ok", "message": None,
        }
        if days[-1] < today:
            out.update(status="passed", message="These days have already been played.")
        elif not fixtures:
            out.update(status="no_fixtures",
                       message=f"No {slot['name']} fixtures on {slot['days_label']} this week in the dataset.")
        elif not eligible:
            out.update(status="no_eligible", message="All fixtures in this slot have started, finished or were postponed.")
        if out["status"] == "ok":
            for t in targets:
                rep = build_report(engine, date_from=d_from, date_to=d_to, target=t, competitions=codes,
                                   max_legs=int(settings["plan_max_legs"]))
                out["tickets"].append({"target": t, "report": rep})
            if len(out["tickets"]) >= 2:
                keys = [{(leg["match_id"], leg["key"]) for leg in tk["report"]["legs"]} for tk in out["tickets"]]
                shared = set.intersection(*keys) if keys else set()
                out["shared_legs"] = len(shared)
        slots_out.append(out)
    return {
        "week_start": monday.isoformat(), "week_end": (monday + timedelta(days=6)).isoformat(),
        "today": today.isoformat(), "timezone": zone, "targets": targets, "slots": slots_out,
        "note": "Each slot is built independently from its own fixtures. The two targets use the same pool of "
                "well-supported selections, so the bigger ticket usually contains the smaller one's legs — "
                "if a shared leg loses, both tickets lose.",
    }
