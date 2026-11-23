"""Parse odds text copied from a bookmaker page (e.g. Bet365) into price rows for review.

Nothing here logs in or fetches anything: you select text on the bookmaker page, copy, paste. The
parser is deliberately tolerant and conservative — every row it produces is shown in a preview with
the raw text it came from, and nothing is saved until you confirm. Lines it cannot interpret are
listed, never guessed.

Recognised:
  * match headers: "Arsenal v Dortmund", "Arsenal vs Dortmund", "Arsenal - Dortmund", or two
    consecutive team-name lines (coupon layout) followed by three prices (1X2);
  * market headers: Full Time Result / Match Result / 1X2, Double Chance, Draw No Bet, Both Teams to
    Score, Goals Over/Under / Total Goals / Goal Line, Asian Handicap, 1st Half Goals, Team Goals,
    Corners, Cards / Bookings;
  * selections: team names, Draw/X, 1X/X2/12, "Team or Draw", Yes/No, Over/Under with a line (same line,
    previous line, or the market's line row), Asian lines like "-0.5,-1.0" (= -0.75);
  * prices: decimal with two decimals (1.80, 13.00), fractional (13/8), EVS/Evens.

A bare number with one decimal (2.5) is read as a line, never as a price; Bet365 shows prices with two
decimals. Quarter lines must be written split ("2.0, 2.5") or with two decimals in a label ("Over 2.25").
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field

from .teamnames import team_key

PRICE_RE = re.compile(r"(?<![\w.])(\d{1,3}\.\d{2}|\d{1,3}/\d{1,3}|EVS|EVENS|Evens|Evs|evens|evs)(?![\w./])")
LINE_RE = re.compile(r"([+-]?\d{1,2}(?:\.\d{1,2})?)(?:\s*,\s*([+-]?\d{1,2}(?:\.\d{1,2})?))?")
MATCH_SEP_RE = re.compile(r"^\s*(.+?)\s+(?:v|vs\.?|VS|V|-|–|—)\s+(.+?)\s*$")

MARKETS = [
    # (regex on a header line, market code)  — order matters (most specific first)
    (r"\b(1st|first)\s*half\b.*\b(goals?|over/under|total)\b|\bhalf[- ]time\b.*\bgoals?\b", "1H_OU"),
    (r"\bcorners?\b", "CORNERS_OU"),
    (r"\b(cards?|bookings?)\b", "CARDS_OU"),
    (r"\bdouble chance\b", "DC"),
    (r"\bdraw no bet\b", "DNB"),
    (r"\bboth teams? to score\b|\bbtts\b", "BTTS"),
    (r"\basian handicap\b|^\s*handicap\b(?!.*result)|\balternative asian handicap\b", "AH"),
    (r"\bteam (total )?goals\b|\bhome team goals\b|\baway team goals\b", "TG"),
    (r"\b(goals? over/under|total goals|match goals|goal line|over/under|alternative total goals)\b", "OU"),
    (r"\b(full ?time result|match result|1x2|match betting|^result$|to win)\b", "1X2"),
]
UNSUPPORTED = re.compile(r"\b(correct score|half ?time/full ?time|goalscorer|scorer|result/both|winning margin|"
                         r"handicap result|3-way|race to|first corner|booking points|player|method of victory|"
                         r"odd/even|clean sheet|to qualify)\b", re.I)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace(" ", " ").replace("−", "-")
    return re.sub(r"\s+", " ", s).strip()


def to_decimal(token: str) -> float | None:
    t = token.strip()
    if t.lower() in ("evs", "evens"):
        return 2.0
    if "/" in t:
        a, b = t.split("/")
        if int(b) == 0:
            return None
        return round(1 + int(a) / int(b), 3)
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v > 1.0 else None


def _line_value(text: str, allow_one_decimal_only: bool = False) -> float | None:
    m = LINE_RE.search(text)
    if not m:
        return None
    a = float(m.group(1))
    if m.group(2) is not None:  # split Asian line "2.0, 2.5" -> 2.25
        b = float(m.group(2))
        if abs(abs(a - b) - 0.5) > 1e-9:
            return None
        return (a + b) / 2
    if allow_one_decimal_only and re.search(r"\.\d\d", m.group(1)):
        return None
    if abs(a * 4 - round(a * 4)) > 1e-9:
        return None
    return a


@dataclass
class Fixture:
    match_id: str
    home: str
    away: str

    @property
    def label(self) -> str:
        return f"{self.home} vs {self.away}"


@dataclass
class ParseResult:
    rows: list[dict] = field(default_factory=list)
    ignored: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _team_score(text: str, team: str) -> float:
    a, b = team_key(text), team_key(team)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) >= 4 and (a in b or b in a):
        return 0.9
    ta, tb = set(a.split()), set(b.split())
    if ta & tb and any(len(x) >= 4 for x in ta & tb):
        return 0.8
    return difflib.SequenceMatcher(None, a, b).ratio() * 0.9


def find_fixture(text: str, fixtures: list[Fixture]) -> Fixture | None:
    m = MATCH_SEP_RE.match(text)
    if not m:
        return None
    best, best_s = None, 0.0
    for f in fixtures:
        s = min(_team_score(m.group(1), f.home), _team_score(m.group(2), f.away))
        if s > best_s:
            best, best_s = f, s
    return best if best_s >= 0.75 else None


def _side(text: str, fx: Fixture) -> str | None:
    h, a = _team_score(text, fx.home), _team_score(text, fx.away)
    if max(h, a) < 0.75 or abs(h - a) < 0.05:
        return None
    return "home" if h > a else "away"


def _header(text: str) -> tuple[str | None, bool]:
    """(market code, is_header). Unsupported known markets return (None, True)."""
    low = text.lower()
    if PRICE_RE.search(text):
        return None, False
    if UNSUPPORTED.search(low):
        return None, True
    for pat, code in MARKETS:
        if re.search(pat, low):
            return code, True
    return None, False


def _strip_price(text: str) -> tuple[str, float | None, str | None]:
    found = list(PRICE_RE.finditer(text))
    if not found:
        return text, None, None
    m = found[-1]
    return (text[:m.start()] + text[m.end():]).strip(" \t-:|"), to_decimal(m.group(1)), m.group(1)


def interpret(label: str, market: str, fx: Fixture, ctx_line: float | None) -> tuple[str, str, float | None] | None:
    """Return (market, selection, line) for a selection label in the current market, or None."""
    low = label.lower().strip()
    if market == "1X2":
        if low in ("x", "draw", "tie"):
            return "1X2", "draw", None
        if low == "1":
            return "1X2", "home", None
        if low == "2":
            return "1X2", "away", None
        side = _side(label, fx)
        return ("1X2", side, None) if side else None
    if market == "DC":
        compact = low.replace(" ", "")
        if compact in ("1x", "homeordraw") or ("or draw" in low and _side(low.replace("or draw", ""), fx) == "home"):
            return "DC", "1X", None
        if compact in ("x2", "awayordraw", "draworaway") or ("draw" in low and _side(low.replace("or draw", "").replace("draw or", ""), fx) == "away"):
            return "DC", "X2", None
        if compact in ("12", "homeoraway") or (" or " in low and "draw" not in low):
            return "DC", "12", None
        return None
    if market == "DNB":
        side = _side(label, fx)
        return ("DNB", side, None) if side else None
    if market == "BTTS":
        if low in ("yes", "y"):
            return "BTTS", "yes", None
        if low in ("no", "n"):
            return "BTTS", "no", None
        return None
    if market in ("OU", "1H_OU", "CORNERS_OU", "CARDS_OU", "TG"):
        sel = "over" if re.search(r"\bover\b|^o\b", low) else "under" if re.search(r"\bunder\b|^u\b", low) else None
        if sel is None:
            return None
        rest = re.sub(r"\b(over|under)\b", " ", label, flags=re.I)
        line = _line_value(rest) if LINE_RE.search(rest) else ctx_line
        if line is None:
            return None
        mk = market
        if market == "TG":
            side = _side(re.sub(r"[+-]?\d+(\.\d+)?", " ", rest), fx)
            if side is None:
                return None
            mk = "TG_HOME" if side == "home" else "TG_AWAY"
        return mk, sel, line
    if market == "AH":
        numbers = re.sub(r"^[^\d+-]*", "", label)
        side = _side(re.sub(r"[+-]?\d+(\.\d+)?\s*,?", " ", label), fx)
        line = _line_value(numbers) if numbers else None
        if side is None or line is None:
            return None
        return "AH", side, line
    return None


def parse_odds_text(text: str, fixtures: list[Fixture], default_match: str | None = None) -> ParseResult:
    res = ParseResult()
    fx_by_id = {f.match_id: f for f in fixtures}
    current: Fixture | None = fx_by_id.get(default_match) if default_match else (fixtures[0] if len(fixtures) == 1 else None)
    market: str | None = None
    ctx_line: float | None = None
    pending: str | None = None  # a label waiting for its price on the next line
    lines = [_norm(x) for x in (text or "").splitlines()]
    lines = [x for x in lines if x]

    def emit(label: str, price: float | None, raw_price: str | None, raw: str):
        nonlocal pending
        if current is None:
            res.ignored.append({"text": raw, "reason": "No match identified yet (add a line like 'Home v Away')."})
            return
        if market is None:
            res.ignored.append({"text": raw, "reason": "Market not recognised (or not supported)."})
            return
        if price is None:
            res.ignored.append({"text": raw, "reason": "Price could not be read."})
            return
        sel = interpret(label, market, current, ctx_line)
        if sel is None:
            res.ignored.append({"text": raw, "reason": f"Selection '{label}' not understood for this market."})
            return
        mk, s, ln = sel
        res.rows.append({"match_id": current.match_id, "match_label": current.label, "market": mk, "selection": s,
                         "line": ln, "odds": round(price, 3), "raw": raw,
                         "price_text": raw_price, "fractional": bool(raw_price and "/" in raw_price)})

    i = 0
    while i < len(lines):
        ln = lines[i]
        fx = find_fixture(ln, fixtures) if not PRICE_RE.fullmatch(ln) else None
        if fx:
            current, market, ctx_line, pending = fx, "1X2", None, None
            i += 1
            continue
        # coupon layout: "Home" / "Away" on two lines, then three prices
        if i + 1 < len(lines) and not PRICE_RE.search(ln) and not PRICE_RE.search(lines[i + 1]):
            pair = find_fixture(f"{ln} v {lines[i + 1]}", fixtures)
            if pair and _team_score(ln, pair.home) >= 0.75:
                prices = []
                j = i + 2
                while j < len(lines) and len(prices) < 3 and PRICE_RE.fullmatch(lines[j]):
                    prices.append(lines[j])
                    j += 1
                if len(prices) == 3:
                    current, market, ctx_line, pending = pair, "1X2", None, None
                    for lab, p in zip(("1", "X", "2"), prices):
                        emit(lab, to_decimal(p), p, f"{pair.label}: {lab} {p}")
                    i = j
                    continue
                current, market, ctx_line, pending = pair, "1X2", None, None
                i += 2
                continue
        code, is_header = _header(ln)
        if is_header:
            market, ctx_line, pending = code, None, None
            if code is None:
                res.warnings.append(f"Skipped unsupported market: '{ln}'.")
            i += 1
            continue
        label, price, raw_price = _strip_price(ln)
        if price is not None and label:
            emit(label, price, raw_price, ln)
            pending = None
        elif price is not None and pending:
            emit(pending, price, raw_price, f"{pending} {raw_price}")
            pending = None
        elif price is not None:
            res.ignored.append({"text": ln, "reason": "Price without a selection label."})
        else:
            # a bare line value (e.g. "2.5" or "2.0, 2.5") sets the line for following Over/Under rows
            v = _line_value(ln, allow_one_decimal_only=True) if re.fullmatch(r"[+-]?\d{1,2}(\.\d)?(\s*,\s*[+-]?\d{1,2}(\.\d)?)?", ln) else None
            if v is not None and market in ("OU", "1H_OU", "CORNERS_OU", "CARDS_OU", "TG"):
                ctx_line = v
            else:
                pending = ln
        i += 1
    if not res.rows and not res.ignored:
        res.warnings.append("Nothing recognised. Copy the market header together with its selections and prices.")
    # duplicates (same selection twice): keep the last one, warn
    seen: dict[tuple, int] = {}
    for k, r in enumerate(res.rows):
        key = (r["match_id"], r["market"], r["selection"], r["line"])
        if key in seen:
            res.warnings.append(f"{r['match_label']}: {r['market']} {r['selection']} {r['line'] or ''} appeared twice; "
                                "the last price is kept.")
        seen[key] = k
    res.rows = [res.rows[k] for k in sorted(seen.values())]
    return res
