"""Write the Irpin accuracy sets: data/zones/irpin/stress_uk.jsonl (tuning) and stress_uk_holdout.jsonl (held out).

    ZONE=irpin python -m scripts.make_zone_stress
    python -m scripts.stress --zone irpin [--offline] [--holdout] [--pace 4.5]

Each turn is a Ukrainian, Russian or mixed radio report. Its truth (where the unit really is) is computed from the
OpenStreetMap geometry of the zone, so it is reproducible: "200 metres north of the market" is 200 m north of the
market's edge; a street corner is where the two streets cross; "between A and B" is the midpoint. Truths are synthetic:
they test hearing, naming and geometry, not how far real soldiers' words are from where they stand.

The held-out set uses other speakers and other wordings. Keep it honest: read only its summary table, and if you
fix one of its failures, move that turn into the tuning set and write a new held-out one.
"""
from __future__ import annotations

import json
import math
import os

os.environ.setdefault("ZONE", "irpin")

from shapely.geometry import LineString, Point  # noqa: E402

from backend import zone  # noqa: E402
from backend.geo import Gazetteer  # noqa: E402

gaz = Gazetteer()
BY_NAME = {}
for p in gaz.places:   # one name, several objects (a station and a hotel both called "Ірпінь"): the landmark wins
    if p.name not in BY_NAME or (BY_NAME[p.name].minor and not p.minor):
        BY_NAME[p.name] = p
COMPASS = {"n": 0, "ne": 45, "e": 90, "se": 135, "s": 180, "sw": 225, "w": 270, "nw": 315}


def P(name: str):
    return BY_NAME[name]


def ll(pt: Point) -> dict:
    g = gaz.proj.to_ll(pt)
    return {"lat": round(g.y, 6), "lon": round(g.x, 6)}


def toward(origin: Point, bearing: float, d: float) -> Point:
    return Point(origin.x + d * math.sin(math.radians(bearing)), origin.y + d * math.cos(math.radians(bearing)))


def edge(name: str, bearing: float) -> Point:
    """Where a ray from the middle of a place leaves it (the place itself for a point)."""
    p = P(name)
    c = p.geom.centroid
    if not p.geom.area:
        return c
    ray = LineString([c, toward(c, bearing, 3000)])
    hit = ray.intersection(p.geom.boundary)
    pts = list(getattr(hit, "geoms", [hit]))
    return min(pts, key=c.distance) if pts and not hit.is_empty else c


def at(name: str) -> Point:
    p = P(name)
    if p.kind == "street":
        return p.geom.interpolate(p.geom.project(p.geom.centroid))   # on the street, near its middle
    return p.geom.centroid


def off(name: str, direction: str, d: float) -> Point:
    b = COMPASS[direction]
    return toward(edge(name, b), b, d)


def bearing_from(name: str, deg: float, d: float) -> Point:
    return toward(P(name).geom.centroid, deg, d)


def cross(a: str, b: str) -> Point:
    return P(a).geom.intersection(P(b).geom).centroid


def mid(a: str, b: str) -> Point:
    return LineString([at(a), at(b)]).interpolate(0.5, normalized=True)


def outside(name: str, direction: str = "s", d: float = 30) -> Point:
    return off(name, direction, d)


