<script setup>
import { computed, ref } from 'vue'
import {
  Activity,
  AlertTriangle,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  Compass,
  Crosshair,
  Download,
  FileAudio,
  Flag,
  HeartPulse,
  HelpCircle,
  Mail,
  MapPin,
  MessageSquare,
  Mic,
  Minus,
  PanelRightClose,
  Pencil,
  Plus,
  Radio,
  RotateCcw,
  Send,
  ShieldAlert,
  ShieldCheck,
  Square,
  Target,
  Terminal,
  Trash2,
  Upload,
  Users,
  X,
} from 'lucide-vue-next'
import {
  detectThreatLevel,
  formatDistance,
  formatZuluTime,
  headingToCardinal,
} from '../tactical.js'
import { mgrsAt } from '../grid.js'

const props = defineProps({
  activeTab: { type: String, default: 'sitrep' },
  callsign: { type: String, default: 'alpha 1' },
  lang: { type: String, default: 'en' },
  activeGrid: String,
  activeHeading: { type: Number, default: 0 },
  trailDistanceM: { type: Number, default: 0 },
  hasSos: Boolean,
  offlineMode: Boolean,
  confirmGate: Boolean,
  listening: Boolean,
  canListen: Boolean,
  txStage: { type: String, default: 'STANDBY' },
  levelBars: { type: Array, default: () => Array(18).fill(14) },
  heard: String,
  serverStt: String,
  sttOptions: { type: Array, default: () => [] },
  sttLabels: { type: Object, default: () => ({}) },
  hasBrowserSpeech: Boolean,
  // Data
  events: { type: Array, default: () => [] },
  visible: { type: Array, default: () => [] },
  drafts: { type: Array, default: () => [] },
  unitRoster: { type: Array, default: () => [] },
  contactsOnMap: { type: Array, default: () => [] },
  customPlaces: { type: Array, default: () => [] },
  tacOverlays: { type: Array, default: () => [] },
  // Radio net
  visibleTx: { type: Array, default: () => [] },
  byId: { type: Object, default: () => new Map() },
  netOn: Boolean,
  netSource: String,
  netSpeaking: Boolean,
  netSegments: { type: Number, default: 0 },
  netMeter: { type: Number, default: 0 },
  netMsg: String,
  kindLabels: { type: Object, default: () => ({}) },
  // Marker drop & preview
  armedDropKind: String,
  msgBusy: Boolean,
  msgStatus: String,
  demoBusy: Boolean,
  // Helpers from App.vue
  colourOf: Function,
  sideOf: Function,
  describeContact: Function,
  draftSymbol: Function,
  draftTitle: Function,
  draftWhy: Function,
  ago: Function,
  age: Function,
})

const emit = defineEmits([
  'update:activeTab',
  'update:callsign',
  'update:lang',
  'step-heading',
  'choose-stt',
  'talk-start',
  'talk-stop',
  'send-report',
  'send-net-text',
  'net-toggle',
  'net-file',
  'replay-demo',
  'confirm-event',
  'confirm-all',
  'reject-event',
  'pick-candidate',
  'edit-event',
  'preview-event',
  'toggle-confirm-gate',
  'run-demo-scenario',
  'ingest-messages',
  'focus-coords',
  'select-unit',
  'reset',
  'trigger-sos',
  'clear-sos',
  'arm-map-drop',
  'drop-at-unit',
  'remove-overlay',
  'submit-medevac',
  'submit-salute',
  'collapse-sidebar',
])

const textInput = ref('')
const netInput = ref('')
const logFilter = ref('all')
const voiceDrawerOpen = ref(false)
const showRawJson = ref(false)
const editOpen = ref(false)
const sosArmed = ref(false)
const dropMode = ref('map')
const customPinLabel = ref('')
const opsFormOpen = ref('medevac')
const selectedEventId = ref(null)

// WhatsApp / Email Message Ingestion state
const msgChannel = ref('auto')
const msgText = ref('')

// 9-Line MEDEVAC fields
const medPrecedence = ref('A - URGENT SURGICAL')
const medPatients = ref('1 LITTER')
const medSecurity = ref('P - POSSIBLE ENEMY')
const medMarking = ref('SMOKE (GREEN)')

// SALUTE Spot Report fields
const salCount = ref(2)
const salSide = ref('hostile')
const salWhat = ref('tank')
const salActivity = ref('moving')
const salHeading = ref('north')
const salRemarks = ref('Observed along avenue')

const SAMPLE_WHATSAPP = `[21/11/2026, 14:12] Граніт: Бачу 3 ворожих танки біля церкви Сен-Сюльпіс, рухаються на схід
[21/11/2026, 14:14] Alpha 2: Holding south of Luxembourg Palace, spotted 2 enemy drones heading west
[21/11/2026, 14:16] Сокіл: На Ромашці, бачу 4 солдати противника 100 метрів на північ від Сараю`

const SAMPLE_EMAIL = `From: recon-lead-bravo1@field-ops.mil
Subject: URGENT SITREP - Sector 6 / Paris
Date: Sat, 21 Nov 2026 14:18:00 +0100

Bravo 1 is at the Medici fountain.
Contact: 3 enemy tanks moving east, 200 metres north of Saint-Sulpice church.
Suspected enemy IED at the corner of rue de Tournon and rue de Vaugirard.`

const EN_PRESETS = [
  { label: '✈ Drone 120 km/h E', text: 'Bravo one, contact, 2 enemy drones flying east at 120 km/h over Pantheon, over' },
  { label: '2 Enemy Tanks E', text: 'Zero, this is Bravo one, contact, two enemy tanks, moving north, 300 metres east of the church, over' },
  { label: '? Tanks at Tower', text: 'Bravo one, contact, 2 enemy tanks at the tower, over' },
  { label: 'S of Saint-Sulpice', text: 'Zero, this is Alpha two, south of the Saint-Sulpice church, over' },
]

const UK_PRESETS = [
  { label: '🇺🇦 Шахед 180 км/год N', text: 'Вежа, я Сокіл, шахед летить на північ 180 км/год над Люксембурзьким палацом, прийом.' },
  { label: '🇺🇦 3 танки Сен-Сюльпіс', text: 'Вежа, я Граніт, бачу 3 ворожих танки біля церкви Сен-Сюльпіс, прийом.' },
  { label: '🇺🇦 Ждун біля Сараю', text: "Вежа, я Граніт, ждун біля Сараю, метрів п'ятдесят на захід, не підходити, прийом." },
  { label: '🇺🇦 Сокіл на Ромашці', text: 'Вежа, я Сокіл, на Ромашці, без змін, прийом.' },
]

const activePresets = computed(() => (['uk', 'ru'].includes(props.lang) ? UK_PRESETS : EN_PRESETS))

const callsignSuggestions = computed(() => {
  const base = ['uk', 'ru'].includes(props.lang)
    ? ['сокіл', 'граніт', 'лис', 'alpha 1', 'alpha 2', 'bravo 1']
    : ['alpha 1', 'alpha 2', 'bravo 1', 'bravo 2', 'charlie 1', 'delta 1']
  const seen = new Set(base)
  for (const u of props.unitRoster) seen.add(u.callsign)
  return [...seen]
})

const latestEvent = computed(() => {
  if (selectedEventId.value != null) {
    const found = props.visible.find((e) => e.id === selectedEventId.value)
    if (found) return found
  }
  return props.visible.at(-1) || null
})

const latestThreat = computed(() => detectThreatLevel(latestEvent.value))

const latestQty = computed(() => {
  const e = latestEvent.value
  if (!e) return null
  if (e.type === 'contact') return e.contact?.count || e.parsed?.quantity || 1
  return e.parsed?.quantity || null
})

