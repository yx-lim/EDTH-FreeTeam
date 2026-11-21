<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { Pause, Play, Radio, SkipBack, SkipForward } from 'lucide-vue-next'
import { formatZuluTime } from '../tactical.js'

const props = defineProps({
  total: { type: Number, default: 0 },
  cursor: { type: Number, default: 0 },
  currentTime: { type: Number, default: null },
})

const emit = defineEmits(['update:cursor'])

const playing = ref(false)
let timer = null

const isLive = computed(() => props.cursor >= props.total)

function stopPlay() {
  playing.value = false
  if (timer) {
    window.clearInterval(timer)
    timer = null
  }
}

function togglePlay() {
  if (playing.value) {
    stopPlay()
    return
  }
  if (props.total < 1) return
  if (props.cursor >= props.total) {
    emit('update:cursor', 1)
  }
  playing.value = true
  timer = window.setInterval(() => {
    if (props.cursor >= props.total) {
      stopPlay()
      return
    }
    emit('update:cursor', props.cursor + 1)
  }, 1200)
}

function step(delta) {
  stopPlay()
  const next = Math.max(0, Math.min(props.total, props.cursor + delta))
  emit('update:cursor', next)
}

function goLive() {
  stopPlay()
  emit('update:cursor', props.total)
}

watch(
  () => props.total,
  (len) => {
    if (len === 0) stopPlay()
  },
)

onUnmounted(stopPlay)
</script>

<template>
  <section v-if="total === 0" class="replay-control is-idle">
    <div class="replay-empty mono">AAR TIMELINE READY · AWAITING FIRST RADIO TRANSMISSION</div>
  </section>

  <section v-else class="replay-control">
    <div class="replay-actions">
      <button
        type="button"
        class="replay-btn"
        :disabled="total < 2"
        :title="playing ? 'Pause AAR replay' : 'Play AAR replay'"
        @click="togglePlay"
      >
        <Pause v-if="playing" :size="13" />
        <Play v-else :size="13" />
      </button>
      <button
        type="button"
        class="replay-btn"
        :disabled="cursor <= 0"
        title="Step backward"
        @click="step(-1)"
      >
        <SkipBack :size="13" />
      </button>
      <button
        type="button"
        class="replay-btn"
        :disabled="isLive"
        title="Step forward"
        @click="step(1)"
      >
        <SkipForward :size="13" />
      </button>
    </div>

    <div class="replay-track">
      <div class="replay-label mono">
        <span>AAR PLAYBACK · {{ cursor }}/{{ total }}</span>
        <time>{{ currentTime ? formatZuluTime(currentTime) : 'LIVE' }}</time>
      </div>
      <input
        aria-label="Replay mission history"
        type="range"
        min="0"
        :max="total"
        :value="cursor"
        @input="
          stopPlay();
          emit('update:cursor', Number($event.target.value))
        "
      />
    </div>

    <button type="button" class="replay-live-btn" :class="{ 'is-live': isLive }" @click="goLive">
      <Radio :size="12" />
      <span>LIVE</span>
    </button>
  </section>
</template>
