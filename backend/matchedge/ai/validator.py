"""Validation of local-model output against the structured data it was given.

An AI explanation is accepted only if:
* it is a JSON object with the required keys;
* every cited field path exists in the data;
* every number in its text is present in the data (allowing rounding, and percent/fraction
  conversion). Small counting words like "5 matches" must also be in the data — they are, because
  sample sizes are part of the payload.
Anything else is rejected and the deterministic explanation is shown instead.
"""
from __future__ import annotations

import re
from typing import Any

_NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
# numbers that carry no statistical claim (ordinals in lists, "both", line notation like 2.5 handled via data)
_ALWAYS_OK = {0.0, 1.0, 2.0}


def numbers_in(text: str) -> list[float]:
    return [float(x) for x in _NUM.findall(text or "")]


def flatten_numbers(obj: Any) -> set[float]:
    out: set[float] = set()
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        out |= set(numbers_in(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= flatten_numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= flatten_numbers(v)
    return out


def path_exists(data: Any, path: str) -> bool:
    cur = data
    for part in re.split(r"[.\[\]]+", path.strip()):
        if part == "":
            continue
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False
    return True


def _supported(x: float, known: set[float]) -> bool:
    if x in _ALWAYS_OK:
        return True
    for k in known:
        for cand in (k, k * 100, k / 100):
            if abs(cand - x) <= 0.051 or (abs(x) >= 1 and abs(round(cand) - x) < 1e-9):
                return True
    return False


def _texts(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        return [t for x in obj for t in _texts(x)]
    if isinstance(obj, dict):
        return [t for v in obj.values() for t in _texts(v)]
    return []


def validate_ai_output(out: Any, data: dict, required: list[str]) -> tuple[bool, list[str]]:
    problems: list[str] = []
    if not isinstance(out, dict):
        return False, ["output is not a JSON object"]
    for k in required:
        if k not in out:
            problems.append(f"missing key '{k}'")
    cites = out.get("citations") or []
    if not isinstance(cites, list) or not cites:
        problems.append("no citations of data fields")
    else:
        bad = [c for c in cites if not isinstance(c, str) or not path_exists(data, c)]
        if bad:
            problems.append(f"cited fields not in data: {bad[:3]}")
    known = flatten_numbers(data)
    text = " ".join(_texts({k: v for k, v in out.items() if k != "citations"}))
    unknown = sorted({x for x in numbers_in(text) if not _supported(x, known)})
    if unknown:
        problems.append(f"numbers not found in the data: {unknown[:6]}")
    return not problems, problems
