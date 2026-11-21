"""Which area of operations the app runs on. ZONE=paris (default) uses data/ as before; ZONE=<name> uses
data/zones/<name>/ for its map data, codenames, aliases, demo nets and logs, so two zones never mix.

    ZONE=irpin .venv/bin/uvicorn backend.app:app --port 8000

A zone folder holds: gazetteer.json (scripts/fetch_district.py --zone <name>), zone.json (label, default language),
and optionally codenames.json, aliases.json, callsigns.json, demo_net_uk.jsonl, demo_net.jsonl, stress_uk.jsonl.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
NAME = (os.getenv("ZONE") or "paris").strip().lower()
DIR = DATA if NAME == "paris" else DATA / "zones" / NAME
if not (DIR / "gazetteer.json").exists():
    raise SystemExit(f"ZONE={NAME}: {DIR / 'gazetteer.json'} not found; run scripts/fetch_district.py --zone {NAME}")


def path(name: str, shared: bool = False) -> Path:
    """A zone's own file. shared=True: fall back to data/<name> when the zone has none (e.g. the callsign table)."""
    p = DIR / name
    return p if p.exists() or not shared else DATA / name


def info() -> dict:
    meta = {"name": NAME, "label": "Paris 6e (Saint-Germain-des-Prés)", "lang": "en"}
    f = DIR / "zone.json"
    if NAME != "paris" and f.exists():
        meta.update(json.loads(f.read_text(encoding="utf-8")))
    return meta
