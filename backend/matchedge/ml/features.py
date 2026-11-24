"""Walk-forward feature builder for the machine-learning models.

Matches are processed in date order. Before each match, its features are read from the current
state (built only from earlier matches); after it, the state is updated with the result. The same
code produces training rows (historical matches) and live rows (upcoming fixtures, read without
updating), so training and prediction see identical feature definitions and there is no look-ahead.

State per team (team ids are country-prefixed, so each country is one Elo pool across divisions):
  * Elo rating (home advantage 65, goal-difference multiplier, 20 % regression at a new season,
    new/promoted teams start below their new league's average);
  * exponentially weighted averages (EWMA) of goals, shots, shots on target, corners and points,
    overall and venue-specific; missing statistics are skipped, never treated as zero;
  * season counters, days since the previous match.
State per competition: EWMA of home and away goals per match (the league's scoring level).

Market features (Bet365 pre-match 1X2 and Over/Under 2.5 with the margin removed, and the Asian
handicap line) form a separate group, so a "stats-only" model can be trained and compared with a
"market-aware" one.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

ALPHA = 0.08  # overall EWMA ≈ 8-match half-life
ALPHA_VENUE = 0.12
ALPHA_FORM = 0.25
HFA = 65.0
STATS = {  # name: (home column, away column)
    "g": ("ft_home", "ft_away"), "s": ("home_shots", "away_shots"), "st": ("home_target", "away_target"),
    "c": ("home_corners", "away_corners"), "y": ("home_yellow", "away_yellow"),
}

STAT_FEATURES = [
    "elo_h", "elo_a", "elo_diff", "elo_exp_h", "tier", "lg_hg", "lg_ag",
    "n_h", "n_a", "season_n_h", "season_n_a", "rest_h", "rest_a", "ppg_h", "ppg_a", "form_h", "form_a",
    "gf_h", "ga_h", "gf_a", "ga_a", "vgf_h", "vga_h", "vgf_a", "vga_a",
    "sf_h", "sa_h", "sf_a", "sa_a", "stf_h", "sta_h", "stf_a", "sta_a", "cf_h", "ca_h", "cf_a", "ca_a",
    "y_h", "y_a", "att_h", "def_h", "att_a", "def_a", "exp_h", "exp_a", "exp_total", "exp_diff",
    "sot_share_h", "sot_share_a",
]
MARKET_FEATURES = ["mkt_ph", "mkt_pd", "mkt_pa", "mkt_po25", "ah_line"]
NAN = float("nan")


def _ewm(old: float | None, x: float | None, a: float) -> float | None:
    if x is None:
        return old
    return x if old is None else old + a * (x - old)


@dataclass
class TeamState:
    elo: float
    n: int = 0
    last: date | None = None
    season: str | None = None
    season_n: int = 0
    season_pts: int = 0
    ew: dict = field(default_factory=dict)  # overall EWMAs: gf, ga, sf, sa, stf, sta, cf, ca, y
    ew_home: dict = field(default_factory=dict)
    ew_away: dict = field(default_factory=dict)
    form: float | None = None


@dataclass
class LeagueState:
    hg: float = 1.45
    ag: float = 1.15
    n: int = 0
    elo_mean: float | None = None


def fair_probs(*odds: float | None) -> list[float] | None:
    if any(o is None or not o or o <= 1 for o in odds):
        return None
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv]


def market_features(row: dict) -> dict:
    p = fair_probs(row.get("b365_h"), row.get("b365_d"), row.get("b365_a"))
    o = fair_probs(row.get("b365_o25"), row.get("b365_u25"))
    return {"mkt_ph": p[0] if p else NAN, "mkt_pd": p[1] if p else NAN, "mkt_pa": p[2] if p else NAN,
            "mkt_po25": o[0] if o else NAN,
            "ah_line": row["ah_line"] if row.get("ah_line") is not None else NAN}


class FeatureBuilder:
    def __init__(self):
        self.teams: dict[str, TeamState] = {}
        self.leagues: dict[str, LeagueState] = {}

    # ------------------------------------------------------------------ state access
    def _league(self, comp: str) -> LeagueState:
        return self.leagues.setdefault(comp, LeagueState())

    def _team(self, tid: str, comp: str, season: str, day: date) -> TeamState:
        lg = self._league(comp)
        t = self.teams.get(tid)
        if t is None:
            base = (lg.elo_mean - 50) if lg.elo_mean is not None else 1500.0
            t = self.teams[tid] = TeamState(elo=base)
        if t.season != season:
            if t.season is not None and lg.elo_mean is not None:
                t.elo = 0.8 * t.elo + 0.2 * lg.elo_mean
            t.season, t.season_n, t.season_pts = season, 0, 0
        return t

    def features(self, row: dict) -> dict:
        """Features for a match from the current state (does not modify the state)."""
        comp, season = row["competition"], row["season"]
        day = date.fromisoformat(row["date"]) if isinstance(row["date"], str) else row["date"]
        lg = self.leagues.get(comp) or LeagueState()
        h = self.teams.get(row["home_key"])
        a = self.teams.get(row["away_key"])
        lg_team = (lg.hg + lg.ag) / 2

        def team_f(t: TeamState | None, venue: str) -> dict:
            if t is None:
                return {"elo": (lg.elo_mean - 50) if lg.elo_mean is not None else 1500.0, "n": 0, "season_n": 0,
                        "rest": NAN, "ppg": NAN, "form": NAN, **{k: NAN for k in ("gf", "ga", "sf", "sa", "stf", "sta",
                                                                                     "cf", "ca", "y", "vgf", "vga")}}
            same = t.season == season
            ev = t.ew_home if venue == "H" else t.ew_away
            return {"elo": t.elo, "n": min(t.n, 80), "season_n": t.season_n if same else 0,
                    "rest": min(30, (day - t.last).days) if t.last else NAN,
                    "ppg": (t.season_pts / t.season_n) if same and t.season_n else NAN,
                    "form": t.form if t.form is not None else NAN,
                    **{k: (t.ew.get(k) if t.ew.get(k) is not None else NAN)
                       for k in ("gf", "ga", "sf", "sa", "stf", "sta", "cf", "ca", "y")},
                    "vgf": ev.get("gf") if ev.get("gf") is not None else NAN,
                    "vga": ev.get("ga") if ev.get("ga") is not None else NAN}

        fh, fa = team_f(h, "H"), team_f(a, "A")
        elo_diff = fh["elo"] + HFA - fa["elo"]

        def rel(x):
            return x / lg_team if (x == x and lg_team > 0) else NAN

        att_h, def_h, att_a, def_a = rel(fh["gf"]), rel(fh["ga"]), rel(fa["gf"]), rel(fa["ga"])
        exp_h = lg.hg * att_h * def_a if att_h == att_h and def_a == def_a else NAN
        exp_a = lg.ag * att_a * def_h if att_a == att_a and def_h == def_h else NAN

        def share(f, a_):
            return f / (f + a_) if f == f and a_ == a_ and (f + a_) > 0 else NAN

        tier = row["competition"].split("_")[1] if "_" in row["competition"] else ""
        out = {
            "elo_h": fh["elo"], "elo_a": fa["elo"], "elo_diff": elo_diff,
            "elo_exp_h": 1 / (1 + 10 ** (-elo_diff / 400)), "tier": float(tier) if tier.isdigit() else NAN,
            "lg_hg": lg.hg, "lg_ag": lg.ag,
            "n_h": fh["n"], "n_a": fa["n"], "season_n_h": fh["season_n"], "season_n_a": fa["season_n"],
            "rest_h": fh["rest"], "rest_a": fa["rest"], "ppg_h": fh["ppg"], "ppg_a": fa["ppg"],
            "form_h": fh["form"], "form_a": fa["form"],
            "gf_h": fh["gf"], "ga_h": fh["ga"], "gf_a": fa["gf"], "ga_a": fa["ga"],
            "vgf_h": fh["vgf"], "vga_h": fh["vga"], "vgf_a": fa["vgf"], "vga_a": fa["vga"],
            "sf_h": fh["sf"], "sa_h": fh["sa"], "sf_a": fa["sf"], "sa_a": fa["sa"],
            "stf_h": fh["stf"], "sta_h": fh["sta"], "stf_a": fa["stf"], "sta_a": fa["sta"],
            "cf_h": fh["cf"], "ca_h": fh["ca"], "cf_a": fa["cf"], "ca_a": fa["ca"], "y_h": fh["y"], "y_a": fa["y"],
            "att_h": att_h, "def_h": def_h, "att_a": att_a, "def_a": def_a, "exp_h": exp_h, "exp_a": exp_a,
            "exp_total": exp_h + exp_a if exp_h == exp_h and exp_a == exp_a else NAN,
            "exp_diff": exp_h - exp_a if exp_h == exp_h and exp_a == exp_a else NAN,
            "sot_share_h": share(fh["stf"], fh["sta"]), "sot_share_a": share(fa["stf"], fa["sta"]),
        }
        out.update(market_features(row))
        return out

    # ------------------------------------------------------------------ update
    def update(self, row: dict) -> None:
        comp, season = row["competition"], row["season"]
        day = date.fromisoformat(row["date"]) if isinstance(row["date"], str) else row["date"]
        hg, ag = row["ft_home"], row["ft_away"]
        lg = self._league(comp)
        h = self._team(row["home_key"], comp, season, day)
        a = self._team(row["away_key"], comp, season, day)
        # Elo
        diff = h.elo + HFA - a.elo
        exp_h = 1 / (1 + 10 ** (-diff / 400))
        res = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        gd = abs(hg - ag)
        k = 20.0 * (1.0 if gd <= 1 else 1.5 if gd == 2 else (11 + gd) / 8)
        h.elo += k * (res - exp_h)
        a.elo -= k * (res - exp_h)
        # EWMAs
        for t, venue, sign in ((h, "H", 0), (a, "A", 1)):
            vals = {}
            for name, (hc, ac) in STATS.items():
                f, ag_ = (row.get(hc), row.get(ac)) if sign == 0 else (row.get(ac), row.get(hc))
                if name == "y":
                    vals["y"] = f
                    continue
                key_f, key_a = {"g": ("gf", "ga"), "s": ("sf", "sa"), "st": ("stf", "sta"), "c": ("cf", "ca")}[name]
                vals[key_f], vals[key_a] = f, ag_
            for k_, v in vals.items():
                t.ew[k_] = _ewm(t.ew.get(k_), v, ALPHA)
            ev = t.ew_home if venue == "H" else t.ew_away
            ev["gf"] = _ewm(ev.get("gf"), vals["gf"], ALPHA_VENUE)
            ev["ga"] = _ewm(ev.get("ga"), vals["ga"], ALPHA_VENUE)
            pts = 3 if vals["gf"] > vals["ga"] else 1 if vals["gf"] == vals["ga"] else 0
            t.form = _ewm(t.form, pts, ALPHA_FORM)
            t.season_n += 1
            t.season_pts += pts
            t.n += 1
            t.last = day
        lg.hg += 0.02 * (hg - lg.hg)  # league scoring level (≈35-match half-life)
        lg.ag += 0.02 * (ag - lg.ag)
        lg.n += 1
        lg.elo_mean = (h.elo + a.elo) / 2 if lg.elo_mean is None else lg.elo_mean + 0.05 * ((h.elo + a.elo) / 2 - lg.elo_mean)


def targets(row: dict) -> dict:
    hg, ag = row["ft_home"], row["ft_away"]
    return {"y_1x2": 0 if hg > ag else 1 if hg == ag else 2, "y_o25": int(hg + ag > 2.5), "y_btts": int(hg > 0 and ag > 0),
            "y_hg": hg, "y_ag": ag}


def build_rows(matches: list[dict], keep=lambda r: True, min_history: int = 3) -> list[dict]:
    """Walk through ``matches`` (finished, any order) and return one row per match with features + targets.

    Rows where either team has fewer than ``min_history`` earlier matches are skipped (cold start).
    """
    fb = FeatureBuilder()
    out = []
    for r in sorted(matches, key=lambda x: (x["date"], x["id"])):
        if r.get("ft_home") is None or r.get("ft_away") is None:
            continue
        if keep(r):
            f = fb.features(r)
            if f["n_h"] >= min_history and f["n_a"] >= min_history:
                out.append({"id": r["id"], "season": r["season"], "competition": r["competition"], "date": r["date"],
                            "features": f, **targets(r), "odds": {k: r.get(k) for k in (
                                "b365_h", "b365_d", "b365_a", "b365_o25", "b365_u25", "b365c_h", "b365c_d", "b365c_a",
                                "b365c_o25", "b365c_u25")}})
        fb.update(r)
    return out


def matrix(rows: list[dict], names: list[str]):
    import numpy as np
    return np.array([[r["features"].get(n, NAN) for n in names] for r in rows], dtype=float)


def is_nan(x) -> bool:
    return isinstance(x, float) and math.isnan(x)
