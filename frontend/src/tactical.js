// Pure tactical geometry, NATO DTG/Zulu formatting, and radio audio cues for MapLibre [lon, lat] coordinates.

const RAD = Math.PI / 180
const DEG = 180 / Math.PI
const EARTH_R = 6371000

export function formatDTG(date = new Date()) {
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  const dd = String(date.getUTCDate()).padStart(2, '0')
  const hh = String(date.getUTCHours()).padStart(2, '0')
  const mm = String(date.getUTCMinutes()).padStart(2, '0')
  const ss = String(date.getUTCSeconds()).padStart(2, '0')
  const mon = months[date.getUTCMonth()]
  const yy = String(date.getUTCFullYear()).slice(-2)
  return `${dd}${hh}${mm}:${ss}Z ${mon} ${yy}`
}

export function formatZuluTime(epochSec) {
  const date = epochSec != null ? new Date(epochSec * 1000) : new Date()
  if (Number.isNaN(date.getTime())) return '--:--:--Z'
  const hh = String(date.getUTCHours()).padStart(2, '0')
  const mm = String(date.getUTCMinutes()).padStart(2, '0')
  const ss = String(date.getUTCSeconds()).padStart(2, '0')
  return `${hh}:${mm}:${ss}Z`
}

export function haversineMeters(a, b) {
  if (!a || !b) return 0
  const [lon1, lat1] = a
  const [lon2, lat2] = b
  const dLat = (lat2 - lat1) * RAD
  const dLon = (lon2 - lon1) * RAD
  const sLat = Math.sin(dLat / 2)
  const sLon = Math.sin(dLon / 2)
  const h = sLat * sLat + Math.cos(lat1 * RAD) * Math.cos(lat2 * RAD) * sLon * sLon
  return 2 * EARTH_R * Math.asin(Math.min(1, Math.sqrt(h)))
}

export function totalTrailDistance(lonLatList) {
  if (!lonLatList || lonLatList.length < 2) return 0
  let sum = 0
  for (let i = 1; i < lonLatList.length; i += 1) {
    sum += haversineMeters(lonLatList[i - 1], lonLatList[i])
  }
  return sum
}

export function bearingDegrees(a, b) {
  if (!a || !b) return 0
  const [lon1, lat1] = a
  const [lon2, lat2] = b
  const dLon = (lon2 - lon1) * RAD
  const y = Math.sin(dLon) * Math.cos(lat2 * RAD)
  const x = Math.cos(lat1 * RAD) * Math.sin(lat2 * RAD) - Math.sin(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.cos(dLon)
  return (Math.atan2(y, x) * DEG + 360) % 360
}

export function headingToCardinal(deg) {
  const dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
  const norm = ((deg % 360) + 360) % 360
  return dirs[Math.round(norm / 22.5) % 16]
}

export function formatDistance(meters) {
  if (!Number.isFinite(meters) || meters <= 0) return '0m'
  if (meters >= 1000) return `${(meters / 1000).toFixed(2)}km`
  return `${Math.round(meters)}m`
}

export function destinationLonLat([lon, lat], bearingDeg, distanceM) {
  const brng = bearingDeg * RAD
  const lat1 = lat * RAD
  const lon1 = lon * RAD
  const ang = distanceM / EARTH_R
  const lat2 = Math.asin(Math.sin(lat1) * Math.cos(ang) + Math.cos(lat1) * Math.sin(ang) * Math.cos(brng))
  const lon2 = lon1 + Math.atan2(Math.sin(brng) * Math.sin(ang) * Math.cos(lat1), Math.cos(ang) - Math.sin(lat1) * Math.sin(lat2))
  return [lon2 * DEG, lat2 * DEG]
}

export function circleCoords([lon, lat], radiusM, steps = 56) {
  const kx = 111320 * Math.cos(lat * RAD)
  const ky = 110540
  return Array.from({ length: steps + 1 }, (_, i) => {
    const a = (i / steps) * 2 * Math.PI
    return [lon + (radiusM * Math.sin(a)) / kx, lat + (radiusM * Math.cos(a)) / ky]
  })
}

export function rangeRingsGeoJson(centre) {
  if (!centre) return { type: 'FeatureCollection', features: [] }
  const rings = [
    { r: 100, colour: '#38bdf8', label: '100m' },
    { r: 250, colour: '#38bdf8', label: '250m' },
    { r: 500, colour: '#e5b84b', label: '500m' },
  ]
  return {
    type: 'FeatureCollection',
    features: rings.map(({ r, colour, label }) => ({
      type: 'Feature',
      properties: { colour, label, radius: r },
      geometry: { type: 'Polygon', coordinates: [circleCoords(centre, r)] },
    })),
  }
}

export function fovConeGeoJson(centre, headingDeg = 0, rangeM = 280, halfSpread = 28) {
  if (!centre) return { type: 'FeatureCollection', features: [] }
  const pts = [centre]
  for (let offset = -halfSpread; offset <= halfSpread; offset += 7) {
    pts.push(destinationLonLat(centre, (headingDeg + offset + 360) % 360, rangeM))
  }
  pts.push(centre)
  return {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [pts] } }],
  }
}

