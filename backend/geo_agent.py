"""AI Geolocation & Coordinate Grounding Agent (Gemini + OpenStreetMap Nominatim/Overpass + Shapely + MGRS).

Activates automatically when GEMINI_API_KEY is configured and local deterministic resolution either:
  1. Failed to find a place (e.g., noisy ASR slips like "champ Luxembourg", multilingual synonyms, or landmarks
     outside the pre-downloaded 3x3 km Paris district such as Eiffel Tower, Arc de Triomphe, or global places), OR
  2. Matched only via a low-confidence sound-alike (e.g., "château du Luxembourg" -> "Théâtre du Luxembourg").

All coordinates are grounded in real OpenStreetMap geometries whenever available, then offset deterministically in
local metres and converted to authoritative MGRS grid references.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from typing import Any

import httpx
import mgrs as mgrs_lib
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry

from . import extract as _extract
from .geo import CATEGORY_WORDS, FOLD, STOP, Gazetteer, Place, Proj, norm, words
from .resolver import BEARINGS, NEAR_M, band, bearing, footprint_radius, resolve, wedge

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "edth-voice-to-map-geo-agent/1.0 (tactical-c2-hackathon)"

# Paris metropolitan viewbox (west, north, east, south) for local biasing before global fallback
PARIS_VIEWBOX = "2.22,48.91,2.47,48.81"
_MGRS_CONV = mgrs_lib.MGRS()

_nominatim_cache: dict[str, list[dict[str, Any]]] = {}
_nominatim_lock = asyncio.Lock()
_last_nominatim = 0.0

_AMENITY_OVERPASS = {
    "church": 'amenity="place_of_worship"',
    "hospital": 'amenity="hospital"',
    "school": 'amenity="school"',
    "pharmacy": 'amenity="pharmacy"',
    "bank": 'amenity="bank"',
    "fountain": 'amenity="fountain"',
    "theatre": 'amenity="theatre"',
    "park": 'leisure="park"',
    "station": 'railway="station"',
    "bridge": 'man_made="bridge"',
    "museum": 'tourism="museum"',
    "market": 'amenity="marketplace"',
    "police": 'amenity="police"',
}

GEO_AGENT_SYSTEM = """You are an elite Military Geolocation & GEOINT Resolution Agent for a live tactical map.
You receive a raw voice-to-text radio transcript (English, French, Ukrainian, Russian, or mixed — often with speech-recognition typos, accents, stutters, or phonetic mishearings), the initial parsed anchor, the soldier's last known position, and a list of local landmarks/codenames in the active Area of Operations (AO: Paris 6e / Saint-Germain-des-Prés, centre 48.85125, 2.33400).

Your job is to determine the EXACT real-world place or tactical movement the speaker intended, and return ONLY valid JSON matching this schema:
{
  "mode": "local_gazetteer" | "nominatim_geocode" | "generic_amenity" | "relative_move" | "direct_coords" | "none",
  "local_place_name": string or null,
  "geocode_queries": [string, ...],
  "prefer_paris": boolean,
  "generic_category": "church"|"park"|"hospital"|"school"|"station"|"bridge"|"fountain"|"square"|"museum"|"theatre"|"market"|"pharmacy"|"bank"|"police"|null,
  "relation": "at"|"near"|"north_of"|"south_of"|"east_of"|"west_of"|"northeast_of"|"northwest_of"|"southeast_of"|"southwest_of"|"in_front_of"|"behind"|"left_of"|"right_of"|"towards"|"bearing"|"opposite"|"inside"|"around",
  "distance_m": number or null,
  "bearing_deg": number or null,
  "estimated_lat": number or null,
  "estimated_lon": number or null,
  "display_name": string or null,
  "confidence": number (0.0 to 1.0),
  "reasoning": string
}

