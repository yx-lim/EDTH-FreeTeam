"""Turn one structured report into an uncertainty region. No LLM in here: every rule is testable."""
from __future__ import annotations

import math

import mgrs as _mgrs_lib
from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, substring

from . import grid, lang_uk
from .geo import Gazetteer, Place, Proj, norm

_MGRS = _mgrs_lib.MGRS()


def _fmt_mgrs(lat: float, lon: float, precision: int = 4) -> str:
    try:
        raw = _MGRS.toMGRS(lat, lon, MGRSPrecision=precision)
        import re
        m = re.match(r"^(\d{1,2}[C-X])([A-Z]{2})(\d*)$", raw)
        if not m:
            return raw
        d = m.group(3)
        h = len(d) // 2
        return " ".join(p for p in (m.group(1), m.group(2), d[:h], d[h:]) if p)
    except Exception:
        return ""

WALK_MPS = 1.5          # how far a unit has probably moved since its last report
MAX_MPS = 4.0           # faster than this (running) means the place was probably misheard
SLACK_M = 150.0         # tolerance on top of MAX_MPS for vague reports
NEAR_M = 50.0
BEARINGS = {"north_of": 0, "east_of": 90, "south_of": 180, "west_of": 270,
            "northeast_of": 45, "southeast_of": 135, "southwest_of": 225, "northwest_of": 315}
SELF_ANCHORS = {"me", "self", "here", "us", "my position", "current position", "our position", "я", "ми", "мы", "тут", "здесь"}
_COMPASS8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _resolve_self_move(report: dict, gaz: Gazetteer, last: BaseGeometry | None, heading_deg: float | None) -> dict:
    """Dead-reckoning relative movement ('moving 200m forward-left', '100m north from here')."""
    origin_xy = last.centroid if last is not None else Point(0, 0)
    origin_ll = gaz.proj.to_ll(origin_xy)
    local_proj = Proj(origin_ll.y, origin_ll.x)
    relation = report.get("relation") or "in_front_of"
    base_hdg = float(heading_deg or 0.0) % 360
    if report.get("bearing_deg") is not None:
        brng = float(report["bearing_deg"]) % 360
    elif relation in BEARINGS:
        brng = float(BEARINGS[relation])
    elif relation == "left_of":
        brng = (base_hdg - 90) % 360
    elif relation == "right_of":
        brng = (base_hdg + 90) % 360
    elif relation == "behind":
        brng = (base_hdg + 180) % 360
    else:
        brng = base_hdg
    dist = float(report.get("distance_m") or 100.0)
    dx = dist * math.sin(math.radians(brng))
    dy = dist * math.cos(math.radians(brng))
    dest_local = Point(dx, dy)
    unc_r = max(25.0, min(85.0, dist * 0.22))
    region_local = dest_local.buffer(unc_r)
    region_ll = local_proj.to_ll(region_local)
    region_gaz_xy = gaz.proj.to_xy(region_ll)
    c_ll = region_ll.centroid
    cardinal = _COMPASS8[round(brng / 45) % 8]
    notes = [f"dead-reckoning {round(dist)}m bearing {round(brng):03d}° ({cardinal})"]
    ambiguous = last is None or relation in ("left_of", "right_of", "in_front_of", "behind")
    if last is None:
        notes.append("no prior fix: projected from AO centre")
    from shapely.geometry import mapping
    return {
        "ok": True,
        "region": mapping(region_ll),
        "centre": [round(c_ll.x, 6), round(c_ll.y, 6)],
        "radius_m": round(math.sqrt(region_local.area / math.pi), 1),
        "anchor": f"dead-reckoning ({round(dist)}m {cardinal})",
        "ambiguous": ambiguous,
        "alternatives": [],
        "note": "; ".join(notes),
        "_geom": region_gaz_xy,
    }


def wedge(origin: Point, bearing_deg: float, r_in: float, r_out: float, half_angle: float = 35) -> Polygon:
    """Annular sector; bearing is clockwise from north."""
    def arc(r: float, angles):
        return [(origin.x + r * math.sin(math.radians(a)), origin.y + r * math.cos(math.radians(a))) for a in angles]
    steps = [bearing_deg - half_angle + i * (2 * half_angle / 12) for i in range(13)]
    return Polygon(arc(r_out, steps) + arc(max(r_in, 0.1), reversed(steps)))


