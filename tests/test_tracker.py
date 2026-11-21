"""Multi-turn behaviour: state per callsign, corrections, intent, units as anchors, French, radio procedure."""
import asyncio

from shapely.geometry import Point, shape

from backend.extract import stub_extract
from backend.geo import Gazetteer
from backend.tracker import Tracker

gaz = Gazetteer()


def play(script):
    tracker = Tracker(gaz)

    async def go():
        out = []
        for when, text in script:
            out += await tracker.ingest(text, now=when)
        return out
    return tracker, asyncio.run(go())


def xy(event):
    return gaz.proj.to_xy(Point(event["centre"]))


def test_same_words_resolve_to_the_church_nearest_the_unit():
    _, a = play([(0, "Bravo one, at Mabillon station"), (120, "Bravo one, now at the church")])
    _, b = play([(0, "Charlie one, corner of Rue Bonaparte and Rue du Vieux Colombier"), (90, "Charlie one, now at the church")])
    assert a[-1]["anchor"] == "Église Saint-Germain des Prés"
    assert b[-1]["anchor"] == "Église Saint-Sulpice"


def test_correction_withdraws_the_previous_fix_and_keeps_its_context():
    tracker, ev = play([(0, "Delta two, south of the Saint-Germain-des-Prés church"),
                        (20, "Delta two, correction, east of the church, not south")])
    assert ev[1]["corrects"] == ev[0]["id"] and tracker.events[0]["superseded"]
    assert ev[1]["anchor"] == "Église Saint-Germain des Prés"
    church = gaz.find("eglise saint germain des pres")[0].geom.centroid
    assert xy(ev[1]).x > church.x + 20


def test_intent_does_not_move_the_unit_and_holding_reuses_the_fix():
    tracker, ev = play([(0, "Delta one, at the Saint Germain market"),
                        (30, "Delta one, I'll be at Odeon station in five minutes"),
                        (60, "Delta one, holding position")])
    assert not ev[1]["ok"] and "intention" in ev[1]["note"]
    assert ev[2]["ok"] and ev[2]["centre"] == ev[0]["centre"]


def test_back_where_i_was_uses_the_timestamped_history():
    _, ev = play([(0, "Echo two, at the Saint Germain market"), (300, "Echo two, at Odeon station"),
                  (600, "Echo two, back at the market"), (900, "Echo two, back where I was ten minutes ago")])
    assert ev[2]["anchor"].startswith("Marché Saint-Germain")
    assert ev[3]["centre"] == ev[1]["centre"]


def test_units_as_anchors_and_reports_about_other_units():
    _, ev = play([(0, "Alpha one, at the Fontaine Médicis"), (30, "Bravo two, I'm with Alpha one"),
                  (60, "Alpha one, Bravo one is at the Odeon theatre, I'm still at the fountain")])
    assert ev[1]["callsign"] == "bravo 2" and xy(ev[1]).distance(xy(ev[0])) < 5
    assert {e["callsign"] for e in ev[2:]} == {"bravo 1", "alpha 1"}
    assert next(e for e in ev[2:] if e["callsign"] == "alpha 1")["anchor"] == "Fontaine Médicis"


def test_two_units_in_one_transmission():
    _, ev = play([(0, "Charlie one and Charlie two at the corner of Rue de Tournon and Rue de Vaugirard")])
    assert [e["callsign"] for e in ev] == ["charlie 1", "charlie 2"] and all(e["ok"] for e in ev)


def test_radio_procedure_and_combined_clues():
    _, ev = play([(0, "Hello Zero, this is Alpha two, uh, position west side of Place Saint-Sulpice, by the town hall, over")])
    assert ev[0]["callsign"] == "alpha 2" and "Mairie du 6e arrondissement" in ev[0]["anchor"]
    assert xy(ev[0]).distance(gaz.find("town hall")[0].geom) < 50


def test_non_reports_and_unknown_places_are_not_plotted():
    _, ev = play([(0, "Zero, this is Charlie one, roger, out"), (10, "Charlie one, at the Eiffel Tower")])
    assert not ev[0]["ok"] and not ev[1]["ok"] and "unknown" in ev[1]["note"]


def test_french_reports():
    r = stub_extract("Alpha deux, je suis au sud de l'église Saint-Sulpice, rue Palatine")
    assert r["speaker"] == "alpha 2" and r["reports"][0]["relation"] == "south_of"
    r = stub_extract("Bravo un, au carrefour de la rue de Rennes et de la rue du Four")["reports"][0]
    assert r["relation"] == "intersection" and r["anchor2"]["name"] == "rue du four"
    _, ev = play([(0, "Alpha deux, je suis au sud de l'église Saint-Sulpice"),
                  (90, "Alpha deux, je me dirige vers le boulevard Saint-Germain")])
    assert all(e["ok"] for e in ev) and ev[1]["type"] == "movement"


def test_log_replay_restores_state(tmp_path):
    log = tmp_path / "events.jsonl"
    t1 = Tracker(gaz, log=log)
    asyncio.run(t1.ingest("Delta two, south of the Saint-Germain-des-Prés church", now=0))
    asyncio.run(t1.ingest("Delta two, correction, east of the church, not south", now=20))
    t2 = Tracker(gaz, log=log)
    assert [e["superseded"] for e in t2.events] == [True, False]
    assert list(t2.units()) == ["delta 2"]


def test_movement_towards_a_far_street_is_not_flagged_as_a_jump():
    _, ev = play([(0, "Alpha two, I'm at the Saint-Sulpice fountain"), (5, "Alpha two, I moved towards Boulevard Saint-Germain")])
    assert ev[1]["ok"] and "implausible" not in ev[1]["note"] and not ev[1]["ambiguous"]


def test_movement_follows_streets_from_every_plausible_start():
    # Lysk's slide example: from the fountain, "moved towards" the boulevard means walking up Rue Bonaparte.
    _, ev = play([(0, "Alpha two, I'm at the Saint-Sulpice fountain"), (90, "Alpha two, I moved towards Boulevard Saint-Germain")])
    region = gaz.proj.to_xy(shape(ev[1]["region"]))
    assert region.contains(gaz.proj.to_xy(Point(2.332976, 48.851804)))          # Rue Bonaparte, ~100 m north
    assert not region.contains(gaz.find("boulevard saint germain", kind="street")[0].geom.centroid)
    # Start known only as "south of the church": the walk may go round either side, so both must be covered.
    _, ev = play([(0, "Alpha two, I'm south of the Saint-Sulpice church"), (90, "Alpha two, moving towards Boulevard Saint-Germain")])
    region = gaz.proj.to_xy(shape(ev[1]["region"]))
    assert region.contains(gaz.proj.to_xy(Point(2.335332, 48.851317)))          # east side, Rue Mabillon
