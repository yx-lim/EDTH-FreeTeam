"""Local metric projection and gazetteer lookup for one pre-downloaded district."""
from __future__ import annotations

import difflib
import heapq
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring, unary_union

DATA = Path(__file__).resolve().parent.parent / "data"
GAZETTEER = DATA / "gazetteer.json"
ALIASES = DATA / "aliases.json"          # hand-written spoken names -> OSM names
CUSTOM = DATA / "custom_places.json"     # operator-named points ("checkpoint 3"), added at runtime

# Generic words a speaker may use instead of a proper name.
CATEGORY_WORDS = {
    "church": "church", "eglise": "church", "cathedral": "church", "chapel": "church", "chapelle": "church",
    "park": "park", "garden": "park", "gardens": "park", "jardin": "park", "parc": "park",
    "school": "school", "ecole": "school", "lycee": "school",
    "hospital": "hospital", "hopital": "hospital",
    "station": "station", "metro": "station", "gare": "station",
    "museum": "museum", "musee": "museum",
    "square": "square",
    "fountain": "fountain", "fontaine": "fountain",
    "theatre": "theatre", "theater": "theatre",
    "market": "market", "marche": "market",
    "bridge": "bridge", "pont": "bridge",
}
# Words that carry no identity in a place name.
STOP = {"the", "la", "le", "l", "les", "de", "du", "des", "d", "of", "a", "au", "aux"}
# Spoken variants folded onto the form OSM uses.
FOLD = {"st": "saint", "ste": "sainte", "san": "saint", "sant": "saint", "santa": "sainte",
        "palace": "palais", "street": "rue", "senate": "senat"}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]|_", " ", text).split())   # dashes, en dashes, apostrophes -> spaces


def words(text: str) -> list[str]:
    return [FOLD.get(t, t) for t in norm(text).split() if t not in STOP]


def similar(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 3 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.75)


