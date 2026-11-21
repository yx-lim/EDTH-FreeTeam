"""Which cloud model is used for each key, and that a failing one degrades instead of dropping the report."""
import asyncio

from backend import extract as ex
from backend import stt


def test_gemini_preferred_over_mistral(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("MISTRAL_API_KEY", "m")
    assert ex.model()[0] == "gemini"
    monkeypatch.setenv("EXTRACTOR", "mistral")
    assert ex.model()[0] == "mistral"
    monkeypatch.setenv("EXTRACTOR", "rules")
    assert ex.model() is None


def test_gemini_reply_is_validated(monkeypatch):
    async def fake(text, key):
        return ex.validate({"speaker": "bravo 1", "reports": [{"type": "contact", "anchor": {"name": "church", "kind": "landmark"},
                                                               "relation": "east_of", "distance_m": "300",
                                                               "contact": {"what": "tank", "side": "hostile"}}]})
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setattr(ex, "_gemini", fake)
    out = asyncio.run(ex.extract("Zero, Bravo one, contact, enemy tank 300 m east of the church, over"))
    assert out["extractor"].startswith("gemini:") and out["reports"][0]["distance_m"] == 300


def test_gemini_failure_falls_back_to_rules(monkeypatch):
    async def broken(text, key):
        raise TimeoutError
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setattr(ex, "_gemini", broken)
    out = asyncio.run(ex.extract("Zero, this is Alpha two, south of the Saint-Sulpice church, over"))
    assert out["extractor"] == "rules (gemini failed: TimeoutError)" and out["reports"][0]["relation"] == "south_of"


def test_elevenlabs_preferred_for_speech(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "m")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "e")
    assert stt.provider() == "elevenlabs"
    monkeypatch.setenv("STT_PROVIDER", "whisper")
    assert stt.provider() == "whisper"


def test_elevenlabs_transcribe(monkeypatch):
    seen = {}

    async def fake(audio, vocabulary, language):
        seen["language"] = language
        return " Zero, this is Alpha two. "
    monkeypatch.setenv("ELEVENLABS_API_KEY", "e")
    monkeypatch.setattr(stt, "_elevenlabs", fake)
    out = asyncio.run(stt.transcribe(b"wav", [], "uk"))
    assert out["provider"] == "elevenlabs" and out["text"] == "Zero, this is Alpha two." and seen["language"] == "uk"


def test_switch_provider_at_run_time(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "e")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setattr(stt, "_whisper_installed", lambda: False)
    assert stt.available() == ["elevenlabs", "gemini"] and stt.provider() == "elevenlabs"
    assert stt.choose("gemini") == "gemini"
    assert stt.choose("none") is None                      # browser speech recognition takes over
    import pytest
    with pytest.raises(ValueError):
        stt.choose("mistral")                              # no key: refused, choice unchanged
    assert stt.provider() is None


def test_stt_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    import backend.app as app_module
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setattr(stt, "_whisper_installed", lambda: False)
    client = TestClient(app_module.app)
    assert client.post("/stt", json={"provider": "gemini"}).json() == {"provider": "gemini", "available": ["gemini"]}
    assert client.get("/state").json()["stt"] == "gemini"
    assert client.post("/stt", json={"provider": "elevenlabs"}).status_code == 400


def test_gemini_transcribe(monkeypatch):
    async def fake(audio, vocabulary, language):
        return "Вежа, я Сокіл, прийом.\n"
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setattr(stt, "_gemini", fake)
    stt.choose("gemini")
    out = asyncio.run(stt.transcribe(b"wav", [], "uk"))
    assert out["provider"] == "gemini" and out["text"] == "Вежа, я Сокіл, прийом."
