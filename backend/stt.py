"""Speech-to-text for push-to-talk clips (16 kHz mono WAV from the browser).

The operator can switch provider while the app runs (the dropdown in the app, POST /stt); that choice lasts until the
backend restarts.

Providers, picked by STT_PROVIDER or automatically (in this order):
  elevenlabs  ElevenLabs Scribe. Needs ELEVENLABS_API_KEY. Strong on Ukrainian and Russian.
  gemini   Gemini listening to the clip, primed with the place names. Needs GEMINI_API_KEY. Only used when chosen.
  mistral  Voxtral via Mistral's API, primed with the district's place names (context_bias). Needs MISTRAL_API_KEY.
  whisper  faster-whisper running locally, primed through initial_prompt. Offline. `pip install faster-whisper`.
           Default `small` on the CPU: ~2-3 s a clip on an M-series Mac. large-v3-turbo is more accurate (12% vs 19%
           word errors on the demo net) but takes ~17 s a clip on the CPU. Its Apple GPU backend (WHISPER_DEVICE=mps)
           is ~2.4 s a clip but experimental: in testing it failed on every clip after the first, so it is opt-in.
"""
from __future__ import annotations

import asyncio
import base64
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
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_STT_MODEL = os.getenv("GEMINI_STT_MODEL") or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
LANGUAGES = {"en": "English", "fr": "French", "uk": "Ukrainian", "ru": "Russian"}
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
MLX_WHISPER_MODEL = os.getenv("MLX_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo-q4")
_mlx_local_path: str | None = None
_whisper = None


def _resolve_mlx_model_path() -> str:
    """Resolve the local cached HuggingFace snapshot directory once so MLX Whisper makes ZERO network calls offline."""
    global _mlx_local_path
    if _mlx_local_path:
        return _mlx_local_path
    from pathlib import Path
    repo = MLX_WHISPER_MODEL
    if Path(repo).exists():
        _mlx_local_path = repo
        return repo
    slug = "models--" + repo.replace("/", "--")
    snaps = sorted(Path.home().glob(f".cache/huggingface/hub/{slug}/snapshots/*"))
    if snaps:
        _mlx_local_path = str(snaps[-1])
        return _mlx_local_path
    return repo
# Whisper's initial_prompt sets the expected language and style as much as the words: a Ukrainian prompt keeps
# Ukrainian in Cyrillic instead of transliterating or translating it.
PROMPTS = {"en": "Radio position report. Places: ", "fr": "Compte rendu radio de position. Lieux : ",
           "uk": "Радіообмін. Вежа, я Сокіл, прийом. Позивні та орієнтири: ",
           "ru": "Радиообмен. Башня, я Сокол, приём. Позывные и ориентиры: "}


def _prompt(language: str | None, vocabulary: list[str]) -> str:
    """Auto language on a Ukrainian net: an English prompt pulls Whisper towards transliteration, so go by the
    script of the callsigns and codenames it is being primed with."""
    if language is None and any("\u0400" <= ch <= "\u04ff" for w in vocabulary[:40] for ch in w):
        return PROMPTS["uk"]
    return PROMPTS.get(language, PROMPTS["en"])


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


def _mlx_installed() -> bool:
    try:
        import mlx_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _faster_whisper_installed() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _whisper_installed() -> bool:
    return _mlx_installed() or _faster_whisper_installed()


def _is_offline_mode() -> bool:
    from . import extract as _extract
    return bool(getattr(_extract, "_offline_mode", False))


_chosen: str | None = None   # set from the app at run time; overrides STT_PROVIDER until restart
KEYS = {"elevenlabs": "ELEVENLABS_API_KEY", "gemini": "GEMINI_API_KEY", "mistral": "MISTRAL_API_KEY"}
LABELS = {
    "elevenlabs": "ElevenLabs",
    "gemini": "Gemini",
    "mistral": "Mistral Voxtral",
    "whisper": "MLX Whisper (Local)" if _mlx_installed() else "Whisper (local)",
}


def available() -> list[str]:
    """Providers that can run now: cloud ones with a key, local Whisper (MLX / faster-whisper) when installed."""
    out = [name for name, key in KEYS.items() if os.getenv(key)]
    return out + (["whisper"] if _whisper_installed() else [])