const latestConfidencePct = computed(() => {
  const c = latestEvent.value?.parsed?.confidence
  if (typeof c !== 'number') return null
  return Math.round(Math.max(0, Math.min(1, c)) * 100)
})

const filteredEvents = computed(() => {
  return [...props.visible]
    .reverse()
    .filter((e) => {
      if (logFilter.value === 'all') return true
      if (logFilter.value === 'units') return e.type !== 'contact'
      if (logFilter.value === 'contacts') return e.type === 'contact'
      if (logFilter.value === 'alerts') {
        const lvl = detectThreatLevel(e)
        return lvl === 'critical' || lvl === 'caution' || !e.confirmed
      }
      return true
    })
})

const MARKER_BUTTONS = [
  { kind: 'hostile', label: 'HOSTILE', icon: Target, cls: 'btn-hostile' },
  { kind: 'hazard', label: 'HAZARD / IED', icon: AlertTriangle, cls: 'btn-hazard' },
  { kind: 'medevac', label: 'MEDEVAC LZ', icon: HeartPulse, cls: 'btn-medevac' },
  { kind: 'rally', label: 'RALLY PT', icon: Flag, cls: 'btn-rally' },
]

function submitText() {
  const val = textInput.value.trim()
  if (!val) return
  textInput.value = ''
  if (props.activeTab === 'net') emit('send-net-text', val)
  else emit('send-report', val)
}

function submitNetText() {
  const val = netInput.value.trim()
  if (!val) return
  netInput.value = ''
  emit('send-net-text', val)
}

function runPreset(pText) {
  if (props.activeTab === 'net') emit('send-net-text', pText)
  else emit('send-report', pText)
}

function stepEventQty(e, delta) {
  const cur = e.type === 'contact' ? e.contact?.count || e.parsed?.quantity || 1 : e.parsed?.quantity || 1
  const next = Math.max(1, cur + delta)
  emit('edit-event', e.id, { count: next })
}

function updateContactField(e, patch) {
  emit('edit-event', e.id, patch)
}

function handleSosClick() {
  if (props.hasSos) {
    sosArmed.value = false
    emit('clear-sos')
    return
  }
  if (!sosArmed.value) {
    sosArmed.value = true
    window.setTimeout(() => {
      sosArmed.value = false
    }, 5000)
    return
  }
  sosArmed.value = false
  emit('trigger-sos')
}

function handleQuickPin(kind) {
  if (dropMode.value === 'map') {
    emit('arm-map-drop', props.armedDropKind === kind ? null : kind, customPinLabel.value.trim() || null)
    return
  }
  emit('drop-at-unit', kind, customPinLabel.value.trim() || null)
  customPinLabel.value = ''
}

function handleMedevacSubmit() {
  emit('submit-medevac', {
    precedence: medPrecedence.value,
    patients: medPatients.value,
    security: medSecurity.value,
    marking: medMarking.value,
  })
  emit('update:activeTab', 'sitrep')
}

function handleSaluteSubmit() {
  emit('submit-salute', {
    count: Number(salCount.value) || 1,
    side: salSide.value,
    what: salWhat.value,
    activity: salActivity.value,
    heading: salHeading.value,
    remarks: salRemarks.value,
  })
  emit('update:activeTab', 'sitrep')
}

function handleIngestMessages() {
  const txt = msgText.value.trim()
  if (!txt) return
  emit('ingest-messages', { text: txt, channel: msgChannel.value })
}

async function onUploadMsgFile(ev) {
  const f = ev.target.files?.[0]
  ev.target.value = ''
  if (!f) return
  msgText.value = await f.text()
  if (f.name.endsWith('.eml')) msgChannel.value = 'email'
  else if (f.name.endsWith('.txt')) msgChannel.value = 'auto'
}

function selectEventRow(e) {
  selectedEventId.value = e.id
  emit('preview-event', e)
  if (e.centre) emit('focus-coords', e.centre)
}

