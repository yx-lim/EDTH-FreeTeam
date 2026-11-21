"""Contact reports in Ukrainian and Russian: "ждун біля Сараю, метрів п'ятдесят на захід", "бачу трьох, рухаються на
південь", "мопед пройшов над Люксембурзьким палацом на захід".

Same report shape as backend/contact.py ({what, side, count, activity, heading} plus the anchor fields), so the
tracker and the map need nothing new. Two additions ride along in the contact dict:
  detail  the specific type as the troops say it ("FPV waiting on the ground", "Shahed"), shown on the map
  ttl_s   how long the sighting stays useful: an FPV has moved on in 90 s, a mine stays until cleared

Same safety rule as English: hostile only when the speaker says so (ворог, противник), or for systems only the
Russian side flies (Shahed, Orlan, Lancet...: data/threat_vocab.csv "side" column). Never inferred from a drone word
that both sides use (FPV, баба яга, мавік).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from . import lang_uk
from .lang_uk import _alt, fold

VOCAB = Path(__file__).resolve().parent.parent / "data" / "threat_vocab.csv"


def _load() -> list[dict]:
    try:
        with VOCAB.open(encoding="utf-8") as f:
            return [r for r in csv.DictReader(f) if r.get("spoken")]
    except OSError:
        return []


ROWS = _load()
_INDEX = lang_uk.index_of({r["spoken"]: str(i) for i, r in enumerate(ROWS)})
_WORDS = _alt(*[r["spoken"] for r in ROWS]) if ROWS else r"(?!x)x"

HOSTILE = _alt("ворог", "ворога", "ворожий", "ворожа", "ворожі", "противник", "противника", "вражеский", "вражеская",
               "вражеские", "орки", "рашисти", "окупанти", "окупанти", "enemy")
TRIGGER = _alt("контакт", "бачу", "вижу", "спостерігаю", "наблюдаю", "помітив", "заметил", "виявив", "обнаружил",
               "contact", "увага", "внимание")
COUNT_WORDS = {fold(k): v for k, v in {
    "двох": 2, "двоє": 2, "двоих": 2, "двое": 2, "трьох": 3, "троє": 3, "троих": 3, "трое": 3, "чотирьох": 4,
    "четверо": 4, "четверых": 4, "п'ятьох": 5, "пятеро": 5, "пятерых": 5, "групу": None, "группу": None}.items()}
ANOTHER = _alt("ще один", "ще одна", "ще одне", "ещё один", "ещё одна", "еще один", "еще одна", "another")
STATIC = _alt("стоїть", "стоит", "стоять", "сидить", "сидит", "висить", "висит", "зависла", "завис", "окопались",
              "лежить", "лежит", "чекає", "ждет")
FIRING = _alt("стріляє", "стреляет", "стріляють", "стреляют", "працює", "работает", "обстрілює", "обстреливает",
              "веде вогонь", "ведет огонь", "атакує", "атакует")
MOVING = _alt("йде", "іде", "идет", "йдуть", "идут", "летить", "летит", "летять", "летят", "рухається", "рухаються",
              "двигается", "двигаются", "пройшов", "прошел", "пролетів", "пролетел", "їде", "едет", "заходить", "заходит",
              "висувається", "выдвигается")
_HEAD_DIRS = [("пивнич", "north"), ("север", "north"), ("пивден", "south"), ("юг", "south"), ("схид", "east"),
              ("восто", "east"), ("захид", "west"), ("запад", "west")]
_OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}


def _dir_word(w: str) -> str | None:
    for stem, d in _HEAD_DIRS:
        if w.startswith(stem):
            return d
    return None


def threat(text: str) -> dict | None:
    """The vocabulary row for the first threat word in the text (longest phrase wins)."""
    hit = lang_uk.lookup(text, _INDEX)
    return ROWS[int(hit)] if hit is not None else None


def starts_contact(clause: str) -> bool:
    c = fold(clause)
    return threat(clause) is not None or bool(re.search(rf"\b{TRIGGER}\b", c) or re.search(rf"\b{HOSTILE}\b", c))


_BARE_DIR = rf"\b(?:на|в|у|к)\s+(?P<d>{lang_uk._DIR})\b(?!\s+(?:вид|от|of)\b)"


def heading(text: str) -> str | None:
    t = fold(text)
    m = re.search(rf"\b(?:{MOVING})\s+(?:на|в|у|к)?\s*(?P<d>\w+)", t) or re.search(r"\bкурс\s+(?:на\s+)?(?P<d>\w+)", t)
    if m and (d := _dir_word(m["d"])):
        return d
    # "мопед пройшов над палацом на захід": with a movement verb, a bare "на захід" is where it is going
    m = re.search(rf"\b(?:{MOVING})\b", t) and re.search(_BARE_DIR, t)
    if m and (d := lang_uk.relation_of(m["d"])):
        return d.removesuffix("_of")
    m = re.search(r"\b(?:з|с|зи|со)\s+(?P<d>пивноч\w*|пивдн\w*|сход\w*|заход\w*|север\w*|юг\w*|восто\w*|запад\w*)", t)
    if m:   # "заходить з півночі": coming from the north, so heading south
        d = {"пивноч": "north", "пивдн": "south", "сход": "east", "заход": "west"}.get(m["d"][:6].rstrip("иаую"))
        d = d or _dir_word(m["d"])
        return _OPPOSITE.get(d or "", None)
    return None


def describe(text: str) -> dict:
    t = fold(text)
    row = threat(text)
    count = None
    m = re.search(rf"(?P<n>\d+|\b(?:{lang_uk._NUMW})\b)\s+(?:\w+\s+)?{_WORDS}", t)
    if m:
        count = lang_uk.number(m["n"])
    for w in t.split():
        if w in COUNT_WORDS and COUNT_WORDS[w]:
            count = count or COUNT_WORDS[w]
    what = row["what"] if row else ("infantry" if count else "unknown")
    side = ("hostile" if re.search(rf"\b{HOSTILE}\b", t) or (row and row.get("side") == "hostile")
            else "neutral" if what == "civilians" else "unknown")
    head = heading(text)
    activity = ("firing" if re.search(rf"\b{FIRING}\b", t) else "static" if re.search(rf"\b{STATIC}\b", t)
                or (row and int(row["ttl_s"] or 0) >= 1800 and what == "drone") else "moving" if head
                or re.search(rf"\b{MOVING}\b", t) else None)
    return {"what": what, "side": side, "count": int(count) if count else None, "activity": activity, "heading": head,
            "detail": (row or {}).get("detail") or ("group of people" if what == "infantry" else None),
            "ttl_s": int(row["ttl_s"]) if row and row.get("ttl_s") else (900 if what == "infantry" else None),
            "word": (row or {}).get("spoken"), "another": bool(re.search(rf"\b{ANOTHER}\b", t))}


def location_text(text: str) -> str:
    """The sighting with what/how-many/how-it-moves words removed, so only where it is remains."""
    t = lang_uk.fold_keep(text)
    t = re.sub(rf"\b(?:{MOVING})\s+(?:на|в|у|к)?\s*(?:{lang_uk._DIR})(?:\s+(?:вид|от)\s+[^,.;]+)?", " ", t)
    t = re.sub(rf"\b(?:{MOVING})\s+(?:до|к|в напрямку|в сторону)\s+[^,.;]+", " ", t)   # a destination, not where it is
    t = re.sub(r"\bкурс\s+(?:на\s+)?\w+", " ", t)
    if re.search(rf"\b(?:{MOVING})\b", t):
        t = re.sub(_BARE_DIR, " ", t)   # the heading, already read by heading()
    t = re.sub(rf"\b(?:{MOVING}|{STATIC}|{FIRING}|{TRIGGER}|{HOSTILE}|{ANOTHER})\b", " ", t)
    t = re.sub(rf"\b(?:\d+|{lang_uk._NUMW})?\s*(?:{_WORDS})\w*", " ", t)
    t = re.sub(r"\b(?:" + "|".join(COUNT_WORDS) + r")\b", " ", t)
    t = re.sub(r"\bнад\s+(?:нами|мною|нам)\b", " overhead ", t)
    t = re.sub(r"\bнад\b", "на", t)   # "над Ромашкою" (a drone above it): at Ромашка
    return re.sub(r"\s+", " ", t)


def locate(text: str, speaker: str | None) -> dict:
    """Anchor/relation fields for where the sighting is."""
    t = location_text(text)
    if re.search(r"\boverhead\b", t):
        return {"anchor": {"name": speaker or "me", "kind": "unit"}, "relation": "at", "distance_m": None,
                "relative_to_reporter": True, "vague": False}
    report = None
    for clause in filter(None, (c.strip() for c in re.split(r"\s*[,.;]\s*", t))):
        r = lang_uk.parse_location(clause)
        if r and r.get("anchor"):
            report = r
            break
    if report is None:
        return {"anchor": None, "relation": "at", "distance_m": None, "vague": False}
    # "ждун біля Сараю, метрів п'ятдесят на захід": the bare direction in another clause refines "near Сарай".
    if report["relation"] in ("near", "at"):
        m = re.search(rf"(?:{lang_uk._DIST})?\s*(?:\bна\s+|\bк\s+)?\b(?P<dir>{lang_uk._DIR})(?!\s+(?:вид|от)\b)", t)
        rel = lang_uk.relation_of(m["dir"]) if m else None
        if rel:
            report["relation"] = rel
            dm = re.search(lang_uk._DIST, t)
            report["distance_m"] = report["distance_m"] or (lang_uk.number(dm["d1"] or dm["d2"]) if dm else None)
            report["vague"] = report.get("vague") or bool(re.search(rf"\b{lang_uk._M}\s+{lang_uk._N}", t))
    return {k: report.get(k) for k in ("anchor", "anchor2", "relation", "distance_m", "vague")}


def report(sighting: str, speaker: str | None) -> dict:
    out = {"subject": None, "type": "contact", "anchor2": None, "minutes_ago": None, "confidence": 0.5,
           **locate(sighting, speaker), "contact": describe(sighting)}
    return out
