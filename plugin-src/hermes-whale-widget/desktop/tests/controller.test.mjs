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

const { createWhaleController, $whale, $bubble, moodAccent } = await import('../src/ui/controller.js')

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

test('combo ≥4 dismisses the greeting and surfaces the idle-line (Goal-pass P2-1)', () => {
  const c = createWhaleController()
  c.click()
  c.click()
  c.click()
  assert.equal(c.click(), 4)
  assert.equal($whale.get().clickCount, 4)
  // the greeting (same info rank, re-armed by the advancing taps) is dismissed
  // first, so the idle-line is actually visible — the WP-1 occlusion fix
  assert.equal($bubble.get().key, 'idle-line')
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

// ── Goal-pass additions (P0-2 notifications consumer + P1-1 sound sink) ────

test('syncNotifications maps rules-engine items to ranked bubbles (— on missing money)', () => {
  const c = createWhaleController()
  c.syncNotifications([
    {
      kind: 'balance_low',
      rank: 2,
      dedup_key: 'balance_low:fp:2026-10-04',
      ttl_ms: 0,
      payload: { observed_balance_units: 0, currency: 'CNY', day: '2026-10-04' },
    },
    { kind: 'wait_input', rank: 4, dedup_key: 'wait:question:t1', ttl_ms: 0, payload: {} }, // skipped: wait-state chain owns it
    { kind: 'bogus', rank: 9, dedup_key: 'x', ttl_ms: 0, payload: {} }, // skipped: unknown kind
  ])
  const view = $bubble.get()
  assert.equal(view.key, 'balance_low:fp:2026-10-04')
  assert.equal(view.kind, 'balance_low') // rank 2 wins the tie-break vs nothing else queued
})

test('syncNotifications: recovered standing alert is dismissed (balance_low recovery)', () => {
  const c = createWhaleController()
  const item = {
    kind: 'balance_low', rank: 2, dedup_key: 'balance_low:fp:d1', ttl_ms: 0,
    payload: { observed_balance_units: 0, currency: 'CNY', day: 'd1' },
  }
  c.syncNotifications([item])
  assert.equal($bubble.get().key, 'balance_low:fp:d1')
  c.syncNotifications([]) // recovery: server no longer lists it
  assert.equal($bubble.get(), null)
})

test('syncNotifications: turn_cost notification carries formatted estimate (est. honesty via def text)', () => {
  const c = createWhaleController()
  c.syncNotifications([
    {
      kind: 'turn_cost', rank: 3, dedup_key: 'turn:d9', ttl_ms: 5000,
      payload: { estimated_cost_units: 42_000_000, currency: 'CNY', cost_basis: 'whale_pricing', model: 'm1' },
    },
  ])
  const view = $bubble.get()
  assert.equal(view.key, 'turn:d9')
  assert.equal(view.kind, 'turn_cost')
})

test('syncWaiting first appearance plays question/approval sound once (sound sink hooked)', () => {
  const c = createWhaleController()
  const played = []
  const pressed = []
  c.attachSound({
    press: () => pressed.push('press'),
    release: () => pressed.push('release'),
    play: (event) => played.push(event),
  })
  c.syncWaiting({ question: true, approval: false })
  c.syncWaiting({ question: true, approval: false }) // sticky re-sync: no repeat
  assert.deepEqual(played, ['question'])
  c.syncWaiting({ question: false, approval: true })
  assert.deepEqual(played, ['question', 'approval'])
  c.syncWaiting({ question: false, approval: false })
  assert.deepEqual(played, ['question', 'approval'])
  c.press()
  c.release()
  assert.deepEqual(pressed, ['press', 'release'])
})

test('TASK_COMPLETED plays task_finished through the sound sink', () => {
  const c = createWhaleController()
  const played = []
  c.attachSound({ play: (event) => played.push(event) })
  c.event('TASK_COMPLETED')
  assert.deepEqual(played, ['task_finished'])
})

// ── Pet-hosting de-roling (DR-15): mood → accent colour mapping ─────────────

test('moodAccent maps every mood to its panel accent colour (idle灰/press蓝/happy绿/money青/waiting黄)', () => {
  assert.equal(moodAccent('idle'), '#6b7280') // 灰
  assert.equal(moodAccent('press'), '#3f97de') // 蓝
  assert.equal(moodAccent('happy'), '#2e7d32') // 绿
  assert.equal(moodAccent('money'), '#0891b2') // 青
  assert.equal(moodAccent('waiting'), '#e8a13a') // 黄
})

test('combo ≥4 surfaces combo-line, combo ≥8 drops easter-egg', () => {
  const c = createWhaleController()
  for (let i = 0; i < 4; i++) c.click()
  assert.equal($bubble.get().key, 'idle-line')
  for (let i = 4; i < 8; i++) c.click()
  assert.equal($bubble.get().key, 'easter-egg')
})

test('triggerIdleBubble surfaces idle-line or quota-report', () => {
  const c = createWhaleController()
  c.triggerIdleBubble()
  assert.equal($bubble.get().key, 'idle-line')
  assert.ok($bubble.get().def)
})

test('moodAccent falls back to idle grey for unknown/missing moods', () => {
  assert.equal(moodAccent('bogus'), moodAccent('idle'))
  assert.equal(moodAccent(undefined), moodAccent('idle'))
})
