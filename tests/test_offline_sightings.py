"""English sightings the offline rules used to miss (docs/edge_case_script_en.md, lines 76-90): overhead, another,
the clock method, our own drones, a second contact against the first one's heading, and place status."""
import asyncio

from backend.geo import Gazetteer
from backend.net import Net
from backend.tracker import Tracker


def play(lines, step=60):
    net = Net(Tracker(Gazetteer()))

    async def run():
        out = []
        for i, text in enumerate(lines):
            out.append((await net.hear(text, now=1_000_000 + i * step))["events"])
        return out
    return asyncio.run(run())


def test_overhead_is_the_reporters_position():
    ev = play(["Zero, this is Echo one, at Odeon station, over.", "Zero, this is Echo one, contact, drone overhead, over."])
    assert ev[1][0]["ok"] and ev[1][0]["anchor"] == "echo 1"


def test_another_is_never_merged():
    ev = play(["Zero, this is Foxtrot three, enemy drone over the Pantheon, heading west, over.",
               "Zero, this is Golf four, another drone over the Pantheon, over."])
    assert ev[0][0]["callsign"] != ev[1][0]["callsign"]


def test_clock_method_is_a_ring_around_the_reporter():
    ev = play(["Zero, this is Alpha two, at the Pantheon, over.",
               "Zero, this is Alpha two, contact, enemy APC at my two o'clock, about one hundred metres, over."])
    e = ev[1][0]
    assert e["ok"] and e["anchor"] == "alpha 2" and "ring" in e["note"]


def test_our_own_drone_is_friendly_and_warns_nobody():
    ev = play(["Zero, this is Bravo two, at Odeon station, over.",
               "Zero, this is Bravo two, friendly drone overhead, ours, over."])
    e = ev[1][0]
    assert e["ok"] and e["contact"]["side"] == "friendly" and not e.get("threats")


def test_second_contact_against_the_first_ones_heading():
    ev = play(["Zero, this is Alpha one, contact, two enemy tanks moving north, three hundred metres east of the church, over.",
               "Zero, this is Foxtrot three, contact, enemy tank at the Luxembourg palace, over."])
    assert ev[0][0]["callsign"] != ev[1][0]["callsign"]


def test_place_status_names_the_place():
    ev = play(["Zero, this is Golf four, the Pont des Arts is destroyed, over.",
               "Zero, this is Hotel one, Rue de Seine is blocked, over.",
               "Zero, this is Kilo two, Rue de Seine is open again, over."])
    assert ev[0][0]["ok"] and ev[0][0]["anchor"] == "Pont des Arts"
    assert ev[1][0]["anchor"] == "Rue de Seine" and ev[2][0].get("cleared") and ev[2][0]["callsign"] == ev[1][0]["callsign"]
