"""The battle replay (data/demo_net_battle.jsonl) tells the story the demo needs, end to end, with rules only."""
import asyncio
import json
from pathlib import Path

from backend.geo import Gazetteer
from backend.net import Net
from backend.tracker import Tracker

SCRIPT = Path(__file__).resolve().parent.parent / "data" / "demo_net_battle.jsonl"


def test_battle_replay(monkeypatch):
    for key in ("GEMINI_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    async def go():
        tracker = Tracker(Gazetteer(), log=None)
        net, events, t = Net(tracker, log=None), [], 0
        for s in SCRIPT.read_text(encoding="utf-8").splitlines():
            line = json.loads(s)
            t = 1e6 + line["t"]
            events += (await net.hear(line["text"], now=t, source="radio-text"))["events"]
        return tracker, events, t
    tracker, events, t = asyncio.run(go())
    picture = tracker.picture(now=t)
    units = {e["callsign"]: e["anchor"] for e in picture if e.get("type") != "contact"}
    seen = sorted((e["contact"].get("detail") or e["contact"]["what"]) for e in picture if e.get("type") == "contact")
    assert units == {"сокіл": "Ромашка", "граніт": "Сарай", "лис": "Орієнтир 3"}
    assert seen.count("FPV waiting on the ground") == 2 and "bridge destroyed" in seen and "mine" in seen
    assert "road blocked" not in seen                                   # reported, then reopened
    assert not any("sounds alike" in (e.get("note") or "") and e["callsign"] != "contact 6" for e in events)
    arrived = next(e for e in events if e["callsign"] == "лис" and e.get("anchor") == "Орієнтир 3" and e.get("ok"))
    assert [w["contact"]["what"] for w in arrived["threats"]] == ["ied"]   # walked onto the reported mine: warned
    bridge = [e for e in events if (e.get("contact") or {}).get("detail") == "bridge destroyed"]
    assert bridge[1]["corroborated"]                                      # two stations saw it