# (scenario, category, t, text, callsigns or [] for "do not plot", relation, acceptable anchors, truth point fn)
TUNE = [
    ("U1", "places", 0, "Вежа, я Сокіл, на вокзалі, прийом.", ["сокіл"], "at", ["Ірпінь"], lambda: at("Ірпінь")),
    ("U2", "places", 0, "Вежа, я Граніт, біля Центрального ринку, прийом.", ["граніт"], "near", ["Центральний ринок"],
     lambda: outside("Центральний ринок", "e", 25)),
    ("U3", "places", 0, "Вежа, я Лис, у Парку Перемоги, прийом.", ["лис"], "at", ["Парк Перемоги"], lambda: at("Парк Перемоги")),
    ("U4", "places", 0, "Вежа, я Явір, біля Троїцької церкви, прийом.", ["явір"], "near",
     ["Церква Святої Трійці ПЦУ"], lambda: outside("Церква Святої Трійці ПЦУ", "w", 20)),
    ("U5", "places", 0, "Вежа, я Беркут, на Привокзальній площі, прийом.", ["беркут"], "at", ["Привокзальна площа"],
     lambda: at("Привокзальна площа")),
    ("U6", "places", 0, "Вежа, я Ворон, біля бібліотеки, прийом.", ["ворон"], "near", ["Міська бібліотека"],
     lambda: outside("Міська бібліотека", "n", 20)),
    ("U7", "places", 0, "Вежа, я Сич, в Центральному парку, прийом.", ["сич"], "at", ["Центральний парк"],
     lambda: at("Центральний парк")),
    ("U8", "places", 0, "Вежа, я Шторм, біля кінотеатру Перун, прийом.", ["шторм"], "near", ["Перун"],
     lambda: outside("Перун", "e", 20)),
    ("S1", "streets", 0, "Вежа, я Сокіл, на перехресті Шевченка та Соборної, прийом.", ["сокіл"], "intersection",
     ["вулиця Шевченка", "Соборна вулиця"], lambda: cross("вулиця Шевченка", "Соборна вулиця")),
    ("S2", "streets", 0, "Вежа, я Граніт, на розі Центральної і Котляревського, прийом.", ["граніт"], "intersection",
     ["Центральна вулиця", "вулиця Котляревського"], lambda: cross("Центральна вулиця", "вулиця Котляревського")),
    ("S3", "streets", 0, "Вежа, я Лис, перехрестя Донцова і Соборної, прийом.", ["лис"], "intersection",
     ["вулиця Матвія Донцова", "Соборна вулиця"], lambda: cross("вулиця Матвія Донцова", "Соборна вулиця")),
    ("S4", "streets", 0, "Вежа, я Явір, на вулиці Шевченка, прийом.", ["явір"], "at", ["вулиця Шевченка"],
     lambda: at("вулиця Шевченка")),
    ("S5", "streets", 0, "Башня, я Ястреб, на улице Шевченко, приём.", ["яструб"], "at", ["вулиця Шевченка"],
     lambda: at("вулиця Шевченка")),
    ("D1", "directions", 0, "Вежа, я Сокіл, двісті метрів на північ від Центрального ринку, прийом.", ["сокіл"],
     "north_of", ["Центральний ринок"], lambda: off("Центральний ринок", "n", 200)),
    ("D2", "directions", 0, "Вежа, я Граніт, сто метрів на схід від вокзалу, прийом.", ["граніт"], "east_of",
     ["Ірпінь"], lambda: off("Ірпінь", "e", 100)),
    ("D3", "directions", 0, "Вежа, я Лис, триста метрів на захід від Парку Перемоги, прийом.", ["лис"], "west_of",
     ["Парк Перемоги"], lambda: off("Парк Перемоги", "w", 300)),
    ("D4", "directions", 0, "Башня, я Волк, метров двести южнее Центрального рынка, приём.", ["вовк"], "south_of",
     ["Центральний ринок"], lambda: off("Центральний ринок", "s", 200)),
    ("D5", "directions", 0, "Вежа, я Беркут, навпроти Троїцької церкви, прийом.", ["беркут"], "opposite",
     ["Церква Святої Трійці ПЦУ"], lambda: outside("Церква Святої Трійці ПЦУ", "s", 35)),
    ("D6", "directions", 0, "Вежа, я Ворон, в районі парку Правика, прийом.", ["ворон"], "around", ["Парк ім. Правика"],
     lambda: off("Парк ім. Правика", "e", 60)),
    ("D7", "directions", 0, "Вежа, я Сич, всередині Парку творчості письменників, прийом.", ["сич"], "inside",
     ["Парк творчості письменників"], lambda: at("Парк творчості письменників")),
    ("D8", "directions", 0, "Вежа, я Дніпро, між вокзалом і Центральним ринком, прийом.", ["дніпро"], "between",
     ["Ірпінь", "Центральний ринок"], lambda: mid("Ірпінь", "Центральний ринок")),
    ("M1", "distances", 0, "Вежа, я Кобзар, пів кілометра на південь від вокзалу, прийом.", ["кобзар"], "south_of",
     ["Ірпінь"], lambda: off("Ірпінь", "s", 500)),
    ("M2", "distances", 0, "Вежа, я Тайфун, двісті-триста метрів на схід від Центрального ринку, прийом.", ["тайфун"],
     "east_of", ["Центральний ринок"], lambda: off("Центральний ринок", "e", 250)),
    ("M3", "distances", 0, "Вежа, я Бук, азимут 15-00, триста метрів від Водокачки, прийом.", ["бук"], "bearing",
     ["Водокачка"], lambda: bearing_from("Водокачка", 90, 300)),
    ("M4", "distances", 0, "Вежа, я Чайка, азимут сорок п'ять, двісті метрів від Сараю, прийом.", ["чайка"], "bearing",
     ["Сарай"], lambda: bearing_from("Сарай", 45, 200)),
    ("M5", "distances", 0, "Вежа, я Орел, чотириста метрів від Ромашки, прийом.", ["орел"], "from", ["Ромашка"],
     lambda: bearing_from("Ромашка", 200, 400)),
    ("C1", "codenames", 0, "Вежа, я Скіф, сто метрів на схід від Сараю, прийом.", ["скіф"], "east_of", ["Сарай"],
     lambda: off("Сарай", "e", 100)),
    ("C2", "codenames", 0, "Башня, я Лис, между Ромашкой и второй посадкой, приём.", ["лис"], "between",
     ["Ромашка", "Друга посадка"], lambda: mid("Ромашка", "Друга посадка")),
    ("C3", "codenames", 0, "Вежа, я Граніт, на Орієнтирі три, прийом.", ["граніт"], "at", ["Орієнтир 3"],
     lambda: at("Орієнтир 3")),
    ("R1", "procedure", 0, "Вежа, я Граніт, сто метрів на північ від Сараю, прийом.", ["граніт"], "north_of", ["Сарай"],
     lambda: off("Сарай", "n", 100)),
    ("R1", "procedure", 20, "Вежа, я Граніт, мінус, мінус, не на північ. Сто метрів на південь від Сараю, прийом.",
     ["граніт"], "south_of", ["Сарай"], lambda: off("Сарай", "s", 100)),
    ("R2", "procedure", 0, "Вежа, я Сокіл, біля вокзалу, прийом.", ["сокіл"], "near", ["Ірпінь"],
     lambda: outside("Ірпінь", "n", 25)),
    ("R2", "procedure", 120, "Вежа, я Сокіл, без змін, прийом.", ["сокіл"], "previous", None,
     lambda: outside("Ірпінь", "n", 25)),
    ("R3", "procedure", 0, "Плюс, Граніт.", [], None, None, None),
    ("R4", "procedure", 0, "Всім, я Вежа, перевірка зв'язку, прийом.", [], None, None, None),
    ("H1", "misheard", 0, "Вежа, я Гранід, біля Центрального ринку, прийом.", ["граніт"], "near",
     ["Центральний ринок"], lambda: outside("Центральний ринок", "n", 25)),
    ("H2", "misheard", 0, "Вежа, я Альфа один, на вокзалі, прийом.", ["alpha 1"], "at", ["Ірпінь"], lambda: at("Ірпінь")),
    ("H3", "misheard", 0, "Вежа, я Сокіл, біля Цетрального ринку, прийом.", ["сокіл"], "near", ["Центральний ринок"],
     lambda: outside("Центральний ринок", "w", 25)),
    ("T1", "trap", 0, "Вежа, я Сокіл, біля Ейфелевої вежі, прийом.", [], None, None, None),
    ("T2", "trap", 0, "Вежа, я Граніт, біля Хрещатика, прийом.", [], None, None, None),
]

