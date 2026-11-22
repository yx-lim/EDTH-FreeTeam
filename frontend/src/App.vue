<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import maplibregl from 'maplibre-gl'
import ms from 'milsymbol'
import {
  Crosshair,
  Grid3x3,
  Info,
  Layers,
  LocateFixed,
  Navigation,
  PanelRightClose,
  PanelRightOpen,
  Radar,
  Target,
  Terminal,
  X,
} from 'lucide-vue-next'
import { createVad } from './vad.js'
import { createBrowserPtt, createRecorderPtt } from './ptt.js'
import { gridLines, mgrsAt } from './grid.js'
import {
  bearingDegrees,
  circleCoords,
  createOverlayCanvasImage,
  formatDistance,
  formatZuluTime,
  fovConeGeoJson,
  haversineMeters,
  headingToCardinal,
  playRadioTone,
  rangeRingsGeoJson,
  totalTrailDistance,
} from './tactical.js'
import TopBar from './components/TopBar.vue'
import ReplayBar from './components/ReplayBar.vue'
import CommandSidebar from './components/CommandSidebar.vue'
import PhoneMicModal from './components/PhoneMicModal.vue'
import HandsetView from './components/HandsetView.vue'

// Dedicated mobile wireless microphone view when opened on a phone via QR code (`/?handset=1`)
const isHandset = typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('handset')

const COLOURS = ['#60a5fa', '#22d3ee', '#a78bfa', '#34d399', '#93c5fd', '#c084fc']
const WALK_MPS = 1.5
const STALE_CAP_M = 1500
const STALE_S = 300
const SIDC = { solid: 'SFGPUCI--------', dashed: 'SFGAUCI--------' }
const SIDE = {
  hostile: { code: 'H', colour: '#f87171', word: 'enemy' },
  unknown: { code: 'U', colour: '#facc15', word: '' },
  neutral: { code: 'N', colour: '#4ade80', word: '' },
  friendly: { code: 'F', colour: '#60a5fa', word: 'friendly' },
}
const WHAT = {
  infantry: ['GPUCI', 'infantry'],
  sniper: ['GPUCIS', 'sniper'],
  tank: ['GPEVAT', 'tank'],
  apc: ['GPEVAA', 'armoured vehicle'],
  vehicle: ['GPEV', 'vehicle'],
  artillery: ['GPUCF', 'artillery'],
  drone: ['APMFQ', 'drone'],
  helicopter: ['APMH', 'helicopter'],
  aircraft: ['APMF', 'aircraft'],
  ied: ['GPEXI', 'IED'],
  civilians: ['GP', 'civilians'],
  unknown: ['GP', 'contact'],
}
const CONTACT_TTL_S = { drone: 180, helicopter: 300, aircraft: 120, artillery: 600, sniper: 1800, ied: 86400, civilians: 1800 }
const contactTtl = (c) => c?.ttl_s || CONTACT_TTL_S[c?.what] || 900
const persistent = (c) => c?.what === 'ied' || (c?.ttl_s || 0) >= 1800
const HEADING_DEG = { north: 0, northeast: 45, east: 90, southeast: 135, south: 180, southwest: 225, west: 270, northwest: 315 }
const sideOf = (c) => SIDE[c?.side] || SIDE.unknown
const sidc = (c, doubt) => {
  const f = (WHAT[c?.what] || WHAT.unknown)[0]
  return `S${sideOf(c).code}${f[0]}${doubt ? 'A' : 'P'}${f.slice(2)}`.padEnd(15, '-')
}

function describeContact(c, { spoken = false } = {}) {
  if (!c) return 'contact'
  const what = c.detail || (WHAT[c.what] || WHAT.unknown)[1]
  const n = c.count > 1 ? (spoken ? `${c.count} ` : `${c.count}× `) : ''
  const side = sideOf(c).word ? `${sideOf(c).word} ` : ''
  const unknown = c.side === 'unknown' || !SIDE[c.side] ? (spoken ? ', side unknown' : ' (side unknown)') : ''
  const act = c.activity === 'moving' ? `, moving${c.heading ? ' ' + c.heading : ''}` : c.activity ? `, ${c.activity}` : ''
  return `${n}${side}${what}${unknown}${act}`
}

const LEGEND = [
  ['SFGPUCI', 'Own unit (friendly)'],
  ['SHGPUCI', 'Hostile / enemy'],
  ['SUGPUCI', 'Side unknown'],
  ['SNGP', 'Neutral / civilians'],
].map(([code, label]) => ({ label, svg: new ms.Symbol(code.padEnd(15, '-'), { size: 13 }).asSVG() }))

const RASTER_BASEMAPS = {
  dark: {
    label: 'DARK OPS',
    tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
    attribution: '© OpenStreetMap contributors · Dark Ops',
    maxzoom: 19,
    grid: '#cbd5e1',
    halo: '#0b0d10',
    paint: {
      'raster-brightness-min': 0.92,
      'raster-brightness-max': 0.06,
      'raster-saturation': -0.85,
      'raster-hue-rotate': 180,
      'raster-contrast': 0.12,
    },
  },
  satellite: {
    label: 'SAT',
    tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
    attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
    maxzoom: 19,
    grid: '#ffffff',
    halo: '#000000',
    paint: { 'raster-brightness-max': 0.85 },
  },
  topo: {
    label: 'TOPO',
    tiles: ['a', 'b', 'c'].map((s) => `https://${s}.tile.opentopomap.org/{z}/{x}/{y}.png`),
    attribution: 'Map data © OpenStreetMap contributors, SRTM · OpenTopoMap',
    maxzoom: 17,
    grid: '#1f2937',
    halo: '#ffffff',
  },
  street: {
    label: 'STREET',
    tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
    attribution: '© OpenStreetMap contributors',
    maxzoom: 19,
    grid: '#1f2937',
    halo: '#ffffff',
  },
  offline: {
    label: 'OFFLINE',
    tiles: ['/api/tiles/{z}/{x}/{y}.jpg'],
    attribution: 'Local Paris Offline Map Cache (Zero Internet)',
    minzoom: 12,
    maxzoom: 16,
    grid: '#cbd5e1',
    halo: '#090e14',
    paint: {
      'raster-brightness-min': 0.92,
      'raster-brightness-max': 0.06,
      'raster-saturation': -0.85,
      'raster-hue-rotate': 180,
      'raster-contrast': 0.14,
    },
  },
}

const ALL_BASEMAPS = {
  ...RASTER_BASEMAPS,
}

const SPEECH_LANG = { en: 'en-GB', fr: 'fr-FR', uk: 'uk-UA', ru: 'ru-RU', auto: 'en-GB' }
const STT_LABELS = { elevenlabs: 'ElevenLabs', gemini: 'Gemini', mistral: 'Mistral', whisper: 'MLX Whisper' }
const KIND = {
  report: 'report',
  request: 'request',
  order: 'order',
  ack: 'ack',
  say_again: 'say again',
  radio_check: 'radio check',
  call: 'call',
  other: 'chatter',
}

// Core reactive state
const events = ref([])
const customPlaces = ref([])
const defaultCentre = ref([2.334, 48.851])
const callsign = ref('alpha 1')
const lang = ref('en')
const readBack = ref(true)
const cursor = ref(0)
const listening = ref(false)
const status = ref('connecting…')
const appAlert = ref('')
const serverStt = ref(null)
const sttOptions = ref([])
const heard = ref('')
const txStage = ref('STANDBY')
const levelBars = ref(Array(18).fill(14))
const now = ref(Date.now() / 1000)

// New features state
const offlineMode = ref(false)
const phoneModalOpen = ref(false)
const handsets = ref({ count: 0, transmitting: false, active_callsign: null })
const previewedEvent = ref(null)
const msgBusy = ref(false)
const msgStatus = ref('')
const demoBusy = ref(false)

// Persisted tactical look preferences
const saved = (() => {
  try {
    return JSON.parse(localStorage.getItem('mapLook')) || {}
  } catch {
    return {}
  }
})()
const basemap = ref(saved.basemap in ALL_BASEMAPS ? saved.basemap : 'dark')
const showGrid = ref(saved.showGrid ?? true)
const showRings = ref(saved.showRings ?? true)
const showFov = ref(saved.showFov ?? true)
const showContacts = ref(saved.showContacts ?? true)
const showLegend = ref(false)
const nvgMode = ref(!!saved.nvgMode)
const redNight = ref(!!saved.night)
const confirmGate = ref(!!saved.confirmGate)
const sidebarOpen = ref(saved.sidebarOpen ?? true)
const showMapHud = ref(saved.showMapHud ?? !sidebarOpen.value)

function toggleSidebar(force) {
  const next = typeof force === 'boolean' ? force : !sidebarOpen.value
  sidebarOpen.value = next
  // Auto-show the transparent game-style overlay when collapsing; hide duplication when expanding
  showMapHud.value = !next
  nextTick(() => map?.resize())
  window.setTimeout(() => map?.resize(), 230)
}

watch([basemap, showGrid, showRings, showFov, showContacts, nvgMode, redNight, confirmGate, sidebarOpen, showMapHud], () => {
  try {
    localStorage.setItem(
      'mapLook',
      JSON.stringify({
        basemap: basemap.value,
        showGrid: showGrid.value,
        showRings: showRings.value,
        showFov: showFov.value,
        showContacts: showContacts.value,
        nvgMode: nvgMode.value,
        night: redNight.value,
        confirmGate: confirmGate.value,
        sidebarOpen: sidebarOpen.value,
        showMapHud: showMapHud.value,
      }),
    )
  } catch {}
})

const activeTab = ref('sitrep')
const unitHeadings = ref({})
const tacOverlays = ref([])
const armedDrop = ref({ kind: null, label: null })

const cursorLngLat = ref(null)
const cursorGrid = ref('')

// Radio-net mode state
const txs = ref([])
const netOn = ref(false)
const netSource = ref('')
const netLevel = ref(0)
const netSpeaking = ref(false)
const netSegments = ref(0)
const netMsg = ref('')

let map, netRecogniser, ticker, flightTimer, socket, unmounted = false
let netCtx, netStream, netNode, netAudio, netVad, netQueue = Promise.resolve()
let waveCtx = null
let waveRaf = null
let offlineDataLoaded = false

const Speech = window.SpeechRecognition || window.webkitSpeechRecognition
const canRecord = !!navigator.mediaDevices?.getUserMedia
const canListen = computed(() => (serverStt.value && canRecord) || !!Speech)
const connected = computed(() => status.value === 'live')
const sttDisplayLabel = computed(() => STT_LABELS[serverStt.value] || serverStt.value || (Speech ? 'Browser' : 'Off'))

const visible = computed(() => events.value.slice(0, cursor.value))
const live = computed(() => cursor.value === events.value.length)
const isContact = (e) => e.type === 'contact'
const isPlottableOnMap = (e) => !confirmGate.value || !!e.confirmed
const callsigns = computed(() => [...new Set(events.value.filter((e) => !isContact(e)).map((e) => e.callsign))])

