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

from . import zone  # noqa: E402

CALLSIGNS = zone.path("callsigns.json", shared=True)   # the zone's own table, else data/callsigns.json

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
    "тисяча": 1000, "тисячу": 1000, "тысяча": 1000, "тысячу": 1000, "тисячі": 1000, "тисяч": 1000,
    "тысячи": 1000, "тысяч": 1000, "сорок": 40, "сороку": 40, "сорока": 40,
    # oblique cases, as in "від двохсот до трьохсот метрів" / "около двухсот метров"
    "ста": 100, "двохсот": 200, "двухсот": 200, "трьохсот": 300, "трехсот": 300, "чотирьохсот": 400,
    "четырехсот": 400, "п'ятисот": 500, "пятисот": 500, "шестисот": 600, "семисот": 700, "восьмисот": 800,
    "п'ятдесяти": 50, "пятидесяти": 50, "двадцяти": 20, "двадцати": 20, "тридцяти": 30, "тридцати": 30,
    "десяти": 10, "двох": 2, "двух": 2, "трьох": 3, "трех": 3, "чотирьох": 4, "четырех": 4, "п'яти": 5, "пяти": 5,
    "полтораста": 150, "пивтораста": 150, "пивтори": 1.5, "полтора": 1.5, "півтора": 1.5,
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


# --- place-name words ----------------------------------------------------------------------------------------------
# Street words: Ukrainian and Russian forms and abbreviations fold to one ("улица", "ул", "вул" -> "вулиця"), so
# "улица Шевченко" finds "вулиця Шевченка". Keys and values are folded.
STREET_WORDS = {fold(k): fold(v) for k, v in {
    "вулиця": "вулиця", "вул": "вулиця", "улица": "вулиця", "ул": "вулиця", "провулок": "провулок",
    "пров": "провулок", "переулок": "провулок", "пер": "провулок", "площа": "площа", "пл": "площа",
    "площадь": "площа", "проспект": "проспект", "просп": "проспект", "пр": "проспект", "бульвар": "бульвар",
    "бульв": "бульвар", "б-р": "бульвар", "набережна": "набережна", "набережная": "набережна", "шосе": "шосе",
    "шоссе": "шосе", "узвіз": "узвіз", "спуск": "узвіз", "тупик": "тупик", "проїзд": "проїзд", "проезд": "проїзд",
    "сквер": "сквер", "парк": "парк", "міст": "міст", "мост": "міст"}.items()}
# Generic words a speaker uses instead of a name, as stems matched with case endings ("біля церкви", "у школі").
# The values are the gazetteer's categories. "Собор" is left out: it would swallow "Соборна вулиця".
CATEGORY_STEMS = {fold(k): v for k, v in {
    "церква": "church", "церковь": "church", "храм": "church", "каплиця": "church", "часовня": "church",
    "парк": "park", "сквер": "park", "сад": "park", "школа": "school", "ліцей": "school", "лицей": "school",
    "гімназія": "school", "гимназия": "school", "коледж": "school", "колледж": "school", "університет": "school",
    "университет": "school", "лікарня": "hospital", "больница": "hospital", "госпіталь": "hospital",
    "госпиталь": "hospital", "вокзал": "station", "станція": "station", "станция": "station", "метро": "station",
    "музей": "museum", "фонтан": "fountain", "театр": "theatre", "ринок": "market", "рынок": "market",
    "базар": "market", "ринк": "market", "рынк": "market", "кафе": "cafe", "ресторан": "restaurant", "бар": "bar", "аптека": "pharmacy",
    "банк": "bank", "пошта": "post office", "почта": "post office", "поліція": "police", "полиция": "police",
    "бібліотека": "library", "библиотека": "library", "кінотеатр": "cinema", "кинотеатр": "cinema",
    "готель": "hotel", "гостиница": "hotel", "супермаркет": "supermarket", "магазин": "supermarket",
    "пекарня": "bakery", "пам'ятник": "monument", "памятник": "monument", "меморіал": "memorial",
    "мемориал": "memorial", "заправка": "petrol station", "азс": "petrol station", "пожежна": "fire station",
    "мерія": "town hall", "мерия": "town hall", "міськрада": "town hall", "горсовет": "town hall",
    "посольство": "embassy"}.items()}


