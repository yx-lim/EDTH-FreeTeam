"""Ukrainian and Russian: folding, numbers, case endings, callsigns and codenames.

Radio reports from Ukrainian units mix Ukrainian, Russian and English, and the two Cyrillic languages inflect place
names ("Ромашка", "на Ромашці", "біля Ромашки", "за Ромашкою"). Exact matching would miss most of them, so names are
matched on folded word stems instead, but only against a closed set: codenames, the operator's aliases and known
callsigns. Open-world names (every OSM street) are never fuzzy-matched this way.

Ported from a teammate's language layer (alias_lookup.py), with stricter stem matching and consistent ordinals.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
CALLSIGNS = DATA / "callsigns.json"

_CYR = re.compile(r"[а-яёіїєґ]", re.I)
_FOLD = str.maketrans({"і": "и", "ї": "и", "ы": "и", "є": "е", "э": "е", "ё": "е", "й": "и", "ґ": "г",
                       "ъ": "", "ь": "", "'": "", "’": "", "ʼ": "", "`": ""})


def has_cyrillic(text: str | None) -> bool:
    return bool(text and _CYR.search(text))


def cyrillic_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum(1 for c in letters if _CYR.match(c)) / len(letters) if letters else 0.0


def fold(text: str) -> str:
    """Match key only: Ukrainian and Russian spellings of one word fold together ("Граніт" == "Гранит"); what is
    shown to the operator stays as spoken."""
    t = unicodedata.normalize("NFC", text.lower()).translate(_FOLD)
    return " ".join(re.sub(r"[^\w\s]|_", " ", t).split())


# --- numbers ----------------------------------------------------------------------------------------------------
# Folded forms (і/ї/й -> и, є/ё -> е, apostrophes dropped), so one table serves both languages.
_UNITS = {
    "нуль": 0, "ноль": 0, "один": 1, "одна": 1, "одне": 1, "одно": 1, "два": 2, "дви": 2, "две": 2,
    "три": 3, "чотири": 4, "четире": 4, "пять": 5, "шисть": 6, "шесть": 6, "сим": 7, "семь": 7, "сем": 7,
    "висим": 8, "восемь": 8, "восем": 8, "девять": 9, "девят": 9, "десять": 10, "десят": 10,
    "одинадцять": 11, "одиннадцать": 11, "дванадцять": 12, "двенадцать": 12, "пятнадцять": 15, "пятнадцать": 15,
    "двадцять": 20, "двадцать": 20, "тридцять": 30, "тридцать": 30, "сорок": 40, "пятдесят": 50, "пятьдесят": 50,
    "шистдесят": 60, "шестьдесят": 60, "симдесят": 70, "семьдесят": 70, "висимдесят": 80, "восемьдесят": 80,
    "девяносто": 90, "сто": 100, "двисти": 200, "двести": 200, "триста": 300, "чотириста": 400,
    "четиреста": 400, "пятсот": 500, "пятьсот": 500, "шистсот": 600, "шестьсот": 600, "симсот": 700,
    "семьсот": 700, "висимсот": 800, "восемьсот": 800, "девятсот": 900, "девятьсот": 900,
    "тисяча": 1000, "тисячу": 1000, "тысяча": 1000, "тысячу": 1000,
    "полтораста": 150, "пивтораста": 150, "пивтори": 1.5, "полтора": 1.5,
}
_UNITS = {fold(k): v for k, v in _UNITS.items()}
# Ordinal stems: "друга посадка", "второй посадкой", "третій орієнтир" all name the same numbered reference.
ORDINAL_STEMS = [("перш", 1), ("перв", 1), ("друг", 2), ("втор", 2), ("трет", 3), ("четверт", 4), ("пят", 5)]


def number(text: str) -> float | None:
    """"двісті п'ятдесят" -> 250, "полтораста" -> 150, "250" -> 250. None if there is no number."""
    total, seen = 0.0, False
    for w in fold(text).split():
        if re.fullmatch(r"\d+(?:\.\d+)?", w):
            total += float(w)
            seen = True
        elif w in _UNITS:
            total += _UNITS[w]
            seen = True
        elif seen:
            break
    return total if seen else None


def _word_key(w: str) -> str:
    """A folded word, with number words and ordinals as digits ("три" -> "3", "второй" -> "2")."""
    if w in _UNITS and float(_UNITS[w]).is_integer():
        return str(int(_UNITS[w]))
    for stem, n in ORDINAL_STEMS:
        if w.startswith(stem) and len(w) - len(stem) <= 4 and not (stem == "пят" and w in _UNITS):
            return str(n)
    return w


def key(text: str) -> list[str]:
    return [_word_key(w) for w in fold(text).split()]


# --- inflected names ----------------------------------------------------------------------------------------------

def same_word(a: str, b: str) -> bool:
    """Case endings change the last letters only: "ромашка" / "ромашци" / "ромашкою" match, "романа" does not."""
    if a == b:
        return True
    if a.isdigit() or b.isdigit() or min(len(a), len(b)) < 3:
        return False
    if min(len(a), len(b)) == 3:   # "сад" / "саду" / "сада": one extra ending letter at most
        short, long_ = sorted((a, b), key=len)
        return len(long_) - len(short) <= 1 and long_.startswith(short)
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    shortest = min(len(a), len(b))
    # Stems of longer words keep at least 5 letters, so a consonant change in the ending ("ромашка" / "ромашці")
    # still matches but a different word with the same first syllables ("романа") does not.
    return common >= max(4, shortest - 2, 5 if shortest >= 6 else 0)


def lookup(spoken: str, index: dict[str, str]) -> str | None:
    """index: folded key (see `key`) -> target name. The alias may sit anywhere in the phrase ("100 метрів на схід
    від Сараю"); the longest matching alias wins, so "друга посадка" beats a codename "посадка"."""
    words = key(spoken)
    best, best_len = None, 0
    for k, target in index.items():
        kw = k.split()
        if len(kw) <= best_len or len(kw) > len(words):
            continue
        for i in range(len(words) - len(kw) + 1):
            if all(same_word(a, b) for a, b in zip(kw, words[i:i + len(kw)])):
                best, best_len = target, len(kw)
                break
    return best


def index_of(names: dict[str, str]) -> dict[str, str]:
    """{spoken alias: target} -> lookup index."""
    return {" ".join(key(k)): v for k, v in names.items() if k.strip()}


# --- callsigns ----------------------------------------------------------------------------------------------------

def _load_callsigns() -> dict[str, list[str]]:
    try:
        return json.loads(CALLSIGNS.read_text(encoding="utf-8"))["callsigns"]
    except (OSError, ValueError, KeyError):
        return {}


_CALLSIGNS = _load_callsigns()


def callsign(raw: str | None) -> str | None:
    """Canonical callsign: "Гранит" (Russian) and "Граніт" (Ukrainian) are one unit, and so are "Сокол" and "Сокіл"
    when the operator's table says so (data/callsigns.json). A number word becomes a digit ("Граніт два" -> "граніт
    2"). Unknown callsigns keep their own spelling, lowercased."""
    if not raw or not raw.strip():
        return None
    words = unicodedata.normalize("NFC", raw.lower())
    words = re.sub(r"[^\w\s'’-]|_", " ", words).split()
    if not words:
        return None
    head, rest = words[0], [str(int(_UNITS[fold(w)])) if fold(w) in _UNITS and float(_UNITS[fold(w)]).is_integer()
                            else w for w in words[1:]]
    for canon, alts in _CALLSIGNS.items():
        if any(same_word(fold(head), fold(n)) and len(fold(head)) - len(fold(n)) <= 2 for n in [canon, *alts]):
            head = canon.lower()
            break
    return " ".join([head, *rest])


def callsign_names() -> list[str]:
    return [n for canon, alts in _CALLSIGNS.items() for n in [canon, *alts]]


def unit_lookup(spoken: str, units) -> str | None:
    """"300 метрів на північ від Птахи" -> "птаха" when that unit is on the map. Spoken forms of a known callsign
    (its Russian spelling, case endings) count, through the callsign table."""
    names = {u: u for u in units if has_cyrillic(u)}
    for canon, alts in _CALLSIGNS.items():
        if canon.lower() in units:
            names.update({n: canon.lower() for n in alts})
    return lookup(spoken, index_of(names)) if names else None
