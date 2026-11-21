# Voice-to-Map

Starter for EDTH Paris 2026, Challenge 01 (Lysk): spoken position reports become live map updates.

The idea that sets it apart: a report becomes an **uncertainty region**, not a pin, and the system keeps
**state per callsign**. The language model only names what was said (who, which place, which relation);
deterministic geometry over a pre-downloaded OpenStreetMap extract turns that into a region, checks it is
physically reachable, and keeps a corrected, timestamped history.

```
push-to-talk            -> speech-to-text ->                                  extract (Gemini / Mistral JSON / rules) -> tracker (state, corrections) -> resolver (Shapely, street routing) -> WebSocket -> MapLibre
radio net -> VAD cuts   -> speech-to-text -> net (who, to whom, what kind) -> extract -> tracker ...
```

See [docs/PRD.md](docs/PRD.md) and [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md).

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/uvicorn backend.app:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:5173, hold **Space** (or the button) and say
`Zero, this is Alpha two, south of the Saint-Sulpice church, over`. Or type it.

Copy `.env.example` to `.env` and add keys. With `GEMINI_API_KEY`, Gemini (`gemini-3.5-flash-lite`, ~1 s) reads the
reports; with `ELEVENLABS_API_KEY`, ElevenLabs Scribe does speech-to-text. The **speech** dropdown at the top of the panel
switches speech-to-text live between ElevenLabs, Gemini, local Whisper and the browser (until the backend restarts). A Mistral key works for both too. With no
keys everything runs offline apart from the map tiles: a rule-based extractor (English, French, Ukrainian demo
grammar) and local Whisper (`pip install faster-whisper`) or the browser's speech recognition. If a cloud call fails,
the report still goes through the rules, so the map never stops.

No callsign heard (noise, a clipped start)? With the **Default callsign** box filled in, the report goes to that unit,
marked "(assumed)" and drawn dashed until confirmed. With it empty, the report is held, not plotted, and the map reads
back "Station calling, say again your callsign". A reply such as "This is Delta three" within two minutes claims it.

## Radio-net mode

Open the **Radio net** tab and press **Listen to the net**, or **Play a recording**. Nobody presses a button per
transmission and nobody picks a callsign. A voice-activity detector cuts the channel into transmissions; each is
transcribed; `backend/net.py` works out who is talking from voice procedure and the order of the conversation, the
way an operator at the command post follows a net:

| Heard on the net | Read as |
|---|---|
| "Alpha two, this is Zero …", "Alpha deux de Zéro …", "Alpha two, Zero …" | named in the call |
| "Bravo two, south of the town hall, over", just after Zero called Bravo two | Bravo two answering with its own callsign |
| "At the Saint-Sulpice fountain, over", right after "Alpha one, send position" | Alpha one's reply |
| "Bravo two, say again, over", just after Bravo two spoke | Zero asking Bravo two to repeat; the repeat replaces the queried fix |
| "Roger, out." / "Wilco, out." | acknowledgement: ticks the report or order it answers |
| "Charlie one, move to the Medici fountain, over" | order: the destination is drawn dashed until Charlie one reports arriving |
| "Delta one reports he's at the corner of …" | relayed report about Delta one |
| a report that cannot be tied to anyone | logged and flagged "speaker not identified", never plotted |

Control stations (Zero, Command) never get a position of their own. Two transmissions caught in one segment are
split at "over"; one transmission cut in two by a pause is joined back to its speaker. Read-back is off on the net,
because it would hear itself.

Try it without a radio:

- **Replay demo net** plays `data/demo_net.jsonl` (24 transmissions, English and French) as text at 3× speed.
- `python -m scripts.make_demo_net` (macOS) voices the same script, one voice per station and band-limited like a
  handheld radio, into `data/demo_net.wav`. Play it with **Play a recording**, or `POST` it to `/net/recording`.

Audio needs server speech-to-text (an ElevenLabs or Mistral key, or faster-whisper). Without one, recordings are still cut into
transmissions but not transcribed, and **Listen to the net** falls back to the browser's own continuous recogniser.

## Contact reports

Soldiers can report what they see, not just where they are: *"Zero, this is Bravo one, contact, two enemy tanks,
moving north, 300 metres east of the church, over."* `backend/contact.py` reads what (infantry, sniper, tank, armoured
vehicle, vehicle, artillery, drone, helicopter, aircraft, IED, civilians), which side, how many, and whether it is moving
(and which way), static or firing. A sighting becomes its own track (`contact 1`, `contact 2`…) and never moves a
friendly unit. "200 metres north of me" is measured from the reporter's latest position.

