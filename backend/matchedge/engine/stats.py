"""Descriptive, missing-aware team statistics.

Rules enforced here:
* averages use only matches where the statistic exists (``None`` is skipped, never 0);
* every statistic reports ``n`` (matches used), ``of`` (matches considered) and completeness;
* a statistic with fewer than ``min_n`` usable matches carries a ``warning``.
"""
from __future__ import annotations

import math
from typing import Callable, Iterable

from .data import TeamRow


def stat(values: Iterable[float | int | None], of: int | None = None, min_n: int = 5,
         label: str = "", digits: int = 2) -> dict:
    vals = list(values)
    total = of if of is not None else len(vals)
    usable = [float(v) for v in vals if v is not None]
    n = len(usable)
    out: dict = {"n": n, "of": total, "completeness": round(n / total, 3) if total else 0.0,
                 "mean": None, "sd": None, "warning": None}
    if n:
        mean = sum(usable) / n
        out["mean"] = round(mean, digits)
        out["sd"] = round(math.sqrt(sum((x - mean) ** 2 for x in usable) / (n - 1)), digits) if n > 1 else None
    if total == 0:
        out["warning"] = f"No matches available{(' for ' + label) if label else ''}."
    elif n == 0:
        out["warning"] = f"{label or 'Statistic'} not provided by the dataset for these matches."
    elif n < min_n:
        out["warning"] = f"Insufficient sample: only {n} match{'es' if n != 1 else ''} with {label or 'this statistic'}."
    return out


def rate(rows: list[TeamRow], pred: Callable[[TeamRow], bool | None], min_n: int = 5, label: str = "") -> dict:
    """Frequency of a condition; rows where the condition cannot be evaluated are skipped."""
    outcomes = [pred(r) for r in rows]
    usable = [o for o in outcomes if o is not None]
    n, k = len(usable), sum(1 for o in usable if o)
    out = {"k": k, "n": n, "of": len(rows), "rate": round(k / n, 3) if n else None,
           "completeness": round(n / len(rows), 3) if rows else 0.0, "warning": None}
    if n == 0:
        out["warning"] = f"No usable data for {label or 'this condition'}."
    elif n < min_n:
        out["warning"] = f"Insufficient sample ({n}) for {label or 'this condition'}."
    return out


def form_block(rows: list[TeamRow], window: int, min_n: int) -> dict:
    sub = rows[:window]
    n = len(sub)
    w = sum(1 for r in sub if r.result == "W")
    d = sum(1 for r in sub if r.result == "D")
    l_ = n - w - d
    gf = sum(r.gf for r in sub)
    ga = sum(r.ga for r in sub)
    return {
        "window": window, "n": n, "sequence": "".join(r.result for r in sub),
        "w": w, "d": d, "l": l_, "gf": gf, "ga": ga,
        "win_pct": round(w / n, 3) if n else None,
        "ppg": round((3 * w + d) / n, 2) if n else None,
        "gf_avg": round(gf / n, 2) if n else None,
        "ga_avg": round(ga / n, 2) if n else None,
        "warning": None if n >= min(window, min_n) else f"Only {n} matches available (wanted {window}).",
    }


