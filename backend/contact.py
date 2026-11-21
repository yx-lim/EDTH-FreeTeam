"""Contact reports: what a unit sees, not where it is. "Contact, two enemy tanks, moving north, 300 metres east of
the church" -> one report of type "contact" with {what, side, count, activity, heading} and the usual anchor fields.

Shaped like the SALUTE report soldiers are taught (Size, Activity, Location, Unit, Time, Equipment).

Safety rule: the side is "hostile" only when the speaker says so ("enemy", "hostile"). Anything else is "unknown"
(yellow on the map), because a misheard word must never paint a friendly unit as a target.
"""
from __future__ import annotations

import re

WHATS = ["infantry", "sniper", "tank", "apc", "vehicle", "artillery", "drone", "helicopter", "aircraft", "ied", "civilians",
         "unknown"]
# Threats named on their own are a sighting ("IED behind the town hall"); "vehicle" or "infantry" alone are not.
_ALWAYS = {"tank", "apc", "drone", "helicopter", "aircraft", "artillery", "ied", "sniper", "civilians"}
SIDES = ["hostile", "unknown", "friendly", "neutral"]
ACTIVITIES = ["moving", "static", "firing", None]

# Order matters: the first match wins ("armoured vehicle" is an apc, not a vehicle; "mortar fire" is artillery).
_WHAT = [
    ("apc", r"apcs?|ifvs?|bmps?|btrs?|armou?red (?:vehicles?|cars?|personnel carriers?)|blindes?|vbci"),
    ("tank", r"tanks?|chars?(?: d assaut)?|armou?r|t ?(?:64|72|80|90)s?|mbts?"),
    ("drone", r"drones?|uavs?|quadcopters?|fpvs?|shaheds?|lancets?"),
    ("helicopter", r"helicopters?|helos?|choppers?|helicopteres?"),
    ("aircraft", r"aircraft|planes?|jets?|avions?"),
    ("artillery", r"artillery|mortars?|shelling|rockets?|grads?|artillerie|mortiers?|obus"),
    ("ied", r"ieds?|mines?|bombs?|explosives?|booby traps?|engins? explosifs?|mines? antichars?"),
    ("sniper", r"snipers?|tireurs? d elite"),
    ("vehicle", r"vehicles?|trucks?|technicals?|pick ?ups?|vehicules?|camions?"),
    ("infantry", r"infantry|troops|soldiers|personnel|squad|platoon|dismounts?|fantassins?|soldats?|combattants?"),
    ("civilians", r"civilians?|refugees?|civils?|crowd|foule|refugies?"),
]
WHAT_RE = "|".join(f"(?P<{k}>\\b(?:{v})\\b)" for k, v in _WHAT)

_HOSTILE = r"\b(?:enemy|enemies|hostiles?|opfor|ennemis?|hostiles?|adverses?)\b"
_FRIENDLY = r"\b(?:friendly|friendlies|own forces|blue forces?|amis?|forces amies)\b"
_NEUTRAL = r"\b(?:civilians?|civils?|neutral|neutres?|refugees?|refugies?)\b"
# Words that make a clause a sighting even before the equipment is named.
_TRIGGER = r"\b(?:contact|spotted|sighted|spot|observe[ds]?|observing|seen|i see|we see|i can see|we can see|enemy|enemies|hostiles?|ennemis?|incoming|repere|reperes|vu|vus|on voit|je vois)\b"
_MOVING = r"\b(?:moving|heading|driving|flying|advancing|going|travelling|traveling|se deplacent|se dirige(?:nt)?|avancent?|roulent?)\b"
_STATIC = r"\b(?:static|stationary|parked|dug in|not moving|hovering|immobiles?|a l arret|retranches?)\b"
_FIRING = r"\b(?:firing|shooting|engaging|attacking|under fire|taking fire|incoming|tirent|tire|ouvrent le feu|sous le feu)\b"
_HEADING = (r"\b(?:towards? (?:the )?|to the |vers le |vers l |au |a l )?(?P<h>northeast|northwest|southeast|southwest|north|south|east|west"
            r"|nord est|nord ouest|sud est|sud ouest|nord|sud|est|ouest)(?:wards?)?\b")
