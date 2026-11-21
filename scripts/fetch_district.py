"""Download named streets and landmarks for one bounding box from OpenStreetMap (Overpass)
and write data/gazetteer.json.

    python scripts/fetch_district.py                     # default: Saint-Germain-des-Pres, Paris 6e
    python scripts/fetch_district.py S W N E             # custom bounding box in degrees
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "data" / "gazetteer.json"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]  # public mirrors, tried in order
DEFAULT_BBOX = (48.8455, 2.3260, 48.8570, 2.3420)  # south, west, north, east

CATEGORY = [  # (tag, value or None for any, category)
    ("amenity", "place_of_worship", "church"), ("building", "church", "church"), ("building", "cathedral", "church"),
    ("leisure", "park", "park"), ("leisure", "garden", "park"),
    ("amenity", "school", "school"), ("amenity", "college", "school"), ("amenity", "university", "school"),
    ("amenity", "hospital", "hospital"), ("railway", "station", "station"), ("station", "subway", "station"),
    ("tourism", "museum", "museum"), ("place", "square", "square"), ("amenity", "fountain", "fountain"),
    ("amenity", "theatre", "theatre"), ("amenity", "marketplace", "market"), ("man_made", "bridge", "bridge"),
]


def category(tags: dict) -> str:
    for tag, value, cat in CATEGORY:
        if tags.get(tag) == value:
            return cat
    return ""


def main() -> None:
    s, w, n, e = map(float, sys.argv[1:5]) if len(sys.argv) >= 5 else DEFAULT_BBOX
    bbox = f"{s},{w},{n},{e}"
    query = f"""[out:json][timeout:60];
(
  way["highway"]["name"]({bbox});
  nwr["name"]["amenity"~"place_of_worship|school|college|university|hospital|fountain|theatre|marketplace|townhall|library"]({bbox});
  nwr["name"]["tourism"~"museum|attraction"]({bbox});
  nwr["name"]["leisure"~"park|garden"]({bbox});
  nwr["name"]["historic"]({bbox});
  nwr["name"]["railway"="station"]({bbox});
  nwr["name"]["place"="square"]({bbox});
);
out geom;"""
    r = None
    for url in OVERPASS:
        try:
            r = httpx.post(url, data={"data": query}, timeout=90, headers={"User-Agent": "voice-to-map-hackathon/0.1"})
            r.raise_for_status()
            break
        except httpx.HTTPError as err:
            print(f"{url} failed: {err!r}; trying next mirror")
            r = None
    if r is None:
        sys.exit("All Overpass mirrors failed; try again in a minute.")

    streets: dict[str, list] = {}
    places: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for el in r.json()["elements"]:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        if el["type"] == "node":
            geom = {"type": "Point", "coordinates": [el["lon"], el["lat"]]}
        elif el["type"] == "way":
            coords = [[p["lon"], p["lat"]] for p in el["geometry"]]
            if "highway" in tags and tags.get("area") != "yes":
                streets.setdefault(name, []).append(coords)
                continue
            closed = len(coords) >= 4 and coords[0] == coords[-1]
            geom = {"type": "Polygon", "coordinates": [coords]} if closed else {"type": "LineString", "coordinates": coords}
        else:  # relation: use its bounding-box centre
            b = el.get("bounds")
            if not b:
                continue
            geom = {"type": "Point", "coordinates": [(b["minlon"] + b["maxlon"]) / 2, (b["minlat"] + b["maxlat"]) / 2]}
        cat = category(tags)
        if (name, cat) in seen and geom["type"] == "Point":
            continue
        seen.add((name, cat))
        places.append({"name": name, "kind": "landmark", "category": cat, "geometry": geom})

    for name, lines in streets.items():
        places.append({"name": name, "kind": "street", "category": "",
                       "geometry": {"type": "MultiLineString", "coordinates": lines}})

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "centre": [(s + n) / 2, (w + e) / 2], "bbox": [s, w, n, e],
        "attribution": "© OpenStreetMap contributors (ODbL)", "places": places,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"{len(places)} places ({len(streets)} streets) -> {OUT}")


if __name__ == "__main__":
    main()
