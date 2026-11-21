"""The language-model path for Ukrainian/Russian, with a fake model (no network): what the model returns is
validated, and the vocabulary adds what the model does not know (lifetime, enemy-only systems)."""
import asyncio

from backend import extract as ex
from backend.stt import PROMPTS


def fake_model(reply):
    async def _mistral(text, key):
        return ex.validate(reply)
    return _mistral


def test_prompt_covers_ukrainian_procedure():
    for word in ("прийом", "мінус", "ждун", "Never output coordinates"):
        assert word in ex.SYSTEM
    assert "Вежа" in PROMPTS["uk"] and "Башня" in PROMPTS["ru"]


def test_model_sighting_gets_vocabulary_fields(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test")
    monkeypatch.setattr(ex, "_mistral", fake_model({"speaker": "Сокол", "reports": [{
        "type": "contact", "anchor": {"name": "Сарай", "kind": "landmark"}, "relation": "at",
        "contact": {"what": "drone", "side": "unknown", "word": "мопед"}}]}))
    out = asyncio.run(ex.extract("Башня, я Сокол, мопед над Сараем, приём."))
    c = out["reports"][0]["contact"]
    assert out["speaker"] == "сокіл"                       # Russian spelling, one unit
    assert (c["detail"], c["ttl_s"], c["side"]) == ("Shahed", 120, "hostile")


def test_model_failure_falls_back_to_rules(monkeypatch):
    async def broken(text, key):
        raise TimeoutError
    monkeypatch.setenv("MISTRAL_API_KEY", "test")
    monkeypatch.setattr(ex, "_mistral", broken)
    out = asyncio.run(ex.extract("Вежа, я Граніт, сто метрів на схід від Сараю, прийом."))
    assert out["extractor"].startswith("rules") and out["reports"][0]["relation"] == "east_of"