const age = (t) => {
  const s = Math.max(0, now.value - t)
  return s < 3600 ? `${Math.round(s / 60)} min` : s < 172800 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} days`
}
const ago = (t) => {
  const s = Math.max(0, now.value - t)
  return s < 60 ? `${Math.round(s)}s ago` : `${Math.round(s / 60)}m ago`
}

// Contacts that are currently active (filtered by confirmGate when strict gate is enabled!)
const allLiveContacts = computed(() => {
  const latest = new Map()
  const confirmed = new Set()
  visible.value.forEach((e) => {
    if (!isContact(e) || !e.ok || e.superseded) return
    latest.set(e.callsign, e)
    if (e.confirmed) confirmed.add(e.callsign)
  })
  return [...latest.values()]
    .filter((e) => !live.value || now.value - e.t <= contactTtl(e.contact) || persistent(e.contact))
    .map((e) => ({
      ...e,
      trackConfirmed: confirmed.has(e.callsign),
      expired: live.value && now.value - e.t > contactTtl(e.contact),
    }))
})

const contactsOnMap = computed(() => {
  if (!confirmGate.value) return allLiveContacts.value
  const latestConfirmed = new Map()
  visible.value.forEach((e) => {
    if (!isContact(e) || !e.ok || e.superseded || !e.confirmed) return
    latestConfirmed.set(e.callsign, e)
  })
  return [...latestConfirmed.values()]
    .filter((e) => !live.value || now.value - e.t <= contactTtl(e.contact) || persistent(e.contact))
    .map((e) => ({
      ...e,
      trackConfirmed: true,
      expired: live.value && now.value - e.t > contactTtl(e.contact),
    }))
})

const contactDoubt = (e) =>
  !(e.trackConfirmed || e.confirmed || e.corroborated) ||
  e.expired ||
  (live.value && now.value - e.t > contactTtl(e.contact) / 2)

const WARN_M = 300
const metres = ([lon1, lat1], [lon2, lat2]) =>
  Math.hypot((lon2 - lon1) * 111320 * Math.cos((lat1 * Math.PI) / 180), (lat2 - lat1) * 110540)
const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
const compass = ([lon1, lat1], [lon2, lat2]) =>
  COMPASS[
    Math.round(
      (((Math.atan2((lon2 - lon1) * Math.cos((lat1 * Math.PI) / 180), lat2 - lat1) * 180) / Math.PI + 360) % 360) / 45,
    ) % 8
  ]

function threatsTo(u) {
  return contactsOnMap.value
    .filter((c) => c.contact?.side === 'hostile')
    .map((c) => ({ c, d: Math.max(0, metres(u.centre, c.centre) - u.radius_m - c.radius_m) }))
    .filter((x) => x.d <= WARN_M)
    .sort((a, b) => a.d - b.d)
    .map(({ c, d }) => ({
      what: describeContact({ ...c.contact, activity: null }),
      d: Math.round(d / 10) * 10,
      dir: compass(u.centre, c.centre),
    }))
}

const colour = (c) => (callsigns.value.includes(c) ? COLOURS[callsigns.value.indexOf(c) % COLOURS.length] : '#60a5fa')
const byId = computed(() => new Map(events.value.map((e) => [e.id, e])))
const visibleTx = computed(() =>
  live.value ? txs.value : txs.value.filter((tx) => tx.t <= (visible.value.at(-1)?.t ?? 0)),
)
const tasks = computed(() => {
  const last = new Map()
  visible.value.forEach((e) => {
    if (e.type === 'order') last.set(e.callsign, e)
  })
  return [...last.values()].filter((e) => e.target && !e.reached && !e.superseded)
})
const netMeter = computed(() => Math.max(0, Math.min(100, ((20 * Math.log10(netLevel.value + 1e-6) + 60) / 60) * 100)))
const suspected = (e) => ((e.ambiguous || e.callsign_assumed) && !e.confirmed) || (live.value && now.value - e.t > STALE_S)

const unitRoster = computed(() => {
  const ok = visible.value.filter((e) => e.ok && !e.superseded && !isContact(e) && isPlottableOnMap(e))
  const latest = new Map()
  ok.forEach((e) => latest.set(e.callsign, e))
  return [...latest.values()]
    .sort((a, b) => b.t - a.t)
    .map((e) => {
      const isSusp = suspected(e)
      return {
        ...e,
        suspected: isSusp,
        colour: colour(e.callsign),
        svg: new ms.Symbol(isSusp ? SIDC.dashed : SIDC.solid, { size: 16 }).asSVG(),
        threats: showContacts.value ? threatsTo(e) : [],
        task: tasks.value.find((t) => t.callsign === e.callsign) || null,
      }
    })
})

const totalThreatCount = computed(() => unitRoster.value.reduce((acc, u) => acc + (u.threats.length > 0 ? 1 : 0), 0))

const activeUnitObj = computed(() => {
  const target = callsign.value.trim().toLowerCase()
  return unitRoster.value.find((u) => u.callsign.toLowerCase() === target) || unitRoster.value[0] || null
})

const activeUnitCentre = computed(() => activeUnitObj.value?.centre || defaultCentre.value)
const activeUnitRadius = computed(() => activeUnitObj.value?.radius_m || null)
const activeUnitGrid = computed(() =>
  activeUnitObj.value?.centre
    ? activeUnitObj.value.mgrs || mgrsAt(activeUnitObj.value.centre, { radius: activeUnitObj.value.radius_m })
    : mgrsAt(defaultCentre.value, { digits: 4 }),
)
const activeHeading = computed(() => {
  const cs = (activeUnitObj.value?.callsign || callsign.value || 'alpha 1').toLowerCase()
  return unitHeadings.value[cs] ?? 0
})

const activeTrailDistanceM = computed(() => {
  const targetCs = activeUnitObj.value?.callsign
  if (!targetCs) return 0
  const pts = visible.value
    .filter((e) => e.ok && !e.superseded && !isContact(e) && isPlottableOnMap(e) && e.callsign === targetCs && e.centre)
    .map((e) => e.centre)
  return totalTrailDistance(pts)
})

const hasSos = computed(() => tacOverlays.value.some((o) => o.kind === 'sos'))

const cursorDistance = computed(() =>
  cursorLngLat.value && activeUnitCentre.value ? haversineMeters(activeUnitCentre.value, cursorLngLat.value) : null,
)
const cursorBearing = computed(() =>
  cursorLngLat.value && activeUnitCentre.value ? Math.round(bearingDegrees(activeUnitCentre.value, cursorLngLat.value)) : null,
)

// Duty-Officer Confirmation Queue:
// - When confirmGate is ON (GATE: ON): holds EVERY unconfirmed plotted report before going on the map!
// - When confirmGate is OFF (AUTO-PLOT): reports auto-agree & confirm immediately — zero manual queue nagging!
const drafts = computed(() => {
  if (!live.value || !confirmGate.value) return []
  const latestUnits = new Map()
  visible.value.forEach((e) => {
    if (e.ok && !e.superseded && !isContact(e)) latestUnits.set(e.callsign, e)
  })
  const units = [...latestUnits.values()].filter((e) => !e.confirmed)
  const seen = allLiveContacts.value.filter((e) => !(e.trackConfirmed || e.confirmed))
  const rank = (e) => ((e.candidate_options || []).length > 1 ? 0 : isContact(e) ? (e.contact?.side === 'hostile' ? 1 : 2) : 3)
  return [...seen, ...units].sort((a, b) => rank(a) - rank(b) || b.t - a.t)
})

const draftSymbol = (e) => new ms.Symbol(isContact(e) ? sidc(e.contact, !e.confirmed) : SIDC.dashed, { size: 16 }).asSVG()
const draftTitle = (e) => (isContact(e) ? `${e.callsign} · ${describeContact(e.contact)}` : `${e.callsign} position`)
const draftWhy = (e) => {
  if ((e.candidate_options || []).length > 1) return `${e.candidate_options.length} matching places — pick one`
  if (confirmGate.value && !e.confirmed) return 'awaiting operator gate approval'
  return isContact(e)
    ? 'single report'
    : [e.ambiguous && 'place uncertain', e.callsign_assumed && 'callsign assumed'].filter(Boolean).join(', ')
}

const currentReplayTime = computed(() => (cursor.value > 0 ? visible.value.at(-1)?.t ?? null : null))

// Game-Style Transparent Top-Right Map HUD Feed & Live Process Line
const hudProcessInfo = computed(() => {
  if (listening.value) return { state: 'tx', text: 'TX LIVE · LISTENING [RELEASE SPACE TO SEND]' }
  if (handsets.value.transmitting) return { state: 'tx', text: `PHONE TX LIVE · ${(handsets.value.active_callsign || 'HANDSET').toUpperCase()}` }
  if (txStage.value === 'TRANSCRIBING' || txStage.value === 'PROCESSING') {
    const engine = offlineMode.value ? 'MLX WHISPER + OLLAMA' : (sttDisplayLabel.value || 'AI').toUpperCase()
    return { state: 'busy', text: `${txStage.value} (${engine})…` }
  }
  if (msgBusy.value) return { state: 'busy', text: 'EXTRACTING WHATSAPP / EMAIL INTEL…' }
  if (demoBusy.value) return { state: 'busy', text: 'RUNNING TACTICAL DEMO SEQUENCE…' }
  if (netOn.value) return { state: 'busy', text: `RADIO NET LIVE · ${netSegments.value} SEGMENTS` }
  const modeTag = offlineMode.value ? 'OFFLINE OPS · MLX + OLLAMA' : 'HYBRID AI'
  const gateTag = confirmGate.value ? `GATE ON (${drafts.value.length} HELD)` : 'AUTO-PLOT'
  return { state: 'idle', text: `${modeTag} · ${gateTag} · HOLD [SPACE] TO TALK` }
})

const gameHudFeed = computed(() => {
  return [...visible.value]
    .filter((e) => !e.superseded && !e.rejected)
    .reverse()
    .slice(0, 6)
    .map((e, idx) => {
      const isC = isContact(e)
      const title = isC
        ? describeContact(e.contact).toUpperCase()
        : `${formatCallsignTitle(e.callsign).toUpperCase()} · ${(e.type || 'POS').toUpperCase()}`
      const speedTag =
        isC && e.contact?.speed_mps != null
          ? `${Math.round(e.contact.speed_mps * 3.6)} km/h ${(e.contact.heading || '').toUpperCase()}`.trim()
          : ''
      return {
        raw: e,
        id: e.id,
        time: formatZuluTime(e.t),
        title,
        speedTag,
        colour: isC ? sideOf(e.contact).colour : colour(e.callsign),
        place: e.anchor ? String(e.anchor).split(',')[0].trim() : e.ok ? '' : 'NO FIX',
        mgrs: e.centre ? e.mgrs || mgrsAt(e.centre, { radius: e.radius_m }) : '',
        confirmed: !!e.confirmed,
        pending: confirmGate.value && e.ok && !e.confirmed,
        candidates: (e.candidate_options || []).length > 1 ? e.candidate_options : [],
        sub: idx < 2 ? e.parsed?.summary_en || (e.text ? `“${e.text}”` : '') : '',
        opacity: Math.max(0.58, 1 - idx * 0.085),
      }
    })
})

// --- API Actions -----------------------------------------------------------------------------------------------
async function chooseStt(name) {
  const r = await fetch('/api/stt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider: name }),
  })
  if (!r.ok) {
    heard.value = (await r.json().catch(() => ({}))).detail || 'could not switch speech-to-text'
    return
  }
  const out = await r.json()
  serverStt.value = out.provider
  sttOptions.value = out.available
}

async function setConfirmGate(enabled) {
  confirmGate.value = !!enabled
  const autoConfirm = !confirmGate.value
  try {
    const r = await fetch('/api/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_confirm: autoConfirm }),
    })
    if (r.ok) {
      playRadioTone('ack')
    }
  } catch {}
}

async function toggleOfflineMode() {
  const next = !offlineMode.value
  const r = await fetch('/api/mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ offline: next }),
  })
  if (r.ok) {
    const out = await r.json()
    offlineMode.value = !!out.offline
    if (offlineMode.value) {
      basemap.value = 'offline'
      heard.value = 'OFFLINE OPS ENABLED · MLX Whisper (EN/FR/UK) + Ollama qwen2.5:3b + Local Paris Map (zero internet)'
    } else {
      if (basemap.value === 'offline') basemap.value = 'dark'
      heard.value = 'HYBRID AI MODE · Gemini + ElevenLabs + OSM Grounding active'
    }
  }
}

async function confirmEvent(e) {
  await fetch(`/api/events/${e.id}/confirm`, { method: 'POST' })
  playRadioTone('ack')
  if (e.centre) focusCoords(e.centre)
}

async function confirmAllDrafts() {
  for (const d of [...drafts.value]) {
    await fetch(`/api/events/${d.id}/confirm`, { method: 'POST' })
  }
  playRadioTone('ack')
}

async function rejectEvent(e) {
  await fetch(`/api/events/${e.id}/reject`, { method: 'POST' })
  if (previewedEvent.value?.id === e.id) previewedEvent.value = null
}

async function pickCandidate(eventId, index) {
  const r = await fetch(`/api/events/${eventId}/pick`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ index }),
  })
  if (r.ok) {
    const updated = await r.json()
    playRadioTone('ack')
    if (updated.centre) focusCoords(updated.centre)
  }
}

async function editEvent(eventId, patch) {
  const r = await fetch(`/api/events/${eventId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (r.ok) playRadioTone('ack')
}

