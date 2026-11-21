"""Spoken grid references through the whole pipeline: extract -> resolve -> tracker, on the real gazetteer."""
import asyncio

import pytest
from shapely.geometry import Point, shape

from backend import grid
from backend.app import gaz
from backend.extract import stub_extract, validate
from backend.resolver import resolve
from backend.tracker import Tracker


def ingest(*texts, start=0):
    t = Tracker(gaz)

    async def go():
        out = []
        for i, text in enumerate(texts):
            out += await t.ingest(text, now=start + 30 * i)
        return out
    return t, asyncio.run(go())


def square_of(g):
    return shape({"type": "Polygon", "coordinates": [[(lon, lat) for lat, lon in grid.square_corners(g)]]})


# ---- grid.py helpers ----

def test_short_grid_takes_the_square_of_the_mapped_area():
    centre = (gaz.proj.lat0, gaz.proj.lon0)
    assert grid.to_mgrs(*centre).startswith("31U DQ")
    assert grid.complete_grid("512110", centre) == "31U DQ 512 110"
    assert grid.complete_grid("51201105", centre) == "31U DQ 5120 1105"
    assert grid.complete_grid("31UDQ512110", centre) == "31U DQ 512 110"
    with pytest.raises(ValueError):
        grid.complete_grid("51211", centre)


def test_square_corners_span_the_square():
    sw, se, ne, nw = grid.square_corners("31U DQ 512 110")
    assert 95 < grid.distance_km(sw, se) * 1000 < 105 and 95 < grid.distance_km(sw, nw) * 1000 < 105
    assert grid.distance_km(grid.to_latlon("31U DQ 512 110"), square_of("31U DQ 512 110").centroid.coords[0][::-1]) < 0.002


@pytest.mark.parametrize("clause, name", [
    ("grid 512 110", "512110"),
    ("enemy mortar at grid 5120 1105", "51201105"),
    ("grid five one two one one zero", "512110"),
    ("at grid 31u dq 512 110", "31UDQ512110"),       # a lower-cased transcript
    ("grid three one uniform delta quebec five one two one one zero", "31UDQ512110"),
])
def test_clause_grid(clause, name):
    anchor, _ = grid.clause_grid(clause)
    assert anchor["kind"] == "grid" and anchor["name"] == name


@pytest.mark.parametrize("clause", ["two tanks 200 metres north", "at the church", "1 m up the street", "alpha 2"])
def test_numbers_without_the_word_grid_are_not_grids(clause):
    assert grid.clause_grid(clause) is None


# ---- extraction ----

def test_rules_mark_the_report_as_a_grid():
    [r] = stub_extract("Zero, this is Alpha two, grid 512 110, over")["reports"]
    assert r["anchor"] == {"name": "512110", "kind": "grid", "doubt": None} and r["relation"] == "at"
    [c] = stub_extract("Zero, this is Bravo one, contact, enemy mortar at grid 5120 1105, over")["reports"]
    assert c["type"] == "contact" and c["anchor"]["name"] == "51201105" and c["contact"]["what"] == "artillery"


def test_landmark_in_the_same_clause_is_kept_as_fallback():
    [r] = stub_extract("Alpha two, at the Saint-Sulpice church grid 512 110")["reports"]
    assert r["anchor"]["kind"] == "grid"
    assert r["fallback"]["anchor"]["name"] == "saint sulpice church" and r["fallback"]["relation"] == "at"


def test_validate_normalises_model_grids():
    def anchor(a):
        return validate({"speaker": "alpha two", "reports": [{"type": "position", "anchor": a}]})["reports"][0]["anchor"]
    assert anchor({"name": "512 110", "kind": "grid"})["name"] == "512110"
    assert anchor({"name": "31U DQ 512 110", "kind": "grid"})["name"] == "31UDQ512110"
    assert anchor({"name": "five one two one one zero", "kind": "grid"})["name"] == "512110"
    assert anchor({"name": "grid 512 110", "kind": "landmark"}) == {"name": "512110", "kind": "grid", "doubt": None}
    assert anchor({"name": "the church", "kind": "grid"}) is None          # not a grid: never guessed


# ---- end to end through the tracker ----

def test_own_position_from_a_short_grid():
    _, [e] = ingest("Zero, this is Alpha two, grid 512 110, over")
    assert e["ok"] and e["callsign"] == "alpha 2" and e["anchor"] == "grid 31U DQ 512 110"
    assert shape(e["region"]).symmetric_difference(square_of("31U DQ 512 110")).area < 1e-10
    assert 50 < e["radius_m"] < 60          # a 100 m square: radius of the circle with the same area is 56 m


def test_contact_at_a_grid():
    t, [c] = ingest("Zero, this is Bravo one, contact, enemy mortar at grid 5120 1105, over")
    assert c["type"] == "contact" and c["ok"] and c["anchor"] == "grid 31U DQ 5120 1105"
    assert c["contact"]["side"] == "hostile"
    assert 5 < c["radius_m"] < 6            # 10 m square
    assert "bravo 1" not in t.units()       # a sighting is not the reporter's position


@pytest.mark.parametrize("text", ["Zero, this is Charlie one, at 31U DQ 512 110, over",
                                  "Zero, this is Charlie one, grid three one uniform delta quebec five one two one one zero"])
def test_full_grid(text):
    _, [e] = ingest(text)
    assert e["ok"] and e["anchor"] == "grid 31U DQ 512 110"


def test_grid_outside_the_map_is_not_plotted():
    _, [e] = ingest("Zero, this is Alpha two, grid 600 150, over")
    assert not e["ok"] and "outside the mapped area" in e["note"] and "grid 31U DQ 600 150" in e["note"]


def test_implausible_grid_falls_back_to_the_landmark():
    _, [e] = ingest("Alpha two, at the Saint-Sulpice church grid 600 150")
    assert e["ok"] and e["anchor"] == "Église Saint-Sulpice" and e["ambiguous"]
    assert "grid 31U DQ 600 150 is outside the mapped area; used saint sulpice church instead" in e["note"]


def test_plausible_grid_beats_the_landmark():
    _, [e] = ingest("Alpha two, at the Saint-Sulpice church grid 512 110")
    assert e["ok"] and e["anchor"] == "grid 31U DQ 512 110"


def test_short_grid_uses_the_units_last_position_and_walking_check():
    t, ev = ingest("Delta one, grid 512 110", "Delta one, grid 5125 1112")
    assert all(e["ok"] for e in ev) and ev[1]["anchor"] == "grid 31U DQ 5125 1112"
    assert t.units()["delta 1"].distance(gaz.proj.to_xy(Point(ev[1]["centre"]))) < 1


def test_resolver_rejects_a_broken_grid():
    out = resolve({"anchor": {"name": "51211", "kind": "grid"}, "relation": "at"}, gaz)
    assert not out["ok"] and "not a valid grid" in out["note"]


def test_short_grid_picks_the_nearest_repeat():
    # 6-figure grids repeat every 100 km; the map sits 11 km above the DP/DQ line, so "900 900" is the one in DP
    assert grid.complete_grid("900900", (gaz.proj.lat0, gaz.proj.lon0)) == "31U DP 900 900"