def team_profile(rows: list[TeamRow], venue: str | None, min_n: int = 5) -> dict:
    """Full statistical profile from a list of perspective rows (newest first)."""
    venue_rows = [r for r in rows if venue is None or r.venue == venue]
    last10 = rows[:10]

    def goals_block(rs: list[TeamRow]) -> dict:
        def tg(r: TeamRow) -> int:
            return r.gf + r.ga

        def ht_total(r: TeamRow) -> int | None:
            return r.total("ht_goals")

        def sh_goals(r: TeamRow) -> int | None:
            h = r.total("ht_goals")
            return None if h is None else r.gf + r.ga - h

        return {
            "gf": stat((r.gf for r in rs), min_n=min_n, label="goals"),
            "ga": stat((r.ga for r in rs), min_n=min_n, label="goals"),
            "total": stat((tg(r) for r in rs), min_n=min_n, label="goals"),
            "over15": rate(rs, lambda r: tg(r) > 1.5, min_n, "Over 1.5"),
            "over25": rate(rs, lambda r: tg(r) > 2.5, min_n, "Over 2.5"),
            "over35": rate(rs, lambda r: tg(r) > 3.5, min_n, "Over 3.5"),
            "under25": rate(rs, lambda r: tg(r) < 2.5, min_n, "Under 2.5"),
            "btts": rate(rs, lambda r: r.gf > 0 and r.ga > 0, min_n, "BTTS"),
            "clean_sheet": rate(rs, lambda r: r.ga == 0, min_n, "clean sheets"),
            "failed_to_score": rate(rs, lambda r: r.gf == 0, min_n, "failed to score"),
            "scored_2plus": rate(rs, lambda r: r.gf >= 2, min_n, "2+ goals scored"),
            "ht_goal": rate(rs, lambda r: None if ht_total(r) is None else ht_total(r) > 0, min_n,
                            "first-half goals (half-time scores)"),
            "ht_over15": rate(rs, lambda r: None if ht_total(r) is None else ht_total(r) > 1.5, min_n,
                              "first-half Over 1.5"),
            "first_half_goals": stat((ht_total(r) for r in rs), min_n=min_n, label="half-time scores"),
            "second_half_goals": stat((sh_goals(r) for r in rs), min_n=min_n, label="half-time scores"),
        }

    def misc_block(rs: list[TeamRow]) -> dict:
        return {
            "corners_for": stat((r.f["corners"] for r in rs), min_n=min_n, label="corners"),
            "corners_against": stat((r.a["corners"] for r in rs), min_n=min_n, label="corners"),
            "corners_total": stat((r.total("corners") for r in rs), min_n=min_n, label="corners"),
            "corners_1h_total": stat((r.total("corners_1h") for r in rs), min_n=min_n, label="first-half corners"),
            "yellow_for": stat((r.f["yellow"] for r in rs), min_n=min_n, label="cards"),
            "yellow_against": stat((r.a["yellow"] for r in rs), min_n=min_n, label="cards"),
            "red_for": stat((r.f["red"] for r in rs), min_n=min_n, label="cards"),
            "cards_total": stat((r.cards_total() for r in rs), min_n=min_n, label="cards"),
            "fouls_for": stat((r.f["fouls"] for r in rs), min_n=min_n, label="fouls"),
            "fouls_against": stat((r.a["fouls"] for r in rs), min_n=min_n, label="fouls"),
            "shots_for": stat((r.f["shots"] for r in rs), min_n=min_n, label="shots"),
            "shots_against": stat((r.a["shots"] for r in rs), min_n=min_n, label="shots"),
            "sot_for": stat((r.f["sot"] for r in rs), min_n=min_n, label="shots on target"),
            "sot_against": stat((r.a["sot"] for r in rs), min_n=min_n, label="shots on target"),
        }

    last5_corners = [r for r in rows if r.f["corners"] is not None][:5]
    return {
        "matches": len(rows),
        "venue": venue,
        "venue_matches": len(venue_rows),
        "form5": form_block(rows, 5, min_n),
        "form10": form_block(rows, 10, min_n),
        "venue_form": form_block(venue_rows, len(venue_rows) or 1, min_n) | {"window": len(venue_rows)},
        "goals_all": goals_block(rows),
        "goals_venue": goals_block(venue_rows),
        "goals_last10": goals_block(last10),
        "misc_all": misc_block(rows),
        "misc_venue": misc_block(venue_rows),
        "corners_last5": {
            "n": len(last5_corners),
            "values": [{"date": r.date.isoformat(), "opponent": r.opponent, "venue": r.venue,
                        "for": r.f["corners"], "against": r.a["corners"]} for r in last5_corners],
            "warning": None if len(last5_corners) >= 5 else
            f"Only {len(last5_corners)} recent matches have corner data.",
        },
        "scoring_consistency": rate(rows, lambda r: r.gf > 0, min_n, "matches scored in"),
        "recent": [{"date": r.date.isoformat(), "competition": r.competition, "venue": r.venue,
                    "opponent": r.opponent, "gf": r.gf, "ga": r.ga, "result": r.result,
                    "ht": None if r.f["ht_goals"] is None else f"{r.f['ht_goals']}-{r.a['ht_goals']}",
                    "corners": None if r.f["corners"] is None else f"{r.f['corners']}-{r.a['corners']}",
                    "cards": None if r.cards_for() is None else f"{r.cards_for()}-{r.cards_against()}"}
                   for r in rows[:10]],
    }
