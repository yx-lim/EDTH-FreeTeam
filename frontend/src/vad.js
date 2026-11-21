// Live voice-activity detection: cut a continuous channel into transmissions. Same thresholds as backend/vad.py,
// but the noise floor is learned as audio arrives instead of from the whole file.
const START_K = 3, STOP_K = 2, MIN_LEVEL = 0.004
const HANG_S = 0.7, PRE_S = 0.25, MIN_S = 0.35, MAX_S = 30, WARMUP_S = 0.5, TAIL_S = 0.1

export function createVad(rate, { level = () => {}, segment }) {
  let floor = 1, heard = 0, active = false
  let pre = [], preLen = 0, chunks = [], len = 0, lead = 0, quiet = 0, startedAt = 0, levels = []

  function emit() {
    const voiced = (len - lead) / rate - quiet
    if (voiced < MIN_S) return
    const keep = Math.min(len, len - Math.floor(quiet * rate) + Math.floor(TAIL_S * rate))
    const out = new Float32Array(keep)
    let o = 0
    for (const c of chunks) { if (o >= keep) break; out.set(c.subarray(0, keep - o), o); o += c.length }
    segment(out, startedAt, keep / rate)
  }

  return {
    push(input) {
      const x = Float32Array.from(input)            // the browser reuses its buffer
      let sum = 0
      for (let i = 0; i < x.length; i++) sum += x[i] * x[i]
      const rms = Math.sqrt(sum / x.length), dt = x.length / rate
      heard += dt
      if (!active) {
        // Falls fast, rises slowly: a long burst of speech must not become the new floor.
        floor = heard <= WARMUP_S ? Math.min(floor, rms) : rms < floor ? (rms + floor) / 2 : floor + (rms - floor) * 0.02
        pre.push(x); preLen += x.length
        while (pre.length > 1 && preLen - pre[0].length >= PRE_S * rate) preLen -= pre.shift().length
        if (heard > WARMUP_S && rms > Math.max(floor * START_K, MIN_LEVEL)) {
          active = true; chunks = pre; len = lead = preLen; pre = []; preLen = 0; quiet = 0; levels = []
          startedAt = Date.now() / 1000 - len / rate
        }
      } else {
        chunks.push(x); len += x.length; levels.push(rms)
        quiet = rms < Math.max(floor * STOP_K, MIN_LEVEL * 0.6) ? quiet + dt : 0
        if (quiet >= HANG_S || len / rate >= MAX_S) {
          emit()
          // Cut at the limit: the floor was probably wrong (the hiss got louder). Relearn it from this stretch.
          if (quiet < HANG_S) floor = [...levels].sort((a, b) => a - b)[Math.floor(levels.length * 0.2)] ?? floor
          active = false; chunks = []; len = 0
        }
      }
      level(rms, active, floor)
    },
    flush() { if (active) { emit(); active = false; chunks = []; len = 0 } },
  }
}
