// Push-to-talk state machines, free of Vue and of real browser objects so tests can drive them with fakes
// (frontend/tests/ptt.test.js). One press = one transmission = at most one report.

// Browser speech recognition (Chrome's webkitSpeechRecognition).
//   Chrome fires onresult many times while it refines a guess: only the text standing when the press ends is sent.
//   Chrome also ends a session by itself (silence, network) while the key is still down: start a new session and
//   keep what was heard, so the press ends only when the key or button is released.
//   A release followed quickly by a new press must not lose the first transmission, and nothing may be sent twice.
export function createBrowserPtt({ Speech, lang = () => 'en-GB', onSend, onHeard = () => {}, onListening = () => {} }) {
  let current = null   // the press being held (or finishing); only it updates the live text

  function press() {
    const p = { held: true, pieces: [], failed: false, done: false, rec: null }
    current = p
    onListening(true)
    session(p)
  }

  function session(p) {
    const rec = new Speech(), finals = []
    let interim = ''
    rec.lang = lang()
    rec.continuous = true          // a pause mid-sentence must not end the transmission
    rec.interimResults = true      // live text; sent only if the key is released before it turns final
    const text = () => [...p.pieces, ...finals.filter(Boolean), interim.trim()].filter(Boolean).join(' ').trim()
    rec.onresult = (r) => {
      if (p.rec !== rec) return
      interim = ''
      for (let i = r.resultIndex; i < r.results.length; i++) {
        if (r.results[i].isFinal) finals[i] = r.results[i][0].transcript.trim()
        else interim += r.results[i][0].transcript
      }
      if (current === p) onHeard(`hearing: “${text()}”`)
    }
    rec.onerror = (e) => {
      if (p.rec !== rec || e.error === 'aborted' || e.error === 'no-speech') return
      p.failed = true
      if (current === p) onHeard(`speech: ${e.error}`)
    }
    rec.onend = () => {            // after stop(), with every final result delivered
      if (p.rec !== rec || p.done) return
      const t = text()
      if (p.held && !p.failed) { p.pieces = t ? [t] : []; session(p); return }   // ended by Chrome, key still down
      p.done = true
      p.rec = null
      if (current === p) { current = null; onListening(false) }
      if (t) onSend(t)
      else if (!p.failed && current === null) onHeard('heard nothing')        // keep an error on screen
    }
    p.rec = rec
    try { rec.start() } catch (err) { p.failed = true; p.held = false; rec.onend() ; onHeard(`speech: ${err.message}`) }
  }

  function release() {
    const p = current
    if (!p || !p.held) return
    p.held = false
    p.rec?.stop()                  // onend sends the transmission
  }

  return { press, release, get busy() { return current !== null } }
}

// Server speech-to-text: record while held, send the clip on release.
//   Opening the microphone is slow (and asks for permission the first time). A release that arrives while it is
//   still opening must close it again, or the microphone stays on and the next press leaks a second stream.
export function createRecorderPtt({ open, close, discard, onListening = () => {} }) {
  let current = null

  async function press() {
    const p = { held: true, handle: null }
    current = p
    onListening(true)
    try {
      p.handle = await open()
    } catch (err) {
      if (current === p) { current = null; onListening(false) }
      throw err
    }
    if (!p.held) { await discard(p.handle); return }   // released while the microphone was opening
  }

  async function release() {
    const p = current
    if (!p || !p.held) return
    p.held = false
    current = null
    onListening(false)
    if (p.handle) await close(p.handle)               // else press() discards it once open() returns
  }

  return { press, release }
}
