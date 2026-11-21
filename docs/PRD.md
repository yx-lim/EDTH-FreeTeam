# Voice-to-Map: Product Requirements

EDTH Paris 2026, Challenge 01 (set by Lysk). Draft of 20 November 2026; status marks reflect the repository on that date.

## 1. Summary

Field teams report positions by radio. Today someone at the command post listens and moves markers by hand, which is slow,
error-prone and minutes behind. Voice-to-Map listens to short spoken reports and updates a shared map within seconds:
each report becomes a **region that is honest about uncertainty**, attached to the right callsign, with a corrected,
timestamped history anyone can replay.

At least ten teams build from the same brief and suggested stack, so the working pipeline is assumed. This product competes on
the parts the brief's arrows leave out: what a report means given everything said before it, how sure the map is, and how a
mistake gets corrected.

## 2. Context: who judges and what they know

Lysk builds **Lore**, which turns command-post radio traffic into a structured log. Press coverage (SLD Info, June 2026) reports
that it runs Whisper, which Lysk fine-tunes, on a compact offline box. It is described as demonstrated in French, English, German
and Polish, and as tested during the French Army's Orion 2026 exercise. Pain points they cite:
- an aide copying coordinates onto a whiteboard by hand;
- seconds to decide;
- transcripts needed later to justify decisions.

Implications for this product:
- Judges are experts in noisy radio speech. A clean-microphone demo will not impress them; correct handling of radio procedure and
  messy speech will.
- **Offline operation is a real requirement**, not a bonus.
- **The log is the product's backbone.** Every map change must trace to the words that caused it, and corrections must not erase
  history.
- **French matters.** Lysk is a French company with a French Army customer.

## 3. Users

| Persona | Need | Today |
|---|---|---|
| **Command-post watch officer** (primary) | Current picture of every unit; know what is stale or doubtful; trust it under pressure | Whiteboard or manual map updates from radio |
| **Field team member** (secondary) | Report in natural words without a device-specific workflow; hear confirmation | Speaks on the radio; no feedback beyond "copy" |
| **After-action reviewer** | Replay who said what, when, and what the map showed | Searches logs and spreadsheets, sometimes for months |
| **Civil analogue: search-and-rescue coordinator** | Same problem with volunteers | Same |

## 4. Goals and non-goals

**Goals:**
1. Spoken report to map update in under 3 s end to end (under 2 s target), live in front of judges.
2. Natural phrasing in English and French: relations, streets, landmarks, corrections and radio procedure.
3. The marker never claims more precision than the speaker gave; doubt is visible.
4. A replayable, append-only history.
5. Runs fully offline on a laptop.

**Non-goals for the weekend:**
- Tracking adversaries, or anything to do with targeting.
- Automatic decisions.
- Accounts and authorisation.
- Native mobile apps.
- Training custom models.

## 5. What other teams will miss (differentiators)

1. **Regions, not pins.** "South of the church" is a wedge outside the church. "Moved towards the boulevard" is the set of street
   walks from where the unit could have been, capped at walking speed.
2. **Memory per callsign.** "The church" means the church nearest that unit, so the same words give different places for
   different units. "Back where I was ten minutes ago" uses the history.
3. **A speed check.** A unit on foot cannot cross the district in ten seconds, so an impossible jump is flagged as a probably
   misheard name, and a reachable candidate is preferred.
4. **Radio realism.**
   - Recognises "Zero, this is Alpha two".
   - Handles several units in one transmission, and reports about another unit.
   - Handles "correction" and "negative", and doesn't move a unit for "I'll be at …".
   - Treats "holding position" as a fresh report at the same place.
   - Ignores "roger, out".
5. **Corrections keep history.** The withdrawn fix stays in the log, struck through. The correction is resolved in its context.
6. **Staleness.** A silent unit's ring grows at walking pace on the map ("±240 m · 3 min ago").
7. **Operator vocabulary.**
   - Right-click to name a point ("checkpoint 3"); it becomes speakable immediately.
   - Aliases cover what people actually say ("town hall", "Medici fountain").
   - The same names prime speech-to-text.
8. **Evidence.** A stress set of judge-style sentences with ground truth, scored against a naive "geocode the noun" baseline, plus a
   human baseline (Section 7).

## 6. Requirements

Status: ✅ done in repo · 🟡 partial or untested · ⬜ to do.

### Must

| ID | Requirement | Status |
|---|---|---|
| M1 | Push-to-talk capture (button, Space bar, touch) and typed input | ✅ |
| M2 | Speech-to-text with place-name vocabulary; browser fallback | 🟡 Voxtral and faster-whisper paths written, not yet run with a key or model |
| M3 | Extraction of speaker, subjects, relation, anchors, distance, type (position, movement, correction, holding, intent, other) | ✅ rules; 🟡 Mistral prompt untested |
| M4 | Gazetteer for the demo district: aliases, fuzzy and phonetic slips, operator-named points | ✅ |
| M5 | Region per relation: at, near, cardinal ± distance, intersection, between, behind/in front, towards/along via streets | ✅ |
| M6 | Per-callsign state: nearest-candidate disambiguation, speed check, history lookup | ✅ |
| M7 | Shared live map over WebSocket; regions, paths, labels, ambiguity styling | ✅ |
| M8 | Append-only event log, replayed on restart; history scrubber | ✅ |
| M9 | Never plot an unknown or out-of-area place; say why | ✅ |
| M10 | Measured end-to-end latency shown per event | ✅ text→region; 🟡 speech-to-text timing untested |

