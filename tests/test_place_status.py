"""The state of a place: "the bridge is destroyed", "міст знищено, проїзду нема", "road reopened". It is plotted like a
persistent hazard, updated when the state changes, and taken off the map when someone reports it open again."""
import asyncio

import pytest

from backend.geo import Gazetteer
from backend.tracker import Tracker


@pytest.fixture(autouse=True)
def rules_only(monkeypatch):
    for key in ("GEMINI_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def run(lines, step=30):
    async def go():
        tracker, t, out = Tracker(Gazetteer(), log=None), 1e6, []
        for line in lines:
            out += await tracker.ingest(line, None, now=t)
            t += step
        return tracker, out, t
    return asyncio.run(go())


def obstacles(tracker, t):
    return [e["contact"]["detail"] for e in tracker.picture(now=t) if (e.get("contact") or {}).get("what") == "obstacle"]


@pytest.mark.parametrize("line, anchor, detail", [
    ("Вежа, я Лис, міст біля Ромашки знищено, проїзду нема, прийом.", "Ромашка", "bridge destroyed"),
    ("Вежа, я Граніт, дорога біля Сараю перекрита, завал, прийом.", "Сарай", "road blocked"),
    ("Башня, я Гранит, мост возле Сарая взорван, приём.", "Сарай", "bridge destroyed"),
    ("Zero, this is Bravo one, the bridge near the Odeon theatre is destroyed, no passage, over",
     "Odéon–Théâtre de l'Europe", "bridge destroyed"),
    ("Zero, this is Alpha two, road blocked at the Saint-Sulpice church, over", "Église Saint-Sulpice", "road blocked"),
    ("Zero, this is Delta one, building damaged south of the town hall, over", "Mairie du 6e arrondissement",
     "building damaged"),
])
def test_place_state_is_plotted_where_it_is(line, anchor, detail):
    _, events, _ = run([line])
    e = events[0]
    assert e["type"] == "contact" and e["ok"] and e["anchor"] == anchor
    assert e["contact"]["what"] == "obstacle" and e["contact"]["detail"] == detail and e["contact"]["side"] == "unknown"
    assert len(events) == 1   # the reporter's own position is not moved to the bridge


def test_state_change_updates_one_marker():
    tracker, events, t = run(["Вежа, я Лис, міст біля Ромашки пошкоджено, прийом.",
                              "Вежа, я Сокіл, міст біля Ромашки знищено, прийом."])
    assert obstacles(tracker, t) == ["bridge destroyed"] and events[1]["merged_with"] == events[0]["id"]
    assert events[1]["corroborated"]   # two stations


def test_it_stays_for_a_day_and_never_warns_as_a_threat():
    tracker, events, t = run(["Вежа, я Лис, міст біля Ромашки знищено, прийом.", "Вежа, я Сокіл, на Ромашці, прийом."])
    assert events[1]["threats"] == [] and obstacles(tracker, t + 20 * 3600) == ["bridge destroyed"]


@pytest.mark.parametrize("down, up", [
    ("Вежа, я Лис, міст біля Ромашки знищено, прийом.", "Вежа, я Лис, міст біля Ромашки відновлено, проїзд відкрито, прийом."),
    ("Zero, this is Alpha two, road blocked at the Saint-Sulpice church, over",
     "Zero, this is Alpha two, road at the Saint-Sulpice church reopened, over"),
])
def test_reopened_takes_it_off_the_map(down, up):
    tracker, events, t = run([down, up])
    assert events[1]["cleared"] and events[1]["callsign"] == events[0]["callsign"] and obstacles(tracker, t) == []


def test_rejecting_the_reopened_report_puts_it_back():
    tracker, events, t = run(["Zero, this is Alpha two, road blocked at the Saint-Sulpice church, over",
                              "Zero, this is Alpha two, road at the Saint-Sulpice church reopened, over"])
    tracker.reject(events[1]["id"])
    assert obstacles(tracker, t) == ["road blocked"]


def test_reopened_with_nothing_on_record_is_not_plotted():
    tracker, events, t = run(["Zero, this is Alpha two, road at the Saint-Sulpice church reopened, over"])
    assert not events[0]["ok"] and obstacles(tracker, t) == []


def test_a_destroyed_tank_is_still_a_tank_and_all_clear_is_not_an_obstacle():
    _, events, _ = run(["Zero, this is Bravo one, contact, enemy tank destroyed at the Odeon theatre, over",
                        "Zero, this is Bravo one, all clear at the Medici fountain, over"])
    assert events[0]["contact"]["what"] == "tank" and events[1]["type"] == "position"


@pytest.mark.parametrize("line", ["Башня, я Лис, перекресток возле Сарая, приём.", "Вежа, я Лис, перехрестя біля Сараю, прийом."])
def test_a_crossroads_is_not_a_blocked_road(line):
    """"перекресток" must not be taken for "перекрыт": state words are matched strictly."""
    _, events, _ = run([line])
    assert [e["type"] for e in events] == ["position"] and events[0]["anchor"] == "Сарай"
