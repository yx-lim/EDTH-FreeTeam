"""Transcript -> structured transmission. Uses Mistral when MISTRAL_API_KEY is set, a rule-based parser otherwise
(and as a fallback whenever the API call fails, so the map never stops updating).

A transmission can hold several reports: "Alpha one, Bravo one is at the theatre, I'm still at the fountain"
is one report about Bravo 1 and one about Alpha 1. The model is never asked for coordinates.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata

import httpx

from . import contact, lang_uk
from .geo import norm

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

RELATIONS = ["at", "near", "behind", "in_front_of", "north_of", "south_of", "east_of", "west_of",
             "northeast_of", "northwest_of", "southeast_of", "southwest_of",
             "between", "intersection", "towards", "along", "previous"]
TYPES = ["position", "movement", "correction", "holding", "intent", "contact", "other"]

SYSTEM = f"""You turn one radio transmission into JSON for a live map. It may be English or French, may contain
fillers, radio procedure ("Zero, this is Alpha two ... over") and transcription errors.
Return only a JSON object:
{{"speaker": callsign of the station transmitting, lowercase with digits ("alpha 2"), or null,
  "reports": [ one object per unit whose location is reported:
    {{"subject": callsign this report is about, or null if it is the speaker,
     "type": one of {TYPES},
     "anchor": {{"name": place name as spoken (fix obvious transcription slips), "kind": "landmark" | "street" | "intersection" | "unit"}} or null,
     "anchor2": same shape, only for "between" and "intersection", else null,
     "relation": one of {RELATIONS},
     "distance_m": metres as a number if a distance is spoken ("two hundred metres" -> 200, "a block" -> 100), else null,
     "minutes_ago": number, only for relation "previous" ("back where I was ten minutes ago"), else null,
     "confidence": 0 to 1}} ]}}
Rules:
- "X, this is Y": Y is the speaker. Callsigns use digits: "Alpha deux" -> "alpha 2".
- "correction" / "negative" / "not X, Y": report only the corrected location, with type "correction".
- "I'll be at X in five minutes": type "intent" (it is not a position).
- "holding" / "no change" / "same position": type "holding", anchor null.
- "I'm with Bravo one" / "50 m north of Bravo one": anchor kind "unit", name "bravo 1".
- A place mentioned only as context ("can see the church", "not far from the market") is not the anchor.
- Radio checks, acknowledgements ("roger", "wilco", "say again"): reports = [{{"type": "other", ...}}].
- Something SEEN (enemy, vehicles, drones, aircraft, artillery, IEDs, civilians): a separate report with type "contact",
  subject null, the anchor fields saying where the THING is, plus
  "contact": {{"what": one of {contact.WHATS}, "side": one of {contact.SIDES}, "count": number or null,
              "activity": "moving" | "static" | "firing" | null, "heading": compass direction or null}}.
  side is "hostile" ONLY if the speaker says enemy/hostile; never infer it. Otherwise "unknown" (civilians: "neutral").
  "300 m east of me" -> anchor {{"name": "me", "kind": "unit"}}, relation "east_of", distance_m 300.
  "moving north" is the heading, not the location. The speaker's own position, if also given, is its own report.
Never output coordinates. Never invent a place that was not spoken.

