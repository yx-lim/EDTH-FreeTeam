"""Voice-activity detection on synthetic radio audio: speech-like bursts in hiss, clicks, a long transmission."""
import json
from pathlib import Path

import numpy as np
import pytest

from backend.vad import MAX_S, read_wav, segments, split_recording, to_wav

RATE = 16000
rng = np.random.default_rng(1)


def burst(seconds, level=0.2):
    """Noise shaped by a 4 Hz syllable envelope, with short gaps between words (as speech has)."""
    t = np.arange(int(seconds * RATE)) / RATE
    env = np.clip(np.sin(2 * np.pi * 4 * t), 0.15, 1)
    return rng.normal(0, level, len(t)) * env


def channel(parts):
    """parts: list of (start_s, samples). Hiss at -50 dB underneath, like an open squelch."""
    end = max(s + len(x) / RATE for s, x in parts) + 1.5
    out = rng.normal(0, 0.003, int(end * RATE))
    for s, x in parts:
        out[int(s * RATE):int(s * RATE) + len(x)] += x
    return out.astype(np.float32)


def test_transmissions_are_found_with_tight_boundaries():
    truth = [(1.0, 3.5), (5.0, 9.0), (10.5, 12.0)]
    segs = segments(channel([(a, burst(b - a)) for a, b in truth]), RATE)
    assert len(segs) == 3
    for (a, b), (ta, tb) in zip(segs, truth):
        assert ta - 0.4 <= a <= ta + 0.05 and tb - 0.1 <= b <= tb + 0.3


def test_clicks_and_key_ups_are_ignored():
    click = rng.normal(0, 0.5, int(0.08 * RATE))
    assert segments(channel([(1.0, click), (3.0, click)]), RATE) == []


def test_quiet_station_is_still_heard():
    segs = segments(channel([(1.0, burst(2.0, level=0.03))]), RATE)
    assert len(segs) == 1


def test_long_transmission_is_cut_for_transcription():
    segs = segments(channel([(0.5, burst(MAX_S + 10))]), RATE)
    assert len(segs) == 2 and segs[0][1] - segs[0][0] <= MAX_S + 0.5


def test_wav_round_trip_and_resampling():
    x = channel([(0.5, burst(1.0))])
    y, rate = read_wav(to_wav(np.repeat(x, 3), RATE * 3))     # 48 kHz in, 16 kHz out
    assert rate == RATE and abs(len(y) - len(x)) < 10
    clips = split_recording(to_wav(x, RATE))
    assert len(clips) == 1 and clips[0][2][:4] == b"RIFF"


DEMO = Path(__file__).resolve().parent.parent / "data" / "demo_net.wav"


@pytest.mark.skipif(not DEMO.exists(), reason="run `python -m scripts.make_demo_net` (macOS) to create it")
def test_synthetic_radio_net_recording():
    x, rate = read_wav(DEMO.read_bytes())
    truth = json.loads(DEMO.with_suffix(".times.json").read_text())
    segs = segments(x, rate)
    assert len(segs) == len(truth)
    assert all(abs(a - ta) < 0.4 and abs(b - tb) < 0.4 for (a, b), (ta, tb) in zip(segs, truth))
