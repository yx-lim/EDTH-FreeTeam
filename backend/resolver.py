"""Turn one structured report into an uncertainty region. No LLM in here: every rule is testable."""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, substring

from .geo import Gazetteer, Place, norm

WALK_MPS = 1.5          # how far a unit has probably moved since its last report
MAX_MPS = 4.0           # faster than this (running) means the place was probably misheard
SLACK_M = 150.0         # tolerance on top of MAX_MPS for vague reports
NEAR_M = 50.0
BEARINGS = {"north_of": 0, "east_of": 90, "south_of": 180, "west_of": 270,
            "northeast_of": 45, "southeast_of": 135, "southwest_of": 225, "northwest_of": 315}


def wedge(origin: Point, bearing_deg: float, r_in: float, r_out: float, half_angle: float = 35) -> Polygon:
    """Annular sector; bearing is clockwise from north."""
    def arc(r: float, angles):
        return [(origin.x + r * math.sin(math.radians(a)), origin.y + r * math.cos(math.radians(a))) for a in angles]
    steps = [bearing_deg - half_angle + i * (2 * half_angle / 12) for i in range(13)]
    return Polygon(arc(r_out, steps) + arc(max(r_in, 0.1), reversed(steps)))


def bearing(a: Point, b: Point) -> float:
    return math.degrees(math.atan2(b.x - a.x, b.y - a.y)) % 360


def footprint_radius(place: Place) -> float:
    return math.sqrt(place.geom.area / math.pi) if place.geom.area else 0.0


def candidates(name: str, gaz: Gazetteer, units: dict[str, BaseGeometry] | None, near, kind) -> list[Place]:
    """Another unit's callsign is a valid anchor ("I'm with Alpha one", "50 m north of Bravo two")."""
    key = norm(name)
    for n, w in {"one": "1", "two": "2", "three": "3", "four": "4", "un": "1", "deux": "2", "trois": "3"}.items():
        key = key.replace(f" {n}", f" {w}")
    if units and key in units:
        return [Place(key, "unit", "unit", units[key])]
    return gaz.find(name, near=near, kind=kind)