async function ingestMessages({ text, channel }) {
  msgBusy.value = true
  msgStatus.value = 'Extracting tactical entities, quantities & coordinates...'
  try {
    const r = await fetch('/api/ingest/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        channel,
        default_callsign: callsign.value || null,
        heading: activeHeading.value,
      }),
    })
    const out = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(out.detail || `Ingest failed (${r.status})`)
    msgStatus.value = `Extracted ${out.parsed_count} message(s) via ${(out.channel || channel).toUpperCase()} → ${out.events?.length || 0} tactical report(s)`
    playRadioTone('ack')
    activeTab.value = 'sitrep'
  } catch (err) {
    msgStatus.value = `Extraction failed: ${err.message}`
  } finally {
    msgBusy.value = false
  }
}

async function runDemoScenario(kind) {
  if (demoBusy.value) return
  demoBusy.value = true
  activeTab.value = 'sitrep'
  const scripts = {
    en: [
      { lang: 'en', text: 'Zero, this is Alpha two, south of the Saint-Sulpice church, over' },
      { lang: 'en', text: 'Bravo one, contact, 2 enemy tanks at the tower, over' },
      { lang: 'en', text: 'Zero, this is Charlie one, 3 enemy infantry moving east, 200 metres north of the Medici fountain, over' },
    ],
    uk: [
      { lang: 'uk', text: 'Вежа, я Сокіл, на Ромашці, без змін, прийом.' },
      { lang: 'uk', text: 'Вежа, я Граніт, бачу 3 ворожих танки біля церкви Сен-Сюльпіс, рухаються на схід, прийом.' },
      { lang: 'uk', text: "Вежа, я Граніт, ждун біля Сараю, метрів п'ятдесят на захід, не підходити, прийом." },
    ],
    mixed: [
      { lang: 'en', text: 'Zero, this is Alpha two, 100 metres south of Saint-Sulpice church, over' },
      { lang: 'uk', text: 'Вежа, я Сокіл, на Ромашці, прийом.' },
      { lang: 'uk', text: 'Вежа, я Граніт, бачу 3 ворожих танки біля церкви Сен-Сюльпіс, прийом.' },
      { lang: 'en', text: 'Bravo one, contact, 2 enemy tanks at the tower, over' },
    ],
  }
  try {
    for (const step of scripts[kind] || scripts.en) {
      lang.value = step.lang
      await send(step.text)
      await new Promise((r) => window.setTimeout(r, 400))
    }
  } finally {
    demoBusy.value = false
  }
}

async function reset() {
  await fetch('/api/reset', { method: 'POST' })
  tacOverlays.value = []
  previewedEvent.value = null
  heard.value = ''
  netMsg.value = ''
}

function stepHeading(delta) {
  const cs = (activeUnitObj.value?.callsign || callsign.value || 'alpha 1').toLowerCase()
  const next = ((unitHeadings.value[cs] ?? 0) + delta + 360) % 360
  unitHeadings.value = { ...unitHeadings.value, [cs]: next }
}

function focusCoords(lngLat) {
  if (!map || !lngLat) return
  map.flyTo({ center: lngLat, zoom: Math.max(map.getZoom(), 15.2), duration: 700 })
}

function selectUnit(u) {
  callsign.value = u.callsign
  if (u.centre) focusCoords(u.centre)
}

function toggleNvg() {
  nvgMode.value = !nvgMode.value
  if (nvgMode.value) redNight.value = false
}

function toggleRedNight() {
  redNight.value = !redNight.value
  if (redNight.value) nvgMode.value = false
}

// --- Defense C2 Ops: SOS, Marker Drop, 9-Line MEDEVAC, SALUTE --------------------------------------------------
function triggerSos() {
  const pos = activeUnitCentre.value
  const cs = callsign.value.trim() || activeUnitObj.value?.callsign || 'alpha 1'
  const gridStr = mgrsAt(pos, { digits: 4 })
  tacOverlays.value = [
    ...tacOverlays.value.filter((o) => o.kind !== 'sos'),
    { id: `sos-${Date.now()}`, kind: 'sos', label: `SOS · ${cs.toUpperCase()}`, coords: [...pos] },
  ]
  playRadioTone('sos')
  if (readBack.value && window.speechSynthesis) {
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(`Priority alert. ${cs} SOS man down beacon activated at grid ${gridStr}.`)
    u.lang = SPEECH_LANG[lang.value]
    window.speechSynthesis.speak(u)
  }
  focusCoords(pos)
}

function clearSos() {
  tacOverlays.value = tacOverlays.value.filter((o) => o.kind !== 'sos')
}

async function dropTacticalPin(kind, coords, customLabel = null) {
  const cs = callsign.value.trim() || activeUnitObj.value?.callsign || 'alpha 1'
  const gridStr = mgrsAt(coords, { digits: 4 })
  if (kind === 'hostile') {
    const what = customLabel || 'enemy infantry'
    const text = `Zero, this is ${cs}, contact, ${what.toLowerCase().includes('enemy') || what.toLowerCase().includes('hostile') ? what : `enemy ${what}`}, at grid ${gridStr}, over`
    await send(text)
    focusCoords(coords)
  } else if (kind === 'hazard') {
    const text = `Zero, this is ${cs}, contact, enemy IED hazard, at grid ${gridStr}, over`
    await send(text)
    focusCoords(coords)
  } else if (kind === 'medevac' || kind === 'rally') {
    const label = customLabel || (kind === 'medevac' ? `LZ ${tacOverlays.value.length + 1}` : `Rally ${tacOverlays.value.length + 1}`)
    await fetch('/api/places', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: label, lon: coords[0], lat: coords[1] }),
    })
    tacOverlays.value = [...tacOverlays.value, { id: `${kind}-${Date.now()}`, kind, label, coords: [...coords] }]
    playRadioTone('ack')
    focusCoords(coords)
  }
}

async function handleSubmitMedevac(form) {
  const coords = activeUnitCentre.value
  const cs = callsign.value.trim() || activeUnitObj.value?.callsign || 'alpha 1'
  const label = `LZ ${cs.toUpperCase()}`
  await fetch('/api/places', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: label, lon: coords[0], lat: coords[1] }),
  })
  tacOverlays.value = [
    ...tacOverlays.value,
    { id: `medevac-${Date.now()}`, kind: 'medevac', label: `${label} (${form.precedence.slice(0, 1)})`, coords: [...coords] },
  ]
  const gridStr = mgrsAt(coords, { digits: 4 })
  heard.value = `9-LINE MEDEVAC TX · ${label} · ${gridStr} · ${form.precedence} · ${form.patients} · SEC ${form.security}`
  playRadioTone('ack')
  focusCoords(coords)
}

async function handleSubmitSalute(form) {
  const coords = activeUnitCentre.value
  const cs = callsign.value.trim() || activeUnitObj.value?.callsign || 'alpha 1'
  const gridStr = mgrsAt(coords, { digits: 4 })
  const sideWord = form.side === 'hostile' ? 'enemy ' : form.side === 'neutral' ? 'civilian ' : ''
  const whatWord = form.what === 'apc' ? 'armoured vehicle' : form.what === 'ied' ? 'IED' : form.what
  const countStr = form.count > 1 ? `${form.count} ` : ''
  const actStr = form.activity === 'moving' ? `, moving ${form.heading}` : `, ${form.activity}`
  const reportText = `Zero, this is ${cs}, contact, ${countStr}${sideWord}${whatWord}${actStr}, at grid ${gridStr}, over`
  await send(reportText)
  focusCoords(coords)
}

function removeOverlay(id) {
  tacOverlays.value = tacOverlays.value.filter((o) => o.id !== id)
}

// --- Airborne UAV / Flying Object Live Vector & Directional Arrow Physics -------------------------------------
const AIRBORNE_WHATS = new Set(['drone', 'helicopter', 'aircraft'])
const isAirborneContact = (c) => AIRBORNE_WHATS.has(c?.what)

function airborneHeadingDeg(c) {
  if (!c) return null
  if (typeof c.heading_deg === 'number' && Number.isFinite(c.heading_deg)) return ((c.heading_deg % 360) + 360) % 360
  if (c.heading && c.heading in HEADING_DEG) return HEADING_DEG[c.heading]
  return null
}

function airborneSpeedMps(c) {
  if (!c) return 0
  if (c.activity === 'static' || /waiting|hover|ждун/i.test(c.detail || '')) return 0
  if (typeof c.speed_mps === 'number' && Number.isFinite(c.speed_mps) && c.speed_mps >= 0) return c.speed_mps
  const hasDir = airborneHeadingDeg(c) != null
  if (!hasDir && c.activity !== 'moving') return 0
  const det = (c.detail || '').toLowerCase()
  if (det.includes('shahed') || det.includes('geran') || det.includes('мопед')) return 50
  if (det.includes('orlan') || det.includes('lancet')) return 30
  if (c.what === 'aircraft') return 140
  if (c.what === 'helicopter') return 55
  return 18 // default tactical UAV / FPV cruise (~65 km/h)
}

function offsetLonLat([lon0, lat0], bearingDeg, distM) {
  if (!distM || bearingDeg == null) return [lon0, lat0]
  const rad = (bearingDeg * Math.PI) / 180
  const dNorth = distM * Math.cos(rad)
  const dEast = distM * Math.sin(rad)
  const lat = lat0 + dNorth / 110540
  const lon = lon0 + dEast / (111320 * Math.max(0.15, Math.cos((lat0 * Math.PI) / 180)))
  return [lon, lat]
}

function airborneLiveState(e, nowSec) {
  const c = e.contact || {}
  const headingDeg = airborneHeadingDeg(c)
  const speedMps = airborneSpeedMps(c)
  const moving = headingDeg != null && speedMps > 0
  const ttlCap = contactTtl(c)
  const elapsed = live.value ? Math.max(0, Math.min(nowSec - e.t, ttlCap)) : 0
  const travelledM = moving ? speedMps * elapsed : 0
  const pos = moving ? offsetLonLat(e.centre, headingDeg, travelledM) : e.centre
  const leadEnd = moving ? offsetLonLat(pos, headingDeg, Math.max(70, Math.min(450, speedMps * 12))) : null
  const speedKmh = Math.round(speedMps * 3.6)
  return { headingDeg, speedMps, speedKmh, moving, elapsed, travelledM, pos, leadEnd }
}

function renderAirborne(nowSec = Date.now() / 1000) {
  if (!map?.getSource('airborne')) return
  const seen = showContacts.value ? contactsOnMap.value : []
  const airSeen = seen.filter((e) => isAirborneContact(e.contact))
  const trackFeatures = []
  const vectorFeatures = []
  const arrowFeatures = []

  for (const e of airSeen) {
    const st = airborneLiveState(e, nowSec)
    const colourHex = sideOf(e.contact).colour
    const desc = describeContact(e.contact)
    const dirLabel = st.headingDeg != null ? headingToCardinal(st.headingDeg) : ''
    const speedTag = st.moving ? `${st.speedKmh} km/h ${dirLabel}` : 'HOVER · 0 km/h'
    const compactLabel = `${desc} • ${speedTag}`

    if (st.moving && st.travelledM > 2) {
      trackFeatures.push({
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: [e.centre, st.pos] },
        properties: { colour: colourHex },
      })
    }
    if (st.moving && st.leadEnd) {
      vectorFeatures.push({
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: [st.pos, st.leadEnd] },
        properties: { colour: colourHex },
      })
    }

    arrowFeatures.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: st.pos },
      properties: {
        icon: st.moving ? 'flight-arrow' : 'hover-arrow',
        colour: colourHex,
        heading: st.headingDeg ?? 0,
        label: compactLabel,
        title: desc.toUpperCase(),
        lat: Number(st.pos[1]).toFixed(5),
        lon: Number(st.pos[0]).toFixed(4),
        margin: Math.round(e.radius_m || 0),
        mgrs: mgrsAt(st.pos, { radius: e.radius_m }),
        detail: e.seen_by?.length ? `seen by ${e.seen_by.join(', ')}` : 'airborne track',
        flight: st.moving
          ? `${String(Math.round(st.headingDeg)).padStart(3, '0')}° ${dirLabel} · ${st.speedKmh} km/h (${st.speedMps.toFixed(1)} m/s) · +${Math.round(st.travelledM)}m`
          : 'HOVER / STATIC · 0 km/h',
        threat: '',
      },
    })
  }

  map.getSource('airborne-tracks').setData({ type: 'FeatureCollection', features: trackFeatures })
  map.getSource('airborne-vectors').setData({ type: 'FeatureCollection', features: vectorFeatures })
  map.getSource('airborne').setData({ type: 'FeatureCollection', features: arrowFeatures })
}

