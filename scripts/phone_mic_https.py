"""Lightweight HTTPS reverse proxy on :8443 so iOS Safari & Android Chrome can use their live microphone
over Wi-Fi LAN (`https://<LAN_IP>:8443/?handset=1`) without changing the desktop `http://localhost:5173` setup.

Proxies:
  /api/ws   -> ws://127.0.0.1:8000/ws
  /api/*    -> http://127.0.0.1:8000/*
  /*        -> http://127.0.0.1:5173/*
"""
from __future__ import annotations

import asyncio
import socket
import subprocess
from pathlib import Path

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect

REPO = Path(__file__).resolve().parent.parent
CERT_DIR = REPO / ".local_certs"
CERT_FILE = CERT_DIR / "phone_mic.crt"
KEY_FILE = CERT_DIR / "phone_mic.key"

BACKEND_HTTP = "http://127.0.0.1:8000"
BACKEND_WS = "ws://127.0.0.1:8000/ws"
FRONTEND_HTTP = "http://127.0.0.1:5173"

proxy_app = FastAPI(title="Phone Mic HTTPS Bridge")


def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def ensure_cert() -> tuple[str, str]:
    CERT_DIR.mkdir(exist_ok=True)
    ip = get_lan_ip()
    if not (CERT_FILE.exists() and KEY_FILE.exists()):
        san = f"DNS:localhost,IP:127.0.0.1,IP:{ip}"
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(KEY_FILE),
                "-out", str(CERT_FILE),
                "-days", "30",
                "-subj", f"/CN={ip}",
                "-addext", f"subjectAltName={san}",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return str(CERT_FILE), str(KEY_FILE)


@proxy_app.websocket("/api/ws")
async def ws_proxy(client_ws: WebSocket) -> None:
    await client_ws.accept()
    try:
        async with websockets.connect(BACKEND_WS) as up_ws:
            async def c2u():
                try:
                    while True:
                        msg = await client_ws.receive_text()
                        await up_ws.send(msg)
                except WebSocketDisconnect:
                    pass

            async def u2c():
                try:
                    async for msg in up_ws:
                        await client_ws.send_text(msg)
                except Exception:
                    pass

            done, pending = await asyncio.wait(
                [asyncio.create_task(c2u()), asyncio.create_task(u2c())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
    except Exception:
        pass


@proxy_app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def api_proxy(path: str, request: Request) -> Response:
    url = f"{BACKEND_HTTP}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    async with httpx.AsyncClient(timeout=40.0) as client:
        r = await client.request(request.method, url, content=body, headers=headers)
    resp_headers = {k: v for k, v in r.headers.items() if k.lower() not in ("content-encoding", "transfer-encoding", "content-length")}
    return Response(content=r.content, status_code=r.status_code, headers=resp_headers)


@proxy_app.api_route("/{path:path}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def frontend_proxy(path: str, request: Request) -> Response:
    url = f"{FRONTEND_HTTP}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "accept-encoding")}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.request(request.method, url, headers=headers)
    resp_headers = {k: v for k, v in r.headers.items() if k.lower() not in ("content-encoding", "transfer-encoding", "content-length")}
    return Response(content=r.content, status_code=r.status_code, headers=resp_headers)


if __name__ == "__main__":
    cert, key = ensure_cert()
    ip = get_lan_ip()
    print(f"Phone Mic HTTPS Bridge listening on https://{ip}:8443/?handset=1")
    uvicorn.run(proxy_app, host="0.0.0.0", port=8443, ssl_certfile=cert, ssl_keyfile=key, log_level="warning")
