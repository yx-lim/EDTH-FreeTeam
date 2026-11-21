"""Misheard NATO callsigns back to their canonical form: "Alfa won" -> "Alpha 1", "Brava to," -> "Bravo 2".

Western-style nets use a NATO phonetic letter plus a number ("Alpha 1", "Bravo 2"). Speech-to-text often spells the
letter word wrong ("Alfa", "Charly", "Siera", "fox trot") or writes the number as a word that sounds like it ("won",
"too", "for", "ate"). This module snaps those back, by sound, before the report is read.

It is careful because several letter words are ordinary words or place names ("Hotel de Ville", "rue Victor Hugo",
"Golf"): a word is only changed into a letter when a number follows it ("Victor two") or it comes after "this is".
A sound-alike number ("to", "for") only counts at the end of the callsign: before a comma, full stop, "this is",
"over" or the end of the text, so "Alpha to Zero" stays as it is.

Ukrainian and Russian units use personal nicknames (Сокіл, Граніт), not letters: those are matched by sound against
the operator's callsign table in lang_uk.callsign().
"""
from __future__ import annotations

import difflib
import re
import unicodedata

NATO = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima",
        "mike", "november", "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey",
        "xray", "yankee", "zulu"]
CONTROL = ["zero", "control", "command"]
# Letters that are also everyday words or common in place names: never a callsign without a number after them.
COMMON_WORDS = {"golf", "hotel", "india", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo", "tango",
                "uniform", "victor", "whiskey", "juliet", "kilo", "echo", "yankee"}
# Spellings speech-to-text produces for each letter (also covers two-word splits, joined with a space).
VARIANTS = {
    "alfa": "alpha", "elfa": "alpha", "alpa": "alpha", "alpah": "alpha", "alva": "alpha",
    "brava": "bravo", "bravio": "bravo", "brahvo": "bravo",
    "charly": "charlie", "charley": "charlie", "charli": "charlie", "sharley": "charlie", "sharlie": "charlie",
    "charlee": "charlie",
    "delter": "delta", "deltah": "delta", "dealta": "delta",
    "eko": "echo", "ecko": "echo", "ekko": "echo", "ecco": "echo",
    "fox trot": "foxtrot", "fox-trot": "foxtrot", "foxtrott": "foxtrot",
    "gulf": "golf",
    "indya": "india", "indea": "india",
    "juliett": "juliet", "juliette": "juliet", "julia": "juliet",
    "keelo": "kilo", "kylo": "kilo", "keylo": "kilo",
    "leema": "lima", "leemah": "lima",
    "mic": "mike", "myke": "mike",
    "oskar": "oscar",
    "pappa": "papa",
    "kebec": "quebec", "keybeck": "quebec", "kebeck": "quebec",
    "romio": "romeo",
    "siera": "sierra", "cierra": "sierra", "see era": "sierra", "sierrah": "sierra",
    "tangle": "tango",
    "viktor": "victor",
    "whisky": "whiskey", "wiskey": "whiskey", "wisky": "whiskey",
    "x ray": "xray", "x-ray": "xray", "ex ray": "xray", "exray": "xray",
    "yanky": "yankee", "yankie": "yankee",
    "zoolu": "zulu", "zooloo": "zulu", "sulu": "zulu",
}
NUMBERS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "niner": 9, "ten": 10, "eleven": 11, "twelve": 12, "un": 1, "une": 1, "deux": 2, "trois": 3,
           "quatre": 4, "cinq": 5, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
           "tree": 3, "fife": 5, "fower": 4, "wun": 1, "tew": 2}
# Sound-alikes that are also ordinary words: a number only at the end of the callsign.
HOMOPHONES = {"won": 1, "wan": 1, "to": 2, "too": 2, "tu": 2, "free": 3, "for": 4, "fore": 4, "ate": 8, "nein": 9,
              "sicks": 6, "sex": 6}
# Words never read as a letter, however close they sound.
NEVER = {"the", "this", "that", "there", "is", "and", "over", "out", "roger", "copy", "wilco", "say", "again", "at",
         "in", "on", "of", "we", "are", "i", "am", "im", "a", "an", "to", "for", "with", "near", "moving", "contact",
         "enemy", "church", "street", "rue", "place", "park", "station", "metro", "metres", "meters", "north", "south",
         "east", "west", "hello", "radio", "check", "all", "stations", "go", "ahead", "send", "received", "affirm",
         "negative", "correction", "position", "holding", "same", "behind", "front", "between", "towards", "along",
         "mile", "miles", "like", "make", "made", "mice", "lime", "line", "time", "home", "hotels", "goal", "gold",
         "told", "bravely", "brave", "delay", "echoes", "tank", "tanks", "drone", "drones", "theatre", "theater"}