HOLDOUT = [
    ("HU1", "places", 0, "Вежа, я Яструб, знаходжусь біля залізничного вокзалу, прийом.", ["яструб"], "near", ["Ірпінь"],
     lambda: outside("Ірпінь", "s", 25)),
    ("HU2", "places", 0, "Башня, я Скиф, нахожусь возле Центрального рынка, приём.", ["скіф"], "near",
     ["Центральний ринок"], lambda: outside("Центральний ринок", "s", 25)),
    ("HU3", "places", 0, "Вежа, я Орел, стою біля Храму Святителя Миколи, прийом.", ["орел"], "near",
     ["Храм Святителя Миколи"], lambda: outside("Храм Святителя Миколи", "e", 20)),
    ("HU4", "places", 0, "Вежа, я Чайка, ми в Парку Героїв, прийом.", ["чайка"], "at", ["Парк Героїв"],
     lambda: at("Парк Героїв")),
    ("HU5", "places", 0, "Вежа, я Тайфун, закріпились біля поліції, прийом.", ["тайфун"], "near", ["Поліція"],
     lambda: outside("Поліція", "w", 25)),
    ("HU6", "places", 0, "Вежа, я Бук, біля Літнього театру, прийом.", ["бук"], "near", ["Літній театр"],
     lambda: outside("Літній театр", "n", 20)),
    ("HS1", "streets", 0, "Вежа, я Кобзар, на розі Соборної та Шевченка, прийом.", ["кобзар"], "intersection",
     ["Соборна вулиця", "вулиця Шевченка"], lambda: cross("вулиця Шевченка", "Соборна вулиця")),
    ("HS2", "streets", 0, "Башня, я Ворон, перекресток Центральной и Котляревского, приём.", ["ворон"], "intersection",
     ["Центральна вулиця", "вулиця Котляревського"], lambda: cross("Центральна вулиця", "вулиця Котляревського")),
    ("HS3", "streets", 0, "Вежа, я Сич, на Соборній, прийом.", ["сич"], "at", ["Соборна вулиця"],
     lambda: at("Соборна вулиця")),
    ("HS4", "streets", 0, "Вежа, я Шторм, на перехресті Полтавської та Гончара, прийом.", ["шторм"], "intersection",
     ["Полтавська вулиця", "вулиця Гончара"], lambda: cross("Полтавська вулиця", "вулиця Гончара")),
    ("HD1", "directions", 0, "Вежа, я Беркут, метрів сто п'ятдесят на захід від вокзалу, прийом.", ["беркут"],
     "west_of", ["Ірпінь"], lambda: off("Ірпінь", "w", 150)),
    ("HD2", "directions", 0, "Вежа, я Явір, на південь від Парку Перемоги, метрів двісті, прийом.", ["явір"],
     "south_of", ["Парк Перемоги"], lambda: off("Парк Перемоги", "s", 200)),
    ("HD3", "directions", 0, "Башня, я Дніпро, севернее вокзала метров на триста, приём.", ["дніпро"], "north_of",
     ["Ірпінь"], lambda: off("Ірпінь", "n", 300)),
    ("HD4", "directions", 0, "Вежа, я Вовк, напроти Центрального ринку, прийом.", ["вовк"], "opposite",
     ["Центральний ринок"], lambda: outside("Центральний ринок", "n", 35)),
    ("HD5", "directions", 0, "Вежа, я Сокіл, десь в районі Центрального парку, прийом.", ["сокіл"], "around",
     ["Центральний парк"], lambda: off("Центральний парк", "n", 60)),
    ("HD6", "directions", 0, "Вежа, я Граніт, між Троїцькою церквою і Парком Перемоги, прийом.", ["граніт"], "between",
     ["Церква Святої Трійці ПЦУ", "Парк Перемоги"], lambda: mid("Церква Святої Трійці ПЦУ", "Парк Перемоги")),
    ("HD7", "directions", 0, "Вежа, я Лис, на території Центрального ринку, прийом.", ["лис"], "inside",
     ["Центральний ринок"], lambda: at("Центральний ринок")),
    ("HM1", "distances", 0, "Вежа, я Кобзар, кілометр на північ від вокзалу, прийом.", ["кобзар"], "north_of",
     ["Ірпінь"], lambda: off("Ірпінь", "n", 1000)),
    ("HM2", "distances", 0, "Вежа, я Тайфун, від двохсот до трьохсот метрів на захід від Водокачки, прийом.",
     ["тайфун"], "west_of", ["Водокачка"], lambda: off("Водокачка", "w", 250)),
    ("HM3", "distances", 0, "Вежа, я Бук, по азимуту 30-00, двісті метрів від Ромашки, прийом.", ["бук"], "bearing",
     ["Ромашка"], lambda: bearing_from("Ромашка", 180, 200)),
    ("HM4", "distances", 0, "Вежа, я Чайка, п'ятсот метрів від вокзалу, прийом.", ["чайка"], "from", ["Ірпінь"],
     lambda: bearing_from("Ірпінь", 300, 500)),
    ("HC1", "codenames", 0, "Вежа, я Орел, біля Водокачки, прийом.", ["орел"], "near", ["Водокачка"],
     lambda: off("Водокачка", "e", 30)),
    ("HC2", "codenames", 0, "Башня, я Сыч, двести метров западнее Ромашки, приём.", ["сич"], "west_of", ["Ромашка"],
     lambda: off("Ромашка", "w", 200)),
    ("HR1", "procedure", 0, "Вежа, я Явір, біля бібліотеки, прийом.", ["явір"], "near", ["Міська бібліотека"],
     lambda: outside("Міська бібліотека", "e", 20)),
    ("HR1", "procedure", 30, "Вежа, я Явір, поправка, біля музею, прийом.", ["явір"], "near",
     ["Ірпінський історико- краєзнавчий музей"], lambda: outside("Ірпінський історико- краєзнавчий музей", "e", 20)),
    ("HR2", "procedure", 0, "Вежа, я Вовк, як чуєш, прийом.", [], None, None, None),
    ("HH1", "misheard", 0, "Вежа, я Сакіл, біля вокзалу, прийом.", ["сокіл"], "near", ["Ірпінь"],
     lambda: outside("Ірпінь", "e", 25)),
    ("HH2", "misheard", 0, "Вежа, я Браво два, на Привокзальній площі, прийом.", ["bravo 2"], "at",
     ["Привокзальна площа"], lambda: at("Привокзальна площа")),
    ("HH3", "misheard", 0, "Вежа, я Ворон, біля Центрального ринка, прийом.", ["ворон"], "near", ["Центральний ринок"],
     lambda: outside("Центральний ринок", "e", 25)),
    ("HT1", "trap", 0, "Вежа, я Лис, біля Майдану Незалежності, прийом.", [], None, None, None),
]


def rows(spec: list) -> list[dict]:
    out, seen = [], {}
    for scenario, category, t, text, callsigns, relation, anchors, truth in spec:
        seen[scenario] = seen.get(scenario, 0) + 1
        row = {"id": f"{scenario}.{seen[scenario]}", "scenario": scenario, "category": category, "t": t, "text": text,
               "expect": {"plot": bool(callsigns), "callsigns": callsigns, "type": "position", "relation": relation,
                          "anchor": anchors, "ambiguous": False},
               "truth": {cs: {**ll(truth()), "where": f"{relation} {', '.join(anchors or [])}".strip()}
                         for cs in callsigns} if truth else {},
               "naive": "", "truth_source": "computed from OSM geometry by scripts/make_zone_stress.py"}
        out.append(row)
    return out


if __name__ == "__main__":
    for name, spec in (("stress_uk.jsonl", TUNE), ("stress_uk_holdout.jsonl", HOLDOUT)):
        path = zone.DIR / name
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows(spec)), encoding="utf-8")
        print(f"{len(spec)} turns -> {path}")
