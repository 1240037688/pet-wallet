/**
 * Runtime smoke: import the BUILT artifact through the loader hook (bare
 * specifiers → shims, mimicking Hermes' runtime-loader rewriting), call
 * register() with a mock ctx, and assert:
 *   - the chip contribution + health probe + self-check toast (M0 surface);
 *   - the M1 subscription set and the full pipeline: gateway events →
 *     normalize → turn bucketing → POST /ingest/turn via ctx.rest;
 *   - reconnect tagging (after_reconnect on the first post-reconnect settle);
 *   - the ingest-unavailable surfacing when the dashboard half is down.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { register } from 'node:module'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ARTIFACT = path.join(HERE, '..', 'plugin.js')

function makeCtx({ restImpl } = {}) {
  const registered = []
  const handlers = {}
  const disposed = []
  const restCalls = []
  const ctx = {
    rest: async (p, opts) => {
      restCalls.push({ path: p, opts })
      if (restImpl) return restImpl(p, opts)
      if (p === '/health') {
        return { ok: true, plugin: 'whale-widget', version: '0.1.0', schema_version: 1 }
      }
      if (p === '/ingest/turn') return { status: 'accepted', accepted: 1, duplicate: 0 }
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

async function settled() {
  await new Promise((resolve) => setImmediate(resolve))
}

test('built artifact registers under the shimmed runtime', async (t) => {
  assert.ok(fs.existsSync(ARTIFACT), 'run node tools/build-desktop.mjs first')
  register('./loader.mjs', import.meta.url)

  const mod = await import('../plugin.js')
  assert.equal(mod.default.id, 'whale-widget')
  assert.equal(typeof mod.default.register, 'function')
  assert.ok(mod.$health, 'artifact exports $health atom')
  assert.ok(mod.$ingest, 'artifact exports $ingest atom')

  const { ctx, registered, handlers, disposed, restCalls } = makeCtx()
  mod.default.register(ctx)
  // lifecycle red line (AGENTS §9): the poll timer must always be cleared,
  // even on assertion failure, or the node process hangs until the 60s tick
  t.after(() => {
    for (const fn of disposed) fn()
  })

  // chip contribution in the verified statusbar area
  const chip = registered.find((c) => c.id === 'chip')
  assert.ok(chip, 'chip contribution registered')
  assert.equal(chip.area, 'statusBar.right')

  // M1 event surface subscribed at register time
  assert.deepEqual(Object.keys(handlers).sort(), [...mod.SUBSCRIBED_EVENTS].sort())

  // self-check toast fired
  const { notifications } = await import('./shims/sdk-shim.mjs')
  assert.ok(notifications.length >= 1, 'host.notify self-check toast fired')

  // health probe: ctx.rest is namespace-relative → '/health'
  await settled()
  assert.deepEqual(restCalls.map((c) => c.path), ['/health'])
  assert.equal(mod.$health.get().state, 'ok')
  assert.equal(mod.$health.get().version, '0.1.0')

  // chip renders the widget + connectivity text (function component → span)
  const vnode = chip.render()
  assert.equal(typeof vnode.type, 'function') // SDK renders the component
  const rendered = vnode.type(vnode.props) // shim useValue = store.get()
  assert.equal(rendered.type, 'span')
  assert.match(String(rendered.props.children), /Whale widget/)
  assert.match(String(rendered.props.children), /ok · v0\.1\.0 \(schema 1\)/)
})

test('M1 pipeline: gateway events → settled turn → POST /ingest/turn', async (t) => {
  const mod = await import('../plugin.js')
  const postBodies = []
  const { ctx, handlers, disposed, restCalls } = makeCtx({
    restImpl: (p, opts) => {
      if (p === '/ingest/turn') {
        postBodies.push(JSON.parse(opts.body))
        return { status: 'accepted', accepted: 1, duplicate: 0 }
      }
      if (p === '/health') return { ok: true, plugin: 'whale-widget', version: '0.1.0', schema_version: 1 }
      throw new Error(`unexpected rest path: ${p}`)
    },
  })
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })

  // a full turn: start → heartbeat → complete (heartbeat must NOT be forwarded)
  handlers['message.start']({ type: 'message.start', session_id: 's1' })
  handlers['session.usage']({ type: 'session.usage', session_id: 's1', payload: { usage: { input_tokens: 9 } } })
  handlers['message.complete'](completeEvent())
  await settled()

  assert.equal(restCalls.filter((c) => c.path === '/ingest/turn').length, 1, 'exactly one ingest POST per settled turn')
  assert.equal(postBodies[0].turns.length, 1)
  const turn = postBodies[0].turns[0]
  assert.equal(turn.session_id, 's1')
  assert.equal(turn.profile, 'default')
  assert.equal(turn.model, null) // shim host exposes no state.model
  assert.equal(turn.status, 'complete')
  assert.equal(turn.after_reconnect, false)
  assert.equal(turn.replayed, false)
  assert.equal(turn.usage_source, 'complete')
  assert.equal(typeof turn.received_at, 'number')
  assert.equal(turn.usage.input, 100)
  assert.equal(turn.usage.output, 50)
  assert.deepEqual(Object.keys(turn).sort(), [
    'after_reconnect', 'model', 'profile', 'received_at', 'replayed', 'session_id', 'status', 'usage', 'usage_source',
  ])
  assert.equal(mod.$ingest.get().queued, 0)
})

test('M1 reconnect handling: after_reconnect tag on the first post-reconnect settle only', async (t) => {
  const mod = await import('../plugin.js')
  const postBodies = []
  const { ctx, handlers, disposed } = makeCtx({
    restImpl: (p, opts) => {
      if (p === '/ingest/turn') {
        postBodies.push(JSON.parse(opts.body))
        return { status: 'accepted', accepted: 1, duplicate: 0 }
      }
      if (p === '/health') return { ok: true, plugin: 'whale-widget', version: '0.1.0', schema_version: 1 }
      throw new Error(`unexpected rest path: ${p}`)
    },
  })
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })

  handlers['message.complete'](completeEvent({ session_id: 'pre' })) // normal turn
  await settled()
  handlers['gateway.reconnecting']({ type: 'gateway.reconnecting', payload: { attempt: 1 } })
  handlers['message.complete'](completeEvent({ session_id: 'post' })) // first after reconnect
  handlers['gateway.ready']({ type: 'gateway.ready', payload: { replayEpoch: 2 } }) // resume forwarding
  await settled()
  handlers['message.complete'](completeEvent({ session_id: 'post2' }))
  await settled()

  const flags = postBodies.map((b) => b.turns.map((turn) => turn.after_reconnect))
  assert.deepEqual(flags, [[false], [true], [false]])
})

test('M1 degraded surface: dashboard down → dead letter + 记账暂不可用 on the chip', async (t) => {
  const mod = await import('../plugin.js')
  const { ctx, registered, handlers, disposed } = makeCtx({
    restImpl: (p) => {
      if (p === '/health') return { ok: true, plugin: 'whale-widget', version: '0.1.0', schema_version: 1 }
      throw new Error('ECONNREFUSED')
    },
  })
  mod.default.register(ctx)
  t.after(() => {
    for (const fn of disposed) fn()
  })

  handlers['message.complete'](completeEvent())
  // bounded retry (250/500/1000ms backoff) → dead letter; poll until flagged
  const deadline = Date.now() + 6000
  while (!mod.$ingest.get().unavailable && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  const ingest = mod.$ingest.get()
  assert.equal(ingest.unavailable, true, 'ingest flagged unavailable')
  assert.ok(ingest.deadLetters >= 1, 'dead letter recorded')

  // chip surfaces the degraded ledger state
  const chip = registered.find((c) => c.id === 'chip')
  const vnode = chip.render()
  const rendered = vnode.type(vnode.props)
  assert.match(String(rendered.props.children), /记账暂不可用/)
})
