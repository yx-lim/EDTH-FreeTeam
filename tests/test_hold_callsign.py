"""Push-to-talk with no callsign heard and no default: hold the report and ask, never plot it on a guessed unit."""
import asyncio

from backend.app import gaz
from backend.tracker import Tracker


def run(coro):
    return asyncio.run(coro)


def test_report_without_callsign_is_held_not_plotted():
    t = Tracker(gaz)
    [e] = run(t.ingest("south of the Saint-Sulpice church", now=0))
    assert e["callsign"] == "unidentified" and e["type"] == "unidentified" and not e["ok"]
    assert "say again your callsign" in e["note"]
    assert t.units() == {}
    assert "_reports" not in t.public(e)


def test_callsign_reply_claims_held_report():
    t = Tracker(gaz)
    [held] = run(t.ingest("south of the Saint-Sulpice church", now=0))
    [e] = run(t.ingest("This is Delta three, over", now=10))
    assert e["callsign"] == "delta 3" and e["ok"] and e["identifies"] == held["id"]
    assert t.get(held["id"])["identified_as"] == "delta 3"
    assert set(t.units()) == {"delta 3"}
    assert t.pending is None


def test_held_report_expires():
    t = Tracker(gaz)
    run(t.ingest("south of the Saint-Sulpice church", now=0))
    [e] = run(t.ingest("This is Delta three, over", now=500))
    assert e["callsign"] == "delta 3" and not e["ok"] and "identifies" not in e


def test_other_units_full_report_does_not_claim_it():
    t = Tracker(gaz)
    run(t.ingest("south of the Saint-Sulpice church", now=0))
    [e] = run(t.ingest("This is Bravo one, at the Saint-Sulpice fountain", now=5))
    assert e["callsign"] == "bravo 1" and "identifies" not in e
    assert t.pending is not None


def test_default_callsign_still_assumed():
    t = Tracker(gaz)
    [e] = run(t.ingest("south of the Saint-Sulpice church", "alpha 1", now=0))
    assert e["callsign"] == "alpha 1" and e["callsign_assumed"] and e["ok"]


def test_held_and_claim_survive_restart(tmp_path):
    log = tmp_path / "events.jsonl"
    t = Tracker(gaz, log=log)
    run(t.ingest("south of the Saint-Sulpice church", now=0))
    run(t.ingest("This is Delta three", now=5))
    r = Tracker(gaz, log=log)
    assert r.events[0]["identified_as"] == "delta 3" and set(r.units()) == {"delta 3"}