| Said | Plotted as |
|---|---|
| "enemy" / "hostile" | red diamond (APP-6 hostile) |
| no side said | yellow quatrefoil: side unknown. Never assumed hostile, so a misheard word cannot paint a friend as a target |
| "civilians" | green square (neutral) |

The frame shape, not only the colour, carries the side, so it still reads in night mode and for colour-blind users.
A single report is dashed until the duty officer confirms it; contacts then fade by type (a drone after 3 minutes,
vehicles and troops after 15). Static hazards (IEDs, mines, cables) never vanish: they stay dashed as
"unconfirmed, N h old". The **To confirm** panel lists every draft; **C** confirms and **X** rejects the top card.
The **Contacts** button hides or shows them.

## Ukrainian and Russian

Pick **UK** or **RU** (or **Auto**) as the speech language, or type:
*"Вежа, я Граніт, ждун біля Сараю, метрів п'ятдесят на захід, не підходити, прийом."*
**Replay demo net** with UK or RU selected plays `data/demo_net_uk.jsonl`: positions, a correction, an order, and
sightings that merge across units.

| Heard | Read as |
|---|---|
| "Вежа, я Сокіл, …, прийом" / "Башня, я Сокол, …, приём" | Сокіл speaking to control; прийом = over |
| "Сокол", "Гранит" | the same units as Сокіл, Граніт (`data/callsigns.json`) |
| "на Ромашці", "від Сараю", "второй посадкой" | codenames Ромашка, Сарай, Друга посадка, with case endings (`data/codenames.json`) |
| "двісті п'ятдесят метрів", "полтораста", "метрів сто" | 250 m, 150 m, about 100 m (vague) |
| "мінус, мінус, не Сарай …", "без змін", "буду через …" | correction, holding, intent |
| "ждун", "мопед", "пташка", "мавік", "міна", "бачу трьох" | waiting FPV (30 min), Shahed (enemy, 2 min), drone, recon quad, mine (6 h), three people |
| "ще один ждун" | a second drone, never merged with the first |
| "мопед пройшов над палацом на захід" | over the palace, heading west |

