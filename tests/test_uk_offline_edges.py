"""Ukrainian/Russian reports the offline rules used to miss (docs/edge_case_script_uk.md), Irpin zone."""
import asyncio

from backend.geo import DATA, Gazetteer
from backend.net import Net
from backend.tracker import Tracker

ZONE = DATA / "zones" / "irpin"
gaz = Gazetteer(ZONE / "gazetteer.json", aliases=ZONE / "aliases.json", custom=ZONE / "no_custom_places.json",
                codenames=ZONE / "codenames.json")


def play(lines):
    net = Net(Tracker(gaz))

    async def run():
        return [(await net.hear(t, now=1_000_000 + i * 60))["events"] for i, t in enumerate(lines)]
    return asyncio.run(run())


def test_two_units_in_one_call():
    ev = play(["Вежа, я Лис, Сокіл і Граніт на перехресті Донцова і Соборної, прийом."])[0]
    assert {e["callsign"] for e in ev if e["ok"]} == {"сокіл", "граніт"}


def test_grid_said_in_ukrainian():
    ev = play(["Вежа, я Явір, квадрат 049 002, прийом.", "Вежа, я Беркут, сітка 36U UB 049 002, прийом."])
    assert ev[0][0]["anchor"] == ev[1][0]["anchor"] == "grid 36U UB 049 002"


def test_from_me_is_the_reporter():
    ev = play(["Вежа, я Тайфун, біля Парку Героїв, прийом.",
               "Вежа, я Тайфун, снайпер двісті метрів на північ від мене, прийом."])
    assert ev[1][0]["ok"] and ev[1][0]["anchor"] == "тайфун"


def test_from_the_area_of():
    ev = play(["Вежа, я Вовк, арта працює з району Парку Героїв, прийом."])[0]
    assert ev[0]["ok"] and ev[0]["anchor"] == "Парк Героїв"


def test_place_partly_inside_the_area_counts():
    ev = play(["Вежа, я Дніпро, міст біля набережної зруйновано, прийом."])[0]
    assert ev[0]["ok"] and ev[0]["anchor"] == "Ірпінська набережна"


def test_place_status_blocked_then_reopened():
    ev = play(["Вежа, я Птаха, вулиця Соборна заблокована, прийом.",
               "Вежа, я Явір, Соборна вулиця, проїзд відкрито, прийом."])
    assert ev[0][0]["anchor"] == "Соборна вулиця" and not ev[0][0].get("note")
    assert ev[1][0].get("cleared") and ev[1][0]["callsign"] == ev[0][0]["callsign"]


def test_case_endings_are_not_mishearings():
    ev = play(["Вежа, я Явір, поправка, біля Літнього театру, прийом.", "Башня, я Ястреб, на улице Шевченко, приём."])
    assert ev[0][0]["anchor"] == "Літній театр" and "sounds alike" not in (ev[0][0].get("note") or "")
    assert ev[1][0]["anchor"] == "вулиця Шевченка" and "sounds alike" not in (ev[1][0].get("note") or "")
