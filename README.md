# Voice-to-Map

Starter for EDTH Paris 2026, Challenge 01 (Lysk): spoken position reports become live map updates.

The idea that sets it apart: a report becomes an **uncertainty region**, not a pin, and the system keeps
**state per callsign**. The language model only names what was said (who, which place, which relation);
deterministic geometry over a pre-downloaded OpenStreetMap extract turns that into a region, checks it is
physically reachable, and keeps a corrected, timestamped history.

```
push-to-talk            -> speech-to-text ->                                  extract (Mistral JSON / rules) -> tracker (state, corrections) -> resolver (Shapely, street routing) -> WebSocket -> MapLibre
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

Without a `MISTRAL_API_KEY` in `.env` everything runs offline apart from the map tiles: a rule-based
extractor (English and French) and the browser's speech recognition. Copy `.env.example` to `.env` to use
Mistral for extraction and Voxtral for speech-to-text, or `pip install faster-whisper` for local Whisper.

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

Audio needs server speech-to-text (a Mistral key or faster-whisper). Without one, recordings are still cut into
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
vehicles and troops after 15, an IED after a day). The **Contacts** button hides or shows them.

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
| "checkpoint 3" after right-clicking the map to name it | operator-named points, valid at once |
| "at the Eiffel Tower", "roger, out" | flagged, never plotted |

A **speed check** rejects candidates a unit could not have reached since its last report, and flags the move if
none is reachable (usually a misheard name). Each unit's last region grows on the map at walking pace while it
is silent. The event log (`data/events.jsonl`) is replayed on restart.

## Layout

| Path | What it does |
|---|---|
| `backend/extract.py` | Transcript to transmission `{speaker, reports[]}` (Mistral, falls back to rules on any error) |
| `backend/tracker.py` | Per-callsign state, corrections, holding/intent/history, combining clues, event log and replay |
| `backend/resolver.py` | One report to a region; one rule per spatial relation; speed check |
| `backend/geo.py` | Gazetteer: aliases, fuzzy names, custom points, street graph and walking regions |
| `backend/stt.py` | Speech-to-text: Voxtral with place-name vocabulary (`context_bias`) or local faster-whisper |
| `backend/net.py` | Radio-net mode: split at "over"; speaker, addressee and kind (report, request, order, ack, say again, radio check); acks, repeats, taskings |
| `backend/vad.py`, `frontend/src/vad.js` | Energy voice-activity detection that cuts a channel into transmissions (server for recordings, browser live) |
| `backend/app.py` | FastAPI: `POST /report`, `POST /audio`, `POST /net/text`, `POST /net/audio`, `POST /net/recording`, `POST /net/replay`, `GET /state`, `POST /places`, `GET /export.geojson`, `POST /reset`, `WS /ws` |
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

Updated after each major implementation; newest last.

- **Radio-net mode:** listens to a whole channel with no button presses, cuts it into transmissions (voice-activity
  detection) and works out the speaker from radio procedure and conversation order.
- **Push-to-talk, made reliable:** one press sends one report; a report with no callsign gets "say again your
  callsign" instead of a guess; no read-back echo; lost, stuck and leaked transmissions fixed, with a tested state machine.
- **Offline speech-to-text:** local Whisper with no internet (audio decoding fixed, model preloaded).
- **Military map look:** NATO symbols, MGRS grid, dark, satellite and topo base maps, a confirm step before plotting.
- **Spoken grid references:** grids read out loud are plotted directly; a full stop between numbers counts as a pause.
- **Ukrainian/Russian:** codenames with case endings ("від Сараю" → Сарай), one callsign table across spellings,
  Cyrillic aliases, Ukrainian/Russian radio procedure and rule-based reports, a Ukrainian demo net.
- **Contact reports:** enemy, unknown and civilian sightings with APP-6 frames; repeat sightings merge; nearby units
  are warned; contacts fade by type.
- **Team app patch:** `integrations/` adds spoken grid references to the team's React/Gemini app (for Sarthak to apply).

## Not done yet

From research and the debate panel (21 Nov):

- **Speech-to-text comparison:** ElevenLabs Scribe v3 vs Gemini vs gpt-4o-transcribe on radio-degraded audio
  (`radio_effect.py`: narrow band, codec, noise, clipped first syllable). Score callsign, landmark and number accuracy,
  not word error rate. Don't use Voxtral for Ukrainian (not listed).
- **Team app bug:** stale threats never leave the map (it draws from the event list, not the fuser's state).
- **Static hazards** (mines, cables, waiting drones) never auto-delete: they turn "unconfirmed, N h old".
  No growing circles for fast movers; a direction arrow only when a heading is given.
- **Misheard place:** show two candidate places for the officer to pick; read-back is suggested, never automatic.
  Corroboration shrinks a circle only for independent reports, not relays.
- **Calibration:** "truth inside the circle X of 20", labelled synthetic data.
- **Duty-officer confirm queue:** radio call → pre-filled card → one key → map and NATO-format export.
- **Landmarks by voice** ("позначка: спалений танк") and a dated code table (codenames change daily).
- **Casualty card** built from 200/300 reports across several transmissions; strength shown as "last reported N, age X".
- **Friendly drone corridors:** a time-limited corridor that warns nearby infantry.
- **Route threats** for evacuation and supply: "last report X min ago", never coloured green or called safe.
- **Lore-log adapter:** read a Lore-style log (time, speaker, text) and build the map and cards from it.
- **Don't claim** Delta integration, a front-line accuracy percentage, or that Lore lacks Ukrainian.

Earlier gaps:

- Streaming speech-to-text (Voxtral realtime over WebSocket).
- Radio-net transcription on real radio audio: the cutting, attribution and endpoints are tested, but speech-to-text on
  radio-quality audio has not been run yet (no key or model here). Speaker diarisation is not used; attribution relies on procedure.
- Tap-to-pick among ambiguous places; spoken confirmation loop beyond read-back.
- Object-centric "behind / in front of" (entrance side of a building); now read from the unit's last position and flagged.
- Offline map tiles (PMTiles), Cursor-on-Target export for ATAK.
- The Mistral extraction prompt and Voxtral call are written to the documented API but untested until a key is added.

Map data © OpenStreetMap contributors, ODbL. The public OSM tile server is fine for development only.