def category_of(word: str) -> str | None:
    """"церкви" -> "church", "школі" -> "school". Stems of 3 letters must match exactly ("сад", "бар")."""
    w = fold(word)
    for stem, cat in CATEGORY_STEMS.items():
        if w == stem or (len(stem) >= 4 and same_word(w, stem) and abs(len(w) - len(stem)) <= 2):
            return cat
    return None


_LATIN = str.maketrans({"а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie", "ж": "zh",
                        "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
                        "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
                        "ч": "ch", "ш": "sh", "щ": "shch", "ь": "", "ю": "iu", "я": "ia", "ы": "y", "э": "e",
                        "ё": "io", "ъ": "", "'": "", "’": "", "ʼ": ""})


def latin(text: str) -> str:
    """Ukrainian national transliteration (Russian letters too): "Шевченка" -> "shevchenka". Lets a Latin-script
    report find a Cyrillic place name, and the reverse, before sound-alike matching."""
    t = unicodedata.normalize("NFC", text.lower())
    t = re.sub(r"(?<![а-яіїєґ])є", "ye", t)
    t = re.sub(r"(?<![а-яіїєґ])ю", "yu", t)
    t = re.sub(r"(?<![а-яіїєґ])я", "ya", t)
    t = re.sub(r"(?<![а-яіїєґ])ї", "yi", t)
    return t.translate(_LATIN)


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


# NATO letters said in Cyrillic, mapped to the Latin callsign so "Альфа 1" and "Alpha 1" are one unit.
_NATO_CYR = {fold(k): v for k, v in {
    "альфа": "alpha", "браво": "bravo", "чарлі": "charlie", "чарли": "charlie", "дельта": "delta", "ехо": "echo",
    "эхо": "echo", "фокстрот": "foxtrot", "гольф": "golf", "готель": "hotel", "отель": "hotel", "індія": "india",
    "индия": "india", "джульєтта": "juliet", "джульетта": "juliet", "кіло": "kilo", "кило": "kilo", "ліма": "lima",
    "лима": "lima", "майк": "mike", "оскар": "oscar", "папа": "papa", "квебек": "quebec", "ромео": "romeo",
    "сьєрра": "sierra", "сиерра": "sierra", "сієра": "sierra", "танго": "tango", "юніформ": "uniform",
    "юниформ": "uniform", "віктор": "victor", "виктор": "victor", "віскі": "whiskey", "виски": "whiskey",
    "янкі": "yankee", "янки": "yankee", "зулу": "zulu"}.items()}


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
    nato = _NATO_CYR.get(fold(words[0]))
    if nato:   # "Альфа один" is the same unit as "Alpha 1"
        nums = [_UNITS.get(fold(w), w) for w in words[1:]]
        return " ".join([nato, *(str(int(n)) if isinstance(n, (int, float)) else n for n in nums)])
    head, rest = words[0], [str(int(_UNITS[fold(w)])) if fold(w) in _UNITS and float(_UNITS[fold(w)]).is_integer()
                            else w for w in words[1:]]
    for canon, alts in _CALLSIGNS.items():
        if any(same_word(fold(head), fold(n)) and len(fold(head)) - len(fold(n)) <= 2 for n in [canon, *alts]):
            head = canon.lower()
            break
    else:
        head = sound_alike(head) or head
    return " ".join([head, *rest])


# Voiced and voiceless pairs blur on a noisy radio (д/т, б/п, з/с, г/х/к, ж/ш), and an unstressed о sounds like а.
_SOUND = str.maketrans({"д": "т", "б": "п", "з": "с", "г": "к", "ґ": "к", "х": "к", "ж": "ш", "в": "ф", "о": "а",
                        "ц": "с", "щ": "ш"})


def sound_key(word: str) -> str:
    return re.sub(r"(.)\1+", r"\1", fold(word).translate(_SOUND))


def sound_alike(word: str) -> str | None:
    """A misheard nickname -> the callsign in the operator's table it sounds like ("Гранід" -> "граніт", "Сакіл" ->
    "сокіл"). Only for words of 4+ letters, only when one callsign clearly wins; otherwise None (keep as heard)."""
    import difflib

    k = sound_key(word)
    if len(k) < 4:
        return None
    scored = sorted(((difflib.SequenceMatcher(None, k, sound_key(n)).ratio(), canon)
                     for canon, alts in _CALLSIGNS.items() for n in [canon, *alts]
                     if len(sound_key(n)) >= 4), reverse=True)
    if not scored or scored[0][0] < 0.8:
        return None
    best = scored[0]
    rival = next((sc for sc, c in scored[1:] if c != best[1]), 0)
    return best[1].lower() if best[0] - rival >= 0.1 else None


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