function exportSitrepJson() {
  const payload = {
    exported_at_utc: new Date().toISOString(),
    system: 'Voice-to-Map Defense C2 (EDTH)',
    offline_mode: props.offlineMode,
    total_events: props.events.length,
    events: props.events,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `sitrep-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function onFileChange(ev) {
  const f = ev.target.files?.[0]
  ev.target.value = ''
  if (f) emit('net-file', f)
}
</script>

<template>
  <aside class="command-sidebar" aria-label="Tactical Command Sidebar">
    <!-- PINNED SECTION 1: Single-Line Active Selected Unit Badge & Guarded 2-Step SOS -->
    <section class="sidebar-hero-card is-compact">
      <div class="unit-selector-row">
        <div class="unit-select-wrap" title="Active selected unit callsign">
          <span class="unit-status-dot" :class="hasSos ? 'status-sos' : 'status-green'"></span>
          <input
            class="callsign-input"
            list="callsign-list"
            :value="callsign"
            placeholder="Select unit..."
            aria-label="Active selected unit"
            @input="emit('update:callsign', $event.target.value)"
          />
          <datalist id="callsign-list">
            <option v-for="cs in callsignSuggestions" :key="cs" :value="cs" />
          </datalist>
          <span v-if="callsign" class="selected-unit-tag">(selected)</span>
          <button
            v-if="callsign"
            type="button"
            class="clear-cs-btn"
            title="Clear selected unit"
            @click="emit('update:callsign', '')"
          >
            <X :size="12" />
          </button>
        </div>

        <button
          type="button"
          class="sos-trigger"
          :class="{ 'is-armed': sosArmed, 'is-active': hasSos }"
          title="Two-step emergency SOS / Man-Down beacon"
          @click="handleSosClick"
        >
          <ShieldAlert :size="14" />
          <span>{{ hasSos ? 'CLEAR SOS' : sosArmed ? 'CONFIRM?' : 'SOS' }}</span>
        </button>

        <button
          type="button"
          class="sidebar-collapse-btn"
          title="Collapse sidebar (⌘\)"
          aria-label="Collapse right sidebar"
          @click="emit('collapse-sidebar')"
        >
          <PanelRightClose :size="15" />
        </button>
      </div>
    </section>

    <!-- PINNED SECTION 2: Collapsible Voice Comms & PTT Drawer (Collapsed by Default) -->
    <section class="control-panel is-collapsible">
      <button
        type="button"
        class="voice-drawer-toggle"
        :class="{ 'is-open': voiceDrawerOpen, 'is-tx': listening }"
        :aria-expanded="voiceDrawerOpen"
        title="Expand or collapse Voice Comms, Push-to-Talk, Demos & Radio Input"
        @click="voiceDrawerOpen = !voiceDrawerOpen"
      >
        <span class="voice-drawer-left">
          <Mic :size="14" />
          <span>VOICE COMMS</span>
        </span>
        <span class="voice-drawer-right">
          <span
            class="voice-toggle-pill mono"
            :class="{ 'is-on': voiceDrawerOpen, 'is-tx': listening }"
          >
            {{ listening ? 'TX LIVE' : voiceDrawerOpen ? 'TOGGLE • ON' : 'TOGGLE • OFF' }}
          </span>
          <ChevronDown v-if="voiceDrawerOpen" :size="14" />
          <ChevronRight v-else :size="14" />
        </span>
      </button>

      <div v-if="voiceDrawerOpen" class="ptt-module voice-drawer-body">
        <div class="ptt-header">
          <span class="ptt-net-label">
            <Radio :size="13" /> VOICE COMMS
          </span>

          <div class="ptt-controls-inline">
            <select
              v-if="sttOptions.length"
              class="mini-select mono"
              :value="serverStt || 'none'"
              title="Speech-to-text engine"
              aria-label="Speech-to-text engine"
              @change="emit('choose-stt', $event.target.value)"
            >
              <option v-for="p in sttOptions" :key="p" :value="p">{{ sttLabels[p] || p }}</option>
              <option value="none">{{ hasBrowserSpeech ? 'Browser' : 'Off' }}</option>
            </select>

            <select
              class="mini-select mono"
              :value="lang"
              title="Speech language"
              aria-label="Speech language"
              @change="emit('update:lang', $event.target.value)"
            >
              <option value="en">EN</option>
              <option value="uk">UK 🇺🇦</option>
              <option value="fr">FR</option>
              <option value="ru">RU</option>
              <option value="auto">AUTO</option>
            </select>

            <span
              class="ptt-stage-pill"
              :class="{
                'is-tx': listening,
                'is-busy': txStage === 'TRANSCRIBING' || txStage === 'PROCESSING',
                'is-ack': txStage === 'ACK RECEIVED',
              }"
            >
              {{ txStage }}
            </span>
          </div>
        </div>

        <button
          type="button"
          class="mic-button"
          :class="{ 'is-recording': listening, 'is-processing': txStage === 'TRANSCRIBING' }"
          :disabled="!canListen"
          aria-label="Push to talk"
          @mousedown="emit('talk-start')"
          @mouseup="emit('talk-stop')"
          @mouseleave="emit('talk-stop')"
          @touchstart.prevent="emit('talk-start')"
          @touchend.prevent="emit('talk-stop')"
        >
          <div class="mic-button-main">
            <span class="mic-icon-badge" aria-hidden="true">
              <Square v-if="listening" :size="16" fill="currentColor" />
              <Mic v-else :size="18" />
            </span>
            <div class="mic-button-copy">
              <strong>
                {{
                  !canListen
                    ? 'NO SPEECH INPUT'
                    : listening
                      ? 'TRANSMITTING LIVE...'
                      : txStage === 'TRANSCRIBING'
                        ? 'TRANSCRIBING...'
                        : 'PUSH TO TALK'
                }}
              </strong>
              <small>
                {{
                  listening
                    ? 'Release button or [SPACE] to transmit'
                    : 'Hold button or [SPACE] · Right-click map to name point'
                }}
              </small>
            </div>
          </div>

          <div class="ptt-waveform" :class="{ 'is-live': listening }" aria-hidden="true">
            <span
              v-for="(h, idx) in levelBars"
              :key="idx"
              :style="{ height: `${listening ? h : 18 + ((idx * 17) % 24)}%` }"
            ></span>
          </div>
        </button>

        <div v-if="heard" class="heard-strip mono">{{ heard }}</div>

        <form class="radio-text-form" @submit.prevent="submitText">
          <Terminal :size="14" class="radio-input-icon" />
          <input
            v-model="textInput"
            type="text"
            :placeholder="
              ['uk', 'ru'].includes(lang)
                ? 'Вежа, я Граніт, бачу 3 ворожих танки біля церкви, прийом'
                : 'Bravo 1, contact, 2 enemy tanks at the tower, over'
            "
            aria-label="Radio text command"
          />
          <button type="submit" class="radio-send-btn" :disabled="!textInput.trim()">
            <Send :size="13" />
            <span>TX</span>
          </button>
        </form>

        <!-- Bilingual Demo Runner + Quick Tactical Presets -->
        <div class="demo-runner-strip mono">
          <span class="demo-label">DEMO:</span>
          <button
            type="button"
            class="demo-pill"
            :disabled="demoBusy"
            title="Run English live demo sequence"
            @click="emit('run-demo-scenario', 'en')"
          >
            EN
          </button>
          <button
            type="button"
            class="demo-pill is-uk"
            :disabled="demoBusy"
            title="Run Ukrainian live demo sequence (Сокіл, Граніт, Сарай, 3 tanks, drone)"
            @click="emit('run-demo-scenario', 'uk')"
          >
            🇺🇦 UK
          </button>
          <button
            type="button"
            class="demo-pill is-gold"
            :disabled="demoBusy"
            title="Run combined English + Ukrainian bilingual joint demo"
            @click="emit('run-demo-scenario', 'mixed')"
          >
            EN+UK
          </button>
          <button
            type="button"
            class="demo-pill is-amber"
            :disabled="demoBusy"
            title="Test ambiguous disambiguation: '2 enemy tanks at the tower'"
            @click="runPreset('Bravo one, contact, 2 enemy tanks at the tower, over')"
          >
            ? TOWER
          </button>
        </div>

        <div class="quick-presets" aria-label="Quick tactical radio presets">
          <button
            v-for="cmd in activePresets"
            :key="cmd.label"
            type="button"
            class="preset-chip"
            :title="cmd.text"
            @click="runPreset(cmd.text)"
          >
            {{ cmd.label }}
          </button>
        </div>
      </div>
    </section>

    <!-- SECTION 3: 5-Tab Tactical Operations Deck -->
    <nav class="sidebar-tabs tabs-5" role="tablist" aria-label="Command Sidebar Sections">
      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'sitrep'"
        class="sidebar-tab"
        :class="{ 'is-active': activeTab === 'sitrep' }"
        @click="emit('update:activeTab', 'sitrep')"
      >
        <Activity :size="13" />
        <span>SITREP</span>
        <em class="tab-badge" :class="{ 'has-drafts': drafts.length > 0 }">{{ drafts.length || visible.length }}</em>
      </button>

      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'msg'"
        class="sidebar-tab"
        :class="{ 'is-active': activeTab === 'msg' }"
        title="WhatsApp & Email Text Intel Extraction"
        @click="emit('update:activeTab', 'msg')"
      >
        <MessageSquare :size="13" />
        <span>MSG</span>
      </button>

      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'net'"
        class="sidebar-tab"
        :class="{ 'is-active': activeTab === 'net' }"
        @click="emit('update:activeTab', 'net')"
      >
        <Radio :size="13" />
        <span>NET</span>
        <em v-if="visibleTx.length" class="tab-badge">{{ visibleTx.length }}</em>
      </button>

      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'ops'"
        class="sidebar-tab"
        :class="{ 'is-active': activeTab === 'ops' }"
        @click="emit('update:activeTab', 'ops')"
      >
        <Crosshair :size="13" />
        <span>OPS</span>
      </button>

      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'bft'"
        class="sidebar-tab"
        :class="{ 'is-active': activeTab === 'bft' }"
        @click="emit('update:activeTab', 'bft')"
      >
        <Users :size="13" />
        <span>BFT</span>
        <em class="tab-badge">{{ unitRoster.length }}</em>
      </button>
    </nav>

    <!-- TAB BODY (Internally Scrollable) -->
    <div class="sidebar-tab-body">
      <!-- TAB 1: SITREP + CONFIRMATION GATE QUEUE + OPERATOR CONTEXT BREAKDOWN + LOG -->
      <div v-if="activeTab === 'sitrep'" class="sitrep-stack">
        <!-- Operator Confirmation Gate Control Bar (Always visible for instant demo toggle!) -->
        <div class="gate-bar mono" :class="{ 'is-strict': confirmGate }">
          <label class="gate-switch">
            <input type="checkbox" :checked="confirmGate" @change="emit('toggle-confirm-gate')" />
            <ShieldCheck :size="13" />
            <span>CONFIRM EVERY REPORT BEFORE MAP ({{ confirmGate ? 'GATE ON' : 'AUTO-PLOT' }})</span>
          </label>
          <button
            v-if="drafts.length > 0"
            type="button"
            class="confirm-all-btn"
            title="Confirm all pending reports onto the map"
            @click="emit('confirm-all')"
          >
            <CheckCheck :size="12" />
            <span>ALL ({{ drafts.length }})</span>
          </button>
        </div>

        <!-- Duty-Officer Confirmation & Disambiguation Queue -->
        <section v-if="drafts.length" class="panel queue-panel" aria-label="Reports awaiting operator confirmation">
          <div class="panel-heading queue-heading">
            <div class="heading-left">
              <span class="accent-gold">{{ confirmGate ? 'HELD OFF MAP · CONFIRM' : 'TO CONFIRM' }}</span>
              <span class="count-badge is-gold">{{ drafts.length }}</span>
            </div>
            <span class="hotkey-hint mono">C CONFIRM · X REJECT</span>
          </div>

          <ol class="queue-list">
            <li
              v-for="(d, i) in drafts.slice(0, 6)"
              :key="d.id"
              :class="{ 'is-top': i === 0, 'has-candidates': (d.candidate_options || []).length > 1 }"
              @mouseenter="emit('preview-event', d)"
              @mouseleave="emit('preview-event', null)"
            >
              <div class="queue-card-main">
                <i class="queue-sym" v-html="draftSymbol(d)"></i>
                <div class="queue-info" @click="d.centre && emit('focus-coords', d.centre)">
                  <div class="queue-title-line">
                    <strong :style="{ color: d.type === 'contact' ? sideOf(d.contact).colour : colourOf(d.callsign) }">
                      {{ draftTitle(d) }}
                    </strong>
                    <span v-if="d.type === 'contact'" class="qty-chip mono">
                      QTY {{ d.contact?.count || d.parsed?.quantity || 1 }}×
                    </span>
                  </div>
                  <div class="queue-where mono">
                    {{ (d.parsed?.relation || '').replaceAll('_', ' ') }} {{ d.anchor }} ±{{ Math.round(d.radius_m) }}m ·
                    <span class="accent-gold">{{ d.mgrs || mgrsAt(d.centre, { radius: d.radius_m }) }}</span>
                  </div>
                  <div class="queue-who">
                    {{ d.sender ? `${d.channel || d.source}: ${d.sender}` : d.seen_by?.length ? 'seen by ' + d.seen_by.join(', ') : d.speaker || 'unknown' }}
                    · {{ ago(d.t) }} · {{ draftWhy(d) }}
                  </div>
                </div>

                <!-- Inline Quantity Stepper + Confirm/Reject -->
                <div class="queue-btns">
                  <div v-if="d.type === 'contact'" class="mini-qty-edit mono" title="Correct quantity (e.g. 2 tanks -> 3 tanks)">
                    <button type="button" @click.stop="stepEventQty(d, -1)"><Minus :size="10" /></button>
                    <span>{{ d.contact?.count || 1 }}</span>
                    <button type="button" @click.stop="stepEventQty(d, 1)"><Plus :size="10" /></button>
                  </div>
                  <button
                    type="button"
                    class="q-btn is-confirm"
                    :title="confirmGate ? 'Confirm & Plot on Map (C)' : 'Confirm (C)'"
                    @click="emit('confirm-event', d)"
                  >
                    <Check :size="13" />
                  </button>
                  <button type="button" class="q-btn is-reject" title="Reject & Discard (X)" @click="emit('reject-event', d)">
                    <X :size="13" />
                  </button>
                </div>
              </div>

              <!-- AMBIGUITY DISAMBIGUATION PICKER ("Which tower?") -->
              <div v-if="(d.candidate_options || []).length > 1" class="candidate-picker">
                <div class="candidate-header mono">
                  <HelpCircle :size="12" />
                  <span>UNCLEAR LOCATION — SELECT WHICH {{ (d.parsed?.anchor?.name || 'PLACE').toUpperCase() }}:</span>
                </div>
                <div class="candidate-grid">
                  <button
                    v-for="cand in d.candidate_options"
                    :key="cand.index"
                    type="button"
                    class="candidate-btn"
                    @mouseenter="emit('focus-coords', cand.centre)"
                    @click="emit('pick-candidate', d.id, cand.index)"
                  >
                    <span class="cand-num mono">?{{ cand.index + 1 }}</span>
                    <div class="cand-text">
                      <strong>{{ cand.name }}</strong>
                      <small class="mono">{{ cand.mgrs }} · {{ formatDistance(cand.distance_m) }}</small>
                    </div>
                  </button>
                </div>
              </div>
            </li>
          </ol>
          <div v-if="drafts.length > 6" class="queue-more mono">+{{ drafts.length - 6 }} more awaiting confirmation</div>
        </section>

        <!-- CONCISE EVENT NOTIFICATION CARD (Verbose Metadata Footer Removed) -->
        <section class="panel extraction-panel is-concise">
          <div class="panel-heading">
            <div class="heading-left">
              <span>LATEST REPORT</span>
              <span v-if="latestEvent" class="threat-pill" :class="`threat-${latestThreat}`">
                {{ latestThreat.toUpperCase() }}
              </span>
              <span v-if="latestEvent?.source" class="source-pill mono">
                {{ (latestEvent.channel || latestEvent.source).toUpperCase() }}
              </span>
            </div>
            <div class="heading-actions">
              <button
                v-if="latestEvent && latestEvent.type === 'contact'"
                type="button"
                class="json-toggle-btn mono"
                :class="{ 'is-active': editOpen }"
                title="Correct extracted classification or quantity"
                @click="editOpen = !editOpen"
              >
                <Pencil :size="10" /> EDIT
              </button>
              <button
                v-if="latestEvent"
                type="button"
                class="json-toggle-btn mono"
                @click="showRawJson = !showRawJson"
              >
                {{ showRawJson ? 'HIDE' : 'JSON' }}
              </button>
            </div>
          </div>

          <div v-if="latestEvent" class="extraction-content">
            <!-- Concise Notification Row with APP-6 Symbol + Status + Quantity Stepper -->
            <div class="context-class-row">
              <i class="queue-sym" v-html="draftSymbol(latestEvent)"></i>
              <div class="context-class-copy">
                <div class="context-class-title">
                  <strong
                    :style="{
                      color:
                        latestEvent.type === 'contact'
                          ? sideOf(latestEvent.contact).colour
                          : colourOf(latestEvent.callsign),
                    }"
                  >
                    {{
                      latestEvent.type === 'contact'
                        ? describeContact(latestEvent.contact).toUpperCase()
                        : `${(latestEvent.callsign || 'UNIT').toUpperCase()} · ${(latestEvent.type || 'POSITION').toUpperCase()}`
                    }}
                  </strong>
                </div>
                <div class="context-sub-meta mono">
                  <span>{{ latestEvent.confirmed ? (latestEvent.auto_confirmed ? '✓ AUTO-CONFIRMED' : '✓ CONFIRMED') : confirmGate ? '⏳ HELD OFF MAP' : '⚠ DRAFT' }}</span>
                  <span v-if="latestEvent.contact?.speed_mps != null">· {{ Math.round(latestEvent.contact.speed_mps * 3.6) }} km/h {{ (latestEvent.contact?.heading || '').toUpperCase() }}</span>
                  <span v-if="latestEvent.anchor">· {{ latestEvent.anchor }}</span>
                  <span v-if="latestEvent.centre">· {{ latestEvent.mgrs || mgrsAt(latestEvent.centre, { radius: latestEvent.radius_m }) }}</span>
                </div>
              </div>

              <!-- Compact Quantity Stepper (Contacts) -->
              <div
                v-if="latestEvent.type === 'contact'"
                class="qty-control-box mono"
                title="Quantity classification (use -/+ for factual correction)"
              >
                <span class="qty-box-label">QTY</span>
                <div class="qty-stepper">
                  <button type="button" @click="stepEventQty(latestEvent, -1)"><Minus :size="11" /></button>
                  <strong class="qty-value">{{ latestQty ?? 1 }}×</strong>
                  <button type="button" @click="stepEventQty(latestEvent, 1)"><Plus :size="11" /></button>
                </div>
              </div>
            </div>

            <!-- Inline Factual Correction Editor (Only when EDIT clicked) -->
            <div v-if="editOpen && latestEvent.type === 'contact'" class="inline-edit-panel mono">
              <label>
                <span>SIDE</span>
                <select
                  :value="latestEvent.contact?.side || 'unknown'"
                  @change="updateContactField(latestEvent, { side: $event.target.value })"
                >
                  <option value="hostile">HOSTILE</option>
                  <option value="unknown">UNKNOWN</option>
                  <option value="neutral">NEUTRAL</option>
                  <option value="friendly">FRIENDLY</option>
                </select>
              </label>
              <label>
                <span>UNIT TYPE</span>
                <select
                  :value="latestEvent.contact?.what || 'unknown'"
                  @change="updateContactField(latestEvent, { what: $event.target.value })"
                >
                  <option value="tank">TANK</option>
                  <option value="infantry">INFANTRY</option>
                  <option value="apc">ARMOURED VEH</option>
                  <option value="vehicle">VEHICLE</option>
                  <option value="drone">DRONE / UAV</option>
                  <option value="helicopter">HELICOPTER</option>
                  <option value="aircraft">AIRCRAFT</option>
                  <option value="sniper">SNIPER</option>
                  <option value="artillery">ARTILLERY</option>
                  <option value="ied">IED / MINE</option>
                  <option value="civilians">CIVILIANS</option>
                </select>
              </label>
              <label>
                <span>ACTIVITY</span>
                <select
                  :value="latestEvent.contact?.activity || ''"
                  @change="updateContactField(latestEvent, { activity: $event.target.value })"
                >
                  <option value="">NONE</option>
                  <option value="moving">MOVING</option>
                  <option value="static">STATIC</option>
                  <option value="firing">FIRING</option>
                </select>
              </label>
              <label v-if="['drone', 'helicopter', 'aircraft'].includes(latestEvent.contact?.what)">
                <span>DIRECTION</span>
                <select
                  :value="latestEvent.contact?.heading || ''"
                  @change="updateContactField(latestEvent, { heading: $event.target.value })"
                >
                  <option value="">HOVER</option>
                  <option value="north">NORTH (000°)</option>
                  <option value="northeast">NE (045°)</option>
                  <option value="east">EAST (090°)</option>
                  <option value="southeast">SE (135°)</option>
                  <option value="south">SOUTH (180°)</option>
                  <option value="southwest">SW (225°)</option>
                  <option value="west">WEST (270°)</option>
                  <option value="northwest">NW (315°)</option>
                </select>
              </label>
              <label v-if="['drone', 'helicopter', 'aircraft'].includes(latestEvent.contact?.what)">
                <span>SPEED (KM/H)</span>
                <input
                  type="number"
                  min="0"
                  max="1200"
                  step="10"
                  :value="latestEvent.contact?.speed_mps != null ? Math.round(latestEvent.contact.speed_mps * 3.6) : ''"
                  placeholder="auto"
                  @change="updateContactField(latestEvent, { speed_mps: Math.max(0, Number($event.target.value) || 0) / 3.6 })"
                />
              </label>
            </div>

            <!-- Concise English Translation Gloss (Only for non-English UK/RU/FR reports) -->
            <div v-if="latestEvent.parsed?.summary_en" class="translation-gloss mono">
              EN GLOSS: {{ latestEvent.parsed.summary_en }}
            </div>

            <!-- Threat Warnings (Only if Active Threat) -->
            <div
              v-for="w in latestEvent.threats || []"
              :key="w.callsign + (w.track || '')"
              class="threat-alert-strip mono"
            >
              ⚠ {{ w.callsign }}: {{ describeContact({ ...w.contact, activity: null }) }}
              {{ w.distance_m ? `${w.distance_m}m ${w.direction}` : 'AT POSITION' }}
            </div>

            <!-- Inline Candidate Picker (Only when Ambiguous, e.g. 'which tower?') -->
            <div v-if="(latestEvent.candidate_options || []).length > 1" class="candidate-picker">
              <div class="candidate-header mono">
                <HelpCircle :size="12" />
                <span>WHICH {{ (latestEvent.parsed?.anchor?.name || 'PLACE').toUpperCase() }}? CLICK TO RESOLVE:</span>
              </div>
              <div class="candidate-grid">
                <button
                  v-for="cand in latestEvent.candidate_options"
                  :key="cand.index"
                  type="button"
                  class="candidate-btn"
                  @mouseenter="emit('focus-coords', cand.centre)"
                  @click="emit('pick-candidate', latestEvent.id, cand.index)"
                >
                  <span class="cand-num mono">?{{ cand.index + 1 }}</span>
                  <div class="cand-text">
                    <strong>{{ cand.name }}</strong>
                    <small class="mono">{{ cand.mgrs }} · {{ formatDistance(cand.distance_m) }}</small>
                  </div>
                </button>
              </div>
            </div>

            <div v-if="latestEvent.ok && !latestEvent.superseded && !latestEvent.confirmed" class="extraction-footer">
              <button
                type="button"
                class="confirm-inline-btn"
                @click="emit('confirm-event', latestEvent)"
              >
                <Check :size="13" /> {{ confirmGate ? 'CONFIRM & PLOT ON MAP' : 'CONFIRM FIX' }}
              </button>
            </div>

            <pre v-if="showRawJson">{{ JSON.stringify(latestEvent, null, 2) }}</pre>
          </div>

          <div v-else class="empty-state">
            Expand <strong>VOICE COMMS</strong> above, hold <strong>[SPACE]</strong>, use <strong>PHONE MIC</strong>, or paste intel in <strong>MSG</strong>.
          </div>
        </section>

        <!-- SITREP Event Log -->
        <section class="panel event-log-panel">
          <div class="panel-heading">
            <div class="heading-left">
              <span>SITREP LOG</span>
              <span class="count-badge">{{ filteredEvents.length }}</span>
            </div>
            <div class="heading-actions">
              <a class="icon-action-btn" href="/api/picture.nvg" title="Export confirmed picture as NATO Vector Graphics">
                <Download :size="12" />
                <span>NVG</span>
              </a>
              <a class="icon-action-btn" href="/api/picture.geojson" target="_blank" title="Export confirmed picture as GeoJSON">
                <span>GEO</span>
              </a>
              <button
                type="button"
                class="icon-action-btn"
                :disabled="!events.length"
                title="Export full SITREP JSON"
                @click="exportSitrepJson"
              >
                <span>JSON</span>
              </button>
              <button type="button" class="icon-action-btn is-danger" title="Reset mission log & map" @click="emit('reset')">
                <RotateCcw :size="12" />
              </button>
            </div>
          </div>

          <div class="filter-strip">
            <button
              v-for="f in [
                { id: 'all', label: 'ALL' },
                { id: 'units', label: 'UNITS' },
                { id: 'contacts', label: 'CONTACTS' },
                { id: 'alerts', label: 'ALERTS' },
              ]"
              :key="f.id"
              type="button"
              class="filter-pill"
              :class="{ 'is-active': logFilter === f.id }"
              @click="logFilter = f.id"
            >
              {{ f.label }}
            </button>
          </div>

          <div class="event-log">
            <div v-if="!filteredEvents.length" class="empty-state">No tactical reports matching filter</div>
            <button
              v-for="e in filteredEvents"
              :key="e.id"
              type="button"
              class="event-row"
              :class="[
                `is-${detectThreatLevel(e)}`,
                { 'is-selected': selectedEventId === e.id, 'is-gone': e.superseded },
              ]"
              @click="selectEventRow(e)"
            >
              <div class="event-row-top">
                <time class="mono">{{ formatZuluTime(e.t) }}</time>
                <span
                  class="event-callsign"
                  :style="{ color: e.type === 'contact' ? sideOf(e.contact).colour : colourOf(e.callsign) }"
                >
                  {{ e.callsign }}
                </span>
                <span v-if="e.type === 'contact'" class="qty-inline mono">{{ e.contact?.count || 1 }}×</span>
                <span v-if="e.channel || ['whatsapp', 'email'].includes(e.source)" class="mini-channel mono">
                  {{ (e.channel || e.source).toUpperCase() }}
                </span>
                <span class="event-type-tag" :class="`tag-${e.type || 'position'}`">
                  {{ (e.type || 'fix').toUpperCase() }}
                </span>
              </div>

              <div class="event-transcript">“{{ e.text }}”</div>

              <div v-if="e.type === 'contact'" class="event-contact-line" :style="{ color: sideOf(e.contact).colour }">
                ⚠ {{ describeContact(e.contact) }}
              </div>

              <div v-if="e.rejected" class="event-note-line">rejected by duty officer</div>
              <div v-else-if="e.superseded" class="event-note-line">superseded by correction</div>
              <div v-else-if="(e.candidate_options || []).length > 1" class="event-note-line">
                ? Ambiguous — {{ e.candidate_options.length }} candidates to pick
              </div>

              <div class="event-meta mono">
                <span>{{ e.centre ? e.mgrs || mgrsAt(e.centre, { radius: e.radius_m }) : 'NO GRID FIX' }}</span>
                <b>
                  <template v-if="e.ok">{{ e.anchor }}</template>
                  <template v-else>{{ (e.type || 'NOTE').toUpperCase() }}</template>
                  <template v-if="e.confirmed"> · ✓</template>
                </b>
              </div>
            </button>
          </div>
        </section>
      </div>

      <!-- TAB 2: WHATSAPP & EMAIL WARZONE TEXT INTEL EXTRACTOR -->
      <div v-else-if="activeTab === 'msg'" class="ops-stack">
        <section class="panel ops-panel">
          <div class="panel-heading">
            <span class="heading-left"><MessageSquare :size="13" class="accent-green" /> WHATSAPP / EMAIL INTEL EXTRACTOR</span>
            <div class="mode-switch">
              <button type="button" :class="{ 'is-active': msgChannel === 'auto' }" @click="msgChannel = 'auto'">AUTO</button>
              <button type="button" :class="{ 'is-active': msgChannel === 'whatsapp' }" @click="msgChannel = 'whatsapp'">WA</button>
              <button type="button" :class="{ 'is-active': msgChannel === 'email' }" @click="msgChannel = 'email'">EMAIL</button>
            </div>
          </div>

          <div class="ops-body">
            <div class="sample-btn-row">
              <button
                type="button"
                class="sample-load-btn is-wa mono"
                @click="
                  msgChannel = 'whatsapp';
                  msgText = SAMPLE_WHATSAPP
                "
              >
                <MessageSquare :size="12" /> SAMPLE WHATSAPP (UK+EN)
              </button>
              <button
                type="button"
                class="sample-load-btn is-mail mono"
                @click="
                  msgChannel = 'email';
                  msgText = SAMPLE_EMAIL
                "
              >
                <Mail :size="12" /> SAMPLE FIELD EMAIL
              </button>
              <label class="sample-load-btn mono file-label" title="Import exported .txt WhatsApp chat or .eml email">
                <Upload :size="12" /> IMPORT .TXT/.EML
                <input type="file" accept=".txt,.eml,.msg,text/plain" @change="onUploadMsgFile" />
              </label>
            </div>

            <textarea
              v-model="msgText"
              class="msg-textarea mono"
              rows="8"
              placeholder="Paste WhatsApp chat export, Email (From/Subject/Body), Telegram or Signal field intel here (English, Ukrainian, Russian, French)..."
            ></textarea>

            <button
              type="button"
              class="ops-submit-btn is-medevac"
              :disabled="msgBusy || !msgText.trim()"
              @click="handleIngestMessages"
            >
              <Send :size="14" />
              <span>{{ msgBusy ? 'EXTRACTING TACTICAL INTEL...' : 'EXTRACT & INGEST INTO TACTICAL MAP' }}</span>
            </button>

            <div v-if="msgStatus" class="heard-strip mono">{{ msgStatus }}</div>

            <div class="msg-help-note mono">
              Extracts sender, callsign, quantity (2×/3× tanks, drones, pax), coordinates/MGRS, and routes through
              {{ confirmGate ? 'Operator Confirmation Gate before plotting.' : 'live map plotting + Duty Officer queue.' }}
              Works in both Hybrid AI and 100% Offline modes.
            </div>
          </div>
        </section>
      </div>

      <!-- TAB 3: RADIO NET (Continuous Channel VAD + Demo Replay) -->
      <div v-else-if="activeTab === 'net'" class="net-stack">
        <section class="panel ops-panel">
          <div class="panel-heading">
            <span>RADIO NET MONITOR (CONTINUOUS VAD)</span>
            <span class="count-badge">{{ netSegments }} CUT</span>
          </div>
          <div class="ops-body">
            <div class="net-btn-row">
              <button
                type="button"
                class="net-ctrl-btn"
                :class="{ 'is-live': netOn && netSource !== 'file' }"
                @click="emit('net-toggle')"
              >
                <Radio :size="14" />
                <span>{{ netOn && netSource !== 'file' ? 'STOP LISTENING' : 'LISTEN TO NET' }}</span>
              </button>

              <label class="net-ctrl-btn file-label" :class="{ 'is-live': netSource === 'file' }">
                <FileAudio :size="14" />
                <span>{{ netSource === 'file' ? 'PLAYING...' : 'PLAY WAV' }}</span>
                <input type="file" accept="audio/*" @change="onFileChange" />
              </label>

              <button type="button" class="net-ctrl-btn is-gold" @click="emit('replay-demo', 'en')">
                <span>DEMO NET (EN/FR)</span>
              </button>
              <button type="button" class="net-ctrl-btn is-uk" @click="emit('replay-demo', 'uk')">
                <span>🇺🇦 DEMO NET (UK)</span>
              </button>
            </div>

            <div class="vad-meter-wrap">
              <div class="vad-meter-bar">
                <div class="vad-meter-fill" :class="{ 'is-hot': netSpeaking }" :style="{ width: `${netMeter}%` }"></div>
              </div>
              <div class="vad-meta mono">
                <span>{{ netOn ? (netSpeaking ? 'TRANSMISSION ACTIVE' : 'CHANNEL QUIET') : 'MONITOR IDLE' }}</span>
                <button type="button" class="inline-reset-btn" @click="emit('reset')">RESET NET</button>
              </div>
            </div>

            <form class="radio-text-form" @submit.prevent="submitNetText">
              <Terminal :size="14" class="radio-input-icon" />
              <input
                v-model="netInput"
                type="text"
                placeholder="Simulate net call: Zero, this is Alpha one, at the fountain, over"
              />
              <button type="submit" class="radio-send-btn" :disabled="!netInput.trim()">
                <Send :size="13" />
                <span>NET</span>
              </button>
            </form>

            <div v-if="netMsg" class="heard-strip mono">{{ netMsg }}</div>
          </div>
        </section>

        <section class="panel event-log-panel">
          <div class="panel-heading">
            <div class="heading-left">
              <span>NET TRANSCRIPT FEED</span>
              <span class="count-badge">{{ visibleTx.length }}</span>
            </div>
          </div>

          <div class="event-log net-log">
            <div v-if="!visibleTx.length" class="empty-state">
              Nothing heard on the net yet. Click <strong>DEMO NET (EN/FR)</strong> or <strong>🇺🇦 DEMO NET (UK)</strong>.
            </div>
            <div
              v-for="tx in [...visibleTx].reverse()"
              :key="'tx' + tx.id"
              class="net-tx-card"
              :class="['k-' + tx.kind, { 'is-unid': !tx.from }]"
            >
              <div class="event-row-top">
                <strong :style="{ color: colourOf(tx.from) }">{{ tx.from || 'unknown' }}</strong>
                <span class="tx-arrow">→ {{ tx.to || 'ALL' }}</span>
                <span class="tx-kind-chip mono">{{ (kindLabels[tx.kind] || tx.kind).toUpperCase() }}</span>
                <time class="mono">{{ formatZuluTime(tx.t) }}</time>
                <span v-if="tx.stt" class="mono latency-tag">{{ tx.stt.stt_ms }}ms</span>
              </div>
              <div class="event-transcript">“{{ tx.text }}”</div>
              <div class="tx-how mono">{{ tx.how }}</div>

              <template v-for="id in tx.events" :key="id">
                <div
                  v-if="byId.get(id)"
                  class="tx-linked-event mono"
                  :class="{ 'is-gone': byId.get(id).superseded }"
                  @click="byId.get(id).centre && emit('focus-coords', byId.get(id).centre)"
                >
                  <template v-if="byId.get(id).ok">
                    → <b :style="{ color: colourOf(byId.get(id).callsign) }">{{ byId.get(id).callsign }}</b>
                    {{ (byId.get(id).parsed?.relation || '').replaceAll('_', ' ') }} {{ byId.get(id).anchor }}
                    · <span class="accent-gold">{{ byId.get(id).mgrs || mgrsAt(byId.get(id).centre, { radius: byId.get(id).radius_m }) }}</span>
                    <button
                      v-if="!byId.get(id).confirmed && !byId.get(id).superseded"
                      type="button"
                      class="tiny-confirm"
                      @click.stop="emit('confirm-event', byId.get(id))"
                    >
                      CONFIRM
                    </button>
                    <span v-else-if="byId.get(id).confirmed" class="event-ok-line">✓</span>
                  </template>
                  <template v-else-if="byId.get(id).type === 'order'">
                    ▸ <b>{{ byId.get(id).callsign }}</b> {{ byId.get(id).note }}
                  </template>
                  <template v-else>
                    {{ byId.get(id).callsign }}: {{ byId.get(id).note }}
                  </template>
                </div>
              </template>
              <div v-if="tx.note" class="event-note-line">{{ tx.note }}</div>
            </div>
          </div>
        </section>
      </div>

      <!-- TAB 4: OPS / 9-LINE MEDEVAC / SALUTE / APP-6 PIN DROP -->
      <div v-else-if="activeTab === 'ops'" class="ops-stack">
        <section class="panel ops-panel">
          <div class="panel-heading">
            <span>TACTICAL MARKER DROP (APP-6)</span>
            <div class="mode-switch">
              <button type="button" :class="{ 'is-active': dropMode === 'map' }" @click="dropMode = 'map'">CLICK MAP</button>
              <button
                type="button"
                :class="{ 'is-active': dropMode === 'unit' }"
                @click="
                  dropMode = 'unit';
                  emit('arm-map-drop', null, null)
                "
              >
                AT UNIT
              </button>
            </div>
          </div>

          <div class="ops-body">
            <input
              v-model="customPinLabel"
              type="text"
              class="ops-input"
              placeholder="Optional marker callout (e.g. 2x BTR-80, LZ Alpha, CP-3)"
            />
            <div class="marker-btn-grid">
              <button
                v-for="btn in MARKER_BUTTONS"
                :key="btn.kind"
                type="button"
                class="marker-drop-btn"
                :class="[btn.cls, { 'is-armed': dropMode === 'map' && armedDropKind === btn.kind }]"
                @click="handleQuickPin(btn.kind)"
              >
                <component :is="btn.icon" :size="15" />
                <span>{{ dropMode === 'map' && armedDropKind === btn.kind ? 'CLICK MAP...' : btn.label }}</span>
              </button>
            </div>

            <div v-if="tacOverlays.length || customPlaces.length" class="active-markers-list">
              <div class="sub-label mono">
                PLOTTED OVERLAYS &amp; NAMED POINTS ({{ tacOverlays.length + customPlaces.length }})
              </div>
              <div v-for="ov in tacOverlays" :key="ov.id" class="marker-list-row">
                <button type="button" class="marker-list-focus" @click="emit('focus-coords', ov.coords)">
                  <span class="marker-kind-dot" :class="`kind-${ov.kind}`"></span>
                  <div>
                    <strong>{{ ov.label }}</strong>
                    <small class="mono">{{ mgrsAt(ov.coords, { digits: 4 }) }}</small>
                  </div>
                </button>
                <button type="button" class="marker-remove-btn" title="Remove overlay" @click="emit('remove-overlay', ov.id)">
                  <Trash2 :size="13" />
                </button>
              </div>
              <div v-for="cp in customPlaces" :key="'cp-' + cp.name" class="marker-list-row">
                <button type="button" class="marker-list-focus" @click="emit('focus-coords', [cp.lon, cp.lat])">
                  <span class="marker-kind-dot kind-rally"></span>
                  <div>
                    <strong>{{ cp.name }}</strong>
                    <small class="mono">NAMED ANCHOR · {{ mgrsAt([cp.lon, cp.lat], { digits: 4 }) }}</small>
                  </div>
                </button>
              </div>
            </div>
          </div>
        </section>

        <!-- 9-Line MEDEVAC Accordion -->
        <section class="panel ops-panel">
          <button
            type="button"
            class="panel-heading accordion-btn"
            @click="opsFormOpen = opsFormOpen === 'medevac' ? null : 'medevac'"
          >
            <span class="heading-left"><HeartPulse :size="14" class="accent-green" /> 9-LINE MEDEVAC REQUEST</span>
            <ChevronDown v-if="opsFormOpen === 'medevac'" :size="15" />
            <ChevronRight v-else :size="15" />
          </button>

          <form v-if="opsFormOpen === 'medevac'" class="ops-form" @submit.prevent="handleMedevacSubmit">
            <div class="ops-readonly-row mono">
              <span>L1 PICKUP GRID:</span>
              <strong class="accent-gold">{{ activeGrid || '31U DQ —' }}</strong>
            </div>
            <div class="ops-field-grid">
              <label>
                <span>L3 PRECEDENCE</span>
                <select v-model="medPrecedence">
                  <option>A - URGENT SURGICAL</option>
                  <option>B - PRIORITY</option>
                  <option>C - ROUTINE</option>
                </select>
              </label>
              <label>
                <span>L5 PATIENTS</span>
                <input v-model="medPatients" />
              </label>
              <label>
                <span>L6 LZ SECURITY</span>
                <select v-model="medSecurity">
                  <option>N - NO ENEMY</option>
                  <option>P - POSSIBLE ENEMY</option>
                  <option>E - ENEMY IN AREA</option>
                  <option>X - ARMED ESCORT REQ</option>
                </select>
              </label>
              <label>
                <span>L7 MARKING</span>
                <select v-model="medMarking">
                  <option>SMOKE (GREEN)</option>
                  <option>VS-17 PANELS</option>
                  <option>IR STROBE</option>
                  <option>NONE</option>
                </select>
              </label>
            </div>
            <button type="submit" class="ops-submit-btn is-medevac">
              <Radio :size="14" /> TRANSMIT 9-LINE &amp; MARK LZ
            </button>
          </form>
        </section>

        <!-- SALUTE Spot Report Accordion -->
        <section class="panel ops-panel">
          <button
            type="button"
            class="panel-heading accordion-btn"
            @click="opsFormOpen = opsFormOpen === 'salute' ? null : 'salute'"
          >
            <span class="heading-left"><Target :size="14" class="accent-red" /> SALUTE SPOT REPORT</span>
            <ChevronDown v-if="opsFormOpen === 'salute'" :size="15" />
            <ChevronRight v-else :size="15" />
          </button>

          <form v-if="opsFormOpen === 'salute'" class="ops-form" @submit.prevent="handleSaluteSubmit">
            <div class="ops-readonly-row mono">
              <span>L LOCATION (AUTO MGRS):</span>
              <strong class="accent-gold">{{ activeGrid || '31U DQ —' }}</strong>
            </div>
            <div class="ops-field-grid">
              <label>
                <span>S · QUANTITY</span>
                <input v-model.number="salCount" type="number" min="1" max="99" />
              </label>
              <label>
                <span>SIDE</span>
                <select v-model="salSide">
                  <option value="hostile">HOSTILE / ENEMY</option>
                  <option value="unknown">UNKNOWN</option>
                  <option value="neutral">NEUTRAL / CIVILIANS</option>
                </select>
              </label>
              <label>
                <span>E · TYPE / EQUIP</span>
                <select v-model="salWhat">
                  <option value="tank">Tank</option>
                  <option value="infantry">Infantry</option>
                  <option value="apc">Armoured Vehicle</option>
                  <option value="drone">Drone / FPV</option>
                  <option value="sniper">Sniper</option>
                  <option value="artillery">Artillery</option>
                  <option value="ied">IED / Mine</option>
                </select>
              </label>
              <label>
                <span>A · ACTIVITY</span>
                <select v-model="salActivity">
                  <option value="moving">Moving</option>
                  <option value="static">Static</option>
                  <option value="firing">Firing</option>
                </select>
              </label>
              <label v-if="salActivity === 'moving'">
                <span>HEADING</span>
                <select v-model="salHeading">
                  <option value="north">North</option>
                  <option value="northeast">Northeast</option>
                  <option value="east">East</option>
                  <option value="southeast">Southeast</option>
                  <option value="south">South</option>
                  <option value="southwest">Southwest</option>
                  <option value="west">West</option>
                  <option value="northwest">Northwest</option>
                </select>
              </label>
              <label :class="{ 'span-2': salActivity !== 'moving' }">
                <span>REMARKS</span>
                <input v-model="salRemarks" />
              </label>
            </div>
            <button type="submit" class="ops-submit-btn is-salute">
              <Target :size="14" /> TRANSMIT SALUTE &amp; PLOT APP-6 CONTACT
            </button>
          </form>
        </section>
      </div>

      <!-- TAB 5: BFT SQUAD & ACTIVE CONTACTS -->
      <div v-else-if="activeTab === 'bft'" class="bft-stack">
        <div class="sub-section-header mono">FRIENDLY FORCES · BLUE FORCE TRACKING ({{ unitRoster.length }})</div>
        <div v-if="!unitRoster.length" class="panel empty-state">
          No friendly positions plotted yet. Run a demo or transmit a voice/text report.
        </div>

        <article
          v-for="u in unitRoster"
          :key="u.callsign"
          class="bft-card"
          :class="{
            'is-active': u.callsign === callsign,
            'status-sos': u.threats.length > 0,
            'status-amber': u.suspected && !u.threats.length,
          }"
        >
          <div class="bft-card-top">
            <button type="button" class="bft-card-title" @click="emit('select-unit', u)">
              <i class="queue-sym" v-html="u.svg"></i>
              <div>
                <strong :style="{ color: u.colour }">{{ u.callsign }}</strong>
                <small>{{ u.anchor }} · ±{{ Math.round(u.radius_m) }}m · {{ ago(u.t) }}</small>
              </div>
            </button>
            <span
              class="readiness-pill"
              :class="u.threats.length ? 'status-red' : u.suspected ? 'status-amber' : 'status-green'"
            >
              {{ u.threats.length ? 'THREAT' : u.suspected ? 'DOUBT' : 'NOMINAL' }}
            </span>
          </div>
          <div class="bft-card-telemetry mono">
            <span><MapPin :size="11" /> {{ u.mgrs || mgrsAt(u.centre, { radius: u.radius_m }) }}</span>
            <span>{{ u.confirmed ? '✓ CONFIRMED' : 'DRAFT' }}</span>
          </div>
          <div v-if="u.task" class="bft-task-line mono">▸ TASKED TO: {{ u.task.target?.anchor }}</div>
          <div v-for="w in u.threats" :key="w.what + w.d" class="threat-alert-strip mono">
            ⚠ {{ w.what }} {{ w.d ? `${w.d}m ${w.dir}` : 'AT POSITION' }}
          </div>
        </article>

        <div class="sub-section-header mono" style="margin-top: 6px">
          ACTIVE CONTACTS &amp; HAZARDS ({{ contactsOnMap.length }})
        </div>
        <div v-if="!contactsOnMap.length" class="panel empty-state">No active contacts or hazards plotted.</div>

        <article
          v-for="c in contactsOnMap"
          :key="c.callsign"
          class="bft-card contact-roster-card"
          :style="{ borderLeftColor: sideOf(c.contact).colour }"
        >
          <div class="bft-card-top">
            <button type="button" class="bft-card-title" @click="c.centre && emit('focus-coords', c.centre)">
              <i class="queue-sym" v-html="draftSymbol(c)"></i>
              <div>
                <strong :style="{ color: sideOf(c.contact).colour }">{{ describeContact(c.contact) }}</strong>
                <small>{{ c.anchor }} · seen by {{ c.seen_by?.join(', ') || 'unknown' }} · {{ age(c.t) }}</small>
              </div>
            </button>
            <span class="qty-chip mono">{{ c.contact?.count || 1 }}×</span>
          </div>
          <div class="bft-card-telemetry mono">
            <span><MapPin :size="11" /> {{ c.mgrs || mgrsAt(c.centre, { radius: c.radius_m }) }}</span>
            <span>{{ c.expired ? 'STALE HAZARD' : c.trackConfirmed || c.confirmed ? '✓ CONFIRMED' : 'DRAFT' }}</span>
          </div>
          <div v-if="!(c.trackConfirmed || c.confirmed)" class="bft-card-footer">
            <span class="mono bft-comms-tag">Awaiting duty officer verification</span>
            <div class="queue-btns">
              <button type="button" class="q-btn is-confirm" @click="emit('confirm-event', c)"><Check :size="12" /></button>
              <button type="button" class="q-btn is-reject" @click="emit('reject-event', c)"><X :size="12" /></button>
            </div>
          </div>
        </article>
      </div>
    </div>
  </aside>
</template>
