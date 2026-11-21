import os

import pytest

os.environ.pop("ZONE", None)   # tests are written for the Paris zone; backend.zone reads this at import


@pytest.fixture(autouse=True)
def no_cloud_keys(monkeypatch):
    """Tests never reach a paid API: a developer's .env keys (loaded by backend.app) are hidden from every test."""
    for k in ("GEMINI_API_KEY", "ELEVENLABS_API_KEY", "MISTRAL_API_KEY", "EXTRACTOR", "STT_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    from backend import stt
    monkeypatch.setattr(stt, "_chosen", None)   # a switch made in one test (or the app) never leaks into another