def resolve(report: dict, gaz: Gazetteer, last: BaseGeometry | None = None, elapsed_s: float | None = None,
            units: dict[str, BaseGeometry] | None = None) -> dict:
    """Returns {ok, region (GeoJSON), centre [lon, lat], radius_m, anchor, ambiguous, alternatives, note}."""
    anchor = report.get("anchor") or {}
    relation = report.get("relation") or "at"
    name = anchor.get("name")
    if not name:
        return {"ok": False, "note": "no place in report"}

    last_pt = last.centroid if last is not None else None
    found = candidates(name, gaz, units, last_pt, anchor.get("kind"))
    if not found:
        return {"ok": False, "note": f"unknown place: {name!r}; say again or name a nearby street"}  # never guess
    notes = []
    # Physics check: a unit on foot cannot cross the district in a minute. Prefer a reachable candidate; if none
    # is reachable, plot the best one but flag it, because the place was probably misheard.
    # (Not for movement: "towards X" names a destination, not where the unit is.)
    if last is not None and elapsed_s is not None and relation not in ("towards", "along"):
        reach = elapsed_s * MAX_MPS + SLACK_M
        reachable = [p for p in found if p.geom.distance(last) <= reach]
        if reachable and reachable[0] is not found[0]:
            notes.append(f"chose {reachable[0].name}: {found[0].name} is too far to reach in {elapsed_s:.0f} s")
            found = reachable + [p for p in found if p not in reachable]
        elif not reachable:
            jump = found[0].geom.distance(last)
            notes.append(f"implausible move: {jump:.0f} m in {elapsed_s:.0f} s; check the place name")
    place: Place = found[0]
    distinct = list(dict.fromkeys(p.name for p in found))
    ambiguous = len(distinct) > 1 or any("implausible" in n for n in notes)
    centre_geom = place.geom.centroid
    dist = report.get("distance_m")
    base = footprint_radius(place)

    if relation == "intersection" or anchor.get("kind") == "intersection":
        other = gaz.find((report.get("anchor2") or {}).get("name", ""), near=place.geom, kind="street")
        if not other:
            return {"ok": False, "note": "second street of the intersection not found"}
        crossing = place.geom.intersection(other[0].geom)
        if crossing.is_empty:
            # Streets that meet at a square often do not share a node in OSM: use their closest points.
            a, b = nearest_points(place.geom, other[0].geom)
            if a.distance(b) > 40:
                return {"ok": False, "note": f"{place.name} and {other[0].name} do not meet in the map data"}
            crossing = LineString([a, b]).centroid
        region = crossing.centroid.buffer(20)
        place = Place(f"{place.name} × {other[0].name}", "intersection", "", crossing)
        ambiguous = False
    elif relation == "between":
        other = gaz.find((report.get("anchor2") or {}).get("name", ""), near=place.geom)
        if not other:
            return {"ok": False, "note": "second place not found"}
        region = LineString([centre_geom, other[0].geom.centroid]).buffer(25)
    elif relation in BEARINGS:
        # Measured from the edge of the building, not its middle: "south of the church" is outside the church.
        r_in, r_out = (0.7 * dist, 1.3 * dist + base) if dist else (0.5 * base, base + 100)
        region = wedge(centre_geom, BEARINGS[relation], r_in, r_out)
        if place.geom.area:
            region = region.difference(place.geom.buffer(2))
    elif relation in ("behind", "in_front_of"):
        if last_pt is None or last_pt.distance(centre_geom) < 5:
            region = place.geom.buffer(60).difference(place.geom.buffer(5))
            ambiguous = True
            notes.append(f"'{relation.replace('_', ' ')}' needs a viewpoint; no previous position known")
        else:
            b = bearing(last_pt, centre_geom)  # looking from the last position towards the anchor
            if relation == "in_front_of":
                b = (b + 180) % 360
            reach = math.sqrt(place.geom.area) if place.geom.area else 10
            region = wedge(centre_geom, b, 0.3 * reach, reach + 60, half_angle=50).difference(place.geom)
            ambiguous = True   # convention still open: "behind" may also mean the far side from the main entrance
            notes.append("read from the unit's previous position")
    elif relation in ("towards", "along"):
        if last_pt is None:
            region = place.geom.buffer(NEAR_M * 2)
            ambiguous = True
            notes.append("movement reported but no previous position known")
        else:
            # Walk the street network towards the nearest part of the target (the middle of a 3 km boulevard is
            # not where anyone is heading, and people do not walk through buildings). Straight line if not routable.
            cap = dist or (max(30.0, elapsed_s * WALK_MPS) if elapsed_s is not None else 150)
            region = gaz.walk_region(last, place.geom, cap) if place.kind != "unit" else None
            if region is None:
                target = nearest_points(place.geom, last_pt)[0]
                path = LineString([last_pt, target]) if target.distance(last_pt) > 1 else None
                region = target.buffer(25) if path is None else substring(path, 0, min(cap, path.length)).buffer(35)
            notes.append(f"moving towards {place.name}: up to {round(cap)} m along the streets")
    elif relation == "near":
        region = place.geom.buffer(dist or NEAR_M)
    else:  # "at": within a short walk of the walls (a door, the steps, the pavement outside)
        region = place.geom.buffer({"unit": 15, "street": 12}.get(place.kind, 20 if place.geom.area else 25))
        if place.kind == "street" and last_pt is not None:
            # A whole street is too vague: keep the stretch nearest the last known position.
            region = region.intersection(last_pt.buffer(250)) or region

    if region.is_empty:
        return {"ok": False, "note": "resolved to an empty region"}
    if not gaz.inside(region):
        return {"ok": False, "note": f"{place.name} is outside the mapped area"}
    return {
        "ok": True,
        "region": gaz.geojson(region),
        "centre": gaz.lonlat(region),
        "radius_m": round(math.sqrt(region.area / math.pi), 1),
        "anchor": place.name,
        "ambiguous": ambiguous,
        "alternatives": distinct[1:4],
        "note": "; ".join(notes),
        "_geom": region,  # internal; stripped before sending to clients
    }
