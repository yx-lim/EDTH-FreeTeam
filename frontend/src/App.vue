<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import maplibregl from 'maplibre-gl'
import ms from 'milsymbol'
import { createVad } from './vad.js'
import { createBrowserPtt, createRecorderPtt } from './ptt.js'
import { gridLines, mgrsAt } from './grid.js'

// Own units only, so cool colours: on a NATO map red means hostile and yellow means unknown.
const COLOURS = ['#60a5fa', '#22d3ee', '#a78bfa', '#34d399', '#93c5fd', '#c084fc']
const WALK_MPS = 1.5          // uncertainty grows at walking pace while a unit is silent
const STALE_CAP_M = 1500
const STALE_S = 300           // silent this long: the unit's frame turns dashed ("suspected" in APP-6)
// APP-6 / MIL-STD-2525C friendly infantry: P = present (solid frame), A = anticipated/suspected (dashed frame).
const SIDC = { solid: 'SFGPUCI--------', dashed: 'SFGAUCI--------' }
const BASEMAPS = {
  // OpenStreetMap with its brightness inverted and colour drained in the raster paint (no API key, unlike CARTO's dark).
  dark: { label: 'Dark', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], attribution: '© OpenStreetMap contributors',
    maxzoom: 19, grid: '#cbd5e1', halo: '#0b0d10',
    paint: { 'raster-brightness-min': 0.92, 'raster-brightness-max': 0.06, 'raster-saturation': -0.85, 'raster-hue-rotate': 180,
      'raster-contrast': 0.1 } },
  satellite: { label: 'Satellite', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
    attribution: 'Imagery © Esri, Maxar, Earthstar Geographics', maxzoom: 19, grid: '#ffffff', halo: '#000000',
    paint: { 'raster-brightness-max': 0.8 } },
  topo: { label: 'Topo', tiles: ['a', 'b', 'c'].map((s) => `https://${s}.tile.opentopomap.org/{z}/{x}/{y}.png`),
    attribution: 'Map data © OpenStreetMap contributors, SRTM · Style © OpenTopoMap (CC-BY-SA)', maxzoom: 17, grid: '#1f2937', halo: '#ffffff' },
}

const events = ref([])
const customPlaces = ref([])
const text = ref('')
const callsign = ref('alpha 1')
const lang = ref('en')
const readBack = ref(true)
const cursor = ref(0)          // history scrubber: show events[0..cursor)
const listening = ref(false)
const status = ref('connecting…')
const serverStt = ref(null)    // provider name when the backend can transcribe, else null
const heard = ref('')
const now = ref(Date.now() / 1000)
// Map look is a per-screen preference, remembered in this browser only (storage can be blocked: then defaults).
const saved = (() => { try { return JSON.parse(localStorage.getItem('mapLook')) || {} } catch { return {} } })()
const basemap = ref(saved.basemap in BASEMAPS ? saved.basemap : 'dark')
const showGrid = ref(saved.showGrid ?? true)
const night = ref(!!saved.night)  // red-on-black, keeps night vision at a dark command post
watch([basemap, showGrid, night], () => {
  try { localStorage.setItem('mapLook', JSON.stringify({ basemap: basemap.value, showGrid: showGrid.value, night: night.value })) } catch {}
})
const cursorGrid = ref('')     // MGRS under the mouse (or of the map centre on touch screens)
let map, netRecogniser, ticker, socket, unmounted = false

// Radio-net mode: listen to the whole channel, no button, no callsign picker.
const mode = ref('ptt')               // 'ptt' (push-to-talk) | 'net'
const txs = ref([])                   // every transmission heard on the net
const netOn = ref(false)
const netSource = ref('')             // 'mic' | 'file' | 'browser'
const netLevel = ref(0)
const netSpeaking = ref(false)
const netSegments = ref(0)
const netMsg = ref('')
const netText = ref('')
let netCtx, netStream, netNode, netAudio, netVad, netQueue = Promise.resolve()
const KIND = { report: 'report', request: 'request', order: 'order', ack: 'ack', say_again: 'say again',
  radio_check: 'radio check', call: 'call', other: 'chatter' }

const Speech = window.SpeechRecognition || window.webkitSpeechRecognition
const canRecord = !!navigator.mediaDevices?.getUserMedia
const canListen = computed(() => (serverStt.value && canRecord) || !!Speech)

const visible = computed(() => events.value.slice(0, cursor.value))
const live = computed(() => cursor.value === events.value.length)
const callsigns = computed(() => [...new Set(events.value.map((e) => e.callsign))])
const colour = (c) => (callsigns.value.includes(c) ? COLOURS[callsigns.value.indexOf(c) % COLOURS.length] : '#374151')
const byId = computed(() => new Map(events.value.map((e) => [e.id, e])))
const visibleTx = computed(() => (live.value ? txs.value : txs.value.filter((tx) => tx.t <= (visible.value.at(-1)?.t ?? 0))))
// Open taskings: the latest order per unit that has a destination and has not been reached.
const tasks = computed(() => {
  const last = new Map()
  visible.value.forEach((e) => { if (e.type === 'order') last.set(e.callsign, e) })
  return [...last.values()].filter((e) => e.target && !e.reached && !e.superseded)
})
const meter = computed(() => Math.max(0, Math.min(100, ((20 * Math.log10(netLevel.value + 1e-6) + 60) / 60) * 100)))
const clock = (t) => new Date(t * 1000).toLocaleTimeString()
const ago = (t) => { const s = Math.max(0, now.value - t); return s < 60 ? `${Math.round(s)} s ago` : `${Math.round(s / 60)} min ago` }

function circle([lon, lat], r, n = 48) {
  const kx = 111320 * Math.cos((lat * Math.PI) / 180), ky = 110540
  return { type: 'Polygon', coordinates: [Array.from({ length: n + 1 }, (_, i) => {
    const a = (i / n) * 2 * Math.PI
    return [lon + (r * Math.sin(a)) / kx, lat + (r * Math.cos(a)) / ky]
  })] }
}