_FR_DIRS = {"nord": "north", "sud": "south", "est": "east", "ouest": "west", "nord est": "northeast",
            "nord ouest": "northwest", "sud est": "southeast", "sud ouest": "southwest"}
_HEADING_DEG = {"north": 0.0, "northeast": 45.0, "east": 90.0, "southeast": 135.0,
                "south": 180.0, "southwest": 225.0, "west": 270.0, "northwest": 315.0}
_NUMERIC_HEADING_RE = re.compile(r"\b(?:heading|course|bearing|cap|курс)\s+(?:of\s+)?(?P<deg>\d{1,3})\b(?:\s*(?:deg|degrees|°))?", re.IGNORECASE)
_SPEED_KMH_RE = re.compile(r"(?P<v>\d+(?:[.,]\d+)?)\s*(?:km\s*(?:/|per)\s*h(?:our)?|km\s*/?\s*h|kph|kmph|kilomet(?:er|re)s?\s*(?:per|/)\s*hour|км\s*/?\s*год|км\s*/?\s*ч|км\s*(?:на|в|за)\s*годин\w*|кілометр\w*\s*(?:на|в|за)\s*годин\w*)", re.IGNORECASE)
_SPEED_MPS_RE = re.compile(r"(?P<v>\d+(?:[.,]\d+)?)\s*(?:m\s*(?:/|per)\s*s(?:ec(?:ond)?)?|met(?:er|re)s?\s*(?:per|/)\s*sec(?:ond)?|м\s*/\s*с)", re.IGNORECASE)
_SPEED_KTS_RE = re.compile(r"(?P<v>\d+(?:[.,]\d+)?)\s*(?:knots?|kts?|вузл\w*|узл\w*)", re.IGNORECASE)
_SPEED_MPH_RE = re.compile(r"(?P<v>\d+(?:[.,]\d+)?)\s*(?:mph|miles?\s*(?:per|/)\s*hour)", re.IGNORECASE)
_SPEED_QUAL_FAST = re.compile(r"\b(?:very\s+fast|fast|high\s+speed|rapid(?:ly)?|diving|full\s+speed|speeding|швидк\w*|быстр\w*|стремительн\w*)\b", re.IGNORECASE)
_SPEED_QUAL_SLOW = re.compile(r"\b(?:very\s+slow|slow(?:ly)?|loitering|cruising\s+slow|creeping|повільн\w*|медленн\w*)\b", re.IGNORECASE)
_SPEED_QUAL_HOVER = re.compile(r"\b(?:hovering|stationary|static|not\s+moving|waiting\s+on\s+the\s+ground|ждун\w*|висит\w*|висить|завис\w*)\b", re.IGNORECASE)
_SPEED_STRIP_RE = re.compile(
    r"(?:\b(?:at|around|about|speed|at\s+speed|зі\s+швидкістю|со\s+скоростью|швидкість|скорость)\s+)?"
    r"\d+(?:[.,]\d+)?\s*(?:km\s*(?:/|per)\s*h(?:our)?|km\s*/?\s*h|kph|kmph|kilomet(?:er|re)s?\s*(?:per|/)\s*hour|m\s*(?:/|per)\s*s(?:ec(?:ond)?)?|knots?|kts?|mph|км\s*/?\s*год|км\s*/?\s*ч|км\s*(?:на|в|за)\s*годин\w*|кілометр\w*\s*(?:на|в|за)\s*годин\w*|м\s*/\s*с|вузл\w*|узл\w*)",
    re.IGNORECASE,
)


