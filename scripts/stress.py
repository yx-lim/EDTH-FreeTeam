"""Replay the judge stress-test scenarios in tests/stress.jsonl and score them.

    python -m scripts.stress              # Mistral extraction if MISTRAL_API_KEY is set, else the rules extractor
    python -m scripts.stress --offline    # force the rules extractor
    python -m scripts.stress --all        # also list turns that passed
    python -m scripts.stress --holdout    # score tests/stress_holdout.jsonl instead; failing turns stay hidden

tests/stress.jsonl was used to tune the backend, so its scores are training scores.
tests/stress_holdout.jsonl was written after tuning and has not been tuned on. Keep it that way: read only
its summary table. If you look at its failing turns (--holdout --all) and fix them, move those turns to
tests/stress.jsonl and write new held-out ones.

Each line of either file is one spoken turn:
  id, scenario, category, t (seconds since the scenario started), text,
  expect: {plot, callsigns, type, relation, anchor: [acceptable OSM names] or null, ambiguous,
           supersedes (optional): id of the turn this one corrects},
  truth: {callsign: {lat, lon, where}}  where each unit actually is after this turn,
  truth_alt (optional): an equally valid reading, for open conventions,
  naive: what a plain "geocode the noun" pipeline does, note (optional), truth_source.

Every scenario starts from an empty map. Two systems are scored on the same transcripts:
  current  backend.tracker.Tracker: one tracker per scenario, ingest(text, now=t), each unit's
           position read back from tracker.units()
  naive    extract() reports, then the first gazetteer match for each report's anchor pinned at its
           centre with a 25 m radius; ignores report type, relation, distance, second anchor and history.
           It shares the gazetteer's aliases and fuzzy matching, so the gap measures the resolver and
           the history, not name lookup. It cannot pin places outside the district (T4a), as a global
           geocoder would.
The anchor and ambiguity checks apply to the first expected callsign of a turn.
"Region size" is the radius of a circle with the same area as the plotted region: a huge region contains
the truth easily, so read "truth inside" together with it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import statistics
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from shapely.geometry import Point

load_dotenv()

from backend.extract import extract  # noqa: E402
from backend.geo import Gazetteer  # noqa: E402
from backend.tracker import Tracker  # noqa: E402

TESTS = Path(__file__).resolve().parent.parent / "tests"
CASES = TESTS / "stress.jsonl"
HOLDOUT = TESTS / "stress_holdout.jsonl"
PIN_M = 25.0


def load(path: Path) -> dict[str, list[dict]]:
    scenarios: dict[str, list[dict]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            scenarios.setdefault(row["scenario"], []).append(row)
    return scenarios


def current(events: list[dict], tracker: Tracker, first: str | None) -> dict:
    units = tracker.units()
    ok = [e for e in events if e["ok"]]
    main = next((e for e in ok if e["callsign"] == first), ok[0] if ok else None)
    return {"updated": {e["callsign"]: units[e["callsign"]] for e in ok if e["callsign"] in units},
            "anchor": main and main.get("anchor"), "ambiguous": bool(main and main.get("ambiguous")),
            "corrects": main and main.get("corrects"),
            "note": "; ".join(e.get("note") or "" for e in events if not e["ok"]) or "nothing returned"}


def naive(parsed: dict, gaz: Gazetteer) -> dict:
    updated, anchors = {}, {}
    for r in parsed["reports"]:
        name = (r.get("anchor") or {}).get("name")
        cs = r.get("subject") or parsed.get("speaker") or "unit 1"
        if r.get("type") == "other" or not name or cs in updated:
            continue
        hits = gaz.find(name)
        if hits:
            updated[cs] = hits[0].geom.centroid.buffer(PIN_M)
            anchors[cs] = hits[0].name
    first = next(iter(anchors), None)
    return {"updated": updated, "anchor": anchors.get(first), "ambiguous": False, "corrects": None,
            "note": "" if updated else "nothing geocoded"}


def score(row: dict, out: dict, gaz: Gazetteer, event_ids: dict[str, int]) -> dict:
    exp = row["expect"]
    plotted = bool(out["updated"])
    s = {"decision": plotted == exp["plot"], "callsign": None, "anchor": None,
         "inside": [], "errors": [], "radii": [], "reasons": []}
    if not s["decision"]:
        s["reasons"].append("plotted" if plotted else f"not plotted ({out['note']})")
    if exp["plot"]:
        s["callsign"] = set(out["updated"]) == set(exp["callsigns"])
        if not s["callsign"] and plotted:
            s["reasons"].append(f"updated {sorted(out['updated'])}, expected {exp['callsigns']}")
        if exp.get("anchor") and plotted:
            parts = re.split(r" \+ | × ", out["anchor"] or "")   # combined clues, street corners
            s["anchor"] = any(p in exp["anchor"] for p in parts)
            if not s["anchor"]:
                s["reasons"].append(f"anchor {out['anchor']!r}")
        for cs in exp["callsigns"]:
            truths = [row["truth"][cs]] + ([row["truth_alt"][cs]] if cs in row.get("truth_alt", {}) else [])
            pts = [gaz.proj.to_xy(Point(p["lon"], p["lat"])) for p in truths]
            region = out["updated"].get(cs)
            if region is None:
                s["inside"].append(False)
                continue
            inside = any(region.buffer(1).contains(p) for p in pts)
            err = min(region.centroid.distance(p) for p in pts)
            s["inside"].append(inside)
            s["errors"].append(err)
            s["radii"].append(math.sqrt(region.area / math.pi))
            if not inside:
                s["reasons"].append(f"{cs}: truth outside region, centre {err:.0f} m off")
    if exp.get("ambiguous") and plotted and not out["ambiguous"]:
        s["reasons"].append("ambiguity not flagged")
    if exp.get("supersedes") and plotted and out["corrects"] != event_ids.get(exp["supersedes"]):
        s["reasons"].append(f"did not withdraw the fix from {exp['supersedes']}")
    return s


def frac(values: list) -> str:
    vals = [v for v in values if v is not None]
    return f"{sum(vals)}/{len(vals)}" if vals else "-"


def summary(scores: list[dict]) -> dict:
    errors = [e for s in scores for e in s["errors"]]
    radii = [r for s in scores for r in s["radii"]]
    return {
        "decision": frac([s["decision"] for s in scores]),
        "callsign": frac([s["callsign"] for s in scores]),
        "anchor": frac([s["anchor"] for s in scores]),
        "inside": frac([i for s in scores for i in s["inside"]]),
        "error": f"{statistics.median(errors):.0f} m" if errors else "-",
        "radius": f"{statistics.median(radii):.0f} m" if radii else "-",
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use the rules extractor even if a Mistral key is set")
    ap.add_argument("--all", action="store_true", help="list every turn (with --holdout: also reveals its failures)")
    ap.add_argument("--holdout", action="store_true", help="score the held-out set; failing turns stay hidden unless --all")
    args = ap.parse_args()
    if args.offline:
        os.environ.pop("MISTRAL_API_KEY", None)

    path = HOLDOUT if args.holdout else CASES
    scenarios = load(path)
    categories = list(dict.fromkeys(row["category"] for turns in scenarios.values() for row in turns))
    gaz = Gazetteer()
    results: dict[str, dict[str, list]] = {"current": defaultdict(list), "naive": defaultdict(list)}
    lines, extractors = [], set()
    for turns in scenarios.values():
        tracker, event_ids = Tracker(gaz), {}
        for row in turns:
            first = (row["expect"]["callsigns"] or [None])[0]
            events = await tracker.ingest(row["text"], now=row["t"])
            extractors.update(e.get("extractor") or "?" for e in events)
            for e in events:
                if e["callsign"] == first or len(events) == 1:
                    event_ids[row["id"]] = e["id"]
            parsed = await extract(row["text"])
            for system, out in (("current", current(events, tracker, first)), ("naive", naive(parsed, gaz))):
                s = score(row, out, gaz, event_ids)
                results[system][row["category"]].append(s)
                results[system]["all"].append(s)
                if system == "current" and (s["reasons"] or args.all):
                    mark = "FAIL" if s["reasons"] else "ok  "
                    lines.append(f"  {mark} {row['id']:6} {row['text'][:58]:58} {'; '.join(s['reasons'])}")

    print(f"cases: {path.name}{' (held out)' if args.holdout else ' (used for tuning)'}")
    print(f"extractor: {', '.join(sorted(extractors))}")
    print("each cell: current / naive\n")
    head = (f"{'category':9} {'turns':>5}  {'plot decision':>15}  {'callsign':>13}  {'anchor':>13}  "
            f"{'truth inside':>13}  {'median error':>15}  {'region size':>15}")
    print(head)
    print("-" * len(head))
    for cat in categories + ["all"]:
        c, n = summary(results["current"][cat]), summary(results["naive"][cat])
        cells = [f"{c[k]} / {n[k]}" for k in ("decision", "callsign", "anchor", "inside", "error", "radius")]
        print(f"{cat:9} {len(results['current'][cat]):>5}  {cells[0]:>15}  {cells[1]:>13}  {cells[2]:>13}  "
              f"{cells[3]:>13}  {cells[4]:>15}  {cells[5]:>15}")
    failing = sum(1 for line in lines if line.lstrip().startswith("FAIL"))
    if args.holdout and not args.all:
        print(f"\n{failing} failing turn(s) hidden. --all lists them; fix one and it belongs in tests/stress.jsonl.")
        return
    print("\ncurrent pipeline, turn by turn:" if args.all else "\ncurrent pipeline failures:")
    print("\n".join(lines) if lines else "  none")


if __name__ == "__main__":
    asyncio.run(main())
