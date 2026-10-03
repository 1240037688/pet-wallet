#!/usr/bin/env node
/**
 * dev-preview.mjs — local preview of the built desktop artifact WITHOUT Hermes.
 *
 * (IMPLEMENTATION_PLAN M0 task 7.) Serves:
 *   /                                    → preview.html (import map + mounts)
 *   /desktop/plugin.js                   → the BUILT artifact
 *   /shims/*.js                          → esbuild-bundled shims (tools/preview/)
 *   /preview-host.js                     → esbuild-bundled preview host
 *   /api/plugins/whale-widget/health     → mock dashboard-half response
 *
 * Usage: node tools/dev-preview.mjs [--port 8123]
 * Acceptance (M0): the page shows the whale chip placeholder with health
 * state "ok", and window.__preview has {ready:true, errors:[]}.
 *
 * DEV TOOL ONLY — generates bundles into tools/.preview-build/ (gitignored).
 */
import { build } from 'esbuild'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const TOOLS_DIR = path.join(ROOT, 'tools')
const BUILD_DIR = path.join(TOOLS_DIR, '.preview-build')
const ARTIFACT = path.join(ROOT, 'plugin-src/hermes-whale-widget/desktop/plugin.js')

const args = process.argv.slice(2)
const portIdx = args.indexOf('--port')
const PORT = portIdx >= 0 ? Number(args[portIdx + 1]) || 8123 : 8123

// ── shim bundles ─────────────────────────────────────────────────────────────
fs.mkdirSync(BUILD_DIR, { recursive: true })

const common = { bundle: true, format: 'esm', platform: 'browser', target: ['chrome120'], minify: false, logLevel: 'silent' }

await build({
  ...common,
  entryPoints: [path.join(TOOLS_DIR, 'preview/sdk-shim.js')],
  outfile: path.join(BUILD_DIR, 'sdk-shim.js'),
  alias: { '@hermes/plugin-sdk': path.join(TOOLS_DIR, 'preview/sdk-shim.js') },
})

await build({
  ...common,
  entryPoints: [path.join(TOOLS_DIR, 'preview/preview-host.js')],
  outfile: path.join(BUILD_DIR, 'preview-host.js'),
})

// bare-specifier shims for the artifact's import whitelist (import map targets)
await build({
  ...common,
  stdin: { contents: `export * from 'react';`, resolveDir: TOOLS_DIR, sourcefile: 'react-entry.js' },
  outfile: path.join(BUILD_DIR, 'react.js'),
})
await build({
  ...common,
  stdin: { contents: `export { jsx, jsxs, Fragment } from 'react/jsx-runtime';`, resolveDir: TOOLS_DIR, sourcefile: 'jsx-runtime-entry.js' },
  outfile: path.join(BUILD_DIR, 'jsx-runtime.js'),
})

// ── mock backend (dashboard half is not running in preview) ─────────────────
const MOCK_HEALTH = {
  ok: true,
  plugin: 'whale-widget',
  version: '0.1.0',
  schema_version: 1,
  track3_state: 'not_implemented',
  contract_probe: null,
}

// M5/M8 wiring mocks: the pane polls these via ctx.rest (namespace-relative).
const MOCK_CONFIG = {
  balance_poll_seconds: 60,
  usage_summary_poll_seconds: 30,
  reminders: { balance_low_enabled: true, budget_enabled: true, turn_cost_enabled: true },
  thresholds: { balance_low: null, daily_budget: null },
  bubbles: { enabled: true, turn_cost_ttl_ms: 5000 },
}
const MOCK_BALANCE = {
  credential: { configured: true },
  state: 'ok',
  observed_balance_units: 1234500000,
  currency: 'CNY',
  fetched_at: null,
  error: null,
}
const MOCK_SUMMARY = {
  estimated_today_units: 456700000,
  turns_today: 12,
  unpriced_today: 0,
  estimated_today: [{ currency: 'CNY' }],
}
const MOCK_WAIT_STATE = { slots: [] }
// settled array exercises the WP-2 turn-cost contract in the preview
const MOCK_INGEST = {
  status: 'accepted',
  accepted: 1,
  duplicate: 0,
  settled: [{ dedup_key: 'preview-turn', estimated_cost_units: 42000000, currency: 'CNY', cost_basis: 'preview' }],
}

