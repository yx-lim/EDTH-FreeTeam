"""Per-unit state and the event log. One transmission in -> one event per unit it mentions.

Kept separate from the web app so tests and evaluation scripts can replay scenarios with simulated clocks:
    tracker = Tracker(Gazetteer());  events = await tracker.ingest("Alpha one, at the church", now=0)
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from .extract import extract
from .geo import Gazetteer, norm
from .resolver import resolve


HOLD_S = 120   # how long a report with no callsign waits for the station to say who it is


class Tracker:
    def __init__(self, gaz: Gazetteer, log: Path | None = None):
        self.gaz, self.log = gaz, log
        self.events: list[dict] = []
        self.pending: dict | None = None   # the last report heard with no callsign, held until someone claims it
        # callsign -> fixes still standing, oldest first: (event id, region in metres, time)
        self.history: dict[str, list[tuple[int, BaseGeometry, float]]] = {}
        if log and log.exists():
            self._replay(log)

    # --- public --------------------------------------------------------------------------------
    async def ingest(self, text: str, default_callsign: str | None = None, now: float | None = None,
                     source: str = "text", stt: dict | None = None, *, speaker: str | None = None,
                     parsed: dict | None = None, replaces: int | None = None, extra: dict | None = None) -> list[dict]:
        """speaker / parsed: set by the radio-net layer, which has already worked out who is talking and parsed
        the text. replaces: an event the speaker was asked to repeat ("say again"); the repeat supersedes it."""
        now = time.time() if now is None else now
        t0 = time.perf_counter()
        parsed = parsed or await extract(text)
        named = bool(speaker or parsed["speaker"])
        if not named and all(r["type"] == "other" for r in parsed["reports"]):
            return []   # chatter ("hello hello"): no callsign, no place, no procedure. Nothing to log or plot.
        if not named and not default_callsign:
            return [self._hold(text, parsed, now, source, stt)]
        held = self.pending if self.pending and now - self.pending["t"] <= HOLD_S else None
        if held and speaker is None and parsed["speaker"] and all(r["type"] == "other" for r in parsed["reports"]):
            return await self._claim(held, parsed["speaker"], now, source, stt)   # push-to-talk only; the net has its own
        speaker = speaker or parsed["speaker"] or (norm(default_callsign) if default_callsign else None) or "unit 1"
        by_subject: dict[str, list[dict]] = {}
        for r in parsed["reports"]:
            by_subject.setdefault(r.get("subject") or speaker, []).append(r)
        out = []
        for subject, reports in by_subject.items():
            event = self._apply(subject, speaker, reports, text, now, replaces if subject == speaker else None)
            event.update(source=source, extractor=parsed.get("extractor"), transcript_meta=stt, **(extra or {}),
                         callsign_assumed=not named and subject == speaker,
                         latency_ms={"stt": (stt or {}).get("stt_ms"), "extract": parsed.get("extract_ms"),
                                     "total": round((time.perf_counter() - t0) * 1000) + ((stt or {}).get("stt_ms") or 0)})
            self._write({"kind": "event", **event})
            out.append(event)
        return out

    def _hold(self, text: str, parsed: dict, now: float, source: str, stt: dict | None) -> dict:
        """A report with no callsign and no default to fall back on: plotting it on a guessed unit would put a team
        in the wrong place, so it is logged, not plotted, and the station is asked to say who it is (as an operator
        would: "Station calling, say again your callsign")."""
        event = self.note("unidentified", None, text, now, "unidentified", source=source, transcript_meta=stt,
                          extractor=parsed.get("extractor"), note="callsign not heard: say again your callsign",
                          _reports=parsed["reports"])
        self.pending = event
        return event

    async def _claim(self, held: dict, speaker: str, now: float, source: str, stt: dict | None) -> list[dict]:
        """The reply to "say again your callsign" ("This is Delta three"): the held report becomes theirs."""
        self.pending = None
        out = await self.ingest(held["text"], now=now, source=source, stt=stt, speaker=speaker,
                                parsed={"speaker": speaker, "reports": held["_reports"], "extractor": held.get("extractor")},
                                extra={"identifies": held["id"]})
        self.annotate(held["id"], identified_as=speaker)
        return out

    def note(self, callsign: str, speaker: str | None, text: str, now: float, type: str, **fields) -> dict:
        """An event that is not a position (an order, a tasking); kept in the same log and history."""
        event = {"id": len(self.events) + 1, "t": now, "callsign": callsign, "speaker": speaker, "text": text,
                 "parsed": None, "type": type, "ok": False, "superseded": False, **fields}
        self.events.append(event)
        self._write({"kind": "event", **{k: v for k, v in event.items() if not k.startswith("_")}})
        return event

    def annotate(self, event_id: int, **fields) -> dict | None:
        """Add facts learned later (acknowledged by Zero, asked to repeat, task reached) to a logged event."""
        event = self.get(event_id)
        if event is None:
            return None
        event.update(fields)
        self._write({"kind": "annotate", "id": event_id, **fields})
        return event

    def get(self, event_id: int) -> dict | None:
        return self.events[event_id - 1] if 0 < event_id <= len(self.events) else None

    def reset(self) -> None:
        self.events.clear()
        self.history.clear()
        self.pending = None
        self._write({"kind": "reset", "t": time.time()})

    def units(self) -> dict[str, BaseGeometry]:
        return {cs: h[-1][1] for cs, h in self.history.items() if h}

    def public(self, event: dict) -> dict:
        return {k: v for k, v in event.items() if not k.startswith("_")}

    # --- internals -----------------------------------------------------------------------------
    def _apply(self, subject: str, speaker: str, reports: list[dict], text: str, now: float,
               replaces: int | None = None) -> dict:
        event = {"id": len(self.events) + 1, "t": now, "callsign": subject, "speaker": speaker, "text": text,
                 "parsed": reports[0], "type": reports[0]["type"], "ok": False, "superseded": False}
        if all(r["type"] == "other" for r in reports):
            return self._store(event, {"ok": False, "note": "not a location report"})

        correction = any(r["type"] == "correction" for r in reports)
        wrong = self._supersede(subject) if correction else self._supersede(subject, only=replaces) if replaces else None
        if wrong:
            event["corrects"] = wrong[0]
        # A correction still names places relative to what was just said ("east of the church, not south"),
        # so the withdrawn fix stays the context for resolving names; it just no longer counts as a position.
        fix = wrong or (self.history.get(subject) or [None])[-1]
        last_geom = fix[1] if fix else None
        elapsed = max(0.0, now - fix[2]) if fix else None   # replays can deliver times out of order
        others = {cs: g for cs, g in self.units().items() if cs != subject}

        results = []
        for r in reports:
            if r["type"] == "other":
                continue
            if r["type"] == "intent":
                where = (r.get("anchor") or {}).get("name", "somewhere")
                results.append({"ok": False, "note": f"stated intention ({r['relation'].replace('_', ' ')} {where}); position unchanged"})
            elif r["type"] == "holding":
                results.append(self._reuse(last_geom, "previous position", "holding position") if last_geom is not None
                               else {"ok": False, "note": "holding, but no earlier position is known"})
            elif r["relation"] == "previous":
                results.append(self._previous(subject, now, r.get("minutes_ago")))
            else:
                results.append(resolve(r, self.gaz, last=last_geom, elapsed_s=elapsed, units=others))

        oks = [x for x in results if x["ok"]]
        if not oks:
            return self._store(event, results[0] if results else {"ok": False, "note": "nothing to plot"})
        best = min(oks, key=lambda x: x["radius_m"])   # the most specific clue wins...
        if len(oks) > 1:                                 # ...unless the clues overlap: then use what they agree on
            common = oks[0]["_geom"]
            for x in oks[1:]:
                common = common.intersection(x["_geom"])
            if common.area > 1:
                best = {**best, **self._region(common), "anchor": " + ".join(x["anchor"] for x in oks),
                        "note": f"combined {len(oks)} clues"}
        event["parsed"] = reports[results.index(best)] if best in results else reports[0]
        return self._store(event, best)

    def _store(self, event: dict, result: dict) -> dict:
        geom = result.get("_geom")
        event.update({k: v for k, v in result.items() if k != "_geom"})
        self.events.append(event)
        if event["ok"] and geom is not None:
            self.history.setdefault(event["callsign"], []).append((event["id"], geom, event["t"]))
        return event

    def _region(self, geom: BaseGeometry) -> dict:
        return {"region": self.gaz.geojson(geom), "centre": self.gaz.lonlat(geom),
                "radius_m": round(math.sqrt(geom.area / math.pi), 1), "_geom": geom}

    def _reuse(self, geom: BaseGeometry, anchor: str, note: str) -> dict:
        return {"ok": True, **self._region(geom), "anchor": anchor, "ambiguous": False, "alternatives": [], "note": note}

    def _previous(self, subject: str, now: float, minutes: float | None) -> dict:
        fixes = self.history.get(subject) or []
        if not fixes:
            return {"ok": False, "note": "no earlier position to go back to"}
        target = now - 60 * (minutes or 0)
        earlier = [f for f in fixes if f[2] <= target + 30] or fixes[:1]
        fid, geom, t = earlier[-1]
        return self._reuse(geom, f"position at {time.strftime('%H:%M:%S', time.localtime(t))}",
                           f"back to the position reported in event {fid}")

    def _supersede(self, subject: str, only: int | None = None) -> tuple[int, BaseGeometry, float] | None:
        """Withdraw the subject's latest fix, but only if it is what they said last: correcting a report that was
        never plotted ("banana tower") must not wipe out the good fix before it."""
        fixes = self.history.get(subject)
        if not fixes:
            return None
        said_last = next((e for e in reversed(self.events)
                          if e["callsign"] == subject and e["type"] not in ("intent", "other", "order")), None)
        if said_last is None or said_last["id"] != fixes[-1][0] or (only is not None and only != fixes[-1][0]):
            return None
        withdrawn = fixes.pop()
        for e in self.events:
            if e["id"] == withdrawn[0]:
                e["superseded"] = True
        self._write({"kind": "supersede", "id": withdrawn[0]})
        return withdrawn

    def _write(self, line: dict) -> None:
        if not self.log:
            return
        self.log.parent.mkdir(exist_ok=True)
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def _replay(self, log: Path) -> None:
        """Rebuild state after a restart: the log is the source of truth."""
        for raw in log.read_text(encoding="utf-8").splitlines():
            try:
                line = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = line.pop("kind", "event")
            if kind == "reset":
                self.events.clear()
                self.history.clear()
            elif kind == "supersede":
                for e in self.events:
                    if e["id"] == line["id"]:
                        e["superseded"] = True
                for fixes in self.history.values():
                    fixes[:] = [f for f in fixes if f[0] != line["id"]]
            elif kind == "annotate":
                event = self.get(line.pop("id"))
                if event:
                    event.update(line)
            elif kind == "event" and "id" in line:
                line["id"] = len(self.events) + 1
                self.events.append(line)
                if line.get("ok") and line.get("region") and not line.get("superseded"):
                    geom = self.gaz.proj.to_xy(shape(line["region"]))
                    self.history.setdefault(line["callsign"], []).append((line["id"], geom, line["t"]))