// A report is a draft until the duty officer confirms it, and only drafts with real doubt look uncertain:
// an ambiguous fix or an assumed callsign. Any unit silent for STALE_S is uncertain again, confirmed or not.
const suspected = (e) => ((e.ambiguous || e.callsign_assumed) && !e.confirmed) || (live.value && now.value - e.t > STALE_S)

async function confirm(e) {
  await fetch(`/api/events/${e.id}/confirm`, { method: 'POST' })   // the update comes back over the WebSocket
}

function render() {
  if (!map?.getSource('regions')) return
  const ok = visible.value.filter((e) => e.ok && !e.superseded)
  const latest = new Map()
  ok.forEach((e) => latest.set(e.callsign, e))
  const current = [...latest.values()]
  map.getSource('units').setData({ type: 'FeatureCollection', features: current.map((e) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: e.centre },
    properties: { icon: `ms:${suspected(e) ? SIDC.dashed : SIDC.solid}` },
  })) })
  map.getSource('regions').setData({ type: 'FeatureCollection', features: ok.map((e) => ({
    type: 'Feature', geometry: e.region,
    properties: { colour: colour(e.callsign), current: latest.get(e.callsign) === e, ambiguous: !!e.ambiguous },
  })) })
  map.getSource('paths').setData({ type: 'FeatureCollection', features: callsigns.value.map((c) => ({
    type: 'Feature', properties: { colour: colour(c) },
    geometry: { type: 'LineString', coordinates: ok.filter((e) => e.callsign === c).map((e) => e.centre) },
  })).filter((f) => f.geometry.coordinates.length > 1) })
  // Where the unit could be by now: last region radius plus walking distance since the report.
  map.getSource('stale').setData({ type: 'FeatureCollection', features: live.value ? current.map((e) => ({
    type: 'Feature', properties: { colour: colour(e.callsign) },
    geometry: circle(e.centre, Math.min(STALE_CAP_M, e.radius_m + WALK_MPS * Math.max(0, now.value - e.t))),
  })) : [] })
  map.getSource('labels').setData({ type: 'FeatureCollection', features: current.map((e) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: e.centre },
    // Second line: the grid, never more precise than the report (±40 m reads as a 100 m square).
    properties: { label: `${e.callsign} ±${Math.round(e.radius_m)} m${live.value ? ' · ' + ago(e.t) : ''}\n${mgrsAt(e.centre, { radius: e.radius_m })}`,
      colour: colour(e.callsign) },
  })) })
  map.getSource('tasks').setData({ type: 'FeatureCollection', features: tasks.value.map((e) => ({
    type: 'Feature', geometry: e.target.region,
    properties: { colour: colour(e.callsign), label: `${e.callsign} ▸ ${e.target.anchor}` },
  })) })
  map.getSource('custom').setData({ type: 'FeatureCollection', features: customPlaces.value.map((p) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [p.lon, p.lat] }, properties: { label: p.name },
  })) })
}
watch([visible, callsigns, customPlaces, now, tasks], render)

// --- map look: basemap, MGRS grid, night mode -----------------------------------------------------------------
function updateGrid() {
  if (!map?.getSource('grid')) return
  const g = showGrid.value ? gridLines(map.getBounds(), map.getZoom()) : null
  map.getSource('grid').setData(g?.lines ?? { type: 'FeatureCollection', features: [] })
  map.getSource('grid-labels').setData(g?.labels ?? { type: 'FeatureCollection', features: [] })
}

function applyBasemap() {
  if (!map?.getLayer('grid-line')) return
  const b = BASEMAPS[basemap.value]
  for (const id of Object.keys(BASEMAPS)) map.setLayoutProperty(`base-${id}`, 'visibility', id === basemap.value ? 'visible' : 'none')
  map.setPaintProperty('grid-line', 'line-color', b.grid)
  map.setPaintProperty('grid-label', 'text-color', b.grid)
  map.setPaintProperty('grid-label', 'text-halo-color', b.halo)   // unit labels keep their dark halo on every basemap
}
watch(basemap, applyBasemap)
watch(showGrid, updateGrid)

// Milsymbol draws each APP-6 symbol the first time the map asks for it.
function addSymbolImage(ev) {
  if (!ev.id.startsWith('ms:') || map.hasImage(ev.id)) return
  const ratio = window.devicePixelRatio || 1
  const canvas = new ms.Symbol(ev.id.slice(3), { size: 26 }).asCanvas(ratio)
  map.addImage(ev.id, canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height), { pixelRatio: ratio })
}

function add(event) {
  const atEnd = cursor.value === events.value.length
  events.value.push(event)
  if (atEnd) cursor.value = events.value.length
  if (event.ok) map?.easeTo({ center: event.centre, duration: 600 })
  if (event.identifies) {                     // "This is Delta three" claimed a report held for lack of a callsign
    const held = events.value.find((x) => x.id === event.identifies)
    if (held) { held.identified_as = event.callsign; events.value = [...events.value] }
  }
}

// Read-back, radio style, so the speaker hears what the map understood. Only the screen that sent the report speaks
// (every open tab gets every event over the WebSocket, and several tabs reading back at once sounds like an echo).
function speak(e) {
  if (!readBack.value || !window.speechSynthesis || e.source?.startsWith('radio')) return   // the net would hear itself
  let msg
  if (e.type === 'unidentified') msg = lang.value === 'fr' ? 'Station qui appelle, répétez votre indicatif.' : 'Station calling, say again your callsign.'
  else if (e.ok) msg = `${e.callsign}, ${e.parsed?.relation === 'at' ? 'at' : (e.parsed?.relation || '').replaceAll('_', ' ')} ${e.anchor}`
  else if (e.type === 'intent') msg = `${e.callsign}, copy intention.`
  else msg = `${e.callsign}, say again. ${e.note || ''}`
  window.speechSynthesis.cancel()             // never queue up old read-backs behind the new one
  const u = new SpeechSynthesisUtterance(msg)
  u.lang = lang.value === 'fr' ? 'fr-FR' : 'en-GB'
  window.speechSynthesis.speak(u)
}

