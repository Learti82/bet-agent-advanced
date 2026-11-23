import json

import pytest

from matchedge.ai.ollama import OllamaClient, OllamaError, ai_match_explanation, ai_payload_for_match, check_host
from matchedge.ai.validator import validate_ai_output
from matchedge.config import DEFAULT_SETTINGS


def settings(**kw):
    return dict(DEFAULT_SETTINGS) | {"ai_enabled": True} | kw


@pytest.fixture()
def analysis(loaded):
    _, engine = loaded
    mid = next(k for k, m in engine.store.matches.items() if m["status"] == "scheduled" and m["home"] == "Alpha FC")
    return engine.analyze(mid)


def test_disabled_ai_falls_back(analysis):
    out = ai_match_explanation(analysis, dict(DEFAULT_SETTINGS))
    assert out["engine"] == "deterministic" and out["ai"]["used"] is False


def test_non_local_hosts_are_refused():
    check_host("http://127.0.0.1:11434", False)
    check_host("http://localhost:11434", False)
    with pytest.raises(OllamaError):
        check_host("https://api.example.com", False)
    check_host("http://192.168.1.20:11434", True)  # only with explicit opt-in


def test_unreachable_ollama_falls_back(analysis):
    def boom(*a, **k):
        raise OSError("connection refused")
    client = OllamaClient(settings(), post=boom, get=boom)
    out = ai_match_explanation(analysis, settings(), client)
    assert out["ai"]["used"] is False and "unavailable" in out["ai"]["reason"]
    assert out["reasoning"] == analysis["explanation"]["reasoning"]
    assert client.status()["reachable"] is False


def test_valid_ai_output_is_used(analysis):
    data = ai_payload_for_match(analysis)
    xg = data["model_expected_goals"]
    text = {"summary": f"The model expects {xg['total']} goals.", "market_comparison": "See the alternatives.",
            "contradictions": [], "why_selected": "Supported by both hit rates.", "how_it_could_fail": ["Early red card [qualitative]"],
            "citations": ["model_expected_goals.total", "home.form5.sequence"]}
    client = OllamaClient(settings(), post=lambda *a, **k: {"response": json.dumps(text)})
    out = ai_match_explanation(analysis, settings(), client)
    assert out["ai"]["used"] is True


def test_invented_numbers_are_rejected(analysis):
    text = {"summary": "Striker has scored 37 goals in 13 games, 91.3% conversion.", "market_comparison": "",
            "contradictions": [], "why_selected": "", "how_it_could_fail": [], "citations": ["home.form5.sequence"]}
    client = OllamaClient(settings(), post=lambda *a, **k: {"response": json.dumps(text)})
    out = ai_match_explanation(analysis, settings(), client)
    assert out["ai"]["used"] is False and "rejected" in out["ai"]["reason"]


def test_bad_citations_and_non_json_are_rejected(analysis):
    data = ai_payload_for_match(analysis)
    ok, problems = validate_ai_output({"summary": "x", "citations": ["home.injuries"]}, data, ["summary", "citations"])
    assert not ok and any("cited fields" in p for p in problems)
    client = OllamaClient(settings(), post=lambda *a, **k: {"response": "not json"})
    out = ai_match_explanation(analysis, settings(), client)
    assert out["ai"]["used"] is False
