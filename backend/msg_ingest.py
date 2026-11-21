"""Extract tactical field reports from WhatsApp chat exports, emails, Telegram, or Signal threads.

Supports both online AI parsing (Gemini) and 100% offline deterministic parsing so warzone text
communications work even with zero internet connectivity.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from . import extract as _extract

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# WhatsApp export patterns:
#   [21/11/2026, 14:12:05] +380 67 555 1234 (Граніт): message
#   21/11/2026, 14:12 - Alpha 2: message
#   [14:12] Bravo 1: message
_WA_BRACKET = re.compile(r"^\[([^\]]+)\]\s*([^:]{1,60}):\s*(.+)$")
_WA_DASH = re.compile(r"^(\d{1,2}[./-]\d{1,2}[./-]\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?)\s*[-–]\s*([^:]{1,60}):\s*(.+)$")
_EMAIL_HEADER = re.compile(r"^(From|To|Cc|Subject|Date|Sent):\s*(.*)$", re.IGNORECASE)
_CALLSIGN_HINT = re.compile(
    r"\b(alpha|bravo|charlie|delta|echo|foxtrot|сокіл|сокол|граніт|гранит|лис|вікінг|беркут)(?:\s*[- ]?\s*\d+)?\b",
    re.IGNORECASE,
)


def detect_channel(raw_text: str, requested: str = "auto") -> str:
    if requested in ("whatsapp", "email", "chat"):
        return requested
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if any(_EMAIL_HEADER.match(ln) for ln in lines[:8]):
        return "email"
    if any(_WA_BRACKET.match(ln) or _WA_DASH.match(ln) for ln in lines[:8]):
        return "whatsapp"
    return "chat"


def _extract_callsign_from_sender(sender: str | None) -> str | None:
    if not sender:
        return None
    m = _CALLSIGN_HINT.search(sender)
    if m:
        return m.group(0).strip().replace("-", " ").lower()
    # Fallback handle from email local-part or display name ("Capt. Kovalenko <...>" -> "capt kovalenko")
    s = sender.strip()
    if "<" in s:
        name_part = s.split("<", 1)[0].strip(' "\'')
        if name_part:
            s = name_part
        else:
            s = s.split("<", 1)[1].split(">", 1)[0].strip()
    if "@" in s:
        s = s.split("@", 1)[0]
    cleaned = re.sub(r"[^a-zA-Z0-9\u0400-\u04FF\s]", " ", s).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned and len(cleaned) <= 24 and cleaned.lower() not in ("whatsapp", "email", "message", "unknown"):
        return cleaned.lower()
    return None


def _parse_deterministic(raw_text: str, channel: str) -> list[dict[str, Any]]:
    """Offline-capable parser for WhatsApp exports, Email messages, and multi-line chat logs."""
    lines = raw_text.splitlines()
    messages: list[dict[str, Any]] = []

    if channel == "whatsapp":
        current: dict[str, Any] | None = None
        for raw_ln in lines:
            ln = raw_ln.strip()
            if not ln:
                continue
            m = _WA_BRACKET.match(ln) or _WA_DASH.match(ln)
            if m:
                if current:
                    messages.append(current)
                ts, sender, body = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                if any(skip in body.lower() for skip in ("end-to-end encrypted", "media omitted", "deleted this message")):
                    current = None
                    continue
                current = {
                    "channel": "whatsapp",
                    "sender": sender,
                    "callsign": _extract_callsign_from_sender(sender),
                    "timestamp_raw": ts,
                    "text": body,
                }
            elif current:
                current["text"] = f"{current['text']} {ln}".strip()
            else:
                messages.append({"channel": "whatsapp", "sender": "WhatsApp", "callsign": None, "timestamp_raw": "", "text": ln})
        if current:
            messages.append(current)
    elif channel == "email":
        headers: dict[str, str] = {}
        body_lines: list[str] = []
        in_headers = True
        for raw_ln in lines:
            ln = raw_ln.strip()
            if in_headers and not ln:
                if headers:
                    in_headers = False
                continue
            if in_headers and (hm := _EMAIL_HEADER.match(ln)):
                headers[hm.group(1).lower()] = hm.group(2).strip()
                continue
            in_headers = False
            if ln.startswith("--") or ln.lower().startswith(("regards,", "best,", "sent from my")):
                break
            if ln and not ln.startswith(">"):
                body_lines.append(ln)
        sender = headers.get("from", "Email")
        subject = headers.get("subject", "")
        ts = headers.get("date") or headers.get("sent") or ""
        cs = _extract_callsign_from_sender(sender) or _extract_callsign_from_sender(subject)
        # Split email body into individual tactical sentences/bullets
        body = "\n".join(body_lines)
        chunks = [c.strip(" •-*") for c in re.split(r"(?:\n+|(?<=[.!?])\s+(?=[A-ZА-ЯІЇЄ]))", body) if c.strip(" •-*")]
        for chunk in chunks:
            if len(chunk) < 6:
                continue
            messages.append({
                "channel": "email",
                "sender": sender,
                "subject": subject,
                "callsign": cs,
                "timestamp_raw": ts,
                "text": chunk,
            })
    else:
        for raw_ln in lines:
            ln = raw_ln.strip(" •-*")
            if len(ln) < 4:
                continue
            if ":" in ln and len(ln.split(":", 1)[0]) <= 30:
                sender, body = ln.split(":", 1)
                messages.append({
                    "channel": "chat",
                    "sender": sender.strip(),
                    "callsign": _extract_callsign_from_sender(sender),
                    "timestamp_raw": "",
                    "text": body.strip(),
                })
            else:
                messages.append({"channel": "chat", "sender": "Message", "callsign": None, "timestamp_raw": "", "text": ln})

    # Further split compound sentences containing multiple independent reports separated by semicolons/plus
    return messages


async def _split_with_gemini(raw_text: str, channel: str) -> list[dict[str, Any]] | None:
    """Use Gemini (when online) to cleanly separate noisy WhatsApp/Email threads into atomic tactical reports."""
    if _extract.is_offline():
        return None
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    prompt = (
        f"Channel: {channel}\n"
        "Split this warzone WhatsApp/email/chat text into individual atomic tactical reports (unit positions, "
        "movements, corrections, or enemy/hazard contacts). Preserve the original language (English, French, "
        "Ukrainian, Russian) and exact quantities (e.g., '2 tanks', '3 ворожих танки'). Ignore greetings, "
        "email signatures, and non-tactical chatter.\n"
        "Return ONLY JSON:\n"
        '{"items": [{"sender": "name or email", "callsign": "normalized callsign or null", '
        '"timestamp_raw": "original timestamp or empty", "text": "clean single tactical report sentence"}]}\n\n'
        f"RAW TEXT:\n{raw_text[:6000]}"
    )
    gen_cfg: dict[str, Any] = {"temperature": 0, "responseMimeType": "application/json"}
    if "3.5" in model or "2.5" in model:
        gen_cfg["thinkingConfig"] = {"thinkingLevel": "MINIMAL"}
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(GEMINI_URL.format(model=model), json=payload, headers={"x-goog-api-key": key})
            if r.status_code == 400 and "thinkingConfig" in payload["generationConfig"]:
                payload["generationConfig"].pop("thinkingConfig", None)
                r = await client.post(GEMINI_URL.format(model=model), json=payload, headers={"x-goog-api-key": key})
            r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        data = json.loads("".join(p.get("text", "") for p in parts))
        items = data.get("items") or []
        out = []
        for it in items:
            txt = str(it.get("text") or "").strip()
            if not txt:
                continue
            out.append({
                "channel": channel,
                "sender": str(it.get("sender") or channel.title()).strip(),
                "callsign": it.get("callsign") or _extract_callsign_from_sender(it.get("sender")),
                "timestamp_raw": str(it.get("timestamp_raw") or "").strip(),
                "text": txt,
            })
        return out or None
    except Exception:
        return None


async def _split_with_ollama(raw_text: str, channel: str) -> list[dict[str, Any]] | None:
    """Use local on-device Ollama LLM (offline) to split noisy WhatsApp/Email threads into atomic tactical reports."""
    if (os.getenv("EXTRACTOR") or "").lower() == "rules":
        return None
    prompt = (
        f"Channel: {channel}. Split this WhatsApp/email text into atomic tactical reports (positions, movements, "
        "contacts). Keep original language (English, French, Ukrainian, Russian) and exact quantities. Ignore greetings.\n"
        'Return ONLY JSON: {"items": [{"sender": "name", "callsign": "lowercase callsign or null", "timestamp_raw": "", "text": "single report"}]}\n\n'
        f"{raw_text[:4000]}"
    )
    payload = {
        "model": _extract.OLLAMA_MODEL,
        "format": "json",
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0, "num_predict": 450},
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.post(_extract.OLLAMA_URL, json=payload)
            r.raise_for_status()
        data = json.loads((r.json().get("message") or {}).get("content") or "{}")
        out = []
        for it in data.get("items") or []:
            txt = str(it.get("text") or "").strip()
            if not txt:
                continue
            out.append({
                "channel": channel,
                "sender": str(it.get("sender") or channel.title()).strip(),
                "callsign": it.get("callsign") or _extract_callsign_from_sender(it.get("sender")),
                "timestamp_raw": str(it.get("timestamp_raw") or "").strip(),
                "text": txt,
            })
        return out or None
    except Exception:
        return None


async def parse_messages(raw_text: str, requested_channel: str = "auto") -> tuple[str, list[dict[str, Any]]]:
    """Return (detected_channel, list_of_atomic_messages)."""
    channel = detect_channel(raw_text, requested_channel)
    if _extract.is_offline():
        if getattr(_extract, "_offline_mode", False):
            ol_items = await _split_with_ollama(raw_text, channel)
            if ol_items:
                return channel, ol_items
        return channel, _parse_deterministic(raw_text, channel)
    ai_items = await _split_with_gemini(raw_text, channel)
    if ai_items:
        return channel, ai_items
    return channel, _parse_deterministic(raw_text, channel)
