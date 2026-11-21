<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Check, Mic, Radio, Send, Square, Upload, Volume2 } from 'lucide-vue-next'
import { playRadioTone } from '../tactical.js'

const callsign = ref('alpha 1')
const lang = ref('en')
const connected = ref(false)
const recording = ref(false)
const processing = ref(false)
const statusMsg = ref('READY · HOLD BUTTON TO TRANSMIT TO C2 MAP')
const lastTranscript = ref('')
const lastResult = ref(null)
const textMsg = ref('')
const elapsed = ref(0)

let ws = null
let stream = null
let recorder = null
let chunks = []
let timer = null
let startedAt = 0

const PRESETS = computed(() =>
  ['uk', 'ru'].includes(lang.value)
    ? [
        'Вежа, я Сокіл, на Ромашці, прийом',
        'Вежа, я Граніт, бачу 3 ворожих танки біля церкви, прийом',
        'Вежа, я Лис, ждун біля Сараю, 50 метрів на захід, прийом',
      ]
    : [
        'Zero, this is Alpha two, south of Saint-Sulpice church, over',
        'Bravo one, contact, 2 enemy tanks at the tower, over',
        'Alpha one, 100 meters east of the Eiffel Tower, over',
      ],
)

function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2)
  const v = new DataView(buf)
  const w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)))
  w(0, 'RIFF')
  v.setUint32(4, 36 + samples.length * 2, true)
  w(8, 'WAVE')
  w(12, 'fmt ')
  v.setUint32(16, 16, true)
  v.setUint16(20, 1, true)
  v.setUint16(22, 1, true)
  v.setUint32(24, rate, true)
  v.setUint32(28, rate * 2, true)
  v.setUint16(32, 2, true)
  v.setUint16(34, 16, true)
  w(36, 'data')
  v.setUint32(40, samples.length * 2, true)
  samples.forEach((s, i) => v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true))
  return buf
}

function sendWs(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj))
  }
}

