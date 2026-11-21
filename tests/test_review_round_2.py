"""Findings from a read-through of the rules path: things that put a unit or an enemy in the wrong place."""
import asyncio

import pytest

from backend.geo import Gazetteer
from backend.tracker import Tracker


@pytest.fixture(autouse=True)
def rules_only(monkeypatch):
    for key in ("GEMINI_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def run(lines, step=60):
    async def go():
        tracker, t, out = Tracker(Gazetteer(), log=None), 1e6, []
        for line in lines:
            out.append(await tracker.ingest(line, None, now=t))
            t += step
        return tracker, out, t
    return asyncio.run(go())


def where(tracker, t):
    return {e["callsign"]: e["anchor"] for e in tracker.picture(now=t) if e.get("type") != "contact"}


def contacts(tracker, t):
    return [e for e in tracker.picture(now=t) if e.get("type") == "contact"]


def test_two_units_in_one_call_each_get_their_own_place():
    tracker, _, t = run(["Вежа, я Лис, Сокіл на Сараї, я на Ромашці, прийом."])
    assert where(tracker, t) == {"сокіл": "Сарай", "лис": "Ромашка"}


@pytest.mark.parametrize("first, second, stays", [
    ("Zero, this is Alpha two, at the town hall, over",
     "Zero, this is Alpha two, enemy reported at the Pantheon yesterday, nothing seen now, over", "Mairie du 6e arrondissement"),
    ("Zero, this is Alpha two, at the town hall, over",
     "Zero, this is Alpha two, no enemy at the Odeon theatre, over", "Mairie du 6e arrondissement"),
    ("Вежа, я Лис, на Ромашці, прийом.", "Вежа, я Лис, біля Сараю противника немає, прийом.", "Ромашка"),
    ("Вежа, я Лис, на Ромашці, прийом.", "Вежа, я Лис, біля Сараю чисто, прийом.", "Ромашка"),
    ("Вежа, я Лис, на Ромашці, прийом.", "Вежа, я Лис, вчора біля Сараю бачили танк, прийом.", "Ромашка"),
])
def test_negation_and_hearsay_move_nobody_and_plot_no_enemy(first, second, stays):
    tracker, _, t = run([first, second])
    assert list(where(tracker, t).values()) == [stays] and contacts(tracker, t) == []


def test_a_watching_word_alone_is_not_a_contact():
    tracker, out, t = run(["Башня, я Лис, полтораста метров западнее Сарая, наблюдаю, приём."])
    assert contacts(tracker, t) == [] and len(out[0]) == 1
    assert out[0][0]["anchor"] == "Сарай" and out[0][0]["parsed"]["relation"] == "west_of"


def test_a_sighting_with_no_place_of_its_own_is_where_the_speaker_is():
    tracker, out, t = run(["Вежа, я Лис, на Орієнтирі три, міну бачу, обходжу, прийом."])
    mine = contacts(tracker, t)
    assert len(mine) == 1 and mine[0]["contact"]["what"] == "ied" and mine[0]["ok"]
    assert where(tracker, t) == {"лис": "Орієнтир 3"}


def test_offset_said_after_the_place_is_kept():
    _, out, _ = run(["Вежа, я Граніт, стою возле Сарая, метрів п'ятдесят на північ, прийом."])
    p = out[0][0]["parsed"]
    assert out[0][0]["anchor"] == "Сарай" and p["relation"] == "north_of" and p["distance_m"] == 50


def test_clock_method_gives_a_ring_not_a_point():
    tracker, out, t = run(["Вежа, я Лис, на Ромашці, прийом.",
                           "Вежа, я Лис, ждун на дванадцяту годину, двісті метрів, прийом."])
    drone = out[1][0]
    assert drone["type"] == "contact" and drone["ok"] and drone["anchor"] == "лис"
    assert drone["parsed"]["relation"] == "from" and drone["parsed"]["distance_m"] == 200
    assert where(tracker, t) == {"лис": "Ромашка"}
    _, out, _ = run(["Вежа, я Лис, на третій годині від мене Сарай, метрів сто, прийом."])
    assert out[0][0]["anchor"] == "Сарай" and out[0][0]["parsed"]["relation"] == "from" and out[0][0]["parsed"]["distance_m"] == 100


@pytest.mark.parametrize("line", ["Вежа, я Лис, наша пташка над Ромашкою, прийом.",
                                  "Zero, this is Alpha two, our drone over the town hall, over"])
def test_our_own_drone_is_friendly_and_warns_nobody(line):
    tracker, out, t = run(["Вежа, я Сокіл, на Ромашці, прийом.", "Zero, this is Bravo one, at the town hall, over", line])
    c = out[2][0]
    assert c["contact"]["side"] == "friendly" and c["threats"] == []


def test_a_distance_from_our_position_does_not_make_the_enemy_friendly():
    _, out, _ = run(["Zero, this is Alpha two, at the town hall, over",
                     "Zero, this is Alpha two, contact, enemy tank 300 metres east of our position, over"])
    assert out[1][0]["contact"]["side"] == "hostile"
