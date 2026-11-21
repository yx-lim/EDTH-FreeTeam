"""Rule-based Ukrainian/Russian reports (no language model): the closed demo grammar."""
import pytest
from shapely.geometry import Point

from backend.extract import stub_extract
from backend.geo import Gazetteer
from backend.resolver import resolve

gaz = Gazetteer()

CASES = [  # text, speaker, relation, distance, anchor place, vague
    ("Вежа, я Сокіл, на Ромашці, прийом.", "сокіл", "at", None, "Ромашка", False),
    ("Вежа, я Граніт, сто метрів на схід від Сараю, прийом.", "граніт", "east_of", 100, "Сарай", False),
    ("Башня, я Гранит, полтораста метров западнее Сарая, приём.", "граніт", "west_of", 150, "Сарай", False),
    ("Башня, я Сокол, к северу от Ромашки метров двести, приём.", "сокіл", "north_of", 200, "Ромашка", True),
    ("Вежа, я Лис, метрів сто на північ від орієнтиру три, прийом", "лис", "north_of", 100, "Орієнтир 3", True),
    ("Вежа, я Сокіл, двісті п'ятдесят метрів на північний схід від собору святого Володимира, прийом.", "сокіл",
     "northeast_of", 250, "Cathédrale Ukrainienne Saint-Vladimir-le-Grand", False),
    ("Вежа, я Сокіл, contact, двісті метрів east від Сараю, прийом", "сокіл", "east_of", 200, "Сарай", False),
    ("Вежа, я Лис, біля другої посадки, прийом", "лис", "near", None, "Друга посадка", False),
    ("Вежа, я Граніт два, рухаюсь до Орієнтиру 3, прийом", "граніт 2", "towards", None, "Орієнтир 3", False),
]


@pytest.mark.parametrize("text,speaker,relation,distance,place,vague", CASES)
def test_rules(text, speaker, relation, distance, place, vague):
    got = stub_extract(text)
    r = got["reports"][0]
    assert got["speaker"] == speaker
    assert (r["relation"], r["distance_m"], bool(r.get("vague"))) == (relation, distance, vague)
    assert gaz.find(r["anchor"]["name"])[0].name == place


def test_resolved_region_is_on_the_right_side():
    r = stub_extract("Вежа, я Граніт, сто метрів на схід від Сараю, прийом.")["reports"][0]
    region = resolve(r, gaz)
    barn = gaz.find("Сарай")[0].geom
    assert region["ok"] and gaz.proj.to_xy(Point(region["centre"])).x > barn.x + 50


def test_holding_correction_and_intent():
    assert stub_extract("Вежа, я Лис, без змін, прийом.")["reports"][0]["type"] == "holding"
    assert stub_extract("Вежа, я Граніт, мінус, не Сарай. На Ромашці, прийом.")["reports"][0]["type"] == "correction"
    assert stub_extract("Вежа, я Сокіл, буду на Ромашці через п'ять хвилин, прийом.")["reports"][0]["type"] == "intent"