def bearing(a: Point, b: Point) -> float:
    return math.degrees(math.atan2(b.x - a.x, b.y - a.y)) % 360


def band(report: dict, base: float) -> tuple[float, float]:
    """Inner and outer distance of a reported distance band, from the edge of the place. A spoken range ("200 to 300
    metres") is used as said; an approximate one ("about 200") is widened; none at all means "close by"."""
    lo, hi, d = report.get("distance_min_m"), report.get("distance_max_m"), report.get("distance_m")
    if lo and hi:
        return 0.85 * lo, 1.15 * hi + base
    if d:
        return (0.5 * d, 1.5 * d + base) if report.get("vague") else (0.7 * d, 1.3 * d + base)
    return 0.5 * base, base + 100


def footprint_radius(place: Place) -> float:
    return math.sqrt(place.geom.area / math.pi) if place.geom.area else 0.0


def candidates(name: str, gaz: Gazetteer, units: dict[str, BaseGeometry] | None, near, kind) -> list[Place]:
    """Another unit's callsign is a valid anchor ("I'm with Alpha one", "50 m north of Bravo two")."""
    key = norm(name)
    for n, w in {"one": "1", "two": "2", "three": "3", "four": "4", "un": "1", "deux": "2", "trois": "3"}.items():
        key = key.replace(f" {n}", f" {w}")
    if units and key in units:
        return [Place(key, "unit", "unit", units[key])]
    if units and lang_uk.has_cyrillic(name) and (hit := lang_uk.unit_lookup(name, units)):
        return [Place(hit, "unit", "unit", units[hit])]
    return gaz.find(name, near=near, kind=kind)


def grid_place(name: str, gaz: Gazetteer, near: Point | None) -> tuple[list[Place], str | None]:
    """A grid anchor -> its square as a Place (metres), or a reason not to plot it. A short grid ("512110") takes
    its zone and 100 km square from `near` (the unit's last position) or else the middle of the mapped area."""
    ll = gaz.proj.to_ll(near if near is not None else Point(0, 0))   # projection origin = gazetteer centre
    try:
        full = grid.complete_grid(name, (ll.y, ll.x))
        square = gaz.proj.to_xy(Polygon([(lon, lat) for lat, lon in grid.square_corners(full)]))
    except Exception:  # noqa: BLE001 - ValueError from grid.py, plain Exception from the mgrs package
        return [], f"grid {name} is not a valid grid reference"
    label = f"grid {full}"
    if not gaz.inside(square):
        return [], f"{label} is outside the mapped area"
    return [Place(label, "grid", "", square)], None


def grid_fallback(report: dict, problem: str, gaz: Gazetteer, last, elapsed_s, units) -> dict:
    """An implausible grid (misheard, or outside the map): use the landmark said with it, if any, and say why."""
    fb = report.get("fallback") or {}
    if not (fb.get("anchor") or {}).get("name"):
        return {"ok": False, "note": f"{problem}; say again the grid"}
    out = resolve({**report, "anchor2": None, "distance_m": None, **fb, "fallback": None}, gaz, last, elapsed_s, units)
    note = f"{problem}; used {fb['anchor']['name']} instead"
    out["note"] = "; ".join(n for n in (note, out.get("note")) if n)
    if out.get("ok"):
        out["ambiguous"] = True
    return out


