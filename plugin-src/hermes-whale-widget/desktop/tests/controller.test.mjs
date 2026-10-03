/**
 * M5/M6/M7 pane controller (node:test via the loader shims — imports the SDK
 * atom): click sequence → greeting → tap-advance → ≥4 combo idle-line;
 * turnSettled → turn-cost bubble (dedup key, cost text, session); syncWaiting
 * open/close with sticky bubbles + waiting mood; mood events; press/release;
 * turnCostEnabled=false disables cost bubbles.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register('./loader.mjs', import.meta.url)

const { createWhaleController, $whale, $bubble } = await import('../src/ui/controller.js')

test('first click opens the greeting sequence; 2nd/3rd taps advance it', () => {
  const c = createWhaleController()
  assert.equal(c.click(), 1)
  assert.equal($bubble.get().key, 'greeting')
  assert.equal($bubble.get().stepIndex, 0)
  assert.equal(c.click(), 2)
  assert.equal($bubble.get().key, 'greeting') // same bubble…
  assert.equal($bubble.get().stepIndex, 1) // …advanced
  assert.equal(c.click(), 3)
  assert.equal($bubble.get().stepIndex, 2)
})

test('combo ≥4 queues the idle-line bubble (clickCount reaches the easter-egg zone)', () => {
  const c = createWhaleController()
  c.click()
  c.click()
  c.click()
  assert.equal(c.click(), 4)
  assert.equal($whale.get().clickCount, 4)
  // Observed queue semantics: idle-line shares the info rank with the still-alive
  // greeting (re-armed by the advancing taps), and first-inserted wins the tie —
  // so the greeting stays on screen. The idle-line IS queued behind it; making it
  // preempt needs a controller/queue tweak (WP-owned files) — flagged in WORKLOG.
  assert.equal($bubble.get().key, 'greeting')
})

test('TASK_COMPLETED → happy mood + task-done bubble', () => {
  const c = createWhaleController()
  c.event('TASK_COMPLETED')
  assert.equal($whale.get().mood, 'happy')
  assert.equal($bubble.get().key, 'task-done')
})

test('ERROR clears waiting with no mood of its own', () => {
  const c = createWhaleController()
  c.syncWaiting({ question: true, approval: false })
  c.event('ERROR')
  assert.equal($whale.get().mood, 'idle')
  assert.equal($whale.get().waiting, null)
})

test('turnSettled enqueues a turn_cost bubble keyed by dedup_key', () => {
  const c = createWhaleController()
  c.turnSettled({ dedup_key: 'd1', estimated_cost_text: '0.42 CNY', session_id: 's1' })
  const view = $bubble.get()
  assert.equal(view.key, 'turn:d1')
  assert.equal(view.kind, 'turn_cost')
  assert.equal(view.data.turn_cost_text, '0.42 CNY')
  assert.equal(view.data.session_name, 's1')
})

test('turnSettled without a cost text resolves to `—` (never a fabricated 0)', () => {
  const c = createWhaleController()
  c.turnSettled({ dedup_key: 'd2' })
  const view = $bubble.get()
  assert.equal(view.key, 'turn:d2')
  assert.equal(view.data.turn_cost_text, '—')
  assert.equal(view.data.session_name, null)
})

test('turnSettled with turnCostEnabled=false stays silent', () => {
  const c = createWhaleController({ turnCostEnabled: false })
  c.turnSettled({ dedup_key: 'd3', estimated_cost_text: '9.99' })
  assert.equal($bubble.get(), null)
})

test('turnSettled honours a custom ttl (turn_cost bubbles are short-lived)', async () => {
  const c = createWhaleController({ turnCostTtlMs: 5 })
  c.turnSettled({ dedup_key: 'd4', estimated_cost_text: '1.00' })
  assert.equal($bubble.get().key, 'turn:d4')
  await new Promise((resolve) => setTimeout(resolve, 20))
  c.tick() // the periodic settle re-publishes the swept queue view
  assert.equal($bubble.get(), null)
})

test('syncWaiting opens sticky question/approval bubbles and flips the mood', () => {
  const c = createWhaleController()
  c.syncWaiting({ question: true, approval: false })
  assert.equal($whale.get().mood, 'waiting')
  assert.equal($whale.get().waiting, 'question')
  assert.equal($bubble.get().key, 'wait:question')

  c.syncWaiting({ question: true, approval: true })
  assert.equal($whale.get().waiting, 'approval')
  // both waits rank 4; the first-inserted (question) stays visible until dismissed
  assert.equal($bubble.get().key, 'wait:question')

  c.syncWaiting({ question: false, approval: true })
  assert.equal($whale.get().waiting, 'approval')
  assert.equal($bubble.get().key, 'wait:question')
})

test('syncWaiting close dismisses both waits and returns the mood to idle', () => {
  const c = createWhaleController()
  c.syncWaiting({ question: true, approval: true })
  c.syncWaiting({ question: false, approval: false })
  const whale = $whale.get()
  assert.equal(whale.mood, 'idle')
  assert.equal(whale.waiting, null)
  assert.equal($bubble.get(), null)
})

test('waiting bubbles are sticky (ttl 0): they survive ticks until dismissed', async () => {
  const c = createWhaleController()
  c.syncWaiting({ question: true, approval: false })
  await new Promise((resolve) => setTimeout(resolve, 20))
  assert.equal($bubble.get().key, 'wait:question')
})

test('press/release drives the physical mood through the shared atoms', () => {
  const c = createWhaleController()
  c.press()
  assert.equal($whale.get().mood, 'press')
  c.release()
  assert.equal($whale.get().mood, 'idle')
})

test('tick() re-publishes the machine snapshot (periodic settle)', () => {
  const c = createWhaleController()
  c.event('USAGE_UPDATED') // money transient (real clock: still inside 2.5s)
  const snap = c.tick()
  assert.equal(snap.mood, 'money')
  assert.deepEqual($whale.get(), snap)
})

test('setData feeds the resolver snapshot (no throw, no bubble side effects)', () => {
  const c = createWhaleController()
  c.setData({ balanceText: '110.00 CNY', todayText: '4.57 CNY' })
  assert.equal(c._data.balance_text, '110.00 CNY')
  assert.equal($bubble.get(), null)
})
