"""Radio-net endpoints end to end, with speech-to-text replaced by a script (no key or model needed)."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from backend import stt
from backend.net import Net
from backend.tracker import Tracker
from backend.vad import to_wav

RATE = 16000
SAID = ["Alpha one, this is Zero, send position, over.", "At the Saint-Sulpice fountain, over.",
        "Zero, roger, out.", "Near the Odeon theatre, over."]


@pytest.fixture
def client(monkeypatch):
    tracker = Tracker(app_module.gaz)            # in memory: never touch data/*.jsonl
    monkeypatch.setattr(app_module, "tracker", tracker)
    monkeypatch.setattr(app_module, "net", Net(tracker))
    return TestClient(app_module.app)


def fake_stt(monkeypatch, lines):
    queue = list(lines)

    async def transcribe(audio, vocabulary, language=None):
        assert audio[:4] == b"RIFF" and "over" in vocabulary
        return {"text": queue.pop(0), "provider": "fake", "stt_ms": 5}
    monkeypatch.setattr(stt, "provider", lambda: "fake")
    monkeypatch.setattr(stt, "transcribe", transcribe)


def recording(starts, seconds=2.0):
    rng = np.random.default_rng(3)
    x = rng.normal(0, 0.002, int((starts[-1] + seconds + 2) * RATE))
    t = np.arange(int(seconds * RATE)) / RATE
    for s in starts:
        x[int(s * RATE):int(s * RATE) + len(t)] += rng.normal(0, 0.2, len(t)) * np.clip(np.sin(2 * np.pi * 4 * t), 0.2, 1)
    return to_wav(x.astype(np.float32), RATE)


def test_recorded_net_is_cut_transcribed_and_attributed(client, monkeypatch):
    fake_stt(monkeypatch, SAID)
    r = client.post("/net/recording", content=recording([1, 5, 9, 40]))
    assert r.status_code == 200
    out = r.json()
    assert out["segments"] == 4
    assert [(t["from"], t["kind"]) for t in out["transmissions"]] == [
        ("zero", "request"), ("alpha 1", "report"), ("zero", "ack"), (None, "report")]
    state = client.get("/state").json()
    plotted = [e for e in state["events"] if e["ok"]]
    assert len(plotted) == 1 and plotted[0]["callsign"] == "alpha 1" and plotted[0]["acked_by"] == "zero"
    assert len(state["transmissions"]) == 4


def test_live_segment_and_typed_line(client, monkeypatch):
    fake_stt(monkeypatch, ["Zero, this is Bravo two, at the Medici fountain, over."])
    r = client.post("/net/audio?lang=en&dur=2", content=recording([0.5]))
    assert r.status_code == 200 and r.json()["events"][0]["callsign"] == "bravo 2"
    r = client.post("/net/text", json={"text": "Bravo two, roger, out."})
    assert r.json()["transmissions"][0]["kind"] == "ack"
    client.post("/reset")
    assert client.get("/state").json()["transmissions"] == []


def test_no_speech_to_text_is_a_clear_501(client, monkeypatch):
    monkeypatch.setattr(stt, "provider", lambda: None)
    assert client.post("/net/audio", content=b"RIFF").status_code == 501
    assert client.post("/net/recording", content=b"RIFF").status_code == 501
