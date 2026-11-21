"""FastAPI service: a transmission (typed or spoken) in, regions on every connected map out.

Run from the repo root:  uvicorn backend.app:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

from . import stt, vad  # noqa: E402  (after load_dotenv so keys are visible)
from .geo import Gazetteer  # noqa: E402
from .net import Net  # noqa: E402
from .tracker import Tracker  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
LOG = DATA / "events.jsonl"

app = FastAPI(title="Voice-to-Map")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

gaz = Gazetteer()
tracker = Tracker(gaz, log=LOG)   # replays data/events.jsonl, so a restart keeps the picture
net = Net(tracker, log=DATA / "net.jsonl")   # radio-net mode: every transmission heard on the channel
clients: set[WebSocket] = set()
replay_task: asyncio.Task | None = None


class Report(BaseModel):
    text: str
    callsign: str | None = None   # used when the speaker does not say one


class NetLine(BaseModel):
    text: str
    t: float | None = None        # replays only: when it was said. Live input uses the server clock.


class NewPlace(BaseModel):
    name: str
    lon: float
    lat: float


async def broadcast(message: dict) -> None:
    for ws in list(clients):
        try:
            await ws.send_json(message)
        except Exception:
            clients.discard(ws)


async def publish(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        if e.get("corrects"):
            await broadcast({"type": "supersede", "id": e["corrects"], "by": e["id"]})
        pub = tracker.public(e)
        await broadcast({"type": "event", "event": pub})
        out.append(pub)
    return out


async def publish_net(heard: dict) -> dict:
    events = await publish(heard["events"])
    for a in heard["annotations"]:
        await broadcast({"type": "annotate", **a})
    for tx in heard["transmissions"]:
        await broadcast({"type": "tx", "tx": tx})
    return {"transmissions": heard["transmissions"], "events": events}


def _clock(t: float | None) -> float | None:
    """A client's capture time is better than ours (speech-to-text adds seconds), unless its clock is off."""
    return t if t is not None and abs(t - time.time()) < 120 else None


@app.post("/report")
async def report(body: Report) -> dict:
    return {"events": await publish(await tracker.ingest(body.text, body.callsign))}


@app.post("/audio")
async def audio(request: Request, callsign: str | None = None, lang: str | None = None) -> dict:
    """Body: a 16 kHz mono WAV clip from push-to-talk."""
    if stt.provider() is None:
        raise HTTPException(501, "no speech-to-text provider configured; the browser will fall back to its own")
    clip = await request.body()
    try:
        heard = await stt.transcribe(clip, gaz.vocabulary(), lang)
    except Exception as err:
        raise HTTPException(502, f"speech-to-text failed: {type(err).__name__}: {err}") from err
    if not heard["text"]:
        return {"transcript": "", "events": []}
    events = await tracker.ingest(heard["text"], callsign, source="voice", stt=heard)
    return {"transcript": heard["text"], "events": await publish(events)}


@app.post("/net/text")
async def net_text(body: NetLine) -> dict:
    """One transmission as heard on the net (typed by an operator, or from another recogniser)."""
    return await publish_net(await net.hear(body.text, now=body.t, source="radio-text"))


@app.post("/net/audio")
async def net_audio(request: Request, lang: str | None = None, t: float | None = None, dur: float = 0.0) -> dict:
    """One transmission cut from the channel by the browser's voice-activity detector (16 kHz mono WAV)."""
    if stt.provider() is None:
        raise HTTPException(501, "no speech-to-text provider configured")
    try:
        heard = await stt.transcribe(await request.body(), net.vocabulary(), lang)
    except Exception as err:
        raise HTTPException(502, f"speech-to-text failed: {type(err).__name__}: {err}") from err
    if not heard["text"]:
        return {"transcript": "", "transmissions": [], "events": []}
    out = await publish_net(await net.hear(heard["text"], now=_clock(t), duration=dur, source="radio", stt=heard))
    return {"transcript": heard["text"], **out}


@app.post("/net/recording")
async def net_recording(request: Request, lang: str | None = None) -> dict:
    """A recorded net (PCM WAV): cut into transmissions, transcribed in order, timed so the last one is now."""
    if stt.provider() is None:
        raise HTTPException(501, "no speech-to-text provider configured")
    try:
        clips = vad.split_recording(await request.body())
    except Exception as err:
        raise HTTPException(400, f"not a PCM WAV file: {err}") from err
    base = time.time() - (clips[-1][1] if clips else 0)
    out = []
    for start, end, clip in clips:
        heard = await stt.transcribe(clip, net.vocabulary(), lang)
        if heard["text"]:
            got = await publish_net(await net.hear(heard["text"], now=base + start, duration=end - start,
                                                   source="radio", stt=heard))
            out += got["transmissions"]
    return {"segments": len(clips), "transmissions": out}


@app.post("/net/replay")
async def net_replay(speed: float = 3.0) -> dict:
    """Play data/demo_net.jsonl onto the net, `speed` times faster than scripted (its own clock keeps real gaps)."""
    global replay_task
    if replay_task and not replay_task.done():
        raise HTTPException(409, "a replay is already running")
    lines = [json.loads(s) for s in (DATA / "demo_net.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]

    async def run() -> None:
        start, offset = time.time(), 0.0
        for line in lines:
            await asyncio.sleep(max(0.0, line["t"] - offset) / max(speed, 0.1))
            offset = line["t"]
            await publish_net(await net.hear(line["text"], now=start + line["t"], source="radio-text"))

    replay_task = asyncio.create_task(run())
    return {"lines": len(lines), "seconds": round(lines[-1]["t"] / max(speed, 0.1)) if lines else 0}


@app.get("/state")
def state() -> dict:
    return {"centre": [gaz.proj.lon0, gaz.proj.lat0], "bbox": gaz.bbox, "places": len(gaz.places),
            "events": [tracker.public(e) for e in tracker.events], "custom_places": gaz.custom(),
            "transmissions": net.transmissions[-500:], "stt": stt.provider()}


@app.post("/places")
async def add_place(body: NewPlace) -> dict:
    """Operator-named points ("checkpoint 3", "rally point bravo") become valid anchors immediately."""
    if not body.name.strip():
        raise HTTPException(400, "name required")
    gaz.add_custom(body.name.strip(), body.lon, body.lat)
    await broadcast({"type": "places", "places": gaz.custom()})
    return {"places": gaz.custom()}


@app.get("/export.geojson")
def export() -> dict:
    """Current picture and track history as GeoJSON, for any GIS or C2 tool."""
    features = [{"type": "Feature", "geometry": e["region"],
                 "properties": {k: e.get(k) for k in ("id", "t", "callsign", "text", "anchor", "radius_m", "ambiguous", "note")}}
                for e in tracker.events if e.get("ok") and not e.get("superseded")]
    return {"type": "FeatureCollection", "features": features}


@app.post("/reset")
async def reset() -> dict:
    if replay_task and not replay_task.done():
        replay_task.cancel()
    tracker.reset()
    net.reset()
    await broadcast({"type": "reset"})
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)