Critical GEOINT rules:
1. Phonetic / ASR repair in AO Paris:
   - "château du Luxembourg" / "palais du Luxembourg" / "senate" -> mode "local_gazetteer", local_place_name "Palais du Luxembourg" (NOT Théâtre du Luxembourg!).
   - "champ Luxembourg" / "jardin Luxembourg" / "Luxembourg park" -> mode "local_gazetteer", local_place_name "Jardin du Luxembourg".
   - "Saint Sulpice" / "San Sulpice" / "Saint Sul-piece" -> "Église Saint-Sulpice" (or "Fontaine des Quatre Évêques" if fountain).
   - "Louvre" / "Louvre museum" -> mode "nominatim_geocode", geocode_queries ["Musée du Louvre, Paris, France"], prefer_paris true, estimated_lat 48.8606, estimated_lon 2.3376.
   - Always check the provided LOCAL LANDMARKS & CODENAMES list first! If the spoken name clearly refers to one of those (even with typos, French/Ukrainian/Russian translation, or ASR garbling), choose mode "local_gazetteer" with the EXACT spelling from that list.
2. Generic landmarks in ANY language ("церква"/"около церкви"/"the church"/"l'église", "парк", "міст", "лікарня", "station"):
   - Choose mode "generic_amenity" and set generic_category (e.g. "church").
3. Landmarks outside the small 3x3km AO (e.g. Eiffel Tower, Arc de Triomphe, Champs-Élysées, Gare du Nord, Montmartre, Sacré-Cœur, Invalides, OR landmarks in other cities/countries like Kyiv Maidan, White House, Pentagon, Big Ben, Brandenburg Gate):
   - Choose mode "nominatim_geocode", give 1-3 crisp OpenStreetMap search queries in geocode_queries, set prefer_paris true if in Paris else false, and provide your best estimated_lat / estimated_lon to disambiguate geocoding results!
4. Relative dead-reckoning movement without a named place (e.g., "moving 200m forward-left", "Ми йдемо наліво на двісті метрів вперед", "advancing 150m east"):
   - Choose mode "relative_move", set distance_m, relation, and bearing_deg (if compound like front-left -> 315 relative to North or heading; front-right -> 45).
5. Disambiguation of famous landmarks vs local namesakes:
   - "Arc de Triomphe" without "Carrousel" means the iconic Arc de Triomphe de l'Étoile at Place Charles de Gaulle (48.8738, 2.2950), NOT "Arc de Triomphe du Carrousel" near the Louvre! Use mode "nominatim_geocode", geocode_queries ["Arc de Triomphe, Place Charles de Gaulle, Paris, France"], prefer_paris true, estimated_lat 48.8738, estimated_lon 2.2950.
   - If the speaker names another city/country (e.g., "White House in Washington DC", "Maidan in Kyiv", "Big Ben London"), NEVER match a local Paris café/street like "Maison Blanche" — use mode "nominatim_geocode" with prefer_paris false and the exact global query!
6. Anti-hallucination:
   - If the transcript is pure radio chatter ("roger, out", "hello") or an obviously invented/fictional place ("banana tower", "moon base"), return mode "none" with confidence 0.0.
