"""Speech-to-text for push-to-talk clips (16 kHz mono WAV from the browser).

Providers, picked by STT_PROVIDER or automatically (in this order):
  elevenlabs  ElevenLabs Scribe. Needs ELEVENLABS_API_KEY. Strong on Ukrainian and Russian.
  mistral  Voxtral via Mistral's API, primed with the district's place names (context_bias). Needs MISTRAL_API_KEY.
  whisper  faster-whisper running locally, primed through initial_prompt. Offline. `pip install faster-whisper`.
           Default `small` on the CPU: ~2-3 s a clip on an M-series Mac. large-v3-turbo is more accurate (12% vs 19%
           word errors on the demo net) but takes ~17 s a clip on the CPU. Its Apple GPU backend (WHISPER_DEVICE=mps)
           is ~2.4 s a clip but experimental: in testing it failed on every clip after the first, so it is opt-in.
"""
from __future__ import annotations

import asyncio
import io
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

STT_URL = "https://api.mistral.ai/v1/audio/transcriptions"
STT_MODEL = os.getenv("STT_MODEL", "voxtral-mini-transcribe-3")
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v1")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
_whisper = None
# Whisper's initial_prompt sets the expected language and style as much as the words: a Ukrainian prompt keeps
# Ukrainian in Cyrillic instead of transliterating or translating it.
PROMPTS = {"en": "Radio position report. Places: ", "fr": "Compte rendu radio de position. Lieux : ",
           "uk": "Радіообмін. Вежа, я Сокіл, прийом. Позивні та орієнтири: ",
           "ru": "Радиообмен. Башня, я Сокол, приём. Позывные и ориентиры: "}
_whisper_lock = threading.Lock()
# One thread owns the model, so two quick presses queue rather than compete for the CPU.
_whisper_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")


def _load_whisper():
    """Load once (the first load downloads the model: ~0.5 GB for small, ~1.6 GB for large-v3-turbo)."""
    global _whisper
    with _whisper_lock:
        if _whisper is None:
            from faster_whisper import WhisperModel
            try:
                _whisper = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE,
                                        compute_type="float16" if WHISPER_DEVICE == "mps" else "int8")
            except (ValueError, RuntimeError):   # a CTranslate2 build without the Metal backend: CPU, small model
                _whisper = WhisperModel(os.getenv("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    return _whisper


def _pcm(wav: bytes):
    """The browser's 16 kHz mono 16-bit WAV as float samples. Decoding it here avoids faster-whisper's PyAV path,
    which breaks when PyAV and faster-whisper versions drift apart (and is not needed for plain WAV)."""
    import wave

    import numpy as np

    with wave.open(io.BytesIO(wav)) as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            return io.BytesIO(wav)   # anything else: let faster-whisper decode and resample it
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def warm() -> None:
    """Load the local model in the background at startup, so the first push-to-talk does not wait for it."""
    if provider() == "whisper":
        _whisper_thread.submit(_load_whisper)


def provider() -> str | None:
    chosen = os.getenv("STT_PROVIDER")
    if chosen:
        return None if chosen == "none" else chosen
    if os.getenv("ELEVENLABS_API_KEY"):
        return "elevenlabs"
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
        raise RuntimeError("no speech-to-text provider: set ELEVENLABS_API_KEY or MISTRAL_API_KEY, or install faster-whisper")
    language = None if language in (None, "", "auto") else language
    if language in ("uk", "ru"):   # callsigns, procedure words and drone slang first: they are what gets misheard
        from . import lang_uk
        vocabulary = list(dict.fromkeys(lang_uk.vocabulary() + vocabulary))
    t0 = time.perf_counter()
    run = {"elevenlabs": _elevenlabs, "mistral": _mistral}.get(name, _local)
    text = await run(audio, vocabulary, language)
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


async def _elevenlabs(audio: bytes, vocabulary: list[str], language: str | None) -> str:
    data: dict = {"model_id": ELEVENLABS_MODEL, "tag_audio_events": "false"}
    if language:
        data["language_code"] = language
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(ELEVENLABS_URL, data=data, files={"file": ("clip.wav", audio, "audio/wav")},
                              headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]})
        r.raise_for_status()
    return r.json().get("text", "")


async def _local(audio: bytes, vocabulary: list[str], language: str | None) -> str:
    def run() -> str:
        segments, _ = _load_whisper().transcribe(_pcm(audio), language=language, vad_filter=True,
                                          initial_prompt=PROMPTS.get(language, PROMPTS["en"]) + ", ".join(vocabulary[:40]))
        return " ".join(s.text for s in segments)

    return await asyncio.get_running_loop().run_in_executor(_whisper_thread, run)
