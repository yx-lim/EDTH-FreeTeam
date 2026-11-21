"""Military grid references (MGRS): convert positions, and find grids read out on the radio.

The arithmetic is the `mgrs` package (NGA's GeoTrans code). Checked against pygeodesy and pyproj on 34,000 points:
every 100 m square agreed, 99.98 % of 10 m squares, and round trips at 1 m stay within 0.71 m (the most the square
allows). This module adds what the package lacks: grids spoken in English, Ukrainian or Russian, grid precision
that follows the report's uncertainty, and a check that the grid lies in the area we are working in.

    to_mgrs(48.836, 2.452)                   -> "31U DQ 5978 0936"    10 m square
    to_mgrs(48.836, 2.452, radius_m=150)     -> "31U DQ 59 09"        never more precise than the report
    to_latlon("31U DQ 5978 0936")            -> (48.835957, 2.451979) centre of the square
    find_spoken_grid("квадрат тридцять один юніформ дельта квебек п'ять дев'ять сім вісім нуль дев'ять три шість")
                                             -> "31U DQ 5978 0936"
    parse_spoken_grid(text, near=(lat, lon)) -> GridHit: position, square size, and any doubt about it

Same function names as ground-truth's mgrs_convert.py, and nothing else from this app is imported, so the file can be
copied into another backend as it is. Needs `pip install mgrs`.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

import mgrs as _mgrs

_M = _mgrs.MGRS()

# zone 1-60, latitude band C-X, 100 km square column A-Z and row A-V (I and O never used), 0-5 digits per axis
_GRID = re.compile(r"(\d{1,2})([C-HJ-NP-X])([A-HJ-NP-Z])([A-HJ-NP-V])((?:\d\d){0,5})")


# ---- conversion ----------------------------------------------------------------------------------------------------

def compact(grid: str) -> str:
    return re.sub(r"\s+", "", grid).upper()


def format_grid(grid: str) -> str:
    """Any spacing -> the written form "31U DQ 5978 0936". Raises ValueError if it is not an MGRS reference."""
    hit = _GRID.fullmatch(compact(grid))
    halves = re.findall(r"\d+", grid)[1:]          # "31U DQ 123 45678": written halves must match
    if not hit or not 1 <= int(hit.group(1)) <= 60 or (len(halves) == 2 and len(halves[0]) != len(halves[1])):
        raise ValueError(f"not an MGRS reference: {grid!r}")
    zone, band, col, row, digits = hit.groups()
    half = len(digits) // 2
    return " ".join(p for p in (f"{int(zone):02d}{band}", col + row, digits[:half], digits[half:]) if p)


def square_m(grid: str) -> int:
    """Side of the square a grid names: 4+4 digits -> 10 m, 3+3 -> 100 m, no digits -> 100 km."""
    digits = _GRID.fullmatch(compact(grid)).group(5)
    return 10 ** (5 - len(digits) // 2)


def digits_for_radius(radius_m: float) -> int:
    """Digits per axis so the square is at least as wide as the uncertainty radius: a report good to ±40 m is
    given as a 100 m square, not a 10 m one that claims more than the speaker said."""
    for digits in (5, 4, 3, 2, 1):
        if 10 ** (5 - digits) >= radius_m:
            return digits
    return 1


def to_mgrs(lat: float, lon: float, digits: int = 4, radius_m: float | None = None) -> str:
    """WGS84 lat/lon -> "31U DQ 5978 0936". digits per axis: 5 = 1 m, 4 = 10 m (NATO default), 3 = 100 m.
    Pass radius_m instead to let the report's uncertainty choose the precision."""
    if radius_m is not None:
        digits = digits_for_radius(radius_m)
    return format_grid(_M.toMGRS(lat, lon, MGRSPrecision=digits))


def to_latlon(grid: str) -> tuple[float, float]:
    """MGRS (any spacing) -> (lat, lon) of the CENTRE of the square, so a 100 m grid is at most 71 m off."""
    lat, lon = _M.toLatLon(compact(format_grid(grid)))
    return round(lat, 7), round(lon, 7)


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742.0 * math.asin(math.sqrt(h))


# ---- spoken grids --------------------------------------------------------------------------------------------------

def _table(groups: dict[str, str]) -> dict[str, str]:
    """{"value": "word word ..."} -> {word: value}, plus each word without its apostrophe (speech-to-text often drops
    it: "пять" for "п'ять")."""
    out = {}
    for value, words in groups.items():
        for w in words.split():
            out[w] = value
            out.setdefault(w.replace("'", ""), value)
    return out


