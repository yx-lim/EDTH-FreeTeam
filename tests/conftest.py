import pytest


@pytest.fixture(autouse=True)
def no_cloud_keys(monkeypatch):
    """Tests never reach a paid API: a developer's .env keys (loaded by backend.app) are hidden from every test."""
    for k in ("GEMINI_API_KEY", "ELEVENLABS_API_KEY", "MISTRAL_API_KEY", "EXTRACTOR", "STT_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
