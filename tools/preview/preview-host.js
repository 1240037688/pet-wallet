/**
 * Preview host — mounts the built desktop artifact against the shim ctx.
 *
 * DEV TOOL ONLY. Loaded by the preview page (bundled with real react-dom).
 * Provides a minimal ctx (rest/onEvent/onDispose/register/storage), mounts
 * statusbar contributions with real react-dom, and records uncaught errors
 * into window.__preview.errors for automated verification.
 */
import { createRoot } from 'react-dom/client'

const disposers = []
const storageMap = new Map()
const ctx = {
  rest: async (path, opts) => {
    const res = await fetch(`/api/plugins/whale-widget${path}`, opts)
    if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`)
    return res.json()
  },
  onEvent: () => () => {},
  onDispose: (fn) => disposers.push(fn),
  storage: {
    get: (key, fallback = null) => (storageMap.has(key) ? storageMap.get(key) : fallback),
    set: (key, value) => storageMap.set(key, value),
  },
  register: (contrib) => {
    window.__preview.registrations.push(contrib)
    mountContribution(contrib)
  },
}

function mountContribution(contrib) {
  if (contrib.area === 'statusBar.right') {
    const container = document.getElementById('statusbar-right')
    const root = createRoot(container)
    root.render(contrib.render())
  } else {
    const container = document.getElementById('other-areas')
    const row = document.createElement('div')
    row.className = 'unmounted-area'
    row.textContent = `registered contribution "${contrib.id}" in area "${String(contrib.area)}" (no preview mount)`
    container.appendChild(row)
  }
}

window.__preview = { registrations: [], errors: [], ready: false }
window.addEventListener('error', (event) => window.__preview.errors.push(String(event.message)))
window.addEventListener('unhandledrejection', (event) => window.__preview.errors.push(String(event.reason)))

try {
  const mod = await import('/desktop/plugin.js')
  mod.default.register(ctx)
  window.__preview.ready = true
} catch (err) {
  window.__preview.errors.push(`register failed: ${err?.stack || err}`)
}
