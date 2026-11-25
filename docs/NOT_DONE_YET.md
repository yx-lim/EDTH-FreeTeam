# Not done yet

Moved from the README on 25 Nov 2026. Some items may already be done in this version.

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
