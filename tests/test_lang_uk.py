import json

from backend import lang_uk
from backend.extract import _callsign
from backend.geo import Gazetteer
from backend.resolver import candidates

gaz = Gazetteer()


def test_fold_joins_ukrainian_and_russian_spellings():
    assert lang_uk.fold("Граніт") == lang_uk.fold("Гранит")
    assert lang_uk.fold("п'ятдесят") == lang_uk.fold("пятьдесят").replace("ь", "")


def test_callsigns():
    assert lang_uk.callsign("Сокол") == lang_uk.callsign("Сокіл") == "сокіл"
    assert lang_uk.callsign("Гранит") == "граніт"
    assert lang_uk.callsign("Граніт два") == "граніт 2"
    assert lang_uk.callsign("Чайка") == "чайка"          # unknown callsigns keep their own spelling, й included
    assert _callsign("Сокол") == "сокіл"
    assert _callsign("alpha two") == "alpha 2"            # English path unchanged


def test_numbers():
    assert lang_uk.number("двісті п'ятдесят") == 250
    assert lang_uk.number("полтораста") == 150
    assert lang_uk.number("сто метрів") == 100
    assert lang_uk.number("250") == 250
    assert lang_uk.number("метрів") is None


def name(spoken):
    found = gaz.find(spoken)
    return found[0].name if found else None


def test_codenames_with_case_endings():
    for spoken in ["Ромашка", "Ромашці", "Ромашкою", "Ромашки"]:
        assert name(spoken) == "Ромашка", spoken
    assert name("сто метрів на схід від Сараю") == "Сарай"
    assert name("орієнтир три") == name("ориентиру три") == "Орієнтир 3"
    assert name("второй посадкой") == name("другій посадці") == "Друга посадка"
    assert name("Романа") is None


def test_cyrillic_aliases_to_osm():
    assert name("собору святого Володимира") == "Cathédrale Ukrainienne Saint-Vladimir-le-Grand"
    assert name("Люксембургского сада") == "Jardin du Luxembourg"


def test_unit_anchor_from_russian_spelling():
    units = {"сокіл": gaz.find("Ромашка")[0].geom}
    found = candidates("Сокола", gaz, units, None, "unit")
    assert found and found[0].name == "сокіл"


def test_seeded_codenames_not_saved(tmp_path):
    g = Gazetteer(custom=tmp_path / "custom.json")
    g.add_custom("checkpoint 3", 2.333, 48.85, ["чекпоінт 3"])
    saved = json.loads((tmp_path / "custom.json").read_text(encoding="utf-8"))
    assert [c["name"] for c in saved] == ["checkpoint 3"]
    assert any(c["seeded"] and c["name"] == "Ромашка" for c in g.custom())
