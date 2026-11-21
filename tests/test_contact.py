"""Contact reports: sightings are plotted as their own tracks, never as a unit's position, and are hostile only
when the speaker says so."""
import asyncio

import pytest

from backend.app import gaz
from backend.extract import stub_extract
from backend.tracker import Tracker


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("text, what, side, count", [
    ("Zero, this is Bravo one, contact, two enemy tanks, moving north, 300 metres east of the church, over", "tank", "hostile", 2),
    ("This is Charlie one, enemy infantry in the Luxembourg garden, firing, over", "infantry", "hostile", None),
    ("Alpha one, I see three vehicles near the town hall, over", "vehicle", "unknown", 3),
    ("Alpha one, IED behind the town hall, over", "ied", "unknown", None),
    ("Delta one, civilians at the Medici fountain", "civilians", "neutral", None),
    ("Bravo deux, contact, char ennemi au nord de l'église Saint-Sulpice, à vous", "tank", "hostile", None),
    ("Alpha one, incoming, south of the church", "artillery", "unknown", None),
])
def test_contact_fields(text, what, side, count):
    [r] = [r for r in stub_extract(text)["reports"] if r["type"] == "contact"]
    assert (r["contact"]["what"], r["contact"]["side"], r["contact"]["count"]) == (what, side, count)


def test_side_is_never_assumed_hostile():
    [r] = stub_extract("Alpha one, spotted a tank near the town hall")["reports"]
    assert r["contact"]["side"] == "unknown"


def test_heading_is_not_the_location():
    [r] = stub_extract("Bravo one, contact, enemy tank moving north, 300 metres east of the church")["reports"]
    assert r["relation"] == "east_of" and r["distance_m"] == 300 and r["contact"]["heading"] == "north"


@pytest.mark.parametrize("text", [
    "Zero, this is Alpha two, at the car park, over",
    "Zero, this is Alpha two, south of the Saint-Sulpice church, over",
    "Zero, Bravo two, loud and clear, over",
])
def test_ordinary_reports_are_not_contacts(text):
    assert all(r["type"] != "contact" for r in stub_extract(text)["reports"])


def test_zero_comma_callsign_names_the_speaker():
    assert stub_extract("Zero, Alpha two, at the church, over")["speaker"] == "alpha 2"


def test_contact_is_plotted_and_does_not_move_the_reporter():
    t = Tracker(gaz)
    [own] = run(t.ingest("Zero, this is Bravo one, at the Saint-Sulpice fountain, over", now=0))
    [c] = run(t.ingest("Zero, this is Bravo one, contact, two enemy tanks, 300 metres east of the Saint-Sulpice church, over", now=10))
    assert c["type"] == "contact" and c["ok"] and c["speaker"] == "bravo 1" and c["callsign"] == "contact 1"
    assert c["contact"]["side"] == "hostile" and c["contact"]["count"] == 2
    assert set(t.units()) == {"bravo 1"} and t.history["bravo 1"][-1][0] == own["id"]


def test_contact_relative_to_reporter_uses_their_new_position():
    t = Tracker(gaz)
    events = run(t.ingest("Zero, Alpha two, at the Saint-Sulpice fountain, contact, enemy drone 200 metres north of me, over", now=0))
    assert [e["type"] for e in events] == ["contact", "position"]
    drone, own = events
    assert drone["ok"] and own["ok"]
    assert drone["centre"][1] > own["centre"][1]   # north of the reporter


def test_relative_contact_without_reporter_position_is_not_guessed():
    t = Tracker(gaz)
    [c] = run(t.ingest("Zero, this is Alpha two, contact, enemy drone 200 metres north of me, over", now=0))
    assert not c["ok"] and "relative to the reporter" in c["note"]


def test_contact_from_unidentified_station_is_still_plotted():
    t = Tracker(gaz)
    [c] = run(t.ingest("contact, enemy tank at the Saint-Sulpice church", now=0))
    assert c["type"] == "contact" and c["ok"] and c["speaker"] is None
    assert t.pending is None   # nothing of the reporter's own to hold


def test_contacts_survive_restart_without_becoming_units(tmp_path):
    log = tmp_path / "events.jsonl"
    t = Tracker(gaz, log=log)
    run(t.ingest("Zero, this is Bravo one, contact, enemy tank at the Saint-Sulpice church", now=0))
    r = Tracker(gaz, log=log)
    assert r.events[0]["type"] == "contact" and r.events[0]["ok"] and r.units() == {}
