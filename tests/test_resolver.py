from shapely.geometry import Point

from backend.extract import stub_extract
from backend.geo import Gazetteer
from backend.resolver import resolve

gaz = Gazetteer()
CHURCH = {"name": "saint sulpice church", "kind": "landmark"}


def centre_xy(result):
    return gaz.proj.to_xy(Point(result["centre"]))


def church():
    return gaz.find("saint sulpice church")[0].geom


def test_at_landmark_is_small_and_on_it():
    r = resolve({"anchor": CHURCH, "relation": "at"}, gaz)
    assert r["ok"] and r["anchor"] == "Église Saint-Sulpice"
    assert centre_xy(r).distance(church()) < 5


def test_unknown_place_is_flagged_not_plotted():
    r = resolve({"anchor": {"name": "banana tower", "kind": "landmark"}, "relation": "at"}, gaz)
    assert not r["ok"] and "unknown" in r["note"]


def test_north_of_with_distance():
    r = resolve({"anchor": CHURCH, "relation": "north_of", "distance_m": 100}, gaz)
    c, origin = centre_xy(r), church().centroid
    assert c.y - origin.y > 60 and abs(c.x - origin.x) < 30


def test_behind_is_on_the_far_side_from_last_position():
    origin = church().centroid
    viewer = Point(origin.x - 200, origin.y)          # standing west of the church
    r = resolve({"anchor": CHURCH, "relation": "behind"}, gaz, last=viewer)
    assert r["ok"] and centre_xy(r).x > origin.x      # so "behind" is east of it


def test_behind_without_viewpoint_is_ambiguous():
    r = resolve({"anchor": CHURCH, "relation": "behind"}, gaz)
    assert r["ok"] and r["ambiguous"]


def test_towards_is_capped_by_walking_speed():
    origin = church().centroid
    start = Point(origin.x - 400, origin.y)
    r = resolve({"anchor": CHURCH, "relation": "towards"}, gaz, last=start, elapsed_s=60)
    assert centre_xy(r).distance(start) < 120         # 60 s at 1.5 m/s = 90 m, plus buffer


def test_intersection():
    r = resolve({"anchor": {"name": "rue de rennes", "kind": "street"},
                 "anchor2": {"name": "rue du four", "kind": "street"}, "relation": "intersection"}, gaz)
    assert r["ok"] and r["radius_m"] < 40


def test_bare_church_is_ambiguous():
    r = resolve({"anchor": {"name": "church", "kind": "landmark"}, "relation": "near"}, gaz)
    assert r["ok"] and r["ambiguous"] and r["alternatives"]


def test_stub_extractor():
    p = stub_extract("Alpha two, I'm behind the Saint Sulpice church")
    r = p["reports"][0]
    assert p["speaker"] == "alpha 2" and r["relation"] == "behind"
    assert r["anchor"]["name"] == "saint sulpice church"
    r = stub_extract("bravo 1 moving towards rue de rennes")["reports"][0]
    assert r["type"] == "movement" and r["anchor"]["kind"] == "street"
    assert stub_extract("radio check, over")["reports"][0]["type"] == "other"


def test_towards_a_long_street_aims_at_its_nearest_part():
    start = gaz.find("fontaine des quatre eveques")[0].geom.centroid
    boulevard = gaz.find("boulevard saint germain", kind="street")[0].geom
    r = resolve({"anchor": {"name": "boulevard saint germain", "kind": "street"}, "relation": "towards"},
                gaz, last=start, elapsed_s=90)
    # Heading north to the boulevard, not 1 km east to the middle of a 2.9 km street.
    assert centre_xy(r).distance(start) < 150
    assert centre_xy(r).y > start.y and boulevard.distance(centre_xy(r)) < boulevard.centroid.distance(start)


def test_south_of_a_building_excludes_the_building():
    r = resolve({"anchor": CHURCH, "relation": "south_of"}, gaz)
    assert not r["_geom"].intersects(church().buffer(-3))


def test_spoken_variants_and_transcription_slips_resolve():
    expect = {"town hall": "Mairie du 6e arrondissement", "rude rennes": "Rue de Rennes",
              "san sulpice church": "Église Saint-Sulpice", "saint germain de pre church": "Église Saint-Germain des Prés",
              "medici fountain": "Fontaine Médicis", "odeon theatre": "Odéon–Théâtre de l'Europe",
              "luxembourg palace": "Palais du Luxembourg", "rennes street": "Rue de Rennes"}
    for spoken, osm in expect.items():
        assert gaz.find(spoken)[0].name == osm, spoken
    assert gaz.find("eiffel tower") == [] and gaz.find("bakery on the corner") == []


def test_unreachable_candidate_is_skipped_for_a_reachable_one():
    mabillon = gaz.find("mabillon")[0].geom
    r = resolve({"anchor": {"name": "church", "kind": "landmark"}, "relation": "at"}, gaz, last=mabillon, elapsed_s=60)
    assert r["anchor"] == "Église Saint-Germain des Prés"


def test_implausible_jump_is_flagged():
    far = gaz.find("fontaine medicis")[0].geom
    r = resolve({"anchor": {"name": "rue de rennes", "kind": "street"}, "anchor2": {"name": "rue du four", "kind": "street"},
                 "relation": "intersection"}, gaz, last=far, elapsed_s=10)
    assert r["ok"] and "implausible" in r["note"]
