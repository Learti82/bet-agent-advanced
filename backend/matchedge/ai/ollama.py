"""Optional local reasoning layer via Ollama (https://ollama.com).

Safety rules:
* disabled by default; the user enables it in Settings;
* only loopback hosts (localhost / 127.0.0.1 / ::1) are contacted unless the user explicitly sets
  ``allow_non_local_ai_host`` — no cloud AI provider is ever called;
* the model receives structured JSON produced by the statistical engine and must cite the fields
  it uses; its output is validated (``validator.py``) and discarded if it references numbers that
  are not in the data;
* if Ollama is missing, slow or produces invalid output, the deterministic explanation is used.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .validator import validate_ai_output

LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}

SYSTEM_PROMPT = """You are a skeptical, experienced football betting analyst writing for a normal bettor.
You receive DATA as JSON produced by a statistical engine. Rules you must follow:
1. Use ONLY facts and numbers present in DATA. Never invent injuries, lineups, odds, statistics or news.
2. If something is missing from DATA, say it is unavailable. Do not guess it.
3. Every number you write must appear in DATA (you may round it). Do not compute new statistics.
4. Mark opinions that are not directly supported by DATA with the tag [qualitative].
5. Model probabilities are estimates, never facts. Bookmaker prices entered manually are not live prices.
6. Be direct about weaknesses and how the bet could fail. No hype, no generic praise of teams.
Respond with JSON only, using exactly these keys:
{"summary": str, "market_comparison": str, "contradictions": [str], "why_selected": str,
 "how_it_could_fail": [str], "citations": [str]}