# --- radio procedure and rule-based parsing (closed demo grammar; free speech needs the language model) -------------
# Everything below works on folded text, so one pattern covers Ukrainian, Russian and their mixtures. Patterns are
# written in normal spelling and folded once here.

def _alt(*phrases: str) -> str:
    return "(?:" + "|".join(sorted({re.escape(fold(p)).replace(r"\ ", r"\s+") for p in phrases}, key=len,
                                   reverse=True)) + ")"


CONTROL_WORDS = {fold(w) for w in ("Вежа", "Башня", "Tower", "База")}
ALL_WORDS = {fold(w) for w in ("всім", "всем", "всім станціям", "всем станциям")}
OVER = _alt("прийом", "приём", "прием")
OUT = _alt("кінець зв'язку", "конец связи", "відбій", "отбой", "кінець", "конец")
ACK = _alt("плюс", "прийняв", "прийнято", "принял", "принято", "зрозумів", "зрозуміло", "понял", "понятно",
           "так точно", "добре", "есть", "є", "роджер", "roger", "виконую", "выполняю", "висуваюсь", "выдвигаюсь")
SAY_AGAIN = _alt("повтори", "повторіть", "повторите", "не чую", "не слышу", "не зрозумів", "не понял")
CHECK = _alt("перевірка зв'язку", "проверка связи", "як чуєш", "как слышишь", "як чути", "как слышно", "чую добре",
             "чую нормально", "чую вас", "слышу хорошо", "слышу нормально", "слышу вас")
REQUEST = _alt("доповідай", "доповідайте", "доповідь", "доклад", "докладывай", "докладывайте", "де ти", "де ви",
               "где ты", "где вы", "твоя позиція", "ваша позиція", "твоя позиция", "ваша позиция", "позицію",
               "позицию")
ORDER_MOVE = _alt("висувайся до", "висувайтесь до", "висувайтеся до", "рухайся до", "рухайтесь до",
                  "выдвигайся к", "выдвигайтесь к", "двигайся к", "двигайтесь к", "иди до", "иди к", "йди до")
ORDER_HOLD = _alt("тримай позицію", "тримайте позицію", "залишайся на місці", "залишайтесь на місці",
                  "держи позицию", "держите позицию", "оставайся на месте", "оставайтесь на месте")
CORRECTION = _alt("мінус", "минус", "отставить", "відставити", "поправка", "виправлення")
HOLDING = _alt("без змін", "без изменений", "там само", "там же", "на тому ж місці", "на том же месте",
               "стою на місці", "стою на месте", "на місці", "на месте")
INTENT = _alt("буду через", "буду за", "будем через", "будемо через", "буду на", "будем на", "будемо на")
VAGUE = _alt("близько", "около", "приблизно", "примерно", "десь", "где-то", "майже", "почти")
POSITION_WORDS = _alt("на позиції", "на позиции", "я на позиції", "стою", "знаходжусь", "нахожусь", "перебуваю")
_PREP = _alt("від", "от", "of", "from", "до", "к", "біля", "возле", "у", "в", "на", "за", "с", "з", "із", "над",
             "під", "под", "поруч", "рядом", "около")

_DIRS = [  # folded stems -> relation; compounds first
    (r"(?:пивнично|северо)\s*(?:схид|восто)\w*|(?:пивничн\w*\s+схид\w*)|north\s*east", "northeast_of"),
    (r"(?:пивнично|северо)\s*(?:захид|запад)\w*|(?:пивничн\w*\s+захид\w*)|north\s*west", "northwest_of"),
    (r"(?:пивденно|юго)\s*(?:схид|восто)\w*|(?:пивденн\w*\s+схид\w*)|south\s*east", "southeast_of"),
    (r"(?:пивденно|юго)\s*(?:захид|запад)\w*|(?:пивденн\w*\s+захид\w*)|south\s*west", "southwest_of"),
    (r"пивнич\w*|север\w*|north", "north_of"),
    (r"пивден\w*|юг\w*|южн\w*|south", "south_of"),
    (r"схид\w*|восто\w*|east", "east_of"),
    (r"захид\w*|запад\w*|west", "west_of"),
]
_DIR = "|".join(f"(?:{p})" for p, _ in _DIRS)
_NUMW = "|".join(sorted((re.escape(k) for k in _UNITS), key=len, reverse=True))
_N = rf"(?:\d+(?:\.\d+)?|(?:\b(?:{_NUMW})\b\s*)+)"
_M = r"(?:метр\w*|м|m|meters?|metres?)"
_DIST = rf"(?:(?P<d1>{_N})\s*{_M}\b|\b{_M}\s+(?P<d2>{_N}))"


