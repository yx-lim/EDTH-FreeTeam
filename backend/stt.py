"""Speech-to-text for push-to-talk clips (16 kHz mono WAV from the browser).

Providers, picked by STT_PROVIDER or automatically:
  mistral  Voxtral via Mistral's API, primed with the district's place names (context_bias). Needs MISTRAL_API_KEY.
  whisper  faster-whisper running locally, primed through initial_prompt. Offline. `pip install faster-whisper`.
"""
from __future__ import annotations

import asyncio
import io
import os
import time

import httpx

STT_URL = "https://api.mistral.ai/v1/audio/transcriptions"
STT_MODEL = os.getenv("STT_MODEL", "voxtral-mini-transcribe-3")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
_whisper = None


def provider() -> str | None:
    chosen = os.getenv("STT_PROVIDER")
    if chosen:
        return None if chosen == "none" else chosen
    if os.getenv("MISTRAL_API_KEY"):
        return "mistral"
    try:
        import faster_whisper  # noqa: F401
        return "whisper"
    except ImportError:
        return None


async def transcribe(audio: bytes, vocabulary: list[str], language: str | None = None) -> dict:
    name = provider()
    if name is None:
        raise RuntimeError("no speech-to-text provider: set MISTRAL_API_KEY or install faster-whisper")
    t0 = time.perf_counter()
    text = await (_mistral(audio, vocabulary, language) if name == "mistral" else _local(audio, vocabulary, language))
    return {"text": text.strip(), "provider": name, "stt_ms": round((time.perf_counter() - t0) * 1000)}


async def _mistral(audio: bytes, vocabulary: list[str], language: str | None) -> str:
    data: dict = {"model": STT_MODEL, "context_bias": vocabulary[:100]}   # repeated form field, one term each
    if language:
        data["language"] = language
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(STT_URL, data=data, files={"file": ("clip.wav", audio, "audio/wav")},
                              headers={"Authorization": f"Bearer {os.environ['MISTRAL_API_KEY']}"})
        r.raise_for_status()
    return r.json().get("text", "")


async def _local(audio: bytes, vocabulary: list[str], language: str | None) -> str:
    global _whisper
    from faster_whisper import WhisperModel

    if _whisper is None:
        _whisper = WhisperModel(WHISPER_MODEL, compute_type="int8")

    def run() -> str:
        segments, _ = _whisper.transcribe(io.BytesIO(audio), language=language, vad_filter=True,
                                          initial_prompt="Radio position report. Places: " + ", ".join(vocabulary[:40]))
        return " ".join(s.text for s in segments)

    return await asyncio.to_thread(run)
