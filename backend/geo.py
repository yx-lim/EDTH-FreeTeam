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

from . import lang_uk, zone

DATA = zone.DIR                          # data/ for Paris, data/zones/<name>/ for another zone (backend/zone.py)
GAZETTEER = DATA / "gazetteer.json"
ALIASES = DATA / "aliases.json"          # hand-written spoken names -> OSM names
CUSTOM = DATA / "custom_places.json"     # operator-named points ("checkpoint 3"), added at runtime
CODENAMES = DATA / "codenames.json"      # mission codenames for the day (Ромашка, Сарай), loaded as operator points

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
    "cafe": "cafe", "coffee": "cafe", "restaurant": "restaurant", "brasserie": "restaurant", "bistro": "restaurant",
    "bar": "bar", "pub": "bar", "pharmacy": "pharmacy", "pharmacie": "pharmacy", "chemist": "pharmacy",
    "bank": "bank", "banque": "bank", "post": "post office", "poste": "post office", "police": "police",
    "commissariat": "police", "library": "library", "bibliotheque": "library", "cinema": "cinema",
    "hotel": "hotel", "supermarket": "supermarket", "bakery": "bakery", "boulangerie": "bakery",
    "embassy": "embassy", "ambassade": "embassy", "statue": "statue", "monument": "monument", "memorial": "memorial",
    "bookshop": "bookshop", "bookstore": "bookshop", "librairie": "bookshop",
    "tower": "tower", "towers": "tower", "tour": "tower", "tours": "tower",
}
# Small, numerous places (1,400 restaurants, 460 cafes...): matched only by their exact name, never by a fuzzy guess
# or a shortened phrase, so a misheard landmark is not quietly turned into some bistro.
MINOR = {"cafe", "restaurant", "bar", "hotel", "bookshop", "statue", "bakery", "pharmacy", "bank", "car park",
         "supermarket", "memorial"}
# Words that carry no identity in a place name.
STOP = {"the", "la", "le", "l", "les", "de", "du", "des", "d", "of", "a", "au", "aux"}
# Spoken variants folded onto the form OSM uses.
FOLD = {"vulytsia": "rue", "vul": "rue", "ulitsa": "rue", "ulytsia": "rue", "ulica": "rue",
        "st": "saint", "ste": "sainte", "san": "saint", "sant": "saint", "santa": "sainte",
        "palace": "palais", "chateau": "palais", "street": "rue", "senate": "senat"}

# Bare Ukrainian / Russian generic landmark words (stems) -> canonical English category words.
_CYRILLIC_CATEGORY_STEMS = (
    ("церкв", "church"), ("церков", "church"), ("храм", "church"), ("собор", "church"), ("костел", "church"),
    ("парк", "park"), ("сад", "park"), ("сквер", "park"),
    ("школ", "school"), ("ліце", "school"), ("лице", "school"),
    ("лікарн", "hospital"), ("больниц", "hospital"), ("госпітал", "hospital"), ("госпитал", "hospital"),
    ("станці", "station"), ("станци", "station"), ("метро", "station"), ("вокзал", "station"),
    ("музе", "museum"), ("площ", "square"), ("майдан", "square"),
    ("фонтан", "fountain"), ("театр", "theatre"),
    ("ринок", "market"), ("ринк", "market"), ("рынок", "market"), ("рынк", "market"), ("базар", "market"),
    ("міст", "bridge"), ("мост", "bridge"), ("мост", "bridge"),
    ("аптек", "pharmacy"), ("банк", "bank"), ("кафе", "cafe"), ("ресторан", "restaurant"),
    ("готел", "hotel"), ("отел", "hotel"), ("пошт", "post office"), ("почт", "post office"),
    ("поліці", "police"), ("полици", "police"),
    ("башт", "tower"), ("веж", "tower"), ("башн", "tower"),
)
_CYRILLIC_PREP = {"около", "біля", "возле", "у", "в", "на", "до", "від", "от", "за", "перед", "під", "под", "над", "при", "к"}


