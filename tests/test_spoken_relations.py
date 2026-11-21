"""Misheard callsigns and places, and the wider set of spoken directions and distances (offline rules path)."""
import asyncio

import pytest
from shapely.geometry import Point

from backend import callsign, lang_uk
from backend.extract import extract
from backend.geo import Gazetteer
from backend.resolver import resolve

gaz = Gazetteer()


def first(text: str) -> tuple[dict, dict]:
    d = asyncio.run(extract(text))   # conftest hides API keys: this is the rule-based path
    r = next(x for x in d["reports"] if x.get("anchor"))
    return d, r


def xy(res: dict) -> Point:
    return gaz.proj.to_xy(Point(res["centre"]))


# --- callsigns -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("heard, fixed", [
    ("Zero, this is Alfa won, over", "Zero, this is Alpha 1, over"),
    ("Zero this is Charly too, at the fountain", "Zero this is Charlie 2, at the fountain"),
    ("this is fox trot three at the corner", "this is Foxtrot 3 at the corner"),
    ("Zero, this is Ecko ate, over", "Zero, this is Echo 8, over"),
    ("this is Delter 3 behind the church", "this is Delta 3 behind the church"),
])
def test_misheard_nato_callsigns_are_snapped(heard, fixed):
    assert callsign.snap(heard) == fixed


@pytest.mark.parametrize("text", [
    "Alpha to Zero, radio check",                       # "to" is procedure here, not a 2
    "rue Victor Hugo near the Hotel de Ville",           # letter words inside place names
    "I'm at the golf course with Mike",
])
def test_ordinary_words_are_left_alone(text):
    assert callsign.snap(text) == text


def test_model_callsigns_are_canonical():
    assert callsign.canonical("alfa won") == "alpha 1"
    assert callsign.canonical("fox trot two") == "foxtrot 2"


def test_ukrainian_nickname_matched_by_sound():
    assert lang_uk.callsign("Гранід") == "граніт"      # д/т blur on a noisy radio
    assert lang_uk.callsign("Сакіл") == "сокіл"        # unstressed о heard as а
    assert lang_uk.callsign("Мадяр") == "мадяр"        # not in the table: kept as heard


def test_speaker_from_misheard_callsign():
    d, _ = first("Zero this is Alfa won, about 200 metres north of Saint-Sulpice church, over")
    assert d["speaker"] == "alpha 1"


# --- places --------------------------------------------------------------------------------------------------------
def test_sound_alike_place_is_plotted_but_flagged():
    res = resolve({"anchor": {"name": "Odin", "kind": "landmark"}, "relation": "at"}, gaz)
    assert res["ok"] and res["anchor"] == "Odéon" and res["ambiguous"] and "sounds alike" in res["note"]


def test_nonsense_place_is_still_unknown():
    assert not resolve({"anchor": {"name": "banana tower", "kind": "landmark"}, "relation": "at"}, gaz)["ok"]


def test_wider_area_and_alternative_names():
    for name in ("Panthéon", "Café de Flore", "Cathédrale Notre-Dame de Paris"):
        assert gaz.find(name)[0].name == name
    assert gaz.find("Шатле")[0].name == "Châtelet"     # Russian name from OpenStreetMap


def test_bare_category_prefers_the_area_of_operations():
    res = resolve({"anchor": {"name": "church", "kind": "landmark"}, "relation": "at"}, gaz)
    assert res["anchor"] == "Église Saint-Sulpice"


# --- distances -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("phrase, metres", [
    ("100 yards west of the Odeon theatre", 91),
    ("300 feet west of the Odeon theatre", 91),
    ("half a click south of the Luxembourg gardens", 500),
    ("two blocks north of Mabillon", 200),
    ("a couple hundred metres south of the Pantheon", 200),
    ("1.5 km north of the Pantheon", 1500),
])
def test_distance_units(phrase, metres):
    _, r = first(f"this is Echo 1, {phrase}")
    assert r["distance_m"] == pytest.approx(metres, abs=1)


def test_range_and_approximate_distance():
    _, r = first("this is Bravo 2, between 200 and 300 metres east of the Pantheon")
    assert (r["distance_min_m"], r["distance_max_m"], r["distance_m"]) == (200, 300, 250)
    _, r = first("this is Bravo 2, about 200 metres east of the Pantheon")
    assert r["vague"] and r["distance_m"] == 200


def test_vague_distance_widens_the_region():
    base = {"anchor": {"name": "Panthéon", "kind": "landmark"}, "relation": "east_of", "distance_m": 200}
    assert resolve({**base, "vague": True}, gaz)["radius_m"] > resolve(base, gaz)["radius_m"]


# --- directions ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("phrase, deg", [
    ("bearing 045, 300 metres from Saint-Sulpice church", 45),
    ("on bearing zero niner zero from the Pantheon", 90),
    ("500 m on azimuth 1600 mils from the Pantheon", 90),
    ("north northeast of the Pantheon", 22.5),
])
def test_bearings(phrase, deg):
    _, r = first(f"this is Echo 1, {phrase}")
    assert r["relation"] == "bearing" and r["bearing_deg"] == pytest.approx(deg)


def test_bearing_region_points_the_right_way():
    pan = gaz.find("Panthéon")[0].geom.centroid
    res = resolve({"anchor": {"name": "Panthéon", "kind": "landmark"}, "relation": "bearing", "bearing_deg": 90,
                   "distance_m": 300}, gaz)
    c = xy(res)
    assert c.x - pan.x > 200 and abs(c.y - pan.y) < 60


@pytest.mark.parametrize("phrase, relation", [
    ("across the street from Saint-Sulpice church", "opposite"),
    ("opposite the Cafe de Flore", "opposite"),
    ("inside the Luxembourg gardens", "inside"),
    ("just past the Pantheon", "behind"),
    ("just short of the Pantheon", "in_front_of"),
    ("to the left of the Pantheon", "left_of"),
    ("in the area of Odeon", "around"),
    ("400 metres from the Pantheon", "from"),
    ("five minutes walk from Odeon station", "from"),
])
def test_relation_words(phrase, relation):
    _, r = first(f"this is Echo 1, {phrase}")
    assert r["relation"] == relation


def test_from_is_a_ring():
    res = resolve({"anchor": {"name": "Panthéon", "kind": "landmark"}, "relation": "from", "distance_m": 400}, gaz)
    pan = gaz.find("Panthéon")[0].geom.centroid
    assert res["ok"] and res["ambiguous"] and xy(res).distance(pan) < 100 and res["radius_m"] > 300


def test_inside_stays_within_the_walls():
    garden = gaz.find("Jardin du Luxembourg")[0].geom
    res = resolve({"anchor": {"name": "Jardin du Luxembourg", "kind": "landmark"}, "relation": "inside"}, gaz)
    assert garden.buffer(5).contains(gaz.proj.to_xy(__import__("shapely").geometry.shape(res["region"])))


def test_left_of_uses_the_previous_position():
    pan = gaz.find("Panthéon")[0].geom.centroid
    last = Point(pan.x, pan.y - 300).buffer(10)          # coming from the south, facing north
    res = resolve({"anchor": {"name": "Panthéon", "kind": "landmark"}, "relation": "left_of"}, gaz, last=last,
                  elapsed_s=600)
    assert xy(res).x < pan.x - 20                         # left when facing north is west
