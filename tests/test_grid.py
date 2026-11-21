import random

import pytest

from backend.grid import (digits_for_radius, distance_km, find_spoken_grid, format_grid, parse_spoken_grid,
                          square_m, to_latlon, to_mgrs)

VINCENNES = (48.8445, 2.4385)
SARAI = "31U DQ 5978 0936"                 # a 10 m square in the Bois de Vincennes
SARAI_CENTRE = (48.835957, 2.451979)       # from pygeodesy, independent of the mgrs package


# ---- conversion (reference values from pygeodesy / pyproj, see the benchmark in the PR notes) ----

def test_known_points():
    assert to_mgrs(46.578, 9.866) == "32T NS 6635 5863"      # map.army sample unit
    assert to_mgrs(*SARAI_CENTRE) == SARAI
    assert to_mgrs(50.4501, 30.5234) == "36U UA 2418 9160"   # Kyiv: Ukraine is in zones 34-37


def test_to_latlon_is_the_centre_of_the_square():
    lat, lon = to_latlon(SARAI)
    assert distance_km((lat, lon), SARAI_CENTRE) * 1000 < 0.5
    # a 100 m square's centre is 50 m in from its south-west corner on each axis
    c100 = to_latlon("31U DQ 597 093")
    sw100 = to_latlon("31U DQ 59700 09300")
    assert 65 < distance_km(c100, sw100) * 1000 < 76


def test_round_trip_within_the_1m_square():
    r = random.Random(7)
    for _ in range(500):
        p = (r.uniform(44.4, 52.3), r.uniform(22.2, 40.1))   # Ukraine
        assert distance_km(to_latlon(to_mgrs(*p, digits=5)), p) * 1000 <= 0.72   # half-diagonal of 1 m


def test_spacing_and_validation():
    assert format_grid("31udq59780936") == SARAI
    assert format_grid("31U DQ") == "31U DQ"
    for bad in ("31I DQ 1234 5678", "61U DQ 1234 5678", "31U DQ 123 45678", "hello"):
        with pytest.raises(ValueError):
            format_grid(bad)


def test_precision_follows_uncertainty():
    assert [digits_for_radius(r) for r in (0.5, 8, 40, 150, 2000, 50000)] == [5, 4, 3, 2, 1, 1]
    assert to_mgrs(*SARAI_CENTRE, radius_m=150) == "31U DQ 59 09"
    assert square_m("31U DQ 597 093") == 100


# ---- spoken grids ----

SPOKEN = [
    # (what was said, expected grid or None, why it is here)
    ("contact at grid three two tango november sierra six six three five five eight six three, moving north",
     "32T NS 6635 5863", "English NATO alphabet"),
    ("grid three one uniform delta quebec five nine seven eight zero nine three six, over", SARAI, "English"),
    ("grid three one uniform delta quebec five nine seven eight zero nine three six, two zero metres north",
     SARAI, "distance after the grid (was 84 km off)"),
    ("grid thirty one uniform delta quebec five nine seven eight zero nine three six", SARAI,
     "zone as a number word (was zone 1, 9,181 km off)"),
    ("grid thirty-one uniform delta quebec five nine seven eight zero nine three six", SARAI, "hyphenated"),
    ("grid three one uniform delta quebec five nine seven zero nine three, over", "31U DQ 597 093", "100 m grid"),
    ("grid 31U DQ 5978 0936", SARAI, "written with spaces (was not found)"),
    ("we are at 31udq59780936 now", SARAI, "written run together"),
    ("two tanks at grid three one uniform delta quebec five nine seven eight zero nine three six", SARAI,
     "number before the grid"),
    ("Вежа, я Сокіл, квадрат тридцять один юніформ дельта квебек п'ять дев'ять сім вісім нуль дев'ять три шість, прийом",
     SARAI, "Ukrainian"),
    ("Вежа, я Сокіл, квадрат тридцять один юніформ дельта квебек пʼятдесят девʼять сімдесят вісім нуль девʼять "
     "тридцять шість, прийом", SARAI, "Ukrainian, digits read in pairs, typographic apostrophe"),
    ("Вежа, я Граніт, тридцять один юніформ дельта квебек пять девять сім вісім нуль девять три шість двадцять метрів "
     "на схід", SARAI, "Ukrainian without apostrophes, distance after the grid, no pause"),
    ("Башня, я Сокол, тридцать один юниформ дельта квебек пять девять семь восемь ноль девять три шесть, приём",
     SARAI, "Russian"),
    ("Башня, я Гранит, 31U DQ 5978 0936, вижу двоих", SARAI, "mixed: written grid in a Russian sentence"),
    ("I am 20m behind the church", None, "no grid"),
    ("Alpha two at the town hall, over", None, "no grid, NATO words"),
    ("Zero, this is Delta one, at the Hotel de Ville, over", None, "no grid, NATO words that are also names"),
    ("Вежа, я Сокіл, на Ромашці, без змін, прийом", None, "no grid, Ukrainian"),
]