def _cyrillic_category(name: str) -> str | None:
    """Map a bare Cyrillic generic landmark ('церква', 'около церкви', 'парку', 'мосту') to its English category."""
    toks = [t for t in norm(name).split() if t not in _CYRILLIC_PREP]
    if len(toks) != 1:
        return None
    tok = toks[0]
    for stem, cat in _CYRILLIC_CATEGORY_STEMS:
        if tok == stem or (len(stem) >= 4 and tok.startswith(stem) and len(tok) <= len(stem) + 4):
            return cat
        if len(stem) == 3 and tok in (stem, stem + "у", stem + "а", stem + "е", stem + "і", stem + "ом", stem + "ів"):
            return cat
    return None


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]|_", " ", text).split())   # dashes, en dashes, apostrophes -> spaces


# Cyrillic filler words in names: "Парк ім. Правика" is said "парк Правика"; "і"/"та"/"и" join two names.
STOP_CYR = {"им", "имени", "та", "и"}


def words(text: str) -> list[str]:
    out = []
    for t in norm(text).split():
        if lang_uk.has_cyrillic(t):
            t = lang_uk.fold(t)
            if t in STOP_CYR:
                continue
            t = lang_uk.STREET_WORDS.get(t) or next(   # "улица", "ул", "вул", "на улице", "вулиці" -> "вулиця"
                (v for k, v in lang_uk.STREET_WORDS.items() if len(k) >= 5 and lang_uk.same_word(t, k)
                 and abs(len(t) - len(k)) <= 2), t)
        elif t in STOP:
            continue
        out.append(FOLD.get(t, t))
    return out


def has_word(pw: list[str], t: str) -> bool:
    """t is one of the words pw, allowing Ukrainian/Russian case endings ("Соборній" ~ "соборна")."""
    return t in pw or (lang_uk.has_cyrillic(t) and any(lang_uk.same_word(t, w) for w in pw if lang_uk.has_cyrillic(w)))


def skeleton(word: str) -> str:
    """What a word sounds like, roughly, for English and French names: its first letter and its consonants.
    "odin" / "odeon" -> "odn", "sulpis" / "sulpice" -> "slps", "luxemburg" / "luxembourg" -> "lksmbrk"."""
    w = norm(lang_uk.latin(word) if lang_uk.has_cyrillic(word) else word).replace(" ", "")
    for a, b in (("kh", "k"), ("ph", "f"), ("qu", "k"), ("ck", "k"), ("x", "ks"), ("w", "v"), ("z", "s"), ("y", "i"),
                 ("gn", "n"), ("th", "t"), ("g", "k")):
        w = w.replace(a, b)
    w = re.sub(r"c(?=[eiy])", "s", w).replace("c", "k")
    w = w.replace("h", "")
    w = re.sub(r"(?<=.)[aeiou]+", "", w)          # vowels blur first on a radio; keep the first letter
    w = re.sub(r"(?<=.{3})[std]$", "", w)         # French silent final consonant: "Saint-Germain-des-Pres(t)"
    return re.sub(r"(.)\1+", r"\1", w)


def sounds_like(a: str, b: str) -> bool:
    if len(a) < 3 or len(b) < 3 or a[0] != b[0] and {a[0], b[0]} - set("aeiou"):
        return False
    ka, kb = skeleton(a), skeleton(b)
    return len(ka) >= 3 and (ka == kb or (min(len(ka), len(kb)) >= 4 and difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.85))


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
    aliases: list[str] = field(default_factory=list)   # other spoken names (codenames: "Вторая посадка")
    seeded: bool = False                               # loaded from data/codenames.json, not added by the operator

    alt_words: list[list[str]] = field(default_factory=list)   # words of each Latin-script alias

    def __post_init__(self):
        self.words = self.words or words(self.name)
        # Other names (OSM alternatives, Ukrainian/Russian names), and a Cyrillic name in Latin letters so an
        # English report can say "Shevchenka street" in Irpin.
        self.alt_words = [words(a) for a in self.aliases]
        self.latin_words = words(lang_uk.latin(self.name)) if lang_uk.has_cyrillic(self.name) else []
        if self.latin_words:
            self.alt_words.append(self.latin_words)

    @property
    def minor(self) -> bool:
        return self.category in MINOR

    @property
    def key(self) -> str:
        return norm(self.name)

    @property
    def size(self) -> float:
        return self.geom.area or self.geom.length