// --- MapLibre Rendering ----------------------------------------------------------------------------------------
function formatCallsignTitle(cs) {
  if (!cs) return 'Unit'
  return cs
    .split(/\s+/)
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : ''))
    .join(' ')
}

function escapeHtml(s) {
  return String(s ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function render() {
  if (!map?.getSource('regions')) return
  const ok = visible.value.filter((e) => e.ok && !e.superseded && !isContact(e) && isPlottableOnMap(e))
  const latest = new Map()
  ok.forEach((e) => latest.set(e.callsign, e))
  const current = [...latest.values()]
  const threatened = current.map((e) => [e, showContacts.value ? threatsTo(e) : []]).filter(([, t]) => t.length)

  const unitFeatureProps = (e) => {
    const t = threatened.find(([u]) => u === e)?.[1] || []
    const title = formatCallsignTitle(e.callsign)
    const mgrs = e.mgrs || mgrsAt(e.centre, { radius: e.radius_m })
    return {
      icon: `ms:${suspected(e) ? SIDC.dashed : SIDC.solid}`,
      label: live.value ? `${title} • ${ago(e.t)}` : title,
      colour: t.length ? SIDE.hostile.colour : colour(e.callsign),
      title,
      lat: Number(e.centre[1]).toFixed(5),
      lon: Number(e.centre[0]).toFixed(4),
      margin: Math.round(e.radius_m || 0),
      mgrs,
      detail: e.anchor || '',
      threat: t.length ? `⚠ ${t[0].what} ${t[0].d ? `${t[0].d}m ${t[0].dir}` : 'at position'}` : '',
    }
  }

  map.getSource('units').setData({
    type: 'FeatureCollection',
    features: current.map((e) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: e.centre },
      properties: unitFeatureProps(e),
    })),
  })
  map.getSource('regions').setData({
    type: 'FeatureCollection',
    features: ok.map((e) => ({
      type: 'Feature',
      geometry: e.region,
      properties: { colour: colour(e.callsign), current: latest.get(e.callsign) === e, ambiguous: !!e.ambiguous },
    })),
  })
  map.getSource('paths').setData({
    type: 'FeatureCollection',
    features: callsigns.value
      .map((c) => ({
        type: 'Feature',
        properties: { colour: colour(c) },
        geometry: { type: 'LineString', coordinates: ok.filter((e) => e.callsign === c).map((e) => e.centre) },
      }))
      .filter((f) => f.geometry.coordinates.length > 1),
  })
  map.getSource('stale').setData({
    type: 'FeatureCollection',
    features: live.value
      ? current.map((e) => ({
          type: 'Feature',
          properties: { colour: colour(e.callsign) },
          geometry: {
            type: 'Polygon',
            coordinates: [circleCoords(e.centre, Math.min(STALE_CAP_M, e.radius_m + WALK_MPS * Math.max(0, now.value - e.t)), 48)],
          },
        }))
      : [],
  })

  map.getSource('labels').setData({
    type: 'FeatureCollection',
    features: current.map((e) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: e.centre },
      properties: unitFeatureProps(e),
    })),
  })
  map.getSource('threat').setData({
    type: 'FeatureCollection',
    features: threatened.map(([e]) => ({
      type: 'Feature',
      properties: {},
      geometry: { type: 'Polygon', coordinates: [circleCoords(e.centre, e.radius_m + 25, 48)] },
    })),
  })
  map.getSource('tasks').setData({
    type: 'FeatureCollection',
    features: tasks.value.map((e) => ({
      type: 'Feature',
      geometry: e.target.region,
      properties: { colour: colour(e.callsign), label: `${formatCallsignTitle(e.callsign)} ▸ ${e.target.anchor}` },
    })),
  })

  const seen = showContacts.value ? contactsOnMap.value : []
  const groundSeen = seen.filter((e) => !isAirborneContact(e.contact))
  map.getSource('contact-regions').setData({
    type: 'FeatureCollection',
    features: groundSeen.map((e) => ({
      type: 'Feature',
      geometry: e.region,
      properties: { colour: sideOf(e.contact).colour },
    })),
  })
  map.getSource('contacts').setData({
    type: 'FeatureCollection',
    features: groundSeen.map((e) => {
      const desc = describeContact(e.contact)
      const timeTag = e.expired ? `${age(e.t)} old` : live.value ? ago(e.t) : ''
      return {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: e.centre },
        properties: {
          icon: `ms:${sidc(e.contact, contactDoubt(e))}`,
          colour: sideOf(e.contact).colour,
          heading: HEADING_DEG[e.contact?.heading] ?? null,
          label: timeTag ? `${desc} • ${timeTag}` : desc,
          title: desc.toUpperCase(),
          lat: Number(e.centre[1]).toFixed(5),
          lon: Number(e.centre[0]).toFixed(4),
          margin: Math.round(e.radius_m || 0),
          mgrs: e.mgrs || mgrsAt(e.centre, { radius: e.radius_m }),
          detail: e.seen_by?.length ? `seen by ${e.seen_by.join(', ')}` : 'reporter unknown',
          flight: '',
          threat: '',
        },
      }
    }),
  })
  renderAirborne(Date.now() / 1000)
  map.getSource('custom').setData({
    type: 'FeatureCollection',
    features: customPlaces.value.map((p) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
      properties: { label: p.name },
    })),
  })

  map.getSource('range-rings').setData(showRings.value ? rangeRingsGeoJson(activeUnitCentre.value) : { type: 'FeatureCollection', features: [] })
  map.getSource('fov-cone').setData(
    showFov.value ? fovConeGeoJson(activeUnitCentre.value, activeHeading.value, 280, 28) : { type: 'FeatureCollection', features: [] },
  )
  map.getSource('tac-overlays').setData({
    type: 'FeatureCollection',
    features: tacOverlays.value.map((o) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: o.coords },
      properties: { icon: `ov-${o.kind}`, label: o.label, kind: o.kind },
    })),
  })

  // Staged Preview & Ambiguous Candidate Ghost Pins (?1 / ?2 / ?3 / ?4)
  const focusEv =
    previewedEvent.value ||
    drafts.value.find((d) => (d.candidate_options || []).length > 1) ||
    (confirmGate.value ? drafts.value[0] : null)

  const candPolys = []
  const candPts = []
  if (focusEv) {
    if ((focusEv.candidate_options || []).length > 1) {
      for (const c of focusEv.candidate_options) {
        if (c.region) candPolys.push({ type: 'Feature', geometry: c.region, properties: { label: `?${c.index + 1}` } })
        if (c.centre) {
          candPts.push({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: c.centre },
            properties: { label: `?${c.index + 1} ${c.name}` },
          })
        }
      }
    } else if (confirmGate.value && !focusEv.confirmed && focusEv.region) {
      candPolys.push({ type: 'Feature', geometry: focusEv.region, properties: { label: 'STAGED' } })
      if (focusEv.centre) {
        candPts.push({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: focusEv.centre },
          properties: { label: `⏳ STAGED: ${focusEv.anchor}` },
        })
      }
    }
  }
  map.getSource('candidate-regions')?.setData({ type: 'FeatureCollection', features: candPolys })
  map.getSource('candidate-points')?.setData({ type: 'FeatureCollection', features: candPts })
}

watch(
  [
    visible,
    callsigns,
    customPlaces,
    now,
    tasks,
    showContacts,
    showRings,
    showFov,
    activeUnitCentre,
    activeHeading,
    tacOverlays,
    confirmGate,
    previewedEvent,
    drafts,
  ],
  render,
)

function updateGrid() {
  if (!map?.getSource('grid')) return
  const g = showGrid.value ? gridLines(map.getBounds(), map.getZoom()) : null
  map.getSource('grid').setData(g?.lines ?? { type: 'FeatureCollection', features: [] })
  map.getSource('grid-labels').setData(g?.labels ?? { type: 'FeatureCollection', features: [] })
}

async function ensureOfflineBasemapLoaded() {
  if (offlineDataLoaded || !map?.getSource('offline-vec')) return
  const data = await fetch('/api/offline-basemap.geojson').then((r) => (r.ok ? r.json() : null)).catch(() => null)
  if (data && map?.getSource('offline-vec')) {
    map.getSource('offline-vec').setData(data)
    offlineDataLoaded = true
  }
}

function applyBasemap() {
  if (!map?.getLayer('grid-line')) return
  const b = ALL_BASEMAPS[basemap.value] || ALL_BASEMAPS.dark
  for (const id of Object.keys(RASTER_BASEMAPS)) {
    map.setLayoutProperty(`base-${id}`, 'visibility', id === basemap.value ? 'visible' : 'none')
  }
  // Keep vector street overlay off when crisp pre-cached Paris offline raster tiles are active
  for (const lyr of ['offline-parks', 'offline-buildings', 'offline-streets', 'offline-streets-major', 'offline-labels']) {
    if (map.getLayer(lyr)) map.setLayoutProperty(lyr, 'visibility', 'none')
  }
  map.setPaintProperty('grid-line', 'line-color', b.grid)
  map.setPaintProperty('grid-label', 'text-color', b.grid)
  map.setPaintProperty('grid-label', 'text-halo-color', b.halo)
}
watch(basemap, applyBasemap)
watch(showGrid, updateGrid)

function flightArrowImage() {
  // Bold swept directional flight chevron arrow pointing 0° North (SDF tinted by side colour)
  const size = 96
  const c = document.createElement('canvas')
  c.width = c.height = size
  const g = c.getContext('2d')
  g.fillStyle = '#ffffff'
  g.strokeStyle = '#ffffff'
  g.lineJoin = 'round'
  g.beginPath()
  g.moveTo(size / 2, 6)               // sharp nose tip
  g.lineTo(size - 14, size - 16)     // right swept wingtip
  g.lineTo(size / 2, size - 32)      // inner tail notch
  g.lineTo(14, size - 16)            // left swept wingtip
  g.closePath()
  g.fill()
  g.lineWidth = 4
  g.stroke()
  return { width: size, height: size, data: new Uint8Array(g.getImageData(0, 0, size, size).data.buffer) }
}

function hoverArrowImage() {
  // Hovering / stationary UAV radar ring + inner directional chevron (SDF tinted by side colour)
  const size = 96
  const c = document.createElement('canvas')
  c.width = c.height = size
  const g = c.getContext('2d')
  g.strokeStyle = '#ffffff'
  g.fillStyle = '#ffffff'
  g.lineWidth = 5
  g.beginPath()
  g.arc(size / 2, size / 2, 34, 0, Math.PI * 2)
  g.stroke()
  g.beginPath()
  g.moveTo(size / 2, 22)
  g.lineTo(size / 2 + 18, 62)
  g.lineTo(size / 2, 52)
  g.lineTo(size / 2 - 18, 62)
  g.closePath()
  g.fill()
  return { width: size, height: size, data: new Uint8Array(g.getImageData(0, 0, size, size).data.buffer) }
}

