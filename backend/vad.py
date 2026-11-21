"""Voice-activity detection: cut a continuous channel into transmissions. Energy-based on purpose: a radio net is
squelched (near silence between transmissions) or carries steady hiss, and either way speech stands well above the
floor. The browser runs the same algorithm live (frontend/src/vad.js); this one serves recorded files and tests.

    segments(samples, rate) -> [(start_s, end_s), ...]
"""
from __future__ import annotations

import io
import wave

import numpy as np

FRAME_S = 0.02
START_K, STOP_K = 3.0, 2.0       # speech starts above 3x the noise floor and stops below 2x
MIN_LEVEL = 0.004                # absolute floor (about -48 dBFS) so digital silence does not trigger on breath
HANG_S = 0.7                     # silence needed to end a transmission (radio speakers pause between phrases)
PRE_S = 0.25                     # keep a little audio before the trigger: the first syllable is often quiet
MIN_S = 0.35                     # shorter bursts are clicks, squelch tails or key-ups
MAX_S = 30.0                     # cut very long transmissions so transcription stays fast


def segments(x: np.ndarray, rate: int) -> list[tuple[float, float]]:
    frame = max(1, int(rate * FRAME_S))
    n = len(x) // frame
    if n == 0:
        return []
    rms = np.sqrt(np.mean(x[: n * frame].reshape(n, frame).astype(np.float64) ** 2, axis=1))
    floor = max(float(np.percentile(rms, 10)), 1e-5)
    on, off = max(floor * START_K, MIN_LEVEL), max(floor * STOP_K, MIN_LEVEL * 0.6)
    out, start, quiet = [], None, 0
    for i, level in enumerate(rms):
        if start is None:
            if level > on:
                start, quiet = i, 0
            continue
        quiet = quiet + 1 if level < off else 0
        if quiet * FRAME_S >= HANG_S or (i - start) * FRAME_S >= MAX_S:
            end = i - quiet + 1
            if (end - start) * FRAME_S >= MIN_S:
                out.append((max(0.0, start * FRAME_S - PRE_S), min(n, end + 5) * FRAME_S))
            start = None
    if start is not None and (n - start) * FRAME_S >= MIN_S:
        out.append((max(0.0, start * FRAME_S - PRE_S), n * FRAME_S))
    return out


def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    """PCM WAV (8/16/32-bit, any rate, mono or stereo) -> float32 mono in [-1, 1]."""
    with wave.open(io.BytesIO(data)) as w:
        rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[width]
    x = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    x = (x - 128) / 128 if width == 1 else x / float(np.iinfo(dtype).max)
    return x.reshape(-1, channels).mean(axis=1), rate


def to_wav(x: np.ndarray, rate: int, out_rate: int = 16000) -> bytes:
    """float32 mono -> 16-bit WAV at out_rate (what speech-to-text wants), low-passed before downsampling."""
    if rate != out_rate:
        if out_rate < rate:   # windowed-sinc low-pass at the new Nyquist, or high frequencies fold into speech
            cutoff, taps = 0.45 * out_rate / rate, 63
            k = np.arange(taps) - taps // 2
            h = np.sinc(2 * cutoff * k) * np.hamming(taps)
            x = np.convolve(x, h / h.sum(), mode="same")
        t = np.arange(int(len(x) * out_rate / rate)) * rate / out_rate
        x = np.interp(t, np.arange(len(x)), x)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(out_rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def split_recording(data: bytes) -> list[tuple[float, float, bytes]]:
    """A recorded net -> [(start_s, end_s, 16 kHz WAV clip)], ready for speech-to-text one by one."""
    x, rate = read_wav(data)
    return [(a, b, to_wav(x[int(a * rate):int(b * rate)], rate)) for a, b in segments(x, rate)]
