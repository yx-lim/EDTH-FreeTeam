"""Which area of operations the app runs on. Paris uses data/ as before; another zone uses data/zones/<name>/ for its
map data, codenames, aliases, demo nets and logs, so two zones never mix.

The starting zone comes from ZONE (default paris); the app's zone dropdown (POST /zone) switches it while running.

    ZONE=irpin .venv/bin/uvicorn backend.app:app --port 8000

A zone folder holds: gazetteer.json (scripts/fetch_district.py --zone <name>), zone.json (label, default language),
and optionally codenames.json, aliases.json, callsigns.json, demo_net_uk.jsonl, demo_net.jsonl, stress_uk.jsonl.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def dir_of(name: str) -> Path:
    return DATA if name == "paris" else DATA / "zones" / name


def available() -> list[str]:
    """Zones with map data: paris, then every data/zones/<name>/gazetteer.json."""
    others = sorted(p.parent.name for p in (DATA / "zones").glob("*/gazetteer.json")) if (DATA / "zones").exists() else []
    return ["paris", *others]


NAME = (os.getenv("ZONE") or "paris").strip().lower()
DIR = dir_of(NAME)
if not (DIR / "gazetteer.json").exists():
    raise SystemExit(f"ZONE={NAME}: {DIR / 'gazetteer.json'} not found; run scripts/fetch_district.py --zone {NAME}")


def switch(name: str) -> None:
    """Make `name` the current zone (backend.app reloads its gazetteer, tracker and net from it)."""
    global NAME, DIR
    if name not in available():
        raise ValueError(f"unknown zone {name!r}; available: {', '.join(available())}")
    NAME, DIR = name, dir_of(name)
    from . import lang_uk
    lang_uk.reload_callsigns()   # a zone may have its own callsign table


def path(name: str, shared: bool = False) -> Path:
    """A zone's own file. shared=True: fall back to data/<name> when the zone has none (e.g. the callsign table)."""
    p = DIR / name
    return p if p.exists() or not shared else DATA / name


def info(name: str | None = None) -> dict:
    name = name or NAME
    meta = {"name": name, "label": "Paris 6e (Saint-Germain-des-Prés)", "lang": "en"}
    f = dir_of(name) / "zone.json"
    if name != "paris" and f.exists():
        meta.update(json.loads(f.read_text(encoding="utf-8")))
    return meta