# NATO phonetic alphabet as said in English, Ukrainian and Russian.
LETTERS = _table({
    "A": "alpha alfa альфа", "B": "bravo браво", "C": "charlie чарлі чарли", "D": "delta дельта",
    "E": "echo ехо эхо", "F": "foxtrot фокстрот", "G": "golf гольф", "H": "hotel готель отель хотел",
    "I": "india індія индия", "J": "juliet juliett джульєтта джульєт джульетта", "K": "kilo кіло кило",
    "L": "lima ліма лима", "M": "mike майк", "N": "november новембер ноябрь", "O": "oscar оскар", "P": "papa папа",
    "Q": "quebec квебек", "R": "romeo ромео", "S": "sierra сьєрра сієрра сьєра сієра сьерра",
    "T": "tango танго", "U": "uniform юніформ уніформ юниформ униформ", "V": "victor віктор виктор",
    "W": "whiskey whisky віскі виски", "X": "xray x-ray ікс-рей ексрей ікс икс-рей эксрей икс",
    "Y": "yankee янкі янки", "Z": "zulu зулу",
})
DIGITS = _table({
    "0": "zero oh nought нуль ноль", "1": "one один одна одне", "2": "two два дві две", "3": "three tree три",
    "4": "four fower чотири четыре", "5": "five fife п'ять пять", "6": "six шість шесть", "7": "seven сім семь",
    "8": "eight вісім восемь", "9": "nine niner дев'ять девять",
})
TEENS = _table({
    "10": "ten десять", "11": "eleven одинадцять одиннадцать", "12": "twelve дванадцять двенадцать",
    "13": "thirteen тринадцять тринадцать", "14": "fourteen чотирнадцять четырнадцать",
    "15": "fifteen п'ятнадцять пятнадцать", "16": "sixteen шістнадцять шестнадцать",
    "17": "seventeen сімнадцять семнадцать", "18": "eighteen вісімнадцять восемнадцать",
    "19": "nineteen дев'ятнадцять девятнадцать",
})
TENS = _table({
    "2": "twenty двадцять двадцать", "3": "thirty тридцять тридцать", "4": "forty fourty сорок",
    "5": "fifty п'ятдесят пятьдесят", "6": "sixty шістдесят шестьдесят", "7": "seventy сімдесят семьдесят",
    "8": "eighty вісімдесят восемьдесят", "9": "ninety дев'яносто девяносто",
})
_UNIT = re.compile(r"(?:m|km|metres?|meters?|klicks?|kilomet(?:re|er)s?|м|км|метр\w*|кілометр\w*|километр\w*)")
_TOKEN = re.compile(r"\d+|[^\W\d_]+(?:['-][^\W\d_]+)*|[,;:.!?]")
_APOSTROPHES = str.maketrans({c: "'" for c in "’ʼ‘`′´"})


@dataclass
class GridHit:
    grid: str                      # "31U DQ 5978 0936"
    lat: float | None              # centre of the square
    lon: float | None
    square_m: int                  # 10 for 4+4 digits
    said: str                      # the words it came from
    ambiguous: str | None = None   # a guess was made; ask for a read-back before acting on it
    problem: str | None = None     # do not plot: grid does not exist or is outside the area