function arrowImage() {
  const size = 96
  const c = document.createElement('canvas')
  c.width = c.height = size
  const g = c.getContext('2d')
  g.strokeStyle = g.fillStyle = '#ffffff'
  g.lineWidth = 6
  g.beginPath()
  g.moveTo(size / 2, size / 2 - 22)
  g.lineTo(size / 2, 8)
  g.stroke()
  g.beginPath()
  g.moveTo(size / 2, 0)
  g.lineTo(size / 2 - 11, 18)
  g.lineTo(size / 2 + 11, 18)
  g.closePath()
  g.fill()
  return { width: size, height: size, data: new Uint8Array(g.getImageData(0, 0, size, size).data.buffer) }
}

function addSymbolImage(ev) {
  if (!ev.id.startsWith('ms:') || map.hasImage(ev.id)) return
  const ratio = window.devicePixelRatio || 1
  const canvas = new ms.Symbol(ev.id.slice(3), { size: 28 }).asCanvas(ratio)
  map.addImage(ev.id, canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height), { pixelRatio: ratio })
}

function add(event) {
  const atEnd = cursor.value === events.value.length
  events.value.push(event)
  if (atEnd) cursor.value = events.value.length
  if (event.ok && event.centre && isPlottableOnMap(event)) {
    map?.flyTo({ center: event.centre, zoom: Math.max(map.getZoom(), 15.0), duration: 900 })
  }
  if (event.identifies) {
    const held = events.value.find((x) => x.id === event.identifies)
    if (held) {
      held.identified_as = event.callsign
      events.value = [...events.value]
    }
  }
}

function speak(e) {
  if (!readBack.value || !window.speechSynthesis || e.source?.startsWith('radio')) return
  let msg
  if (e.type === 'contact') {
    const who = e.speaker || 'Station'
    msg = e.ok
      ? `${who}, contact, ${describeContact(e.contact, { spoken: true })}, ${e.parsed?.relation === 'at' ? 'at' : (e.parsed?.relation || '').replaceAll('_', ' ')} ${e.anchor}.`
      : `${who}, contact copied. Say again its location.`
  } else if (e.type === 'unidentified') {
    msg =
      {
        fr: 'Station qui appelle, répétez votre indicatif.',
        uk: "Хто на зв'язку, повторіть позивний.",
        ru: 'Кто на связи, повторите позывной.',
      }[lang.value] || 'Station calling, say again your callsign.'
  } else if (e.ok) {
    msg = `${e.callsign}, ${e.parsed?.relation === 'at' ? 'at' : (e.parsed?.relation || '').replaceAll('_', ' ')} ${e.anchor}`
  } else if (e.type === 'intent') {
    msg = `${e.callsign}, copy intention.`
  } else {
    msg = `${e.callsign}, say again. ${e.note || ''}`
  }
  const warn = (e.threats || []).map(
    (w) =>
      `${w.callsign}, ${describeContact({ ...w.contact, activity: null }, { spoken: true })} ${w.distance_m ? `${w.distance_m} metres ${w.direction} of you` : 'at your position'}.`,
  )
  if (warn.length) msg = `Warning. ${warn.join(' ')} ${msg}`
  window.speechSynthesis.cancel()
  const u = new SpeechSynthesisUtterance(msg)
  u.lang = SPEECH_LANG[lang.value]
  window.speechSynthesis.speak(u)
}

async function send(body, { voice = false } = {}) {
  const trimmed = (body || '').trim()
  if (!trimmed) return
  txStage.value = 'PROCESSING'
  playRadioTone('ptt_start')
  try {
    const r = await fetch('/api/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: trimmed, callsign: callsign.value, heading: activeHeading.value }),
    })
    const out = await r.json().catch(() => ({}))
    if (r.ok) {
      out.events?.forEach(speak)
      txStage.value = 'ACK RECEIVED'
      playRadioTone('ack')
    } else {
      txStage.value = 'TX FAULT'
      appAlert.value = out.detail || `Report failed (${r.status})`
    }
    if (r.ok && !out.events?.length) heard.value = `heard “${trimmed}”: ignored, no callsign or place`
    else if (voice) heard.value = `heard: “${trimmed}”`
  } catch (err) {
    txStage.value = 'TX FAULT'
    appAlert.value = `Network error: ${err.message}`
  } finally {
    window.setTimeout(() => {
      if (!listening.value) txStage.value = 'STANDBY'
    }, 2000)
  }
}

// --- Live Waveform & Push-to-Talk (ptt.js preserved 100%) ------------------------------------------------------
function startWaveform(stream) {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext
    if (!AudioCtx) return
    waveCtx = new AudioCtx()
    const source = waveCtx.createMediaStreamSource(stream)
    const analyser = waveCtx.createAnalyser()
    analyser.fftSize = 64
    source.connect(analyser)
    const data = new Uint8Array(analyser.frequencyBinCount)
    const tick = () => {
      analyser.getByteFrequencyData(data)
      const bars = []
      for (let i = 0; i < 18; i += 1) {
        bars.push(Math.max(12, Math.min(100, Math.round(((data[i] || 0) / 255) * 100))))
      }
      levelBars.value = bars
      waveRaf = window.requestAnimationFrame(tick)
    }
    tick()
  } catch {}
}

function stopWaveform() {
  if (waveRaf) {
    window.cancelAnimationFrame(waveRaf)
    waveRaf = null
  }
  if (waveCtx) {
    waveCtx.close().catch(() => {})
    waveCtx = null
  }
  levelBars.value = Array(18).fill(14)
}

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

async function recordStart() {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, noiseSuppression: true, echoCancellation: true },
  })
  startWaveform(stream)
  const chunks = []
  const recorder = new MediaRecorder(stream)
  recorder.ondataavailable = (e) => chunks.push(e.data)
  recorder.start()
  return { stream, recorder, chunks }
}

async function recordHalt({ stream, recorder }) {
  stopWaveform()
  const stopped = new Promise((r) => {
    recorder.onstop = r
  })
  recorder.stop()
  await stopped
  stream.getTracks().forEach((t) => t.stop())
}

async function recordStop(handle) {
  await recordHalt(handle)
  const { chunks } = handle
  const ctx = new AudioContext()
  const decoded = await ctx.decodeAudioData(await new Blob(chunks).arrayBuffer())
  ctx.close()
  const off = new OfflineAudioContext(1, Math.ceil(decoded.duration * 16000), 16000)
  const src = off.createBufferSource()
  src.buffer = decoded
  src.connect(off.destination)
  src.start()
  const wav = encodeWav((await off.startRendering()).getChannelData(0), 16000)
  heard.value = 'transcribing…'
  txStage.value = 'TRANSCRIBING'
  const r = await fetch(
    `/api/audio?callsign=${encodeURIComponent(callsign.value)}&lang=${lang.value}&heading=${Math.round(activeHeading.value)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'audio/wav' },
      body: wav,
    },
  )
  if (r.status === 501) {
    serverStt.value = null
    heard.value = 'server speech-to-text off; using the browser'
    txStage.value = 'STANDBY'
    return
  }
  const out = await r.json().catch(() => ({}))
  if (r.ok) {
    out.events?.forEach(speak)
    txStage.value = 'ACK RECEIVED'
    playRadioTone('ack')
  } else {
    txStage.value = 'TX FAULT'
  }
  heard.value = !r.ok
    ? `speech-to-text failed: ${out.detail || r.status}`
    : out.transcript && !out.events?.length
      ? `heard “${out.transcript}”: ignored, no callsign or place`
      : `heard: “${out.transcript}”`
  window.setTimeout(() => {
    if (!listening.value) txStage.value = 'STANDBY'
  }, 2200)
}

let held = false
const browserPtt =
  Speech &&
  createBrowserPtt({
    Speech,
    lang: () => SPEECH_LANG[lang.value],
    onSend: (t) => send(t, { voice: true }),
    onHeard: (h) => {
      heard.value = h
    },
    onListening: (v) => {
      listening.value = v
      txStage.value = v ? 'TX LIVE' : 'STANDBY'
    },
  })
const recorderPtt = createRecorderPtt({
  open: recordStart,
  close: recordStop,
  discard: recordHalt,
  onListening: (v) => {
    listening.value = v
    if (v) txStage.value = 'TX LIVE'
  },
})

async function talk(start) {
  if (!canListen.value || start === held) return
  if (start && netOn.value && netSource.value === 'browser') {
    heard.value = 'stop the radio net first: the browser has one recogniser'
    return
  }
  held = start
  playRadioTone(start ? 'ptt_start' : 'ptt_stop')
  try {
    if (serverStt.value && canRecord) await (start ? recorderPtt.press() : recorderPtt.release())
    else start ? browserPtt.press() : browserPtt.release()
  } catch (err) {
    heard.value = `microphone: ${err.message}`
    held = false
    listening.value = false
    txStage.value = 'STANDBY'
    stopWaveform()
  }
}

// --- Radio-Net Mode --------------------------------------------------------------------------------------------
async function netSend(body) {
  const trimmed = (body || '').trim()
  if (!trimmed) return
  await fetch('/api/net/text', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: trimmed }),
  })
}

async function replayDemo(forcedScript = null) {
  const script = forcedScript || (['uk', 'ru'].includes(lang.value) ? 'uk' : 'en')
  if (script === 'uk') lang.value = 'uk'
  const r = await fetch(`/api/net/replay?speed=3&script=${script}`, { method: 'POST' })
  const out = await r.json().catch(() => ({}))
  netMsg.value = r.ok
    ? `replaying ${out.lines} transmissions (${script.toUpperCase()}) over ~${out.seconds} s (3× speed)`
    : out.detail || `replay failed (${r.status})`
}

function queueSegment(samples, rate, startedAt, seconds) {
  netSegments.value++
  netQueue = netQueue
    .then(async () => {
      const off = new OfflineAudioContext(1, Math.ceil(seconds * 16000), 16000)
      const buf = off.createBuffer(1, samples.length, rate)
      buf.copyToChannel(samples, 0)
      const src = off.createBufferSource()
      src.buffer = buf
      src.connect(off.destination)
      src.start()
      const wav = encodeWav((await off.startRendering()).getChannelData(0), 16000)
      const r = await fetch(`/api/net/audio?lang=${lang.value}&t=${startedAt.toFixed(2)}&dur=${seconds.toFixed(2)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'audio/wav' },
        body: wav,
      })
      if (r.status === 501) {
        netMsg.value = `transmission ${netSegments.value} detected (${seconds.toFixed(1)} s), server STT off`
        return
      }
      const out = await r.json().catch(() => ({}))
      netMsg.value = r.ok ? `heard: “${out.transcript}”` : `speech-to-text failed: ${out.detail || r.status}`
    })
    .catch((err) => {
      netMsg.value = err.message
    })
}

function browserNet() {
  netRecogniser = new Speech()
  netRecogniser.lang = SPEECH_LANG[lang.value]
  netRecogniser.continuous = true
  netRecogniser.onresult = (r) => {
    for (let i = r.resultIndex; i < r.results.length; i++) {
      if (!r.results[i].isFinal) continue
      const t = r.results[i][0].transcript.trim()
      if (t) {
        netSegments.value++
        netMsg.value = `heard: “${t}”`
        netSend(t)
      }
    }
  }
  netRecogniser.onend = () => {
    if (netOn.value && netSource.value === 'browser') netRecogniser.start()
  }
  netRecogniser.start()
  netSource.value = 'browser'
  netOn.value = true
  netMsg.value = 'listening with the browser recogniser'
}

async function netStart(file) {
  if (netOn.value) await netStop()
  netSegments.value = 0
  if (!file && !serverStt.value) {
    if (Speech) return browserNet()
    netMsg.value = 'no speech-to-text configured'
    return
  }
  try {
    netCtx = new AudioContext()
    let src
    if (file) {
      netAudio = new Audio(URL.createObjectURL(file))
      src = netCtx.createMediaElementSource(netAudio)
      src.connect(netCtx.destination)
      netAudio.onended = () => setTimeout(netStop, 1000)
    } else {
      netStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: false, noiseSuppression: true },
      })
      src = netCtx.createMediaStreamSource(netStream)
    }
    netVad = createVad(netCtx.sampleRate, {
      level: (rms, speaking) => {
        netLevel.value = rms
        netSpeaking.value = speaking
      },
      segment: (samples, startedAt, seconds) => queueSegment(samples, netCtx.sampleRate, startedAt, seconds),
    })
    netNode = netCtx.createScriptProcessor(2048, 1, 1)
    netNode.onaudioprocess = (e) => netVad.push(e.inputBuffer.getChannelData(0))
    src.connect(netNode)
    netNode.connect(netCtx.destination)
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
  netNode?.disconnect()
  netAudio?.pause()
  netStream?.getTracks().forEach((t) => t.stop())
  await netCtx?.close().catch(() => {})
  netCtx = netNode = netAudio = netStream = netVad = null
  netOn.value = false
  netSpeaking.value = false
  netLevel.value = 0
  netSource.value = ''
}