def resolve(report: dict, gaz: Gazetteer, last: BaseGeometry | None = None, elapsed_s: float | None = None,
            units: dict[str, BaseGeometry] | None = None, heading_deg: float | None = None) -> dict:
    """Returns {ok, region (GeoJSON), centre [lon, lat], radius_m, anchor, ambiguous, alternatives, note}."""
    anchor = report.get("anchor") or {}
    relation = report.get("relation") or "at"
    name = anchor.get("name")
    # Relative self-movement (e.g. "moving 200m left/forward/north", "Ми йдемо наліво на двісті метрів вперед")
    if report.get("type") != "contact":
        if (name and norm(name) in SELF_ANCHORS) or (
            not name and (report.get("distance_m") or report.get("bearing_deg") is not None)
            and relation in (*BEARINGS, "bearing", "left_of", "right_of", "in_front_of", "behind", "towards")
        ):
            return _resolve_self_move(report, gaz, last, heading_deg)
    if not name:
        return {"ok": False, "note": "no place in report"}

    last_pt = last.centroid if last is not None else None
    notes = []
    if anchor.get("kind") == "grid":
        found, problem = grid_place(name, gaz, last_pt)
        if problem:
            return grid_fallback(report, problem, gaz, last, elapsed_s, units)
        if anchor.get("doubt"):
            notes.append(f"read back the grid: {anchor['doubt']}")
    else:
        # No previous position: the middle of the mapped area (the projection origin) breaks ties, so "the church"
        # is the one in the area of operations, not the biggest one on the map.
        found = candidates(name, gaz, units, last_pt if last_pt is not None else Point(0, 0), anchor.get("kind"))
    if not found:
        return {"ok": False, "note": f"unknown place: {name!r}; say again or name a nearby street"}  # never guess
    if found[0].kind not in ("unit", "grid") and gaz.by_sound(name, found[0]):
        notes.append(f"heard {name!r}: taken as {found[0].name} (sounds alike); confirm")
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
    ambiguous = len(distinct) > 1 or any("implausible" in n or "read back" in n or "sounds alike" in n for n in notes)
    centre_geom = place.geom.centroid
    dist = report.get("distance_m")
    base = footprint_radius(place)

    if relation == "intersection" or anchor.get("kind") == "intersection":
        if place.kind != "street":   # "Rue de Rennes" is also a metro entrance: at a corner, the street is meant
            place = next((p for p in [*found, *gaz.find(place.name, near=last_pt, kind="street")]
                          if p.kind == "street" and p.key == place.key), place)
        other = gaz.find((report.get("anchor2") or {}).get("name", ""), near=place.geom, kind="street")
        if not other:
            return {"ok": False, "note": "second street of the intersection not found"}
        a, b = nearest_points(place.geom, other[0].geom)
        if place.kind == "street" and other[0].kind == "street" and a.distance(b) <= 40:
            crossing = place.geom.intersection(other[0].geom)
            if crossing.is_empty:
                # Streets that meet at a square often do not share a node in OSM: use their closest points.
                crossing = LineString([a, b]).centroid
            region = crossing.centroid.buffer(20)
            place = Place(f"{place.name} × {other[0].name}", "intersection", "", crossing)
            ambiguous = False
        elif a.distance(b) <= 400:
            # "The crossing between the Odéon and the CCF": landmarks, not two streets. Read it as between them.
            region = LineString([a, b]).buffer(25) if a.distance(b) > 1 else a.buffer(25)
            notes.append(f"read as between {place.name} and {other[0].name}")
            place = Place(f"{place.name} – {other[0].name}", "intersection", "", region)
            ambiguous = True
        else:
            return {"ok": False, "note": f"{place.name} and {other[0].name} do not meet in the map data"}
    elif relation == "between":
        other = gaz.find((report.get("anchor2") or {}).get("name", ""), near=place.geom)
        if not other:
            return {"ok": False, "note": "second place not found"}
        region = LineString([centre_geom, other[0].geom.centroid]).buffer(25)
    elif relation in BEARINGS or (relation == "bearing" and report.get("bearing_deg") is not None):
        # Measured from the edge of the building, not its middle: "south of the church" is outside the church.
        # A numeric bearing or a 16-point direction is narrower than "north of" (which covers 70 degrees).
        r_in, r_out = band(report, base)
        if relation == "bearing":
            region = wedge(centre_geom, float(report["bearing_deg"]) % 360, r_in, r_out, half_angle=15)
            notes.append(f"bearing {round(float(report['bearing_deg'])):03d} from {place.name}")
        else:
            region = wedge(centre_geom, BEARINGS[relation], r_in, r_out)
        if place.geom.area:
            region = region.difference(place.geom.buffer(2))
    elif relation == "from":
        # A distance with no direction: a ring around the place.
        if dist or report.get("distance_max_m"):
            r_in, r_out = band(report, base)
            region = centre_geom.buffer(r_out).difference(centre_geom.buffer(max(r_in, 0.1)))
            notes.append("distance given without a direction: anywhere on the ring")
        else:
            region = place.geom.buffer(NEAR_M)
        ambiguous = True
    elif relation == "opposite":
        # Across the street from it, on a side nobody said: a band just outside the walls.
        region = place.geom.buffer(dist or 60).difference(place.geom.buffer(10))
        ambiguous = True
        notes.append("'opposite': which side was not said")
    elif relation == "inside":
        region = place.geom.buffer(3) if place.geom.area else place.geom.buffer(25)
    elif relation == "around":
        region = place.geom.buffer(dist or 150)
        ambiguous = True
    elif relation in ("left_of", "right_of"):
        if last_pt is None or last_pt.distance(centre_geom) < 5:
            region = place.geom.buffer(60).difference(place.geom.buffer(5))
            ambiguous = True
            notes.append(f"'{relation.replace('_', ' ')}' needs a viewpoint; no previous position known")
        else:
            b = bearing(last_pt, centre_geom) + (-90 if relation == "left_of" else 90)   # facing the place
            r_in, r_out = band(report, base) if dist else (0.3 * base, base + 60)
            region = wedge(centre_geom, b % 360, r_in, r_out, half_angle=45)
            if place.geom.area:
                region = region.difference(place.geom.buffer(2))
            ambiguous = True
            notes.append("left and right read as seen from the unit's previous position")
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
    elif place.kind == "grid":   # "at" a grid: the square the grid names, no more and no less
        region = place.geom
    else:  # "at": within a short walk of the walls (a door, the steps, the pavement outside)
        region = place.geom.buffer({"unit": 15, "street": 12}.get(place.kind, 20 if place.geom.area else 25))
        if place.kind == "street" and last_pt is not None:
            # A whole street is too vague: keep the stretch nearest the last known position.
            region = region.intersection(last_pt.buffer(250)) or region

    if region.is_empty:
        return {"ok": False, "note": "resolved to an empty region"}
    if not gaz.inside(region):
        return {"ok": False, "note": f"{place.name} is outside the mapped area"}

    # Build clickable candidate_options when multiple distinct places match (e.g., "the tower", "the church")
    candidate_options = []
    if len(distinct) > 1 and relation not in ("intersection", "between"):
        seen_names: set[str] = set()
        kept_geoms: list[BaseGeometry] = []
        ref_pt = last_pt if last_pt is not None else Point(0, 0)
        for cand in found:
            if cand.name in seen_names:
                continue
            # Avoid duplicate adjacent sub-parts (e.g., Tour Nord + Tour Sud on the same cathedral)
            if any(cand.geom.distance(g) < 80 for g in kept_geoms):
                continue
            seen_names.add(cand.name)
            kept_geoms.append(cand.geom)
            c_reg = region if cand is place else cand.geom.buffer(25 if cand.geom.area else 35)
            c_ll = gaz.lonlat(c_reg)
            candidate_options.append({
                "index": len(candidate_options),
                "name": cand.name,
                "category": cand.category or cand.kind,
                "centre": c_ll,
                "mgrs": _fmt_mgrs(c_ll[1], c_ll[0]),
                "radius_m": round(math.sqrt(c_reg.area / math.pi), 1),
                "region": gaz.geojson(c_reg),
                "distance_m": round(cand.geom.distance(ref_pt)),
            })
            if len(candidate_options) >= 4:
                break

    centre_ll = gaz.lonlat(region)
    out = {
        "ok": True,
        "region": gaz.geojson(region),
        "centre": centre_ll,
        "mgrs": _fmt_mgrs(centre_ll[1], centre_ll[0]),
        "radius_m": round(math.sqrt(region.area / math.pi), 1),
        "anchor": place.name,
        "ambiguous": ambiguous,
        "alternatives": distinct[1:4],
        "note": "; ".join(notes),
        "_geom": region,  # internal; stripped before sending to clients
    }
    if candidate_options:
        out["candidate_options"] = candidate_options
    return out
