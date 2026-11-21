"""Transcript -> structured transmission. Uses Gemini when GEMINI_API_KEY is set, else Mistral when MISTRAL_API_KEY is
set (EXTRACTOR=gemini|mistral|rules forces one), and a rule-based parser otherwise and as a fallback whenever the API
call fails, so the map never stops updating.

A transmission can hold several reports: "Alpha one, Bravo one is at the theatre, I'm still at the fountain"
is one report about Bravo 1 and one about Alpha 1. The model is never asked for coordinates.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import unicodedata

import httpx

from . import callsign, contact, grid, lang_uk
from .geo import norm

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

_offline_mode: bool = False


def set_offline(enabled: bool) -> bool:
    global _offline_mode
    _offline_mode = bool(enabled)
    return _offline_mode


def is_offline() -> bool:
    return _offline_mode or (os.getenv("EXTRACTOR") or "").lower() == "rules"

RELATIONS = ["at", "near", "behind", "in_front_of", "north_of", "south_of", "east_of", "west_of",
             "northeast_of", "northwest_of", "southeast_of", "southwest_of",
             "between", "intersection", "towards", "along", "previous",
             "opposite", "inside", "around", "from", "bearing", "left_of", "right_of"]
# Spoken compass points, 16 of them, as bearings clockwise from north.
COMPASS = {"north": 0, "north northeast": 22.5, "northeast": 45, "east northeast": 67.5, "east": 90,
           "east southeast": 112.5, "southeast": 135, "south southeast": 157.5, "south": 180, "south southwest": 202.5,
           "southwest": 225, "west southwest": 247.5, "west": 270, "west northwest": 292.5, "northwest": 315,
           "north northwest": 337.5}
TYPES = ["position", "movement", "correction", "holding", "intent", "contact", "other"]

SYSTEM = f"""You turn one radio transmission into JSON for a live map. It may be English or French, may contain
fillers, radio procedure ("Zero, this is Alpha two ... over") and transcription errors.
Return only a JSON object:
{{"speaker": callsign of the station transmitting, lowercase with digits ("alpha 2"), or null,
  "reports": [ one object per unit whose location is reported:
    {{"subject": callsign this report is about, or null if it is the speaker,
     "type": one of {TYPES},
     "anchor": {{"name": place name as spoken (fix obvious transcription slips), "kind": "landmark" | "street" | "intersection" | "unit" | "grid"}} or null,
     "anchor2": same shape, only for "between" and "intersection", else null,
     "relation": one of {RELATIONS},
     "distance_m": metres as a number if a distance is spoken, converted to metres ("two hundred metres" -> 200,
                   "a block" -> 100, "half a click"/"half a kilometre" -> 500, "100 yards" -> 91, "300 feet" -> 91,
                   "50 paces" -> 38, "five minutes' walk" -> 400, "a stone's throw" -> 50), else null,
     "distance_min_m" / "distance_max_m": only for a spoken range ("200 to 300 metres", "between 2 and 3 hundred"),
     "vague": true if the distance is approximate ("about", "roughly", "a couple of hundred", "a few hundred",
              "maybe", "some"), else omit,
     "bearing_deg": only for relation "bearing": degrees clockwise from north ("bearing 045" -> 45, "1600 mils" ->
                    90 (NATO mils, 6400 to a circle), "азимут 15-00" -> 90 (goniometer divisions, 60-00 to a circle),
                    "азимут сорок п'ять" -> 45, "north-northeast" -> 22.5),
     "minutes_ago": number, only for relation "previous" ("back where I was ten minutes ago"), else null,
     "quantity": integer count of units/vehicles/personnel if mentioned (e.g. "2 tanks" -> 2, "3 infantry" -> 3, "squad of 6" -> 6), else null,
     "summary_en": concise English tactical summary (<= 15 words) when the transcript is Ukrainian, Russian, or French, else null,
     "confidence": 0 to 1}} ]}}
Rules:
- "X, this is Y": Y is the speaker. Callsigns use digits: "Alpha deux" -> "alpha 2".
- "correction" / "negative" / "not X, Y": report only the corrected location, with type "correction".
- "I'll be at X in five minutes" / "je serai à X" / "ETA": type "intent" (explicit future tense only; present tense like "I am" or "je suis" is ALWAYS "position", never "intent").
- "holding" / "no change" / "same position": type "holding", anchor null.
- "I'm with Bravo one" / "50 m north of Bravo one": anchor kind "unit", name "bravo 1".
- A grid reference ("grid 512 110", "grid three one uniform delta quebec five one two one one zero"): anchor
  {{"name": "<the grid as spoken, digits and letters only, e.g. 512 110 or 31U DQ 512 110>", "kind": "grid"}},
  relation "at". If a landmark is also given for the same position, add "fallback": {{"anchor": that landmark,
  "relation": ..., "distance_m": ...}}. Never compute coordinates from a grid yourself.