export function detectThreatLevel(event) {
  if (!event) return 'normal'
  if (event.type === 'sos') return 'critical'
  if (event.type === 'contact') {
    if (event.contact?.side === 'hostile' || event.contact?.what === 'ied') return 'critical'
    if (event.contact?.side === 'unknown') return 'caution'
  }
  if ((event.threats || []).length > 0) return 'critical'
  if (event.ambiguous || event.callsign_assumed || event.type === 'unidentified' || event.rejected) return 'caution'
  if (!event.ok && !['intent', 'order'].includes(event.type)) return 'caution'
  return 'normal'
}

export function playRadioTone(kind = 'ptt_start') {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext
    if (!AudioCtx) return
    const ctx = new AudioCtx()
    const now = ctx.currentTime
    const beep = (freq, startOffset, duration, gainVal = 0.045, type = 'sine') => {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = type
      osc.frequency.setValueAtTime(freq, now + startOffset)
      gain.gain.setValueAtTime(gainVal, now + startOffset)
      gain.gain.exponentialRampToValueAtTime(0.0001, now + startOffset + duration)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start(now + startOffset)
      osc.stop(now + startOffset + duration + 0.01)
    }

    if (kind === 'ptt_start') {
      beep(1150, 0, 0.05, 0.045, 'triangle')
      beep(1450, 0.05, 0.04, 0.038, 'triangle')
    } else if (kind === 'ptt_stop') {
      beep(920, 0, 0.055, 0.04, 'triangle')
    } else if (kind === 'ack') {
      beep(880, 0, 0.055, 0.038, 'sine')
      beep(1320, 0.065, 0.08, 0.042, 'sine')
    } else if (kind === 'sos') {
      beep(980, 0, 0.14, 0.085, 'sawtooth')
      beep(740, 0.17, 0.14, 0.085, 'sawtooth')
      beep(980, 0.34, 0.16, 0.085, 'sawtooth')
    }

    window.setTimeout(() => ctx.close().catch(() => {}), 800)
  } catch {
    // Ignore autoplay/audio restrictions
  }
}

export function createOverlayCanvasImage(kind) {
  const size = 64
  const c = document.createElement('canvas')
  c.width = c.height = size
  const g = c.getContext('2d')
  const cx = size / 2
  const cy = size / 2

  if (kind === 'sos') {
    g.beginPath()
    g.arc(cx, cy, 26, 0, Math.PI * 2)
    g.fillStyle = 'rgba(220, 38, 38, 0.28)'
    g.fill()
    g.lineWidth = 3
    g.strokeStyle = '#ef4444'
    g.stroke()

    g.beginPath()
    g.arc(cx, cy, 18, 0, Math.PI * 2)
    g.fillStyle = '#dc2626'
    g.fill()
    g.strokeStyle = '#ffffff'
    g.lineWidth = 2.5
    g.stroke()

    g.fillStyle = '#ffffff'
    g.font = 'bold 13px "JetBrains Mono", monospace'
    g.textAlign = 'center'
    g.textBaseline = 'middle'
    g.fillText('SOS', cx, cy + 0.5)
  } else if (kind === 'medevac') {
    g.fillStyle = 'rgba(21, 128, 61, 0.94)'
    g.strokeStyle = '#bbf7d0'
    g.lineWidth = 3
    g.beginPath()
    g.roundRect(12, 12, 40, 40, 8)
    g.fill()
    g.stroke()
    g.fillStyle = '#ffffff'
    g.fillRect(27, 19, 10, 26)
    g.fillRect(19, 27, 26, 10)
  } else {
    // rally point
    g.beginPath()
    g.arc(cx, cy, 18, 0, Math.PI * 2)
    g.fillStyle = 'rgba(14, 116, 144, 0.92)'
    g.fill()
    g.strokeStyle = '#bae6fd'
    g.lineWidth = 3
    g.stroke()
    g.beginPath()
    g.arc(cx, cy, 5, 0, Math.PI * 2)
    g.fillStyle = '#ffffff'
    g.fill()
  }

  return { width: size, height: size, data: new Uint8Array(g.getImageData(0, 0, size, size).data.buffer) }
}