def parse_speed_mps(text: str, what: str = "drone", activity: str | None = None, detail: str | None = None) -> float | None:
    """Extract explicit or qualitative speed (metres/second) from soldier input (EN/FR/UK/RU)."""
    if not text:
        return None
    for rx, factor in (
        (_SPEED_KMH_RE, 1.0 / 3.6),
        (_SPEED_MPS_RE, 1.0),
        (_SPEED_KTS_RE, 0.514444),
        (_SPEED_MPH_RE, 0.44704),
    ):
        m = rx.search(text)
        if m:
            try:
                val = float(m.group("v").replace(",", ".")) * factor
                return round(max(0.0, min(900.0, val)), 2)
            except ValueError:
                pass
    if activity == "static" or _SPEED_QUAL_HOVER.search(text):
        return 0.0
    if _SPEED_QUAL_FAST.search(text):
        return {"drone": 42.0, "helicopter": 75.0, "aircraft": 200.0, "vehicle": 28.0, "tank": 15.0}.get(what, 25.0)
    if _SPEED_QUAL_SLOW.search(text):
        return {"drone": 8.0, "helicopter": 25.0, "aircraft": 70.0, "vehicle": 6.0, "tank": 4.0}.get(what, 6.0)
    return None


def parse_heading_deg(text: str) -> float | None:
    m = _NUMERIC_HEADING_RE.search(text or "")
    if m:
        deg = float(m.group("deg"))
        if 0 <= deg <= 360:
            return deg % 360.0
    return None


# "300 metres east of me": the reporter is the reference point.
SELF = r"(?:me|us|my position|our position|my location|moi|nous|ma position|notre position)"


def starts_contact(clause: str) -> bool:
    """Does this clause begin a sighting? Needs the equipment plus a trigger word, a side word or a count
    ("two tanks"), so "I'm at the car park" or "the tank museum" alone do not count."""
    m = re.search(WHAT_RE, clause)
    if re.search(r"\bcontact\b|\bincoming\b", clause) or (m and m.lastgroup in _ALWAYS):
        return True
    return m is not None and bool(re.search(_TRIGGER, clause) or re.search(_HOSTILE, clause) or re.search(_NEUTRAL, clause)
                             or re.search(rf"\b(?:\d+|a|an|one|two|three|four|five|six|ten|several|multiple|plusieurs|un|une|deux|trois|quatre)\s+(?:\w+\s+)?(?:{WHAT_RE})", clause))


def describe(clauses: list[str], number) -> dict:
    """What, side, count, activity and heading from the clauses of one sighting."""
    text = " , ".join(clauses)
    m = re.search(WHAT_RE, text)   # the first thing named; at one spot, the earlier entry in _WHAT wins
    what = m.lastgroup if m else "artillery" if re.search(r"\bincoming\b", text) else "unknown"
    side = ("hostile" if re.search(_HOSTILE, text) else "neutral" if re.search(_NEUTRAL, text)
            else "friendly" if re.search(_FRIENDLY, text) else "unknown")
    count = None
    m = re.search(rf"(?P<n>\d+|\b(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty|un|une|deux|trois|quatre|cinq|six|dix)\b)"
                  rf"\s+(?:(?:enemy|hostile|ennemis?|enemies|civilian|armou?red|light|heavy|small|large|\w+)\s+)?(?:{WHAT_RE})", text)
    if m:
        count = number(m.group("n"))
    activity = "firing" if re.search(_FIRING, text) else "static" if re.search(_STATIC, text) else \
        "moving" if re.search(_MOVING, text) else None
    heading = None
    heading_deg = parse_heading_deg(text)
    if heading_deg is not None:
        heading = compass(heading_deg)
        if activity is None:
            activity = "moving"
    if heading is None and (activity == "moving" or re.search(_MOVING, text)):
        hm = re.search(_MOVING + r"\s+" + _HEADING, text)
        if hm:
            heading = _FR_DIRS.get(hm.group("h"), hm.group("h"))
            heading_deg = _HEADING_DEG.get(heading)
    speed_mps = parse_speed_mps(text, what=what, activity=activity)
    if speed_mps and speed_mps > 0 and activity is None:
        activity = "moving"
    out = {"what": what, "side": side, "count": int(count) if count else None, "activity": activity, "heading": heading}
    if heading_deg is not None:
        out["heading_deg"] = round(heading_deg, 1)
    if speed_mps is not None:
        out["speed_mps"] = speed_mps
    return out