function toggleNetListen() {
  if (netOn.value && netSource.value !== 'file') netStop()
  else netStart()
}

// --- Keyboard Shortcuts ----------------------------------------------------------------------------------------
const typing = (e) => ['TEXTAREA', 'INPUT', 'SELECT'].includes(e.target?.tagName)

function keydown(e) {
  if (isHandset) return
  if (e.key === 'Escape') {
    if (phoneModalOpen.value) {
      phoneModalOpen.value = false
      return
    }
    if (armedDrop.value.kind) {
      armedDrop.value = { kind: null, label: null }
      return
    }
  }
  if (!typing(e) && !e.repeat && !e.metaKey && !e.ctrlKey && drafts.value.length) {
    if (e.key === 'c' || e.key === 'C') {
      e.preventDefault()
      confirmEvent(drafts.value[0])
      return
    }
    if (e.key === 'x' || e.key === 'X') {
      e.preventDefault()
      rejectEvent(drafts.value[0])
      return
    }
  }
  if ((e.metaKey || e.ctrlKey) && e.key === '\\') {
    e.preventDefault()
    toggleSidebar()
    return
  }
  if (activeTab.value === 'net' && netOn.value) return
  if (e.code === 'Space' && !e.repeat && !typing(e)) {
    e.preventDefault()
    talk(true)
  }
}

function keyup(e) {
  if (isHandset) return
  if (e.code === 'Space' && !typing(e)) {
    e.preventDefault()
    talk(false)
  }
}

function blur() {
  talk(false)
}
function hidden() {
  if (document.hidden) talk(false)
}