"citations" must list the DATA field paths you used, e.g. "selection.probability_pct" or "home.form5.sequence"."""

TICKET_PROMPT = """You are a skeptical football betting analyst. DATA is a JSON accumulator report produced by a
statistical engine. Use ONLY facts and numbers in DATA; never invent anything; every number you write must
appear in DATA. Say plainly whether the ticket is statistically well-supported or has been made too risky by
chasing the target odds. Respond with JSON only:
{"summary": str, "biggest_risks": [str], "final_opinion": str, "citations": [str]}"""


class OllamaError(RuntimeError):
    pass


def check_host(url: str, allow_non_local: bool) -> None:
    host = urllib.parse.urlparse(url).hostname or ""
    if host not in LOOPBACK and not allow_non_local:
        raise OllamaError(f"Refusing to contact non-local AI host '{host}'. Only a local Ollama is allowed "
                          "unless you explicitly enable a non-local host in Settings.")


def _post(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (validated host)
        return json.loads(resp.read().decode())


def _get(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (validated host)
        return json.loads(resp.read().decode())


class OllamaClient:
    def __init__(self, settings: dict, post: Callable = _post, get: Callable = _get):
        self.url = str(settings["ollama_url"]).rstrip("/")
        self.model = str(settings["ollama_model"])
        self.enabled = bool(settings["ai_enabled"])
        self.allow_non_local = bool(settings["allow_non_local_ai_host"])
        self.timeout = float(settings["ai_timeout_seconds"])
        self._post, self._get = post, get

    def status(self) -> dict:
        out = {"enabled": self.enabled, "url": self.url, "model": self.model, "reachable": False,
               "models": [], "model_installed": False, "error": None}
        try:
            check_host(self.url, self.allow_non_local)
            tags = self._get(f"{self.url}/api/tags", 3.0)
            names = [m.get("name") for m in tags.get("models", [])]
            out.update(reachable=True, models=names,
                       model_installed=any(n == self.model or n.split(":")[0] == self.model.split(":")[0]
                                           for n in names if n))
        except (OllamaError, urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            out["error"] = str(exc)
        return out

    def generate(self, system: str, data: dict) -> dict:
        if not self.enabled:
            raise OllamaError("Local AI is disabled in Settings.")
        check_host(self.url, self.allow_non_local)
        prompt = f"{system}\n\nDATA:\n{json.dumps(data, ensure_ascii=False, default=str)}"
        try:
            resp = self._post(f"{self.url}/api/generate",
                              {"model": self.model, "prompt": prompt, "stream": False, "format": "json",
                               "options": {"temperature": 0.2}}, self.timeout)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            raise OllamaError(f"Ollama unavailable: {exc}") from exc
        text = resp.get("response", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise OllamaError("Ollama returned non-JSON output.") from exc


def ai_payload_for_match(a: dict) -> dict:
    """Compact structured data for the model (only engine outputs, nothing else)."""
    rec_key = (a.get("recommendation") or {}).get("key")
    sel = next((c for c in a["candidates"] if c["key"] == rec_key), None)
    hp, ap = a["profiles"]["home"], a["profiles"]["away"]

    def team(p):
        return {"matches": p["matches"], "form5": {k: p["form5"][k] for k in ("sequence", "gf", "ga", "ppg")},
                "form10": {k: p["form10"][k] for k in ("sequence", "gf", "ga", "ppg")},
                "venue": {k: p["venue_form"][k] for k in ("n", "w", "d", "l", "ppg", "gf_avg", "ga_avg")},
                "over25_venue": p["goals_venue"]["over25"], "btts_venue": p["goals_venue"]["btts"],
                "clean_sheets_venue": p["goals_venue"]["clean_sheet"]}

    def brief(c):
        return {"label": c["label"], "probability_pct": c["probability_pct"], "range_pct": c["range_pct"],
                "odds": (c["price"] or {}).get("odds"), "price_source": (c["price"] or {}).get("source"),
                "implied_probability": c["implied_probability"], "hit_rates": c["hit_rates"],
                "evidence_score": c["score"]["evidence"], "qualifies": c["qualifies"],
                "gates_failed": c["gates_failed"]}

    return {
        "match": {"home": a["fixture"]["home"], "away": a["fixture"]["away"],
                  "competition": a["fixture"]["competition_name"], "kickoff_local": a["fixture"]["kickoff_local"]},
        "decision": a["decision"]["status"],
        "factors": [f["message"] for f in a["decision"]["factors"]],
        "missing_information": a["decision"]["missing_information"],
        "model_expected_goals": (a["model"] or {}).get("expected_goals"),
        "league_avg_total_goals": a["league"]["avg_total_goals"],
        "home": team(hp), "away": team(ap),
        "selection": brief(sel) if sel else None,
        "alternatives": [brief(c) for c in a["candidates"] if c["supported"] and c["key"] != rec_key][:5],
        "research_notes": [{"statistic": r.get("statistic"), "value": r.get("value"), "impact": r["impact"],
                            "reliability": r["reliability"], "url": r.get("url")} for r in a["evidence"]],
        "data_quality": a["data_quality"]["score"], "research_score": a["research_score"]["score"],
    }


def ai_match_explanation(a: dict, settings: dict, client: OllamaClient | None = None) -> dict:
    """Return the AI explanation if valid, else the deterministic one with the reason."""
    deterministic = a["explanation"]
    client = client or OllamaClient(settings)
    if not client.enabled:
        return {**deterministic, "ai": {"used": False, "reason": "Local AI disabled in Settings."}}
    data = ai_payload_for_match(a)
    try:
        out = client.generate(SYSTEM_PROMPT, data)
    except OllamaError as exc:
        return {**deterministic, "ai": {"used": False, "reason": str(exc)}}
    ok, problems = validate_ai_output(out, data, ["summary", "market_comparison", "contradictions",
                                                   "why_selected", "how_it_could_fail", "citations"])
    if not ok:
        return {**deterministic, "ai": {"used": False, "reason": "AI output rejected: " + "; ".join(problems[:5])}}
    return {**deterministic, "ai": {"used": True, "model": client.model, "text": out,
                                    "note": "Written by a local model from engine data; numbers verified against the data."}}


def ai_ticket_summary(report: dict, settings: dict, client: OllamaClient | None = None) -> dict:
    client = client or OllamaClient(settings)
    if not client.enabled:
        return {"used": False, "reason": "Local AI disabled in Settings."}
    data = {k: report[k] for k in ("summary", "selections", "biggest_risks", "final_opinion") if k in report}
    try:
        out = client.generate(TICKET_PROMPT, data)
    except OllamaError as exc:
        return {"used": False, "reason": str(exc)}
    ok, problems = validate_ai_output(out, data, ["summary", "biggest_risks", "final_opinion", "citations"])
    if not ok:
        return {"used": False, "reason": "AI output rejected: " + "; ".join(problems[:5])}
    return {"used": True, "model": client.model, "text": out}

