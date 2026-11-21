"""Score the pipeline on tests/utterances.jsonl.

    python -m scripts.evaluate            # from the repo root

Each line: {"text": ..., "lat": ..., "lon": ...} with a hand-marked ground-truth point.
Reports resolution rate, median centre error, and containment (truth inside the region).
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path

from dotenv import load_dotenv
from shapely.geometry import Point, shape

load_dotenv()

from backend.geo import Gazetteer  # noqa: E402
from backend.tracker import Tracker  # noqa: E402

CASES = Path(__file__).resolve().parent.parent / "tests" / "utterances.jsonl"


async def main() -> None:
    gaz = Gazetteer()
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors, contained, latencies, failed = [], 0, [], []
    for case in cases:
        t0 = time.time()
        tracker = Tracker(gaz)                      # each case starts with no history
        events = await tracker.ingest(case["text"], now=0)
        latencies.append((time.time() - t0) * 1000)
        result = next((e for e in events if e["ok"]), events[0])
        if not result["ok"]:
            failed.append((case["text"], result["note"]))
            continue
        truth = gaz.proj.to_xy(Point(case["lon"], case["lat"]))
        region = gaz.proj.to_xy(shape(result["region"]))
        errors.append(truth.distance(region.centroid))
        contained += region.buffer(1).contains(truth)

    n = len(cases)
    print(f"cases               {n}")
    print(f"resolved            {len(errors)}/{n}")
    if errors:
        print(f"median error        {statistics.median(errors):.1f} m")
        print(f"truth inside region {contained}/{len(errors)}")
    print(f"median latency      {statistics.median(latencies):.0f} ms (text in -> region out, no speech-to-text)")
    for text, note in failed:
        print(f"  FAILED: {text!r} -> {note}")


if __name__ == "__main__":
    asyncio.run(main())