def relation_of(direction: str) -> str | None:
    for p, rel in _DIRS:
        if re.fullmatch(p, direction.strip()):
            return rel
    return None


_TOKEN = re.compile(r"[^\W_][\w'’ʼ-]*|[,.;!?]")


def tokens(text: str) -> list[tuple[str, str]]:
    """(as spoken, folded) per word or punctuation mark."""
    return [(t, fold(t) or t) for t in _TOKEN.findall(unicodedata.normalize("NFC", text))]


def _is_station(f: str) -> bool:
    return f in CONTROL_WORDS or f in ALL_WORDS or any(
        same_word(f, fold(n)) and len(f) - len(fold(n)) <= 2 for n in callsign_names())


def station(spoken: str) -> str:
    f = fold(spoken)
    if f in ALL_WORDS:
        return "all stations"
    if f in CONTROL_WORDS:
        return callsign(spoken) if any(same_word(f, fold(n)) for n in callsign_names()) else f
    return callsign(spoken)


def header(text: str) -> tuple[str | None, str | None, str | None, str, str]:
    """Like net.header for Ukrainian/Russian procedure: (to, from, single callsign, body, how).
    "Вежа, я Сокіл, ..." / "я Сокіл, ..." / "Сокіл, Вежа, ..." / "Сокіл, ..." / "Плюс, Сокіл.\""""
    toks = [t for t in tokens(text)]
    words = [(i, s, f) for i, (s, f) in enumerate(toks) if f not in ",.;!?"]
    acks = {fold(w) for w in ("плюс", "прийняв", "принял", "прийнято", "принято", "зрозумів", "понял")}

    def body_from(k: int) -> str:
        return " ".join(s for s, _ in toks[k:])

    for j, (i, s, f) in enumerate(words[:5]):
        if f == "я" and j + 1 < len(words):
            frm_i = j + 1
            name = words[frm_i][1]
            nxt = words[frm_i + 1][2] if frm_i + 1 < len(words) else ""
            # "я Граніт два, ..." is callsign Граніт 2; "я Сокол, два мавика" is a count. The number belongs to the
            # callsign only when it ends the call sign phrase (punctuation or end of text after it).
            after = toks[words[frm_i + 1][0] + 1][1] if frm_i + 1 < len(words) and words[frm_i + 1][0] + 1 < len(toks) else ","
            direct = frm_i + 1 < len(words) and words[frm_i + 1][0] == words[frm_i][0] + 1
            if direct and after in ",.;!?" and ((nxt.isdigit() and len(nxt) == 1)
                                                 or (_UNITS.get(nxt, 99) < 10 and float(_UNITS[nxt]).is_integer())):
                name, frm_i = f"{name} {words[frm_i + 1][1]}", frm_i + 1
            before = [w for w in words[:j] if w[2] not in acks]
            to = station(before[-1][1]) if before and _is_station(before[-1][2]) else None
            lead = " ".join(w[1] for w in words[:j] if w[2] in acks)
            return to, station(name), None, (lead + " " + body_from(words[frm_i][0] + 1)).strip(" ,.;"), "named in the call"
    first = [w for w in words if w[2] not in acks]
    if first and _is_station(first[0][2]):
        lead = " ".join(w[1] for w in words if w[2] in acks and w[0] < first[0][0])
        if len(first) > 1 and _is_station(first[1][2]) and first[1][0] - first[0][0] <= 2:
            rest = body_from(first[1][0] + 1)
            return station(first[0][1]), station(first[1][1]), None, f"{lead} {rest}".strip(" ,.;"), "abbreviated call"
        rest = body_from(first[0][0] + 1)
        return None, None, station(first[0][1]), f"{lead} {rest}".strip(" ,.;"), ""
    return None, None, None, text.strip(" ,.;"), ""