### Should

| ID | Requirement | Status |
|---|---|---|
| S1 | Spoken read-back in the speaker's language | ✅ browser speech synthesis |
| S2 | Streaming transcription with live partial text | ⬜ Voxtral realtime WebSocket |
| S3 | Offline profile: local Whisper, local Ministral, offline tiles | 🟡 local Whisper path written; ⬜ local LLM switch, PMTiles |
| S4 | Tap to choose among ambiguous candidates; spoken confirmation ("Alpha two, confirm Saint-Sulpice?") | ⬜ |
| S5 | Export: GeoJSON ✅; Cursor-on-Target to ATAK ⬜ | 🟡 |
| S6 | Held-out evaluation with numbers on the pitch slide | ⬜ needs fresh sentences |

### Could

| ID | Requirement |
|---|---|
| C1 | **Radio-net mode:** listen to a continuous channel, split it into transmissions with voice-activity detection and procedure words, with no button press. ✅ built: VAD (browser and server), attribution from procedure and conversation order, acks, say-again repeats, orders with arrival check. 🟡 transcription of radio audio untested without a key or model |
| C2 | NATO unit symbols (APP-6 / MIL-STD-2525) on the map |
| C3 | MGRS grid references ("grid 31U DQ 52 11") and bearings ("200 m bearing 090 from the church") |
| C4 | Auto-generated situation report: one paragraph per unit from the last 15 minutes |
| C5 | Phones as radios: judges scan a QR code, get a callsign, and report into the shared map |
| C6 | Building-entrance-aware "in front of" from OSM `entrance=main` |

## 7. Success metrics and how we show them

| Metric | Target | How measured |
|---|---|---|
| End of speech → map update | median < 2 s, p90 < 3 s | Per-stage timings logged per event (speech, extraction, total) |
| Held-out accuracy | truth inside region ≥ 80 %, correct plot/no-plot decision ≥ 95 % | 30+ fresh sentences written by people who did not build the system, ideally Lysk, scored by `scripts/stress.py` |
| Versus naive pipeline | clear gap on every category | Same sentences through "geocode the noun, drop a pin" |
| **Versus a human** | faster and fewer errors | Volunteer plots a two-minute recorded radio log by hand; compare time and errors |
| Robustness | no crash or silent drop on API failure | Kill the network mid-demo: rules plus local Whisper take over |

Current evidence: on the 48-sentence stress set, the original scaffold passes 22 and this version passes 48. That set was used for
tuning, so it is a regression suite, not an accuracy claim.

## 8. Demo script (3 minutes)

1. **Problem (20 s).** Play 15 s of noisy radio. Show a whiteboard photo.
2. **Live (90 s).** A teammate reports from the back of the room. Then:
   - Hand the microphone to a judge.
   - Show "correction, east of the church, not south" leaving the old fix struck through.
   - Show a silent unit's ring growing.
   - Say "I'll be at Odéon in five minutes" and show nothing moves.
   - Say a French report.
   - Switch to **Radio net** and play the recorded net: the map fills in with nobody pressing a button. Acks tick reports,
     a "say again" repeat replaces the garbled fix, Charlie one's tasking closes when he reports arriving, and the one
     transmission nobody identified stays off the map.
3. **Trust (30 s).** Show the speed-check flag on a deliberately misheard place. Scrub the history. Export.
4. **Evidence (25 s).** One slide: ours versus naive versus human, with the held-out numbers and one honest failure case.
5. **Offline (15 s).** Turn Wi-Fi off and report again.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Venue noise breaks transcription | Push-to-talk, headset microphone, vocabulary priming, typed fallback |
| Venue Wi-Fi | Local gazetteer and routing already; local Whisper; pre-cached tiles |
| LLM returns odd JSON or invents places | Schema validation; rules fallback; anchors must match the gazetteer or the report is flagged |
| "Behind" depends on viewpoint | Flagged as ambiguous on the map; agree a convention with Lysk |
| Over-fitting to our own test sentences | Held-out set from outsiders before quoting numbers |
| Demo district unfamiliar to judges | Rebuild the gazetteer for the venue's neighbourhood (`scripts/fetch_district.py`) |

## 10. Open questions for Lysk (Friday)

- How will they test it: their own sentences, recorded radio, several speakers, noise?
- Do teams report against street names, or against pre-agreed reference points and codenames?
- Is French expected in the demo?
- Which convention for "behind" and "in front of"?
- Does Lore expose a log format or API we could read from or write to?
- Which map area do they prefer: the venue, or a sample area?