def _symbols(text: str) -> list[tuple[str, str, list[str]]]:
    """Text -> [(kind, value, parts)]: D digits, L letters, P pause (comma), U distance unit, W any other word or a
    full stop. Neighbouring digits and neighbouring letters are joined ("three one" -> D "31"; "31U DQ" -> D "31",
    L "UDQ"); `parts` keeps how the digits were said ("тридцять шість двадцять" -> ["36", "20"])."""
    text = unicodedata.normalize("NFC", text).translate(_APOSTROPHES)
    tokens = [(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(text)]
    out: list[tuple[str, str, list[str]]] = []

    def add(kind: str, value: str) -> None:
        if out and out[-1][0] == kind and kind in "DL":
            out[-1] = (kind, out[-1][1] + value, out[-1][2] + [value])
        else:
            out.append((kind, value, [value]))

    i, prev_end, prev_digits = 0, -1, False
    while i < len(tokens):
        tok, start, end = tokens[i]
        low = tok.lower()
        glued = start == prev_end and prev_digits          # "31U", "20m"
        nxt = tokens[i + 1][0].lower() if i + 1 < len(tokens) else ""
        if tok.isdigit():
            add("D", tok)
        elif tok in ",;:":
            add("P", tok)
        elif tok in ".!?":
            add("W", tok)
        elif low in TENS and DIGITS.get(nxt, "0") != "0":   # "тридцять один" -> 31
            add("D", TENS[low] + DIGITS[nxt])
            i += 1
        elif low in TENS:
            add("D", TENS[low] + "0")
        elif low in TEENS:
            add("D", TEENS[low])
        elif low in DIGITS:
            add("D", DIGITS[low])
        elif low in LETTERS:
            add("L", LETTERS[low])
        elif _UNIT.fullmatch(low) and not tok.isupper():
            add("U", low)
        elif tok.isascii() and len(tok) <= 3 and (tok.isupper() or glued):
            add("L", tok.upper())                          # typed or transcribed "31U DQ"
        elif "-" in low and all(p in DIGITS or p in TENS or p in TEENS for p in low.split("-")):
            tokens[i:i + 1] = [(p, start, end) for p in low.split("-")]   # "thirty-one"
            continue
        else:
            add("W", low)
        prev_end, prev_digits = end, tok.isdigit()
        i += 1
    return out


def _even(d: str) -> bool:
    return len(d) % 2 == 0 and 0 < len(d) <= 10


def _pick_digits(groups: list[list[str]], unit_follows: bool) -> tuple[str | None, str | None]:
    """Decide which of the digits after the grid letters belong to the grid. `groups` are the digit parts between
    pauses (commas). Returns (digits, doubt); doubt is set when a guess was made."""
    parts = [p for g in groups for p in g]
    digits = "".join(parts)
    by_pause = ("".join(p for g in groups[:-1] for p in g), "".join(groups[-1])) if len(groups) > 1 else None
    if unit_follows:
        # "... zero nine three six, two zero metres north": the number before "metres" is a distance.
        # Clear when a pause or a whole number word ("двадцять", "200") separates it from the grid.
        for split in (by_pause, ("".join(parts[:-1]), parts[-1]) if len(parts[-1]) >= 2 else None):
            if split and _even(split[0]) and 1 <= len(split[1]) <= 4:
                return split[0], None
        for keep in (10, 8, 6, 4, 2):
            if 1 <= len(digits) - keep <= 3:
                return digits[:keep], f"read the last {len(digits) - keep} digits as a distance, not part of the grid"
        return None, None
    # "... zero nine three six, two" (a count after a pause): a grid half is never under 3 digits after a pause.
    if by_pause and _even(by_pause[0]) and len(by_pause[0]) >= 4 and len(by_pause[1]) <= 3:
        return by_pause[0], f"ignored the number after the grid ({by_pause[1]})"
    if _even(digits):
        doubt = "1 m grids are rare on the radio: check the last digits were not a separate number" \
            if len(digits) == 10 else None
        return digits, doubt
    if len(digits) % 2 == 1 and len(digits) - 1 <= 10 and len(digits) > 1:
        return digits[:-1], f"odd number of digits; dropped the last one ({digits[-1]})"
    return None, None


def parse_spoken_grid(text: str, near: tuple[float, float] | None = None, max_km: float = 50.0) -> GridHit | None:
    """First grid reference in a transcript, typed or spoken in English, Ukrainian or Russian. Returns None when there
    is none. A hit with `problem` set must not be plotted; one with `ambiguous` set should be read back first.
    `near`: the area of operations; a grid more than max_km from it is almost certainly misheard."""
    syms = _symbols(text)
    for i in range(len(syms) - 1):
        (k1, d, _), (k2, letters, _) = syms[i], syms[i + 1]
        if k1 != "D" or k2 != "L" or len(letters) != 3:
            continue
        zone = d[-2:] if len(d) >= 2 and 1 <= int(d[-2:]) <= 60 else d[-1]
        groups: list[list[str]] = []
        j = i + 2
        while j < len(syms):
            if syms[j][0] == "D":
                groups.append(list(syms[j][2]))
            elif not (syms[j][0] == "P" and j + 1 < len(syms) and syms[j + 1][0] == "D"):
                break
            j += 1
        unit_follows = j < len(syms) and syms[j][0] == "U"
        digits, doubt = _pick_digits(groups, unit_follows) if groups else ("", None)
        if digits is None:
            continue
        raw = zone + letters + digits
        if not _GRID.fullmatch(raw) or not 1 <= int(zone) <= 60:
            continue
        grid = format_grid(raw)
        said = " ".join(v for _, v, _ in syms[i:j])
        try:
            lat, lon = to_latlon(grid)
        except Exception:  # noqa: BLE001 - the package raises plain Exception for squares that do not exist
            return GridHit(grid, None, None, square_m(grid), said, doubt, "this grid square does not exist")
        hit = GridHit(grid, lat, lon, square_m(grid), said, doubt)
        if not digits:
            hit.problem = "no digits: only names a 100 km square"
        elif near is not None and (far := distance_km(near, (lat, lon))) > max_km:
            hit.problem = f"{far:,.0f} km from the area of operations; probably misheard"
        return hit
    return None


def find_spoken_grid(text: str, near: tuple[float, float] | None = None, max_km: float = 50.0) -> str | None:
    """Grid reference in a transcript as "31U DQ 5978 0936", or None if there is none or it must not be plotted."""
    hit = parse_spoken_grid(text, near, max_km)
    return hit.grid if hit and not hit.problem else None
