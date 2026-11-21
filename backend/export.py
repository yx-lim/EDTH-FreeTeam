"""The current picture for other C2 tools: NVG (NATO Vector Graphics, the NATO overlay format read by C2 systems and
map.army-style viewers) and GeoJSON. Both carry the APP-6 / MIL-STD-2525C symbol code of every item.

By default only what the duty officer has let through: drafts (an unconfirmed single sighting, a doubtful fix) stay
behind unless asked for, so a guess never leaves the command post looking like a fact.
"""
from __future__ import annotations

from xml.sax.saxutils import quoteattr

from . import contact as contacts
from .grid import to_mgrs

NVG_NS = "http://tide.act.nato.int/schemas/2012/10/nvg"


def items(tracker, drafts: bool = False) -> list[dict]:
    out = []
    for e in tracker.picture():
        draft = tracker.is_draft(e)
        if draft and not drafts:
            continue
        is_contact = e.get("type") == "contact"
        code = contacts.sidc(e.get("contact"), doubt=draft) if is_contact else contacts.sidc(None, doubt=draft, side="friendly")
        lon, lat = e["centre"]
        what = describe(e.get("contact")) if is_contact else "own unit"
        out.append({"id": e["id"], "t": e["t"], "callsign": e["callsign"], "kind": "contact" if is_contact else "unit",
                    "sidc": code, "draft": draft, "what": what, "lon": lon, "lat": lat, "radius_m": e.get("radius_m"),
                    "mgrs": to_mgrs(lat, lon, radius_m=e.get("radius_m")), "anchor": e.get("anchor"),
                    "seen_by": e.get("seen_by") or ([e["speaker"]] if e.get("speaker") else []), "region": e.get("region"),
                    "contact": e.get("contact")})
    return out


def describe(c: dict | None) -> str:
    c = c or {}
    n = f"{c['count']}x " if (c.get("count") or 0) > 1 else ""
    side = {"hostile": "enemy ", "friendly": "friendly "}.get(c.get("side"), "")
    return f"{n}{side}{c.get('detail') or c.get('what', 'contact')}".strip()


def _rings(geom: dict | None) -> list[list]:
    if not geom:
        return []
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


def nvg(rows: list[dict]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', f'<nvg xmlns="{NVG_NS}" version="2.0.2">']
    for r in rows:
        label = f"{r['callsign']}: {r['what']}" + (" (draft)" if r["draft"] else "")
        symbol, uri = "2525c:" + r["sidc"], f"voice-to-map:event/{r['id']}"
        area = f"{r['callsign']} ±{round(r['radius_m'] or 0)} m"
        lines.append(f"  <g label={quoteattr(label)}>")
        lines.append(f'    <point x="{r["lon"]:.6f}" y="{r["lat"]:.6f}" symbol={quoteattr(symbol)} '
                     f"label={quoteattr(r['callsign'])} uri={quoteattr(uri)}/>")
        for ring in _rings(r["region"]):
            pts = " ".join(f"{x:.6f},{y:.6f}" for x, y in ring)
            lines.append(f'    <polygon points="{pts}" label={quoteattr(area)}/>')
        lines.append("  </g>")
    lines.append("</nvg>")
    return "\n".join(lines) + "\n"


def geojson(rows: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": r["region"], "properties": {k: v for k, v in r.items() if k != "region"}}
        for r in rows]}