class Gazetteer:
    def __init__(self, path: Path = GAZETTEER, aliases: Path = ALIASES, custom: Path = CUSTOM,
                 codenames: Path = CODENAMES):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        lat0, lon0 = raw["centre"]
        self.bbox = raw.get("bbox")
        self.proj = Proj(lat0, lon0)
        self.places = [
            Place(
                p["name"],
                p["kind"],
                "tower" if (
                    p["kind"] == "landmark"
                    and p.get("category", "") in ("", "landmark")
                    and norm(p["name"]).startswith(("tour ", "tours "))
                ) else p.get("category", ""),
                self.proj.to_xy(shape(p["geometry"])),
                aliases=p.get("aliases", []),
            )
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
        self.aliases, self._spoken = {}, {}
        if Path(aliases).exists():
            self._spoken = json.loads(Path(aliases).read_text(encoding="utf-8"))["aliases"]
            self.aliases = {norm(k): v for k, v in self._spoken.items()}
        self._cyr: dict[str, str] | None = None
        if codenames and Path(codenames).exists():
            for c in json.loads(Path(codenames).read_text(encoding="utf-8"))["codenames"]:
                self._add_custom(c["name"], c["lon"], c["lat"], c.get("aliases", []), seeded=True)
        self.custom_path = Path(custom)
        if self.custom_path.exists():
            for c in json.loads(self.custom_path.read_text(encoding="utf-8")):
                self._add_custom(c["name"], c["lon"], c["lat"], c.get("aliases", []))

    # --- operator-named points -------------------------------------------------------------
    def _add_custom(self, name: str, lon: float, lat: float, aliases=(), seeded: bool = False) -> Place:
        place = Place(name, "landmark", "custom", self.proj.to_xy(Point(lon, lat)),
                      aliases=[a for a in aliases if a.strip()], seeded=seeded)
        self.places = [p for p in self.places if not (p.category == "custom" and p.key == place.key)] + [place]
        self._cyr = None
        return place

    def add_custom(self, name: str, lon: float, lat: float, aliases=()) -> Place:
        place = self._add_custom(name, lon, lat, aliases)
        # Seeded codenames come from data/codenames.json every start; only the operator's own points are saved.
        own = [c for c in self.custom() if not c["seeded"]]
        self.custom_path.write_text(json.dumps(own, ensure_ascii=False, indent=1), encoding="utf-8")
        return place

    def custom(self) -> list[dict]:
        out = []
        for p in self.places:
            if p.category == "custom":
                ll = self.proj.to_ll(p.geom)
                out.append({"name": p.name, "lon": round(ll.x, 6), "lat": round(ll.y, 6), "aliases": p.aliases,
                            "seeded": p.seeded})
        return out

    def _cyrillic_index(self) -> dict[str, str]:
        """Cyrillic spoken names -> place name, matched with case endings (see lang_uk). Closed set only: the
        alias table and operator points with their aliases, never the open list of OSM names."""
        if self._cyr is None:
            names = {k: v for k, v in self._spoken.items() if lang_uk.has_cyrillic(k)}
            for p in self.places:   # codenames and operator points; OSM names go through find()'s ranking
                if p.category == "custom":
                    names.update({n: p.name for n in [p.name, *p.aliases] if lang_uk.has_cyrillic(n)})
            self._cyr = lang_uk.index_of(names)
        return self._cyr

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
    def find(self, name: str, near: BaseGeometry | None = None, kind: str | None = None, shrink: bool = True,
             sound: bool = True) -> list[Place]:
        """Candidates for a spoken anchor, best first. Empty list means unknown: never guess."""
        cyr = lang_uk.has_cyrillic(name)
        if cyr:
            # Codenames, the alias table and operator points first: inflected anywhere in the phrase ("100 метрів на
            # схід від Сараю"). A bare generic word ("церква", "біля мосту") becomes its category. Otherwise the map's
            # own names, ranked like any other (Ukrainian zones name places in Cyrillic; in Paris a Cyrillic name may
            # be an OSM alternative such as "Шатле").
            hit = lang_uk.lookup(name, self._cyrillic_index())
            if hit is not None:
                name, cyr = hit, lang_uk.has_cyrillic(hit)
            elif (cat := _cyrillic_category(name)) is not None and not self._names_a_place(name):
                name, cyr = cat, False   # a generic word, unless the map has a place called that ("Соборна")
        q_norm = " ".join(t for t in norm(name).split() if t not in ("the", "la", "le", "l", "les"))
        if q_norm in self.aliases:
            name = self.aliases[q_norm]
        tokens = words(name)

        def category(t: str) -> str | None:
            return CATEGORY_WORDS.get(t) or (lang_uk.category_of(t) if lang_uk.has_cyrillic(t) else None)

        wanted = next((c for t in tokens if (c := category(t))), None)
        named = [t for t in tokens if not category(t)]
        pool = [p for p in self.places if kind in (None, "intersection", "unit", p.kind)] or self.places

        def score(p: Place) -> int:
            best = 9
            for i, pw in enumerate((p.words, *p.alt_words)):   # its name, or another name it is known by
                if pw == tokens:
                    if p.minor and wanted != p.category:
                        best = min(best, 2)
                        continue
                    if i == 0:
                        return 0
                    best = min(best, 0.5)   # exact on an alias: behind a place actually called that ("Panthéon")
                    continue
                # a bare category word ("the market") is matched by category below, not by any name containing it
                if tokens and named and all(has_word(pw, t) for t in tokens) and not (p.minor and wanted != p.category):
                    best = min(best, 1)
                elif wanted and p.category == wanted and all(has_word(pw, t) for t in named):
                    best = min(best, 2 if named else 3)   # "saint sulpice church" beats a bare "the church"
            return best

        hits = [(s, p) for p in pool if (s := score(p)) < 9]
        if not hits and named:
            # Transcription slips ("Rude Rennes", "Saint Germain de Pre"): every spoken word must be close to a
            # word of the place, and at least one must match exactly.
            for p in pool:
                if (wanted and p.category != wanted) or p.minor:
                    continue
                for pw in (p.words, p.latin_words):   # not OSM alternatives: too loose for fuzzy matching
                    # every word close, and one exact, or the category said matches too ("station Mabion")
                    if pw and all(any(similar(t, w) for w in pw) for t in named) and (
                            any(has_word(pw, t) for t in named) or (wanted and p.category == wanted)):
                        hits.append((4, p))
                        break
        if wanted and any(p.category == wanted for _, p in hits):
            hits = [(s, p) for s, p in hits if p.category == wanted]
        if not hits:
            close = difflib.get_close_matches(norm(name), {p.key for p in pool if not p.minor}, n=3, cutoff=0.8)
            hits = [(5, p) for p in pool if p.key in close and not p.minor]
        if not hits and shrink and sound and named and any(len(t) >= 3 for t in named):   # whole phrase only
            # Sound-alikes ("the Odin" for Odéon): every spoken word must sound like a word of the place. Landmarks
            # and streets only; the resolver marks the result for the duty officer to confirm.
            spoken = [t for t in named if len(t) >= 3]
            for p in pool:
                if p.minor or (wanted and p.category != wanted):
                    continue
                if all(any(sounds_like(t, w) for pw in (p.words, *p.alt_words) for w in pw) for t in spoken):
                    hits.append((6, p))
        if not hits and kind is not None:
            return self.find(name, near=near, kind=None, shrink=shrink, sound=sound)   # the kind guess was wrong
        if not hits and cyr and shrink:
            # A Cyrillic name for a Latin-script place ("Пантеон", "Одеон" in Paris): try it in Latin letters.
            # Close spellings only: sound-matching a transliteration would be a guess on a guess ("Романа").
            found = self.find(lang_uk.latin(name), near=near, kind=kind, shrink=True, sound=False)
            if found:
                return found
        if not hits and shrink:
            # Trailing context ("medici fountain in the luxembourg gardens", "town hall on place saint sulpice"):
            # drop words from the end until a place matches.
            toks = norm(name).split()
            for k in range(len(toks) - 1, 0, -1):
                if all(CATEGORY_WORDS.get(t) or t in STOP for t in toks[:k]):
                    break   # "tour banane" must not become "the tower": a bare category is not what was said
                found = [p for p in self.find(" ".join(toks[:k]), near=near, kind=None, shrink=False) if not p.minor]
                if found:
                    return found
            return []
        # Best score, then nearest to the unit's last position, then footprints before points, then bigger first
        # (a speaker saying "the church" means the landmark, not a chapel inside a school).
        # Within about 100 m, the name with fewest extra words wins ("Odéon" over "MK2 Odéon (côté Saint-Germain)").
        def dist(p: Place) -> float:
            return p.geom.distance(near) if near is not None else 0

        # A fuzzy or sound-alike match: the plainest name first, wherever it is ("Odin" -> "Odéon", not a cinema).
        if wanted == "tower" and not named:
            hits.sort(key=lambda sp: (sp[0], sp[1].minor, -sp[1].size, round(dist(sp[1]))))
        else:
            hits.sort(key=lambda sp: (sp[0], sp[1].minor, len(sp[1].words) if sp[0] >= 4 else 0, round(dist(sp[1]) / 100),
                                      len(sp[1].words) if sp[0] == 2 else 0, round(dist(sp[1])),
                                      sp[1].geom.geom_type == "Point", -sp[1].size))
        return [p for _, p in hits]

    def _names_a_place(self, name: str) -> bool:
        """A word of `name` is a word of some place's name on the map (with case endings): "на Соборній" names
        Соборна вулиця, so it is not the generic "собор"."""
        preps = {lang_uk.fold(w) for w in _CYRILLIC_PREP}
        spoken = [t for t in words(name) if lang_uk.has_cyrillic(t) and t not in preps]
        return any(all(has_word(p.words, t) for t in spoken) for p in self.places if p.words) if spoken else False

    def by_sound(self, name: str, place: Place) -> bool:
        """True when `name` reached `place` only through a sound-alike match (worth a "did you mean" check)."""
        names = [w for pw in (place.words, *place.alt_words) for w in pw]
        forms = [name] + ([lang_uk.latin(name)] if lang_uk.has_cyrillic(name) else [])
        for form in forms:
            spoken = [t for t in words(form) if t not in CATEGORY_WORDS and len(t) >= 3
                      and not (lang_uk.has_cyrillic(t) and lang_uk.category_of(t))]
            if not spoken or all(any(similar(t, w) or has_word([w], t) for w in names) for t in spoken):
                return False
        if lang_uk.has_cyrillic(name) and lang_uk.lookup(name, self._cyrillic_index()):
            return False   # a codename or alias, said with a case ending
        return place.key not in self.aliases.values() and norm(name) not in self.aliases

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
        if getattr(self, "_bbox_xy", None) is None:
            s, w, n, e = self.bbox
            self._bbox_xy = self.proj.to_xy(shapely.box(w, s, e, n))
        # Inside if any of it is: a long embankment whose middle lies just past the edge is still in the area.
        return geom_xy.intersects(self._bbox_xy)

    def to_xy_ll(self, lon: float, lat: float) -> BaseGeometry:
        return self.proj.to_xy(Point(lon, lat))

    def geojson(self, geom_xy: BaseGeometry) -> dict:
        return mapping(self.proj.to_ll(geom_xy))

    def lonlat(self, geom_xy: BaseGeometry) -> list[float]:
        pt = self.proj.to_ll(geom_xy.centroid)
        return [round(pt.x, 6), round(pt.y, 6)]

    def offline_basemap(self) -> dict:
        """Cached lightweight GeoJSON of local OSM streets, parks, and major landmark footprints for 100% offline map mode."""
        if getattr(self, "_offline_map", None) is None:
            features = []
            for p in self.places:
                if p.kind == "street":
                    geom = p.geom.simplify(4.0)
                    features.append({
                        "type": "Feature",
                        "properties": {"layer": "street", "name": p.name, "major": p.size > 450},
                        "geometry": mapping(self.proj.to_ll(geom)),
                    })
                elif p.kind == "landmark" and not p.minor and p.geom.area >= 300:
                    geom = p.geom.simplify(3.0)
                    layer = "park" if p.category == "park" else "building"
                    features.append({
                        "type": "Feature",
                        "properties": {"layer": layer, "name": p.name, "category": p.category},
                        "geometry": mapping(self.proj.to_ll(geom)),
                    })
            self._offline_map = {"type": "FeatureCollection", "features": features}
        return self._offline_map
