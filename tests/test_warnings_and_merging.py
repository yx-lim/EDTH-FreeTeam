"""Three things the demo depends on: a waiting FPV or a mine warns the unit that walks up to it even though nobody
said "enemy"; two contacts at two places are two contacts; a thing that does not move is not merged across distance."""
import asyncio

import pytest

from backend.geo import Gazetteer
from backend.tracker import Tracker


@pytest.fixture(autouse=True)
def rules_only(monkeypatch):
    for key in ("GEMINI_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def run(lines, step=20):
    async def go():
        tracker, t, out = Tracker(Gazetteer(), log=None), 1e6, []
        for line in lines:
            out += await tracker.ingest(line, None, now=t)
            t += step
        return tracker, out, t
    return asyncio.run(go())


def contacts_live(tracker, t):
    return [e for e in tracker.picture(now=t) if e.get("type") == "contact"]


@pytest.mark.parametrize("threat", ["ждун біля Сараю", "міна біля Сараю"])
def test_unit_walking_onto_unmarked_threat_is_warned(threat):
    _, events, _ = run([f"Вежа, я Лис, {threat}, прийом.", "Вежа, я Сокіл, вийшов на Сарай, прийом."])
    assert [w["callsign"] for w in events[-1]["threats"]] == ["сокіл"]


def test_threat_reported_on_top_of_a_unit_warns_it():
    _, events, _ = run(["Вежа, я Сокіл, на Сараї, прийом.", "Вежа, я Лис, ждун біля Сараю, прийом."])
    assert "сокіл" in [w["callsign"] for w in events[-1]["threats"]]


def test_unidentified_vehicles_and_civilians_do_not_warn():
    _, events, _ = run(["Zero, this is Alpha two, at the town hall, over",
                        "Zero, this is Delta one, I see three vehicles near the town hall, over",
                        "Zero, this is Delta one, civilians near the town hall, over"])
    assert events[1]["threats"] == [] and events[2]["threats"] == []


def test_two_tanks_at_two_places_are_two_tanks():
    tracker, _, t = run(["Zero, this is Bravo one, contact, enemy tank at the Odeon theatre, over",
                         "Zero, this is Alpha two, contact, enemy tank at the Saint-Sulpice church, over"], step=60)
    assert len(contacts_live(tracker, t)) == 2


def test_same_tank_seen_by_two_units_is_still_one():
    tracker, _, t = run(["Zero, this is Charlie one, contact, two enemy tanks, moving north, at the Saint-Sulpice church, over",
                         "Zero, this is Bravo one, contact, enemy tank near the Saint-Sulpice church, over"])
    assert len(contacts_live(tracker, t)) == 1


def test_two_waiting_fpvs_150_m_apart_are_two():
    tracker, _, t = run(["Вежа, я Лис, ждун сто метрів на захід від Сараю, прийом.",
                         "Вежа, я Сокіл, ждун п'ятдесят метрів на схід від Сараю, прийом."])
    assert len(contacts_live(tracker, t)) == 2


def test_same_waiting_fpv_reported_twice_is_one():
    tracker, _, t = run(["Вежа, я Лис, ждун біля Сараю, прийом.", "Вежа, я Сокіл, ждун біля Сараю, прийом."])
    assert len(contacts_live(tracker, t)) == 1