Examples:
"Zero this is Alpha two, uh, south of Saint Sulpice church, over" ->
{{"speaker":"alpha 2","reports":[{{"subject":null,"type":"position","anchor":{{"name":"Saint Sulpice church","kind":"landmark"}},"anchor2":null,"relation":"south_of","distance_m":null,"minutes_ago":null,"confidence":0.9}}]}}
"Charlie one and Charlie two at the corner of rue de Tournon and rue de Vaugirard" ->
{{"speaker":"charlie 1","reports":[{{"subject":"charlie 1","type":"position","anchor":{{"name":"rue de Tournon","kind":"street"}},"anchor2":{{"name":"rue de Vaugirard","kind":"street"}},"relation":"intersection","distance_m":null,"minutes_ago":null,"confidence":0.9}},{{"subject":"charlie 2","type":"position","anchor":{{"name":"rue de Tournon","kind":"street"}},"anchor2":{{"name":"rue de Vaugirard","kind":"street"}},"relation":"intersection","distance_m":null,"minutes_ago":null,"confidence":0.9}}]}}
"Alpha deux, je me dirige vers le boulevard Saint-Germain" ->
{{"speaker":"alpha 2","reports":[{{"subject":null,"type":"movement","anchor":{{"name":"boulevard Saint-Germain","kind":"street"}},"anchor2":null,"relation":"towards","distance_m":null,"minutes_ago":null,"confidence":0.9}}]}}
"Zero, Bravo one, contact, two enemy tanks moving north, three hundred metres east of the church, over" ->
{{"speaker":"bravo 1","reports":[{{"subject":null,"type":"contact","anchor":{{"name":"church","kind":"landmark"}},"anchor2":null,"relation":"east_of","distance_m":300,"minutes_ago":null,"confidence":0.8,"contact":{{"what":"tank","side":"hostile","count":2,"activity":"moving","heading":"north"}}}}]}}"""


async def extract(text: str) -> dict:
    """Returns {"speaker", "reports": [...], "extractor", "extract_ms"}."""
    t0 = time.perf_counter()
    key = os.getenv("MISTRAL_API_KEY")
    out = None
    if key:
        try:
            out = await _mistral(text, key)
            out["extractor"] = f"mistral:{MISTRAL_MODEL}"
        except Exception as err:  # network, quota, malformed JSON: degrade, don't drop the report
            out = stub_extract(text)
            out["extractor"] = f"rules (mistral failed: {type(err).__name__})"
    if out is None:
        out = stub_extract(text)
        out["extractor"] = "rules"
    out["extract_ms"] = round((time.perf_counter() - t0) * 1000)
    return out


async def _mistral(text: str, key: str) -> dict:
    payload = {
        "model": MISTRAL_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
    }
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.post(MISTRAL_URL, json=payload, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
    return validate(json.loads(r.json()["choices"][0]["message"]["content"]))


def _callsign(text: str | None) -> str | None:
    if not text:
        return None
    if lang_uk.has_cyrillic(text):
        return lang_uk.callsign(text)
    t = norm(text)
    for w, d in _DIGITS.items():
        t = re.sub(rf"\b{w}\b", d, t)
    return t or None


def validate(d: dict) -> dict:
    if "reports" not in d:   # a model that answered with a single flat report
        d = {"speaker": d.get("callsign") or d.get("speaker"), "reports": [d]}
    reports = []
    for r in d.get("reports") or []:
        if not isinstance(r, dict):
            continue
        if r.get("relation") not in RELATIONS:
            r["relation"] = "at"
        if r.get("type") not in TYPES:
            r["type"] = "position"
        for k in ("anchor", "anchor2"):
            if not (isinstance(r.get(k), dict) and r[k].get("name")):
                r[k] = None
        for k in ("distance_m", "minutes_ago"):
            try:
                r[k] = float(r[k]) if r.get(k) is not None else None
            except (TypeError, ValueError):
                r[k] = None
        r["subject"] = _callsign(r.get("subject") or r.get("callsign"))
        if r["type"] == "contact":
            r["subject"] = None   # a sighting is never a unit's own position
            r["contact"] = contact.validate(r.get("contact"))
            if (r.get("anchor") or {}).get("name") and re.fullmatch(contact.SELF, norm(r["anchor"]["name"])):
                r["anchor"] = {"name": _callsign(d.get("speaker")) or "me", "kind": "unit"}
                r["relative_to_reporter"] = True
        reports.append(r)
    return {"speaker": _callsign(d.get("speaker")), "reports": reports or [_other()]}


def _other() -> dict:
    return {"subject": None, "type": "other", "anchor": None, "anchor2": None, "relation": "at",
            "distance_m": None, "minutes_ago": None, "confidence": 0.0}


# --- Rule-based parser: offline, deterministic, and the fallback when the API fails. ----------------------------

_DIGITS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
           "nine": "9", "un": "1", "deux": "2", "trois": "3", "quatre": "4", "cinq": "5", "sept": "7", "huit": "8",
           "neuf": "9"}
_CS = (r"(?:alpha|bravo|charlie|delta|echo|foxtrot|kilo|sierra|tango|zulu|zero|command|control|hq)"
       rf"(?:\s+(?:\d+|{'|'.join(_DIGITS)})\b)?")
_NUMWORDS = {"zero": 0, "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
             "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "un": 1, "une": 1, "deux": 2,
             "trois": 3, "quatre": 4, "cinq": 5, "dix": 10, "vingt": 20, "trente": 30, "quarante": 40,
             "cinquante": 50}
_NW = "|".join(sorted(set(_NUMWORDS) | {"hundred", "thousand", "cent", "cents", "mille", "and", "et"}, key=len, reverse=True))
_NUM = rf"(?:\d+(?:\.\d+)?|(?:\b(?:{_NW})\b\s*)+)"
_UNIT = r"(?:m|meters?|metres?|yards?)"
_DIRS = {"north": "north", "south": "south", "east": "east", "west": "west", "northeast": "northeast",
         "northwest": "northwest", "southeast": "southeast", "southwest": "southwest",
         "nord": "north", "sud": "south", "est": "east", "ouest": "west"}
_DIR_EN = r"(?P<dir>northeast|northwest|southeast|southwest|north|south|east|west)"
_DIR_FR = r"(?P<dir>nord|sud|est|ouest)"
_ART = r"(?:(?:the|la|le|l|les|de|du|des)\s+)*"

# (pattern, relation); a None relation is filled from the direction group. Order matters: most specific first.
_PATTERNS = [
    (rf"(?:corner|intersection|crossing|junction) of {_ART}(?P<a>.+?) and {_ART}(?P<b>.+)", "intersection"),
    (rf"(?:carrefour|coin|croisement|angle) {_ART}(?P<a>.+?) et {_ART}(?P<b>.+)", "intersection"),
    (rf"\bbetween {_ART}(?P<a>.+?) and {_ART}(?P<b>.+)", "between"),
    (rf"\bentre {_ART}(?P<a>.+?) et {_ART}(?P<b>.+)", "between"),
    (rf"(?P<d>{_NUM}|a block|one block|two blocks)\s*{_UNIT}?\s+(?:to the\s+)?{_DIR_EN}(?:\s+side)?(?:\s+of)?\s+(?P<a>.+)", None),
    (rf"(?P<d>{_NUM})\s*{_UNIT}\s+(?:au|a l)\s*{_DIR_FR}\s+(?:de\s+|du\s+|des\s+)?(?P<a>.+)", None),
    (rf"\b(?:to the\s+|on the\s+)?{_DIR_EN}(?:\s+side)?(?:\s+of)?\s+(?P<a>.+)", None),
    (rf"\b(?:au|a l)\s*{_DIR_FR}\s+(?:de\s+|du\s+|des\s+)?(?P<a>.+)", None),
    (rf"\b(?:with|avec)\s+(?P<unit>{_CS})", "at"),
    (r"\b(?:moving|heading|going|moved|advancing|walking|proceeding|en route|headed)\s+(?:towards?|to|for)\s+(?P<a>.+)", "towards"),
    (rf"\b(?:vers|en direction\s+(?:de|du|des))\s+(?P<a>.+)", "towards"),
    (r"\b(?:moving|heading|going|moved|walking)\s+(?:along|down|up)\s+(?P<a>.+)", "along"),
    (r"\ble long (?:de|du|des)\s+(?P<a>.+)", "along"),
    (r"\b(?:behind|derriere)\s+(?P<a>.+)", "behind"),
    (r"\b(?:in front of|devant)\s+(?P<a>.+)", "in_front_of"),
    (r"\b(?:near|next to|close to|by|beside|outside|not far from|pres (?:de|du|des)|a cote (?:de|du|des))\s+(?P<a>.+)", "near"),
    (r"\b(?:at|in|on|inside|au|aux|a la|a l|sur|dans)\s+(?P<a>.+)", "at"),
]
_HOLDING = r"\b(?:holding|hold position|no change|same position|stationary|static|je ne bouge pas|pas de changement|toujours au meme endroit)\b"
_INTENT = r"\b(?:i ll be|i will be|will be at|we ll be|going to be|eta|je serai|nous serons)\b"
_PREVIOUS = rf"\bback (?:to )?where (?:i|we) (?:was|were)\s+(?P<n>{_NUM})\s*minutes? ago"
_CORRECTION = r"\b(?:correction|negative|negatif|je corrige|je rectifie)\b"
_FILLERS = r"\b(?:uh|um|er|erm|euh|ah|hmm|over|out|terminé|termine|a vous|i say again|je repete)\b"
_STREET = re.compile(r"(?:rue|boulevard|bd|avenue|av|quai|place|allee|impasse|passage|cour|carrefour|street|road)\b")


def _prep(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"['’`\-–—]", " ", t)
    t = re.sub(r"[!?:]", ",", t)
    t = re.sub(_FILLERS, " ", t)
    return re.sub(r"\s+", " ", t).strip(" ,.;")


def _number(s: str) -> float | None:
    s = s.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return float(s)
    if "block" in s:
        return 200.0 if "two" in s else 100.0
    total, cur = 0, 0
    for w in s.split():
        if w in ("and", "et"):
            continue
        if w in ("hundred", "cent", "cents"):
            cur = (cur or 1) * 100
        elif w in ("thousand", "mille"):
            total, cur = total + (cur or 1) * 1000, 0
        elif w in _NUMWORDS:
            cur += _NUMWORDS[w]
        else:
            return None
    return float(total + cur) or None


def _clean(name: str) -> str:
    name = re.split(r"[,.;]| moving | heading | and then | not | in (?:\w+ )?(?:minutes?|mins?|seconds?)\b| dans ", f"{name} ")[0]
    name = re.sub(r"^(?:(?:the|la|le|l|les|de|du|des)\s+)+", "", name.strip())
    return name.strip()


def _anchor(name: str | None) -> dict | None:
    if not name:
        return None
    name = _clean(name)
    if not name:
        return None
    kind = "street" if _STREET.match(name) or name.endswith((" street", " road")) else "landmark"
    return {"name": name, "kind": kind}


def _parse_clause(clause: str) -> dict | None:
    m = re.search(_PREVIOUS, clause)
    if m:
        return {**_other(), "type": "position", "relation": "previous", "minutes_ago": _number(m.group("n")),
                "confidence": 0.6}
    for pattern, relation in _PATTERNS:
        m = re.search(pattern, clause)
        if not m:
            continue
        g = m.groupdict()
        if g.get("unit"):
            return {**_other(), "type": "position", "relation": "at", "confidence": 0.6,
                    "anchor": {"name": _callsign(g["unit"]), "kind": "unit"}}
        rel = relation or f"{_DIRS[g['dir']]}_of"
        a = _anchor(g.get("a"))
        if not a:
            continue
        d = _number(g["d"]) if g.get("d") else None
        return {"subject": None, "type": "movement" if rel in ("towards", "along") else "position",
                "anchor": a, "anchor2": _anchor(g.get("b")), "relation": rel, "distance_m": d,
                "minutes_ago": None, "confidence": 0.5}
    if re.search(_HOLDING, clause):
        return {**_other(), "type": "holding", "confidence": 0.6}
    return None


def stub_extract(text: str) -> dict:
    if lang_uk.cyrillic_share(text) > 0.3:   # Ukrainian / Russian radio procedure and the demo grammar
        return validate(lang_uk.stub_extract_uk(text))
    t = _prep(text)
    speaker, subjects = None, None
    m = re.match(rf"(?:hello\s+|allo\s+)?(?P<to>{_CS})\s*,?\s*(?:this is|ici|de)\s+(?P<frm>{_CS})\b[\s,]*", t)
    # No addressee, as people often speak: "This is Delta three, behind the church", maybe after a false start
    # ("this is, hi, this is Delta three"). Up to five words may come before the last "this is <callsign>".
    m = m or re.match(rf"(?:[\w']+[\s,]+){{0,5}}?(?:this is|ici)\s+(?P<frm>{_CS})\b[\s,]*", t)
    # "Zero, Alpha two, ...": calling the control station without "this is". Zero never reports a position of its own.
    m = m or re.match(rf"(?P<to>zero|control|command|hq)\s*,?\s*(?P<frm>{_CS})\b[\s,]*", t)
    if m and m.group("frm") in ("zero", "control", "command", "hq"):
        m = None
    if m:
        speaker, t = _callsign(m.group("frm")), t[m.end():]
    else:
        m = re.match(rf"(?P<a>{_CS})\s+(?:and|et)\s+(?P<b>{_CS})\b[\s,]*", t)
        if m:
            subjects = [_callsign(m.group("a")), _callsign(m.group("b"))]
            speaker, t = subjects[0], t[m.end():]
        else:
            m = re.match(rf"(?P<a>{_CS})\b[\s,]*", t)
            if m and not re.match(rf"{_CS}\s+(?:is|est)\b", t):
                speaker, t = _callsign(m.group("a")), t[m.end():]

    correction = False
    marks = list(re.finditer(_CORRECTION, t))
    if marks:
        correction, before, t = True, t[:marks[-1].start()], t[marks[-1].end():].strip(" ,")
        if not any(_parse_clause(c) for c in re.split(r"\s*[,.;]\s*", t) if c):
            t = f"at {t}"   # "at Odeon station, correction, Odeon theatre"
        del before
    t = re.sub(r"\b(?:i m |i am |we re |we are )?not (?:at|near|by|in|on) [^,.;]*", " ", t)

    intent = bool(re.search(_INTENT, t))
    clauses = re.split(rf"\s*[,.;]\s*|\s+(?=(?:i m|i am|we re|we are|je suis)\b)|\s+(?={_CS}\s+(?:is|est)\b)"
                       r"|\s+(?=(?:by|near|next to|close to|beside) (?:the )?\w)", t)   # "west side of X by the Y": two clues
    reports, current = [], None
    clauses = [c.strip() for c in clauses if c and c.strip()]
    # A sighting runs from the first clause that starts one to the end of the transmission; what comes before is the
    # speaker's own position ("at the church, contact, enemy tank 200 m north of me").
    seen = next((i for i, c in enumerate(clauses) if contact.starts_contact(c)), None)
    if seen is not None:
        sighting, clauses = clauses[seen:], clauses[:seen]
        r = next((x for x in map(_parse_clause, contact.location_clauses(sighting)) if x and x["type"] == "position"), None)
        r = contact.self_anchor({**(r or _other()), "subject": None, "type": "contact"}, speaker)
        r["contact"] = contact.describe(sighting, _number)
        reports.append(r)
    for clause in clauses:
        m = re.match(rf"(?P<s>{_CS})\s+(?:is|est)\b\s*", clause)
        if m:
            current, clause = _callsign(m.group("s")), clause[m.end():]
        elif re.match(r"(?:i m|i am|we re|we are|je suis)\b", clause):
            current = None
        r = _parse_clause(clause)
        if not r:
            continue
        if intent:
            r["type"] = "intent"
        elif correction and r["type"] != "holding":
            r["type"] = "correction"
        for s in (subjects if subjects and current is None else [current]):
            reports.append({**r, "subject": s})
    # the sighting is reported first: it matters most
    return validate({"speaker": speaker, "reports": sorted(reports, key=lambda r: r["type"] != "contact") or [_other()]})
