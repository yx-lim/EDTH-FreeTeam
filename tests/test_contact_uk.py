"""Ukrainian/Russian contact reports: drone slang, counts, headings, and how sightings join tracks."""
import json
from pathlib import Path

import pytest

from backend.extract import stub_extract
from backend.geo import Gazetteer
from tests.test_net import run

gaz = Gazetteer()
DEMO_UK = Path(__file__).resolve().parent.parent / "data" / "demo_net_uk.jsonl"


def contact(text):
    [r] = [r for r in stub_extract(text)["reports"] if r["type"] == "contact"]
    return r


@pytest.mark.parametrize("text, what, detail, side, count, heading, place, relation", [
    ("Вежа, я Граніт, ждун біля Сараю, метрів п'ятдесят на захід, не підходити, прийом.",
     "drone", "FPV waiting on the ground", "unknown", None, None, "Сарай", "west_of"),
    ("Вежа, я Сокіл, пташка над Ромашкою, йде на схід, прийом.", "drone", "drone", "unknown", None, "east", "Ромашка", "at"),
    ("Вежа, я Лис, мопед пройшов над Люксембурзьким палацом на захід, прийом.",
     "drone", "Shahed", "hostile", None, "west", "Palais du Luxembourg", "at"),
    ("Вежа, я Сокіл, бачу трьох на схід від Сараю, рухаються на південь, прийом.",
     "infantry", "group of people", "unknown", 3, "south", "Сарай", "east_of"),
    ("Вежа, я Сокіл, ворожий танк двісті метрів на північ від Ромашки, прийом.",
     "tank", "tank", "hostile", None, None, "Ромашка", "north_of"),
    ("Башня, я Сокол, два мавика возле Сарая, приём.", "drone", "Mavic recon quad", "unknown", 2, None, "Сарай", "near"),
    ("Вежа, я Сокіл, міна на стежці біля другої посадки, прийом.", "ied", "mine", "unknown", None, None, "Друга посадка", "near"),
])
def test_contact_fields(text, what, detail, side, count, heading, place, relation):
    r = contact(text)
    c = r["contact"]
    assert (c["what"], c["detail"], c["side"], c["count"], c["heading"]) == (what, detail, side, count, heading)
    assert (gaz.find(r["anchor"]["name"])[0].name, r["relation"]) == (place, relation)


def test_lifetimes_follow_the_type():
    assert contact("Вежа, я Лис, фпв біля Сараю, прийом.")["contact"]["ttl_s"] == 90
    assert contact("Вежа, я Граніт, ждун біля Сараю, прийом.")["contact"]["ttl_s"] == 1800
    assert contact("Вежа, я Сокіл, міна біля Сараю, прийом.")["contact"]["ttl_s"] == 21600


def test_overhead_is_the_reporter():
    r = contact("Вежа, я Лис, фпв над нами, прийом.")
    assert r["anchor"] == {"name": "лис", "kind": "unit"} and r["relative_to_reporter"]


def test_own_position_and_sighting_in_one_call():
    got = stub_extract("Башня, я Гранит, на Сарае, вижу двоих, приём.")["reports"]
    assert [r["type"] for r in got] == ["contact", "position"] and got[0]["contact"]["count"] == 2


def test_demo_net_tracks():
    script = [(d["t"], d["text"]) for d in map(json.loads, DEMO_UK.read_text(encoding="utf-8").splitlines())]
    net, txs = run(script)
    ev = {e["id"]: e for e in net.tracker.events}
    contacts = [e for e in ev.values() if e["type"] == "contact"]
    ambush = [e for e in contacts if e["callsign"] == "contact 1"]
    # Граніт and Сокіл both saw the waiting drone: one track, corroborated. Вежа relaying it is not a third witness.
    assert ambush[-1]["seen_by"] == ["граніт", "сокіл", "вежа"] and ambush[-1]["corroborated"]
    # "ще один ждун": a second drone, never merged into the first
    assert any(e["callsign"] == "contact 2" and e["contact"]["another"] for e in contacts)
    # the Shahed flying west is not the bird flying east half a minute earlier
    shahed = next(e for e in contacts if e["contact"]["detail"] == "Shahed")
    bird = next(e for e in contacts if e["contact"]["detail"] == "drone")
    assert shahed["callsign"] != bird["callsign"] and shahed["contact"]["side"] == "hostile"
    # three enemy 200 m east of Ромашка: Сокіл, who reported from Ромашка, is warned
    enemy = next(e for e in contacts if e["contact"]["what"] == "infantry")
    assert enemy["contact"]["side"] == "hostile" and [w["callsign"] for w in enemy["threats"]] == ["сокіл"]


def test_relay_alone_does_not_corroborate():
    net, _ = run([(0, "Вежа, я Граніт, ждун біля Сараю, прийом."), (10, "Всім, я Вежа, ждун біля Сараю, прийом.")])
    last = [e for e in net.tracker.events if e["type"] == "contact"][-1]
    assert last["seen_by"] == ["граніт", "вежа"] and not last["corroborated"]
