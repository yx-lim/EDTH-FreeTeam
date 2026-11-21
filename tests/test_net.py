"""Radio-net mode: who is speaking, to whom, what kind of transmission, and what it does to the picture."""
import asyncio
import json
from pathlib import Path

from backend.geo import Gazetteer
from backend.net import Net, ended, split
from backend.tracker import Tracker

gaz = Gazetteer()
DEMO = Path(__file__).resolve().parent.parent / "data" / "demo_net.jsonl"


def run(script, log=None):
    """script: [(seconds, text)]. Returns the net and every transmission in order."""
    tracker = Tracker(gaz)
    net = Net(tracker, log=log)

    async def go():
        txs = []
        for when, text in script:
            txs += (await net.hear(text, now=1000 + when))["transmissions"]
        return txs
    return net, asyncio.run(go())


def events(net, tx):
    return [net.tracker.get(i) for i in tx["events"]]


def test_demo_net_attribution():
    script = [(d["t"], d["text"]) for d in map(json.loads, DEMO.read_text().splitlines())]
    net, txs = run(script)
    got = [(tx["from"], tx["to"], tx["kind"]) for tx in txs]
    assert got == [
        ("zero", "all stations", "radio_check"), ("alpha 1", "zero", "radio_check"), ("bravo 2", "zero", "radio_check"),
        ("zero", "alpha 1", "request"), ("alpha 1", "zero", "report"), ("zero", "alpha 1", "ack"),
        ("zero", "bravo 2", "request"), ("bravo 2", "zero", "report"), ("zero", "bravo 2", "say_again"),
        ("bravo 2", "zero", "report"), ("zero", "bravo 2", "ack"),
        ("zero", "charlie 1", "order"), ("charlie 1", "zero", "ack"),
        ("alpha 1", "zero", "report"), ("zero", "alpha 1", "ack"),
        ("bravo 2", "zero", "report"), ("zero", "bravo 2", "ack"),
        ("charlie 1", "zero", "report"), ("zero", "charlie 1", "ack"),
        ("zero", "alpha 2", "request"), ("alpha 2", "zero", "report"), ("zero", "alpha 2", "ack"),
        (None, None, "report"), ("zero", "all stations", "order"),
    ]
    plotted = {e["callsign"] for e in net.tracker.events if e["ok"]}
    assert plotted == {"alpha 1", "bravo 2", "charlie 1", "delta 1", "alpha 2"}   # never Zero, never a guess


def test_header_less_reply_belongs_to_the_station_called():
    net, txs = run([(0, "Alpha one, this is Zero, send position, over."), (4, "At the Saint-Sulpice fountain, over.")])
    assert txs[1]["from"] == "alpha 1" and events(net, txs[1])[0]["anchor"] == "Fontaine des Quatre Évêques"


def test_own_callsign_on_a_report_but_called_station_on_a_request():
    _, txs = run([(0, "Bravo one, at the Saint Germain market, over.")])
    assert (txs[0]["from"], txs[0]["to"]) == ("bravo 1", None)
    _, txs = run([(0, "Bravo one, send position, over.")])
    assert (txs[0]["from"], txs[0]["to"]) == ("zero", "bravo 1")


def test_unidentified_report_is_logged_not_plotted():
    net, txs = run([(0, "Near the Odeon theatre, over.")])
    assert txs[0]["from"] is None and not txs[0]["events"] and "not identified" in txs[0]["note"]
    assert not net.tracker.events


def test_control_never_gets_a_position_but_relayed_reports_count():
    net, txs = run([(0, "All stations, this is Zero, I am at the town hall, over."),
                    (10, "Alpha two, this is Zero, Bravo one reports he's at the Odeon theatre, over.")])
    assert not txs[0]["events"] and "control" in txs[0]["note"]
    e = events(net, txs[1])[0]
    assert e["callsign"] == "bravo 1" and e["speaker"] == "zero" and e["anchor"].startswith("Odéon")


def test_both_acknowledgement_styles_tick_the_report():
    for ack in ("Roger, out.", "Zero, roger, out.", "Alpha one, roger, out."):
        net, txs = run([(0, "Zero, this is Alpha one, at the Medici fountain, over."), (5, ack)])
        assert (txs[1]["from"], txs[1]["to"], txs[1]["kind"]) == ("zero", "alpha 1", "ack"), ack
        assert events(net, txs[0])[0]["acked_by"] == "zero"


def test_say_again_then_repeat_replaces_the_queried_fix():
    net, txs = run([(0, "Zero, this is Bravo two, south of the town hall, over."), (5, "Bravo two, say again, over."),
                    (10, "Bravo two, I say again, one hundred metres north of the town hall, over.")])
    first, repeat = events(net, txs[0])[0], events(net, txs[2])[0]
    assert first["queried_by"] == "zero" and first["superseded"] and repeat["corrects"] == first["id"]
    assert [e["callsign"] for e in net.tracker.events if e["ok"] and not e["superseded"]] == ["bravo 2"]


def test_order_draws_the_destination_and_closes_on_arrival():
    net, txs = run([(0, "Charlie one, this is Zero, move to the Medici fountain, over."), (4, "Wilco, out."),
                    (90, "Zero, this is Charlie one, at the Medici fountain, over.")])
    order = events(net, txs[0])[0]
    assert order["type"] == "order" and order["target"]["anchor"] == "Fontaine Médicis" and not order["ok"]
    assert order["acked_by"] == "charlie 1" and order["reached"]["event"] == txs[2]["events"][0]


def test_order_to_an_unknown_place_is_flagged():
    net, txs = run([(0, "Charlie one, this is Zero, move to the banana tower, over.")])
    order = events(net, txs[0])[0]
    assert "unresolved" in order["note"] and "target" not in order


def test_vad_split_without_over_is_one_speaker():
    _, txs = run([(0, "Zero, this is Delta two, at the Saint Germain market"), (1.5, "heading to rue de Rennes, over.")])
    assert txs[1]["from"] == "delta 2" and "continues" in txs[1]["how"]


def test_two_transmissions_in_one_segment_are_split():
    assert split("Alpha one, this is Zero, send position, over. Alpha one, at the church, over.") == [
        "Alpha one, this is Zero, send position, over.", "Alpha one, at the church, over."]
    assert split("Moving over the bridge, over") == ["Moving over the bridge, over"]
    _, txs = run([(0, "Alpha one, this is Zero, send position, over. At the Saint-Sulpice fountain, over.")])
    assert [(t["from"], t["kind"]) for t in txs] == [("zero", "request"), ("alpha 1", "report")]


def test_prowords():
    assert ended("Zero, roger, out.") == "out" and ended("Reçu, terminé.") == "out"
    assert ended("at the fountain, over") == "over" and ended("Alpha deux, à vous") == "over"
    assert ended("moving out of the church") is None


def test_net_log_survives_a_restart(tmp_path):
    log = tmp_path / "net.jsonl"
    run([(0, "Alpha one, this is Zero, send position, over."), (4, "At the Saint-Sulpice fountain, over.")], log=log)
    again = Net(Tracker(gaz), log=log)
    assert [t["from"] for t in again.transmissions] == ["zero", "alpha 1"]
