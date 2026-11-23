"""Team-name normalisation and cross-competition linking.

Open-Matchday keeps each provider's spelling, so one club can appear as "Stade Rennais FC",
"Stade Rennais" and "Rennes". Two layers handle this:

1. ``team_key`` — a deterministic canonical key (transliterate, lower-case, strip punctuation,
   drop club-type tokens such as FC/SC/VfB and bare numbers). Verified against the 2026/27 data:
   it unifies every results-vs-fixtures spelling inside each league.
2. Cross-competition links (UEFA competitions use short names like "B. Dortmund", "Inter").
   A UEFA name links to a domestic team when (a) a user alias exists, (b) a seeded alias exists,
   or (c) exactly one domestic team in the whole dataset has the same key. Ambiguous names
   (e.g. "Paris" vs "Paris FC"/"Paris Saint-Germain") are *never* guessed — they stay unlinked
   until an alias resolves them.

Team identity is ``"<COUNTRY>:<key>"`` (e.g. ``"GER:borussia dortmund"``) so that clubs with the
same name in different countries are never merged.
"""
from __future__ import annotations

import re
import unicodedata

_TRANSLIT = str.maketrans({
    "æ": "ae", "Æ": "ae", "ø": "o", "Ø": "o", "ß": "ss", "ł": "l", "Ł": "l",
    "đ": "d", "Đ": "d", "ı": "i", "œ": "oe", "Œ": "oe", "þ": "th", "ð": "d",
})

# Club-type tokens that do not identify a club on their own.
_DROP = {
    "fc", "cf", "afc", "sc", "ac", "as", "ssc", "ud", "cd", "rc", "rcd", "sl", "ogc", "losc",
    "bv", "vfb", "vfl", "tsg", "fk", "sk", "nk", "if", "bk", "rb", "sv", "fsv", "cp",
}

# Seeded aliases: UEFA-style short name key -> domestic team identity.
# Each was checked against the 2026/27 Open-Matchday files. Seeds whose target does not exist
# in the imported data are ignored (and reported) rather than applied blindly.
SEED_ALIASES: dict[str, str] = {
    "b dortmund": "GER:borussia dortmund",
    "inter": "ITA:internazionale",
    "paris": "FRA:paris saint germain",
    "atleti": "ESP:atletico de madrid",
    "leverkusen": "GER:bayer leverkusen",
    "lyon": "FRA:olympique lyonnais",
    "marseille": "FRA:olympique de marseille",
    "n e c": "NED:n e c nijmegen",
    "rennes": "FRA:stade rennais",
    "az alkmaar": "NED:az",
    "gent": "BEL:kaa gent",
    "s bratislava": "SVK:slovan bratislava",
    "shakhtar": "UKR:shakhtar donetsk",
    "slavia praha": "CZE:slavia prague",
    "sparta praha": "CZE:sparta prague",
    "viktoria plzen": "CZE:plzen",
    "u craiova": "ROU:univ craiova",
    "union sg": "BEL:union st gilloise",
    "hearts": "SCO:heart of midlothian",
    "gnk dinamo": "CRO:din zagreb",
    "kups kuopio": "FIN:kups",
}


def team_key(name: str) -> str:
    s = unicodedata.normalize("NFKD", (name or "").translate(_TRANSLIT))
    s = s.encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    tokens = s.split()
    kept = [t for t in tokens if t not in _DROP and not t.isdigit()]
    return " ".join(kept) if kept else " ".join(tokens)


def country_of(competition_code: str) -> str:
    return competition_code.split("_", 1)[0]


def is_international(competition_code: str) -> bool:
    return country_of(competition_code) == "UEFA"


def is_domestic_league(competition_code: str) -> bool:
    parts = competition_code.split("_")
    return len(parts) >= 2 and parts[1].isdigit() and parts[0] != "UEFA"


class TeamResolver:
    """Resolves (competition, raw name) -> team identity, with an audit trail."""

    def __init__(self, domestic_ids: dict[str, set[str]], aliases: dict[str, str]):
        # domestic_ids: key -> set of team ids found in domestic league files
        self.domestic_ids = domestic_ids
        self.all_ids = {tid for ids in domestic_ids.values() for tid in ids}
        self.aliases = aliases  # alias key -> team id (user aliases override seeds)
        self.links: dict[str, dict] = {}

    def resolve(self, competition: str, name: str) -> str:
        key = team_key(name)
        country = country_of(competition)
        if not is_international(competition):
            return f"{country}:{key}"
        if key in self.aliases and self.aliases[key] in self.all_ids:
            tid, how = self.aliases[key], "alias"
        else:
            candidates = self.domestic_ids.get(key, set())
            if len(candidates) == 1:
                tid, how = next(iter(candidates)), "exact-key"
            else:
                tid = f"UEFA:{key}"
                how = "ambiguous" if len(candidates) > 1 else "unlinked"
                self.links[name] = {"name": name, "key": key, "team_id": tid, "method": how,
                                    "candidates": sorted(candidates)}
                return tid
        self.links[name] = {"name": name, "key": key, "team_id": tid, "method": how, "candidates": [tid]}
        return tid


def display_from_id(team_id: str) -> str:
    return team_id.split(":", 1)[-1].title()
