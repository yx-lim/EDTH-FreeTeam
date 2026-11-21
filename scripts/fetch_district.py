"""Download named streets and landmarks for one bounding box from OpenStreetMap (Overpass)
and write data/gazetteer.json.

    python scripts/fetch_district.py                     # default: Saint-Germain-des-Pres, Paris 6e
    python scripts/fetch_district.py S W N E             # custom bounding box in degrees
    python scripts/fetch_district.py --zone irpin        # a named zone (ZONES below) -> data/zones/irpin/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "data" / "gazetteer.json"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]  # public mirrors, tried in order
# South, west, north, east. About 3 x 3 km around Saint-Sulpice (same centre as the first, 1.2 km box): the 6e
# arrondissement plus Notre-Dame, the Pantheon, Montparnasse and both banks of the Seine.
DEFAULT_BBOX = (48.83775, 2.3140, 48.86475, 2.3540)

CATEGORY = [  # (tag, value or None for any, category)
    ("amenity", "place_of_worship", "church"), ("building", "church", "church"), ("building", "cathedral", "church"),
    ("leisure", "park", "park"), ("leisure", "garden", "park"),
    ("amenity", "school", "school"), ("amenity", "college", "school"), ("amenity", "university", "school"),
    ("amenity", "hospital", "hospital"), ("railway", "station", "station"), ("station", "subway", "station"),
    ("tourism", "museum", "museum"), ("place", "square", "square"), ("amenity", "fountain", "fountain"),
    ("amenity", "theatre", "theatre"), ("amenity", "marketplace", "market"), ("man_made", "bridge", "bridge"),
    ("bridge", "yes", "bridge"), ("amenity", "cafe", "cafe"), ("amenity", "restaurant", "restaurant"),
    ("amenity", "bar", "bar"), ("amenity", "pub", "bar"), ("amenity", "pharmacy", "pharmacy"), ("amenity", "bank", "bank"),
    ("amenity", "post_office", "post office"), ("amenity", "police", "police"), ("amenity", "fire_station", "fire station"),
    ("amenity", "townhall", "town hall"), ("amenity", "library", "library"), ("amenity", "cinema", "cinema"),
    ("amenity", "fuel", "petrol station"), ("amenity", "parking", "car park"), ("amenity", "embassy", "embassy"),
    ("office", "diplomatic", "embassy"), ("tourism", "hotel", "hotel"), ("shop", "supermarket", "supermarket"),
    ("shop", "bakery", "bakery"), ("shop", "department_store", "department store"), ("shop", "books", "bookshop"),
    ("historic", "monument", "monument"), ("historic", "memorial", "memorial"), ("memorial", "statue", "statue"),
    ("tourism", "artwork", "statue"), ("historic", "building", "building"), ("building", "university", "school"),
    ("railway", "subway_entrance", "station"), ("tourism", "attraction", "landmark"), ("place", "square", "square"),
    ("highway", "pedestrian", "square"),
]
# Other names a place is known by: spoken in English, shortened, or its old name. Cyrillic ones let a Ukrainian or
# Russian speaker name a landmark ("Нотр-Дам", "Люксембурзький сад").
ALT_TAGS = ["alt_name", "name:en", "short_name", "official_name", "old_name", "loc_name", "name:uk", "name:ru"]


def category(tags: dict) -> str:
    for tag, value, cat in CATEGORY:
        if tags.get(tag) == value:
            return cat
    return ""


# Named zones: bounding box and the zone.json written next to the gazetteer.
ZONES = {
    # Irpin, Kyiv oblast: a town of streets, a river, parks and landmarks, fought over in 2022 and now behind the
    # lines. OSM names are in Ukrainian. About 3 x 3 km around the city centre and the station.
    "irpin": ((50.5083, 30.2266, 50.5353, 30.2690),
              {"label": "Ірпінь (Irpin), Kyiv oblast", "lang": "uk"}),
}


def main() -> None:
    global OUT
    args = sys.argv[1:]
    if "--zone" in args:
        name = args[args.index("--zone") + 1]
        bbox, meta = ZONES[name]
        OUT = OUT.parent / "zones" / name / "gazetteer.json"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        (OUT.parent / "zone.json").write_text(json.dumps({"name": name, **meta}, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
        args = [str(x) for x in bbox]
    s, w, n, e = map(float, args[:4]) if len(args) >= 4 else DEFAULT_BBOX
    bbox = f"{s},{w},{n},{e}"
    query = f"""[out:json][timeout:120];
(
  way["highway"]["name"]({bbox});
  nwr["name"]["amenity"~"^(place_of_worship|school|college|university|hospital|fountain|theatre|marketplace|townhall|library|cafe|restaurant|bar|pub|pharmacy|bank|post_office|police|fire_station|cinema|fuel|parking|embassy)$"]({bbox});
  nwr["name"]["office"="diplomatic"]({bbox});
  nwr["name"]["tourism"~"^(museum|attraction|hotel|artwork)$"]({bbox});
  nwr["name"]["shop"~"^(supermarket|bakery|department_store|books)$"]({bbox});
  way["name"]["man_made"="bridge"]({bbox});
  node["name"]["railway"="subway_entrance"]({bbox});
  nwr["name"]["leisure"~"park|garden"]({bbox});
  nwr["name"]["historic"]({bbox});
  nwr["name"]["railway"="station"]({bbox});
  nwr["name"]["place"="square"]({bbox});
);
out geom;"""
    r = None
    for url in OVERPASS:
        try:
            r = httpx.post(url, data={"data": query}, timeout=150, headers={"User-Agent": "voice-to-map-hackathon/0.1"})
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
            closed = len(coords) >= 4 and coords[0] == coords[-1]
            # A street is a line; a closed pedestrian way or area=yes is a square, kept as a landmark.
            if "highway" in tags and not (closed and (tags.get("area") == "yes" or tags["highway"] == "pedestrian")):
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
        place = {"name": name, "kind": "landmark", "category": cat, "geometry": geom}
        alts = list(dict.fromkeys(a.strip() for t in ALT_TAGS for a in tags.get(t, "").split(";")
                                  if a.strip() and a.strip() != name))
        if alts:
            place["aliases"] = alts
        places.append(place)

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
