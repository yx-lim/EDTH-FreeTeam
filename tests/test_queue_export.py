"""Duty-officer queue (drafts, confirm, reject), static hazards that never vanish, and the NVG / GeoJSON picture."""
import asyncio
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from backend import contact as contacts
from backend.app import gaz
from backend.net import Net
from backend.tracker import Tracker

TANK = "Zero, this is Charlie one, contact, enemy tank at the Saint-Sulpice church"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def client(monkeypatch, tmp_path):
    tracker = Tracker(gaz, log=tmp_path / "events.jsonl")
    monkeypatch.setattr(app_module, "tracker", tracker)
    monkeypatch.setattr(app_module, "net", Net(tracker))
    return TestClient(app_module.app)


# --- static hazards ----------------------------------------------------------------------------------------------

def test_ied_never_expires_but_a_drone_does():
    assert contacts.persistent({"what": "ied"}) and contacts.persistent({"what": "unknown", "ttl_s": 21600})
    assert not contacts.persistent({"what": "drone"}) and not contacts.persistent({"what": "drone", "ttl_s": 90})
    t = Tracker(gaz)
    run(t.ingest("Zero, this is Charlie one, contact, IED at the Saint-Sulpice church", now=0))
    run(t.ingest("Zero, this is Charlie one, contact, enemy drone at the Medici fountain", now=0))
    week = 7 * 86400
    assert [e["contact"]["what"] for e in t.picture(now=week)] == ["ied"]


def test_old_mine_still_warns_a_unit_walking_up_to_it():
    t = Tracker(gaz)
    run(t.ingest("Zero, this is Charlie one, contact, enemy IED at the Saint-Sulpice church", now=0))
    [e] = run(t.ingest("Zero, this is Alpha two, south of the Saint-Sulpice church", now=3 * 86400))
    assert e["threats"] and e["threats"][0]["contact"]["what"] == "ied"


# --- drafts, confirm, reject -------------------------------------------------------------------------------------

def test_drafts():
    t = Tracker(gaz)
    [clear] = run(t.ingest("Zero, this is Alpha two, at the Saint-Sulpice church", now=0))
    [assumed] = run(t.ingest("at the Medici fountain", "bravo 1", now=0))
    [c1] = run(t.ingest(TANK, now=0))
    assert not t.is_draft(clear) and t.is_draft(assumed) and t.is_draft(c1)
    [c2] = run(t.ingest("Zero, this is Bravo one, contact, enemy tank near the Saint-Sulpice church", now=30))
    assert not t.is_draft(c2)   # two stations


def test_reject_unit_fix_falls_back_to_previous_and_survives_restart(tmp_path):
    log = tmp_path / "events.jsonl"
    t = Tracker(gaz, log=log)
    [first] = run(t.ingest("Zero, this is Alpha two, at the Saint-Sulpice church", now=0))
    [wrong] = run(t.ingest("Zero, this is Alpha two, at the Medici fountain", now=60))
    t.reject(wrong["id"])
    assert t.history["alpha 2"][-1][0] == first["id"] and t.get(wrong["id"])["rejected"]
    r = Tracker(gaz, log=log)
    assert r.history["alpha 2"][-1][0] == first["id"] and r.get(wrong["id"])["superseded"]


def test_reject_contact_removes_track_or_falls_back():
    t = Tracker(gaz)
    [a] = run(t.ingest(TANK, now=0))
    [b] = run(t.ingest("Zero, this is Bravo one, contact, enemy tank near the Saint-Sulpice church", now=30))
    t.reject(b["id"])
    assert t.tracks["contact 1"]["id"] == a["id"]
    t.reject(a["id"])
    assert "contact 1" not in t.tracks and t.picture(now=40) == []


def test_reject_endpoint_broadcasts(client):
    with client.websocket_connect("/ws") as ws:
        out = client.post("/report", json={"text": TANK}).json()
        eid = out["events"][0]["id"]
        assert ws.receive_json()["type"] == "event"
        assert client.post(f"/events/{eid}/reject").json()["rejected"] is True
        msg = ws.receive_json()
        assert msg["type"] == "annotate" and msg["fields"]["rejected"] and msg["fields"]["superseded"]
    assert client.post("/events/999/reject").status_code == 404


# --- export -----------------------------------------------------------------------------------------------------

def test_picture_exports_only_confirmed_unless_drafts_asked(client):
    client.post("/report", json={"text": "Zero, this is Alpha two, at the Saint-Sulpice church"})
    eid = client.post("/report", json={"text": TANK}).json()["events"][0]["id"]
    kinds = lambda q="": [f["properties"]["kind"] for f in client.get(f"/picture.geojson{q}").json()["features"]]
    assert kinds() == ["unit"] and sorted(kinds("?drafts=true")) == ["contact", "unit"]
    client.post(f"/events/{eid}/confirm")
    feats = client.get("/picture.geojson").json()["features"]
    tank = next(f["properties"] for f in feats if f["properties"]["kind"] == "contact")
    assert tank["sidc"] == "SHGPEVAT-------" and tank["mgrs"].startswith("31U DQ") and tank["seen_by"] == ["charlie 1"]


def test_nvg_is_well_formed_with_app6_symbols(client):
    client.post("/report", json={"text": "Zero, this is Alpha two, at the Saint-Sulpice church"})
    client.post("/report", json={"text": TANK})
    r = client.get("/picture.nvg?drafts=true")
    assert r.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(r.text)
    ns = {"n": "http://tide.act.nato.int/schemas/2012/10/nvg"}
    symbols = sorted(p.get("symbol") for p in root.iterfind(".//n:point", ns))
    assert symbols == ["2525c:SFGPUCI--------", "2525c:SHGAEVAT-------"]   # the draft tank is dashed (A)
    assert root.findall(".//n:polygon", ns)
