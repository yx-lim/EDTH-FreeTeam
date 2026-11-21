"""Ukrainian/Russian at the level of the English pipeline (Paris zone, offline rules): distances, ranges, bearings,
the wider set of relations, callsigns, and Cyrillic names for Latin-script places."""
import pytest

from backend import lang_uk
from backend.geo import Gazetteer
from backend.resolver import resolve

gaz = Gazetteer()


def report(text: str) -> tuple[str, dict]:
    out = lang_uk.stub_extract_uk(text)
    return out["speaker"], out["reports"][0]


@pytest.mark.parametrize("phrase, metres", [
    ("двісті метрів на схід від Сараю", 200),
    ("пів кілометра на південь від Ромашки", 500),
    ("півтора кілометра на південь від Ромашки", 1500),
    ("два квартали на північ від Сараю", 200),
    ("около двухсот метров восточнее Сарая", 200),
])
def test_distances(phrase, metres):
    _, r = report(f"Вежа, я Граніт, {phrase}, прийом.")
    assert r["distance_m"] == metres


@pytest.mark.parametrize("phrase", ["двісті-триста метрів на схід від Сараю",
                                    "від двохсот до трьохсот метрів на схід від Сараю"])
def test_ranges(phrase):
    _, r = report(f"Вежа, я Граніт, {phrase}, прийом.")
    assert (r["distance_min_m"], r["distance_max_m"], r["distance_m"]) == (200, 300, 250) and r["vague"]


@pytest.mark.parametrize("phrase, deg, metres", [
    ("азимут сорок п'ять, триста метрів від Сараю", 45, 300),
    ("азимут 15-00, двісті метрів від Ромашки", 90, 200),       # goniometer divisions: 60-00 to a circle
    ("по азимуту 1600 мілів, двісті метрів від Ромашки", 90, 200),
])
def test_bearings(phrase, deg, metres):
    _, r = report(f"Вежа, я Граніт, {phrase}, прийом.")
    assert r["relation"] == "bearing" and r["bearing_deg"] == pytest.approx(deg) and r["distance_m"] == metres


@pytest.mark.parametrize("phrase, relation", [
    ("навпроти Сараю", "opposite"), ("напротив Сарая", "opposite"), ("всередині Ромашки", "inside"),
    ("в районі Сараю", "around"), ("в районе Ромашки", "around"), ("не доходячи до Сараю", "in_front_of"),
    ("по той бік Сараю", "behind"), ("ліворуч від Сараю", "left_of"), ("справа от Сарая", "right_of"),
    ("триста метрів від Сараю", "from"), ("п'ять хвилин пішки від Сараю", "from"),
    ("на перехресті Ренн та Фур", "intersection"),
])
def test_relations(phrase, relation):
    _, r = report(f"Вежа, я Граніт, {phrase}, прийом.")
    assert r["relation"] == relation


def test_cyrillic_nato_callsign_is_the_latin_unit():
    speaker, _ = report("Вежа, я Альфа один, біля Сараю, прийом.")
    assert speaker == "alpha 1"


def test_new_nicknames_and_russian_spelling():
    assert lang_uk.callsign("Ястреб") == "яструб" and lang_uk.callsign("Днепр") == "дніпро"


@pytest.mark.parametrize("spoken, place", [
    ("біля Пантеону", "Panthéon"), ("на бульварі Сен-Жермен", "Boulevard Saint-Germain"),
    ("Нотр-Даму", "Cathédrale Notre-Dame de Paris"), ("на вулиці Ренн", "Rue de Rennes"), ("Лувру", "Musée du Louvre"),
])
def test_ukrainian_names_for_paris_places(spoken, place):
    assert gaz.find(spoken)[0].name == place


def test_transliteration_bridge_without_an_alias():
    assert gaz.find("Вавен")[0].name == "Vavin"           # no alias: matched through its Latin spelling
    assert gaz.find("Романа") == []                        # still no wild guesses


def test_ukrainian_report_resolves_end_to_end():
    _, r = report("Вежа, я Граніт, двісті метрів на південь від Пантеону, прийом.")
    res = resolve(r, gaz)
    assert res["ok"] and res["anchor"] == "Panthéon"