def choose(name: str) -> str | None:
    """Switch provider from the app. "none" turns server speech-to-text off (the browser's own takes over)."""
    global _chosen
    if name != "none" and name not in available():
        raise ValueError(f"{name} is not available: add its key to .env or install it")
    _chosen = name
    if name == "whisper" and not _mlx_installed():
        _whisper_thread.submit(_load_whisper)   # preload faster-whisper CPU model
    return provider()


def provider() -> str | None:
    if _is_offline_mode():
        return "whisper" if _whisper_installed() else None
    chosen = _chosen or os.getenv("STT_PROVIDER")
    if chosen:
        return None if chosen == "none" else chosen
    if os.getenv("ELEVENLABS_API_KEY"):
        return "elevenlabs"
    if os.getenv("MISTRAL_API_KEY"):
        return "mistral"
    return "whisper" if _whisper_installed() else None


async def transcribe(audio: bytes, vocabulary: list[str], language: str | None = None) -> dict:
    name = provider()
    if name is None:
        raise RuntimeError("no speech-to-text provider: set ELEVENLABS_API_KEY or MISTRAL_API_KEY, or install mlx-whisper/faster-whisper")
    language = None if language in (None, "", "auto") else language
    if language in ("uk", "ru"):   # callsigns, procedure words and drone slang first: they are what gets misheard
        from . import lang_uk
        vocabulary = list(dict.fromkeys(lang_uk.vocabulary() + vocabulary))
    t0 = time.perf_counter()
    run = {"elevenlabs": _elevenlabs, "gemini": _gemini, "mistral": _mistral}.get(name, _local)
    used_provider = "mlx-whisper" if (name == "whisper" and _mlx_installed()) else name
    try:
        text = await run(audio, vocabulary, language)
    except (httpx.HTTPError, OSError):
        # Automatic offline failover: if cloud STT fails due to internet loss, run local MLX Whisper seamlessly!
        if name != "whisper" and _whisper_installed():
            text = await _local(audio, vocabulary, language)
            used_provider = "mlx-whisper (offline fallback)" if _mlx_installed() else "whisper (offline fallback)"
        else:
            raise
    return {"text": text.strip(), "provider": used_provider, "stt_ms": round((time.perf_counter() - t0) * 1000)}


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


async def _gemini(audio: bytes, vocabulary: list[str], language: str | None) -> str:
    said = f"The speaker uses {LANGUAGES[language]}. " if language in LANGUAGES else ""
    prompt = ("Transcribe this military radio transmission word for word, in the language and script spoken (keep "
              "Ukrainian and Russian in Cyrillic; never translate). Output only the transcript, no notes. " + said +
              "Callsigns, procedure words and place names likely to be heard: " + ", ".join(vocabulary[:100]))
    payload = {"contents": [{"role": "user", "parts": [
        {"text": prompt}, {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(audio).decode()}}]}],
        "generationConfig": {"temperature": 0}}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(GEMINI_URL.format(model=GEMINI_STT_MODEL), json=payload,
                              headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
        r.raise_for_status()
    parts = r.json()["candidates"][0]["content"].get("parts") or []
    return "".join(p.get("text", "") for p in parts)


async def _local(audio: bytes, vocabulary: list[str], language: str | None) -> str:
    def run() -> str:
        prompt = _prompt(language, vocabulary) + ", ".join(vocabulary[:40])
        if _mlx_installed():
            import mlx_whisper
            import numpy as np
            pcm = _pcm(audio)
            if isinstance(pcm, np.ndarray) and (pcm.size < 1600 or float(np.sqrt(np.mean(pcm ** 2))) < 0.0025):
                return ""   # silence guard prevents Whisper "Thank you." hallucinations on empty clicks
            kwargs: dict = {
                "path_or_hf_repo": _resolve_mlx_model_path(),
                "initial_prompt": prompt,
                "condition_on_previous_text": False,
                "no_speech_threshold": 0.6,
            }
            if language:
                kwargs["language"] = language
            result = mlx_whisper.transcribe(pcm, **kwargs)
            try:
                import mlx.core as mx
                mx.clear_cache()
            except Exception:
                pass
            return str(result.get("text") or "")
        segments, _ = _load_whisper().transcribe(_pcm(audio), language=language, vad_filter=True,
                                                 initial_prompt=prompt)
        return " ".join(s.text for s in segments)

    return await asyncio.get_running_loop().run_in_executor(_whisper_thread, run)