class Proj:
    """Equirectangular projection around a centre; fine at district scale."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self.kx = 111_320.0 * math.cos(math.radians(lat0))
        self.ky = 110_540.0

    def to_xy(self, geom: BaseGeometry) -> BaseGeometry:
        return shapely.transform(geom, lambda c: (c - [self.lon0, self.lat0]) * [self.kx, self.ky])

    def to_ll(self, geom: BaseGeometry) -> BaseGeometry:
        return shapely.transform(geom, lambda c: c / [self.kx, self.ky] + [self.lon0, self.lat0])


@dataclass
class Place:
    name: str
    kind: str        # "street", "landmark", or "unit" (another callsign's last region)
    category: str    # e.g. "church", "park", "custom", "" if unknown
    geom: BaseGeometry  # metres, local projection
    words: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.words = self.words or words(self.name)

    @property
    def key(self) -> str:
        return norm(self.name)

    @property
    def size(self) -> float:
        return self.geom.area or self.geom.length


class Gazetteer:
    def __init__(self, path: Path = GAZETTEER, aliases: Path = ALIASES, custom: Path = CUSTOM):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        lat0, lon0 = raw["centre"]
        self.bbox = raw.get("bbox")
        self.proj = Proj(lat0, lon0)
        self.places = [
            Place(p["name"], p["kind"], p.get("category", ""), self.proj.to_xy(shape(p["geometry"])))
            for p in raw["places"]
        ]
        # OSM sometimes spells one street two ways ("Rue de Rennes" / "rue de rennes"): merge them.
        merged: dict[tuple[str, str], Place] = {}
        rest: list[Place] = []
        for p in self.places:
            if p.kind != "street":
                rest.append(p)
            elif (p.key, p.kind) in merged:
                m = merged[(p.key, p.kind)]
                m.geom = unary_union([m.geom, p.geom])
            else:
                merged[(p.key, p.kind)] = p
        self.places = rest + list(merged.values())
        self.aliases = {}
        if Path(aliases).exists():
            self.aliases = {norm(k): v for k, v in json.loads(Path(aliases).read_text(encoding="utf-8"))["aliases"].items()}
        self.custom_path = Path(custom)
        if self.custom_path.exists():
            for c in json.loads(self.custom_path.read_text(encoding="utf-8")):
                self._add_custom(c["name"], c["lon"], c["lat"])

    # --- operator-named points -------------------------------------------------------------
    def _add_custom(self, name: str, lon: float, lat: float) -> Place:
        place = Place(name, "landmark", "custom", self.proj.to_xy(Point(lon, lat)))
        self.places = [p for p in self.places if not (p.category == "custom" and p.key == place.key)] + [place]
        return place

    def add_custom(self, name: str, lon: float, lat: float) -> Place:
        place = self._add_custom(name, lon, lat)
        self.custom_path.write_text(json.dumps(self.custom(), ensure_ascii=False, indent=1), encoding="utf-8")
        return place

    def custom(self) -> list[dict]:
        out = []
        for p in self.places:
            if p.category == "custom":
                ll = self.proj.to_ll(p.geom)
                out.append({"name": p.name, "lon": round(ll.x, 6), "lat": round(ll.y, 6)})
        return out

    def vocabulary(self, limit: int = 100) -> list[str]:
        """Names worth priming speech-to-text with: custom points, aliases, then the biggest places."""
        named = [p for p in self.places if p.category == "custom"]
        named += sorted((p for p in self.places if p.category not in ("", "custom")), key=lambda p: -p.size)
        named += sorted((p for p in self.places if p.kind == "street"), key=lambda p: -p.size)
        out = list(dict.fromkeys([p.name for p in named[:1]] + list(self.aliases.values())))
        for p in named:
            if p.name not in out:
                out.append(p.name)
        return out[:limit]

    # --- lookup ------------------------------------------------------------------------------
    def find(self, name: str, near: BaseGeometry | None = None, kind: str | None = None, shrink: bool = True) -> list[Place]:
        """Candidates for a spoken anchor, best first. Empty list means unknown: never guess."""
        q_norm = " ".join(t for t in norm(name).split() if t not in ("the", "la", "le", "l", "les"))
        if q_norm in self.aliases:
            name = self.aliases[q_norm]
        raw_tokens = [t for t in norm(name).split() if t not in STOP]
        wanted = next((CATEGORY_WORDS[t] for t in raw_tokens if t in CATEGORY_WORDS), None)
        named = [FOLD.get(t, t) for t in raw_tokens if t not in CATEGORY_WORDS]
        tokens = words(name)
        pool = [p for p in self.places if kind in (None, "intersection", "unit", p.kind)] or self.places

        def score(p: Place) -> int:
            if p.words == tokens:
                return 0
            if tokens and all(t in p.words for t in tokens):
                return 1
            if wanted and p.category == wanted and all(t in p.words for t in named):
                return 2 if named else 3   # "saint sulpice church" beats a bare "the church"
            return 9

        hits = [(s, p) for p in pool if (s := score(p)) < 9]
        if not hits and named:
            # Transcription slips ("Rude Rennes", "Saint Germain de Pre"): every spoken word must be close to a
            # word of the place, and at least one must match exactly.
            for p in pool:
                if wanted and p.category != wanted:
                    continue
                if all(any(similar(t, w) for w in p.words) for t in named) and any(t in p.words for t in named):
                    hits.append((4, p))
        if wanted and any(p.category == wanted for _, p in hits):
            hits = [(s, p) for s, p in hits if p.category == wanted]
        if not hits:
            close = difflib.get_close_matches(norm(name), {p.key for p in pool}, n=3, cutoff=0.8)
            hits = [(5, p) for p in pool if p.key in close]
        if not hits and kind is not None:
            return self.find(name, near=near, kind=None, shrink=shrink)   # the kind guess was wrong; retry
        if not hits and shrink:
            # Trailing context ("medici fountain in the luxembourg gardens", "town hall on place saint sulpice"):
            # drop words from the end until a place matches.
            toks = norm(name).split()
            for k in range(len(toks) - 1, 0, -1):
                found = self.find(" ".join(toks[:k]), near=near, kind=None, shrink=False)
                if found:
                    return found
            return []
        # Best score, then nearest to the unit's last position, then footprints before points, then bigger first
        # (a speaker saying "the church" means the landmark, not a chapel inside a school).
        hits.sort(key=lambda sp: (sp[0], round(sp[1].geom.distance(near)) if near is not None else 0,
                                  sp[1].geom.geom_type == "Point", -sp[1].size))
        return [p for _, p in hits]

    # --- walking routes over the named-street network -------------------------------------------
    def _graph(self):
        if getattr(self, "_adj", None) is None:
            adj: dict[tuple, list] = {}
            for p in self.places:
                if p.kind != "street":
                    continue
                for line in getattr(p.geom, "geoms", [p.geom]):
                    if line.geom_type != "LineString":
                        continue
                    pts = [(round(x, 2), round(y, 2)) for x, y in line.coords]
                    for a, b in zip(pts, pts[1:]):
                        d = math.dist(a, b)
                        adj.setdefault(a, []).append((b, d))
                        adj.setdefault(b, []).append((a, d))
            self._adj = adj
            self._keys = list(adj)
            self._pts = shapely.points(np.array(self._keys)) if adj else None
        return self._adj

    def walk_region(self, start: BaseGeometry, target: BaseGeometry, cap_m: float, width_m: float = 30,
                    snap_m: float = 120, max_starts: int = 24) -> BaseGeometry | None:
        """Where a unit can be after walking up to cap_m along streets from anywhere in `start` towards `target`.

        One Dijkstra from the target gives every street node's shortest way there; each plausible start node
        follows it for cap_m. The union of those walks is the region, so an uncertain start (either side of a
        church) gives a wider answer instead of a confident wrong one. None if the streets cannot be used.
        """
        adj = self._graph()
        if not adj:
            return None
        d_target = shapely.distance(self._pts, target)
        if d_target.min() > snap_m:
            return None
        goals = [self._keys[i] for i in np.flatnonzero(d_target <= max(2.0, d_target.min() + 1))]
        dist, nxt, todo = {g: 0.0 for g in goals}, {}, [(0.0, g) for g in goals]
        while todo:
            d, n = heapq.heappop(todo)
            if d > dist.get(n, math.inf):
                continue
            for m, w in adj[n]:
                if d + w < dist.get(m, math.inf):
                    dist[m], nxt[m] = d + w, n
                    heapq.heappush(todo, (d + w, m))
        d_start = shapely.distance(self._pts, start)
        inside = [self._keys[i] for i in np.flatnonzero(d_start <= 5)]
        if not inside:
            if d_start.min() > snap_m:
                return None
            inside = [self._keys[int(np.argmin(d_start))]]
        inside = [n for n in inside if n in dist] or []
        if not inside:
            return None
        step = max(1, len(inside) // max_starts)
        walks = []
        for n in inside[::step]:
            path = [n]
            while path[-1] in nxt and len(path) < 5000:
                path.append(nxt[path[-1]])
            line = LineString(path) if len(path) > 1 else Point(path[0])
            walks.append(substring(line, 0, min(cap_m, line.length)) if line.geom_type == "LineString" else line)
        return unary_union([w.buffer(width_m) for w in walks])

    def inside(self, geom_xy: BaseGeometry) -> bool:
        if not self.bbox:
            return True
        s, w, n, e = self.bbox
        ll = self.proj.to_ll(geom_xy.centroid)
        return s <= ll.y <= n and w <= ll.x <= e

    def to_xy_ll(self, lon: float, lat: float) -> BaseGeometry:
        return self.proj.to_xy(Point(lon, lat))

    def geojson(self, geom_xy: BaseGeometry) -> dict:
        return mapping(self.proj.to_ll(geom_xy))

    def lonlat(self, geom_xy: BaseGeometry) -> list[float]:
        pt = self.proj.to_ll(geom_xy.centroid)
        return [round(pt.x, 6), round(pt.y, 6)]
