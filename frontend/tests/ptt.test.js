// Push-to-talk tests with a fake recogniser that replays the event orders Chrome produces.
//   node --test frontend/tests/          (no dependencies; Node 18+)
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createBrowserPtt, createRecorderPtt } from '../src/ptt.js'

// --- a fake webkitSpeechRecognition ---------------------------------------------------------------------------
function fakeSpeech() {
  const made = []
  class FakeRecognition {
    constructor() { this.results = []; this.started = false; this.ended = false; made.push(this) }
    start() { if (this.started) throw new Error('InvalidStateError: already started'); this.started = true }
    stop() { this.stopRequested = true }
    abort() { this.aborted = true }
    // Chrome sends the whole result list each time; resultIndex is the first entry that changed.
    say(text, { final = false, index = this.results.length - (this.results.at(-1)?.isFinal === false ? 1 : 0) } = {}) {
      const r = Object.assign([{ transcript: text }], { isFinal: final })
      this.results[index] = r
      this.onresult?.({ resultIndex: index, results: this.results })
    }
    error(code) { this.onerror?.({ error: code }) }
    end() { if (this.ended) return; this.ended = true; this.onend?.() }
  }
  return { Speech: FakeRecognition, made, last: () => made.at(-1) }
}

function setup() {
  const f = fakeSpeech(), sent = [], heard = [], listening = []
  const ptt = createBrowserPtt({ Speech: f.Speech, onSend: (t) => sent.push(t), onHeard: (h) => heard.push(h),
    onListening: (v) => listening.push(v) })
  return { ...f, ptt, sent, heard, listening }
}

// --- browser recogniser ---------------------------------------------------------------------------------------
test('the reported bug: refining guesses of one phrase send ONE report', () => {
  const s = setup()
  s.ptt.press()
  const rec = s.last()
  rec.say('Hello')                       // interim guesses, refined in place
  rec.say('Hello hello')
  rec.say('Hello hello')
  rec.say('Hello hello', { final: true })
  rec.say('Hello hello', { final: true, index: 0 })   // Chrome sometimes repeats the final
  s.ptt.release()
  assert.equal(s.sent.length, 0, 'nothing is sent before the recogniser has ended')
  rec.end()
  assert.deepEqual(s.sent, ['Hello hello'])
})

test('two sentences in one press are sent together, once', () => {
  const s = setup()
  s.ptt.press()
  const rec = s.last()
  rec.say('Zero this is alpha two', { final: true })
  rec.say('south of the church', { final: true })
  s.ptt.release(); rec.end()
  assert.deepEqual(s.sent, ['Zero this is alpha two south of the church'])
})

test('released before Chrome marks it final: the interim text is sent', () => {
  const s = setup()
  s.ptt.press(); const rec = s.last()
  rec.say('alpha one at the fountain')
  s.ptt.release(); rec.end()
  assert.deepEqual(s.sent, ['alpha one at the fountain'])
})

test('Chrome ends the session while the key is held: keep listening, keep the text, one report', () => {
  const s = setup()
  s.ptt.press(); const first = s.last()
  first.say('alpha one', { final: true })
  first.end()                            // Chrome gave up after silence; key still down
  assert.equal(s.made.length, 2, 'a new session was started')
  assert.equal(s.sent.length, 0)
  const second = s.last()
  second.say('at the fountain', { final: true })
  s.ptt.release(); second.end()
  assert.deepEqual(s.sent, ['alpha one at the fountain'])
  assert.deepEqual(s.listening, [true, false])
})

test('releasing twice (mouseup then mouseleave) sends once', () => {
  const s = setup()
  s.ptt.press(); const rec = s.last()
  rec.say('alpha one at the fountain', { final: true })
  s.ptt.release(); s.ptt.release(); rec.end(); rec.end()
  assert.deepEqual(s.sent, ['alpha one at the fountain'])
})

test('quick release then press: the first transmission is not lost', () => {
  const s = setup()
  s.ptt.press(); const a = s.last()
  a.say('alpha one at the fountain', { final: true })
  s.ptt.release()                        // a has not ended yet
  s.ptt.press(); const b = s.last()      // second press before a's onend
  a.end()
  b.say('bravo two at the church', { final: true })
  s.ptt.release(); b.end()
  assert.deepEqual(s.sent, ['alpha one at the fountain', 'bravo two at the church'])
})

test('a late result from a finished press never sends again', () => {
  const s = setup()
  s.ptt.press(); const a = s.last()
  a.say('alpha one at the fountain', { final: true })
  s.ptt.release(); a.end()
  a.say('alpha one at the fountain', { final: true, index: 0 })   // stray event after onend
  a.onend?.()                                                       // and a stray second onend
  assert.deepEqual(s.sent, ['alpha one at the fountain'])
})

test('no speech: nothing sent, operator told', () => {
  const s = setup()
  s.ptt.press(); const rec = s.last()
  rec.error('no-speech')
  s.ptt.release(); rec.end()
  assert.deepEqual(s.sent, [])
  assert.equal(s.heard.at(-1), 'heard nothing')
})

test('a real error (network) ends the press, keeps the error on screen, sends what was heard', () => {
  const s = setup()
  s.ptt.press(); const rec = s.last()
  rec.say('alpha one at', { final: true })
  rec.error('network')
  rec.end()                              // key still held, but the session failed: do not loop
  assert.equal(s.made.length, 1, 'no restart loop after a real error')
  assert.deepEqual(s.sent, ['alpha one at'])
  assert.equal(s.heard.at(-1), 'speech: network')
  assert.deepEqual(s.listening, [true, false])
})

test('start() throwing (microphone blocked) does not leave the button stuck', () => {
  const f = fakeSpeech()
  class Broken extends f.Speech { start() { throw new Error('not-allowed') } }
  const listening = [], sent = []
  const ptt = createBrowserPtt({ Speech: Broken, onSend: (t) => sent.push(t), onListening: (v) => listening.push(v) })
  ptt.press()
  assert.equal(ptt.busy, false)
  assert.deepEqual(listening, [true, false])
  assert.deepEqual(sent, [])
})

// --- server speech-to-text (record, then send the clip) -------------------------------------------------------
function recorderSetup() {
  const log = []
  let resolveOpen
  const ptt = createRecorderPtt({
    open: () => new Promise((r) => { resolveOpen = () => { log.push('open'); r({ id: log.length }) } }),
    close: async (h) => log.push('close'),
    discard: async (h) => log.push('discard'),
  })
  return { ptt, log, finishOpening: () => resolveOpen() }
}

test('recorder: normal press and release sends the clip once', async () => {
  const s = recorderSetup()
  const pressing = s.ptt.press(); s.finishOpening(); await pressing
  await s.ptt.release(); await s.ptt.release()
  assert.deepEqual(s.log, ['open', 'close'])
})

test('recorder: release while the microphone is still opening closes it, sends nothing', async () => {
  const s = recorderSetup()
  const pressing = s.ptt.press()
  await s.ptt.release()                  // quick tap, or the permission prompt is still up
  s.finishOpening(); await pressing
  assert.deepEqual(s.log, ['open', 'discard'], 'the microphone must not stay on')
})