_END = r"(?=\s*(?:$|[,.;:!?]|\bthis is\b|\bover\b|\bout\b|\bthis\b))"


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def sound(word: str) -> str:
    """A rough English sound key: spellings that sound alike get the same key ("alfa" / "alpha", "charly" /
    "charlie", "siera" / "sierra")."""
    w = _plain(word).replace(" ", "").replace("-", "")
    for a, b in (("ph", "f"), ("ck", "k"), ("qu", "kw"), ("x", "ks"), ("ch", "sh"), ("c", "k"), ("z", "s"),
                 ("y", "i"), ("ee", "i"), ("oo", "u"), ("ie", "i"), ("ey", "i"), ("wh", "w"), ("gh", "g")):
        w = w.replace(a, b)
    w = re.sub(r"h(?![aeiou])", "", w)          # silent h: "deltah", "brahvo"
    w = re.sub(r"(.)\1+", r"\1", w)              # doubled letters
    w = re.sub(r"(?<=.)[aeiou]+$", "a", w)       # any final vowel sound: "charli" / "charlee"
    return w


def letter(word: str, strict: bool = True) -> str | None:
    """The NATO letter a spoken word stands for, or None. strict: close sound match only."""
    w = _plain(word).strip()
    if w in NATO or w in CONTROL:
        return w
    if w in VARIANTS:
        return VARIANTS[w]
    if w in NEVER or len(w) < 3 or w in NUMBERS or w in HOMOPHONES:
        return None
    key = sound(w)
    scored = sorted(((difflib.SequenceMatcher(None, key, sound(n)).ratio(), n) for n in NATO), reverse=True)
    (best, name), (second, _) = scored[0], scored[1]
    need = 0.8 if strict else 0.7
    if best >= need and best - second >= 0.1 and abs(len(w) - len(name)) <= 3:
        return name
    return None


def number(word: str, at_end: bool) -> int | None:
    w = _plain(word).strip()
    if w.isdigit() and len(w) <= 2:
        return int(w)
    if w in NUMBERS:
        return NUMBERS[w]
    if at_end and w in HOMOPHONES:
        return HOMOPHONES[w]
    return None


def canonical(raw: str | None) -> str | None:
    """A callsign the language model or the rules returned ("alfa won", "Charly 2") -> "alpha 1" / "charlie 2".
    Anything that is not a letter plus optional number is returned unchanged (lowercased)."""
    if not raw:
        return None
    words = _plain(raw).replace("-", " ").split()
    if not words:
        return None
    for n in (2, 1):   # "fox trot two", "x ray 3"
        head = " ".join(words[:n])
        name = VARIANTS.get(head) or (letter(head, strict=False) if n == 1 else None)
        if name:
            rest = words[n:]
            nums = [number(w, at_end=True) for w in rest]
            if rest and all(x is not None for x in nums):
                return f"{name} {''.join(str(x) for x in nums)}"
            if not rest:
                return name
            break
    return " ".join(words)


_TOKEN = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)?|\d+", re.UNICODE)


def snap(text: str) -> str:
    """Rewrite misheard callsigns inside a transcript; the rest of the text is left exactly as it was.
    "this is alfa won, at the church" -> "this is Alpha 1, at the church"."""
    if not text or re.search(r"[Ѐ-ӿ]", text):
        return text
    toks = list(_TOKEN.finditer(text))
    out, pos, i = [], 0, 0
    while i < len(toks):
        hit = None
        for n in (2, 1):
            if i + n > len(toks):
                continue
            words = [t.group() for t in toks[i:i + n]]
            if n == 2 and not re.fullmatch(r"[\s-]*", text[toks[i].end():toks[i + 1].start()]):
                continue
            phrase = " ".join(words)
            name = VARIANTS.get(_plain(phrase)) if n == 2 else letter(phrase)
            if not name:
                continue
            j = i + n
            after_this_is = bool(re.search(r"\bthis is\s*$", _plain(text[:toks[i].start()])))
            num, k = None, j
            if j < len(toks) and re.fullmatch(r"[\s,]*", text[toks[j - 1].end():toks[j].start()]) \
                    and "," not in text[toks[j - 1].end():toks[j].start()]:
                at_end = bool(re.match(_END, text[toks[j].end():]))
                num = number(toks[j].group(), at_end)
                k = j + 1 if num is not None else j
            exact = _plain(phrase) in NATO or _plain(phrase) in CONTROL
            if name in CONTROL:
                break
            if num is None and not after_this_is:
                break   # a lone word: a callsign only after "this is"
            if num is None and name in COMMON_WORDS and not exact:
                break
            if exact and num is None:
                break   # already right
            hit = (i, k, f"{name.capitalize()}" + (f" {num}" if num is not None else ""))
            break
        if hit:
            a, k, repl = hit
            out.append(text[pos:toks[a].start()])
            out.append(repl)
            pos, i = toks[k - 1].end(), k
        else:
            i += 1
    out.append(text[pos:])
    return "".join(out)