@pytest.mark.parametrize("said,want,why", SPOKEN, ids=[s[2] for s in SPOKEN])
def test_spoken(said, want, why):
    assert find_spoken_grid(said) == want


def test_area_check_blocks_misheard_grids():
    far = "grid one uniform delta quebec five nine seven eight zero nine three six"   # zone 1: the Pacific
    hit = parse_spoken_grid(far, near=VINCENNES)
    assert hit.grid == "01U DQ 5978 0936" and "km from the area" in hit.problem
    assert find_spoken_grid(far, near=VINCENNES) is None
    assert find_spoken_grid(SPOKEN[1][0], near=VINCENNES) == SARAI


def test_guesses_are_flagged_for_read_back():
    glued = "grid three one uniform delta quebec five nine seven eight zero nine three six two zero metres north"
    hit = parse_spoken_grid(glued)
    assert hit.grid == SARAI and "distance" in hit.ambiguous
    clean = parse_spoken_grid(SPOKEN[2][0])        # a pause before "two zero metres": no guess needed
    assert clean.grid == SARAI and clean.ambiguous is None
    count = parse_spoken_grid("grid 31U DQ 5978 0936, two, moving west")   # the pause makes it clear
    assert count.grid == SARAI and count.ambiguous is None


def test_full_stop_between_numbers_is_a_pause():
    # was "31U DQ 59 78": a wrong 1 km square, with no warning
    assert find_spoken_grid("grid 31U DQ 5978.0936") == SARAI
    assert find_spoken_grid("grid 31U DQ 5978. 0936, over") == SARAI
    assert find_spoken_grid("квадрат 31U DQ 5978 0936. 200 метрів на південь") == SARAI
    assert find_spoken_grid("Grid 31U DQ 5978 0936. Over.") == SARAI


def test_one_metre_flag_only_without_area_check():
    one_m = "grid thirty one uniform delta quebec five eight eight zero two one zero three two one over"
    assert "1 m" in parse_spoken_grid(one_m).ambiguous
    hit = parse_spoken_grid(one_m, near=VINCENNES)
    assert hit.grid == "31U DQ 58802 10321" and hit.ambiguous is None and hit.problem is None
    glued = "grid three one uniform delta quebec five nine seven eight zero nine three six two zero"
    assert parse_spoken_grid(glued, near=VINCENNES).problem          # stray "two zero": rejected, not plotted


def test_hit_carries_position_and_square():
    hit = parse_spoken_grid(SPOKEN[9][0], near=VINCENNES)
    assert hit.problem is None and hit.square_m == 10
    assert distance_km((hit.lat, hit.lon), SARAI_CENTRE) * 1000 < 0.5


def test_square_that_does_not_exist():
    hit = parse_spoken_grid("grid 31U ZZ 1234 5678")
    assert hit is None or hit.problem
