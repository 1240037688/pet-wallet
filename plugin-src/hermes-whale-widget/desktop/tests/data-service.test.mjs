/**
 * M5 data service (node:test via the loader shims — imports the SDK atom):
 * start/stop with config-driven intervals, immediate refresh on start,
 * idempotent start, pokeSummary coalescing under an injected clock,
 * unreachable backend → $dashboard 'unreachable' (never a fabricated balance).
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register('./loader.mjs', import.meta.url)

const { createDataService, $balance, $summary, $dashboard, BALANCE_FLOOR_MS, SUMMARY_FLOOR_MS } =
  await import('../src/core/data-service.js')

const drain = () => new Promise((resolve) => setImmediate(resolve))

const okRest = (calls) => async (path) => {
  calls.push(path)
  if (path === '/balance') return { state: 'ok', observed_balance_units: 11_000_000_000, currency: 'CNY', credential: { configured: true } }
  if (path === '/usage/summary') return { estimated_today_units: 456_700_000, turns_today: 12 }
  throw new Error(`unexpected path ${path}`)
}

function makeService({ rest, now } = {}) {
  const calls = []
  const service = createDataService({ rest: rest ?? okRest(calls), now: now ?? (() => Date.now()) })
  test.after(() => service.stop())
  return { service, calls }
}

test('start() immediately refreshes balance + summary and flips $dashboard to ok', async () => {
  $balance.set(null)
  $summary.set(null)
  const { service, calls } = makeService()
  service.start({ balance_poll_seconds: 60, usage_summary_poll_seconds: 30 })
  await drain()
  assert.deepEqual(calls, ['/balance', '/usage/summary'])
  assert.equal($balance.get().observed_balance_units, 11_000_000_000)
  assert.equal($summary.get().turns_today, 12)
  assert.equal($dashboard.get().state, 'ok')
})

test('start() is idempotent (no duplicate timers/refreshes)', async () => {
  const { service, calls } = makeService()
  service.start({})
  service.start({})
  await drain()
  assert.equal(calls.filter((p) => p === '/balance').length, 1)
  assert.equal(calls.filter((p) => p === '/usage/summary').length, 1)
})

test('pokeSummary coalesces: no refresh inside 2s of the last one, one after', async () => {
  let t = 0
  const calls = []
  const service = createDataService({ rest: okRest(calls), now: () => t })
  test.after(() => service.stop())
  service.start({})
  await drain()
  const before = calls.filter((p) => p === '/usage/summary').length
  assert.equal(before, 1) // the start() refresh itself

  t = 1_999
  service.pokeSummary()
  await drain()
  assert.equal(calls.filter((p) => p === '/usage/summary').length, before, 'throttled inside the window')

  t = 2_000
  service.pokeSummary()
  await drain()
  assert.equal(calls.filter((p) => p === '/usage/summary').length, before + 1, 'refreshed past the window')
})

test('pokeSummary before start / after stop is a safe no-op', async () => {
  const { service, calls } = makeService()
  service.pokeSummary() // no timers yet
  await drain()
  service.start({})
  await drain()
  service.stop()
  service.pokeSummary() // stopped
  await drain()
  assert.equal(calls.filter((p) => p === '/usage/summary').length, 1)
})

test('unreachable backend → $dashboard unreachable with detail; atoms stay null', async () => {
  $balance.set(null)
  $summary.set(null)
  const { service } = makeService({
    rest: async () => {
      throw new Error('ECONNREFUSED')
    },
  })
  service.start({})
  await drain()
  const dash = $dashboard.get()
  assert.equal(dash.state, 'unreachable')
  assert.match(dash.detail, /ECONNREFUSED/)
  assert.equal($balance.get(), null)
  assert.equal($summary.get(), null)
})

test('stop() disposes: no further refreshes even when poked', async () => {
  const { service, calls } = makeService()
  service.start({})
  await drain()
  service.stop()
  const snapshot = [...calls]
  service.pokeSummary()
  await drain()
  assert.deepEqual(calls, snapshot)
})

test('interval floors exist (AGENTS §8: no tight polling loops)', () => {
  assert.equal(BALANCE_FLOOR_MS, 15_000)
  assert.equal(SUMMARY_FLOOR_MS, 10_000)
})
