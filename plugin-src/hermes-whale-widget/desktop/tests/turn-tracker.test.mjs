/**
 * L1 tests for the M1 turn tracker (node:test):
 * (sessionId, turn) bucketing, turn-end-only settlement, heartbeat/salvage
 * fallbacks, after_reconnect tagging, no fabricated usage.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { normalizeEventList } from '../src/core/normalize.js'
import {
  applyFocusedUsage,
  createTurnTracker,
  ingestWhaleEvent,
  markReconnected,
  markReconnecting,
} from '../src/core/turn-tracker.js'

const META = { receivedAt: 1_792_000_000_000, model: 'deepseek-chat', profile: 'default' }

function feed(tracker, raw, meta = META) {
  const payloads = []
  for (const event of normalizeEventList(raw)) {
    const payload = ingestWhaleEvent(tracker, event, meta)
    if (payload) payloads.push(payload)
  }
  return payloads
}

const COMPLETE = (usage, extra = {}) => ({
  type: 'message.complete',
  session_id: 's1',
  payload: { status: 'complete', usage, ...extra },
})

test('full turn: start → heartbeats → complete settles once with the authoritative usage', () => {
  const tracker = createTurnTracker()
  assert.deepEqual(feed(tracker, { type: 'message.start', session_id: 's1' }), [])
  assert.deepEqual(
    feed(tracker, { type: 'session.usage', session_id: 's1', payload: { usage: { input_tokens: 10 } } }),
    [],
  )
  const payloads = feed(tracker, COMPLETE({ input_tokens: 100, output_tokens: 50 }))
  assert.equal(payloads.length, 1)
  const p = payloads[0]
  assert.equal(p.session_id, 's1')
  assert.equal(p.model, 'deepseek-chat')
  assert.equal(p.profile, 'default')
  assert.equal(p.status, 'complete')
  assert.equal(p.received_at, META.receivedAt)
  assert.equal(p.after_reconnect, false)
  assert.equal(p.usage_source, 'complete')
  assert.equal(p.usage.input, 100)
  assert.equal(p.usage.output, 50)
  // heartbeats never produce payloads (AGENTS.md §8: 心跳永不落库)
  assert.equal(feed(tracker, { type: 'session.usage', session_id: 's1', payload: { usage: { input_tokens: 999 } } }).length, 0)
})

test('turn settles exactly once — a duplicate complete for a closed turn re-settles only via Python dedup', () => {
  const tracker = createTurnTracker()
  assert.equal(feed(tracker, COMPLETE({ input_tokens: 10 })).length, 1)
  // bucket removed after settle; the same event again still yields a payload
  // (JS is stateless across reloads — DATA_MODEL §3.2) — Python dedups.
  const second = feed(tracker, COMPLETE({ input_tokens: 10 }))
  assert.equal(second.length, 1)
  assert.equal(second[0].usage_source, 'complete')
})

test('error/interrupted statuses map to Hermes TurnStatus in the payload', () => {
  const tracker = createTurnTracker()
  const [err] = feed(tracker, { type: 'message.complete', session_id: 's1', payload: { status: 'error', usage: { input: 5 } } })
  assert.equal(err.status, 'error')
  const [interrupted] = feed(tracker, { type: 'message.complete', session_id: 's1', payload: { status: 'interrupted', usage: { input: 6 } } })
  assert.equal(interrupted.status, 'interrupted')
})

test('complete without usage falls back to the last heartbeat of the open turn', () => {
  const tracker = createTurnTracker()
  feed(tracker, { type: 'message.start', session_id: 's1' })
  feed(tracker, { type: 'session.usage', session_id: 's1', payload: { usage: { input_tokens: 42 } } })
  const [p] = feed(tracker, COMPLETE(undefined))
  assert.equal(p.usage_source, 'heartbeat')
  assert.equal(p.usage.input, 42)
})

test('no usage anywhere → no payload (nothing fabricated), reconnect flag not consumed', () => {
  const tracker = createTurnTracker()
  markReconnecting(tracker)
  assert.deepEqual(feed(tracker, { type: 'message.complete', session_id: 's1', payload: { status: 'complete' } }), [])
  // a later settle with usage still carries the reconnect tag
  const [p] = feed(tracker, COMPLETE({ input_tokens: 7 }))
  assert.equal(p.after_reconnect, true)
})

test('first settle after reconnect is tagged after_reconnect, subsequent are not', () => {
  const tracker = createTurnTracker()
  feed(tracker, COMPLETE({ input_tokens: 10 }))
  markReconnecting(tracker)
  const [first] = feed(tracker, COMPLETE({ input_tokens: 20 }))
  assert.equal(first.after_reconnect, true)
  const [second] = feed(tracker, COMPLETE({ input_tokens: 30 }))
  assert.equal(second.after_reconnect, false)
})

test('focusedUsage salvage applies to the matching (or unknown) session only', () => {
  const tracker = createTurnTracker()
  assert.equal(applyFocusedUsage(tracker, { input_tokens: 55 }, { sessionId: 's1' }), true)
  // mismatching session: no salvage applied
  assert.deepEqual(feed(tracker, { type: 'message.complete', session_id: 's2', payload: { status: 'complete' } }), [])
  const [p] = feed(tracker, { type: 'message.complete', session_id: 's1', payload: { status: 'complete' } })
  assert.equal(p.usage_source, 'focused')
  assert.equal(p.usage.input, 55)
})

test('markReconnecting captures the focusedUsage salvage snapshot', () => {
  const tracker = createTurnTracker()
  markReconnecting(tracker, { salvageUsage: { input_tokens: 77 }, salvageSessionId: 's1' })
  const [p] = feed(tracker, { type: 'message.complete', session_id: 's1', payload: { status: 'complete' } })
  assert.equal(p.usage_source, 'focused')
  assert.equal(p.usage.input, 77)
  markReconnected(tracker)
})

test('non-measurable salvage (context-only) is rejected', () => {
  const tracker = createTurnTracker()
  assert.equal(applyFocusedUsage(tracker, { context_used: 100 }, { sessionId: 's1' }), false)
})

test('session.info remembers the model for turns without an open bucket', () => {
  const tracker = createTurnTracker()
  feed(tracker, { type: 'session.info', session_id: 's9', payload: { model: 'glm-5' } })
  const [p] = feed(tracker, { type: 'message.complete', session_id: 's9', payload: { status: 'complete', usage: { input: 3 } } })
  assert.equal(p.model, 'glm-5')
})

test('meta.model is the fallback when no session fact exists', () => {
  const tracker = createTurnTracker()
  const [p] = feed(tracker, COMPLETE({ input: 3 }), { receivedAt: 1, model: 'fallback-model', profile: 'work' })
  assert.equal(p.model, 'fallback-model')
  assert.equal(p.profile, 'work')
})

test('replayed envelope flag rides into the payload', () => {
  const tracker = createTurnTracker()
  const [p] = feed(tracker, { type: 'message.complete', session_id: 's1', replayed: true, payload: { status: 'complete', usage: { input: 3 } } })
  assert.equal(p.replayed, true)
  assert.equal(p.after_reconnect, false)
})

test('non-settling events never produce payloads', () => {
  const tracker = createTurnTracker()
  assert.deepEqual(feed(tracker, { type: 'message.delta', session_id: 's1', payload: { text: 'x' } }), [])
  assert.deepEqual(feed(tracker, { type: 'tool.start', session_id: 's1', payload: { name: 'bash' } }), [])
  assert.deepEqual(feed(tracker, { type: 'error', session_id: 's1', payload: { message: 'x' } }), [])
  assert.deepEqual(feed(tracker, { type: 'totally.unknown', session_id: 's1' }), [])
})

test('two sessions bucket independently', () => {
  const tracker = createTurnTracker()
  feed(tracker, { type: 'message.start', session_id: 's1' })
  feed(tracker, { type: 'message.start', session_id: 's2' })
  feed(tracker, { type: 'session.usage', session_id: 's1', payload: { usage: { input_tokens: 11 } } })
  feed(tracker, { type: 'session.usage', session_id: 's2', payload: { usage: { input_tokens: 22 } } })
  const [p1] = feed(tracker, { type: 'message.complete', session_id: 's1', payload: { status: 'complete' } })
  const [p2] = feed(tracker, { type: 'message.complete', session_id: 's2', payload: { status: 'complete' } })
  assert.equal(p1.usage.input, 11)
  assert.equal(p2.usage.input, 22)
})