function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/api/ws`)
  ws.onopen = () => {
    connected.value = true
    sendWs({ type: 'handset_hello', callsign: callsign.value })
  }
  ws.onclose = () => {
    connected.value = false
    window.setTimeout(connectWs, 2000)
  }
}

async function decodeAndUpload(blob) {
  processing.value = true
  statusMsg.value = 'UPLOADING & TRANSCRIBING...'
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext
    const ctx = new AudioCtx()
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer())
    ctx.close()
    const off = new OfflineAudioContext(1, Math.ceil(decoded.duration * 16000), 16000)
    const src = off.createBufferSource()
    src.buffer = decoded
    src.connect(off.destination)
    src.start()
    const wav = encodeWav((await off.startRendering()).getChannelData(0), 16000)

    const r = await fetch(`/api/audio?callsign=${encodeURIComponent(callsign.value)}&lang=${lang.value}`, {
      method: 'POST',
      headers: { 'Content-Type': 'audio/wav' },
      body: wav,
    })
    const out = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(out.detail || `Server error (${r.status})`)
    lastTranscript.value = out.transcript || '(empty)'
    lastResult.value = out.events?.[0] || null
    statusMsg.value = out.events?.[0]?.ok
      ? `PLOTTED ON C2: ${out.events[0].anchor} · ${out.events[0].mgrs || ''}`
      : `TRANSMITTED: "${out.transcript || 'no speech'}"`
    playRadioTone('ack')
  } catch (err) {
    statusMsg.value = `ERROR: ${err.message}`
  } finally {
    processing.value = false
    sendWs({ type: 'handset_ptt', active: false, callsign: callsign.value })
  }
}

async function startPtt() {
  if (recording.value || processing.value) return
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    statusMsg.value = 'Live mic needs HTTPS — use "RECORD VOICE CLIP" button below!'
    return
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    chunks = []
    recorder = new MediaRecorder(stream)
    recorder.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data)
    }
    recorder.onstop = async () => {
      window.clearInterval(timer)
      stream?.getTracks().forEach((t) => t.stop())
      recording.value = false
      const blob = new Blob(chunks, { type: recorder?.mimeType || 'audio/webm' })
      if (blob.size > 400) await decodeAndUpload(blob)
      else statusMsg.value = 'Too short — hold button while speaking.'
    }
    playRadioTone('ptt_start')
    recorder.start()
    recording.value = true
    startedAt = Date.now()
    elapsed.value = 0
    statusMsg.value = 'TRANSMITTING LIVE TO C2...'
    sendWs({ type: 'handset_ptt', active: true, callsign: callsign.value })
    timer = window.setInterval(() => {
      elapsed.value = Math.floor((Date.now() - startedAt) / 1000)
    }, 250)
  } catch (err) {
    statusMsg.value = `Mic blocked (${err.message}) — use RECORD VOICE CLIP below.`
  }
}

function stopPtt() {
  if (!recording.value) return
  playRadioTone('ptt_stop')
  if (recorder && recorder.state === 'recording') recorder.stop()
}

function togglePtt() {
  if (recording.value) stopPtt()
  else startPtt()
}

async function onCaptureFile(ev) {
  const f = ev.target.files?.[0]
  ev.target.value = ''
  if (!f) return
  await decodeAndUpload(f)
}

async function sendText(txt = textMsg.value) {
  const body = txt.trim()
  if (!body || processing.value) return
  textMsg.value = ''
  processing.value = true
  statusMsg.value = 'TRANSMITTING TO C2...'
  try {
    const r = await fetch('/api/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: body, callsign: callsign.value }),
    })
    const out = await r.json().catch(() => ({}))
    lastTranscript.value = body
    lastResult.value = out.events?.[0] || null
    statusMsg.value = out.events?.[0]?.ok
      ? `PLOTTED ON C2: ${out.events[0].anchor} · ${out.events[0].mgrs || ''}`
      : 'REPORT SENT TO C2'
    playRadioTone('ack')
  } catch (err) {
    statusMsg.value = `ERROR: ${err.message}`
  } finally {
    processing.value = false
  }
}

onMounted(connectWs)
onUnmounted(() => {
  window.clearInterval(timer)
  stream?.getTracks().forEach((t) => t.stop())
  ws?.close()
})
</script>

<template>
  <main class="handset-shell">
    <header class="handset-header">
      <div class="handset-title">
        <Radio :size="18" class="accent-gold" />
        <div>
          <p class="eyebrow">FIELD RADIO HANDSET</p>
          <h1>VOICE-TO-MAP PTT</h1>
        </div>
      </div>
      <span class="handset-link mono" :class="{ 'is-on': connected }">
        <i></i>{{ connected ? 'C2 LINKED' : 'LINKING...' }}
      </span>
    </header>

    <section class="handset-controls">
      <label>
        <span class="mono">CALLSIGN</span>
        <select v-model="callsign" @change="sendWs({ type: 'handset_hello', callsign })">
          <option value="alpha 1">Alpha 1</option>
          <option value="alpha 2">Alpha 2</option>
          <option value="bravo 1">Bravo 1</option>
          <option value="charlie 1">Charlie 1</option>
          <option value="сокіл">Сокіл (UK)</option>
          <option value="граніт">Граніт (UK)</option>
        </select>
      </label>

      <label>
        <span class="mono">LANGUAGE</span>
        <select v-model="lang">
          <option value="en">EN (English)</option>
          <option value="uk">UK (Українська)</option>
          <option value="fr">FR (Français)</option>
          <option value="ru">RU (Русский)</option>
          <option value="auto">AUTO</option>
        </select>
      </label>
    </section>

    <section class="handset-ptt-stage">
      <button
        type="button"
        class="handset-ptt-btn"
        :class="{ 'is-recording': recording, 'is-processing': processing }"
        :disabled="processing"
        @click="togglePtt"
      >
        <span class="handset-ptt-ring"></span>
        <Square v-if="recording" :size="44" fill="currentColor" />
        <Mic v-else :size="48" />
        <strong>
          {{ processing ? 'PROCESSING...' : recording ? `STOP TX · ${elapsed}s` : 'TAP TO TALK' }}
        </strong>
        <small class="mono">
          {{ recording ? 'Tap again to send to C2 map' : 'Streams live voice to C2 Tactical Map' }}
        </small>
      </button>

      <label class="handset-capture-fallback mono">
        <Upload :size="15" />
        <span>OR RECORD / UPLOAD VOICE CLIP (ANY BROWSER)</span>
        <input type="file" accept="audio/*" capture="microphone" @change="onCaptureFile" />
      </label>
    </section>

    <section class="handset-status-card mono">
      <div class="handset-status-line">
        <Volume2 :size="14" class="accent-cyan" />
        <span>{{ statusMsg }}</span>
      </div>
      <div v-if="lastTranscript" class="handset-tx-echo">“{{ lastTranscript }}”</div>
      <div v-if="lastResult?.ok" class="handset-fix-pill">
        <Check :size="13" />
        <span>{{ lastResult.anchor }} · {{ lastResult.mgrs }}</span>
      </div>
    </section>

    <form class="radio-text-form" @submit.prevent="sendText()">
      <input v-model="textMsg" type="text" placeholder="Type tactical report..." />
      <button type="submit" class="radio-send-btn" :disabled="!textMsg.trim() || processing">
        <Send :size="14" />
        <span>TX</span>
      </button>
    </form>

    <div class="quick-presets">
      <button
        v-for="p in PRESETS"
        :key="p"
        type="button"
        class="preset-chip"
        :disabled="processing"
        @click="sendText(p)"
      >
        {{ p }}
      </button>
    </div>
  </main>
</template>