async function send(body = text.value.trim(), { voice = false } = {}) {
  if (!body) return
  text.value = ''
  const r = await fetch('/api/report', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: body, callsign: callsign.value }),
  })  // events come back over the WebSocket, same as for every other client
  const out = await r.json().catch(() => ({}))
  if (r.ok) out.events?.forEach(speak)
  if (r.ok && !out.events?.length) heard.value = `heard “${body}”: ignored, no callsign or place`
  else if (voice) heard.value = `heard: “${body}”`
}

async function reset() {
  await fetch('/api/reset', { method: 'POST' })
}

// --- push-to-talk: server-side speech-to-text when available, the browser's own otherwise ---------------------
function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf)
  const w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)))
  w(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); w(8, 'WAVE'); w(12, 'fmt ')
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true)
  v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data')
  v.setUint32(40, samples.length * 2, true)
  samples.forEach((s, i) => v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true))
  return buf
}

// Each press gets its own stream, recorder and chunks, so an overlapping press can never mix or leak them.
async function recordStart() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, noiseSuppression: true, echoCancellation: true } })
  const chunks = [], recorder = new MediaRecorder(stream)
  recorder.ondataavailable = (e) => chunks.push(e.data)
  recorder.start()
  return { stream, recorder, chunks }
}

async function recordHalt({ stream, recorder }) {
  const stopped = new Promise((r) => { recorder.onstop = r })
  recorder.stop(); await stopped
  stream.getTracks().forEach((t) => t.stop())
}

async function recordStop(handle) {
  await recordHalt(handle)
  const { chunks } = handle
  const ctx = new AudioContext()
  const decoded = await ctx.decodeAudioData(await new Blob(chunks).arrayBuffer())
  ctx.close()
  const off = new OfflineAudioContext(1, Math.ceil(decoded.duration * 16000), 16000)
  const src = off.createBufferSource(); src.buffer = decoded; src.connect(off.destination); src.start()
  const wav = encodeWav((await off.startRendering()).getChannelData(0), 16000)
  heard.value = 'transcribing…'
  const r = await fetch(`/api/audio?callsign=${encodeURIComponent(callsign.value)}&lang=${lang.value}`, {
    method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav })
  if (r.status === 501) { serverStt.value = null; heard.value = 'server speech-to-text off; using the browser'; return }
  const out = await r.json().catch(() => ({}))
  if (r.ok) out.events?.forEach(speak)
  heard.value = !r.ok ? `speech-to-text failed: ${out.detail || r.status}`
    : out.transcript && !out.events?.length ? `heard “${out.transcript}”: ignored, no callsign or place`
    : `heard: “${out.transcript}”`
}

// Push-to-talk. The state machines live in ptt.js (tested in frontend/tests/ptt.test.js): one press = one report,
// nothing sent twice, a quick release-then-press loses nothing, and a quick tap never leaves the microphone on.
let held = false
const browserPtt = Speech && createBrowserPtt({
  Speech, lang: () => (lang.value === 'fr' ? 'fr-FR' : 'en-GB'),
  onSend: (t) => send(t, { voice: true }), onHeard: (h) => { heard.value = h }, onListening: (v) => { listening.value = v },
})
const recorderPtt = createRecorderPtt({
  open: recordStart, close: recordStop, discard: recordHalt, onListening: (v) => { listening.value = v },
})

async function talk(start) {
  if (!canListen.value || start === held) return
  if (start && netOn.value && netSource.value === 'browser') { heard.value = 'stop the radio net first: the browser has one recogniser'; return }
  held = start
  try {
    if (serverStt.value && canRecord) await (start ? recorderPtt.press() : recorderPtt.release())
    else start ? browserPtt.press() : browserPtt.release()
  } catch (err) {
    heard.value = `microphone: ${err.message}`
    held = false
    listening.value = false
  }
}

// --- radio-net mode -------------------------------------------------------------------------------------------
async function netSend(body = netText.value.trim()) {
  if (!body) return
  netText.value = ''
  await fetch('/api/net/text', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: body }) })
}

async function replayDemo() {
  const r = await fetch('/api/net/replay?speed=3', { method: 'POST' })
  const out = await r.json().catch(() => ({}))
  netMsg.value = r.ok ? `replaying ${out.lines} transmissions over ~${out.seconds} s (3× speed)` : out.detail || `replay failed (${r.status})`
}

// Each transmission cut by the VAD goes to the server in order: who-is-speaking depends on the sequence.
function queueSegment(samples, rate, startedAt, seconds) {
  netSegments.value++
  netQueue = netQueue.then(async () => {
    const off = new OfflineAudioContext(1, Math.ceil(seconds * 16000), 16000)
    const buf = off.createBuffer(1, samples.length, rate); buf.copyToChannel(samples, 0)
    const src = off.createBufferSource(); src.buffer = buf; src.connect(off.destination); src.start()
    const wav = encodeWav((await off.startRendering()).getChannelData(0), 16000)
    const r = await fetch(`/api/net/audio?lang=${lang.value}&t=${startedAt.toFixed(2)}&dur=${seconds.toFixed(2)}`, {
      method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav })
    if (r.status === 501) {
      netMsg.value = `transmission ${netSegments.value} detected (${seconds.toFixed(1)} s), but the server has no speech-to-text: set MISTRAL_API_KEY or install faster-whisper`
      return
    }
    const out = await r.json().catch(() => ({}))
    netMsg.value = r.ok ? `heard: “${out.transcript}”` : `speech-to-text failed: ${out.detail || r.status}`
  }).catch((err) => { netMsg.value = err.message })
}

