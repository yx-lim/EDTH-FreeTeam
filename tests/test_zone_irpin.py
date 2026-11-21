"""The Irpin zone (data/zones/irpin/): Ukrainian OSM names, inflected and Russian forms, Latin spellings, and the
zone's tuning set end to end with the offline rules. Loaded by path, so the rest of the suite stays on Paris."""
import asyncio
import json

import pytest
from shapely.geometry import Point

from backend.geo import DATA, Gazetteer
from backend.resolver import resolve
from backend.tracker import Tracker

ZONE = DATA / "zones" / "irpin"
gaz = Gazetteer(ZONE / "gazetteer.json", aliases=ZONE / "aliases.json", custom=ZONE / "no_custom_places.json",
                codenames=ZONE / "codenames.json")


@pytest.mark.parametrize("spoken, place", [
    ("на вокзалі", "Ірпінь"),                                   # alias, locative case
    ("Центрального ринку", "Центральний ринок"),                # genitive
    ("на Соборній", "Соборна вулиця"),                          # street said without "вулиця"
    ("улица Шевченко", "вулиця Шевченка"),                      # Russian street word and spelling
    ("Парку Перемоги", "Парк Перемоги"),
    ("Soborna street", "Соборна вулиця"),                       # English report, Latin letters
    ("central market", "Центральний ринок"),
    ("Сараю", "Сарай"),                                         # the zone's codenames
])
def test_names(spoken, place):
    assert gaz.find(spoken)[0].name == place


def test_misspelt_name_is_matched_and_flagged():
    res = resolve({"anchor": {"name": "Цетрального ринку", "kind": "landmark"}, "relation": "near"}, gaz)
    assert res["ok"] and res["anchor"] == "Центральний ринок"


def test_unknown_place_in_another_city_is_not_plotted():
    assert gaz.find("Хрещатика") == [] and gaz.find("Майдану Незалежності") == []


def test_corner_prefers_the_street():
    res = resolve({"anchor": {"name": "Центральної", "kind": "landmark"},
                   "anchor2": {"name": "Котляревського", "kind": "landmark"}, "relation": "intersection"}, gaz)
    assert res["ok"] and res["anchor"] == "Центральна вулиця × вулиця Котляревського"


def test_tuning_set_with_offline_rules():
    """Every turn of data/zones/irpin/stress_uk.jsonl: plot or not, callsign, and truth inside the region."""
    rows = [json.loads(line) for line in (ZONE / "stress_uk.jsonl").read_text(encoding="utf-8").splitlines()]
    scenarios: dict[str, list] = {}
    for r in rows:
        scenarios.setdefault(r["scenario"], []).append(r)
    misses = []

    async def run():
        for turns in scenarios.values():
            tracker = Tracker(gaz)
            for row in turns:
                events = await tracker.ingest(row["text"], now=row["t"])
                plotted = {e["callsign"] for e in events if e["ok"]}
                if bool(plotted) != row["expect"]["plot"] or (row["expect"]["plot"] and plotted != set(row["expect"]["callsigns"])):
                    misses.append((row["id"], plotted))
                    continue
                for cs, truth in row["truth"].items():
                    if not tracker.units()[cs].buffer(5).contains(gaz.proj.to_xy(Point(truth["lon"], truth["lat"]))):
                        misses.append((row["id"], "truth outside"))
    asyncio.run(run())
    assert not misses
