"""Closing-line value (CLV): did you get a better price than the market's final price?

Beating the closing price consistently is the most reliable early sign of a real edge — it shows up
long before win/loss results become meaningful. Closing price, best source first:

1. Bet365 closing odds from football-data.co.uk's current-season file (1X2, Over/Under 2.5, the main
   Asian handicap line) — a true closing price.
2. The last Open-Matchday snapshot price from the preferred bookmaker before kickoff. Snapshots are
   taken once a day, so this can be many hours before kickoff — labelled as an approximation.

CLV = your odds / closing odds − 1  (positive = you beat the close).
"""
from __future__ import annotations

from ..db import Database
from ..history import closing_row
from ..timeutil import iso, now_utc, parse_iso


def fd_closing(row: dict, market: str, selection: str, line: float | None) -> float | None:
    if market == "1X2":
        return row.get({"home": "b365c_h", "draw": "b365c_d", "away": "b365c_a"}[selection])
    if market == "OU" and line == 2.5:
        return row.get("b365c_o25" if selection == "over" else "b365c_u25")
    if market == "AH" and line is not None and row.get("ahc_line") is not None:
        home_line = row["ahc_line"]
        if selection == "home" and abs(line - home_line) < 1e-9:
            return row.get("b365c_ahh")
        if selection == "away" and abs(line + home_line) < 1e-9:
            return row.get("b365c_aha")
    return None


def closing_price(db: Database, pred: dict, bookmaker: str = "bet365") -> tuple[float, str, str] | None:
    ko = pred.get("kickoff_utc")
    day = (ko or "")[:10]
    if day and pred.get("competition") and pred.get("home_key"):
        row = closing_row(db, pred["competition"], pred["home_key"], pred["away_key"], day)
        if row:
            o = fd_closing(row, pred["market"], pred["selection"], pred["line"])
            if o:
                return float(o), "Bet365 closing (football-data.co.uk)", row["date"]
    params = [pred["match_id"], pred["market"], pred["selection"], bookmaker.lower()]
    sql = ("SELECT odds, captured_at FROM odds_history WHERE match_id=? AND market=? AND selection=? "
           "AND LOWER(bookmaker)=? AND " + ("line IS NULL" if pred["line"] is None else "ABS(line - ?) < 1e-9"))
    if pred["line"] is not None:
        params.append(pred["line"])
    if ko:
        sql += " AND captured_at <= ?"
        params.append(ko)
    row = db.one(sql + " ORDER BY captured_at DESC, id DESC LIMIT 1", tuple(params))
    if row:
        return float(row["odds"]), "Last pre-kickoff snapshot (daily, approximate)", row["captured_at"]
    return None


def update_clv(db: Database) -> dict:
    """Fill closing odds / CLV for predictions whose match has kicked off. Re-checks approximate ones."""
    now = now_utc()
    rows = db.query("SELECT * FROM predictions WHERE odds IS NOT NULL AND "
                    "(closing_odds IS NULL OR closing_source NOT LIKE 'Bet365 closing%')")
    updated = 0
    for p in rows:
        ko = parse_iso(p.get("kickoff_utc"))
        if ko is None or ko > now:
            continue
        c = closing_price(db, p)
        if not c:
            continue
        odds, source, when = c
        clv = p["odds"] / odds - 1
        if p.get("closing_odds") == odds and p.get("closing_source") == source:
            continue
        db.execute("UPDATE predictions SET closing_odds=?, closing_source=?, closing_checked_at=?, clv=? WHERE id=?",
                   (odds, source, when, round(clv, 4), p["id"]))
        updated += 1
    return {"checked": len(rows), "updated": updated, "at": iso(now)}


def clv_summary(rows: list[dict]) -> dict:
    with_c = [r for r in rows if r.get("clv") is not None]
    if not with_c:
        return {"n": 0, "avg_clv": None, "beat_close_share": None, "true_closing_share": None}
    return {
        "n": len(with_c),
        "avg_clv": round(sum(r["clv"] for r in with_c) / len(with_c), 4),
        "beat_close_share": round(sum(1 for r in with_c if r["clv"] > 0) / len(with_c), 3),
        "true_closing_share": round(sum(1 for r in with_c if (r.get("closing_source") or "").startswith("Bet365 closing"))
                                    / len(with_c), 3),
    }
