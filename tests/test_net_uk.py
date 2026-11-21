"""Radio-net mode in Ukrainian and Russian: procedure words, Ukrainian/Russian spellings of one callsign."""
import json
from pathlib import Path

from backend.net import ended, split
from tests.test_net import run

DEMO_UK = Path(__file__).resolve().parent.parent / "data" / "demo_net_uk.jsonl"


def test_ukrainian_demo_net_attribution():
    script = [(d["t"], d["text"]) for d in map(json.loads, DEMO_UK.read_text(encoding="utf-8").splitlines())]
    net, txs = run(script)
    got = [(tx["from"], tx["to"], tx["kind"]) for tx in txs]
    assert got == [
        ("вежа", "all stations", "radio_check"), ("сокіл", "вежа", "radio_check"), ("вежа", "сокіл", "request"),
        ("сокіл", "вежа", "report"), ("вежа", "сокіл", "ack"),
        ("граніт", "вежа", "report"), ("вежа", "граніт", "ack"), ("граніт", "вежа", "report"),
        ("лис", "вежа", "report"), ("вежа", "лис", "order"), ("лис", "вежа", "ack"),
        ("лис", "вежа", "report"), ("граніт", "вежа", "report"),
        # sightings (tests/test_contact_uk.py checks the tracks)
        ("граніт", "вежа", "report"), ("вежа", "граніт", "ack"), ("сокіл", "вежа", "report"), ("вежа", "all stations", "report"),
        ("граніт", "вежа", "report"), ("лис", "вежа", "report"), ("сокіл", "вежа", "report"), ("лис", "вежа", "report"),
    ]
    units = net.tracker.units()
    assert set(units) == {"сокіл", "граніт", "лис"}          # Вежа (control) is never plotted
    reply = txs[3]
    assert reply["how"].startswith("reply to")              # "На Ромашці, без змін" has no callsign: Сокіл answering
    order = net.tracker.get(txs[9]["events"][0])
    assert order["note"] == "tasked: move to Орієнтир 3" and order.get("reached")


def test_correction_withdraws_the_fix():
    net, txs = run([(0, "Вежа, я Граніт, сто метрів на схід від Сараю, прийом."),
                    (20, "Вежа, я Граніт, мінус, мінус, не на схід. Сто метрів на південь від Сараю, прийом.")])
    first, second = (net.tracker.get(tx["events"][0]) for tx in txs)
    assert second["type"] == "correction" and first["superseded"]


def test_russian_spelling_is_the_same_unit():
    net, _ = run([(0, "Вежа, я Граніт, на Сараї, прийом."), (60, "Башня, я Гранит, на Ромашке, приём.")])
    assert list(net.tracker.units()) == ["граніт"]


def test_procedure_words():
    assert ended("Вежа, я Лис, прийом.") == "over"
    assert ended("Башня, я Гранит, приём") == "over"
    assert ended("Плюс, кінець зв'язку.") == "out"
    assert split("Сокіл, я Вежа, доповідай позицію, прийом. Вежа, я Сокіл, на Ромашці, прийом.") == [
        "Сокіл, я Вежа, доповідай позицію, прийом.", "Вежа, я Сокіл, на Ромашці, прийом."]
