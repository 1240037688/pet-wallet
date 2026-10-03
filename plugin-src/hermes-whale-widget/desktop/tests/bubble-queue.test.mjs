/**
 * M7 bubble queue (node:test, injected clock): rank priority (budget <
 * balance_low < turn_cost < waiting < info), dedup by key (re-show replaces,
 * ttl NOT re-armed), ttl expiry, sticky waiting preemption, advance on
 * tapAdvance definitions (wraps + re-arms ttl), dismiss by key / visible,
 * pending()/clear() surfaces.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { createBubbleQueue, RANKS } from '../src/ui/bubble/queue.js'

const tapDef = { v: 1, tapAdvance: true, items: [{ kind: 'custom', modules: [{ type: 'text', text: 'a' }] }, { kind: 'custom', modules: [{ type: 'text', text: 'b' }] }] }
const fixedDef = { v: 1, tapAdvance: false, items: [{ kind: 'custom', modules: [{ type: 'text', text: 'x' }] }] }

function makeQueue() {
  let t = 1_000
  const queue = createBubbleQueue({ now: () => t })
  return { queue, advance: (ms) => { t += ms }, now: () => t }
}

test('ranks: lower number = more urgent', () => {
  assert.deepEqual(RANKS, { budget: 1, balance_low: 2, turn_cost: 3, waiting: 4, info: 5 })
})

test('show + view expose the top item; higher urgency preempts the visible bubble', () => {
  const { queue } = makeQueue()
  queue.show({ key: 'info', kind: 'info', def: tapDef, ttlMs: 5_000 })
  assert.equal(queue.view().key, 'info')

  queue.show({ key: 'wait', kind: 'waiting', def: fixedDef, data: {}, ttlMs: 0 })
  assert.equal(queue.view().key, 'wait') // waiting (4) preempts info (5)

  queue.show({ key: 'cost', kind: 'turn_cost', def: fixedDef, ttlMs: 5_000 })
  assert.equal(queue.view().key, 'cost') // turn_cost (3) preempts waiting (4)

  queue.show({ key: 'budget', kind: 'budget', def: fixedDef, ttlMs: 5_000 })
  assert.equal(queue.view().key, 'budget') // budget (1) tops everything
})

test('same-rank items keep the earlier insertion visible (first wins)', () => {
  const { queue } = makeQueue()
  queue.show({ key: 'cost-1', kind: 'turn_cost', def: fixedDef, ttlMs: 60_000 })
  queue.show({ key: 'cost-2', kind: 'turn_cost', def: fixedDef, ttlMs: 60_000 })
  assert.equal(queue.view().key, 'cost-1')
  assert.deepEqual(queue.pending().map((p) => p.key), ['cost-1', 'cost-2'])
})

test('dedup: re-showing a key replaces instead of duplicating and does NOT re-arm ttl', () => {
  const { queue, advance } = makeQueue()
  queue.show({ key: 'k', kind: 'info', def: fixedDef, ttlMs: 1_000 })
  advance(900)
  queue.show({ key: 'k', kind: 'info', def: fixedDef, ttlMs: 1_000 }) // refresh
  assert.deepEqual(queue.pending().map((p) => p.key), ['k'])
  advance(101) // shown_at was kept from the FIRST show → 900+101 > 1000
  assert.equal(queue.view(), null)
  assert.deepEqual(queue.pending(), [])
})

test('ttl expiry via the injected clock (swept on the next observation)', () => {
  const { queue, advance } = makeQueue()
  queue.show({ key: 'k', kind: 'info', def: fixedDef, ttlMs: 1_000 })
  advance(999)
  assert.equal(queue.view().key, 'k')
  advance(1) // ts == shown_at + ttl → expired
  assert.equal(queue.view(), null)
})

test('sticky bubbles ignore ttl and persist until dismissed', () => {
  const { queue, advance } = makeQueue()
  queue.show({ key: 'sticky', kind: 'waiting', def: fixedDef, sticky: true, ttlMs: 1 })
  advance(60_000)
  assert.equal(queue.view().key, 'sticky')
  queue.dismiss('sticky')
  assert.equal(queue.view(), null)
})

test('advance() only walks tapAdvance definitions and wraps modulo items', () => {
  const { queue } = makeQueue()
  queue.show({ key: 'seq', kind: 'info', def: tapDef, ttlMs: 60_000 })
  assert.equal(queue.view().stepIndex, 0)
  assert.equal(queue.advance().stepIndex, 1)
  assert.equal(queue.advance().stepIndex, 0) // wraps
  queue.show({ key: 'fixed', kind: 'turn_cost', def: fixedDef, ttlMs: 60_000 })
  assert.equal(queue.advance(), null) // tapAdvance=false → advance is a no-op
})

test('advance() re-arms the ttl from the new shown_at', () => {
  const { queue, advance } = makeQueue()
  queue.show({ key: 'seq', kind: 'info', def: tapDef, ttlMs: 1_000 })
  advance(800)
  queue.advance() // shown_at → t=1800, ttl re-armed → expires 2800
  advance(900) // t=2700 < 2800 → still alive on the re-armed clock
  assert.equal(queue.view().key, 'seq')
  advance(200) // t=2900 → past the re-armed ttl
  assert.equal(queue.view(), null)
})

test('dismiss(key) removes that key; dismiss() removes the visible top', () => {
  const { queue } = makeQueue()
  queue.show({ key: 'info', kind: 'info', def: fixedDef, ttlMs: 60_000 })
  queue.show({ key: 'cost', kind: 'turn_cost', def: fixedDef, ttlMs: 60_000 })
  queue.dismiss('cost')
  assert.equal(queue.view().key, 'info')
  queue.dismiss() // no key → visible one
  assert.equal(queue.view(), null)
})

test('waiting preemption is reversible: dismissing the wait restores the info bubble', () => {
  const { queue } = makeQueue()
  queue.show({ key: 'greeting', kind: 'info', def: tapDef, ttlMs: 60_000 })
  queue.show({ key: 'wait:question', kind: 'waiting', def: fixedDef, ttlMs: 0 })
  assert.equal(queue.view().key, 'wait:question')
  queue.dismiss('wait:question')
  assert.equal(queue.view().key, 'greeting')
})

test('ttl=0 (non-sticky) never expires — used for sticky waits', () => {
  const { queue, advance } = makeQueue()
  queue.show({ key: 'wait:approval', kind: 'waiting', def: fixedDef, ttlMs: 0 })
  advance(3_600_000)
  assert.equal(queue.view().key, 'wait:approval')
})

test('clear() empties everything', () => {
  const { queue } = makeQueue()
  queue.show({ key: 'a', kind: 'info', def: fixedDef, ttlMs: 60_000 })
  queue.show({ key: 'b', kind: 'budget', def: fixedDef, ttlMs: 60_000 })
  queue.clear()
  assert.equal(queue.view(), null)
  assert.deepEqual(queue.pending(), [])
})

test('view carries the resolver inputs (def + data) for the visible item only', () => {
  const { queue } = makeQueue()
  const data = { turn_cost_text: '0.42' }
  queue.show({ key: 'cost', kind: 'turn_cost', def: fixedDef, data, ttlMs: 60_000 })
  const view = queue.view()
  assert.equal(view.data, data)
  assert.equal(view.def, fixedDef)
  assert.equal(view.kind, 'turn_cost')
  assert.equal(view.rank, RANKS.turn_cost)
})
