"""Contact reports: what a unit sees, not where it is. "Contact, two enemy tanks, moving north, 300 metres east of
the church" -> one report of type "contact" with {what, side, count, activity, heading} and the usual anchor fields.

Shaped like the SALUTE report soldiers are taught (Size, Activity, Location, Unit, Time, Equipment).

Safety rule: the side is "hostile" only when the speaker says so ("enemy", "hostile"). Anything else is "unknown"
(yellow on the map), because a misheard word must never paint a friendly unit as a target.
"""
from __future__ import annotations

import re

WHATS = ["infantry", "sniper", "tank", "apc", "vehicle", "artillery", "drone", "helicopter", "aircraft", "ied", "civilians",
         "obstacle", "unknown"]
# Threats named on their own are a sighting ("IED behind the town hall"); "vehicle" or "infantry" alone are not.
_ALWAYS = {"tank", "apc", "drone", "helicopter", "aircraft", "artillery", "ied", "sniper", "civilians", "obstacle"}
# The state of a PLACE, not a thing seen: "the bridge near the Odeon is destroyed", "road blocked", "bridge reopened".
# Plotted like a persistent hazard (what "obstacle", detail "bridge destroyed"); "reopened" takes it off the map.
OBSTACLE_STATES = [
    ("reopened", r"re ?opened|repaired|passable|open again|now open|rouverte?s?|retablie?s?|reparee?s?"),
    ("destroyed", r"destroyed|blown up|blown|collapsed|demolished|detruite?s?|effondree?s?"),
    ("blocked", r"blocked|impassable|no passage|closed|cratered|bloquee?s?|coupee?s?|infranchissables?"),
    ("damaged", r"damaged|endommagee?s?"),
]
_OBSTACLE = "|".join(v for _, v in OBSTACLE_STATES)
_OBJECTS = {"bridge": r"bridges?|ponts?", "road": r"roads?|streets?|routes?|rues?|msr", "crossing": r"crossings?|junctions?|carrefours?",
            "tunnel": r"tunnels?", "building": r"buildings?|batiments?|immeubles?", "station": r"stations?|gares?"}
CLEARED = "reopened"


def obstacle_detail(text: str) -> str | None:
    """"bridge destroyed" / "road blocked" / "reopened": the state, with the kind of object when it is named."""
    said = {k for k, v in OBSTACLE_STATES if re.search(rf"\b(?:{v})\b", text)}
    state = next((s for s in ("destroyed", "blocked", "damaged", CLEARED) if s in said), None)   # the worst one said
    if state is None:
        return None
    obj = next((k for k, v in _OBJECTS.items() if re.search(rf"\b(?:{v})\b", text)), None)
    return f"{obj} {state}" if obj else state


def object_only(clause: str) -> bool:
    """"the bridge" on its own, cut off from "near the Odeon is destroyed" by the clause splitter: not a position."""
    return bool(re.fullmatch(rf"(?:the |le |la |les |l )?(?:{'|'.join(_OBJECTS.values())})", clause.strip()))


def cleared(c: dict | None) -> bool:
    """Is this the report that an obstacle is gone ("bridge reopened", "проїзд відкрито")?"""
    c = c or {}
    return c.get("what") == "obstacle" and str(c.get("detail") or "").endswith(CLEARED)
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
    ("obstacle", _OBSTACLE),
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
            else "friendly" if re.search(_FRIENDLY, text) or re.search(rf"\b(?:our|own|notre|nos)\s+(?:\w+\s+)?(?:{WHAT_RE})", text)
            else "unknown")
    count = None
    m = re.search(rf"(?P<n>\d+|\b(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty|un|une|deux|trois|quatre|cinq|six|dix)\b)"
                  rf"\s+(?:(?:enemy|hostile|ennemis?|enemies|civilian|armou?red|light|heavy|small|large|\w+)\s+)?(?:{WHAT_RE})", text)
    if m:
        count = number(m.group("n"))
    activity = "firing" if re.search(_FIRING, text) else "static" if re.search(_STATIC, text) else \
        "moving" if re.search(_MOVING, text) else None
    heading = None
    if activity == "moving" or re.search(_MOVING, text):
        hm = re.search(_MOVING + r"\s+" + _HEADING, text)
        if hm:
            heading = _FR_DIRS.get(hm.group("h"), hm.group("h"))
    out = {"what": what, "side": side, "count": int(count) if count else None, "activity": activity, "heading": heading}
    if what == "obstacle":   # a place's state: no side, no count, it does not move, and it stays until reported open
        out.update(side="unknown", count=None, activity=None, heading=None, detail=obstacle_detail(text), ttl_s=TTL_S["obstacle"])
    return out


def location_clauses(clauses: list[str]) -> list[str]:
    """Clauses that may say where the contact is, with the description words removed, so "moving north" is not
    read as "north of" and "towards the bridge" is not read as the contact's position."""
    out = []
    for c in clauses:
        c = re.sub(_MOVING + r"\s+" + _HEADING, " ", c)
        c = re.sub(_MOVING + r"\s+(?:towards?|to|vers)\s+.*", " ", c)   # a destination, not where it is now
        c = re.sub(r"\b(?:contact|spotted|sighted|observed|i see|we see|i can see|we can see|repere|on voit|je vois)\b", " ", c)
        c = re.sub(rf"\b(?:(?:is|are|was|has been|have been|est|sont) )?(?:now |completely |totally |partly )?(?:{_OBSTACLE})\b", " ", c)
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
    return out


