// MGRS on the map: grid lines for the visible area and grid references for the cursor and each report.
// MGRS digits are the UTM easting and northing (modulo 100 km), so the 1 km grid is the UTM kilometre grid.
// Letters come from the `mgrs` package (proj4js); the lines use the textbook UTM series below (well under 1 m
// error inside a zone), which is plenty for drawing a grid.
import * as mgrsLib from 'mgrs'

const forward = mgrsLib.forward ?? mgrsLib.default.forward   // CommonJS in Node, ES module in Vite

const A = 6378137, F = 1 / 298.257223563, K0 = 0.9996
const E2 = F * (2 - F), EP2 = E2 / (1 - E2), E4 = E2 * E2, E6 = E4 * E2
const RAD = Math.PI / 180

export const zoneOf = (lon) => Math.floor((lon + 180) / 6) + 1
const centralMeridian = (zone) => ((zone - 1) * 6 - 180 + 3) * RAD

export function toUtm(lat, lon, zone = zoneOf(lon)) {
  const phi = lat * RAD, lam = lon * RAD - centralMeridian(zone)
  const s = Math.sin(phi), c = Math.cos(phi), t = Math.tan(phi)
  const N = A / Math.sqrt(1 - E2 * s * s), T = t * t, C = EP2 * c * c, Aa = c * lam
  const M = A * ((1 - E2 / 4 - 3 * E4 / 64 - 5 * E6 / 256) * phi - (3 * E2 / 8 + 3 * E4 / 32 + 45 * E6 / 1024) * Math.sin(2 * phi)
    + (15 * E4 / 256 + 45 * E6 / 1024) * Math.sin(4 * phi) - (35 * E6 / 3072) * Math.sin(6 * phi))
  const e = K0 * N * (Aa + (1 - T + C) * Aa ** 3 / 6 + (5 - 18 * T + T * T + 72 * C - 58 * EP2) * Aa ** 5 / 120) + 500000
  let n = K0 * (M + N * t * (Aa * Aa / 2 + (5 - T + 9 * C + 4 * C * C) * Aa ** 4 / 24
    + (61 - 58 * T + T * T + 600 * C - 330 * EP2) * Aa ** 6 / 720))
  if (lat < 0) n += 10000000
  return [e, n]
}

export function fromUtm(e, n, zone, south = false) {
  const x = e - 500000, y = south ? n - 10000000 : n
  const mu = y / K0 / (A * (1 - E2 / 4 - 3 * E4 / 64 - 5 * E6 / 256))
  const e1 = (1 - Math.sqrt(1 - E2)) / (1 + Math.sqrt(1 - E2))
  const p1 = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
    + (151 * e1 ** 3 / 96) * Math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * Math.sin(8 * mu)
  const s = Math.sin(p1), c = Math.cos(p1), t = Math.tan(p1)
  const N1 = A / Math.sqrt(1 - E2 * s * s), T1 = t * t, C1 = EP2 * c * c
  const R1 = A * (1 - E2) / (1 - E2 * s * s) ** 1.5, D = x / (N1 * K0)
  const lat = p1 - (N1 * t / R1) * (D * D / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * EP2) * D ** 4 / 24
    + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * EP2 - 3 * C1 * C1) * D ** 6 / 720)
  const lon = centralMeridian(zone) + (D - (1 + 2 * T1 + C1) * D ** 3 / 6
    + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * EP2 + 24 * T1 * T1) * D ** 5 / 120) / c
  return [lon / RAD, lat / RAD]
}

// "31UDQ59780936" -> "31U DQ 5978 0936"
export function formatMgrs(raw) {
  const m = /^(\d{1,2}[C-X])([A-Z]{2})(\d*)$/.exec(raw)
  if (!m) return raw
  const d = m[3], h = d.length / 2
  return [m[1], m[2], d.slice(0, h), d.slice(h)].filter(Boolean).join(' ')
}

// Same rule as backend/grid.py: the square is at least as wide as the uncertainty, so ±40 m reads as a 100 m square.
export function digitsForRadius(radius) {
  for (const d of [5, 4, 3, 2, 1]) if (10 ** (5 - d) >= radius) return d
  return 1
}

export function mgrsAt([lon, lat], { digits = 5, radius } = {}) {
  try {
    return formatMgrs(forward([lon, lat], radius != null ? digitsForRadius(radius) : digits))
  } catch {
    return ''   // outside MGRS coverage (polar caps) or not a number
  }
}

// Grid lines and edge labels for the visible area: 1 km squares when zoomed in, 10 km further out, none beyond.
export function gridLines(bounds, zoom) {
  const step = zoom >= 12.5 ? 1000 : zoom >= 9.5 ? 10000 : null
  const empty = { lines: { type: 'FeatureCollection', features: [] }, labels: { type: 'FeatureCollection', features: [] } }
  if (!step) return empty
  const w = bounds.getWest(), s = bounds.getSouth(), e = bounds.getEast(), n = bounds.getNorth()
  const zone = zoneOf((w + e) / 2), south = (s + n) / 2 < 0
  const corners = [[s, w], [s, e], [n, w], [n, e]].map(([la, lo]) => toUtm(la, lo, zone))
  const minE = Math.min(...corners.map((c) => c[0])), maxE = Math.max(...corners.map((c) => c[0]))
  const minN = Math.min(...corners.map((c) => c[1])), maxN = Math.max(...corners.map((c) => c[1]))
  if ((maxE - minE) / step > 80 || (maxN - minN) / step > 80) return empty
  const lines = [], labels = [], SAMPLES = 16
  const label = (v) => String(Math.round(v / 1000) % 100).padStart(2, '0')
  for (let x = Math.ceil(minE / step) * step; x <= maxE; x += step) {
    const coords = Array.from({ length: SAMPLES + 1 }, (_, i) => fromUtm(x, minN + ((maxN - minN) * i) / SAMPLES, zone, south))
    lines.push({ type: 'Feature', properties: { major: x % 10000 === 0 }, geometry: { type: 'LineString', coordinates: coords } })
    labels.push({ type: 'Feature', properties: { label: label(x) },
      geometry: { type: 'Point', coordinates: fromUtm(x, maxN - (maxN - minN) * 0.04, zone, south) } })
  }
  for (let y = Math.ceil(minN / step) * step; y <= maxN; y += step) {
    const coords = Array.from({ length: SAMPLES + 1 }, (_, i) => fromUtm(minE + ((maxE - minE) * i) / SAMPLES, y, zone, south))
    lines.push({ type: 'Feature', properties: { major: y % 10000 === 0 }, geometry: { type: 'LineString', coordinates: coords } })
    labels.push({ type: 'Feature', properties: { label: label(y) },
      geometry: { type: 'Point', coordinates: fromUtm(minE + (maxE - minE) * 0.03, y, zone, south) } })
  }
  return { lines: { type: 'FeatureCollection', features: lines }, labels: { type: 'FeatureCollection', features: labels } }
}
