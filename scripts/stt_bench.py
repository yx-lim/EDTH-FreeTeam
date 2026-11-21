"""Speech-to-text on radio-quality Ukrainian and Russian: every provider, clean and degraded audio, scored.

    python -m scripts.stt_bench                                  # data/demo_net_uk.jsonl, all providers
    python -m scripts.stt_bench --script data/zones/irpin/demo_net.jsonl
    python -m scripts.stt_bench --providers elevenlabs whisper --conditions clean radio5

Each line of the net script ({"t", "text"}) is spoken by a macOS voice (Lesya for Ukrainian, Milena for Russian),
then degraded like a tactical radio: band-pass 300-3000 Hz, down to 8 kHz and back, noise at a set signal-to-noise
ratio, light clipping and a squelch burst at the start. Seeded, so every run hears the same audio.

These are synthetic voices with simulated degradation, not real radio recordings: a real handset adds accents,
shouting, wind and overlapping speech. Treat the numbers as a ranking of providers, not field accuracy.

Scores, per provider and condition:
  WER        word error rate on folded text (Ukrainian/Russian spellings folded together, numbers as digits)
  callsign   the transmitting station heard right (after "я", or the lone callsign), via lang_uk.callsign
  places     codenames and aliases (data/codenames.json) in the reference that are also in the transcript
  numbers    numbers in the reference that come out as the same number (word or digit)
  ms         median transcription time

Audio and transcripts are cached in the session scratchpad (or --out), so a re-run costs no API calls.
Gemini's free tier allows 15 requests a minute: its calls are spaced 6 s apart and a 429 waits once and retries.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import re
import statistics
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv(".env")

from backend import lang_uk, stt  # noqa: E402  (after load_dotenv so keys are visible)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCRIPT = ROOT / "data" / "demo_net_uk.jsonl"
DEFAULT_OUT = Path("/private/tmp/claude-501/-Users-yitxuenglim-Desktop-edth-voice-to-map/"
                  "eb4c4582-2837-447f-b45e-2a3240be74fb/scratchpad/stt_bench")
CODENAMES = ROOT / "data" / "codenames.json"
RATE = 16000
CONDITIONS = {"clean": None, "radio15": 15.0, "radio5": 5.0}   # name -> SNR in dB (None: untouched)
RUSSIAN_WORDS = {"башня", "прием", "приём", "между", "противник", "трое", "метров", "около", "изменений"}
GEMINI_GAP_S = 6.0


# --- audio --------------------------------------------------------------------------------------------------------
def is_russian(text: str) -> bool:
    t = text.lower()
    return bool(re.search(r"[ыэёъ]", t)) or bool(set(re.findall(r"\w+", t)) & RUSSIAN_WORDS)


def synth(text: str, path: Path) -> None:
    if path.exists():
        return
    voice = "Milena" if is_russian(text) else "Lesya"
    subprocess.run(["say", "-v", voice, "-o", str(path), "--data-format=LEI16@16000", text], check=True)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1 and w.getsampwidth() == 2, path
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64) / 32768


def to_wav(x: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def band(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    spec[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(spec, len(x))


def pink(n: int, rng: np.random.Generator) -> np.ndarray:
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / RATE)
    spec[1:] /= np.sqrt(f[1:])
    spec[0] = 0
    p = np.fft.irfft(spec, n)
    return p / (np.std(p) or 1)


def radio(x: np.ndarray, snr_db: float, seed: int, squelch: bool = True) -> np.ndarray:
    """A tactical-radio version of a clean clip: narrow band, 8 kHz, noise at snr_db, clipped, squelch burst."""
    rng = np.random.default_rng(seed)
    y = band(x, 300, 3000)
    y = y[::2]                                                     # 8 kHz (already below 4 kHz, no aliasing)
    y = np.interp(np.arange(len(x)) / 2, np.arange(len(y)), y)     # back to 16 kHz for the providers
    speech = np.sqrt(np.mean(y[np.abs(y) > 0.02 * np.max(np.abs(y))] ** 2))   # loudness of the speech, not silence
    noise = 0.5 * rng.standard_normal(len(y)) + 0.5 * pink(len(y), rng)
    noise = band(noise, 200, 3500)
    noise *= speech / (np.std(noise) or 1) / (10 ** (snr_db / 20))
    y = y + noise
    peak = np.max(np.abs(y)) or 1
    y = np.clip(y / peak, -0.8, 0.8) / 0.8 * 0.9                    # light clipping, then normalise
    if squelch:
        burst = band(rng.standard_normal(int(0.15 * RATE)), 300, 3000)
        burst *= 0.5 / (np.max(np.abs(burst)) or 1)
        y = np.concatenate([burst, y, burst[: int(0.08 * RATE)]])
    return y


# --- scoring ------------------------------------------------------------------------------------------------------
def words(text: str) -> list[str]:
    """Folded words; runs of number words or digits become one number ("двісті п'ятдесят" / "250" -> "250")."""
    toks = re.sub(r"[^\w\s]|_", " ", lang_uk.fold(text)).split()
    out, run = [], []
    for w in toks + [""]:
        if w and (w.isdigit() or w in lang_uk._UNITS):
            run.append(w)
            continue
        if run:
            n = lang_uk.number(" ".join(run))
            out.append(str(int(n)) if n is not None and float(n).is_integer() else " ".join(run))
            run = []
        if w:
            out.append(w)
    return out


def wer(ref: list[str], hyp: list[str]) -> tuple[int, int]:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[len(hyp)], len(ref)


def station(text: str) -> str | None:
    to, frm, single, _, _ = lang_uk.header(text)
    s = frm or single
    return lang_uk.callsign(s) if s and s != "all stations" else None


def place_index() -> dict[str, str]:
    names = {}
    for c in json.loads(CODENAMES.read_text(encoding="utf-8"))["codenames"]:
        names.update({n: c["name"] for n in [c["name"], *c.get("aliases", [])]})
    return lang_uk.index_of(names)


def places_in(text: str, index: dict[str, str]) -> set[str]:
    """Every codename spoken in the text (lookup returns the longest one; remove it and look again)."""
    found, rest = set(), text
    for _ in range(4):
        hit = lang_uk.lookup(rest, index)
        if not hit:
            break
        found.add(hit)
        stems = [k for k, v in index.items() if v == hit]
        rest = " ".join(w for w in lang_uk.key(rest) if not any(lang_uk.same_word(w, s) for k in stems for s in k.split()))
    return found


def numbers_in(text: str) -> list[str]:
    return [w for w in words(text) if w.isdigit()]


# --- transcription ------------------------------------------------------------------------------------------------
class Runner:
    def __init__(self, out: Path):
        self.cache_path = out / "transcripts.json"
        self.cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}
        self.last_gemini = 0.0
        self.calls: dict[str, int] = {}

    def save(self) -> None:
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1))

    async def transcribe(self, provider: str, audio: bytes, vocab: list[str], lang: str, key: str) -> dict:
        if key in self.cache:
            return self.cache[key]
        stt.choose(provider)
        for attempt in range(2):
            if provider == "gemini":
                wait = self.last_gemini + GEMINI_GAP_S - time.time()
                if wait > 0:
                    await asyncio.sleep(wait)
                self.last_gemini = time.time()
            self.calls[provider] = self.calls.get(provider, 0) + 1
            try:
                got = await stt.transcribe(audio, vocab, lang)
                out = {"text": got["text"], "ms": got["stt_ms"]}
                break
            except Exception as err:  # noqa: BLE001 - record it, keep the benchmark going
                resp = getattr(err, "response", None)
                if resp is not None and resp.status_code == 429 and attempt == 0:
                    m = re.search(r'"retryDelay":\s*"(\d+)', resp.text)
                    delay = int(m.group(1)) + 1 if m else 60
                    print(f"  {provider}: 429, waiting {delay} s")
                    await asyncio.sleep(delay)
                    continue
                out = {"text": "", "ms": None, "error": f"{type(err).__name__}: {str(err)[:120]}"}
                break
        self.cache[key] = out
        self.save()
        return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    ap.add_argument("--providers", nargs="*", help="default: every provider available (stt.available())")
    ap.add_argument("--conditions", nargs="*", default=list(CONDITIONS), choices=list(CONDITIONS))
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--no-squelch", action="store_true")
    ap.add_argument("--show", action="store_true", help="print every transcript")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    lines = [json.loads(s) for s in args.script.read_text(encoding="utf-8").splitlines() if s.strip()]
    providers = args.providers or stt.available()
    codes = json.loads(CODENAMES.read_text(encoding="utf-8"))["codenames"]
    vocab = list(dict.fromkeys(lang_uk.vocabulary() + [n for c in codes for n in [c["name"], *c.get("aliases", [])]]))
    index = place_index()
    runner = Runner(args.out)
    tag = hashlib.sha1(str(args.script.resolve()).encode()).hexdigest()[:8]

    clips = []
    for i, line in enumerate(lines):
        text = line["text"]
        path = args.out / f"{tag}_{i:02d}.wav"
        synth(text, path)
        clips.append((i, text, "ru" if is_russian(text) else "uk", read_wav(path)))

    rows, detail = [], []
    for provider in providers:
        for cond in args.conditions:
            snr = CONDITIONS[cond]
            errs = total = cs_ok = cs_n = pl_ok = pl_n = num_ok = num_n = failed = 0
            ms = []
            for i, text, lang, clean in clips:
                audio = to_wav(clean if snr is None else radio(clean, snr, seed=1000 + i, squelch=not args.no_squelch))
                key = f"{tag}|{provider}|{cond}|{'nosq' if args.no_squelch else 'sq'}|{i}|{hashlib.sha1(text.encode()).hexdigest()[:8]}"
                got = await runner.transcribe(provider, audio, vocab, lang, key)
                hyp = got["text"]
                failed += "error" in got
                e, n = wer(words(text), words(hyp))
                errs, total = errs + e, total + n
                ref_cs = station(text)
                if ref_cs:
                    cs_n += 1
                    cs_ok += station(hyp) == ref_cs
                ref_pl = places_in(text, index)
                pl_n += len(ref_pl)
                pl_ok += len(ref_pl & places_in(hyp, index))
                hyp_nums = numbers_in(hyp)
                for x in numbers_in(text):
                    num_n += 1
                    if x in hyp_nums:
                        num_ok += 1
                        hyp_nums.remove(x)
                if got.get("ms"):
                    ms.append(got["ms"])
                detail.append({"provider": provider, "condition": cond, "lang": lang, "ref": text, "hyp": hyp,
                               "wer": round(e / max(n, 1), 3), "error": got.get("error")})
                if args.show:
                    print(f"[{provider}/{cond}] {text}\n    -> {hyp}")
            rows.append({"provider": provider, "condition": cond, "clips": len(clips), "failed": failed,
                         "wer": round(errs / max(total, 1), 3), "callsign": f"{cs_ok}/{cs_n}",
                         "places": f"{pl_ok}/{pl_n}", "numbers": f"{num_ok}/{num_n}",
                         "median_ms": round(statistics.median(ms)) if ms else None})

    print(f"\n{args.script.name}: {len(clips)} clips ({sum(c[2] == 'ru' for c in clips)} Russian), "
          f"radio = 300-3000 Hz, 8 kHz, noise at the SNR shown, clipping{'' if args.no_squelch else ', squelch'}\n")
    print("| provider | audio | WER | callsign | places | numbers | median ms | failed |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['provider']} | {r['condition']} | {r['wer'] * 100:.0f}% | {r['callsign']} | {r['places']} | "
              f"{r['numbers']} | {r['median_ms']} | {r['failed']} |")
    # WER by language, to see whether Russian lines fare worse
    print("\nWER by language (all conditions):")
    for provider in providers:
        for lang in ("uk", "ru"):
            ds = [d for d in detail if d["provider"] == provider and d["lang"] == lang]
            if ds:
                print(f"  {provider:10} {lang}: {statistics.mean(d['wer'] for d in ds) * 100:.0f}% mean per clip")
    print(f"\nAPI calls this run (cached clips cost none): {runner.calls or 'none'}")
    (args.out / "results.json").write_text(json.dumps({"script": str(args.script), "rows": rows, "detail": detail,
                                                       "calls": runner.calls}, ensure_ascii=False, indent=1))
    print(f"results -> {args.out / 'results.json'}")


if __name__ == "__main__":
    asyncio.run(main())