// ── preview page ─────────────────────────────────────────────────────────────
const PREVIEW_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>whale-widget dev preview</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; background: #14161a; color: #d7dae0; }
  #fake-app { padding: 12px 16px; }
  #statusbar { position: fixed; bottom: 0; left: 0; right: 0; height: 28px;
               background: #1d2025; display: flex; align-items: center;
               justify-content: flex-end; padding: 0 12px; font-size: 12px; }
  #pane-slot { margin: 48px auto; max-width: 560px; border: 1px dashed #3a3f4b;
               border-radius: 10px; padding: 18px; }
  .whale-toast { background: #2a2f39; border-radius: 8px; padding: 8px 12px;
                 margin-top: 8px; font-size: 12px; max-width: 380px; }
  .whale-toast-error { background: #4b2a2a; }
  #whale-toasts { position: fixed; top: 12px; right: 12px; }
  .unmounted-area { color: #8a919e; font-size: 12px; margin-top: 6px; }
  #errorbox { position: fixed; top: 0; left: 0; right: 0; background: #5b1d1d;
              color: #ffd7d7; padding: 6px 12px; font-size: 12px; display: none; }
</style>
<script type="importmap">
{
  "imports": {
    "@hermes/plugin-sdk": "/shims/sdk-shim.js",
    "react": "/shims/react.js",
    "react/jsx-runtime": "/shims/jsx-runtime.js"
  }
}
</script>
</head>
<body>
<div id="errorbox"></div>
<div id="fake-app">
  <h3>whale-widget dev preview</h3>
  <p>Simulated Hermes desktop: statusbar at the bottom, pane slot below. Backed by a mock /health endpoint.</p>
  <div id="pane-slot"><b>Whale widget placeholder</b><div id="other-areas"></div></div>
</div>
<div id="statusbar"><span id="statusbar-right"></span></div>
<div id="whale-toasts"></div>
<script type="module" src="/preview-host.js"></script>
</body>
</html>`

// ── static server ────────────────────────────────────────────────────────────
function send(res, code, body, type = 'text/html; charset=utf-8') {
  res.writeHead(code, { 'Content-Type': type, 'Cache-Control': 'no-store' })
  res.end(body)
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`)
  if (url.pathname === '/') return send(res, 200, PREVIEW_HTML)
  if (url.pathname === '/desktop/plugin.js') {
    if (!fs.existsSync(ARTIFACT)) return send(res, 500, 'artifact missing — run: node tools/build-desktop.mjs', 'text/plain')
    return send(res, 200, fs.readFileSync(ARTIFACT, 'utf8'), 'text/javascript')
  }
  if (url.pathname === '/preview-host.js') {
    return send(res, 200, fs.readFileSync(path.join(BUILD_DIR, 'preview-host.js'), 'utf8'), 'text/javascript')
  }
  if (url.pathname.startsWith('/shims/')) {
    const name = path.basename(url.pathname)
    return send(res, 200, fs.readFileSync(path.join(BUILD_DIR, name), 'utf8'), 'text/javascript')
  }
  if (url.pathname === '/api/plugins/whale-widget/health') {
    return send(res, 200, JSON.stringify(MOCK_HEALTH), 'application/json')
  }
  if (url.pathname === '/api/plugins/whale-widget/config') {
    return send(res, 200, JSON.stringify(MOCK_CONFIG), 'application/json')
  }
  if (url.pathname === '/api/plugins/whale-widget/balance') {
    return send(res, 200, JSON.stringify(MOCK_BALANCE), 'application/json')
  }
  if (url.pathname === '/api/plugins/whale-widget/usage/summary') {
    return send(res, 200, JSON.stringify(MOCK_SUMMARY), 'application/json')
  }
  if (url.pathname === '/api/plugins/whale-widget/wait-state') {
    return send(res, 200, JSON.stringify(MOCK_WAIT_STATE), 'application/json')
  }
  if (url.pathname === '/api/plugins/whale-widget/ingest/wait-event') {
    return send(res, 200, JSON.stringify({ ok: true }), 'application/json')
  }
  if (url.pathname === '/api/plugins/whale-widget/ingest/turn' && req.method === 'POST') {
    return send(res, 200, JSON.stringify(MOCK_INGEST), 'application/json')
  }
  send(res, 404, 'not found', 'text/plain')
})

server.listen(PORT, '127.0.0.1', () => {
  console.log(`dev-preview: http://127.0.0.1:${PORT}/`)
  console.log('acceptance: chip shows "● Whale widget · ok · v0.1.0 (schema 1)", the whale pane mounts in the pane slot (balance 12.35 CNY / today 4.56 CNY), window.__preview.errors empty')
})