# --- Tracks: one enemy seen twice is one contact, and nearby friends are warned ---------------------------------

# How long a sighting stays current (the map fades it after this): a drone has moved on in minutes, an IED stays.
# frontend/src/App.vue (CONTACT_TTL_S) mirrors this table.
TTL_S = {"drone": 180, "helicopter": 300, "aircraft": 120, "artillery": 600, "sniper": 1800, "ied": 86400, "obstacle": 86400,
         "civilians": 1800}
DEFAULT_TTL_S = 900
# How far a contact can plausibly have moved between two reports, for deciding whether two sightings are one.
SPEED_MPS = {"infantry": 1.5, "sniper": 1.0, "civilians": 1.5, "tank": 8.0, "apc": 10.0, "vehicle": 12.0,
             "drone": 15.0, "helicopter": 40.0, "aircraft": 100.0, "artillery": 0.0, "ied": 0.0, "obstacle": 0.0, "unknown": 3.0}
SAME_PLACE_M = 75        # two sightings this close (edge to edge, plus movement) can be the same thing
WARN_M = 300             # a friendly unit this close to a hostile contact is warned
# Things that hurt whoever walks up to them, whoever owns them: a waiting FPV ("ждун"), a mine, a tripwire, a gun, a
# sniper. Radio reports rarely say "enemy" for these ("ждун біля Сараю"), so side stays "unknown"; they warn anyway.
WARN_UNKNOWN = {"drone", "ied", "artillery", "sniper"}
DRIFT_M = 100            # most that a contact nobody called "moving" is allowed to have shifted between two reports
MOVED_MAX_M = 600        # and the most for one that is moving: beyond this a second sighting is a second contact


def warns(c: dict | None) -> bool:
    """Should a friendly unit near this contact be warned? Enemy always; unidentified only when the type is lethal."""
    c = c or {}
    return c.get("side") == "hostile" or (c.get("side") == "unknown" and c.get("what") in WARN_UNKNOWN)


def reach_m(c: dict, dt: float) -> float:
    """How far this contact may have moved in dt seconds, for deciding whether a new sighting is the same one.
    Static or firing: nowhere (a ждун waits, a mine stays). Reported moving: its speed, capped. Not said: a little."""
    if c.get("activity") in ("static", "firing") or not SPEED_MPS.get(c.get("what"), 3.0):
        return 0.0
    far = SPEED_MPS.get(c.get("what"), 3.0) * max(0.0, dt)
    return min(far, MOVED_MAX_M if c.get("activity") == "moving" or c.get("heading") else DRIFT_M)


def ttl(c: dict | None) -> float:
    c = c or {}
    return c.get("ttl_s") or TTL_S.get(c.get("what"), DEFAULT_TTL_S)   # a parser may set its own (contact_uk.py)


def compatible(a: dict, b: dict) -> bool:
    """Could two descriptions be the same thing? Same type (or one unknown), and sides that do not contradict."""
    if a["what"] != b["what"] and "unknown" not in (a["what"], b["what"]):
        return False
    # Two named types that differ are two things: a Shahed is not the recon quad seen a minute ago. A generic word
    # ("drone", "пташка") can still be either.
    if a["what"] == b["what"] == "obstacle":   # damaged, then destroyed, then reopened: one place, its state changing
        return True
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
    return {**old, **new,   # extra fields a parser adds (detail, ttl_s) carry over
            "what": new["what"] if new["what"] != "unknown" else old["what"],
            "side": new["side"] if new["side"] != "unknown" else old["side"],
            "count": max(filter(None, (old.get("count"), new.get("count"))), default=None),
            "activity": new.get("activity") or old.get("activity"),
            "heading": new.get("heading") if new.get("activity") else (new.get("heading") or old.get("heading"))}


_POINTS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]


def compass(bearing_deg: float) -> str:
    return _POINTS[round(bearing_deg / 45) % 8]


def persistent(c: dict | None) -> bool:
    """Static hazards (mines, IEDs, fibre-optic cables, drones waiting on the ground) are never removed by age: nobody
    radios "mine cleared". Past their fresh window they stay on the map as "unconfirmed, N h old"."""
    c = c or {}
    return c.get("what") in ("ied", "obstacle") or (c.get("ttl_s") or 0) >= 1800


# --- APP-6 / MIL-STD-2525C symbol codes, for exports (frontend/src/App.vue draws the same codes) -------------------
_SIDE_CODE = {"hostile": "H", "unknown": "U", "neutral": "N", "friendly": "F"}
_FUNCTION = {"infantry": "GPUCI", "sniper": "GPUCIS", "tank": "GPEVAT", "apc": "GPEVAA", "vehicle": "GPEV",
             "artillery": "GPUCF", "drone": "APMFQ", "helicopter": "APMH", "aircraft": "APMF", "ied": "GPEXI",
             "civilians": "GP", "obstacle": "GP", "unknown": "GP"}
OWN_UNIT = "GPUCI"   # friendly infantry


def sidc(c: dict | None, doubt: bool = False, side: str | None = None) -> str:
    """15-character SIDC. Status P (present, solid frame) or A (anticipated/suspected, dashed frame)."""
    c = c or {}
    f = _FUNCTION.get(c.get("what"), "GP") if side is None else OWN_UNIT
    return f"S{_SIDE_CODE.get(side or c.get('side'), 'U')}{f[0]}{'A' if doubt else 'P'}{f[2:]}".ljust(15, "-")
