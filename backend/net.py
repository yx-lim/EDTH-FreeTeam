"""Radio-net mode: listen to a whole channel and work out who is talking, to whom, and whether a transmission is
a position report at all. Nobody presses a button or picks a callsign; voice procedure and the order of the
conversation carry that information, the same way an operator at the command post follows a net.

Who is speaking, most trusted first:
  1. Named in the call: "Alpha two, this is Zero", "Alpha deux de Zéro", or the abbreviated "Alpha two, Zero".
  2. One callsign at the start. If that station was just called, it is answering with its own callsign
     ("Bravo two, south of the town hall"). If that station spoke last, someone is answering it ("Bravo two,
     say again"). With no context: a report starts with the speaker's own callsign, a request or an order with the
     station called. Control stations (Zero, Command) never report their own position.
  3. No callsign: the rest of the previous transmission when it stopped less than 3 s ago without "over";
     otherwise the station that was just called, answering.
  4. Otherwise not identified. The transmission is logged and shown to the operator, never plotted under a guess.

What it does besides plotting reports: acknowledgements ("roger", "wilco") tick the report they answer; "say again"
marks a report as queried, and the repeat replaces it; orders ("Charlie one, move to the Medici fountain") draw the
destination and tick it when the unit reports arriving.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path

from shapely.geometry import Point, shape

from . import callsign, lang_uk
from .extract import _CS, _callsign, _parse_clause, _prep, extract
from .resolver import resolve
from .tracker import Tracker

CONTROL = {"zero", "command", "control", "hq", "вежа", "башня", "tower", "база"}
ALL = "all stations"
CONTINUE_S = 3.0     # a pause shorter than this, without "over", is one transmission cut in two by the VAD
REPLY_S = 45.0       # how long a call waits for its answer
ACK_S = 120.0        # an acknowledgement or "say again" refers to a transmission at most this old
REACHED_M = 40.0     # a tasked unit reporting within this distance of its destination has arrived
PROWORDS = ["Zero", "Alpha", "Bravo", "Charlie", "Delta", "Echo", "this is", "over", "out", "roger", "wilco",
            "say again", "send position", "ici", "à vous", "terminé", "reçu",
            "прийом", "приём", "Вежа", "Башня", "плюс", "мінус", "кінець зв'язку"]

_ST = rf"(?:all stations|toutes (?:les )?stations|{_CS})"
# Atomic groups below keep "Bravo one is ..." from backtracking to a bare "Bravo" that would pass this check.
_NOT_HEADER = r"(?!\s+(?:is|est|and|et|reports?|reported|says|said|confirms|signale|indique|rapporte|dit|annonce)\b)"
_RELAY = (rf"\b(?P<cs>{_CS})\s+(?:reports|reported|says|said|confirms|signale|indique|rapporte|dit|annonce)\s+(?:(?:that|que|qu)\s+)?"
          r"(?:(?:he|she|they|it|il|elle|ils)\s+(?:is|are|s|re|est|sont)\s+)?")
_SAY_AGAIN = (r"\b(?:say again|repeat (?:your )?last|repeat that|please repeat|repetez|unreadable|garbled|"
              r"didn t (?:copy|get) that|did not copy|you re breaking up|breaking up)\b")
_CHECK = (r"\b(?:radio check|how (?:do you )?(?:read|copy)(?: me)?|loud and clear|lima charlie|five by five|5 by 5|"
          r"weak but readable|je vous recois|comment me recevez vous|5 sur 5|cinq sur cinq|essai radio|verification radio|"
          r"fort et clair|je vous entends|recu fort)\b")
_REQUEST = (r"\b(?:send (?:me |us )?(?:your )?(?:position|location|loc|pos|grid|status)|"
            r"(?:what s|what is|confirm|state|give|report) (?:me |us )?your (?:position|location|loc|pos)|"
            r"report (?:position|location)|where are you|position check|"
            r"donne[zr]? (?:moi |nous )?(?:votre |ta )?position|quelle est (?:votre|ta) position|ou etes vous|ou es tu)\b"
            r"|^(?:send )?sitrep$")
_ORDER = (r"^(?:(?:please|now|immediately|then|et)\s+)*(?:move to|go to|proceed to|head to|make your way to|get to|"
          r"rv at|meet at|rejoignez|rejoins|allez (?:a|au|aux|vers|jusqu a)|dirigez vous vers|"
          r"deplacez vous (?:vers|a|au|aux|jusqu a)|rendez vous (?:a|au|aux))\s+(?P<a>.+)")
_HOLD = (r"^(?:(?:please|now)\s+)*(?:hold (?:your )?position|hold there|stay where you are|stay put|remain in place|"
         r"restez (?:sur place|en position|sur position|sur votre position|ou vous etes)|tenez (?:la |votre )?position|"
         r"ne bougez (?:pas|plus))\b")
_ACK = (r"(?:roger(?: that)?|copy(?: that)?|copied|wilco|received|understood|acknowledged|ack|affirmative|affirm|noted|"
        r"send|go ahead|ready to copy|recu|bien recu|compris|bien compris|parlez|allez y|thanks|thank you|merci|good|"
        r"j execute|j y vais|affirmatif|entendu|c est note)")
_END = re.compile(r"\b(?:over and out|over|out|à vous|a vous|terminé|termine|прийом|приём|прием|кінець зв.язку|конец связи"
                  r"|відбій|отбой)(?!\w)(?P<p>[.!,;]*)\s+", re.I)


def split(text: str) -> list[str]:
    """One stretch of audio can hold several transmissions when the VAD missed a gap: cut after "over"/"out" when a
    sentence ends there or the next words are a callsign ("... send position, over. Alpha one, at the church")."""
    parts, start = [], 0
    for m in _END.finditer(text):
        if "." in m.group("p") or "!" in m.group("p") or re.match(rf"{_ST}\b", _prep(text[m.end():m.end() + 40])):
            parts.append(text[start:m.end()].strip())
            start = m.end()
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def ended(text: str) -> str | None:
    """How the transmission closed: "over" (an answer is expected), "out" (exchange finished) or None."""
    if lang_uk.has_cyrillic(text) and (how := lang_uk.ended(text)):
        return how
    t = unicodedata.normalize("NFKD", text.lower())
    t = re.sub(r"[^a-z0-9]+", " ", "".join(c for c in t if not unicodedata.combining(c)))
    m = re.search(r"\b(over and out|over|out|a vous|termine)\s*$", t)
    return None if not m else "out" if m[1] in ("over and out", "out", "termine") else "over"


def header(t: str) -> tuple[str | None, str | None, str | None, str, str]:
    """(to, from, single callsign, body, how) from prepped text."""
    m = re.match(rf"(?:hello\s+|allo\s+)?(?P<to>{_ST})[\s,]*(?:this is|ici|de)\s+(?P<frm>{_ST})\b[\s,]*", t)
    if m:
        return _station(m["to"]), _station(m["frm"]), None, t[m.end():], "named in the call"
    m = re.match(rf"(?:this is|ici)\s+(?P<frm>{_ST})\b[\s,]*", t)
    if m:
        return None, _station(m["frm"]), None, t[m.end():], "named in the call"
    m = re.match(rf"(?:hello\s+|allo\s+)?(?P<to>{_ST})[\s,]+(?P<frm>(?>{_ST}))\b{_NOT_HEADER}[\s,]*", t)
    if m:
        return _station(m["to"]), _station(m["frm"]), None, t[m.end():], "abbreviated call"
    m = re.match(rf"(?:hello\s+|allo\s+)?(?P<x>(?>{_ST}))\b{_NOT_HEADER}[\s,]*", t)
    if m:
        return None, None, _station(m["x"]), t[m.end():], ""
    return None, None, None, t, ""


def kind_of(body: str) -> str | None:
    """Procedure kinds by pattern; None means 'ask the extractor whether it is a report'."""
    b = body.strip(" ,.;")
    if not b:
        return "call"
    if re.search(_SAY_AGAIN, b):
        return "say_again"
    if re.search(_CHECK, b):
        return "radio_check"
    if re.search(_REQUEST, b):
        return "request"
    if re.match(_ORDER, b) or re.match(_HOLD, b):
        return "order"
    if re.fullmatch(rf"(?:{_ACK}\b[\s,.;]*)+", b):
        return "ack"
    return None


def _station(s: str) -> str:
    s = _callsign(s)
    return ALL if s.startswith(("all stations", "toutes")) else s


class Net:
    def __init__(self, tracker: Tracker, log: Path | None = None):
        self.tracker, self.gaz, self.log = tracker, tracker.gaz, log
        self.transmissions: list[dict] = []
        self.control = "zero"          # the net's control station, as last heard
        self.repeat_due: dict[str, tuple[int | None, float]] = {}   # station -> (event to replace, when asked)
        if log and log.exists():
            self._replay(log)

    # --- public --------------------------------------------------------------------------------
    async def hear(self, text: str, now: float | None = None, duration: float = 0.0, source: str = "radio",
                   stt: dict | None = None) -> dict:
        """One transcript (one VAD segment, or one typed line) -> {"transmissions", "events", "annotations"}."""
        now = time.time() if now is None else now
        out: dict[str, list] = {"transmissions": [], "events": [], "annotations": []}
        parts = split(text)
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            got = await self._one(part, now + i * 0.01, now + (duration if last else i * 0.01), source,
                                  stt if i == 0 else None)
            for k in out:
                out[k] += got[k]
        return out

    def reset(self) -> None:
        self.transmissions.clear()
        self.repeat_due.clear()
        self._write({"kind": "reset", "t": time.time()})

    def vocabulary(self) -> list[str]:
        """Words to prime speech-to-text with on this net: procedure, callsigns heard so far, then places."""
        heard = sorted({s for tx in self.transmissions for s in (tx["from"], tx["to"]) if s and s != ALL})
        words = list(dict.fromkeys(PROWORDS + [h.title() for h in heard]))
        return words + self.gaz.vocabulary(limit=max(0, 100 - len(words)))

    # --- one transmission ----------------------------------------------------------------------
    async def _one(self, text: str, t: float, end: float, source: str, stt: dict | None) -> dict:
        text = callsign.snap(text)   # "this is Alfa won" -> "this is Alpha 1" (backend/callsign.py)
        prepped = _prep(text)
        cyrillic = lang_uk.cyrillic_share(text) > 0.3
        to, frm, single, body, how = lang_uk.header(text) if cyrillic else header(prepped)
        kind, parsed = (lang_uk.kind_of(body) if cyrillic else kind_of(body)), None
        if kind is None:
            relayed = re.search(_RELAY, prepped)
            parsed = await extract(re.sub(_RELAY, r"\g<cs> is ", prepped) if relayed else text)
            kind = "report" if any(r["type"] != "other" for r in parsed["reports"]) else "other"
        speaker, to, how = self._attribute(to, frm, single, how, kind, t)
        for s in (speaker, to):
            if s in CONTROL:
                self.control = s

        tx = {"id": len(self.transmissions) + 1, "t": t, "end": end, "text": text, "from": speaker, "to": to,
              "kind": kind, "how": how, "ended": ended(text), "events": [], "note": "", "source": source, "stt": stt}
        out: dict[str, list] = {"transmissions": [tx], "events": [], "annotations": []}

        if kind == "report":
            await self._report(tx, parsed, out)
        elif kind == "ack":
            self._ack(tx, out)
        elif kind == "say_again":
            self._say_again(tx, out)
        elif kind == "order":
            self._order(tx, body, out)
        self.transmissions.append(tx)
        self._write({"kind": "tx", **tx})
        return out

    def _attribute(self, to, frm, single, how, kind, t) -> tuple[str | None, str | None, str]:
        prev = self.transmissions[-1] if self.transmissions else None
        gap = t - prev["end"] if prev else None
        awaited = None   # the station expected to speak next: the one just called, unless the exchange closed
        if prev and gap <= REPLY_S and prev["ended"] != "out" and prev["to"] not in (None, ALL):
            awaited = prev["to"]
        if frm:
            return frm, to, how
        if single:
            x = single
            if awaited == x and x != ALL:
                return x, prev["from"], f"answering {prev['from'] or 'the call'} with its own callsign"
            if prev and prev["from"] == x and gap <= ACK_S:
                other = prev["to"] if prev["to"] not in (None, ALL) else (self.control if x not in CONTROL else None)
                return other, x, f"answering {x}"
            if x in CONTROL or x == ALL or kind in ("request", "order", "call", "radio_check", "say_again"):
                speaker = self.control if x not in CONTROL and kind != "report" else None
                return speaker, x, f"calling {x}" + (" (control assumed)" if speaker else "; speaker not identified")
            return x, None, "own callsign"
        if prev and gap <= CONTINUE_S and prev["ended"] is None and prev["from"]:
            return prev["from"], prev["to"], f"continues {prev['from']}'s transmission"
        if awaited:
            return awaited, prev["from"], f"reply to {prev['from'] or 'the call'}"
        if prev and gap <= ACK_S and kind in ("ack", "say_again") and prev["from"] and prev["from"] not in CONTROL:
            return self.control, prev["from"], "answering the last report (control assumed)"
        return None, to, "speaker not identified"

    # --- effects -------------------------------------------------------------------------------
    async def _report(self, tx: dict, parsed: dict, out: dict) -> None:
        speaker = tx["from"]
        reports = parsed["reports"]
        if speaker in CONTROL or speaker is None:
            # Control does not report its own position; an unknown speaker's own position cannot be plotted.
            # Reports that name their subject ("Bravo one is at the theatre") still count.
            # Sightings count whoever passes them on: control relaying "ждун біля Сараю" to all stations is logged and
            # joins the track (as a relay, not a second witness).
            reports = [r for r in reports if r["type"] == "contact" or (r.get("subject") and r["subject"] not in CONTROL)]
            if not reports:
                heard = next((r for r in parsed["reports"] if r.get("anchor")), None)
                where = f" (heard: {heard['relation'].replace('_', ' ')} {heard['anchor']['name']})" if heard else ""
                tx["note"] = ("control's own position is not tracked" if speaker else
                              "speaker not identified, so not plotted" + where + "; ask for the callsign")
                return
        replaces = None
        if speaker in self.repeat_due and tx["t"] - self.repeat_due[speaker][1] <= ACK_S:
            replaces = self.repeat_due.pop(speaker)[0]
            tx["note"] = "repeat after 'say again'"
        events = await self.tracker.ingest(tx["text"], now=tx["t"], source=tx["source"], stt=tx["stt"],
                                           speaker=speaker or "unidentified", parsed={**parsed, "reports": reports},
                                           replaces=replaces, extra={"tx": tx["id"], "to": tx["to"]})
        tx["events"] = [e["id"] for e in events]
        out["events"] += events
        for e in events:
            self._arrived(e, out)

    def _acknowledged(self, tx: dict) -> dict | None:
        """The transmission an ack or a 'say again' answers: the last one from the station it addresses."""
        for old in reversed(self.transmissions):
            if tx["t"] - old["end"] > ACK_S:
                return None
            if old["from"] == tx["to"] and old["kind"] not in ("ack", "say_again"):
                return old
        return None

    def _ack(self, tx: dict, out: dict) -> None:
        old = self._acknowledged(tx)
        if old:
            for eid in old["events"]:
                self._annotate(eid, out, acked_by=tx["from"] or "?")
            tx["note"] = f"acknowledges transmission {old['id']}"

    def _say_again(self, tx: dict, out: dict) -> None:
        old = self._acknowledged(tx)
        if not old:
            return
        tx["note"] = f"asks {old['from']} to repeat transmission {old['id']}"
        standing = None
        for eid in old["events"]:
            e = self._annotate(eid, out, queried_by=tx["from"] or "?")
            if e and e["ok"] and not e["superseded"] and e["callsign"] == old["from"]:
                standing = eid
        self.repeat_due[old["from"]] = (standing, tx["t"])

    def _order(self, tx: dict, body: str, out: dict) -> None:
        unit = tx["to"]
        if not unit or unit == ALL:
            tx["note"] = "order to all stations" if unit else "order with no addressee"
            return
        if lang_uk.cyrillic_share(body) > 0.3:
            got = lang_uk.order(body)
            dest = got[1] if got else None
            m = dest is not None
        else:
            m = re.match(_ORDER, body.strip(" ,.;"))
            dest = m["a"] if m else None
        fields: dict = {"order": "hold position" if not m else "move"}
        note = "ordered to hold position"
        if m:
            if lang_uk.has_cyrillic(dest):
                clause = lang_uk.parse_location(dest if re.search(r"\bвид\b|\bот\b", lang_uk.fold(dest)) else f"на {dest}")
            else:
                clause = _parse_clause(dest if re.match(r"(?:the |la |le )?(?:corner|intersection|carrefour|coin|angle)\b", dest)
                                       or re.match(r"\d|north|south|east|west", dest) else f"at {dest}")
            last = self.tracker.units().get(unit)
            r = resolve(clause, self.gaz, last=last) if clause else {"ok": False, "note": f"unknown place: {dest!r}"}
            if r["ok"]:
                fields["target"] = {k: r[k] for k in ("region", "centre", "radius_m", "anchor")}
                note = f"tasked: move to {r['anchor']}"
            else:
                note = f"tasked to an unresolved place ({r['note']})"
        event = self.tracker.note(unit, tx["from"], tx["text"], tx["t"], "order", tx=tx["id"], to=unit,
                                  source=tx["source"], note=note, **fields)
        tx["events"] = [event["id"]]
        out["events"].append(event)

    def _arrived(self, e: dict, out: dict) -> None:
        """A position report from a tasked unit inside (or right next to) its destination closes the task."""
        if not e["ok"] or e["type"] not in ("position", "correction", "holding"):
            return
        order = next((o for o in reversed(self.tracker.events) if o["callsign"] == e["callsign"] and o["type"] == "order"
                      and o["t"] <= e["t"]), None)
        if not order or not order.get("target") or order.get("reached"):
            return
        target = self.gaz.proj.to_xy(shape(order["target"]["region"]))
        if target.distance(self.gaz.proj.to_xy(Point(e["centre"]))) <= REACHED_M:
            self._annotate(order["id"], out, reached={"event": e["id"], "t": e["t"]})

    def _annotate(self, event_id: int, out: dict, **fields) -> dict | None:
        e = self.tracker.annotate(event_id, **fields)
        if e:
            out["annotations"].append({"id": event_id, "fields": fields})
        return e

    # --- log -----------------------------------------------------------------------------------
    def _write(self, line: dict) -> None:
        if not self.log:
            return
        self.log.parent.mkdir(exist_ok=True)
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def _replay(self, log: Path) -> None:
        for raw in log.read_text(encoding="utf-8").splitlines():
            try:
                line = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if line.pop("kind", None) == "reset":
                self.transmissions.clear()
            elif "id" in line:
                line["id"] = len(self.transmissions) + 1
                self.transmissions.append(line)
        for tx in self.transmissions:
            for s in (tx.get("from"), tx.get("to")):
                if s in CONTROL:
                    self.control = s
