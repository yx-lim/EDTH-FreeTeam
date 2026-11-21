"""Synthesise data/demo_net.jsonl into a radio-net recording (macOS only: uses the `say` voices).

Each station gets its own voice; the audio is band-limited to 300-3000 Hz like a handheld radio, with hiss while
the channel is keyed, a squelch tail after each transmission and near silence in between. Use it to try radio-net
mode without a radio: play it in the UI ("Play a recording") or POST it to /net/recording.

    python -m scripts.make_demo_net            -> data/demo_net.wav
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from backend.geo import Gazetteer
from backend.net import Net
from backend.tracker import Tracker
from backend.vad import read_wav, to_wav

ROOT = Path(__file__).resolve().parent.parent
RATE = 16000
VOICES = {"zero": "Daniel", "alpha 1": "Reed", "bravo 2": "Flo", "charlie 1": "Rocko", "delta 1": "Sandy",
          None: "Shelley"}
FRENCH = {"zero": "Thomas", "alpha 2": "Jacques", None: "Thomas"}


def bandpass(x: np.ndarray, lo: float = 300, hi: float = 3000, taps: int = 101) -> np.ndarray:
    k = np.arange(taps) - taps // 2
    h = (2 * hi / RATE) * np.sinc(2 * hi / RATE * k) - (2 * lo / RATE) * np.sinc(2 * lo / RATE * k)
    return np.convolve(x, h * np.hamming(taps), mode="same")


def speak(text: str, voice: str) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "line.wav"
        subprocess.run(["say", "-v", voice, "-o", str(out), "--file-format=WAVE", f"--data-format=LEI16@{RATE}", text],
                       check=True)
        x, rate = read_wav(out.read_bytes())
    assert rate == RATE
    return x


def radio(x: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    x = bandpass(x)
    x = np.tanh(3 * x / (np.abs(x).max() + 1e-9)) * 0.5            # handheld radios compress hard
    keyed = np.concatenate([np.zeros(int(0.08 * RATE)), x, np.zeros(int(0.05 * RATE))])
    keyed += rng.normal(0, 0.012, len(keyed))                       # carrier hiss while transmitting
    tail = bandpass(rng.normal(0, 0.08, int(0.12 * RATE)))          # squelch tail
    return np.concatenate([keyed, tail])


def main(dest: Path = ROOT / "data" / "demo_net.wav") -> None:
    if sys.platform != "darwin":
        sys.exit("needs macOS `say`")
    lines = [json.loads(s) for s in (ROOT / "data" / "demo_net.jsonl").read_text().splitlines()]
    net = Net(Tracker(Gazetteer()))
    speakers = []
    for d in lines:   # who says each line decides the voice
        speakers.append(asyncio.run(net.hear(d["text"], now=d["t"]))["transmissions"][0]["from"])
    rng = np.random.default_rng(7)
    clips, cursor = [], 0.0
    for d, who in zip(lines, speakers):
        french = any(w in d["text"] for w in ("Zéro", "deux", "Reçu"))
        voice = (FRENCH if french else VOICES).get(who) or (FRENCH if french else VOICES)[None]
        clip = radio(speak(d["text"], voice), rng)
        start = max(float(d["t"]), cursor + 1.2)                     # never overlap: a net is half-duplex
        clips.append((start, clip))
        cursor = start + len(clip) / RATE
        print(f"{start:6.1f}s  {voice:8} {d['text']}")
    out = rng.normal(0, 0.0005, int((cursor + 1.0) * RATE))          # squelched channel: near silence
    for start, clip in clips:
        i = int(start * RATE)
        out[i:i + len(clip)] += clip
    dest.write_bytes(to_wav(out.astype(np.float32), RATE))
    (dest.with_suffix(".times.json")).write_text(json.dumps([[s, s + len(c) / RATE] for s, c in clips]))
    print(f"wrote {dest} ({cursor:.0f} s, {len(clips)} transmissions)")


if __name__ == "__main__":
    main()
