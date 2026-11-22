"""FastAPI service: a transmission (typed or spoken) in, regions on every connected map out.

Run from the repo root:  uvicorn backend.app:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

from . import export as exports  # noqa: E402
from . import extract as extractor  # noqa: E402
from . import msg_ingest, stt, vad  # noqa: E402  (after load_dotenv so keys are visible)
from .geo import Gazetteer  # noqa: E402
from .net import Net  # noqa: E402
from .tracker import Tracker  # noqa: E402

from . import zone  # noqa: E402


app = FastAPI(title="Voice-to-Map")


@app.on_event("startup")
async def _warm_speech_to_text() -> None:
    stt.warm()


app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# One map, tracker and radio log per zone, loaded the first time the zone is used and kept, so switching back and
# forth loses nothing. The module globals gaz / tracker / net / DATA always point at the current zone.
_zones: dict[str, tuple[Gazetteer, Tracker, Net]] = {}


def use_zone(name: str) -> None:
    global gaz, tracker, net, DATA
    zone.switch(name)
    DATA = zone.DIR      # data/ for Paris, data/zones/<name>/ otherwise: each zone keeps its own logs
    if name not in _zones:
        g = Gazetteer(DATA / "gazetteer.json", aliases=DATA / "aliases.json", custom=DATA / "custom_places.json",
                      codenames=DATA / "codenames.json")
        t = Tracker(g, log=DATA / "events.jsonl")   # replays the zone's log, so a restart keeps the picture
        _zones[name] = (g, t, Net(t, log=DATA / "net.jsonl"))   # radio-net mode: every transmission heard
    gaz, tracker, net = _zones[name]


use_zone(zone.NAME)
clients: set[WebSocket] = set()
handsets: dict[WebSocket, dict] = {}
replay_task: asyncio.Task | None = None
auto_confirm_mode: bool = False   # toggled to True by frontend AUTO-PLOT mode; defaults False so unit tests stay strict


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _handset_summary() -> dict:
    active_tx = [h.get("callsign") for h in handsets.values() if h.get("transmitting")]
    return {
        "count": len(handsets),
        "transmitting": bool(active_tx),
        "active_callsign": active_tx[0] if active_tx else None,
    }


class Report(BaseModel):
    text: str
    callsign: str | None = None   # used when the speaker does not say one
    heading: float | None = None  # optional operator compass heading for dead-reckoning moves


class NetLine(BaseModel):
    text: str
    t: float | None = None        # replays only: when it was said. Live input uses the server clock.


class NewPlace(BaseModel):
    name: str
    lon: float
    lat: float
    aliases: list[str] = []       # other spoken names: "Вторая посадка" for "Друга посадка"


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
        if auto_confirm_mode and e.get("ok") and not e.get("superseded") and not e.get("confirmed"):
            tracker.annotate(e["id"], confirmed=True, confirmed_at=time.time(), auto_confirmed=True)
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
    return {"events": await publish(await tracker.ingest(body.text, body.callsign, heading=body.heading))}


@app.post("/audio")
async def audio(request: Request, callsign: str | None = None, lang: str | None = None,
                heading: float | None = None) -> dict:
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
    events = await tracker.ingest(heard["text"], callsign, source="voice", stt=heard, heading=heading)
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
    failed = 0
    for start, end, clip in clips:
        try:   # one clip the provider chokes on must not lose the rest of the recording
            heard = await stt.transcribe(clip, net.vocabulary(), lang)
        except Exception:
            failed += 1
            continue
        if heard["text"]:
            got = await publish_net(await net.hear(heard["text"], now=base + start, duration=end - start,
                                                   source="radio", stt=heard))
            out += got["transmissions"]
    return {"segments": len(clips), "failed": failed, "transmissions": out}


@app.post("/net/replay")
async def net_replay(speed: float = 3.0, script: str = "en") -> dict:
    """Play a demo net onto the net, `speed` times faster than scripted (its own clock keeps real gaps).
    script: "en" (data/demo_net.jsonl, English and French), "uk" (data/demo_net_uk.jsonl, Ukrainian and Russian) or
    "battle" (data/demo_net_battle.jsonl: three teams, a blown bridge, waiting FPVs, a mine, a blocked road reopened)."""
    global replay_task
    if replay_task and not replay_task.done():
        raise HTTPException(409, "a replay is already running")
    path = DATA / {"uk": "demo_net_uk.jsonl", "battle": "demo_net_battle.jsonl"}.get(script, "demo_net.jsonl")
    if not path.exists():
        raise HTTPException(404, f"no {path.name} for zone {zone.NAME}")
    lines = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]

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
            "transmissions": net.transmissions[-500:], "stt": stt.provider(), "stt_options": stt.available(),
            "zone": zone.info(), "zones": [zone.info(z) for z in zone.available()],
            "offline": extractor.is_offline(), "auto_confirm": auto_confirm_mode, "handsets": _handset_summary()}


class ZoneChoice(BaseModel):
    name: str


@app.post("/zone")
async def zone_set(body: ZoneChoice) -> dict:
    """Switch the area of operations while running (paris | irpin | ...). Every open map reloads onto it."""
    global replay_task
    if replay_task and not replay_task.done():
        replay_task.cancel()   # a demo net belongs to the zone it was started in
    try:
        use_zone(body.name)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    await broadcast({"type": "zone", "zone": zone.info()})
    return zone.info()


@app.get("/offline-basemap.geojson")
def offline_basemap() -> dict:
    """Local pre-downloaded OSM streets, parks, and landmark footprints for 100% offline map rendering."""
    return gaz.offline_basemap()


# Minimal 1x1 light-grey PNG (inverts to #090e14 under MapLibre's Dark Ops paint) for uncached tiles outside Paris
_FALLBACK_TILE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xef\xef\x0f\x00\x05\xc6\x02\xbd\xa4\xc8\x8d\x96\x00\x00\x00\x00IEND\xaeB`\x82"
)


@app.get("/tiles/{z}/{x}/{y}.jpg")
def offline_tile(z: int, x: int, y: int) -> Response:
    """Serve locally cached Paris & surrounding map tiles with zero internet."""
    p = DATA / "offline_tiles" / str(z) / str(x) / f"{y}.jpg"
    if p.exists():
        return Response(p.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
    return Response(_FALLBACK_TILE_PNG, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})


@app.get("/offline-status")
def offline_status() -> dict:
    """Report readiness of local offline stack (MLX Whisper, Ollama LLM, cached Paris tiles, local landmarks)."""
    tile_dir = DATA / "offline_tiles"
    tile_count = sum(1 for _ in tile_dir.rglob("*.jpg")) if tile_dir.exists() else 0
    return {
        "offline_mode": extractor.is_offline(),
        "mlx_whisper": stt._mlx_installed(),
        "mlx_whisper_model": stt.MLX_WHISPER_MODEL,
        "ollama_model": extractor.OLLAMA_MODEL,
        "cached_tiles": tile_count,
        "local_places": len(gaz.places),
    }


class ModeChoice(BaseModel):
    offline: bool | None = None
    auto_confirm: bool | None = None


@app.get("/mode")
def mode_get() -> dict:
    return {"offline": extractor.is_offline(), "auto_confirm": auto_confirm_mode, "stt": stt.provider()}


@app.post("/mode")
async def mode_set(body: ModeChoice) -> dict:
    """Live switch between Hybrid AI / Offline Ops and AUTO-PLOT (auto-confirm clear reports) / GATE: ON."""
    global auto_confirm_mode
    if body.offline is not None:
        extractor.set_offline(body.offline)
    if body.auto_confirm is not None:
        auto_confirm_mode = bool(body.auto_confirm)
        if auto_confirm_mode:
            # Auto-confirm all existing pending reports immediately so AUTO-PLOT clears the queue cleanly
            now_t = time.time()
            for e in tracker.events:
                if e.get("ok") and not e.get("superseded") and not e.get("rejected") and not e.get("confirmed"):
                    fields = {"confirmed": True, "confirmed_at": now_t, "auto_confirmed": True}
                    tracker.annotate(e["id"], **fields)
                    await broadcast({"type": "annotate", "id": e["id"], "fields": fields})
    out = {"offline": extractor.is_offline(), "auto_confirm": auto_confirm_mode, "stt": stt.provider()}
    await broadcast({"type": "mode", **out})
    return out


class PickCandidate(BaseModel):
    index: int


@app.post("/events/{event_id}/pick")
async def pick_candidate(event_id: int, body: PickCandidate) -> dict:
    """Operator resolves an ambiguous place ('which tower?') by selecting one of candidate_options."""
    event = tracker.pick_candidate(event_id, body.index)
    if event is None:
        raise HTTPException(404, f"no event {event_id} or invalid candidate index {body.index}")
    pub = tracker.public(event)
    await broadcast({"type": "annotate", "id": event_id, "fields": pub})
    return pub


class EventEdit(BaseModel):
    count: int | None = None
    side: str | None = None
    what: str | None = None
    activity: str | None = None
    heading: str | None = None
    speed_mps: float | None = None


@app.patch("/events/{event_id}")
async def edit_event(event_id: int, body: EventEdit) -> dict:
    """Operator factual correction (e.g., quantity 2 tanks -> 3 tanks, side unknown -> hostile, UAV speed)."""
    event = tracker.edit_event(
        event_id,
        count=body.count,
        side=body.side,
        what=body.what,
        activity=body.activity,
        heading=body.heading,
        speed_mps=body.speed_mps,
    )
    if event is None:
        raise HTTPException(404, f"no event {event_id}")
    pub = tracker.public(event)
    await broadcast({"type": "annotate", "id": event_id, "fields": pub})
    return pub


class MessageBatch(BaseModel):
    text: str
    channel: str = "auto"   # auto | whatsapp | email | chat
    default_callsign: str | None = None
    heading: float | None = None


@app.post("/ingest/messages")
async def ingest_messages(body: MessageBatch) -> dict:
    """Extract and ingest one or more tactical reports from pasted WhatsApp chats or emails."""
    if not body.text.strip():
        raise HTTPException(400, "message text required")
    channel, items = await msg_ingest.parse_messages(body.text, body.channel)
    all_events = []
    for item in items:
        cs = item.get("callsign") or body.default_callsign
        extra = {
            "channel": channel,
            "sender": item.get("sender"),
            "timestamp_raw": item.get("timestamp_raw"),
            "subject": item.get("subject"),
        }
        evs = await tracker.ingest(
            item["text"],
            default_callsign=cs,
            source=channel,
            extra={k: v for k, v in extra.items() if v},
            heading=body.heading,
        )
        all_events.extend(await publish(evs))
    return {"channel": channel, "parsed_count": len(items), "events": all_events}


@app.get("/network-info")
def network_info() -> dict:
    ip = _lan_ip()
    return {
        "lan_ip": ip,
        "https_handset_url": f"https://{ip}:8443/?handset=1",
        "http_handset_url": f"http://{ip}:5173/?handset=1",
        "handsets": _handset_summary(),
    }


class SttChoice(BaseModel):
    provider: str


@app.get("/stt")
def stt_get() -> dict:
    return {"provider": stt.provider(), "available": stt.available()}


@app.post("/stt")
async def stt_set(body: SttChoice) -> dict:
    """Switch speech-to-text while running (elevenlabs | gemini | mistral | whisper | none). Lasts until restart."""
    try:
        stt.choose(body.provider)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    out = {"provider": stt.provider(), "available": stt.available()}
    await broadcast({"type": "stt", **out})
    return out


@app.post("/places")
async def add_place(body: NewPlace) -> dict:
    """Operator-named points ("checkpoint 3", "rally point bravo") become valid anchors immediately."""
    if not body.name.strip():
        raise HTTPException(400, "name required")
    gaz.add_custom(body.name.strip(), body.lon, body.lat, body.aliases)
    await broadcast({"type": "places", "places": gaz.custom()})
    return {"places": gaz.custom()}


@app.post("/events/{event_id}/confirm")
async def confirm(event_id: int) -> dict:
    """The duty officer accepts a report. Until then it is a draft: the map draws its unit with a dashed
    ("suspected") frame when the fix is ambiguous or the callsign was assumed."""
    fields = {"confirmed": True, "confirmed_at": time.time()}
    event = tracker.annotate(event_id, **fields)
    if event is None:
        raise HTTPException(404, f"no event {event_id}")
    await broadcast({"type": "annotate", "id": event_id, "fields": fields})
    return tracker.public(event)


@app.post("/events/{event_id}/reject")
async def reject(event_id: int) -> dict:
    """The duty officer rules a report out: it leaves the map (the unit falls back to its previous fix, a contact
    track to its previous sighting) and stays in the log, marked rejected."""
    event = tracker.reject(event_id)
    if event is None:
        raise HTTPException(404, f"no event {event_id}")
    fields = {k: event[k] for k in ("rejected", "superseded", "rejected_at")}
    await broadcast({"type": "annotate", "id": event_id, "fields": fields})
    return tracker.public(event)


@app.get("/picture.nvg")
def picture_nvg(drafts: bool = False) -> Response:
    """The current picture as NATO Vector Graphics (APP-6 symbols): confirmed items only unless ?drafts=true."""
    return Response(exports.nvg(exports.items(tracker, drafts)), media_type="application/xml",
                    headers={"Content-Disposition": 'attachment; filename="picture.nvg"'})


@app.get("/picture.geojson")
def picture_geojson(drafts: bool = False) -> dict:
    """The current picture (not the history) as GeoJSON with SIDC, MGRS and draft flags."""
    return exports.geojson(exports.items(tracker, drafts))


@app.get("/export.geojson")
def export() -> dict:
    """Current picture and track history as GeoJSON, for any GIS or C2 tool."""
    features = [{"type": "Feature", "geometry": e["region"],
                 "properties": {k: e.get(k) for k in ("id", "t", "callsign", "type", "contact", "speaker", "text", "anchor",
                                                     "radius_m", "ambiguous", "note")}}
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
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") == "handset_hello":
                handsets[ws] = {"callsign": msg.get("callsign") or "alpha 1", "transmitting": False}
                await broadcast({"type": "handsets", **_handset_summary()})
            elif msg.get("type") == "handset_ptt":
                handsets[ws] = {
                    "callsign": msg.get("callsign") or "alpha 1",
                    "transmitting": bool(msg.get("active")),
                }
                await broadcast({"type": "handsets", **_handset_summary()})
    except WebSocketDisconnect:
        clients.discard(ws)
        if ws in handsets:
            handsets.pop(ws, None)
            await broadcast({"type": "handsets", **_handset_summary()})
