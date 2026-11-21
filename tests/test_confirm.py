"""Duty-officer confirmation: a report stops being a draft, every map hears about it, and the log keeps it."""
import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.net import Net
from backend.tracker import Tracker


@pytest.fixture
def client(monkeypatch, tmp_path):
    tracker = Tracker(app_module.gaz, log=tmp_path / "events.jsonl")
    monkeypatch.setattr(app_module, "tracker", tracker)
    monkeypatch.setattr(app_module, "net", Net(tracker))
    return TestClient(app_module.app)


def test_confirm_marks_event_and_broadcasts(client):
    with client.websocket_connect("/ws") as ws:
        out = client.post("/report", json={"text": "Zero, this is Alpha two, south of the Saint-Sulpice church, over",
                                           "callsign": "alpha 1"}).json()
        event_id = out["events"][0]["id"]
        assert ws.receive_json()["type"] == "event"
        r = client.post(f"/events/{event_id}/confirm")
        assert r.status_code == 200 and r.json()["confirmed"] is True
        msg = ws.receive_json()
        assert msg == {"type": "annotate", "id": event_id, "fields": {"confirmed": True, "confirmed_at": msg["fields"]["confirmed_at"]}}
    state = client.get("/state").json()
    assert state["events"][0]["confirmed"] is True


def test_confirm_survives_restart(client, tmp_path):
    out = client.post("/report", json={"text": "Alpha two at the Saint-Sulpice church", "callsign": "alpha 2"}).json()
    client.post(f"/events/{out['events'][0]['id']}/confirm")
    replayed = Tracker(app_module.gaz, log=tmp_path / "events.jsonl")   # replays the log, as after a restart
    assert replayed.events[0]["confirmed"] is True


def test_confirm_unknown_event(client):
    assert client.post("/events/999/confirm").status_code == 404