// --- WebSocket Connection --------------------------------------------------------------------------------------
function connect() {
  if (unmounted || isHandset) return
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ws`)
  socket = ws
  ws.onopen = () => {
    status.value = 'live'
    appAlert.value = ''
  }
  ws.onclose = () => {
    if (unmounted) return
    status.value = 'reconnecting…'
    setTimeout(connect, 1500)
  }
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data)
    if (msg.type === 'event') add(msg.event)
    if (msg.type === 'supersede') {
      const e = events.value.find((x) => x.id === msg.id)
      if (e) {
        e.superseded = true
        events.value = [...events.value]
      }
    }
    if (msg.type === 'places') customPlaces.value = msg.places
    if (msg.type === 'stt') {
      serverStt.value = msg.provider
      sttOptions.value = msg.available
    }
    if (msg.type === 'mode') {
      offlineMode.value = !!msg.offline
      if (typeof msg.auto_confirm === 'boolean') confirmGate.value = !msg.auto_confirm
      if (msg.stt !== undefined) serverStt.value = msg.stt
    }
    if (msg.type === 'handsets') {
      handsets.value = { count: msg.count || 0, transmitting: !!msg.transmitting, active_callsign: msg.active_callsign || null }
    }
    if (msg.type === 'tx') txs.value.push(msg.tx)
    if (msg.type === 'annotate') {
      const e = events.value.find((x) => x.id === msg.id)
      if (e) {
        Object.assign(e, msg.fields)
        events.value = [...events.value]
      }
    }
    if (msg.type === 'reset') {
      events.value = []
      cursor.value = 0
      txs.value = []
      tacOverlays.value = []
      previewedEvent.value = null
    }
  }
}

onMounted(async () => {
  if (isHandset) return
  const state = await fetch('/api/state')
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null)
  if (!state) {
    status.value = 'backend unreachable'
    appAlert.value = 'Tactical backend not reachable on :8000. Start uvicorn backend.app:app.'
  }
  if (state?.centre) defaultCentre.value = state.centre
  serverStt.value = state?.stt ?? null
  sttOptions.value = state?.stt_options ?? []
  customPlaces.value = state?.custom_places ?? []
  offlineMode.value = !!state?.offline
  if (state?.handsets) handsets.value = state.handsets

  map = new maplibregl.Map({
    container: 'map',
    center: state?.centre ?? [2.334, 48.851],
    zoom: 15.2,
    style: {
      version: 8,
      glyphs: `${location.origin}/glyphs/{fontstack}/{range}.pbf`,
      sources: Object.fromEntries(
        Object.entries(RASTER_BASEMAPS).map(([id, b]) => [
          `base-${id}`,
          {
            type: 'raster',
            tiles: b.tiles,
            tileSize: 256,
            minzoom: b.minzoom ?? 0,
            maxzoom: b.maxzoom,
            attribution: b.attribution,
          },
        ]),
      ),
      layers: [
        { id: 'bg-offline', type: 'background', paint: { 'background-color': '#090e14' } },
        ...Object.keys(RASTER_BASEMAPS).map((id) => ({
          id: `base-${id}`,
          type: 'raster',
          source: `base-${id}`,
          layout: { visibility: id === basemap.value ? 'visible' : 'none' },
          paint: RASTER_BASEMAPS[id].paint ?? {},
        })),
      ],
    },
  })

  map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-left')
  map.on('styleimagemissing', addSymbolImage)

  map.on('load', () => {
    const empty = { type: 'FeatureCollection', features: [] }
    for (const id of [
      'offline-vec',
      'regions',
      'paths',
      'labels',
      'stale',
      'custom',
      'tasks',
      'units',
      'grid',
      'grid-labels',
      'contact-regions',
      'contacts',
      'airborne',
      'airborne-tracks',
      'airborne-vectors',
      'threat',
      'range-rings',
      'fov-cone',
      'tac-overlays',
      'candidate-regions',
      'candidate-points',
    ]) {
      map.addSource(id, { type: 'geojson', data: empty })
    }

    // 100% OFFLINE Local Vector Basemap Layers (drawn from local data/gazetteer.json!)
    map.addLayer({
      id: 'offline-parks',
      type: 'fill',
      source: 'offline-vec',
      filter: ['==', ['get', 'layer'], 'park'],
      layout: { visibility: 'none' },
      paint: { 'fill-color': '#12261e', 'fill-opacity': 0.85 },
    })
    map.addLayer({
      id: 'offline-buildings',
      type: 'fill',
      source: 'offline-vec',
      filter: ['==', ['get', 'layer'], 'building'],
      layout: { visibility: 'none' },
      paint: { 'fill-color': '#182432', 'fill-outline-color': '#2b3e52', 'fill-opacity': 0.9 },
    })
    map.addLayer({
      id: 'offline-streets',
      type: 'line',
      source: 'offline-vec',
      filter: ['all', ['==', ['get', 'layer'], 'street'], ['!', ['get', 'major']]],
      layout: { visibility: 'none' },
      paint: { 'line-color': '#253545', 'line-width': 1.2 },
    })
    map.addLayer({
      id: 'offline-streets-major',
      type: 'line',
      source: 'offline-vec',
      filter: ['all', ['==', ['get', 'layer'], 'street'], ['get', 'major']],
      layout: { visibility: 'none' },
      paint: { 'line-color': '#415a73', 'line-width': 2.2 },
    })
    map.addLayer({
      id: 'offline-labels',
      type: 'symbol',
      source: 'offline-vec',
      filter: ['==', ['get', 'layer'], 'building'],
      layout: {
        visibility: 'none',
        'text-field': ['get', 'name'],
        'text-size': 10,
        'text-font': ['Open Sans Semibold'],
        'text-max-width': 14,
      },
      paint: { 'text-color': '#7892ab', 'text-halo-color': '#090e14', 'text-halo-width': 1.5 },
    })

    // MGRS kilometre grid
    map.addLayer({
      id: 'grid-line',
      type: 'line',
      source: 'grid',
      paint: {
        'line-color': '#cbd5e1',
        'line-width': ['case', ['get', 'major'], 1.4, 0.8],
        'line-opacity': ['case', ['get', 'major'], 0.65, 0.38],
      },
    })
    map.addLayer({
      id: 'grid-label',
      type: 'symbol',
      source: 'grid-labels',
      layout: { 'text-field': ['get', 'label'], 'text-size': 11, 'text-font': ['Open Sans Semibold'], 'text-allow-overlap': true },
      paint: { 'text-color': '#94a3b8', 'text-halo-color': '#0b0d10', 'text-halo-width': 1.5 },
    })

    // Range Rings + FOV Heading Cone
    map.addLayer({ id: 'range-ring-fill', type: 'fill', source: 'range-rings', paint: { 'fill-color': ['get', 'colour'], 'fill-opacity': 0.03 } })
    map.addLayer({
      id: 'range-ring-line',
      type: 'line',
      source: 'range-rings',
      paint: { 'line-color': ['get', 'colour'], 'line-width': 1.2, 'line-dasharray': [4, 4], 'line-opacity': 0.72 },
    })
    map.addLayer({ id: 'fov-fill', type: 'fill', source: 'fov-cone', paint: { 'fill-color': '#38bdf8', 'fill-opacity': 0.14 } })
    map.addLayer({ id: 'fov-line', type: 'line', source: 'fov-cone', paint: { 'line-color': '#38bdf8', 'line-width': 1.2, 'line-opacity': 0.55 } })

    // Staleness rings & Uncertainty regions
    map.addLayer({ id: 'stale-line', type: 'line', source: 'stale', paint: { 'line-color': ['get', 'colour'], 'line-width': 1.1, 'line-dasharray': [1, 3], 'line-opacity': 0.8 } })
    map.addLayer({ id: 'region-fill', type: 'fill', source: 'regions', paint: { 'fill-color': ['get', 'colour'], 'fill-opacity': ['case', ['get', 'current'], 0.34, 0.08] } })
    const outline = { 'line-color': ['get', 'colour'], 'line-width': ['case', ['get', 'current'], 2.2, 0.6] }
    map.addLayer({ id: 'region-line', type: 'line', source: 'regions', filter: ['!', ['get', 'ambiguous']], paint: outline })
    map.addLayer({ id: 'region-line-ambiguous', type: 'line', source: 'regions', filter: ['get', 'ambiguous'], paint: { ...outline, 'line-dasharray': [2, 2] } })

    // Contacts & Tasked destinations
    map.addLayer({ id: 'contact-fill', type: 'fill', source: 'contact-regions', paint: { 'fill-color': ['get', 'colour'], 'fill-opacity': 0.18 } })
    map.addLayer({ id: 'contact-line', type: 'line', source: 'contact-regions', paint: { 'line-color': ['get', 'colour'], 'line-width': 1.6, 'line-dasharray': [3, 2] } })
    map.addLayer({ id: 'task-fill', type: 'fill', source: 'tasks', paint: { 'fill-color': ['get', 'colour'], 'fill-opacity': 0.12 } })
    map.addLayer({ id: 'task-line', type: 'line', source: 'tasks', paint: { 'line-color': ['get', 'colour'], 'line-width': 2.4, 'line-dasharray': [1, 1.5] } })
    map.addLayer({
      id: 'task-label',
      type: 'symbol',
      source: 'tasks',
      layout: { 'text-field': ['get', 'label'], 'text-size': 12, 'text-font': ['Open Sans Semibold'], 'text-max-width': 30 },
      paint: { 'text-color': ['get', 'colour'], 'text-halo-color': '#0b0d10', 'text-halo-width': 2 },
    })

    // Dashed Gold Movement Trails
    map.addLayer({ id: 'path', type: 'line', source: 'paths', paint: { 'line-color': '#e5b84b', 'line-width': 2.6, 'line-dasharray': [3, 1.5], 'line-opacity': 0.88 } })

    // Operator custom named points
    map.addLayer({ id: 'custom-dot', type: 'circle', source: 'custom', paint: { 'circle-radius': 5.5, 'circle-color': '#e5b84b', 'circle-stroke-color': '#0b0d10', 'circle-stroke-width': 2 } })
    map.addLayer({
      id: 'custom-label',
      type: 'symbol',
      source: 'custom',
      layout: { 'text-field': ['get', 'label'], 'text-size': 11.5, 'text-offset': [0, 1.3], 'text-font': ['Open Sans Semibold'] },
      paint: { 'text-color': '#e5b84b', 'text-halo-color': '#0b0d10', 'text-halo-width': 2 },
    })

    // Friendly unit NATO APP-6 symbols & compact 1-line labels
    map.addLayer({ id: 'unit-icon', type: 'symbol', source: 'units', layout: { 'icon-image': ['get', 'icon'], 'icon-allow-overlap': true, 'icon-ignore-placement': true } })
    map.addLayer({
      id: 'label',
      type: 'symbol',
      source: 'labels',
      layout: { 'text-field': ['get', 'label'], 'text-size': 11.5, 'text-offset': [0, -2.0], 'text-max-width': 28, 'text-font': ['Open Sans Semibold'], 'text-line-height': 1.2 },
      paint: { 'text-color': ['get', 'colour'], 'text-halo-color': '#0b0d10', 'text-halo-width': 2 },
    })
    map.addLayer({ id: 'threat-ring', type: 'line', source: 'threat', paint: { 'line-color': SIDE.hostile.colour, 'line-width': 3, 'line-dasharray': [1, 1] } })

    // Contacts heading arrow + APP-6 icons & compact 1-line labels
    map.addImage('heading-arrow', arrowImage(), { pixelRatio: 2, sdf: true })
    map.addLayer({
      id: 'contact-arrow',
      type: 'symbol',
      source: 'contacts',
      filter: ['!=', ['get', 'heading'], null],
      layout: { 'icon-image': 'heading-arrow', 'icon-rotate': ['get', 'heading'], 'icon-rotation-alignment': 'map', 'icon-allow-overlap': true, 'icon-ignore-placement': true },
      paint: { 'icon-color': ['get', 'colour'] },
    })
    map.addLayer({ id: 'contact-icon', type: 'symbol', source: 'contacts', layout: { 'icon-image': ['get', 'icon'], 'icon-allow-overlap': true, 'icon-ignore-placement': true } })
    map.addLayer({
      id: 'contact-label',
      type: 'symbol',
      source: 'contacts',
      layout: { 'text-field': ['get', 'label'], 'text-size': 11, 'text-offset': [0, 1.9], 'text-max-width': 28, 'text-font': ['Open Sans Semibold'], 'text-line-height': 1.2 },
      paint: { 'text-color': ['get', 'colour'], 'text-halo-color': '#0b0d10', 'text-halo-width': 2 },
    })

    // Airborne UAV / Flying Object Directional Flight Arrows + Live Track Trail + Lead Velocity Vector
    map.addImage('flight-arrow', flightArrowImage(), { pixelRatio: 2, sdf: true })
    map.addImage('hover-arrow', hoverArrowImage(), { pixelRatio: 2, sdf: true })
    map.addLayer({
      id: 'airborne-track-line',
      type: 'line',
      source: 'airborne-tracks',
      paint: { 'line-color': ['get', 'colour'], 'line-width': 2.4, 'line-opacity': 0.72 },
    })
    map.addLayer({
      id: 'airborne-vector-line',
      type: 'line',
      source: 'airborne-vectors',
      paint: { 'line-color': ['get', 'colour'], 'line-width': 2, 'line-dasharray': [2, 2], 'line-opacity': 0.85 },
    })
    map.addLayer({
      id: 'airborne-icon',
      type: 'symbol',
      source: 'airborne',
      layout: {
        'icon-image': ['get', 'icon'],
        'icon-rotate': ['get', 'heading'],
        'icon-rotation-alignment': 'map',
        'icon-size': 0.72,
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
      },
      paint: {
        'icon-color': ['get', 'colour'],
        'icon-halo-color': '#080c10',
        'icon-halo-width': 2,
      },
    })
    map.addLayer({
      id: 'airborne-label',
      type: 'symbol',
      source: 'airborne',
      layout: {
        'text-field': ['get', 'label'],
        'text-size': 11,
        'text-offset': [0, 1.85],
        'text-max-width': 28,
        'text-font': ['Open Sans Semibold'],
        'text-allow-overlap': true,
      },
      paint: { 'text-color': ['get', 'colour'], 'text-halo-color': '#080c10', 'text-halo-width': 2 },
    })

    // Ambiguous Candidate Ghost Pins (?1 / ?2 / ?3 / ?4) & Staged Confirmation Preview
    map.addLayer({
      id: 'cand-fill',
      type: 'fill',
      source: 'candidate-regions',
      paint: { 'fill-color': '#f59e0b', 'fill-opacity': 0.16 },
    })
    map.addLayer({
      id: 'cand-line',
      type: 'line',
      source: 'candidate-regions',
      paint: { 'line-color': '#f59e0b', 'line-width': 2.2, 'line-dasharray': [3, 2] },
    })
    map.addLayer({
      id: 'cand-dot',
      type: 'circle',
      source: 'candidate-points',
      paint: { 'circle-radius': 7, 'circle-color': '#f59e0b', 'circle-stroke-color': '#090e14', 'circle-stroke-width': 2 },
    })
    map.addLayer({
      id: 'cand-label',
      type: 'symbol',
      source: 'candidate-points',
      layout: { 'text-field': ['get', 'label'], 'text-size': 12, 'text-offset': [0, -1.5], 'text-font': ['Open Sans Semibold'], 'text-allow-overlap': true },
      paint: { 'text-color': '#fde68a', 'text-halo-color': '#090e14', 'text-halo-width': 2 },
    })

    // SOS / MEDEVAC / Rally overlays
    map.addImage('ov-sos', createOverlayCanvasImage('sos'), { pixelRatio: 2 })
    map.addImage('ov-medevac', createOverlayCanvasImage('medevac'), { pixelRatio: 2 })
    map.addImage('ov-rally', createOverlayCanvasImage('rally'), { pixelRatio: 2 })
    map.addLayer({
      id: 'tac-overlay-icon',
      type: 'symbol',
      source: 'tac-overlays',
      layout: { 'icon-image': ['get', 'icon'], 'icon-allow-overlap': true, 'icon-ignore-placement': true, 'text-field': ['get', 'label'], 'text-size': 11, 'text-offset': [0, 1.9], 'text-font': ['Open Sans Semibold'] },
      paint: { 'text-color': '#f8fafc', 'text-halo-color': '#080c10', 'text-halo-width': 2 },
    })

    applyBasemap()
    updateGrid()
    render()

    // Interactive Hover & Click Micro-Tooltip Overlay for Unit & Contact Markers
    let pinnedPopup = null
    const hoverPopup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 18,
      maxWidth: '320px',
      className: 'tactical-map-popup',
    })

    const buildMarkerTooltipHtml = (p) => {
      const titleColor = p.colour || '#ecf2f7'
      const meta = p.detail ? `<span style="color:#6c8296;font-weight:400">${escapeHtml(p.detail)}</span>` : ''
      const flightHtml = p.flight ? `<div class="tac-tip-flight">flight: ${escapeHtml(p.flight)}</div>` : ''
      const threatHtml = p.threat ? `<div class="tac-tip-threat">${escapeHtml(p.threat)}</div>` : ''
      return `
        <div class="tac-tip-title">
          <span style="color:${escapeHtml(titleColor)}">${escapeHtml(p.title || p.label || 'Marker')}</span>
          ${meta}
        </div>
        <div class="tac-tip-coords">coordinates: <strong>${escapeHtml(p.lat)}, ${escapeHtml(p.lon)}</strong> | margin: <strong>±${escapeHtml(p.margin)}m</strong></div>
        ${flightHtml}
        ${p.mgrs ? `<div class="tac-tip-mgrs">MGRS: ${escapeHtml(p.mgrs)}</div>` : ''}
        ${threatHtml}
      `
    }

    const INTERACTIVE_LAYERS = ['unit-icon', 'label', 'contact-icon', 'contact-label', 'airborne-icon', 'airborne-label']
    for (const layerId of INTERACTIVE_LAYERS) {
      map.on('mouseenter', layerId, (ev) => {
        if (armedDrop.value.kind) return
        map.getCanvas().style.cursor = 'pointer'
        const feat = ev.features?.[0]
        if (!feat || pinnedPopup) return
        hoverPopup.setLngLat(feat.geometry.coordinates.slice()).setHTML(buildMarkerTooltipHtml(feat.properties)).addTo(map)
      })
      map.on('mouseleave', layerId, () => {
        if (!armedDrop.value.kind) map.getCanvas().style.cursor = ''
        hoverPopup.remove()
      })
      map.on('click', layerId, (ev) => {
        if (armedDrop.value.kind) return
        const feat = ev.features?.[0]
        if (!feat) return
        hoverPopup.remove()
        if (pinnedPopup) {
          pinnedPopup.remove()
          pinnedPopup = null
        }
        pinnedPopup = new maplibregl.Popup({
          closeButton: true,
          closeOnClick: true,
          offset: 18,
          maxWidth: '320px',
          className: 'tactical-map-popup',
        })
          .setLngLat(feat.geometry.coordinates.slice())
          .setHTML(buildMarkerTooltipHtml(feat.properties))
          .addTo(map)
        pinnedPopup.on('close', () => {
          pinnedPopup = null
        })
      })
    }
  })

  map.on('moveend', updateGrid)
  map.on('mousemove', (ev) => {
    cursorLngLat.value = [ev.lngLat.lng, ev.lngLat.lat]
    cursorGrid.value = mgrsAt([ev.lngLat.lng, ev.lngLat.lat])
  })
  map.on('mouseout', () => {
    cursorLngLat.value = null
  })
  map.on('move', () => {
    if (!matchMedia('(hover: hover)').matches) cursorGrid.value = mgrsAt(map.getCenter().toArray())
  })
  cursorGrid.value = mgrsAt(map.getCenter().toArray())

  map.on('click', (ev) => {
    if (!armedDrop.value.kind) return
    const { kind, label } = armedDrop.value
    armedDrop.value = { kind: null, label: null }
    dropTacticalPin(kind, [ev.lngLat.lng, ev.lngLat.lat], label)
  })

  map.on('contextmenu', async (ev) => {
    const name = window.prompt('Name this tactical point (e.g. "checkpoint 3")')
    if (!name?.trim()) return
    await fetch('/api/places', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), lon: ev.lngLat.lng, lat: ev.lngLat.lat }),
    })
  })

  if (state) {
    events.value = state.events
    cursor.value = state.events.length
    txs.value = state.transmissions ?? []
  }
  // Sync local AUTO-PLOT / GATE: ON mode with backend immediately on startup
  fetch('/api/mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auto_confirm: !confirmGate.value }),
  }).catch(() => {})

  connect()
  ticker = setInterval(() => {
    now.value = Date.now() / 1000
  }, 5000)
  // Smooth 10 FPS live flight-arrow motion when moving UAVs / flying objects are active
  flightTimer = setInterval(() => {
    if (!live.value || !showContacts.value) return
    const hasMovingAir = contactsOnMap.value.some((e) => {
      if (!isAirborneContact(e.contact)) return false
      return airborneHeadingDeg(e.contact) != null && airborneSpeedMps(e.contact) > 0
    })
    if (hasMovingAir) renderAirborne(Date.now() / 1000)
  }, 100)
  window.addEventListener('keydown', keydown)
  window.addEventListener('keyup', keyup)
  window.addEventListener('blur', blur)
  document.addEventListener('visibilitychange', hidden)
})

onUnmounted(() => {
  unmounted = true
  socket?.close()
  window.speechSynthesis?.cancel()
  stopWaveform()
  netStop()
  clearInterval(ticker)
  clearInterval(flightTimer)
  window.removeEventListener('keydown', keydown)
  window.removeEventListener('keyup', keyup)
  window.removeEventListener('blur', blur)
  document.removeEventListener('visibilitychange', hidden)
})
</script>

<template>
  <!-- Mobile Phone Wireless Microphone Handset Mode (`/?handset=1`) -->
  <HandsetView v-if="isHandset" />

  <!-- Desktop Defense C2 Common Operating Picture -->
  <main v-else class="dashboard" :class="{ 'is-nvg': nvgMode, 'is-red-night': redNight }">
    <TopBar
      :connected="connected"
      :status-text="status"
      :active-callsign="activeUnitObj?.callsign || callsign"
      :active-grid="activeUnitGrid"
      :active-radius="activeUnitRadius"
      :active-heading="activeHeading"
      :read-back="readBack"
      :nvg-mode="nvgMode"
      :red-night="redNight"
      :offline-mode="offlineMode"
      :confirm-gate="confirmGate"
      :has-sos="hasSos"
      :threat-count="totalThreatCount"
      :stt-label="sttDisplayLabel"
      :handsets="handsets"
      @toggle-readback="readBack = !readBack"
      @toggle-nvg="toggleNvg"
      @toggle-red-night="toggleRedNight"
      @toggle-offline="toggleOfflineMode"
      @toggle-confirm-gate="setConfirmGate(!confirmGate)"
      @open-phone-mic="phoneModalOpen = true"
    />

    <div v-if="appAlert" class="error-banner" role="alert">
      <span>{{ appAlert }}</span>
      <button type="button" @click="appAlert = ''">DISMISS</button>
    </div>

    <section class="workspace" :class="{ 'is-sidebar-collapsed': !sidebarOpen }">
      <div class="map-column">
        <div class="map-stage" :class="{ 'is-drop-armed': !!armedDrop.kind }">
          <div id="map"></div>

          <!-- Top-Left Tactical Overlay Controls -->
          <div class="map-hud-topleft">
            <button type="button" class="map-chip" :class="{ 'is-active': showGrid }" @click="showGrid = !showGrid">
              <Grid3x3 :size="13" /><span>MGRS</span>
            </button>
            <button type="button" class="map-chip" :class="{ 'is-active': showRings }" @click="showRings = !showRings">
              <Radar :size="13" /><span>RINGS</span>
            </button>
            <button type="button" class="map-chip" :class="{ 'is-active': showFov }" @click="showFov = !showFov">
              <Navigation :size="13" /><span>FOV</span>
            </button>
            <button type="button" class="map-chip" :class="{ 'is-active': showContacts }" @click="showContacts = !showContacts">
              <Target :size="13" /><span>CONTACTS ({{ contactsOnMap.length }})</span>
            </button>
            <button type="button" class="map-chip" :class="{ 'is-active': showLegend }" @click="showLegend = !showLegend">
              <Info :size="13" /><span>APP-6</span>
            </button>
            <button type="button" class="map-chip" @click="focusCoords(activeUnitCentre)">
              <LocateFixed :size="13" /><span>CENTER</span>
            </button>
          </div>

          <!-- Top-Right Map Bar: Basemap Switcher + Game HUD Toggle + Claude-Style Sidebar Toggle -->
          <div class="map-hud-topright-wrap">
            <div class="map-hud-topright" role="group" aria-label="Base map layer switcher">
              <span class="map-layer-icon"><Layers :size="13" /></span>
              <button
                v-for="(b, id) in ALL_BASEMAPS"
                :key="id"
                type="button"
                class="layer-btn"
                :class="{ 'is-active': basemap === id }"
                :aria-pressed="basemap === id"
                @click="basemap = id"
              >
                {{ b.label }}
              </button>
            </div>

            <button
              type="button"
              class="map-rail-btn"
              :class="{ 'is-active': showMapHud }"
              title="Toggle transparent game-style command & process text overlay on map"
              @click="showMapHud = !showMapHud"
            >
              <Terminal :size="13" />
              <span>HUD</span>
            </button>

            <button
              v-if="!sidebarOpen"
              type="button"
              class="map-rail-btn is-sidebar-btn"
              title="Expand right sidebar (⌘\)"
              aria-label="Expand right sidebar"
              @click="toggleSidebar(true)"
            >
              <PanelRightOpen :size="15" />
              <span v-if="drafts.length" class="rail-badge-dot">{{ drafts.length }}</span>
            </button>
          </div>

          <!-- Game-Style Transparent Top-Right Overlay (NO background box — pure floating tactical text!) -->
          <div v-if="showMapHud" class="map-game-hud" aria-live="polite">
            <div class="game-hud-proc" :class="`is-${hudProcessInfo.state}`">
              <span class="game-hud-dot"></span>
              <span>{{ hudProcessInfo.text }}</span>
            </div>

            <div v-if="heard && (listening || txStage !== 'STANDBY')" class="game-hud-heard">
              {{ heard }}
            </div>

            <div v-if="gameHudFeed.length" class="game-hud-feed">
              <div
                v-for="item in gameHudFeed"
                :key="item.id"
                class="game-hud-item"
                :style="{ opacity: item.opacity }"
                @click="item.raw.centre && focusCoords(item.raw.centre)"
              >
                <div class="game-hud-line">
                  <span class="game-hud-status" :class="item.confirmed ? 'is-ok' : 'is-wait'">
                    {{ item.confirmed ? '✓' : '⏳' }}
                  </span>
                  <span class="game-hud-title" :style="{ color: item.colour }">
                    {{ item.title }}<template v-if="item.speedTag"> · {{ item.speedTag }}</template>
                  </span>
                  <span v-if="item.place" class="game-hud-place">· {{ item.place }}</span>
                  <span v-if="item.mgrs" class="game-hud-mgrs">{{ item.mgrs }}</span>
                  <span class="game-hud-time">{{ item.time }}</span>
                </div>

                <div v-if="item.sub" class="game-hud-sub">↳ {{ item.sub }}</div>

                <div v-if="item.pending || item.candidates.length" class="game-hud-actions" @click.stop>
                  <button
                    v-for="cand in item.candidates.slice(0, 4)"
                    :key="cand.index"
                    type="button"
                    class="game-hud-act is-cand"
                    @click="pickCandidate(item.id, cand.index)"
                  >
                    [?{{ cand.index + 1 }} {{ cand.name }}]
                  </button>
                  <button
                    v-if="item.pending"
                    type="button"
                    class="game-hud-act is-confirm"
                    @click="confirmEvent(item.raw)"
                  >
                    [✓ CONFIRM]
                  </button>
                  <button
                    v-if="item.pending"
                    type="button"
                    class="game-hud-act is-reject"
                    @click="rejectEvent(item.raw)"
                  >
                    [✕ REJECT]
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Collapsible NATO APP-6 Legend Popover -->
          <div v-if="showLegend" class="map-legend-popover">
            <div class="legend-title mono">NATO APP-6 SYMBOLOGY</div>
            <span><i class="frame"></i> Confirmed fix</span>
            <span><i class="frame dashed"></i> Suspected: draft, assumed, or silent 5m</span>
            <span v-for="l in LEGEND" :key="l.label"><i class="sym" v-html="l.svg"></i> {{ l.label }}</span>
          </div>

          <!-- Armed Click-to-Drop Banner -->
          <div v-if="armedDrop.kind" class="map-armed-banner" role="status">
            <Crosshair :size="15" />
            <span>
              CROSSHAIR ARMED · CLICK MAP TO DROP <strong>{{ armedDrop.kind.toUpperCase() }}</strong> · ESC TO CANCEL
            </span>
            <button type="button" aria-label="Cancel marker drop" @click="armedDrop = { kind: null, label: null }">
              <X :size="14" />
            </button>
          </div>

          <!-- Bottom-Left Live ATAK Cursor MGRS + Range/Bearing HUD -->
          <div class="map-hud-bottomleft mono">
            <div class="cursor-hud-row">
              <span class="cursor-label">CURSOR MGRS</span>
              <strong class="accent-gold">{{ cursorGrid || activeUnitGrid }}</strong>
            </div>
            <div class="cursor-hud-row">
              <span class="cursor-label">LAT / LON</span>
              <span>
                {{
                  cursorLngLat
                    ? `${cursorLngLat[1].toFixed(5)}, ${cursorLngLat[0].toFixed(5)}`
                    : `${activeUnitCentre[1].toFixed(5)}, ${activeUnitCentre[0].toFixed(5)}`
                }}
              </span>
            </div>
            <div v-if="cursorDistance != null" class="cursor-hud-row accent-cyan">
              <span class="cursor-label">RNG / BRG</span>
              <strong>
                {{ formatDistance(cursorDistance) }} · {{ String(cursorBearing).padStart(3, '0') }}°
                {{ headingToCardinal(cursorBearing) }}
              </strong>
            </div>
          </div>
        </div>

        <ReplayBar
          :total="events.length"
          :cursor="cursor"
          :current-time="currentReplayTime"
          @update:cursor="cursor = $event"
        />
      </div>

      <CommandSidebar
        :active-tab="activeTab"
        :callsign="callsign"
        :lang="lang"
        :active-grid="activeUnitGrid"
        :active-heading="activeHeading"
        :trail-distance-m="activeTrailDistanceM"
        :has-sos="hasSos"
        :offline-mode="offlineMode"
        :confirm-gate="confirmGate"
        :listening="listening"
        :can-listen="canListen"
        :tx-stage="txStage"
        :level-bars="levelBars"
        :heard="heard"
        :server-stt="serverStt"
        :stt-options="sttOptions"
        :stt-labels="STT_LABELS"
        :has-browser-speech="!!Speech"
        :events="events"
        :visible="visible"
        :drafts="drafts"
        :unit-roster="unitRoster"
        :contacts-on-map="contactsOnMap"
        :custom-places="customPlaces"
        :tac-overlays="tacOverlays"
        :visible-tx="visibleTx"
        :by-id="byId"
        :net-on="netOn"
        :net-source="netSource"
        :net-speaking="netSpeaking"
        :net-segments="netSegments"
        :net-meter="netMeter"
        :net-msg="netMsg"
        :kind-labels="KIND"
        :armed-drop-kind="armedDrop.kind"
        :msg-busy="msgBusy"
        :msg-status="msgStatus"
        :demo-busy="demoBusy"
        :colour-of="colour"
        :side-of="sideOf"
        :describe-contact="describeContact"
        :draft-symbol="draftSymbol"
        :draft-title="draftTitle"
        :draft-why="draftWhy"
        :ago="ago"
        :age="age"
        @update:active-tab="activeTab = $event"
        @update:callsign="callsign = $event"
        @update:lang="lang = $event"
        @step-heading="stepHeading"
        @choose-stt="chooseStt"
        @talk-start="talk(true)"
        @talk-stop="talk(false)"
        @send-report="(txt) => send(txt)"
        @send-net-text="(txt) => netSend(txt)"
        @net-toggle="toggleNetListen"
        @net-file="(file) => netStart(file)"
        @replay-demo="replayDemo"
        @confirm-event="confirmEvent"
        @confirm-all="confirmAllDrafts"
        @reject-event="rejectEvent"
        @pick-candidate="pickCandidate"
        @edit-event="editEvent"
        @preview-event="(ev) => (previewedEvent = ev)"
        @toggle-confirm-gate="setConfirmGate(!confirmGate)"
        @run-demo-scenario="runDemoScenario"
        @ingest-messages="ingestMessages"
        @focus-coords="focusCoords"
        @select-unit="selectUnit"
        @reset="reset"
        @trigger-sos="triggerSos"
        @clear-sos="clearSos"
        @arm-map-drop="(kind, label) => (armedDrop = { kind, label })"
        @drop-at-unit="(kind, label) => dropTacticalPin(kind, activeUnitCentre, label)"
        @remove-overlay="removeOverlay"
        @submit-medevac="handleSubmitMedevac"
        @submit-salute="handleSubmitSalute"
        @collapse-sidebar="toggleSidebar(false)"
      />
    </section>

    <PhoneMicModal :open="phoneModalOpen" :handsets="handsets" @close="phoneModalOpen = false" />
  </main>
</template>
