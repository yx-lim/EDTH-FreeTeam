# Language layer for Voice-to-Map (Team 27)

This folder makes the pipeline work on real Ukrainian and Russian radio talk,
and measures how well it works. It plugs into **layer 2 (output fields)** and
**layer 3 (geocoding and geometry)**. Whisper, Mistral, FastAPI and the frontend stay as they are.

Owner: Nikita (datasets and testing). Questions about the data go to him.

```
voice ─► Whisper ─► Mistral (layer 2) ─► JSON ─► resolve() ─► place_report() ─► fuser.add() ─► map
                                          │         │               │                │
                                          │   alias_lookup.py   geometry.py        fuse.py
                                          │   threat_lookup.py  angles.py
                                          └── fields below
```

## 1. What layer 2 (Mistral) must output, one JSON per call

```json
{
  "id": "UA01",                    // only needed for testing
  "callsign": "Сокіл",             // who is speaking
  "action": "position",            // position | moving | halted | observing | contact | drone_sighting
  "landmark": "Венсенський замок", // as spoken, without prepositions ("від", "біля", "от")
  "relation": "north_of",          // north_of ... northwest_of | at | near | behind | between | above
                                   // | same_as_last | clock_3 | half_right | bearing_mils_1500
  "distance": 50,                  // metres as a number ("двісті п'ятдесят" -> 250); 0 if none
  "vague": false,                  // true for "метрів сто", "близько", "трохи далі"
  "heading": "east",               // direction the speaker is moving, if said ("рухаюсь на схід")
  "threat_word": "ждун",           // drone or threat word as spoken, if any
  "count": 1,                      // "два мавіки" -> 2
  "another": false                 // true for "ще один", "ещё один", "another", "другий"
}
```

Corrections ("мінус", "отставить", "correction") must replace the earlier landmark.
The full list of `relation` values used in testing is in the `relation` column of
`voice_to_map_test_set.csv`.

## 2. What to call in layer 3

```python
from alias_lookup import resolve
from threat_lookup import resolve_threat
from angles import clock_to_bearing, mils_to_degrees, words_to_bearing
from geometry import place_report
from fuse import SightingFuser

fuser = SightingFuser()            # one per command post

# a) Where is the landmark? Checks moving units, then mission codenames, then aliases.
place = resolve(js["landmark"], area="Vincennes",
                unit_positions={"Птаха": (lat, lon, unix_time)})   # drones, other patrols
# place["source"] == "unit" | "mission"  -> has lat/lon, no OSM call needed
# place["source"] == "alias" | "raw"     -> search place["name"] in landmarks.csv / Nominatim

# b) Turn clock / mils / "half right" into a bearing when needed
bearing = clock_to_bearing(3, heading=90)          # "на 3 годині", moving east
bearing = mils_to_degrees(1500, system="ua")       # "азимут 15-00" (6000-mil system)

# c) Place the report using the landmark's SHAPE, not its centre
pos = place_report(coords, kind, js["relation"], js["distance"],
                   last_position=unit_history.get(js["callsign"]),
                   vague=js["vague"],
                   bearing_deg=bearing)            # only with relation="bearing"
# -> {"lat", "lon", "uncertainty_m", "method"}   draw a CIRCLE of uncertainty_m

# d) Drone or enemy sightings: merge duplicates across units
threat = resolve_threat(js["threat_word"])         # -> {"type", "category", ...} or None
marker, what = fuser.add(js["callsign"], threat["category"], pos["lat"], pos["lon"],
                         pos["uncertainty_m"], t=time.time(),
                         count=js["count"], another=js["another"])
fuser.markers(now=time.time())                     # what the map draws
```

`coords` and `kind` come from `landmarks.csv` (columns `geometry` and `kind_of_shape`).
For a mission point, use `[(lat, lon)]` and `"point"`.

## 3. Files

| File | What it is | Needed for demo? |
|---|---|---|
| `alias_lookup.py` | Finds a place from how it's spoken (endings, Russian or Ukrainian, numbers as words) | **Yes** |
| `landmark_aliases.csv` | Spoken names to OSM names, EN/UK/RU | **Yes** |
| `mission_points.csv` | Unit codenames (Ромашка, Сарай...) with coordinates. **Fill in lat/lon before the demo** | **Yes** |
| `geometry.py` | Places reports using shapes and gives an uncertainty circle (`pip install shapely`) | **Yes** |
| `threat_lookup.py` + `threat_vocab.csv` | Drone slang to standard type ("ждун", "мопед", "крило") | Yes, if drone demo |
| `fuse.py` | Merges sightings of the same drone from different units, keeps identical drones apart | Yes, if drone demo |
| `angles.py` | Clock method, mils (6000 vs 6400), half right | Nice to have |
| `fetch_osm_landmarks.py` | Downloads all named places with outlines into `landmarks.csv`, run once with internet | Yes, for offline |
| `voice_to_map_test_set.csv` | 58 test calls (EN, UK, RU, mixed) with correct answers | Testing |
| `check_dataset.py` | Checks the datasets agree with each other, no audio needed | Testing |
| `evaluate.py` | Scores `predictions.jsonl` and prints accuracy by language | Testing |

## 4. Tonight

1. `pip install shapely requests`
2. `python fetch_osm_landmarks.py`, which creates `landmarks.csv`. If it errors, widen the area boxes at the top.
3. Pick 4 points in the Bois de Vincennes on the map and paste lat/lon into `mission_points.csv`.
4. `python check_dataset.py` should say every call resolves.
5. Wire `resolve()` and `place_report()` into layer 3. Everything else can come after the core demo works.

## 5. Testing (Saturday)

Nikita records the calls. Run each through the pipeline and write one JSON line per call to
`predictions.jsonl` (fields as in section 1, plus `lat` and `lon`), then:

```
python evaluate.py
```

Calls are split into a **practice set** (tune on these as much as you like) and a **held-out set**
(run once on Sunday morning; that is the number for the slide). Don't tune on held-out results.

## Rules

* Invented callsigns and public places only. Never real positions or unit names.
* Speeds and time windows in `fuse.py` are estimates. Tune them, and say so if asked.
* A circle that is honest beats a pin that is precise and wrong.
