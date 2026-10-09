/**
 * WP-1 main.js integration smoke over the BUILT artifact (loader shims, mock
 * ctx): floating pane registration, clarify wait-bridge forwarding, settled
 * turn-cost consumption (WP-2 contract), wait-state poll semantics, config →
 * data-service start, and lifecycle disposal of every timer.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { register } from 'node:module'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ARTIFACT = path.join(HERE, '..', 'plugin.js')

const PANE_DATA = { placement: 'floating', anchor: 'bottom-right', width: '280px' }
const SETTLED = [{ dedup_key: 'k1', estimated_cost_units: 42_000_000, currency: 'CNY', cost_basis: 'whale_pricing' }]

function makeCtx({ restImpl } = {}) {
  const registered = []
  const handlers = {}
  const disposed = []
  const restCalls = []
  const ctx = {
    rest: async (p, opts = {}) => {
      restCalls.push({ path: p, method: opts.method ?? 'GET', body: opts.body ?? null })
      // a partial restImpl may return undefined to fall through to the defaults
      const custom = restImpl ? restImpl(p, opts) : undefined
      if (custom !== undefined) return custom
      if (p === '/health') return { ok: true, plugin: 'pet-wallet', version: '0.1.0', schema_version: 1 }
      if (p === '/config') return { balance_poll_seconds: 60, usage_summary_poll_seconds: 30 }
      if (p === '/balance') return { state: 'ok', observed_balance_units: 11_000_000_000, currency: 'CNY', credential: { configured: true } }
      if (p === '/balance/all') {
        return {
          providers: [
            {
              provider_id: 'deepseek',
              known: true,
              configured: true,
              source: 'hermes_secret',
              credential_id: 'deepseek:abcd1234',
              fingerprint: 'fp0000000000000000000001',
              state: 'ok',
              observed_balance_units: 110_000_000,
              currency: 'CNY',
            },
          ],
        }
      }
      if (p === '/usage/summary') return { estimated_today_units: 456_700_000, turns_today: 12, estimated_today: [{ currency: 'CNY' }] }
      if (p === '/usage/turns') return { turns: [], count: 0, limit: 20 }
      if (p === '/providers/status') return { providers: [] }
      if (p === '/pricing') return { builtin: [], custom: [], notes: [] }
      if (p === '/wait-state') return { question_slots: [], approval_slots: [], fired_dedup_keys: [] }
      if (p === '/ingest/turn') return { status: 'accepted', accepted: 1, duplicate: 0, settled: SETTLED }
      if (p === '/ingest/wait-event') return { ok: true }
      throw new Error(`unexpected rest path: ${p}`)
    },
    onEvent: (type, fn) => {
      handlers[type] = fn
      return () => {}
    },
    onDispose: (fn) => disposed.push(fn),
    storage: { get: () => null, set: () => {} },
    register: (contrib) => registered.push(contrib),
  }
  return { ctx, registered, handlers, disposed, restCalls }
}

function completeEvent(overrides = {}) {
  return {
    type: 'message.complete',
    session_id: 's1',
    profile: 'default',
    payload: { status: 'complete', usage: { input_tokens: 100, output_tokens: 50 } },
    ...overrides,
  }
}

const settledNow = () => new Promise((resolve) => setImmediate(resolve))
// async polls (wait-state/notifications) cross several promise hops; a single
// setImmediate is not deterministic under load — flush a few macrotasks instead
const flushAsync = async () => {
  for (let i = 0; i < 8; i++) await new Promise((resolve) => setTimeout(resolve, 0))
}

test('built artifact exists for the wiring smoke', () => {
  assert.ok(fs.existsSync(ARTIFACT), 'run node tools/build-desktop.mjs first')
})

test('floating pane contribution: area panes + native floating data + WhalePane render', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  // DR-16: the butler pane is OPT-IN via config.pane.enabled — registration is
  // config-gated and therefore asynchronous (after the /config load lands).
  const { ctx, registered, disposed } = makeCtx({
    restImpl: (p) => {
      if (p === '/config') return { balance_poll_seconds: 60, usage_summary_poll_seconds: 30, pane: { enabled: true } }
      return undefined
    },
  })
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })
  await settledNow()

  const pane = registered.find((c) => c.id === 'whale-widget-pane')
  assert.ok(pane, 'pane contribution registered (chip stays separate)')
  assert.equal(pane.area, 'panes')
  assert.deepEqual(pane.data, PANE_DATA)
  assert.equal(pane.title, 'Pet Wallet 管家') // de-roled ledger panel title (DR-15)
  assert.ok(registered.some((c) => c.id === 'chip' && c.area === 'statusBar.right'), 'statusbar chip kept')

  // render() yields a WhalePane component element; invoking it with the shim
  // useValue (store.get) produces the pane body div
  const vnode = pane.render()
  assert.equal(typeof vnode.type, 'function')
  const rendered = vnode.type(vnode.props)
  assert.equal(rendered.type, 'div')
  assert.equal(rendered.props.className, 'whale-widget-pane')
})

test('config → data service start: /config fetched then /balance + /usage/summary polled', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  const { ctx, restCalls, disposed } = makeCtx()
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })
  await settledNow()

  const paths = restCalls.map((c) => c.path)
  assert.ok(paths.includes('/config'), 'config fetched from the dashboard half')
  assert.ok(paths.indexOf('/balance') > paths.indexOf('/config'), 'balance poll starts after config')
  assert.ok(paths.includes('/usage/summary'), 'summary poll started')
  assert.ok(paths.includes('/balance/all'), 'bubble balance source (/balance/all) pulled')
  assert.equal(mod.$balance.get()?.observed_balance_units, 11_000_000_000)
  assert.equal(mod.$summary.get()?.turns_today, 12)
  assert.equal(mod.$dashboard.get().state, 'ok')
})

test('WP-dashboard: routes page + sidebar.nav row registered for /pet-wallet', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  const { ctx, registered, disposed } = makeCtx()
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })

  const page = registered.find((c) => c.id === 'dashboard')
  assert.ok(page, 'routes page contribution registered')
  assert.equal(page.area, 'routes')
  assert.equal(page.title, 'Pet Wallet')
  assert.deepEqual(page.data, { path: '/pet-wallet' })
  assert.equal(typeof page.render, 'function')

  const nav = registered.find((c) => c.id === 'nav')
  assert.ok(nav, 'sidebar nav contribution registered')
  assert.equal(nav.area, 'sidebar.nav')
  assert.equal(nav.data.path, '/pet-wallet')
  assert.equal(nav.data.label, 'Pet Wallet')
  assert.equal(typeof nav.data.codicon, 'string')
})

test('WP-dashboard: chip click navigates to /pet-wallet (host.navigate feature-detected)', async (t) => {
  register('./loader.mjs', import.meta.url)
  const { navigations } = await import('./shims/sdk-shim.mjs')
  const mod = await import('../plugin.js')
  const { ctx, registered, disposed } = makeCtx()
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })

  const chip = registered.find((c) => c.id === 'chip')
  const vnode = chip.render()
  assert.equal(typeof vnode.type, 'function', 'chip wrapped by the dashboard navigation layer')
  const rendered = vnode.type(vnode.props)
  assert.equal(rendered.type, 'span')
  assert.equal(typeof rendered.props.onClick, 'function')
  rendered.props.onClick({ preventDefault: () => {} })
  assert.ok(navigations.includes('/pet-wallet'), 'chip click → host.navigate("/pet-wallet")')
})

test('WP-dashboard bubble: /balance/all rows → joined balance text (deepseek ¥1.10)', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  const { ctx, disposed } = makeCtx()
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })
  await flushAsync()

  assert.equal(mod.$bubbleBalanceText.get(), 'deepseek ¥1.10')
})

test('WP-dashboard bubble: show-list filters /balance/all rows (config.bubble.balance_providers)', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  const { ctx, disposed } = makeCtx({
    restImpl: (p) => {
      if (p === '/balance/all') {
        return {
          providers: [
            { provider_id: 'deepseek', configured: true, state: 'ok', observed_balance_units: 110_000_000, currency: 'CNY' },
            { provider_id: 'openai', configured: true, state: 'ok', observed_balance_units: 42_000_000, currency: 'USD' },
          ],
        }
      }
      if (p === '/config') return { bubble: { balance_providers: ['openai'] } }
      if (p === '/health') return { ok: true, version: '0.1.0', schema_version: 1 }
      if (p === '/balance') return { state: 'ok', observed_balance_units: 1, credential: {} }
      if (p === '/usage/summary') return { estimated_today_units: null, turns_today: 0 }
      if (p === '/wait-state') return { question_slots: [], approval_slots: [], fired_dedup_keys: [] }
      throw new Error(`unexpected rest path: ${p}`)
    },
  })
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })
  await flushAsync()

  // the config-seeded show-list selects ONLY openai; deepseek's balance is hidden
  assert.equal(mod.$bubbleBalanceText.get(), 'openai $0.42')
})

test('WP-dashboard bubble: /balance/all absent (older half) → single /balance fallback, no crash', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  const { ctx, restCalls, handlers, disposed } = makeCtx({
    restImpl: (p) => {
      if (p === '/balance/all') throw new Error('404 not found')
      if (p === '/health') return { ok: true, version: '0.1.0', schema_version: 1 }
      if (p === '/config') return { balance_poll_seconds: 60, usage_summary_poll_seconds: 30 }
      if (p === '/balance') return { state: 'ok', observed_balance_units: 22_000_000, currency: 'CNY', credential: { configured: true } }
      if (p === '/usage/summary') return { estimated_today_units: null, turns_today: 0 }
      if (p === '/wait-state') return { question_slots: [], approval_slots: [], fired_dedup_keys: [] }
      if (p === '/ingest/turn') return { status: 'accepted', accepted: 1, duplicate: 0 }
      throw new Error(`unexpected rest path: ${p}`)
    },
  })
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })
  await flushAsync()

  assert.equal(mod.$bubbleBalanceText.get(), null, 'no provider text on the fallback path')
  const attempts = restCalls.filter((c) => c.path === '/balance/all').length
  assert.ok(attempts >= 1, 'fallback attempted at least once')

  // the fallback is sticky: a settled turn re-triggers the display sync but no re-poll
  handlers['message.complete'](completeEvent())
  await flushAsync()
  assert.equal(restCalls.filter((c) => c.path === '/balance/all').length, attempts, 'no further /balance/all attempts')
})

test('settled turn cost (WP-2 contract) → controller turn_cost bubble + money mood', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  const { ctx, handlers, disposed } = makeCtx()
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })

  handlers['message.complete'](completeEvent())
  await settledNow()

  const bubble = mod.$bubble.get()
  assert.ok(bubble, 'turn cost bubble visible')
  assert.equal(bubble.key, 'turn:k1')
  assert.equal(bubble.kind, 'turn_cost')
  assert.equal(bubble.data.turn_cost_text, '0.42 CNY') // 42_000_000 / 1e8 fixed-point
  assert.equal(bubble.data.session_name, 's1') // single-turn batch → session from the payload
  // TASK_COMPLETED→happy then final USAGE_UPDATED→money (last transient wins)
  assert.equal(mod.$whale.get().mood, 'money')
})

test('ingest response without settled → no bubble, behaviour unchanged', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  const { ctx, handlers, disposed } = makeCtx({
    restImpl: (p) => {
      if (p === '/ingest/turn') return { status: 'accepted', accepted: 1, duplicate: 0 }
      if (p === '/health') return { ok: true, version: '0.1.0', schema_version: 1 }
      if (p === '/config') return { balance_poll_seconds: 60, usage_summary_poll_seconds: 30 }
      if (p === '/balance') return { state: 'ok', observed_balance_units: 1, credential: {} }
      if (p === '/usage/summary') return { estimated_today_units: null, turns_today: 0 }
      if (p === '/wait-state') return { question_slots: [], approval_slots: [], fired_dedup_keys: [] }
      throw new Error(`unexpected rest path: ${p}`)
    },
  })
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })

  handlers['message.complete'](completeEvent())
  await settledNow()
  // mood events flow regardless (TASK_COMPLETED → task-done bubble), but with
  // no settled array there is NO turn:... cost bubble
  assert.equal(mod.$bubble.get()?.key, 'task-done')
  assert.equal(mod.$ingest.get().queued, 0)
})

test('clarify tool.start/complete → POST /ingest/wait-event open/close; other tools silent', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  const { ctx, handlers, restCalls, disposed } = makeCtx()
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })

  handlers['tool.start']({ type: 'tool.start', session_id: 's9', payload: { name: 'clarify', tool_id: 't1' } })
  handlers['tool.complete']({ type: 'tool.complete', session_id: 's9', payload: { name: 'clarify', tool_id: 't1' } })
  handlers['tool.start']({ type: 'tool.start', session_id: 's9', payload: { name: 'bash', tool_id: 't2' } })
  await settledNow()

  const waitCalls = restCalls.filter((c) => c.path === '/ingest/wait-event')
  assert.deepEqual(
    waitCalls.map((c) => (typeof c.body === 'string' ? JSON.parse(c.body) : c.body)),
    [
      { kind: 'question', phase: 'open', tool_id: 't1', session_id: 's9' },
      { kind: 'question', phase: 'close', tool_id: 't1', session_id: 's9' },
    ],
  )
})

test('failing /ingest/wait-event is silent (wait bridge never breaks accounting)', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  const { ctx, handlers, restCalls, disposed } = makeCtx({
    restImpl: (p) => {
      if (p === '/ingest/wait-event') throw new Error('wait bridge not deployed')
      if (p === '/ingest/turn') return { status: 'accepted', accepted: 1, duplicate: 0 }
      if (p === '/health') return { ok: true, version: '0.1.0', schema_version: 1 }
      if (p === '/config') return { balance_poll_seconds: 60, usage_summary_poll_seconds: 30 }
      if (p === '/balance') return { state: 'ok', observed_balance_units: 1, credential: {} }
      if (p === '/usage/summary') return { estimated_today_units: null, turns_today: 0 }
      if (p === '/wait-state') return { question_slots: [], approval_slots: [], fired_dedup_keys: [] }
      throw new Error(`unexpected rest path: ${p}`)
    },
  })
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })

  handlers['tool.start']({ type: 'tool.start', session_id: 's9', payload: { name: 'clarify', tool_id: 't1' } })
  await settledNow() // would reject unhandled if not caught
  assert.ok(restCalls.some((c) => c.path === '/ingest/wait-event'), 'attempted despite previous failure')

  // accounting continues unaffected
  handlers['message.complete'](completeEvent())
  await settledNow()
  assert.equal(mod.$ingest.get().queued, 0)
  assert.equal(mod.$ingest.get().unavailable, false)
})

test('wait-state poll: slots → sticky waiting + waiting mood', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  const { ctx, disposed } = makeCtx({
    restImpl: (p) => {
      if (p === '/wait-state') return { question_slots: [{ tool_id: 't1', session_id: 's9', since: 0 }], approval_slots: [], fired_dedup_keys: [] }
      if (p === '/health') return { ok: true, version: '0.1.0', schema_version: 1 }
      if (p === '/config') return { balance_poll_seconds: 60, usage_summary_poll_seconds: 30 }
      if (p === '/balance') return { state: 'ok', observed_balance_units: 1, credential: {} }
      if (p === '/usage/summary') return { estimated_today_units: null, turns_today: 0 }
      throw new Error(`unexpected rest path: ${p}`)
    },
  })
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })
  await flushAsync()

  const whale = mod.$whale.get()
  assert.equal(whale.mood, 'waiting')
  assert.equal(whale.waiting, 'question') // only a question slot is present (real contract shape)
  const bubble = mod.$bubble.get()
  assert.equal(bubble?.key, 'wait:question')
})

test('wait-state failure (WP-2 not deployed) → treated as no waiting, no crash', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  const { ctx, disposed } = makeCtx({
    restImpl: (p) => {
      if (p === '/wait-state') throw new Error('404 not found')
      if (p === '/health') return { ok: true, version: '0.1.0', schema_version: 1 }
      if (p === '/config') return { balance_poll_seconds: 60, usage_summary_poll_seconds: 30 }
      if (p === '/balance') return { state: 'ok', observed_balance_units: 1, credential: {} }
      if (p === '/usage/summary') return { estimated_today_units: null, turns_today: 0 }
      throw new Error(`unexpected rest path: ${p}`)
    },
  })
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })
  await flushAsync()

  const whale = mod.$whale.get()
  assert.equal(whale.mood, 'idle')
  assert.equal(whale.waiting, null)
  assert.equal(mod.$bubble.get(), null)
})

test('lifecycle: dispose stops health poll, UI poll and the data service', async (t) => {
  register('./loader.mjs', import.meta.url)
  const mod = await import('../plugin.js')
  const { ctx, restCalls, disposed } = makeCtx()
  mod.default.register(ctx)
  await settledNow()
  assert.equal(disposed.length, 1, 'one onDispose hook owns every timer')
  for (const fn of disposed) fn()
  const snapshot = restCalls.length
  await new Promise((resolve) => setTimeout(resolve, 30))
  assert.equal(restCalls.length, snapshot, 'no further REST traffic after dispose')
})
