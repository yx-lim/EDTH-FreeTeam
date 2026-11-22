<script setup>
import { onMounted, ref, watch } from 'vue'
import QRCode from 'qrcode'
import { Check, Copy, Radio, Smartphone, Wifi, X } from 'lucide-vue-next'

const props = defineProps({
  open: Boolean,
  handsets: { type: Object, default: () => ({ count: 0, transmitting: false, active_callsign: null }) },
})

const emit = defineEmits(['close'])

const info = ref(null)
const qrDataUrl = ref('')
const useHttp = ref(false)
const copied = ref(false)

async function loadNetwork() {
  const res = await fetch('/api/network-info').then((r) => (r.ok ? r.json() : null)).catch(() => null)
  if (!res) return
  info.value = res
  await renderQr()
}

async function renderQr() {
  if (!info.value) return
  const targetUrl = useHttp.value ? info.value.http_handset_url : info.value.https_handset_url
  qrDataUrl.value = await QRCode.toDataURL(targetUrl, {
    width: 220,
    margin: 2,
    color: { dark: '#0d1319', light: '#ecf2f7' },
  })
}

async function copyUrl() {
  if (!info.value) return
  const targetUrl = useHttp.value ? info.value.http_handset_url : info.value.https_handset_url
  try {
    await navigator.clipboard.writeText(targetUrl)
    copied.value = true
    window.setTimeout(() => {
      copied.value = false
    }, 1800)
  } catch {}
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) loadNetwork()
  },
)
watch(useHttp, renderQr)
onMounted(() => {
  if (props.open) loadNetwork()
})
</script>

<template>
  <div v-if="open" class="modal-backdrop" @click.self="emit('close')">
    <section class="phone-modal" role="dialog" aria-modal="true" aria-label="Phone Wireless Microphone">
      <header class="phone-modal-header">
        <div class="heading-left">
          <Smartphone :size="16" class="accent-gold" />
          <span>WIRELESS PHONE MICROPHONE HANDSET</span>
        </div>
        <button type="button" class="icon-action-btn" aria-label="Close" @click="emit('close')">
          <X :size="14" />
        </button>
      </header>

      <div class="phone-modal-body">
        <div class="handset-live-bar mono" :class="{ 'is-linked': handsets.count > 0, 'is-tx': handsets.transmitting }">
          <Radio :size="14" />
          <span v-if="handsets.transmitting">
            PHONE TX LIVE · {{ (handsets.active_callsign || 'FIELD UNIT').toUpperCase() }}
          </span>
          <span v-else-if="handsets.count > 0">
            {{ handsets.count }} PHONE HANDSET{{ handsets.count > 1 ? 'S' : '' }} LINKED TO C2
          </span>
          <span v-else-if="info?.cloud">READY — SCAN QR CODE FROM ANY SMARTPHONE</span>
          <span v-else>WAITING FOR PHONE HANDSET ON SAME WI-FI ({{ info?.lan_ip || 'LAN' }})</span>
        </div>

        <div class="qr-layout">
          <div class="qr-box">
            <img v-if="qrDataUrl" :src="qrDataUrl" alt="Scan QR code with phone" />
            <div v-else class="empty-state">Generating QR…</div>
          </div>

          <div class="qr-instructions">
            <div v-if="!info?.cloud" class="mode-switch" style="align-self: flex-start">
              <button type="button" :class="{ 'is-active': !useHttp }" @click="useHttp = false">
                HTTPS (LIVE MIC)
              </button>
              <button type="button" :class="{ 'is-active': useHttp }" @click="useHttp = true">
                HTTP FALLBACK
              </button>
            </div>

            <ol v-if="info?.cloud" class="phone-steps">
              <li>Scan the QR code with any iPhone or Android camera (works over Wi-Fi or 4G/5G).</li>
              <li>Allow microphone permission when prompted (trusted HTTPS — no cert warning).</li>
              <li>Hold <strong>PUSH TO TALK</strong> on your phone — reports stream live onto this C2 map!</li>
            </ol>
            <ol v-else class="phone-steps">
              <li>Connect your phone to the <strong>same Wi-Fi</strong> as this laptop.</li>
              <li>Scan the QR code with your iPhone or Android camera.</li>
              <li v-if="!useHttp">
                Tap <strong>Advanced → Proceed</strong> once (local self-signed TLS enables real-time mobile microphone).
              </li>
              <li v-else>Use native Voice Capture or Text Radio fallback on plain HTTP.</li>
              <li>Hold <strong>PUSH TO TALK</strong> on your phone — reports stream live onto this C2 map!</li>
            </ol>

            <div v-if="info" class="url-copy-row mono">
              <span>{{ useHttp ? info.http_handset_url : info.https_handset_url }}</span>
              <button type="button" class="icon-action-btn" @click="copyUrl">
                <Check v-if="copied" :size="12" />
                <Copy v-else :size="12" />
                <span>{{ copied ? 'COPIED' : 'COPY' }}</span>
              </button>
            </div>

            <div class="wifi-note mono">
              <Wifi :size="12" />
              <template v-if="info?.cloud">TRUSTED CLOUD HTTPS · {{ info.lan_ip }}</template>
              <template v-else>LAN IP: {{ info?.lan_ip || 'detecting…' }} · HTTPS Bridge :8443</template>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