def ended(text: str) -> str | None:
    t = fold(text)
    if re.search(rf"\b{OUT}\s*$", t):
        return "out"
    return "over" if re.search(rf"\b{OVER}\s*$", t) else None


def fold_keep(text: str) -> str:
    """fold(), but punctuation stays: clause boundaries matter ("мінус, не Сарай. Сто метрів ...")."""
    return " ".join(f for _, f in tokens(text))


def strip_procedure(text: str) -> str:
    return re.sub(rf"\b(?:{OVER}|{OUT})\b", " ", fold_keep(text))


def kind_of(body: str) -> str | None:
    b = strip_procedure(body).strip(" ,.;")
    if not b:
        return "call"
    if re.search(rf"\b{SAY_AGAIN}\b", b):
        return "say_again"
    if re.search(rf"\b{CHECK}\b", b):
        return "radio_check"
    if re.search(rf"\b{ORDER_MOVE}\b", b) or re.search(rf"\b{ORDER_HOLD}\b", b):
        return "order"
    if re.search(rf"\b{REQUEST}\b", b) and not re.search(_DIST, b):
        return "request"
    rest = re.sub(rf"\b{ACK}\b", " ", b)
    rest = " ".join(w for w in re.sub(r"[,.;!?]", " ", rest).split() if not _is_station(w))
    return "ack" if not rest else None


def order(body: str) -> tuple[str, str | None] | None:
    """("move", destination as spoken) or ("hold", None)."""
    b = strip_procedure(body).strip(" ,.;")
    m = re.search(rf"\b{ORDER_MOVE}\s+(?P<a>[^,.;]+)", b)
    if m:
        return "move", m["a"].strip()
    return ("hold", None) if re.search(rf"\b{ORDER_HOLD}\b", b) else None


MOVE_VERBS = _alt("рухаюсь", "рухаюся", "рухаємось", "рухаються", "рухається", "іду", "йду", "йдемо", "йде", "йдуть",
                  "иду", "идем", "идет", "идут", "висуваюсь", "выдвигаюсь", "двигаюсь", "двигаемся", "двигается",
                  "двигаются", "летить", "летять", "летит", "летят", "пройшов", "прошел", "пролетів", "пролетел")
TOWARDS = _alt("до", "к", "в напрямку", "в направлении", "в сторону", "у напрямку", "у бік", "в бік")
NEAR = _alt("поруч з", "поруч із", "рядом с", "недалеко від", "недалеко от", "біля", "возле", "около", "коло", "near")
SEE = _alt("бачу", "вижу", "спостерігаю", "наблюдаю", "курс")


def _anchor(name: str | None) -> dict | None:
    if not name:
        return None
    name = re.split(rf"[,.;]|\s(?:не|{MOVE_VERBS}|{SEE})\s", f" {name} ")[0]
    name = re.sub(rf"\s*{_DIST}.*$", "", name)
    name = re.sub(rf"^(?:{_PREP}\s+)+", "", name.strip())
    name = re.sub(rf"\b(?:{OVER}|{OUT})\b.*$", "", name).strip()
    return {"name": name, "kind": "landmark"} if name else None


# Spoken distance units (folded stems) -> metres per unit. Rewritten to "<n> м" before the patterns run.
_UNIT_M = [(r"(?:километр\w*|км|клик\w*)", 1000), (r"(?:метр\w*|м)", 1), (r"(?:крок\w*|шаг\w*)", 0.75),
           (r"(?:квартал\w*)", 100), (r"(?:хвилин\w*\s+пишки|минут\w*\s+пешком|хв\s+пишки)", 80)]