def location_clauses(clauses: list[str]) -> list[str]:
    """Clauses that may say where the contact is, with the description words removed, so "moving north" is not
    read as "north of" and "towards the bridge" is not read as the contact's position."""
    out = []
    for c in clauses:
        c = _SPEED_STRIP_RE.sub(" ", c)
        c = _NUMERIC_HEADING_RE.sub(" ", c)
        c = re.sub(_MOVING + r"\s+" + _HEADING, " ", c)
        c = re.sub(_MOVING + r"\s+(?:towards?|to|vers)\s+.*", " ", c)   # a destination, not where it is now
        c = re.sub(r"\b(?:contact|spotted|sighted|observed|i see|we see|i can see|we can see|repere|on voit|je vois)\b", " ", c)
        c = re.sub(r"\s+", " ", c).strip(" ,")
        if c:
            out.append(c)
    return out


def self_anchor(report: dict, speaker: str | None) -> dict:
    """"300 metres east of me" -> anchored on the reporter's own last position."""
    a = report.get("anchor") or {}
    if a.get("name") and re.fullmatch(SELF, a["name"]):
        report["anchor"] = {"name": speaker or "me", "kind": "unit"}
        report["relative_to_reporter"] = True
    return report


def validate(c: dict | None) -> dict:
    c = c if isinstance(c, dict) else {}
    out = {
        "what": c.get("what") if c.get("what") in WHATS else "unknown",
        "side": c.get("side") if c.get("side") in SIDES else "unknown",
        "activity": c.get("activity") if c.get("activity") in ACTIVITIES else None,
        "heading": c.get("heading") if c.get("heading") in
        ("north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest") else None,
    }
    try:
        out["count"] = int(c["count"]) if c.get("count") is not None else None
    except (TypeError, ValueError):
        out["count"] = None
    # Optional, from the Ukrainian/Russian vocabulary (data/threat_vocab.csv) or the model: the specific type as the
    # troops say it, how long the sighting stays useful, the word heard, and "another one" (never merge it).
    out["detail"] = str(c["detail"])[:60] if c.get("detail") else None
    try:
        out["ttl_s"] = int(c["ttl_s"]) if c.get("ttl_s") else None
    except (TypeError, ValueError):
        out["ttl_s"] = None
    out["word"] = str(c["word"])[:40] if c.get("word") else None
    out["another"] = bool(c.get("another"))
    if c.get("heading_deg") is not None:
        try:
            hd = float(c["heading_deg"]) % 360.0
            out["heading_deg"] = round(hd, 1)
            if not out["heading"]:
                out["heading"] = compass(hd)
        except (TypeError, ValueError):
            pass
    elif out["heading"] in _HEADING_DEG:
        out["heading_deg"] = _HEADING_DEG[out["heading"]]
    if c.get("speed_mps") is not None:
        try:
            sp = float(c["speed_mps"])
            if 0.0 <= sp <= 900.0:
                out["speed_mps"] = round(sp, 2)
        except (TypeError, ValueError):
            pass
    elif c.get("speed_kmh") is not None:
        try:
            sp = float(c["speed_kmh"]) / 3.6
            if 0.0 <= sp <= 900.0:
                out["speed_mps"] = round(sp, 2)
        except (TypeError, ValueError):
            pass
    return out


# --- Tracks: one enemy seen twice is one contact, and nearby friends are warned ---------------------------------

# How long a sighting stays current (the map fades it after this): a drone has moved on in minutes, an IED stays.
# frontend/src/App.vue (CONTACT_TTL_S) mirrors this table.
TTL_S = {"drone": 180, "helicopter": 300, "aircraft": 120, "artillery": 600, "sniper": 1800, "ied": 86400,
         "civilians": 1800}
DEFAULT_TTL_S = 900
# How far a contact can plausibly have moved between two reports, for deciding whether two sightings are one.
SPEED_MPS = {"infantry": 1.5, "sniper": 1.0, "civilians": 1.5, "tank": 8.0, "apc": 10.0, "vehicle": 12.0,
             "drone": 15.0, "helicopter": 40.0, "aircraft": 100.0, "artillery": 0.0, "ied": 0.0, "unknown": 3.0}