"""

_EXTERNAL_GEO_CUES = (
    "washington", "dc", "d c", "london", "kyiv", "kiev", "kharkiv", "lviv", "odesa", "odessa", "dnipro", "donetsk",
    "berlin", "munich", "hamburg", "frankfurt", "new york", "manhattan", "brooklyn", "chicago", "los angeles",
    "san francisco", "boston", "pentagon", "arlington", "tokyo", "seoul", "madrid", "barcelona", "rome", "milan",
    "amsterdam", "brussels", "warsaw", "prague", "vienna", "zurich", "geneva", "moscow", "ukraine", "germany",
    "united states", "america", "england", "britain", "spain", "italy", "poland",
)


def needs_ai_verification(text: str, report: dict[str, Any], local_res: dict[str, Any], gaz: Gazetteer) -> bool:
    """Fast heuristic deciding whether a local result should be verified/upgraded by the AI Geo-Agent."""
    if not enabled():
        return False
    if not local_res.get("ok"):
        return True
    note = (local_res.get("note") or "").lower()
    if "sounds alike" in note or "implausible move" in note:
        return True
    anchor_obj = report.get("anchor") or {}
    if anchor_obj.get("kind") in ("grid", "unit"):
        return False
    # Check if raw text mentions an external city/country outside Paris
    t_norm = f" {norm(text)} "
    if any(f" {cue} " in t_norm for cue in _EXTERNAL_GEO_CUES):
        return True
    spoken = anchor_obj.get("name") or ""
    matched = local_res.get("anchor") or ""
    if not spoken or not matched:
        return False
    # If exact match or known alias or bare category word (e.g. "church"), trust local gazetteer
    s_norm = norm(spoken)
    m_norm = norm(matched)
    # Special disambiguation: bare "tower" / "the tower" / "la tour" -> enrich local towers with iconic Tour Eiffel!
    if s_norm in ("tower", "the tower", "tour", "la tour", "вежа", "башня", "башта"):
        return False  # Handled directly in enrich_ambiguous_candidates so local towers + Eiffel Tower appear together!
    if s_norm == m_norm or s_norm in gaz.aliases or s_norm in CATEGORY_WORDS:
        return False
    s_words = [w for w in words(spoken) if w not in CATEGORY_WORDS]
    m_words = [w for w in words(matched) if w not in CATEGORY_WORDS]
    if not s_words:
        return False
    # If spoken anchor had non-category words dropped (e.g. "White House Washington DC" -> "Maison Blanche")
    # OR matched local place has extra distinguishing words not spoken (e.g. "Arc de Triomphe" -> "Arc de Triomphe du Carrousel")
    if any(w not in m_words for w in s_words):
        return True
    if len(m_words) > len(s_words) and any(w not in s_words for w in m_words):
        return True
    return False


def enabled() -> bool:
    """True when Gemini is configured and the AI geo-agent is not explicitly disabled or in offline mode."""
    if _extract.is_offline():
        return False
    if os.getenv("GEO_AGENT", "").lower() in ("0", "false", "off", "no"):
        return False
    if os.getenv("EXTRACTOR", "").lower() == "rules":
        return False
    return bool(os.getenv("GEMINI_API_KEY"))


def format_mgrs(lat: float, lon: float, precision: int = 4) -> str:
    try:
        raw = _MGRS_CONV.toMGRS(lat, lon, MGRSPrecision=precision)
        # "31UDQ51230945" -> "31U DQ 5123 0945"
        import re
        m = re.match(r"^(\d{1,2}[C-X])([A-Z]{2})(\d*)$", raw)
        if not m:
            return raw
        d = m.group(3)
        h = len(d) // 2
        return " ".join(p for p in (m.group(1), m.group(2), d[:h], d[h:]) if p)
    except Exception:
        return ""


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _top_local_landmarks(gaz: Gazetteer, near_xy: BaseGeometry | None, limit: int = 38) -> list[str]:
    custom = [p.name for p in gaz.places if p.category == "custom"]
    majors = [p for p in gaz.places if p.kind == "landmark" and not p.minor and p.category != "custom"]
    if near_xy is not None:
        majors.sort(key=lambda p: (round(p.geom.distance(near_xy) / 250), -p.size))
    else:
        majors.sort(key=lambda p: -p.size)
    streets = sorted((p for p in gaz.places if p.kind == "street"), key=lambda p: -p.size)[:10]
    names = list(dict.fromkeys(custom + [p.name for p in majors[:limit]] + [p.name for p in streets]))
    return names[:limit + 12]


async def _call_gemini_geo(prompt: str) -> dict[str, Any] | None:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    gen_cfg: dict[str, Any] = {"temperature": 0, "responseMimeType": "application/json"}
    if "3.5" in model or "2.5" in model:
        gen_cfg["thinkingConfig"] = {"thinkingLevel": "MINIMAL"}
    payload = {
        "systemInstruction": {"parts": [{"text": GEO_AGENT_SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(GEMINI_URL.format(model=model), json=payload, headers={"x-goog-api-key": key})
            if r.status_code == 400 and "thinkingConfig" in payload["generationConfig"]:
                payload["generationConfig"].pop("thinkingConfig", None)
                r = await client.post(GEMINI_URL.format(model=model), json=payload, headers={"x-goog-api-key": key})
            r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return json.loads("".join(p.get("text", "") for p in parts))
    except Exception:
        return None


async def _nominatim_search(query: str, bounded_paris: bool = False) -> list[dict[str, Any]]:
    cache_key = f"{norm(query)}|paris={bounded_paris}"
    if cache_key in _nominatim_cache:
        return _nominatim_cache[cache_key]

    global _last_nominatim
    async with _nominatim_lock:
        elapsed = time.monotonic() - _last_nominatim
        if elapsed < 1.02:
            await asyncio.sleep(1.02 - elapsed)
        params: dict[str, Any] = {
            "q": query,
            "format": "jsonv2",
            "limit": 5,
            "polygon_geojson": 1,
            "addressdetails": 1,
        }
        if bounded_paris:
            params["viewbox"] = PARIS_VIEWBOX
            params["bounded"] = 1
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                r = await client.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
                items = r.json()
        except Exception:
            items = []
        finally:
            _last_nominatim = time.monotonic()

    _nominatim_cache[cache_key] = items
    return items


async def _overpass_nearest(category: str, lat: float, lon: float) -> dict[str, Any] | None:
    selector = _AMENITY_OVERPASS.get(category)
    if not selector:
        return None
    query = (
        f"[out:json][timeout:8];("
        f"node[{selector}](around:1500,{lat},{lon});"
        f"way[{selector}](around:1500,{lat},{lon});"
        f");out center 10;"
    )
    try:
        async with httpx.AsyncClient(timeout=9.0) as client:
            r = await client.post(OVERPASS_URL, data={"data": query}, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            elements = r.json().get("elements", [])
    except Exception:
        return None
    cands = []
    for el in elements:
        if "lat" in el and "lon" in el:
            clat, clon = float(el["lat"]), float(el["lon"])
        elif el.get("center"):
            clat, clon = float(el["center"]["lat"]), float(el["center"]["lon"])
        else:
            continue
        name = (el.get("tags") or {}).get("name") or category.title()
        cands.append((_haversine_m(lat, lon, clat, clon), clat, clon, name))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    _, clat, clon, name = cands[0]
    return {"lat": clat, "lon": clon, "display_name": name, "geojson": None}


def _apply_offset_around_world_place(
    anchor_lat: float,
    anchor_lon: float,
    geojson_geom: dict[str, Any] | None,
    display_name: str,
    relation: str,
    distance_m: float | None,
    bearing_deg: float | None,
    last_lonlat: tuple[float, float] | None,
    heading_deg: float | None,
    gaz: Gazetteer,
    note: str,
    ambiguous: bool = False,
) -> dict[str, Any]:
    """Build exact Shapely uncertainty region around ANY global lat/lon or OSM polygon using a local tangent projection."""
    local_proj = Proj(anchor_lat, anchor_lon)
    if geojson_geom:
        try:
            raw_geom = shape(geojson_geom)
            geom_xy = local_proj.to_xy(raw_geom)
        except Exception:
            geom_xy = Point(0.0, 0.0)
    else:
        geom_xy = Point(0.0, 0.0)

    place = Place(display_name, "landmark", "", geom_xy)
    centre_xy = geom_xy.centroid
    base = footprint_radius(place)
    report_stub = {"distance_m": distance_m, "bearing_deg": bearing_deg}

    last_xy = local_proj.to_xy(Point(last_lonlat[0], last_lonlat[1])) if last_lonlat else None

    if relation in BEARINGS or (relation == "bearing" and bearing_deg is not None):
        r_in, r_out = band(report_stub, base)
        if relation == "bearing" and bearing_deg is not None:
            region_xy = wedge(centre_xy, float(bearing_deg) % 360, r_in, r_out, half_angle=18)
        else:
            region_xy = wedge(centre_xy, BEARINGS[relation], r_in, r_out)
        if geom_xy.area:
            region_xy = region_xy.difference(geom_xy.buffer(2))
    elif relation in ("left_of", "right_of", "behind", "in_front_of"):
        if last_xy is not None and last_xy.distance(centre_xy) > 5 and last_xy.distance(centre_xy) < 25000:
            b = bearing(last_xy, centre_xy)
            if relation == "in_front_of":
                b = (b + 180) % 360
            elif relation == "left_of":
                b = (b - 90) % 360
            elif relation == "right_of":
                b = (b + 90) % 360
            r_in, r_out = band(report_stub, base) if distance_m else (0.3 * base, base + 55)
            region_xy = wedge(centre_xy, b % 360, r_in, r_out, half_angle=45)
            if geom_xy.area:
                region_xy = region_xy.difference(geom_xy.buffer(2))
        else:
            b_base = float(heading_deg or 0.0)
            if relation == "behind":
                b_base = (b_base + 180) % 360
            elif relation == "left_of":
                b_base = (b_base - 90) % 360
            elif relation == "right_of":
                b_base = (b_base + 90) % 360
            if distance_m:
                r_in, r_out = band(report_stub, base)
                region_xy = wedge(centre_xy, b_base % 360, r_in, r_out, half_angle=40)
            else:
                region_xy = geom_xy.buffer(55).difference(geom_xy.buffer(4)) if geom_xy.area else geom_xy.buffer(55)
    elif relation == "opposite":
        region_xy = geom_xy.buffer(distance_m or 60).difference(geom_xy.buffer(10)) if geom_xy.area else geom_xy.buffer(55)
    elif relation == "inside":
        region_xy = geom_xy.buffer(3) if geom_xy.area else geom_xy.buffer(30)
    elif relation == "around":
        region_xy = geom_xy.buffer(distance_m or 140)
    elif relation == "towards" and last_xy is not None and 5 < last_xy.distance(centre_xy) < 25000:
        cap = float(distance_m or 150.0)
        b = bearing(last_xy, centre_xy)
        step = min(cap, last_xy.distance(centre_xy))
        dest = Point(last_xy.x + step * math.sin(math.radians(b)), last_xy.y + step * math.cos(math.radians(b)))
        region_xy = dest.buffer(35)
    elif relation == "near":
        region_xy = geom_xy.buffer(distance_m or NEAR_M)
    else:  # "at"
        region_xy = geom_xy.buffer(22 if geom_xy.area else 30)

    if region_xy.is_empty:
        region_xy = centre_xy.buffer(35)

    region_ll = local_proj.to_ll(region_xy)
    c_ll = region_ll.centroid
    # Also project into the gazetteer's xy space so tracker history/distances remain consistent
    region_gaz_xy = gaz.proj.to_xy(region_ll)
    radius_m = round(math.sqrt(region_xy.area / math.pi), 1)

    return {
        "ok": True,
        "region": mapping(region_ll),
        "centre": [round(c_ll.x, 6), round(c_ll.y, 6)],
        "mgrs": format_mgrs(c_ll.y, c_ll.x),
        "radius_m": radius_m,
        "anchor": display_name,
        "ambiguous": ambiguous,
        "alternatives": [],
        "note": note,
        "_geom": region_gaz_xy,
    }


async def enrich_ambiguous_candidates(
    report: dict[str, Any],
    res: dict[str, Any],
    gaz: Gazetteer,
    last: BaseGeometry | None = None,
) -> dict[str, Any]:
    """When an ambiguous bare word like 'tower' matches local towers, also offer iconic Paris Tour Eiffel if online."""
    if not res.get("ok") or not res.get("candidate_options"):
        return res
    spoken = norm((report.get("anchor") or {}).get("name") or "")
    if spoken not in ("tower", "the tower", "tour", "la tour", "вежа", "башня", "башта"):
        return res
    names = {c["name"].lower() for c in res["candidate_options"]}
    if not any("eiffel" in n for n in names) and enabled():
        items = await _nominatim_search("Tour Eiffel, Paris, France", bounded_paris=True)
        if items:
            el = items[0]
            elat, elon = float(el["lat"]), float(el["lon"])
            ref_ll = gaz.proj.to_ll(last.centroid) if last is not None else gaz.proj.to_ll(Point(0, 0))
            eiffel_proj = Proj(elat, elon)
            eiffel_reg = eiffel_proj.to_ll(Point(0, 0).buffer(65))
            eiffel_opt = {
                "index": 0,
                "name": "Tour Eiffel (Eiffel Tower)",
                "category": "tower",
                "centre": [round(elon, 6), round(elat, 6)],
                "mgrs": format_mgrs(elat, elon),
                "radius_m": 65.0,
                "region": mapping(eiffel_reg),
                "distance_m": round(_haversine_m(ref_ll.y, ref_ll.x, elat, elon)),
            }
            opts = [eiffel_opt] + res["candidate_options"][:3]
            for idx, opt in enumerate(opts):
                opt["index"] = idx
            res["candidate_options"] = opts
            res["alternatives"] = [o["name"] for o in opts[1:]]
            note = res.get("note") or ""
            hint = f"Ambiguous '{spoken}': {len(opts)} towers found — operator select target"
            res["note"] = "; ".join(n for n in (hint, note) if n)
            res["ambiguous"] = True
    return res


async def resolve_with_ai(
    text: str,
    report: dict[str, Any],
    gaz: Gazetteer,
    last: BaseGeometry | None = None,
    elapsed_s: float | None = None,
    units: dict[str, BaseGeometry] | None = None,
    heading_deg: float | None = None,
) -> dict[str, Any] | None:
    """Ask the Gemini Geolocation Agent + OSM Nominatim/Overpass to ground a hard/failed/out-of-district report."""
    if not enabled():
        return None

    last_ll_pt = gaz.proj.to_ll(last.centroid) if last is not None else None
    last_lonlat = (last_ll_pt.x, last_ll_pt.y) if last_ll_pt is not None else None
    ref_lat = last_ll_pt.y if last_ll_pt is not None else gaz.proj.lat0
    ref_lon = last_ll_pt.x if last_ll_pt is not None else gaz.proj.lon0

    local_list = _top_local_landmarks(gaz, last.centroid if last is not None else None)
    prompt = (
        f"Raw spoken transcript: {text}\n"
        f"Initial parsed report: {json.dumps(report, ensure_ascii=False)}\n"
        f"Soldier last known position: lat={ref_lat:.6f}, lon={ref_lon:.6f}, MGRS={format_mgrs(ref_lat, ref_lon)}"
        f"{' (AO centre, no prior fix)' if last_lonlat is None else ''}\n"
        f"Soldier heading clockwise from North: {heading_deg if heading_deg is not None else 0}°\n"
        f"LOCAL LANDMARKS & CODENAMES in AO Paris 6e:\n" + ", ".join(local_list)
    )

    plan = await _call_gemini_geo(prompt)
    if not plan or not isinstance(plan, dict):
        return None

    mode = plan.get("mode") or "none"
    confidence = float(plan.get("confidence") or 0.0)
    if mode == "none" or confidence < 0.35:
        return None

    relation = plan.get("relation") or report.get("relation") or "at"
    distance_m = plan.get("distance_m") if plan.get("distance_m") is not None else report.get("distance_m")
    bearing_deg = plan.get("bearing_deg") if plan.get("bearing_deg") is not None else report.get("bearing_deg")
    reasoning = (plan.get("reasoning") or "").strip()

    # 1. Local Gazetteer Match (highest accuracy — exact local building footprint!)
    if mode == "local_gazetteer" and plan.get("local_place_name"):
        target_name = str(plan["local_place_name"]).strip()
        hits = gaz.find(target_name, near=last.centroid if last is not None else Point(0, 0))
        if hits:
            patched = {
                **report,
                "anchor": {"name": hits[0].name, "kind": hits[0].kind},
                "relation": relation,
                "distance_m": distance_m,
                "bearing_deg": bearing_deg,
            }
            res = resolve(patched, gaz, last=last, elapsed_s=elapsed_s, units=units, heading_deg=heading_deg)
            if res.get("ok"):
                agent_note = f"AI Geo-Agent → {hits[0].name}" + (f" ({reasoning})" if reasoning else "")
                res["note"] = "; ".join(n for n in (agent_note, res.get("note")) if n)
                res["mgrs"] = format_mgrs(res["centre"][1], res["centre"][0])
                res["ambiguous"] = confidence < 0.7
                return res

    # 2. Generic Amenity ("church", "hospital", "park", "bridge", etc.)
    if mode == "generic_amenity" and plan.get("generic_category"):
        cat = str(plan["generic_category"]).strip().lower()
        # Try local gazetteer first if near AO Paris
        if _haversine_m(ref_lat, ref_lon, gaz.proj.lat0, gaz.proj.lon0) < 3000:
            hits = gaz.find(cat, near=last.centroid if last is not None else Point(0, 0))
            if hits:
                patched = {
                    **report,
                    "anchor": {"name": hits[0].name, "kind": hits[0].kind},
                    "relation": relation,
                    "distance_m": distance_m,
                    "bearing_deg": bearing_deg,
                }
                res = resolve(patched, gaz, last=last, elapsed_s=elapsed_s, units=units, heading_deg=heading_deg)
                if res.get("ok"):
                    res["note"] = f"AI Geo-Agent matched nearest {cat} → {hits[0].name}"
                    res["mgrs"] = format_mgrs(res["centre"][1], res["centre"][0])
                    return res
        # Overpass fallback for anywhere in the world
        ov = await _overpass_nearest(cat, ref_lat, ref_lon)
        if ov:
            return _apply_offset_around_world_place(
                ov["lat"], ov["lon"], None, ov["display_name"], relation, distance_m, bearing_deg,
                last_lonlat, heading_deg, gaz,
                note=f"AI Geo-Agent (OSM Overpass) → nearest {cat}: {ov['display_name']}",
                ambiguous=False,
            )

    # 3. Relative Dead-Reckoning Movement
    if mode == "relative_move":
        patched = {
            **report,
            "type": "movement",
            "anchor": {"name": "me", "kind": "unit"},
            "relation": relation,
            "distance_m": distance_m or 100.0,
            "bearing_deg": bearing_deg,
        }
        res = resolve(patched, gaz, last=last, elapsed_s=elapsed_s, units=units, heading_deg=heading_deg)
        if res.get("ok"):
            res["note"] = f"AI Geo-Agent dead-reckoning" + (f" ({reasoning})" if reasoning else "") + f"; {res.get('note', '')}"
            res["mgrs"] = format_mgrs(res["centre"][1], res["centre"][0])
            return res

    # 4. Global / Wider-Paris OpenStreetMap Nominatim Geocoding (Grounded!)
    queries = [str(q).strip() for q in (plan.get("geocode_queries") or []) if str(q).strip()]
    if plan.get("display_name") and plan["display_name"] not in queries:
        queries.append(str(plan["display_name"]).strip())

    prefer_paris = bool(plan.get("prefer_paris", True))
    est_lat = plan.get("estimated_lat")
    est_lon = plan.get("estimated_lon")
    has_est = isinstance(est_lat, (int, float)) and isinstance(est_lon, (int, float)) and -90 <= est_lat <= 90 and -180 <= est_lon <= 180

    nom_items: list[dict[str, Any]] = []
    for q in queries[:3]:
        if prefer_paris:
            nom_items = await _nominatim_search(q, bounded_paris=True)
            if nom_items:
                break
        nom_items = await _nominatim_search(q, bounded_paris=False)
        if nom_items:
            break

    if nom_items:
        # Pick the best OSM candidate: closest to Gemini's estimate if available, else closest to soldier/AO
        def cand_dist(item: dict[str, Any]) -> float:
            ilat, ilon = float(item["lat"]), float(item["lon"])
            if has_est:
                return _haversine_m(float(est_lat), float(est_lon), ilat, ilon)
            return _haversine_m(ref_lat, ref_lon, ilat, ilon)

        nom_items_sorted = sorted(nom_items, key=cand_dist)
        best = nom_items_sorted[0]
        blat, blon = float(best["lat"]), float(best["lon"])
        # Guard against wildly mismatched global hits when Gemini had a confident coordinate estimate (>50 km away)
        if not has_est or _haversine_m(float(est_lat), float(est_lon), blat, blon) < 50_000:
            short_name = (
                plan.get("display_name")
                or best.get("name")
                or str(best.get("display_name", "")).split(",")[0].strip()
                or queries[0]
            )
            note = f"AI Geo-Agent (OSM Nominatim verified): {short_name}"
            if reasoning:
                note += f" — {reasoning}"
            return _apply_offset_around_world_place(
                blat, blon, best.get("geojson"), short_name, relation, distance_m, bearing_deg,
                last_lonlat, heading_deg, gaz, note=note, ambiguous=confidence < 0.65,
            )

    # 5. Last-Resort High-Confidence AI Direct Coordinates (honestly flagged ambiguous for duty officer!)
    if has_est and confidence >= 0.75:
        label = str(plan.get("display_name") or (report.get("anchor") or {}).get("name") or "AI Estimate")
        note = f"AI Geo-Agent estimate (confirm; OSM unavailable): {reasoning}" if reasoning else "AI Geo-Agent estimate (confirm)"
        res = _apply_offset_around_world_place(
            float(est_lat), float(est_lon), None, label, relation, distance_m, bearing_deg,
            last_lonlat, heading_deg, gaz, note=note, ambiguous=True,
        )
        # Ensure honest uncertainty radius >= 75m when unverified by OSM
        if res["radius_m"] < 75.0:
            local_proj = Proj(res["centre"][1], res["centre"][0])
            c_ll = local_proj.to_ll(Point(0, 0).buffer(75.0))
            res["region"] = mapping(c_ll)
            res["radius_m"] = 75.0
            res["_geom"] = gaz.proj.to_xy(c_ll)
        return res

    return None