- Relations, with the words that mean them:
  "at": at / in / on. "inside": inside / within / in the courtyard of / dans / всередині.
  "near": near / next to / beside / by / outside / close to. "around": in the area of / somewhere around / in the
  vicinity of / в районі. "opposite": opposite / across from / across the street from / facing / en face de /
  навпроти. "behind": behind / past / beyond / on the far side of / the other side of / за. "in_front_of": in front
  of / short of / just before / this side of / before reaching / перед. "left_of" / "right_of": to the left / right
  of (from the speaker's side) / ліворуч / праворуч від. Compass "north_of" etc. for the 8 main points; for the 16-point
  ones ("north-northeast of"), a numeric bearing ("bearing 120 from X", "azimuth 3200 mils"), use "bearing" with
  bearing_deg. "from": a distance with no direction ("300 metres from the church", "five minutes from the station").
- A place mentioned only as context ("can see the church", "not far from the market") is not the anchor.
- Radio checks, acknowledgements ("roger", "wilco", "say again"): reports = [{{"type": "other", ...}}].
- Something SEEN (enemy, vehicles, drones, aircraft, artillery, IEDs, civilians): a separate report with type "contact",
  subject null, the anchor fields saying where the THING is, plus
  "contact": {{"what": one of {contact.WHATS}, "side": one of {contact.SIDES}, "count": number or null,
              "activity": "moving" | "static" | "firing" | null, "heading": compass direction or null}}.
  A PLACE reported destroyed, damaged, blocked or reopened ("the bridge near the Odeon is destroyed", "міст біля Ромашки
  знищено, проїзду нема"): what "obstacle", side "unknown", plus "detail": the object and state in English, e.g.
  "bridge destroyed", "road blocked", "building damaged", "bridge reopened". The anchor is where it is.
  side is "hostile" ONLY if the speaker says enemy/hostile; never infer it. Otherwise "unknown" (civilians: "neutral").
  "300 m east of me" -> anchor {{"name": "me", "kind": "unit"}}, relation "east_of", distance_m 300.
  "moving north" is the heading, not the location. The speaker's own position, if also given, is its own report.
Ukrainian and Russian (and mixtures with English, "surzhyk"):
- Procedure: "Вежа, я Сокіл, ..., прийом" = "Tower, this is Sokil, ..., over": the speaker is the word after "я"
  ("this is"), lowercase as spoken ("сокіл", "граніт 2"). "Башня" is the Russian "Вежа" (control). "прийом"/"приём" =
  over. "плюс"/"прийняв"/"принял" = roger (type "other"). "мінус"/"отставить"/"відставити" = correction.
  "без змін"/"без изменений"/"там само" = holding. "буду через ..." = intent.
- Keep place names and codenames in the original language and script, in the nominative case if obvious
  ("від Сараю" -> "Сарай", "на Ромашці" -> "Ромашка", "орієнтир три" -> "Орієнтир 3"). Never translate them.
- Number words become numbers ("двісті п'ятдесят" -> 250, "полтораста" -> 150). "метрів сто" (number after the unit)
  is approximate: add "vague": true to the report.
- Directions: "на схід від X"/"восточнее X"/"к востоку от X" -> east_of X; same for the other seven.
- Sightings: drone slang is a "drone" contact: ждун (FPV waiting on the ground: activity "static"), мопед/шахед
  (Shahed), пташка/птичка (any drone), мавік (recon quad), орлан (recon wing), ланцет, фпв. "бачу трьох" (I see three)
  is infantry, count 3. Put the word as spoken in "contact.word". "ворог"/"противник" = hostile. "ще один"/"ещё один"
  = another one: "contact.another": true. "над X" (above X) -> relation "at" X; "над нами" -> anchor kind "unit", name
  "me". "йде на схід"/"курс захід" is the heading, not the location.
- Relative dead-reckoning without a named place ("moving 200m north", "we go left 200m forward", "Ми йдемо наліво на двісті метрів вперед", "je vais 100m à droite"): type "movement", anchor {{"name": "me", "kind": "unit"}}, distance_m, and relation ("north_of"/"east_of"/etc. for compass, "in_front_of" for forward/вперед, "left_of" for left/наліво, "right_of" for right/направо, "behind" for back/назад; for front-left use relation "bearing" with bearing_deg 315, front-right bearing_deg 45).
Never output coordinates. Never invent a place that was not spoken.

Examples:
"Zero this is Alpha two, uh, south of Saint Sulpice church, over" ->
{{"speaker":"alpha 2","reports":[{{"subject":null,"type":"position","anchor":{{"name":"Saint Sulpice church","kind":"landmark"}},"anchor2":null,"relation":"south_of","distance_m":null,"minutes_ago":null,"confidence":0.9}}]}}
"Charlie one and Charlie two at the corner of rue de Tournon and rue de Vaugirard" ->
{{"speaker":"charlie 1","reports":[{{"subject":"charlie 1","type":"position","anchor":{{"name":"rue de Tournon","kind":"street"}},"anchor2":{{"name":"rue de Vaugirard","kind":"street"}},"relation":"intersection","distance_m":null,"minutes_ago":null,"confidence":0.9}},{{"subject":"charlie 2","type":"position","anchor":{{"name":"rue de Tournon","kind":"street"}},"anchor2":{{"name":"rue de Vaugirard","kind":"street"}},"relation":"intersection","distance_m":null,"minutes_ago":null,"confidence":0.9}}]}}
"Alpha deux, je me dirige vers le boulevard Saint-Germain" ->
{{"speaker":"alpha 2","reports":[{{"subject":null,"type":"movement","anchor":{{"name":"boulevard Saint-Germain","kind":"street"}},"anchor2":null,"relation":"towards","distance_m":null,"minutes_ago":null,"summary_en":"Alpha 2 moving towards Boulevard Saint-Germain","confidence":0.9}}]}}
"Zero, Bravo one, contact, two enemy tanks moving north, three hundred metres east of the church, over" ->
{{"speaker":"bravo 1","reports":[{{"subject":null,"type":"contact","anchor":{{"name":"church","kind":"landmark"}},"anchor2":null,"relation":"east_of","distance_m":300,"minutes_ago":null,"quantity":2,"confidence":0.8,"contact":{{"what":"tank","side":"hostile","count":2,"activity":"moving","heading":"north"}}}}]}}
"Вежа, я Граніт, мінус, мінус, не Сарай. Сто метрів на південь від Ромашки, прийом." ->
{{"speaker":"граніт","reports":[{{"subject":null,"type":"correction","anchor":{{"name":"Ромашка","kind":"landmark"}},"anchor2":null,"relation":"south_of","distance_m":100,"minutes_ago":null,"summary_en":"Granit correction: 100m south of Romashka","confidence":0.9}}]}}
"Вежа, я Лис, ждун біля Сараю, метрів п'ятдесят на захід, не підходити, прийом." ->
{{"speaker":"лис","reports":[{{"subject":null,"type":"contact","anchor":{{"name":"Сарай","kind":"landmark"}},"anchor2":null,"relation":"west_of","distance_m":50,"vague":true,"minutes_ago":null,"quantity":1,"summary_en":"Lys reports 1 static FPV drone 50m west of Sarai","confidence":0.8,"contact":{{"what":"drone","side":"unknown","count":1,"activity":"static","heading":null,"word":"ждун"}}}}]}}"""


def model() -> tuple[str, str, str] | None:
    """(name, label, key) of the language model to use, or None for the rules."""
    if _offline_mode:
        return None
    chosen = (os.getenv("EXTRACTOR") or "").lower()
    options = [("gemini", GEMINI_MODEL, os.getenv("GEMINI_API_KEY")), ("mistral", MISTRAL_MODEL, os.getenv("MISTRAL_API_KEY"))]
    for name, label, key in options:
        if key and chosen in ("", name):
            return name, f"{name}:{label}", key
    return None


async def extract(text: str) -> dict:
    """Returns {"speaker", "reports": [...], "extractor", "extract_ms"}."""
    t0 = time.perf_counter()
    text = callsign.snap(text)   # misheard NATO callsigns ("Alfa won") back to "Alpha 1" before anything reads them
    chosen = model()
    out = None
    if chosen:
        name, label, key = chosen
        try:
            out = await (_gemini if name == "gemini" else _mistral)(text, key)
            out["extractor"] = label
            if lang_uk.has_cyrillic(text):
                _enrich_uk(out, text)
        except Exception as err:  # network, quota, malformed JSON: degrade, don't drop the report
            out = stub_extract(text)
            out["extractor"] = f"rules ({name} failed: {type(err).__name__})"
    if out is None:
        out = stub_extract(text)
        out["extractor"] = "rules (offline)" if _offline_mode else "rules"
        if lang_uk.has_cyrillic(text):
            _enrich_uk(out, text)
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


async def _gemini(text: str, key: str) -> dict:
    gen_cfg: dict = {"temperature": 0, "responseMimeType": "application/json"}
    if "3.5" in GEMINI_MODEL or "2.5" in GEMINI_MODEL:
        gen_cfg["thinkingConfig"] = {"thinkingLevel": "MINIMAL"}
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": gen_cfg,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        for attempt in range(2):   # "high demand" spikes are brief: one quick retry, then the rules take over
            r = await client.post(GEMINI_URL.format(model=GEMINI_MODEL), json=payload, headers={"x-goog-api-key": key})
            if r.status_code == 400 and "thinkingConfig" in payload["generationConfig"]:
                payload["generationConfig"].pop("thinkingConfig", None)
                r = await client.post(GEMINI_URL.format(model=GEMINI_MODEL), json=payload, headers={"x-goog-api-key": key})
            if r.status_code not in (429, 500, 503) or attempt:
                break
            await asyncio.sleep(0.3)
        r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return validate(json.loads("".join(p.get("text", "") for p in parts)))


def _callsign(text: str | None) -> str | None:
    if not text:
        return None
    if lang_uk.has_cyrillic(text):
        return lang_uk.callsign(text)
    t = norm(text)
    for w, d in _DIGITS.items():
        t = re.sub(rf"\b{w}\b", d, t)
    return callsign.canonical(t) or None   # "alfa 1" -> "alpha 1", "charly too" -> "charlie 2"


def _enrich_uk(out: dict, text: str) -> None:
    """The model names the thing; the vocabulary knows how long it matters and which systems only the enemy flies.
    Adds detail / ttl_s (and hostile for Shahed, Orlan, Lancet...) to Ukrainian/Russian sightings from the model."""
    from . import contact_uk
    for r in out["reports"]:
        if r["type"] == "contact":
            known = contact_uk.describe(r["contact"].get("word") or text)
            c = r["contact"]
            for k in ("detail", "ttl_s", "word"):
                c[k] = c.get(k) or known.get(k)
            if known["side"] == "hostile" and c["side"] == "unknown":
                c["side"] = "hostile"
        if not r.get("summary_en"):
            anchor_name = (r.get("anchor") or {}).get("name") or ""
            rel = (r.get("relation") or "at").replace("_", " ")
            dist = f"{round(r['distance_m'])}m " if r.get("distance_m") else ""
            loc = f"{dist}{rel} {anchor_name}".strip() if anchor_name else ""
            if r["type"] == "contact" and r.get("contact"):
                c = r["contact"]
                qty = f"{c['count']}x " if c.get("count") else ""
                act = f" ({c['activity']})" if c.get("activity") else ""
                hdg = f" heading {c['heading']}" if c.get("heading") else ""
                r["summary_en"] = f"{qty}{c.get('side', 'unknown')} {c.get('what', 'contact')}{act}{hdg} {loc}".strip()
            elif loc:
                r["summary_en"] = f"{r['type'].capitalize()} {loc}".strip()


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
        a = r["anchor"]
        if a and (a.get("kind") == "grid" or re.match(r"grid\b", norm(a["name"]))):
            g = grid.grid_name(str(a["name"]))   # "512 110" -> "512110"; full grids -> "31UDQ512110"; junk -> None
            r["anchor"] = g and {"name": g[0], "kind": "grid", "doubt": a.get("doubt") or g[1]}
        if "fallback" in r:
            fb = r["fallback"]
            r["fallback"] = fb if isinstance(fb, dict) and (fb.get("anchor") or {}).get("name") else None
        for k in ("distance_m", "minutes_ago", "distance_min_m", "distance_max_m", "bearing_deg"):
            if k not in r and k not in ("distance_m", "minutes_ago"):
                continue
            try:
                r[k] = float(r[k]) if r.get(k) is not None else None
            except (TypeError, ValueError):
                r[k] = None
        if r["relation"] == "bearing" and r.get("bearing_deg") is None:
            r["relation"] = "around"   # a bearing nobody gave: say "somewhere around", never invent a direction
        if r.get("distance_m") is None and r.get("distance_min_m") and r.get("distance_max_m"):
            r["distance_m"] = (r["distance_min_m"] + r["distance_max_m"]) / 2
        r["subject"] = _callsign(r.get("subject") or r.get("callsign"))
        if r["type"] == "contact":
            r["subject"] = None   # a sighting is never a unit's own position
            r["contact"] = contact.validate(r.get("contact"))
            if r.get("quantity") and not r["contact"].get("count"):
                try:
                    r["contact"]["count"] = max(1, int(r["quantity"]))
                except (TypeError, ValueError):
                    pass
            elif r["contact"].get("count") and not r.get("quantity"):
                r["quantity"] = r["contact"]["count"]
            if (r.get("anchor") or {}).get("name") and re.fullmatch(contact.SELF, norm(r["anchor"]["name"])):
                r["anchor"] = {"name": _callsign(d.get("speaker")) or "me", "kind": "unit"}
                r["relative_to_reporter"] = True
        elif r.get("quantity") is not None:
            try:
                r["quantity"] = max(1, int(r["quantity"]))
            except (TypeError, ValueError):
                r["quantity"] = None
        reports.append(r)
    return {"speaker": _callsign(d.get("speaker")), "reports": reports or [_other()]}


def _other() -> dict:
    return {"subject": None, "type": "other", "anchor": None, "anchor2": None, "relation": "at",
            "distance_m": None, "minutes_ago": None, "confidence": 0.0}


# --- Rule-based parser: offline, deterministic, and the fallback when the API fails. ----------------------------

_DIGITS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
           "nine": "9", "un": "1", "deux": "2", "trois": "3", "quatre": "4", "cinq": "5", "sept": "7", "huit": "8",
           "neuf": "9"}
_NUMBER = rf"(?:\d+|{'|'.join(_DIGITS)})"
# Letters that are rarely ordinary words may stand alone ("this is Bravo"); the rest need their number ("Hotel 2"),
# or "the hotel" would become a callsign. backend/callsign.py has already fixed misheard spellings.
_CS = (r"(?:(?:alpha|bravo|charlie|delta|echo|foxtrot|kilo|sierra|tango|zulu|zero|command|control|hq)"
       rf"(?:\s+{_NUMBER}\b)?"
       r"|(?:golf|hotel|india|juliet|lima|mike|november|oscar|papa|quebec|romeo|uniform|victor|whiskey|xray|yankee)"
       rf"\s+{_NUMBER}\b)")
_NUMWORDS = {"zero": 0, "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
             "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
             "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "un": 1, "une": 1, "deux": 2,
             "trois": 3, "quatre": 4, "cinq": 5, "dix": 10, "vingt": 20, "trente": 30, "quarante": 40,
             "cinquante": 50}
_NW = "|".join(sorted(set(_NUMWORDS) | {"hundred", "thousand", "cent", "cents", "mille", "and", "et"}, key=len, reverse=True))
_NUM = rf"(?:\d+(?:\.\d+)?|(?:\b(?:{_NW})\b\s*)+)"
_UNIT = r"(?:m|meters?|metres?)"
# Every spoken distance is rewritten to "<n> m" before the patterns run (see _distances): units, ranges, "about".
_UNITS = {r"kilomet(?:re|er)s?|km|klicks?|clicks?": 1000, r"met(?:re|er)s?|m": 1, r"yards?|yds?": 0.9144,
          r"feet|foot|ft": 0.3048, r"paces?|steps?": 0.75, r"blocks?": 100,
          r"minutes?\s+(?:walk|on foot|away on foot)|mins?\s+walk|minutes? a pied": 80}
_UNIT_ANY = "|".join(f"(?:{u})" for u in _UNITS)
_APPROX = (r"(?:about|around|roughly|approximately|approx|some|maybe|perhaps|circa|nearly|almost|give or take|"
           r"environ|a peu pres|a vue de nez|une?\s+(?=\d))")
_COMPASS16 = r"(?P<c16>north northeast|east northeast|east southeast|south southeast|south southwest|west southwest|west northwest|north northwest)"
_DIGIT_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
                "seven": "7", "eight": "8", "nine": "9", "niner": "9"}
_DIRS = {"north": "north", "south": "south", "east": "east", "west": "west", "northeast": "northeast",
         "northwest": "northwest", "southeast": "southeast", "southwest": "southwest",
         "nord": "north", "sud": "south", "est": "east", "ouest": "west"}
_DIR_EN = r"(?P<dir>northeast|northwest|southeast|southwest|north|south|east|west)"
_DIR_FR = r"(?P<dir>nord|sud|est|ouest)"
_ART = r"(?:(?:the|la|le|l|les|de|du|des)\s+)*"

# (pattern, relation); a None relation is filled from the direction group. Order matters: most specific first.
_BEARING = r"(?:on\s+)?(?:a\s+)?(?:grid\s+|magnetic\s+)?(?:bearing|azimuth|azimut|cap)\s+(?P<deg>\d{1,4}(?:\.\d)?)\s*(?P<bu>degrees?|deg|mils?)?"
_PATTERNS = [
    (rf"(?:(?P<d>{_NUM})\s*{_UNIT}\s+)?{_BEARING}\s*,?\s*(?:(?P<d2>{_NUM})\s*{_UNIT}\s+)?(?:from|of|de|du|des|depuis)\s+{_ART}(?P<a>.+)", "bearing"),
    (rf"(?:(?P<d>{_NUM})\s*{_UNIT}\s+)?(?:to the\s+)?{_COMPASS16}(?:\s+side)?(?:\s+of)?\s+(?P<a>.+)", "bearing"),
    (rf"(?:corner|intersection|crossing|junction) of {_ART}(?P<a>.+?) and {_ART}(?P<b>.+)", "intersection"),
    (rf"(?:carrefour|coin|croisement|angle) {_ART}(?P<a>.+?) et {_ART}(?P<b>.+)", "intersection"),
    (rf"\bbetween {_ART}(?P<a>.+?) and {_ART}(?P<b>.+)", "between"),
    (rf"\bentre {_ART}(?P<a>.+?) et {_ART}(?P<b>.+)", "between"),
    (rf"(?P<d>{_NUM}|a block|one block|two blocks)\s*{_UNIT}?\s+(?:to the\s+)?{_DIR_EN}(?:\s+side)?(?:\s+of)?\s+(?P<a>.+)", None),
    (rf"(?P<d>{_NUM})\s*{_UNIT}\s+(?:au|a l)\s*{_DIR_FR}\s+(?:de\s+|du\s+|des\s+)?(?P<a>.+)", None),
    (rf"\b(?:to the\s+|on the\s+)?{_DIR_EN}(?:\s+side)?(?:\s+of)?\s+(?P<a>.+)", None),
    (rf"\b(?:au|a l)\s*{_DIR_FR}\s+(?:de\s+|du\s+|des\s+)?(?P<a>.+)", None),
    (rf"\b(?:with|avec)\s+(?P<unit>{_CS})", "at"),
    (rf"(?P<d>{_NUM})\s*{_UNIT}\s+(?:away\s+)?(?:from|de|du|des)\s+{_ART}(?P<a>.+)", "from"),
    (rf"\ba\s+(?P<d>{_NUM})\s*{_UNIT}\s+(?:de|du|des)\s+(?P<a>.+)", "from"),
    (r"\b(?:opposite|across (?:the (?:street|road|square) )?from|facing|en face (?:de|du|des))\s+(?P<a>.+)", "opposite"),
    (r"\b(?:inside|within|in the (?:courtyard|grounds|garden|gardens|yard) of|a l interieur (?:de|du|des))\s+(?P<a>.+)", "inside"),
    (r"\b(?:(?:just\s+)?past|beyond|on the (?:far|other) side of|the (?:far|other) side of|au dela (?:de|du|des))\s+(?P<a>.+)", "behind"),
    (r"\b(?:(?:just\s+)?short of|just before|this side of|before reaching|before you reach|juste avant)\s+(?P<a>.+)", "in_front_of"),
    (r"\b(?:(?:to|on) the left (?:of|side of)|left of|a gauche (?:de|du|des))\s+(?P<a>.+)", "left_of"),
    (r"\b(?:(?:to|on) the right (?:of|side of)|right of|a droite (?:de|du|des))\s+(?P<a>.+)", "right_of"),
    (r"\b(?:in the (?:area|vicinity|neighbourhood|neighborhood) of|somewhere (?:around|near)|around|aux alentours (?:de|du|des)|dans le secteur (?:de|du|des)|du cote (?:de|du|des))\s+(?!\d)(?P<a>.+)", "around"),
    (r"\b(?:moving|heading|going|moved|advancing|walking|proceeding|en route|headed)\s+(?:towards?|to|for)\s+(?P<a>.+)", "towards"),
    (rf"\b(?:vers|en direction\s+(?:de|du|des))\s+(?P<a>.+)", "towards"),
    (r"\b(?:moving|heading|going|moved|walking)\s+(?:along|down|up)\s+(?P<a>.+)", "along"),
    (r"\ble long (?:de|du|des)\s+(?P<a>.+)", "along"),
    (r"\b(?:behind|derriere)\s+(?P<a>.+)", "behind"),
    (r"\b(?:over|above|overhead|au dessus (?:de|du|des))\s+(?P<a>.+)", "at"),   # an aircraft or drone above a place
    (r"\b(?:in front of|devant)\s+(?P<a>.+)", "in_front_of"),
    (r"\b(?:near|next to|close to|by|beside|outside|not far from|pres (?:de|du|des)|a cote (?:de|du|des))\s+(?P<a>.+)", "near"),
    (r"\b(?:at|in|on|au|aux|a la|a l|sur|dans)\s+(?P<a>.+)", "at"),
]
_HOLDING = r"\b(?:holding|hold position|no change|same position|stationary|static|je ne bouge pas|pas de changement|toujours au meme endroit)\b"
_NOT_SEEN = (r"\b(?:no (?:enemy|enemies|hostiles?|contacts?|movement|activity|sign|sightings?|tanks?|drones?|vehicles?|infantry|troops)"
             r"|negative (?:contact|sighting)|nothing (?:seen|heard|observed|to report)|aucun ennemi|pas d ennemis?|rien a signaler)\b")
_HEARSAY = r"\b(?:yesterday|last night|earlier today|(?:was|were|been) reported|reported (?:at|near|in|by|around)|reportedly|rumou?red|hier)\b"
_INTENT = r"\b(?:i ll be|i will be|will be at|we ll be|going to be|eta|je serai|nous serons)\b"
_PREVIOUS = rf"\bback (?:to )?where (?:i|we) (?:was|were)\s+(?P<n>{_NUM})\s*minutes? ago"
_CORRECTION = r"\b(?:correction|negative|negatif|je corrige|je rectifie)\b"
_FILLERS = r"\b(?:uh|um|er|erm|euh|ah|hmm|out|terminé|termine|a vous|i say again|je repete)\b"
_STREET = re.compile(r"(?:rue|boulevard|bd|avenue|av|quai|place|allee|impasse|passage|cour|carrefour|street|road)\b")


def _prep(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"['’`\-–—]", " ", t)
    t = re.sub(r"[!?:]", ",", t)
    # "over" is procedure when it closes a transmission (end, punctuation, "over and out", or the next call), but a
    # place when something follows it: "drone flying west over the Odeon theatre".
    t = re.sub(r"\bover and out\b", " ", t)
    t = re.sub(rf"\bover\b(?=\s*(?:$|[,.;]|out\b|over\b|(?:this is\s+)?{_CS}\b))", " ", t)
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


def _distances(clause: str) -> tuple[str, dict]:
    """Spoken distances -> "<n> m", so one set of patterns serves every unit. Returns the clause and what it learnt:
    {"vague": True} for approximate distances, and distance_min_m / distance_max_m for a range."""
    info: dict = {}
    c = clause
    # Bearings read digit by digit: "bearing zero four five" -> "bearing 045"
    c = re.sub(r"\b(bearing|azimuth|azimut|cap)\s+((?:(?:zero|oh|one|two|three|four|five|six|seven|eight|niner|nine)\b(?!\s+(?:hundred|thousand))\s*){2,4})",
               lambda m: f"{m.group(1)} " + "".join(_DIGIT_WORDS[w] for w in m.group(2).split()) + " ", c)
    # "sixteen hundred mils", "forty five degrees": an angle said in words
    c = re.sub(rf"\b(?P<n>{_NUM})\s*(?P<u>mils?|degrees?)\b",
               lambda m: f"{int(v)} {m['u']}" if (v := _number(m["n"])) is not None else m[0], c)
    fixed = [(r"\bhalf (?:a |an )?(?:kilomet(?:re|er)|km|klick|click)\b", "500 m", False),
             (r"\b(?:a )?(?:couple|coupla)(?: of)? hundred(?: (?:metres?|meters?|m))?\b", "200 m", True),
             (r"\b(?:a )?few hundred(?: (?:metres?|meters?|m))?\b", "300 m", True),
             (r"\b(?:a )?stone s throw(?: away)?\b", "50 m", True),
             (r"\b(?:a )?(?:click|klick)\b(?! \d)", "1000 m", False)]
    for pat, repl, vague in fixed:
        if re.search(pat, c):
            c = re.sub(pat, repl, c)
            info["vague"] = info.get("vague") or vague

    def unit_factor(u: str) -> float:
        return next(f for pat, f in _UNITS.items() if re.fullmatch(pat, u))

    def to_m(m: re.Match) -> str:
        f = unit_factor(m.group("u"))
        a = _number(m.group("n"))
        if a is None:
            return m.group(0)
        if m.group("n2"):
            b = _number(m.group("n2"))
            if b is not None:
                lo, hi = sorted((a * f, b * f))
                info.update(distance_min_m=round(lo), distance_max_m=round(hi), vague=True)
                return f"{round((lo + hi) / 2)} m"
        if m.group("approx") or f in (80, 100, 0.75):   # minutes' walk, blocks and paces are rough by nature
            info["vague"] = True
        return f"{round(a * f)} m"

    rng = rf"(?:between\s+)?(?P<n>{_NUM})\s*(?:to|or|and|-|a)\s*(?P<n2>{_NUM})"
    c = re.sub(rf"(?P<approx>{_APPROX}\s+)?(?:{rng})\s*(?P<u>{_UNIT_ANY})\b", to_m, c)
    c = re.sub(rf"(?P<approx>{_APPROX}\s+)?(?P<n>{_NUM}|a|an|one|two|three)\s*(?P<n2>)(?P<u>{_UNIT_ANY})\b", to_m, c)
    return re.sub(r"\s+", " ", c).strip(), info


def _parse_clause(clause: str) -> dict | None:
    clause, info = _distances(clause)
    r = _parse_clause_normalised(clause)
    if r and info and r.get("anchor"):
        r.update(info)
        if r.get("distance_m") is None and info.get("distance_min_m"):
            r["distance_m"] = (info["distance_min_m"] + info["distance_max_m"]) / 2
    return r


def _parse_clause_normalised(clause: str) -> dict | None:
    m = re.search(_PREVIOUS, clause)
    if m:
        return {**_other(), "type": "position", "relation": "previous", "minutes_ago": _number(m.group("n")),
                "confidence": 0.6}
    if g := grid.clause_grid(clause):   # a grid read out beats a landmark; the landmark is kept as the fallback
        fb = _parse_clause(g[1]) if g[1] else None
        return {**_other(), "type": "position", "anchor": g[0], "confidence": 0.8,
                "fallback": fb and {k: fb[k] for k in ("anchor", "anchor2", "relation", "distance_m")}}
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
        d = g.get("d") or g.get("d2")
        d = _number(d) if d else None
        out = {"subject": None, "type": "movement" if rel in ("towards", "along") else "position",
               "anchor": a, "anchor2": _anchor(g.get("b")), "relation": rel, "distance_m": d,
               "minutes_ago": None, "confidence": 0.5}
        if rel == "bearing":
            if g.get("c16"):
                out["bearing_deg"] = COMPASS[g["c16"]]
            else:
                deg = float(g["deg"])
                out["bearing_deg"] = (deg * 360 / 6400 if (g.get("bu") or "").startswith("mil") or deg > 360 else deg) % 360
        return out
    if re.search(_HOLDING, clause):
        return {**_other(), "type": "holding", "confidence": 0.6}
    return None


# The clock method: "at my two o'clock, about a hundred metres". Twelve o'clock is the way the speaker faces, which
# the net does not know, so only the distance is used: a ring around the reporter (as lang_uk.CLOCK does).
_CLOCK = r"\b(?:at\s+)?(?:my|our|your)?\s*(?:\w+\s+)?o\s*clock\b"
# Overhead / above us: the thing is where the reporter is ("drone overhead", "helicopter above us").
_OVERHEAD = r"\b(?:overhead|above (?:us|me|my position|our position)|over (?:us|me|my position|our position)|au dessus de nous)\b"


def _contact_place(sighting: list[str], desc: dict) -> dict | None:
    """Where a sighting is, from its clauses (offline rules). Besides the usual "300 m east of the church":
    the clock method and "overhead" (relative to the reporter), and a place whose state is reported ("the Pont des
    Arts is destroyed": the subject is the place)."""
    text = " , ".join(sighting)
    if re.search(_CLOCK, text):
        norm_text, info = _distances(text)
        m = re.search(rf"(?P<d>{_NUM})\s*{_UNIT}\b", norm_text)
        d = _number(m["d"]) if m else None
        return {**_other(), "type": "position", "anchor": {"name": "me", "kind": "unit"},
                "relation": "from" if d else "near", "distance_m": d, "vague": True, "confidence": 0.5,
                "clock": True, **{k: v for k, v in info.items() if k != "vague"}}
    r = next((x for x in map(_parse_clause, contact.location_clauses(sighting)) if x and x["type"] == "position"), None)
    if r is None and re.search(_OVERHEAD, text):
        return {**_other(), "type": "position", "anchor": {"name": "me", "kind": "unit"}, "relation": "at",
                "confidence": 0.5}
    if r is None and desc.get("what") == "obstacle":
        for c in contact.location_clauses(sighting):   # "the pont des arts" left once "is destroyed" is removed
            a = _anchor(re.sub(r"^(?:the|la|le|les|l)\s+", "", c))
            if a:
                return {**_other(), "type": "position", "anchor": a, "relation": "at", "confidence": 0.5}
    return r


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

    # "no enemy at the Odeon", "nothing seen", "enemy reported at the Pantheon yesterday": a place that is clear, or
    # somebody else's old news. Neither is a sighting and neither says where the speaker is: the phrase is dropped.
    t = ", ".join(seg for seg in re.split(r"\s*(?:[,;]|\.(?!\d))\s*", t) if seg and not re.search(_NOT_SEEN, seg)
                  and not re.search(_HEARSAY, seg))

    # "bearing 045, 300 metres from the church": one clue, though said with a pause
    t = re.sub(r"\b((?:bearing|azimuth|azimut|cap)\s+[\w ]{1,30}?(?:degrees?|mils?)?)\s*,\s*(?=[\w ]{1,30}?(?:from|de|du)\b)", r"\1 ", t)
    intent = bool(re.search(_INTENT, t))
    clauses = re.split(rf"\s*(?:[,;]|\.(?!\d))\s*|\s+(?=(?:i m|i am|we re|we are|je suis)\b)|\s+(?={_CS}\s+(?:is|est)\b)"
                       r"|\s+(?=(?:by|near|next to|close to|beside) (?:the )?\w)", t)   # "west side of X by the Y": two clues
    reports, current = [], None
    clauses = [c.strip() for c in clauses if c and c.strip()]
    # A sighting runs from the first clause that starts one to the end of the transmission; what comes before is the
    # speaker's own position ("at the church, contact, enemy tank 200 m north of me").
    seen = next((i for i, c in enumerate(clauses) if contact.starts_contact(c)), None)
    if seen is not None:
        sighting, clauses = clauses[seen:], clauses[:seen]
        desc = contact.describe(sighting, _number)
        r = _contact_place(sighting, desc)
        r = contact.self_anchor({**(r or _other()), "subject": None, "type": "contact"}, speaker)
        r["contact"] = desc
        if r["contact"]["what"] == "obstacle":   # "the bridge / near the Odeon is destroyed": the object may sit in an earlier clause
            r["contact"]["detail"] = contact.obstacle_detail(t) or r["contact"]["detail"]
            clauses = [c for c in clauses if not contact.object_only(c)]
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
