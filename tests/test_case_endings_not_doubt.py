"""A codename in another grammatical case is the same codename, not a mishearing: no "sounds alike; confirm"."""
import asyncio

import pytest

from backend.geo import Gazetteer
from backend.tracker import Tracker


@pytest.mark.parametrize("line, anchor", [
    ("Вежа, я Сокіл, на Ромашці, прийом.", "Ромашка"),
    ("Вежа, я Лис, на Орієнтирі три, прийом.", "Орієнтир 3"),
    ("Вежа, я Граніт, біля другої посадки, прийом.", "Друга посадка"),
    ("Башня, я Лис, возле второй посадки, приём.", "Друга посадка"),
])
def test_inflected_codename_is_not_flagged(monkeypatch, line, anchor):
    for key in ("GEMINI_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    e = asyncio.run(Tracker(Gazetteer(), log=None).ingest(line, None, now=1e6))[0]
    assert e["ok"] and e["anchor"] == anchor and not e["ambiguous"] and "sounds alike" not in (e.get("note") or "")