_UNIT_ANY = "|".join(f"(?:{u})" for u, _ in _UNIT_M)
_RANGE_SEP = r"(?:-|–|до|або|или|чи)"
# Directions and other relations (folded). Each maps a phrase before the place to a relation.
_REL_WORDS = [
    (_alt("навпроти", "напроти", "напротив", "через дорогу від", "через дорогу от", "через вулицю від",
          "через улицу от"), "opposite"),
    (_alt("всередині", "всередину", "в середині", "внутри", "на території", "на территории", "у дворі", "во дворе"),
     "inside"),
    (_alt("в районі", "в районе", "у районі", "в околицях", "в окрестностях", "десь біля", "где-то возле",
          "десь в районі", "в межах"), "around"),
    (_alt("не доходячи до", "не доходя до", "не доїжджаючи до", "не доезжая до", "трохи не дійшовши до", "перед"),
     "in_front_of"),
    (_alt("по той бік", "по тій стороні", "по ту сторону", "на тому боці", "на той стороне", "за межами", "пройшовши",
          "пройдя", "після", "после"), "behind"),
    (_alt("ліворуч від", "зліва від", "слева от", "лівіше", "левее", "ліворуч", "слева"), "left_of"),
    (_alt("праворуч від", "справа від", "справа от", "правіше", "правее", "праворуч", "справа"), "right_of"),
]
_CROSS = _alt("перехрестя", "перехресті", "перекресток", "перекрёсток", "перекрестке", "на розі", "ріг", "розі",
              "угол", "углу", "на углу", "розвилка", "развилка")
_ALONG = _alt("уздовж", "вздовж", "вдоль", "по вулиці", "по улице")
_BEARING = rf"(?:по\s+)?(?:азимут\w*|пеленг\w*)\s+(?P<deg>\d{{1,2}}\s*[-–\s]\s*\d{{2}}\b|\d+(?:\.\d+)?|(?:\b(?:{_NUMW})\b\s*)+)\s*(?P<bu>градус\w*|мил\w*|тисячн\w*|тысячн\w*)?"


def _bearing_deg(raw: str, unit: str | None) -> float | None:
    """"45" -> 45; "15-00" -> 90 (Soviet-style divisions of the goniometer, 60-00 a full turn); "1600 мил" -> 90
    (NATO mils, 6400 a full turn); "сорок п'ять градусів" -> 45."""
    raw = raw.strip()
    m = re.fullmatch(r"(\d{1,2})\s*[-–\s]\s*(\d{2})", raw)
    if m:
        return (int(m[1]) * 100 + int(m[2])) * 360 / 6000 % 360
    n = number(raw)
    if n is None:
        return None
    u = unit or ""
    if u.startswith("мил"):
        return n * 360 / 6400 % 360
    if u.startswith(("тисячн", "тысячн")) or n > 360:
        return n * 360 / 6000 % 360
    return n % 360


def _split_number(text: str) -> tuple[str, str]:
    """Number words said back to back: a number reads big to small ("двісті п'ятдесят"), so a word bigger than the
    one before it starts a new number. Returns (words before the last number, the last number)."""
    ws = text.split()
    vals = [_UNITS.get(w) if not w.replace(".", "").isdigit() else float(w) for w in ws]
    if len(ws) < 2 or any(v is None for v in vals):
        return "", text
    start = len(ws) - 1
    while start > 0 and vals[start - 1] > vals[start]:
        start -= 1
    return " ".join(ws[:start]), " ".join(ws[start:])


def distances(c: str) -> tuple[str, dict]:
    """Folded clause -> clause with every distance as "<n> м", and what it learnt: vague, distance_min_m/max_m."""
    info: dict = {}
    for pat, repl in ((_alt("пів кілометра", "півкілометра", "пол километра", "полкилометра", "півкіломeтра"), "500 м"),
                      (_alt("кілька сотень метрів", "несколько сотен метров", "пару сотень метрів", "пару сотен метров",
                            "кількасот метрів"), "300 м")):
        if re.search(pat, c):
            c = re.sub(pat, repl, c)
            info["vague"] = info.get("vague") or repl == "300 м"

    def factor(u: str) -> float:
        return next(f for pat, f in _UNIT_M if re.fullmatch(pat, u))

    def to_m(m: re.Match) -> str:
        f = factor(m["u"])
        lead, n = _split_number(m["n"])   # "сорок п'ять триста метрів": the angle, then 300 m
        if lead:
            return f"{lead} " + to_m_value(n, None, f, m)
        return to_m_value(m["n"], m.groupdict().get("n2"), f, m)

    def to_m_value(n: str, n2: str | None, f: float, m: re.Match) -> str:
        a = number(n)
        if a is None:
            return m[0]
        if n2:
            b = number(n2)
            if b is not None:
                lo, hi = sorted((a * f, b * f))
                info.update(distance_min_m=round(lo), distance_max_m=round(hi), vague=True)
                return f"{round((lo + hi) / 2)} м "
        if f in (100, 80, 0.75):
            info["vague"] = True
        return f"{round(a * f)} м "   # the number pattern eats the space after it

    c = re.sub(rf"(?:\b(?:вид|от)\s+)?(?P<n>{_N})\s*{_RANGE_SEP}\s*(?P<n2>{_N})\s*(?P<u>{_UNIT_ANY})\b", to_m, c)
    c = re.sub(rf"(?P<n>{_N})\s*(?P<u>{_UNIT_ANY})\b", to_m, c)
    # "метрів сто" (unit before the number) is approximate
    c = re.sub(rf"\b(?P<u>{_UNIT_ANY})\s+(?P<n>{_N})\b", lambda m: (info.__setitem__("vague", True), to_m(m))[1], c)
    return re.sub(r"\s+", " ", c).strip(), info


