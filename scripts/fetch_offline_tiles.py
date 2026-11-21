"""Download a compact offline raster tile pack for Paris & surrounding demo sectors.

Uses Esri World Topo Map tiles saved into data/offline_tiles/{z}/{x}/{y}.jpg and served
locally by FastAPI at /tiles/{z}/{x}/{y}.jpg (rendered dark-inverted by MapLibre so
OFFLINE mode looks crisp and identical to DARK OPS with zero internet).

Usage:
    .venv/bin/python scripts/fetch_offline_tiles.py
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "data" / "offline_tiles"
UA = "EDTH-FreeTeam-OfflineTileCache/1.0 (local hackathon demo)"

# Compact zoom bands covering Paris & surrounding areas:
# - z12..z14: wider Paris metro (Eiffel Tower, Arc de Triomphe, Sacre-Coeur, Bastille, Montparnasse, La Defense)
# - z15..z16: core demo sector (Eiffel Tower <-> Louvre <-> Notre-Dame <-> Pantheon <-> Montparnasse <-> 6e)
BANDS = [
    (12, 48.80, 2.22, 48.91, 2.43),
    (13, 48.81, 2.24, 48.90, 2.41),
    (14, 48.825, 2.275, 48.885, 2.385),
    (15, 48.834, 2.286, 48.870, 2.365),
    (16, 48.842, 2.318, 48.860, 2.354),
]


def deg2tile(lat: float, lon: float, z: int) -> tuple[int, int]:
    lat_r = math.radians(lat)
    n = 2.0 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def main() -> None:
    jobs: list[tuple[int, int, int]] = []
    for z, lat_min, lon_min, lat_max, lon_max in BANDS:
        x0, y0 = deg2tile(lat_max, lon_min, z)
        x1, y1 = deg2tile(lat_min, lon_max, z)
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                jobs.append((z, x, y))

    print(f"Paris offline tile pack: {len(jobs)} tiles across z12-z16 -> {OUT}")
    downloaded = 0
    skipped = 0
    failed = 0
    with httpx.Client(timeout=15.0, headers={"User-Agent": UA}) as client:
        for i, (z, x, y) in enumerate(jobs, 1):
            p = OUT / str(z) / str(x) / f"{y}.jpg"
            if p.exists() and p.stat().st_size > 1000:
                skipped += 1
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}"
            try:
                r = client.get(url)
                if r.status_code == 200 and len(r.content) > 1000:
                    p.write_bytes(r.content)
                    downloaded += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
            if i % 40 == 0 or i == len(jobs):
                print(f"  progress {i}/{len(jobs)} (new={downloaded}, cached={skipped}, failed={failed})", flush=True)
            time.sleep(0.03)
    total_mb = sum(f.stat().st_size for f in OUT.rglob("*.jpg")) / (1024 * 1024)
    print(f"Done! {downloaded} downloaded, {skipped} cached, {failed} failed ({total_mb:.1f} MB total)")


if __name__ == "__main__":
    main()