Without a key the rules cover this demo grammar only (`backend/lang_uk.py`, `backend/contact_uk.py`); free speech
needs the language model (Gemini or Mistral), whose prompt now covers Ukrainian/Russian procedure and drone slang. A Cyrillic place that matches no
codename or alias is reported unknown, never guessed. Codenames rotate daily: replace `data/codenames.json` each
morning. Threat words, lifetimes and which systems count as enemy-only are in `data/threat_vocab.csv` (from a
teammate's list; rows marked `check` are unverified).

## What it understands

| Spoken | Result |
|---|---|
| "south of the church", "200 metres north of the Luxembourg palace", "a block west of …" | wedge outside the building, distance band if given |
| "corner of X and Y", "between X and Y", "on X outside Y" | street crossing, corridor, or both clues combined |
| "I moved towards Boulevard Saint-Germain" | walks the street network from every plausible start, capped at walking speed × time |
| "now at the church" | the church nearest this unit's last position (same words, different place for another unit) |
| "Zero, this is Alpha two …", "Charlie one and Charlie two at …", "Bravo one is at …, I'm at …" | right speaker, several units per transmission |
| "correction, east of the church, not south" | withdraws the last fix (kept, struck through), re-resolves in its context |
| "I'll be at Odéon in five minutes" / "holding position" / "back where I was ten minutes ago" | not a move / same place / from history |
| "I'm with Alpha one", "50 m north of Bravo two" | another unit as the anchor |
| "Rude Rennes", "San Sulpice", "Medici fountain", "town hall" | fuzzy and alias matching (`data/aliases.json`) |
| "the Odin", "Saint Germain de Pray" | matched by sound (Odéon, Saint-Germain-des-Prés), plotted dashed with "confirm" |
| "this is Alfa won", "Charly too", "fox trot three" | misheard NATO callsigns snapped back (Alpha 1, Charlie 2, Foxtrot 3) |
| "Гранід", "Сакіл" | a Ukrainian/Russian nickname matched by sound to the callsign table (Граніт, Сокіл) |
| "100 yards", "300 feet", "half a click", "two blocks", "five minutes' walk", "a couple hundred metres" | converted to metres; approximate ones widen the band |
| "between 200 and 300 metres east of …", "about 200 m …" | a distance range / a wider band |
| "bearing 045, 300 m from …", "azimuth 1600 mils", "north-northeast of …" | a narrow 30° wedge on that bearing |
| "400 metres from the Panthéon" | a ring around it (no direction said) |
| "opposite", "across the street from", "inside", "in the area of", "past", "short of", "left / right of" | band outside the walls, the footprint, a wide circle, far / near side and left / right seen from the last position |
| "checkpoint 3" after right-clicking the map to name it | operator-named points, valid at once |
| "at the Eiffel Tower", "roger, out" | flagged, never plotted |

A **speed check** rejects candidates a unit could not have reached since its last report, and flags the move if
none is reachable (usually a misheard name). Each unit's last region grows on the map at walking pace while it
is silent. The event log (`data/events.jsonl`) is replayed on restart.

## Layout

| Path | What it does |
|---|---|
| `backend/extract.py` | Transcript to transmission `{speaker, reports[]}` (Gemini or Mistral, falls back to rules on any error) |
| `backend/tracker.py` | Per-callsign state, corrections, holding/intent/history, combining clues, event log and replay |
| `backend/resolver.py` | One report to a region; one rule per spatial relation; speed check |
| `backend/geo.py` | Gazetteer: aliases, fuzzy and sound-alike names, OSM alternative names, custom points, street graph and walking regions |
| `backend/callsign.py` | Misheard NATO callsigns back to canonical form ("Alfa won" → Alpha 1), by sound |
| `backend/stt.py` | Speech-to-text, switchable at run time (`GET/POST /stt`): ElevenLabs Scribe, Gemini, Voxtral with place-name vocabulary (`context_bias`), or local faster-whisper |
| `backend/net.py` | Radio-net mode: split at "over"; speaker, addressee and kind (report, request, order, ack, say again, radio check); acks, repeats, taskings |
| `backend/vad.py`, `frontend/src/vad.js` | Energy voice-activity detection that cuts a channel into transmissions (server for recordings, browser live) |
| `backend/app.py` | FastAPI: `POST /report`, `POST /audio`, `POST /net/text`, `POST /net/audio`, `POST /net/recording`, `POST /net/replay`, `GET /state`, `GET/POST /stt`, `POST /places`, `POST /events/{id}/confirm`, `POST /events/{id}/reject`, `GET /picture.nvg`, `GET /picture.geojson`, `GET /export.geojson`, `POST /reset`, `WS /ws` |
| `data/aliases.json` | Spoken names to OSM names; also sent to speech-to-text as vocabulary |
| `data/demo_net.jsonl`, `scripts/make_demo_net.py` | Scripted demo net, and a synthetic radio recording of it |
| `scripts/fetch_district.py` | Rebuild `data/gazetteer.json` for any bounding box |
| `scripts/evaluate.py`, `scripts/stress.py` | Smoke test, and the judge stress set in `tests/stress.jsonl` |
| `frontend/` | Vue + MapLibre: regions, paths, staleness rings, history scrubber, corrections, read-back |

## Check it

```bash
.venv/bin/pytest -q
```

```bash
.venv/bin/python -m scripts.evaluate
```

The stress set was used while tuning, so its pass rate is not a held-out accuracy figure. Write fresh
sentences (ideally with Lysk) and mark their truth points on a map before quoting a number.

## Built

What this repo can do now, grouped by area. Updated after each major implementation.

### 1. Hearing the radio
- **Push-to-talk**: hold Space (or the button), speak, release.
  - One press sends exactly one report; background chatter is ignored.
  - No callsign heard → the app replies "say again your callsign" instead of plotting an unknown unit.
  - The read-back plays only on the screen that sent the report, so it doesn't echo.
  - Fixed transmissions getting lost, stuck, or leaking into the next one (covered by tests).
- **Radio-net mode**: listens to a whole radio channel with nobody pressing anything.
  - Voice-activity detection cuts the channel into separate transmissions.
  - Works out who is talking from radio procedure ("Zero, this is Alpha two…") and from who was just called.
  - Transmissions it can't tie to anyone are logged, never plotted.
- **Offline speech-to-text**: local Whisper runs with no internet, so the demo survives bad Wi-Fi.
- **Cloud models**: ElevenLabs Scribe for speech-to-text and Gemini for reading reports, picked automatically when
  their keys are in `.env`; any failure falls back to the offline path.
- **Speech dropdown**: switch speech-to-text live between ElevenLabs, Gemini, Whisper and the browser. On test clips
  all three got English and Ukrainian right; ElevenLabs was fastest (~0.6 s), then Gemini (~1.5 s), Whisper (~3 s).

### 2. Understanding Ukrainian and Russian
- Ukrainian, Russian and mixed reports work in the language model, the speech-to-text and the UI.
- Codenames are found whatever their case ending: "від Сараю", "на Сараї" → Сарай.
- One unit whatever the spelling: Граніт (UA) = Гранит (RU).
- Radio procedure: "Вежа, я Сокіл… прийом", corrections ("мінус", "отставить").
- A rule-based fallback when no language model is available, and a Ukrainian demo net to replay.

### 3. Reporting what soldiers see (contacts)
- "Contact, two enemy tanks, moving north, 300 m east of the church" becomes its own marker; it never moves a friendly unit.
- NATO (APP-6) frames: red diamond = enemy, yellow = side unknown (never assumed enemy), green = civilians.
- Drone slang (ждун, мопед, пташка), counts ("два мавіки"), headings, "ще один" (= a new drone), and relayed reports.
- The same thing seen twice is merged into one marker instead of two.
- Units nearby are warned ("FPV at your position").
- Markers fade by type: a drone after 3 min, vehicles and troops after 15 min.
- Static hazards (IEDs, mines, cables, drones waiting on the ground) never vanish: past their fresh window they stay
  dashed as "unconfirmed, N h old".
- A moving contact shows an arrow for its heading.

### 4. Positions and grids
- Grid references read out loud ("three one uniform…") place a report directly, for own units and contacts.
- Military map look: NATO symbols, MGRS grid overlay, dark, satellite and topo base maps.
- A confirm step before an unconfirmed report goes on the map.
- **Bigger, richer place list**: 5,700 places over about 3 × 3 km (was 385 over 1.2 km), from Notre-Dame and the
  Panthéon to Montparnasse: landmarks, streets, stations, cafés, restaurants, pharmacies, hotels, statues. Other names
  from OpenStreetMap (English, short, old, Ukrainian/Russian such as "Шатле") count too. Small, numerous places
  (cafés, restaurants…) only match their exact name, never a guess. Rebuild with `scripts/fetch_district.py`.
- **Misheard names**: callsigns snapped to the NATO alphabet by sound; places matched by sound as a last resort and
  flagged for the duty officer. Ukrainian callsigns are personal nicknames (not letter + number), so those are
  matched by sound against `data/callsigns.json`.
- **More ways to say where**: bearings (degrees, mils, 16 compass points), distance ranges and units (yards, feet,
  km, clicks, blocks, paces, minutes' walk), "about", "opposite", "inside", "in the area of", "past", "short of",
  "left/right of", "N metres from". Held-out stress set (offline rules): plotted 19 → 47 of 61, callsign right
  13 → 42 of 54.

### 5. Duty-officer queue and export
- A **To confirm** panel lists every draft: single enemy sightings first, then other sightings, then doubtful unit
  fixes (place uncertain, callsign assumed). Each card shows the symbol, place, grid, reporter and age.
- **C** confirms and **X** rejects the top card. A rejected report leaves the map (the unit falls back to its previous
  fix) but stays in the log, marked "rejected by the duty officer".
- **Export NVG** (NATO Vector Graphics) and **GeoJSON** give the current picture with APP-6 symbol codes and MGRS.
  Only confirmed items leave by default (`?drafts=true` adds drafts), so a guess never looks like a fact.

### 6. For the team app (Sarthak's repo)
- `integrations/` holds a patch that adds spoken grid references to the React/Gemini app. **Sarthak needs to apply it.**

## Not done yet

**Must fix**
- Team app: old threats never leave its map (it draws from the event list, not the merged sightings).
- Speech-to-text has not been tested on real radio-quality Ukrainian audio yet. Compare ElevenLabs Scribe, Gemini and
  gpt-4o-transcribe on degraded recordings and score callsigns, places and numbers. (Skip Voxtral: no Ukrainian.)

**Make the map more honest**
- A misheard place should show two candidate places for the officer to pick (today: the best sound-alike, flagged).
- Measure "truth was inside the circle X of 20" for the pitch slide.

**Next features (by value)**
1. Name landmarks by voice ("позначка: спалений танк") and load a daily code table.
2. Casualty card from 200/300 reports.
3. Friendly drone corridors, so infantry don't jam or shoot our own drones.
4. Reported threats along a route ("last report 5 min ago", never called safe).
5. Read a Lore-style log and build the map from it.

**Later**: streaming speech-to-text, offline map tiles, ATAK export, "in front of" by building entrance.

**Don't claim** Delta integration, a real front-line accuracy %, or that Lore can't do Ukrainian.

Map data © OpenStreetMap contributors, ODbL. The public OSM tile server is fine for development only.
