"""In-memory match store built from SQLite.

Finished matches are expanded into *team-perspective rows* (one per team per match) so every
statistic can be computed as "for"/"against" from the team's point of view. Missing values stay
``None`` throughout; nothing is filled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from ..timeutil import parse_iso

STAT_PAIRS = {
    # perspective name: (home column, away column)
    "goals": ("ft_home", "ft_away"),
    "ht_goals": ("ht_home", "ht_away"),
    "shots": ("home_shots", "away_shots"),
    "sot": ("home_target", "away_target"),
    "fouls": ("home_fouls", "away_fouls"),
    "corners": ("home_corners", "away_corners"),
    "corners_1h": ("home_corners_1h", "away_corners_1h"),
    "corners_2h": ("home_corners_2h", "away_corners_2h"),
    "yellow": ("home_yellow", "away_yellow"),
    "red": ("home_red", "away_red"),
}


@dataclass
class TeamRow:
    match_id: str
    competition: str
    date: date
    venue: str  # 'H' or 'A'
    team_id: str
    opponent_id: str
    opponent: str
    f: dict[str, int | None]  # stats "for"
    a: dict[str, int | None]  # stats "against"

    @property
    def gf(self) -> int:
        return self.f["goals"]  # type: ignore[return-value]

    @property
    def ga(self) -> int:
        return self.a["goals"]  # type: ignore[return-value]

    @property
    def result(self) -> str:
        return "W" if self.gf > self.ga else "D" if self.gf == self.ga else "L"

    @property
    def points(self) -> int:
        return {"W": 3, "D": 1, "L": 0}[self.result]

    def total(self, stat: str) -> int | None:
        x, y = self.f.get(stat), self.a.get(stat)
        return None if x is None or y is None else x + y

    def cards_for(self) -> int | None:
        y, r = self.f.get("yellow"), self.f.get("red")
        return None if y is None or r is None else y + r

    def cards_against(self) -> int | None:
        y, r = self.a.get("yellow"), self.a.get("red")
        return None if y is None or r is None else y + r

    def cards_total(self) -> int | None:
        x, y = self.cards_for(), self.cards_against()
        return None if x is None or y is None else x + y


@dataclass
class MatchStore:
    matches: dict[str, dict[str, Any]]
    competitions: dict[str, dict[str, Any]]
    by_team: dict[str, list[TeamRow]] = field(default_factory=dict)  # newest first
    by_comp: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # finished, any order
    memo: dict = field(default_factory=dict)  # cached league baselines/profiles (immutable per import)

    @classmethod
    def build(cls, match_rows: list[dict[str, Any]], competitions: list[dict[str, Any]]) -> "MatchStore":
        store = cls(matches={}, competitions={c["code"]: c for c in competitions})
        for m in match_rows:
            m = dict(m)
            m["date_obj"] = date.fromisoformat(m["date"])
            m["kickoff_dt"] = parse_iso(m.get("kickoff_utc"))
            store.matches[m["id"]] = m
            if m["status"] != "finished" or m.get("ft_home") is None or m.get("ft_away") is None:
                continue
            store.by_comp.setdefault(m["competition"], []).append(m)
            for venue, tid, oid, opp in (("H", m["home_key"], m["away_key"], m["away"]),
                                         ("A", m["away_key"], m["home_key"], m["home"])):
                f, a = {}, {}
                for stat, (hc, ac) in STAT_PAIRS.items():
                    hv, av = m.get(hc), m.get(ac)
                    f[stat], a[stat] = (hv, av) if venue == "H" else (av, hv)
                store.by_team.setdefault(tid, []).append(
                    TeamRow(m["id"], m["competition"], m["date_obj"], venue, tid, oid, opp, f, a))
        for rows in store.by_team.values():
            rows.sort(key=lambda r: r.date, reverse=True)
        return store

    def history(self, team_id: str, before: date, competitions: set[str] | None = None) -> list[TeamRow]:
        """Finished matches for a team strictly before ``before`` (no look-ahead), newest first."""
        rows = [r for r in self.by_team.get(team_id, []) if r.date < before]
        if competitions is not None:
            rows = [r for r in rows if r.competition in competitions]
        return rows

    def comp_results(self, code: str, before: date | None = None) -> list[dict[str, Any]]:
        rows = self.by_comp.get(code, [])
        return [m for m in rows if before is None or m["date_obj"] < before]

    def primary_league(self, team_id: str) -> str | None:
        """Domestic league where the team has played most of its matches."""
        counts: dict[str, int] = {}
        for r in self.by_team.get(team_id, []):
            parts = r.competition.split("_")
            if len(parts) > 1 and parts[1].isdigit() and parts[0] != "UEFA":
                counts[r.competition] = counts.get(r.competition, 0) + 1
        return max(counts, key=counts.get) if counts else None

    def last_played(self, team_id: str) -> date | None:
        rows = self.by_team.get(team_id)
        return rows[0].date if rows else None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