def parse_location(clause: str) -> dict | None:
    """One clause (folded) -> a report with anchor and relation, or None."""
    c = re.sub(rf"\b{POSITION_WORDS}\b", " ", clause)
    c = re.sub(r"\s+", " ", c).strip(" ,.;")
    if not c:
        return None
    c, info = distances(c)
    vague = bool(info.get("vague")) or bool(re.search(rf"\b{VAGUE}\b", c))
    dist = None
    m = re.search(_DIST, c)
    if m:
        dist = number(m["d1"] or m["d2"])

    def out(rel, a, b=None, typ="position", **more):
        anc = _anchor(a)
        if not anc:
            return None
        r = {"subject": None, "type": typ, "anchor": anc, "anchor2": _anchor(b), "relation": rel,
             "distance_m": dist, "minutes_ago": None, "confidence": 0.5, "vague": vague, **more}
        for k in ("distance_min_m", "distance_max_m"):
            if k in info:
                r[k] = info[k]
        return r

    m = re.search(_BEARING, c)
    if m:
        deg = _bearing_deg(m["deg"], m["bu"])
        rest = c[m.end():]
        a = re.search(rf"(?:\b(?:вид|от)\s+)(?P<a>.+)", rest) or re.search(rf"(?:\b(?:вид|от)\s+)(?P<a>.+?)(?:\s+по\s+азимут|$)", c)
        if deg is not None and a:
            return out("bearing", a["a"], bearing_deg=deg)
    m = re.search(rf"\b{_CROSS}\s+(?P<a>.+?)\s+(?:и|та|and|з|с)\s+(?P<b>.+)", c)
    if m:
        return out("intersection", m["a"], m["b"])
    m = re.search(rf"\b(?:миж|между|between)\s+(?P<a>.+?)\s+(?:и|та|and)\s+(?P<b>.+)", c)
    if m:
        return out("between", m["a"], m["b"])
    # "100 метрів на схід від Сараю", "к северу от Сарая", "east від озера", "севернее Сарая", "північніше Сараю"
    m = re.search(rf"(?:\bна\s+|\bк\s+|\bto the\s+)?(?P<dir>{_DIR})\s+(?:вид|от|of|from)\s+(?P<a>.+)", c)
    if not m:
        m = re.search(rf"(?P<dir>(?:(?:пивнично|северо|пивденно|юго)\s*)?\w+(?:ише|ее))\s+(?P<a>.+)", c)
    if m:
        d = m["dir"]
        rel = relation_of(re.sub(r"(?:ише|ее)$", "", d)) or relation_of(d)
        if rel:
            return out(rel, m["a"])
    for words_, rel in _REL_WORDS:
        m = re.search(rf"\b{words_}\s+(?:вид\s+|от\s+)?(?P<a>(?!{_N}\s*м\b).+)", c)
        if m:
            return out(rel, m["a"])
    # "300 метрів від школи": a distance with no direction
    m = re.search(rf"(?:{_DIST})\s+(?:вид|от)\s+(?P<a>.+)", c)
    if m:
        return out("from", m["a"])
    m = re.search(rf"\b{_ALONG}\s+(?P<a>.+)", c)
    if m:
        return out("along", m["a"], typ="movement")
    m = re.search(rf"\b{MOVE_VERBS}\s+{TOWARDS}\s+(?P<a>.+)", c)
    if m:
        return out("towards", m["a"], typ="movement")
    m = re.search(rf"\b{_alt('в напрямку', 'в направлении', 'в сторону', 'у напрямку')}\s+(?P<a>.+)", c)
    if m:
        return out("towards", m["a"], typ="movement")
    m = re.search(rf"\b(?:позаду|позади|за)\s+(?P<a>(?!{_N}).+)", c)
    if m:
        return out("behind", m["a"])
    m = re.search(rf"\b{NEAR}\s+(?P<a>.+)", c)
    if m:
        return out("near", m["a"])
    m = re.search(rf"\b(?:на|в|у|при|at)\s+(?P<a>.+)", c)
    if m:
        return out("at", m["a"])
    return None


