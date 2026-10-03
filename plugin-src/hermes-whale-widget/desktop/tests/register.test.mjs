/**
 * Runtime smoke: import the BUILT artifact through the loader hook (bare
 * specifiers → shims, mimicking Hermes' runtime-loader rewriting), call
 * register() with a mock ctx, and assert the chip contribution, the health
 * probe against the mock REST door, and the self-check toast.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { register } from 'node:module'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ARTIFACT = path.join(HERE, '..', 'plugin.js')

test('built artifact registers under the shimmed runtime', async (t) => {
  assert.ok(fs.existsSync(ARTIFACT), 'run node tools/build-desktop.mjs first')
  register('./loader.mjs', import.meta.url)

  const mod = await import('../plugin.js')
  assert.equal(mod.default.id, 'whale-widget')
  assert.equal(typeof mod.default.register, 'function')
  assert.ok(mod.$health, 'artifact exports $health atom')

  const registered = []
  const events = []
  const disposed = []
  const restCalls = []
  const ctx = {
    rest: async (p) => {
      restCalls.push(p)
      if (p === '/health') {
        return { ok: true, plugin: 'whale-widget', version: '0.1.0', schema_version: 1 }
      }
      throw new Error(`unexpected rest path: ${p}`)
    },
    onEvent: (type, fn) => {
      events.push(type)
      return () => {}
    },
    onDispose: (fn) => disposed.push(fn),
    storage: { get: () => null, set: () => {} },
    register: (contrib) => registered.push(contrib),
  }

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

  // event subscription made at register time
  assert.deepEqual(events, ['*'])

  // self-check toast fired
  const { notifications } = await import('./shims/sdk-shim.mjs')
  assert.ok(notifications.length >= 1, 'host.notify self-check toast fired')

  // health probe: ctx.rest is namespace-relative → '/health'
  await new Promise((resolve) => setImmediate(resolve))
  assert.deepEqual(restCalls, ['/health'])
  assert.equal(mod.$health.get().state, 'ok')
  assert.equal(mod.$health.get().version, '0.1.0')

  // chip renders the placeholder + connectivity text (function component → span)
  const vnode = chip.render()
  assert.equal(typeof vnode.type, 'function') // SDK renders the component
  const rendered = vnode.type(vnode.props) // shim useValue = store.get()
  assert.equal(rendered.type, 'span')
  assert.match(String(rendered.props.children), /Whale widget placeholder/)
  assert.match(String(rendered.props.children), /ok · v0\.1\.0 \(schema 1\)/)
})
