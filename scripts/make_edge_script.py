"""The 100-report English edge-case script (Paris zone): docs/edge_case_script_en.md to read aloud, and
docs/edge_case_script_en.jsonl ({"t", "text"} per line) to replay or score.

    python -m scripts.make_edge_script          # write both files
    python -m scripts.make_edge_script --play   # also play it through the radio-net layer offline and show results
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"

# (section, spoken text, what should happen)
SCRIPT = [
    ("A. Radio procedure", "All stations, this is Zero, radio check, over.", "radio check, nothing plotted"),
    ("A. Radio procedure", "Zero, this is Alpha one, loud and clear, over.", "radio check reply, nothing plotted"),
    ("A. Radio procedure", "Zero, this is Bravo two, read you five by five, over.", "radio check reply, nothing plotted"),
    ("A. Radio procedure", "Alpha one, this is Zero, send your position, over.", "request to Alpha 1, nothing plotted"),
    ("A. Radio procedure", "Zero, this is Alpha one, at the Saint-Sulpice church, over.", "Alpha 1 at Église Saint-Sulpice"),
    ("A. Radio procedure", "Alpha one, this is Zero, roger, out.", "acknowledgement, ticks Alpha 1's report"),
    ("A. Radio procedure", "Hello hello, testing.", "chatter, ignored"),
    ("A. Radio procedure", "Roger, out.", "acknowledgement, nothing plotted"),

    ("B. Places", "Zero, this is Bravo one, at Odeon station, over.", "Bravo 1 at Odéon station"),
    ("B. Places", "Zero, this is Charlie one, in the Luxembourg gardens, near the Medici fountain, over.", "Charlie 1 by Fontaine Médicis (two clues)"),
    ("B. Places", "Zero, this is Delta one, outside the town hall, over.", "Delta 1 near the Mairie du 6e (alias)"),
    ("B. Places", "Zero, this is Echo one, at the Café de Flore, over.", "Echo 1 at Café de Flore (exact name of a café)"),
    ("B. Places", "Zero, this is Foxtrot three, at the Pantheon, over.", "Foxtrot 3 at the Panthéon"),
    ("B. Places", "Zero, this is Golf four, on Rue de Rennes, over.", "Golf 4 on Rue de Rennes (long street: wide area)"),
    ("B. Places", "Zero, this is Hotel one, at the corner of Rue de Seine and Rue Jacob, over.", "Hotel 1 at the crossing"),
    ("B. Places", "Zero, this is Kilo two, between Mabillon and the Saint-Germain market, over.", "Kilo 2 on the line between them"),
    ("B. Places", "Zero, this is Sierra two, at Place de l'Odéon, over.", "Sierra 2 at Place de l'Odéon"),
    ("B. Places", "Zero, this is Echo two, at the church, over.", "Echo 2 at Saint-Sulpice (bare 'church': the one in the area)"),

    ("C. Directions and distances", "Zero, this is Alpha two, two hundred metres north of the Saint-Sulpice church, over.", "wedge 200 m north"),
    ("C. Directions and distances", "Zero, this is Bravo two, about three hundred metres east of the Pantheon, over.", "wider wedge: 'about'"),
    ("C. Directions and distances", "Zero, this is Charlie two, between two hundred and three hundred metres south of the Luxembourg palace, over.", "200-300 m band south"),
    ("C. Directions and distances", "Zero, this is Delta three, one hundred yards west of the Odeon theatre, over.", "91 m west"),
    ("C. Directions and distances", "Zero, this is Echo one, three hundred feet south of the Café de Flore, over.", "91 m south"),
    ("C. Directions and distances", "Zero, this is Golf four, two blocks west of Mabillon, over.", "about 200 m west"),
    ("C. Directions and distances", "Zero, this is Hotel one, five minutes' walk from Odeon station, over.", "a ring about 400 m out (no direction)"),
    ("C. Directions and distances", "Zero, this is Kilo two, four hundred metres from the Pantheon, over.", "a 400 m ring (no direction)"),
    ("C. Directions and distances", "Zero, this is Sierra two, bearing zero four five, three hundred metres from the Saint-Sulpice church, over.", "narrow wedge at 045, 300 m"),
    ("C. Directions and distances", "Zero, this is Alpha two, on azimuth sixteen hundred mils, two hundred metres from the Pantheon, over.", "bearing 090 (mils), 200 m"),
    ("C. Directions and distances", "Zero, this is Bravo two, north-northeast of the Medici fountain, two hundred metres, over.", "bearing 022.5"),
    ("C. Directions and distances", "Zero, this is Charlie two, opposite the Café de Flore, over.", "band outside it, side not said: flagged"),
    ("C. Directions and distances", "Zero, this is Delta three, inside the Luxembourg gardens, over.", "the garden's footprint"),
    ("C. Directions and distances", "Zero, this is Echo two, in the area of Odeon, over.", "wide circle, flagged"),
    ("C. Directions and distances", "Zero, this is Foxtrot three, just past the Pantheon, over.", "flagged: Foxtrot 3 was at the Panthéon, so there is no viewpoint"),
    ("C. Directions and distances", "Zero, this is Golf four, just short of the Saint-Germain market, over.", "near side, read from its last position"),
    ("C. Directions and distances", "Zero, this is Hotel one, to the left of the Odeon theatre, over.", "left, as seen from its last position"),
    ("C. Directions and distances", "Zero, this is Kilo two, fifty metres north of Bravo one, over.", "another unit as the anchor"),
    ("C. Directions and distances", "Zero, this is Sierra two, I'm with Alpha one, over.", "Sierra 2 at Alpha 1's position"),

    ("D. Callsigns", "Zero, this is Alfa won, at the Medici fountain, over.", "Alpha 1 (misheard callsign fixed)"),
    ("D. Callsigns", "Zero this is Charly too, at the Odeon theatre, over.", "Charlie 2"),
    ("D. Callsigns", "Zero, this is fox trot three, at the Pantheon, over.", "Foxtrot 3"),
    ("D. Callsigns", "Zero, this is Ecko ate, at Mabillon, over.", "Echo 8 (a new unit)"),
    ("D. Callsigns", "Zero, this is Delter three, at the Saint-Sulpice fountain, over.", "Delta 3 at Fontaine des Quatre Évêques"),
    ("D. Callsigns", "Zero, uh, at the Saint-Germain market, over.", "no callsign: held, 'say again your callsign'"),
    ("D. Callsigns", "This is Delta three, over.", "push-to-talk: claims the held report; radio-net mode: a call only"),
    ("D. Callsigns", "Bravo one and Bravo two, at the corner of Rue de Rennes and Rue du Four, over.", "two units in one call"),
    ("D. Callsigns", "Zero, this is Charlie one, Delta one reports he's at the Sorbonne, over.", "relay: Delta 1 at the Sorbonne"),
    ("D. Callsigns", "Zero, this is Alpha two, Bravo one says he is near Odeon, I'm still north of the church, over.", "relay moves Bravo 1; Alpha 2 placed by the church nearest it"),

    ("E. Corrections and history", "Zero, this is Echo one, south of the Saint-Sulpice church, over.", "Echo 1 south of the church"),
    ("E. Corrections and history", "Zero, this is Echo one, correction, east of the church, not south, over.", "replaces the last fix (old one struck through)"),
    ("E. Corrections and history", "Zero, this is Golf four, negative, not at Rue de Rennes, I am at Saint-Placide station, over.", "Golf 4 at Saint-Placide"),
    ("E. Corrections and history", "Zero, this is Hotel one, holding position, over.", "same place as before"),
    ("E. Corrections and history", "Zero, this is Kilo two, no change, over.", "same place as before"),
    ("E. Corrections and history", "Zero, this is Sierra two, I'll be at the Pantheon in ten minutes, over.", "intent: not a move"),
    ("E. Corrections and history", "Zero, this is Alpha one, moving towards Boulevard Saint-Germain, over.", "walking corridor towards it"),
    ("E. Corrections and history", "Zero, this is Bravo two, back where I was ten minutes ago, over.", "position from history"),
    ("E. Corrections and history", "Zero, this is Charlie one, now at the church, over.", "the church nearest Charlie 1"),
    ("E. Corrections and history", "Zero, this is Delta one, at the Pantheon, over.", "Delta 1 at the Panthéon"),

    ("F. Misheard and unknown places", "Zero, this is Echo two, at Odin station, over.", "Odéon by sound, flagged 'confirm'"),
    ("F. Misheard and unknown places", "Zero, this is Foxtrot three, on Rude Rennes, over.", "Rue de Rennes (fuzzy)"),
    ("F. Misheard and unknown places", "Zero, this is Golf four, near San Sulpice, over.", "Saint-Sulpice"),
    ("F. Misheard and unknown places", "Zero, this is Hotel one, at the Saint Germain de Pray church, over.", "Saint-Germain-des-Prés church, flagged"),
    ("F. Misheard and unknown places", "Zero, this is Kilo two, at Mabion station, over.", "Mabillon"),
    ("F. Misheard and unknown places", "Zero, this is Sierra two, at the Luxemburg garden, over.", "Jardin du Luxembourg"),
    ("F. Misheard and unknown places", "Zero, this is Alpha two, at the Pantion, over.", "Panthéon"),
    ("F. Misheard and unknown places", "Zero, this is Bravo two, at the banana tower, over.", "unknown place: not plotted"),
    ("F. Misheard and unknown places", "Zero, this is Charlie two, at the Eiffel Tower, over.", "outside the mapped area: not plotted"),

    ("G. Grid references", "Zero, this is Delta three, grid five one two one one zero, over.", "100 m square 31U DQ 512 110"),
    ("G. Grid references", "Zero, this is Echo one, grid three one uniform delta quebec five one two one one zero, over.", "full grid, same square"),
    ("G. Grid references", "Zero, this is Foxtrot three, grid nine nine nine nine nine nine, over.", "outside the area: not plotted"),
    ("G. Grid references", "Zero, this is Golf four, grid five one two one one, over.", "not a valid grid: say again the grid"),
    ("G. Grid references", "Zero, this is Hotel one, grid nine nine nine nine nine nine, by the Saint-Sulpice church, over.", "bad grid, uses the church instead"),

    ("H. Sightings", "Zero, this is Alpha one, contact, two enemy tanks moving north, three hundred metres east of the church, over.", "2 enemy tanks, red, heading north"),
    ("H. Sightings", "Zero, this is Bravo one, contact, enemy infantry, about ten, at the Saint-Germain market, over.", "enemy infantry, count 10"),
    ("H. Sightings", "Zero, this is Charlie one, contact, unknown vehicle, static, near the Odeon theatre, over.", "side unknown (yellow), never assumed enemy"),
    ("H. Sightings", "Zero, this is Delta one, civilians gathering at Place Saint-Sulpice, over.", "civilians (green)"),
    ("H. Sightings", "Zero, this is Echo one, contact, drone overhead, over.", "drone at Echo 1's own position"),
    ("H. Sightings", "Zero, this is Foxtrot three, enemy drone over the Pantheon, heading west, over.", "enemy drone, arrow west"),
    ("H. Sightings", "Zero, this is Golf four, another drone over the Pantheon, over.", "a second drone, not merged"),
    ("H. Sightings", "Zero, this is Hotel one, I see the same tanks, three hundred metres east of the church, over.", "merged with the tanks: seen by two"),
    ("H. Sightings", "Zero, this is Kilo two, IED on Rue de Tournon, do not approach, over.", "IED: stays on the map"),
    ("H. Sightings", "Zero, this is Sierra two, sniper, two hundred metres north of me, over.", "sniper measured from Sierra 2"),
    ("H. Sightings", "Zero, this is Alpha two, contact, enemy APC at my two o'clock, about one hundred metres, over.", "a ring 100 m around Alpha 2 (which way 'two o'clock' points is not known)"),
    ("H. Sightings", "Zero, this is Bravo two, friendly drone overhead, ours, over.", "own drone at Bravo 2, friendly (blue), no warning"),
    ("H. Sightings", "Zero, this is Charlie two, contact, enemy artillery firing, south of the Montparnasse tower, over.", "enemy artillery"),
    ("H. Sightings", "Zero, this is Delta three, mine at the corner of Rue Guynemer and Rue de Vaugirard, over.", "mine: warning without 'enemy'"),
    ("H. Sightings", "Zero, this is Echo two, helicopter, unknown, over the Luxembourg palace, over.", "helicopter, side unknown"),
    ("H. Sightings", "Zero, this is Foxtrot three, contact, enemy tank at the Luxembourg palace, over.", "a second contact: the first tanks were heading north, this is south of them"),
    ("H. Sightings", "Zero, this is Golf four, the Pont des Arts is destroyed, over.", "place status: destroyed"),
    ("H. Sightings", "Zero, this is Hotel one, Rue de Seine is blocked, over.", "place status: blocked"),
    ("H. Sightings", "Zero, this is Kilo two, Rue de Seine is open again, over.", "place status: reopened"),

    ("I. Orders", "Charlie one, this is Zero, move to the Medici fountain, over.", "order: destination drawn dashed"),
    ("I. Orders", "Zero, this is Charlie one, wilco, out.", "acknowledges the order"),
    ("I. Orders", "Zero, this is Charlie one, at the Medici fountain, over.", "arrival closes the order"),
    ("I. Orders", "Delta one, this is Zero, hold your position, over.", "hold order"),

    ("J. French and repeats", "Zéro, ici Alpha deux, au sud de l'église Saint-Sulpice, terminé.", "French: Alpha 2 south of the church"),
    ("J. French and repeats", "Zéro, ici Bravo un, je me dirige vers le boulevard Saint-Germain, terminé.", "French: Bravo 1 moving towards it"),
    ("J. French and repeats", "Zéro, ici Charlie deux, entre Mabillon et Odéon, terminé.", "French: between"),
    ("J. French and repeats", "Zero, this is Echo one, I say again, at the Pantheon, over.", "Echo 1 at the Panthéon"),
    ("J. French and repeats", "Zero, this is Sierra two, say again your last, over.", "say-again request, nothing plotted"),
    ("J. French and repeats", "All stations, this is Zero, end of exercise, out.", "nothing plotted"),
]
# Lines the offline rules get wrong today (21 Nov 2026). Gemini may handle some live; check before demoing them.
GAPS: dict[int, str] = {}   # all fixed in the offline rules (21 Nov 2026)
STEP_S = 60   # one transmission a minute: units can walk between their reports


def write() -> None:
    DOCS.mkdir(exist_ok=True)
    lines, section = ["# English edge-case script (Paris zone)", "",
                      "100 radio reports, one a minute, covering every case the app handles. Read them aloud on the "
                      "Paris zone, or play `docs/edge_case_script_en.jsonl`. Each line says what should happen.", ""], None
    for i, (sec, text, expect) in enumerate(SCRIPT, 1):
        if sec != section:
            lines += ["", f"## {sec}", ""]
            section = sec
        gap = f"  \n   ⚠ offline rules today: {GAPS[i]}" if i in GAPS else ""
        lines.append(f"{i}. “{text}”  \n   → {expect}{gap}")
    lines += ["", "## Checked offline", "",
              (f"{len(GAPS)} of {len(SCRIPT)} lines are marked ⚠: the offline rules get them wrong today. " if GAPS else
               "Every line behaves as written with the offline rules (no cloud model). ") +
              "Checked by playing the script through the radio-net layer: `python -m scripts.make_edge_script --play`."]
    (DOCS / "edge_case_script_en.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (DOCS / "edge_case_script_en.jsonl").write_text(
        "".join(json.dumps({"t": i * STEP_S, "text": t}, ensure_ascii=False) + "\n" for i, (_, t, _) in enumerate(SCRIPT)),
        encoding="utf-8")
    print(f"{len(SCRIPT)} reports -> docs/edge_case_script_en.md and .jsonl")


async def play() -> None:
    os.environ.setdefault("EXTRACTOR", "rules")
    from backend.geo import Gazetteer
    from backend.net import Net
    from backend.tracker import Tracker
    net = Net(Tracker(Gazetteer()))
    for i, (sec, text, expect) in enumerate(SCRIPT, 1):
        out = await net.hear(text, now=1_000_000 + i * STEP_S)
        tx = out["transmissions"][0] if out["transmissions"] else {}
        ev = "; ".join(f"{e['callsign']}:{'OK' if e['ok'] else 'NO'} {e.get('anchor') or ''} {e.get('note') or ''}".strip()
                       for e in out["events"]) or "-"
        print(f"{i:3} {tx.get('kind') or '-':11} {ev[:110]}")


if __name__ == "__main__":
    write()
    if "--play" in sys.argv:
        asyncio.run(play())