function browserNet() {
  // No server speech-to-text: the browser's own recogniser, kept running, one final result per transmission.
  netRecogniser = new Speech()
  netRecogniser.lang = lang.value === 'fr' ? 'fr-FR' : 'en-GB'
  netRecogniser.continuous = true
  netRecogniser.onresult = (r) => {
    for (let i = r.resultIndex; i < r.results.length; i++) {
      if (!r.results[i].isFinal) continue
      const t = r.results[i][0].transcript.trim()
      if (t) { netSegments.value++; netMsg.value = `heard: “${t}”`; netSend(t) }
    }
  }
  netRecogniser.onend = () => { if (netOn.value && netSource.value === 'browser') netRecogniser.start() }
  netRecogniser.start()
  netSource.value = 'browser'
  netOn.value = true
  netMsg.value = 'listening with the browser recogniser (server speech-to-text is off)'
}

async function netStart(file) {
  if (netOn.value) await netStop()
  netSegments.value = 0
  if (!file && !serverStt.value) {
    if (Speech) return browserNet()
    netMsg.value = 'no speech-to-text: set MISTRAL_API_KEY or install faster-whisper on the server'
    return
  }
  try {
    netCtx = new AudioContext()
    let src
    if (file) {
      netAudio = new Audio(URL.createObjectURL(file))
      src = netCtx.createMediaElementSource(netAudio)
      src.connect(netCtx.destination)                       // the operator hears the recording too
      netAudio.onended = () => setTimeout(netStop, 1000)   // let the VAD close the last transmission
    } else {
      netStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: false, noiseSuppression: true } })
      src = netCtx.createMediaStreamSource(netStream)
    }
    netVad = createVad(netCtx.sampleRate, {
      level: (rms, speaking) => { netLevel.value = rms; netSpeaking.value = speaking },
      segment: (samples, startedAt, seconds) => queueSegment(samples, netCtx.sampleRate, startedAt, seconds),
    })
    netNode = netCtx.createScriptProcessor(2048, 1, 1)
    netNode.onaudioprocess = (e) => netVad.push(e.inputBuffer.getChannelData(0))
    src.connect(netNode); netNode.connect(netCtx.destination)   // silent output; the connection keeps it running
    if (file) await netAudio.play()
    netSource.value = file ? 'file' : 'mic'
    netOn.value = true
    netMsg.value = file ? `playing ${file.name}` : 'listening to the channel'
  } catch (err) {
    netMsg.value = `audio: ${err.message}`
    await netStop()
  }
}

async function netStop() {
  netVad?.flush()
  netRecogniser && netSource.value === 'browser' && netRecogniser.stop()
  netNode?.disconnect(); netAudio?.pause(); netStream?.getTracks().forEach((t) => t.stop())
  await netCtx?.close().catch(() => {})
  netCtx = netNode = netAudio = netStream = netVad = null
  netOn.value = false; netSpeaking.value = false; netLevel.value = 0; netSource.value = ''
}

function netFile(ev) { const f = ev.target.files?.[0]; ev.target.value = ''; if (f) netStart(f) }

// Hold the space bar to talk (unless typing).
const typing = (e) => ['TEXTAREA', 'INPUT', 'SELECT'].includes(e.target.tagName)
function keydown(e) { if (mode.value !== 'ptt') return; if (e.code === 'Space' && !e.repeat && !typing(e)) { e.preventDefault(); talk(true) } }
function keyup(e) { if (mode.value !== 'ptt') return; if (e.code === 'Space' && !typing(e)) { e.preventDefault(); talk(false) } }
// Releasing Space in another window never reaches us: losing focus ends the press, or the microphone stays on.
function blur() { talk(false) }
function hidden() { if (document.hidden) talk(false) }