SAME_PLACE_M = 75        # two sightings this close (edge to edge, plus movement) can be the same thing
WARN_M = 300             # a friendly unit this close to a hostile contact is warned


def ttl(c: dict | None) -> float:
    c = c or {}
    return c.get("ttl_s") or TTL_S.get(c.get("what"), DEFAULT_TTL_S)   # a parser may set its own (contact_uk.py)


def compatible(a: dict, b: dict) -> bool:
    """Could two descriptions be the same thing? Same type (or one unknown), and sides that do not contradict."""
    if a["what"] != b["what"] and "unknown" not in (a["what"], b["what"]):
        return False
    # Two named types that differ are two things: a Shahed is not the recon quad seen a minute ago. A generic word
    # ("drone", "пташка") can still be either.
    generic = {None, "drone", "quadcopter", "vehicle", "infantry", "group of people", "fixed-wing drone"}
    if a.get("detail") not in generic and b.get("detail") not in generic and a.get("detail") != b.get("detail"):
        return False
    # Flying east, then flying west half a minute later: two drones, not one that turned round.
    opposite = {("north", "south"), ("east", "west"), ("northeast", "southwest"), ("northwest", "southeast")}
    if tuple(sorted((a.get("heading") or "", b.get("heading") or ""))) in {tuple(sorted(p)) for p in opposite}:
        return False
    sides = {a["side"], b["side"]} - {"unknown"}
    return len(sides) <= 1


def combine(old: dict, new: dict) -> dict:
    """The track's description after a second sighting: the more specific type and side, the larger count, the
    latest activity and heading."""
    return {**old, **new,   # extra fields a parser adds (detail, ttl_s, speed_mps, heading_deg) carry over
            "what": new["what"] if new["what"] != "unknown" else old["what"],
            "side": new["side"] if new["side"] != "unknown" else old["side"],
            "count": max(filter(None, (old.get("count"), new.get("count"))), default=None),
            "activity": new.get("activity") or old.get("activity"),
            "heading": new.get("heading") if new.get("activity") else (new.get("heading") or old.get("heading")),
            "heading_deg": new.get("heading_deg") if new.get("heading_deg") is not None else old.get("heading_deg"),
            "speed_mps": new.get("speed_mps") if new.get("speed_mps") is not None else old.get("speed_mps")}


_POINTS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]


def compass(bearing_deg: float) -> str:
    return _POINTS[round(bearing_deg / 45) % 8]


def persistent(c: dict | None) -> bool:
    """Static hazards (mines, IEDs, fibre-optic cables, drones waiting on the ground) are never removed by age: nobody
    radios "mine cleared". Past their fresh window they stay on the map as "unconfirmed, N h old"."""
    c = c or {}
    return c.get("what") == "ied" or (c.get("ttl_s") or 0) >= 1800


# --- APP-6 / MIL-STD-2525C symbol codes, for exports (frontend/src/App.vue draws the same codes) -------------------
_SIDE_CODE = {"hostile": "H", "unknown": "U", "neutral": "N", "friendly": "F"}
_FUNCTION = {"infantry": "GPUCI", "sniper": "GPUCIS", "tank": "GPEVAT", "apc": "GPEVAA", "vehicle": "GPEV",
             "artillery": "GPUCF", "drone": "APMFQ", "helicopter": "APMH", "aircraft": "APMF", "ied": "GPEXI",
             "civilians": "GP", "unknown": "GP"}
OWN_UNIT = "GPUCI"   # friendly infantry


def sidc(c: dict | None, doubt: bool = False, side: str | None = None) -> str:
    """15-character SIDC. Status P (present, solid frame) or A (anticipated/suspected, dashed frame)."""
    c = c or {}
    f = _FUNCTION.get(c.get("what"), "GP") if side is None else OWN_UNIT
    return f"S{_SIDE_CODE.get(side or c.get('side'), 'U')}{f[0]}{'A' if doubt else 'P'}{f[2:]}".ljust(15, "-")