def _joins(text: str) -> str:
    """Before folding: "двісті-триста метрів" is a range (folding would drop the dash and add them up), and
    "азимут сорок п'ять, триста метрів від Сараю" is one clue said with a pause."""
    def rng(m: re.Match) -> str:
        before = fold(text[max(0, m.start() - 20):m.start()])
        if re.search(r"(?:азимут|пеленг)\w*\s*$", before) or not (number(m[1]) and number(m[2])):
            return m[0]
        return f"{m[1]} до {m[2]}"
    t = re.sub(r"([\w'’ʼ]+)\s*[-–]\s*([\w'’ʼ]+)", rng, text)
    return re.sub(r"((?:азимут|пеленг)\w*\s+[^,.;]{1,30}?)\s*,\s*(?=[^,.;]{1,40}?\b(?:від|от)\b)", r"\1 ", t,
                  flags=re.I)


def stub_extract_uk(text: str) -> dict:
    """Rule-based fallback for Ukrainian/Russian radio reports: the closed demo grammar (header, corrections,
    holding, eight directions, distances, between/near/behind/at, movement). Free speech needs the language model."""
    text = _joins(text)
    to, frm, single, body, _ = header(text)
    speaker = frm or (single if single and not (fold(single) in CONTROL_WORDS or single == "all stations") else None)
    t = strip_procedure(body)
    t = re.sub(rf"^(?:{ACK})\b[\s,.]*", "", t)
    correction = False
    marks = list(re.finditer(rf"\b{CORRECTION}\b", t))
    if marks:
        correction, t = True, t[marks[-1].end():]
    # A sighting ("ждун біля Сараю ...", "бачу трьох ...") runs from the clause that starts it to the end; what comes
    # before it is the speaker's own position.
    from . import contact_uk
    clauses = [c.strip() for c in re.split(r"\s*[,.;!?]\s*", t) if c.strip()]
    seen = next((i for i, c in enumerate(clauses) if contact_uk.starts_contact(c)), None)
    sightings = []
    if seen is not None:
        sightings.append(contact_uk.report(", ".join(clauses[seen:]), speaker))
        clauses = clauses[:seen]
    # "не озеро": what it is not. But "не доходячи до X" (just short of X) is a place.
    t = re.sub(r"\bне\s+(?!доход|доиждж|доезж|дойд)[^,.;]*", " ", ", ".join(clauses))
    intent = bool(re.search(rf"\b{INTENT}\b", t))
    reports = []
    for clause in filter(None, (c.strip() for c in re.split(r"\s*[,.;!?]\s*", t))):
        r = parse_location(clause)
        if r is None and re.search(rf"\b{HOLDING}\b", clause):
            r = {"subject": None, "type": "holding", "anchor": None, "anchor2": None, "relation": "at",
                 "distance_m": None, "minutes_ago": None, "confidence": 0.6}
        if r is None:
            continue
        if intent:
            r["type"] = "intent"
        elif correction and r["type"] != "holding":
            r["type"] = "correction"
        reports.append(r)
        break   # one location per transmission in the demo grammar; the model handles more
    reports = sightings + reports
    if not reports:
        reports = [{"subject": None, "type": "other", "anchor": None, "anchor2": None, "relation": "at",
                    "distance_m": None, "minutes_ago": None, "confidence": 0.0}]
    return {"speaker": speaker, "reports": reports}


def vocabulary() -> list[str]:
    """Words to prime speech-to-text with for a Ukrainian/Russian net: callsigns, procedure, the commonest threats."""
    from . import contact_uk
    words = callsign_names() + ["прийом", "приём", "плюс", "мінус", "кінець зв'язку", "без змін", "доповідай"]
    return list(dict.fromkeys(words + [r["spoken"] for r in contact_uk.ROWS][:30]))