// One socket per page. On unmount (a hot reload while developing) it is closed for good: a leftover socket would keep
// running the old handlers, and every copy would read each report back aloud.
function connect() {
  if (unmounted) return
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ws`)
  socket = ws
  ws.onopen = () => { status.value = 'live' }
  ws.onclose = () => { if (unmounted) return; status.value = 'reconnecting…'; setTimeout(connect, 1500) }
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data)
    if (msg.type === 'event') add(msg.event)
    if (msg.type === 'supersede') {
      const e = events.value.find((x) => x.id === msg.id)
      if (e) { e.superseded = true; events.value = [...events.value] }
    }
    if (msg.type === 'places') customPlaces.value = msg.places
    if (msg.type === 'tx') txs.value.push(msg.tx)
    if (msg.type === 'annotate') {
      const e = events.value.find((x) => x.id === msg.id)
      if (e) { Object.assign(e, msg.fields); events.value = [...events.value] }
    }
    if (msg.type === 'reset') { events.value = []; cursor.value = 0; txs.value = [] }
  }
}

onMounted(async () => {
  const state = await fetch('/api/state').then((r) => r.json()).catch(() => null)
  if (!state) status.value = 'backend not reachable on :8000'
  serverStt.value = state?.stt ?? null
  customPlaces.value = state?.custom_places ?? []
  map = new maplibregl.Map({
    container: 'map', center: state?.centre ?? [2.334, 48.851], zoom: 15.5,
    style: {
      version: 8,
      glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
      // All basemaps are loaded once and switched by visibility, so our own layers and symbols are never rebuilt.
      sources: Object.fromEntries(Object.entries(BASEMAPS).map(([id, b]) => [`base-${id}`,
        { type: 'raster', tiles: b.tiles, tileSize: 256, maxzoom: b.maxzoom, attribution: b.attribution }])),
      layers: Object.keys(BASEMAPS).map((id) => ({ id: `base-${id}`, type: 'raster', source: `base-${id}`,
        layout: { visibility: id === basemap.value ? 'visible' : 'none' }, paint: BASEMAPS[id].paint ?? {} })),
    },
  })
  map.on('styleimagemissing', addSymbolImage)
  map.on('load', () => {
    const empty = { type: 'FeatureCollection', features: [] }
    for (const id of ['regions', 'paths', 'labels', 'stale', 'custom', 'tasks', 'units', 'grid', 'grid-labels']) {
      map.addSource(id, { type: 'geojson', data: empty })
    }
    // MGRS kilometre grid under everything we draw, with 2-digit easting/northing labels at the edges.
    map.addLayer({ id: 'grid-line', type: 'line', source: 'grid',
      paint: { 'line-color': '#cbd5e1', 'line-width': ['case', ['get', 'major'], 1.5, 0.9],
        'line-opacity': ['case', ['get', 'major'], 0.9, 0.6] } })
    map.addLayer({ id: 'grid-label', type: 'symbol', source: 'grid-labels',
      layout: { 'text-field': ['get', 'label'], 'text-size': 11, 'text-font': ['Open Sans Semibold'], 'text-allow-overlap': true },
      paint: { 'text-color': '#94a3b8', 'text-halo-color': '#0b0d10', 'text-halo-width': 1.5 } })
    map.addLayer({ id: 'stale-line', type: 'line', source: 'stale',
      paint: { 'line-color': ['get', 'colour'], 'line-width': 1, 'line-dasharray': [1, 3], 'line-opacity': 0.8 } })
    map.addLayer({ id: 'region-fill', type: 'fill', source: 'regions',
      paint: { 'fill-color': ['get', 'colour'], 'fill-opacity': ['case', ['get', 'current'], 0.35, 0.08] } })
    // Ambiguous regions get a dashed outline (dash patterns cannot be data-driven, hence two layers).
    const outline = { 'line-color': ['get', 'colour'], 'line-width': ['case', ['get', 'current'], 2, 0.5] }
    map.addLayer({ id: 'region-line', type: 'line', source: 'regions',
      filter: ['!', ['get', 'ambiguous']], paint: outline })
    map.addLayer({ id: 'region-line-ambiguous', type: 'line', source: 'regions',
      filter: ['get', 'ambiguous'], paint: { ...outline, 'line-dasharray': [2, 2] } })
    // Tasked destinations: dashed outline until the unit reports arriving.
    map.addLayer({ id: 'task-fill', type: 'fill', source: 'tasks', paint: { 'fill-color': ['get', 'colour'], 'fill-opacity': 0.12 } })
    map.addLayer({ id: 'task-line', type: 'line', source: 'tasks',
      paint: { 'line-color': ['get', 'colour'], 'line-width': 2.5, 'line-dasharray': [1, 1.5] } })
    map.addLayer({ id: 'task-label', type: 'symbol', source: 'tasks',
      layout: { 'text-field': ['get', 'label'], 'text-size': 12, 'text-font': ['Open Sans Semibold'], 'text-max-width': 30 },
      paint: { 'text-color': ['get', 'colour'], 'text-halo-color': '#0b0d10', 'text-halo-width': 2 } })
    map.addLayer({ id: 'path', type: 'line', source: 'paths',
      paint: { 'line-color': ['get', 'colour'], 'line-width': 2, 'line-opacity': 0.7 } })
    map.addLayer({ id: 'custom-dot', type: 'circle', source: 'custom',
      paint: { 'circle-radius': 5, 'circle-color': '#f5c518', 'circle-stroke-color': '#0b0d10', 'circle-stroke-width': 2 } })
    map.addLayer({ id: 'custom-label', type: 'symbol', source: 'custom',
      layout: { 'text-field': ['get', 'label'], 'text-size': 12, 'text-offset': [0, 1.2], 'text-font': ['Open Sans Semibold'] },
      paint: { 'text-color': '#f5c518', 'text-halo-color': '#0b0d10', 'text-halo-width': 2 } })
    // Each unit's current fix as an APP-6 friendly infantry symbol: solid frame, or dashed while in doubt.
    map.addLayer({ id: 'unit-icon', type: 'symbol', source: 'units',
      layout: { 'icon-image': ['get', 'icon'], 'icon-allow-overlap': true, 'icon-ignore-placement': true } })
    map.addLayer({ id: 'label', type: 'symbol', source: 'labels',
      layout: { 'text-field': ['get', 'label'], 'text-size': 12, 'text-offset': [0, -2.6], 'text-max-width': 30,
        'text-font': ['Open Sans Semibold'], 'text-line-height': 1.25 },
      paint: { 'text-color': ['get', 'colour'], 'text-halo-color': '#0b0d10', 'text-halo-width': 2 } })
    applyBasemap()
    updateGrid()
    render()
  })
  map.on('moveend', updateGrid)
  // Live grid readout: under the mouse on a desktop, the map centre on a touch screen.
  map.on('mousemove', (ev) => { cursorGrid.value = mgrsAt([ev.lngLat.lng, ev.lngLat.lat]) })
  map.on('move', () => { if (!matchMedia('(hover: hover)').matches) cursorGrid.value = mgrsAt(map.getCenter().toArray()) })
  cursorGrid.value = mgrsAt(map.getCenter().toArray())
  // Right-click (long-press on touch) names a point, e.g. "checkpoint 3"; it can be spoken at once.
  map.on('contextmenu', async (ev) => {
    const name = window.prompt('Name this point (e.g. "checkpoint 3")')
    if (!name?.trim()) return
    await fetch('/api/places', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), lon: ev.lngLat.lng, lat: ev.lngLat.lat }) })
  })
  if (state) { events.value = state.events; cursor.value = state.events.length; txs.value = state.transmissions ?? [] }
  connect()
  ticker = setInterval(() => { now.value = Date.now() / 1000 }, 5000)
  window.addEventListener('keydown', keydown)
  window.addEventListener('keyup', keyup)
  window.addEventListener('blur', blur)
  document.addEventListener('visibilitychange', hidden)
})

onUnmounted(() => {
  unmounted = true
  socket?.close()
  window.speechSynthesis?.cancel()
  netStop()
  clearInterval(ticker)
  window.removeEventListener('keydown', keydown)
  window.removeEventListener('keyup', keyup)
  window.removeEventListener('blur', blur)
  document.removeEventListener('visibilitychange', hidden)
})
</script>

<template>
  <div class="layout" :class="{ night }">
    <div class="mapwrap">
      <div id="map"></div>
      <div class="mapbar">
        <div class="seg" role="group" aria-label="Basemap">
          <button v-for="(b, id) in BASEMAPS" :key="id" type="button" :class="{ sel: basemap === id }"
            :aria-pressed="basemap === id" @click="basemap = id">{{ b.label }}</button>
        </div>
        <button type="button" class="chipbtn" :class="{ sel: showGrid }" :aria-pressed="showGrid" @click="showGrid = !showGrid">MGRS grid</button>
        <button type="button" class="chipbtn" :class="{ sel: night }" :aria-pressed="night" @click="night = !night">Night</button>
      </div>
      <div class="readout" title="MGRS under the cursor (1 m)">{{ cursorGrid }}</div>
      <div class="legend">
        <span><i class="frame"></i> report</span>
        <span><i class="frame dashed"></i> in doubt: ambiguous, callsign assumed, or silent 5 min</span>
      </div>
    </div>
    <aside>
      <header>
        <h1>Voice-to-Map</h1>
        <span class="status">{{ status }} · speech: {{ serverStt || (Speech ? 'browser' : 'none') }}</span>
      </header>

      <div class="tabs" role="tablist">
        <button type="button" role="tab" :aria-selected="mode === 'ptt'" :class="{ sel: mode === 'ptt' }" @click="mode = 'ptt'">Push-to-talk</button>
        <button type="button" role="tab" :aria-selected="mode === 'net'" :class="{ sel: mode === 'net' }" @click="mode = 'net'">Radio net</button>
      </div>

      <section v-if="mode === 'net'" class="net">
        <div class="row">
          <button type="button" :class="{ on: netOn && netSource !== 'file' }" @click="netOn && netSource !== 'file' ? netStop() : netStart()">
            {{ netOn && netSource !== 'file' ? 'Stop listening' : 'Listen to the net' }}
          </button>
          <label class="filebtn" :class="{ on: netSource === 'file' }">{{ netSource === 'file' ? 'Playing…' : 'Play a recording' }}
            <input type="file" accept="audio/*" @change="netFile" />
          </label>
          <button type="button" class="quiet" @click="replayDemo">Replay demo net</button>
          <select v-model="lang" title="Speech language"><option value="en">EN</option><option value="fr">FR</option></select>
        </div>
        <div class="meter" :title="netSpeaking ? 'transmission in progress' : 'channel quiet'">
          <div :style="{ width: meter + '%' }" :class="{ hot: netSpeaking }"></div>
        </div>
        <div class="row small">
          <span>{{ netOn ? (netSpeaking ? 'transmission…' : 'channel quiet') : 'not listening' }} · {{ netSegments }} cut</span>
          <button type="button" class="quiet" @click="reset">Reset</button>
        </div>
        <form @submit.prevent="netSend()">
          <input v-model="netText" class="wide" placeholder="Type a transmission as heard, e.g. Zero, this is Alpha one, at the fountain, over" />
        </form>
        <div v-if="netMsg" class="heard">{{ netMsg }}</div>
      </section>

      <form v-else @submit.prevent="send()">
        <div class="row">
          <label>Default callsign <input v-model="callsign" class="callsign" /></label>
          <select v-model="lang" title="Speech language"><option value="en">EN</option><option value="fr">FR</option></select>
        </div>
        <textarea v-model="text" rows="2" placeholder="e.g. Zero, this is Alpha two, south of the church, over"
          @keydown.enter.exact.prevent="send()"></textarea>
        <div class="row">
          <button type="submit">Send</button>
          <button type="button" :disabled="!canListen" :class="{ on: listening }"
            @mousedown="talk(true)" @mouseup="talk(false)" @mouseleave="talk(false)"
            @touchstart.prevent="talk(true)" @touchend.prevent="talk(false)">
            {{ canListen ? (listening ? 'Listening…' : 'Hold to talk (or Space)') : 'No speech input' }}
          </button>
          <button type="button" class="quiet" @click="reset">Reset</button>
        </div>
        <div class="row small">
          <label><input type="checkbox" v-model="readBack" /> read back</label>
          <a href="/api/export.geojson" target="_blank">export GeoJSON</a>
          <span class="hint">right-click map: name a point</span>
        </div>
        <div v-if="heard" class="heard">{{ heard }}</div>
      </form>

      <label class="scrub">History {{ cursor }} / {{ events.length }}
        <input type="range" min="0" :max="events.length" v-model.number="cursor" />
      </label>

      <ol v-if="mode === 'net'" class="log">
        <li v-for="tx in [...visibleTx].reverse()" :key="'tx' + tx.id" class="tx" :class="['k-' + tx.kind, { unid: !tx.from }]">
          <div class="meta">
            <b :style="{ color: colour(tx.from) }">{{ tx.from || 'unknown' }}</b>
            <span>→ {{ tx.to || '—' }}</span>
            <span class="chip">{{ KIND[tx.kind] || tx.kind }}</span>
            <time>{{ clock(tx.t) }}</time>
            <span v-if="tx.stt">🎙 {{ tx.stt.stt_ms }} ms</span>
          </div>
          <div class="said">“{{ tx.text }}”</div>
          <div class="how">{{ tx.how }}</div>
          <template v-for="id in tx.events" :key="id">
            <div v-if="byId.get(id)" class="read" :class="{ gone: byId.get(id).superseded }">
              <template v-if="byId.get(id).ok">→ <b :style="{ color: colour(byId.get(id).callsign) }">{{ byId.get(id).callsign }}</b>
                {{ (byId.get(id).parsed?.relation || '').replaceAll('_', ' ') }} {{ byId.get(id).anchor }} · ±{{ byId.get(id).radius_m }} m
                <span class="gridref">{{ mgrsAt(byId.get(id).centre, { radius: byId.get(id).radius_m }) }}</span>
                <button v-if="!byId.get(id).confirmed && !byId.get(id).superseded" type="button" class="confirm small"
                  @click="confirm(byId.get(id))">Confirm</button>
                <span v-else-if="byId.get(id).confirmed" class="tick">✓ confirmed</span></template>
              <template v-else-if="byId.get(id).type === 'order'">▸ <b :style="{ color: colour(byId.get(id).callsign) }">{{ byId.get(id).callsign }}</b> {{ byId.get(id).note }}</template>
              <template v-else>{{ byId.get(id).callsign }}: {{ byId.get(id).note }}</template>
              <span v-if="byId.get(id).acked_by" class="tick" :title="'acknowledged by ' + byId.get(id).acked_by">✓ {{ byId.get(id).acked_by }}</span>
              <span v-if="byId.get(id).queried_by" class="query">asked to repeat</span>
              <span v-if="byId.get(id).reached" class="tick">✓ arrived</span>
              <span v-if="byId.get(id).superseded" class="query">replaced</span>
            </div>
          </template>
          <div v-if="tx.note" class="note">{{ tx.note }}</div>
        </li>
        <li v-if="!visibleTx.length" class="empty">Nothing heard yet. Listen to the channel, play a recording or replay the demo net.</li>
      </ol>

      <ol v-else class="log">
        <li v-for="e in [...visible].reverse()" :key="e.id"
          :class="{ bad: !e.ok && !e.identified_as && !['intent', 'order'].includes(e.type), amb: e.ambiguous, intent: ['intent', 'order'].includes(e.type), gone: e.superseded }">
          <div class="meta">
            <b :style="{ color: colour(e.callsign) }">{{ e.callsign }}</b>
            <span v-if="e.callsign_assumed" class="assumed" title="No callsign was said; taken from the Default callsign box">(assumed)</span>
            <span v-if="e.speaker && e.speaker !== e.callsign">via {{ e.speaker }}</span>
            <time>{{ clock(e.t) }}</time>
            <span v-if="e.latency_ms">{{ e.latency_ms.total ?? e.latency_ms }} ms<template v-if="e.latency_ms.stt"> (speech {{ e.latency_ms.stt }})</template></span>
            <span v-if="e.source === 'voice' || e.source === 'radio'">🎙</span>
            <span v-if="e.acked_by" class="tick">✓ {{ e.acked_by }}</span>
            <span v-if="e.reached" class="tick">✓ arrived</span>
          </div>
          <div class="said">“{{ e.text }}”</div>
          <div v-if="e.ok" class="read">→ {{ (e.parsed?.relation || '').replaceAll('_', ' ') }} <b>{{ e.anchor }}</b> · ±{{ e.radius_m }} m
            <span class="gridref">{{ mgrsAt(e.centre, { radius: e.radius_m }) }}</span></div>
          <div v-if="e.superseded" class="note">corrected by a later report</div>
          <div v-if="e.identified_as" class="tick">✓ identified as {{ e.identified_as }}</div>
          <div v-else-if="e.note" class="note">{{ e.note }}</div>
          <div v-if="e.identifies" class="assumed">callsign given after “say again”</div>
          <div v-if="e.alternatives?.length" class="note">Could also be: {{ e.alternatives.join(', ') }}</div>
          <div v-if="e.ok && !e.superseded" class="actions">
            <button v-if="!e.confirmed" type="button" class="confirm" @click="confirm(e)">Confirm</button>
            <span v-else class="tick">✓ confirmed {{ clock(e.confirmed_at) }}</span>
          </div>
        </li>
      </ol>
    </aside>
  </div>
</template>

<style>
/* Command-post theme: near-black, low glare, one yellow colour for the action that matters (Confirm, Send). */
:root { --bg: #0b0d10; --panel: #111418; --card: #161a20; --line: #262b33; --text: #e6e8eb; --muted: #8a93a0;
  --accent: #f5c518; --ok: #34d399; --warn: #f59e0b; --bad: #f87171; --blue: #60a5fa; }
body { margin: 0; font: 14px/1.4 system-ui, sans-serif; color: var(--text); background: var(--bg); }
.layout { display: grid; grid-template-columns: 1fr 380px; height: 100vh; }
/* Night: everything red on black, so the operator's eyes stay adapted to the dark. */
.layout.night { filter: grayscale(1) sepia(1) saturate(14) hue-rotate(-52deg) brightness(0.5) contrast(1.25); }
.mapwrap { position: relative; min-height: 0; }
#map { height: 100%; background: var(--bg); }
.mapbar { position: absolute; top: 10px; left: 10px; display: flex; gap: 6px; flex-wrap: wrap; z-index: 2; }
.seg { display: flex; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; background: rgba(17, 20, 24, 0.92); }
.seg button, .chipbtn { background: rgba(17, 20, 24, 0.92); color: var(--muted); border: 0; border-radius: 0; padding: 5px 10px; font-size: 12px; }
.chipbtn { border: 1px solid var(--line); border-radius: 6px; }
.seg button.sel, .chipbtn.sel { color: var(--text); background: #232933; box-shadow: inset 0 -2px 0 var(--accent); }
.readout { position: absolute; left: 10px; bottom: 10px; z-index: 2; font: 600 13px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--text); background: rgba(11, 13, 16, 0.88); border: 1px solid var(--line); border-radius: 6px; padding: 7px 10px; letter-spacing: 0.04em; }
.legend { position: absolute; right: 10px; top: 10px; z-index: 2; display: grid; gap: 4px; font-size: 11px; color: var(--muted);
  background: rgba(11, 13, 16, 0.88); border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; max-width: 230px; }
.legend span { display: flex; gap: 6px; align-items: center; }
.legend .frame { width: 16px; height: 11px; flex: none; background: #80e0ff; border: 1.5px solid #000; box-sizing: border-box; }
.legend .frame.dashed { border: 1.5px dashed #000; outline: 1px solid #80e0ff; background: transparent; }
.maplibregl-ctrl-attrib { background: rgba(11, 13, 16, 0.7) !important; color: var(--muted); }
.maplibregl-ctrl-attrib a { color: var(--muted) !important; }
aside { display: flex; flex-direction: column; gap: 12px; padding: 14px; overflow: hidden; border-left: 1px solid var(--line); background: var(--panel); }
header { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
h1 { font-size: 15px; margin: 0; letter-spacing: 0.08em; text-transform: uppercase; }
.status { color: var(--muted); font-size: 12px; text-align: right; }
form { display: grid; gap: 8px; }
textarea, input.callsign, select, input.wide { font: inherit; padding: 6px 8px; border: 1px solid var(--line); border-radius: 6px;
  background: var(--bg); color: var(--text); }
textarea { resize: vertical; }
input.callsign { width: 110px; margin-left: 6px; }
input.wide { width: 100%; box-sizing: border-box; }
.row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.row.small { font-size: 12px; color: var(--muted); gap: 12px; }
.row.small a { color: var(--blue); }
.hint { margin-left: auto; }
button { font: inherit; padding: 6px 10px; border: 1px solid #2d333c; background: #1c2128; color: var(--text); border-radius: 6px; cursor: pointer; user-select: none; }
button:hover { border-color: #3a414c; }
button[type='submit'], button.confirm { background: var(--accent); border-color: var(--accent); color: #111; font-weight: 600; }
button.confirm { padding: 3px 12px; font-size: 12px; }
button.confirm.small { padding: 1px 8px; margin-left: 6px; }
button.on { background: #b91c1c; border-color: #dc2626; color: #fff; }
button.quiet { background: transparent; color: var(--muted); border-color: var(--line); margin-left: auto; }
button:disabled { opacity: 0.45; cursor: not-allowed; }
.tabs { display: flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.tabs button { flex: 1; background: transparent; color: var(--muted); border: 0; border-radius: 0; }
.tabs button.sel { background: #232933; color: var(--text); box-shadow: inset 0 -2px 0 var(--accent); }
.net { display: grid; gap: 8px; }
.filebtn { font: inherit; padding: 6px 10px; border: 1px solid #2d333c; background: #1c2128; color: var(--text); border-radius: 6px; cursor: pointer; }
.filebtn.on { background: #b91c1c; border-color: #dc2626; color: #fff; }
.filebtn input { display: none; }
.meter { height: 6px; background: #1c2128; border-radius: 3px; overflow: hidden; }
.meter div { height: 100%; background: #4b5563; transition: width 80ms linear; }
.meter div.hot { background: var(--bad); }
.chip { background: #232933; color: var(--muted); border-radius: 4px; padding: 0 6px; }
.k-report .chip { background: rgba(52, 211, 153, 0.15); color: var(--ok); }
.k-order .chip { background: rgba(167, 139, 250, 0.15); color: #c4b5fd; }
.k-say_again .chip { background: rgba(245, 158, 11, 0.15); color: var(--warn); }
.log li.tx { padding: 6px 8px; }
.log li.k-ack, .log li.k-radio_check, .log li.k-call, .log li.k-request { opacity: 0.7; }
.log li.unid { background: rgba(248, 113, 113, 0.08); border-color: rgba(248, 113, 113, 0.35); }
.log li.empty { color: var(--muted); border-style: dashed; }
.how { font-size: 11px; color: #6b7380; }
.read.gone { text-decoration: line-through; opacity: 0.6; }
.tick { color: var(--ok); font-size: 12px; margin-left: 6px; }
.query { color: var(--warn); font-size: 12px; margin-left: 6px; }
.assumed { color: var(--muted); font-size: 12px; font-style: italic; }
.gridref { font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--muted); margin-left: 4px; white-space: nowrap; }
.actions { margin-top: 6px; display: flex; align-items: center; }
.heard { font-size: 12px; color: var(--text); background: #1c2128; padding: 4px 8px; border-radius: 6px; }
.scrub { display: grid; gap: 4px; color: var(--muted); font-size: 12px; }
.scrub input { accent-color: var(--accent); }
aside > * { flex-shrink: 0; }
.log { list-style: none; margin: 0; padding: 0; overflow-y: auto; display: grid; gap: 8px; align-content: start; flex: 1 1 auto; min-height: 0; }
.log li { padding: 8px; border: 1px solid var(--line); border-radius: 8px; background: var(--card); }
.log li.amb { border-style: dashed; border-color: var(--warn); }
.log li.bad { background: rgba(248, 113, 113, 0.08); border-color: rgba(248, 113, 113, 0.35); }
.log li.intent { background: rgba(167, 139, 250, 0.08); border-color: rgba(167, 139, 250, 0.35); }
.log li.gone { opacity: 0.5; }
.log li.gone .said, .log li.gone .read { text-decoration: line-through; }
.meta { display: flex; gap: 8px; font-size: 12px; color: var(--muted); flex-wrap: wrap; }
.said { margin: 2px 0; }
.read { color: #a7f3d0; }
.note { color: var(--warn); font-size: 12px; }
@media (max-width: 760px) {
  .layout { grid-template-columns: 1fr; grid-template-rows: 55vh 1fr; } aside { border-left: 0; border-top: 1px solid var(--line); }
  .legend { display: none; }
}
</style>
