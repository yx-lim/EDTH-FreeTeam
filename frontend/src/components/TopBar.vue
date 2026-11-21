<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import {
  Compass,
  Eye,
  Moon,
  Radio,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  Volume2,
  VolumeX,
  Wifi,
  WifiOff,
} from 'lucide-vue-next'
import { formatDTG, headingToCardinal } from '../tactical.js'

const props = defineProps({
  connected: Boolean,
  statusText: String,
  activeCallsign: String,
  activeGrid: String,
  activeRadius: Number,
  activeHeading: { type: Number, default: 0 },
  readBack: Boolean,
  nvgMode: Boolean,
  redNight: Boolean,
  offlineMode: Boolean,
  confirmGate: Boolean,
  hasSos: Boolean,
  threatCount: { type: Number, default: 0 },
  sttLabel: String,
  handsets: { type: Object, default: () => ({ count: 0, transmitting: false, active_callsign: null }) },
})

const emit = defineEmits([
  'toggle-readback',
  'toggle-nvg',
  'toggle-red-night',
  'toggle-offline',
  'toggle-confirm-gate',
  'open-phone-mic',
])

const dtg = ref(formatDTG(new Date()))
let timer

onMounted(() => {
  timer = window.setInterval(() => {
    dtg.value = formatDTG(new Date())
  }, 1000)
})

onUnmounted(() => {
  window.clearInterval(timer)
})
</script>

<template>
  <header class="topbar" :class="{ 'has-sos': hasSos || threatCount > 0 }">
    <div class="topbar-brand">
      <div class="brand-emblem" aria-hidden="true">
        <Radio :size="18" />
      </div>
      <div>
        <p class="eyebrow">C2 COP // AO PARIS</p>
        <h1>Voice-to-Map</h1>
      </div>
    </div>

    <div class="topbar-telemetry">
      <div class="hud-chip">
        <span class="hud-chip-label">DTG ZULU</span>
        <span class="hud-chip-value mono">{{ dtg }}</span>
      </div>

      <div class="hud-chip">
        <span class="hud-chip-label">
          GRID · {{ (activeCallsign || 'UNASSIGNED').toUpperCase() }}
          <template v-if="activeRadius"> (±{{ Math.round(activeRadius) }}m)</template>
        </span>
        <span class="hud-chip-value mono accent-gold">{{ activeGrid || '31U DQ —' }}</span>
      </div>

      <div class="hud-chip hud-chip-compact">
        <span class="hud-chip-label"><Compass :size="11" /> HDG</span>
        <span class="hud-chip-value mono">
          {{ String(Math.round(activeHeading)).padStart(3, '0') }}° {{ headingToCardinal(activeHeading) }}
        </span>
      </div>

      <div v-if="hasSos" class="hud-sos-badge" role="status">
        <ShieldAlert :size="14" />
        <span>SOS ACTIVE</span>
      </div>
      <div v-else-if="threatCount > 0" class="hud-sos-badge" role="status">
        <ShieldAlert :size="14" />
        <span>{{ threatCount }} THREAT{{ threatCount > 1 ? 'S' : '' }}</span>
      </div>
    </div>

    <div class="topbar-actions">
      <!-- Offline / Hybrid Ops Switch -->
      <button
        type="button"
        class="hud-toggle"
        :class="offlineMode ? 'is-offline-active' : 'is-active'"
        title="Switch between Hybrid AI (Gemini+OSM) and 100% Offline Ops (local rules + local vector street map)"
        @click="emit('toggle-offline')"
      >
        <WifiOff v-if="offlineMode" :size="14" />
        <Wifi v-else :size="14" />
        <span>{{ offlineMode ? 'OFFLINE OPS' : 'HYBRID AI' }}</span>
      </button>

      <!-- Operator Confirm-Before-Map Gate Switch -->
      <button
        type="button"
        class="hud-toggle"
        :class="{ 'is-gate-active': confirmGate }"
        title="When ON, every report is held for operator approval before appearing on the live map"
        @click="emit('toggle-confirm-gate')"
      >
        <ShieldCheck :size="14" />
        <span>{{ confirmGate ? 'GATE: ON' : 'AUTO-PLOT' }}</span>
      </button>

      <!-- Wireless Phone Microphone QR Button -->
      <button
        type="button"
        class="hud-toggle"
        :class="{
          'is-phone-linked': handsets.count > 0 && !handsets.transmitting,
          'is-phone-tx': handsets.transmitting,
        }"
        title="Use your smartphone as a live wireless tactical microphone"
        @click="emit('open-phone-mic')"
      >
        <Smartphone :size="14" />
        <span>{{ handsets.transmitting ? 'PHONE TX' : handsets.count > 0 ? `PHONE (${handsets.count})` : 'PHONE MIC' }}</span>
      </button>

      <button
        type="button"
        class="hud-toggle hud-toggle-compact"
        :class="{ 'is-active': readBack }"
        title="Toggle spoken tactical read-back confirmation"
        @click="emit('toggle-readback')"
      >
        <Volume2 v-if="readBack" :size="14" />
        <VolumeX v-else :size="14" />
        <span>ACK</span>
      </button>

      <button
        type="button"
        class="hud-toggle hud-toggle-compact"
        :class="{ 'is-nvg-active': nvgMode }"
        title="Toggle green phosphor Night Vision Goggle (NVG) mode"
        @click="emit('toggle-nvg')"
      >
        <Eye :size="14" />
        <span>NVG</span>
      </button>

      <button
        type="button"
        class="hud-toggle hud-toggle-compact"
        :class="{ 'is-red-active': redNight }"
        title="Toggle command-post red-on-black mode"
        @click="emit('toggle-red-night')"
      >
        <Moon :size="14" />
      </button>

      <div class="connection" :class="{ 'is-connected': connected }">
        <span class="conn-dot"></span>
        <div class="conn-text">
          <strong>{{ connected ? 'LIVE LINK' : 'OFFLINE' }}</strong>
          <small>{{ connected ? (offlineMode ? 'LOCAL RULES' : (sttLabel || 'BROWSER').toUpperCase()) : statusText.toUpperCase() }}</small>
        </div>
      </div>
    </div>
  </header>
</template>
