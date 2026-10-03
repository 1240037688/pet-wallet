/**
 * L1 tests for the M1 normalize layer (node:test).
 * Discipline under test: null-aware usage (never fabricate 0), status split
 * on message.complete, heartbeat never marked final, unknown → null + counted
 * by the createNormalizer wrapper, envelope replay flag passthrough.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { createNormalizer, hasMeasurableUsage, normalizeEvent, normalizeEventList, normalizeUsage } from '../src/core/normalize.js'

test('message.complete with full usage → TURN_FINISHED(ok) + TASK_COMPLETED + USAGE_UPDATED(final)', () => {
  const events = normalizeEventList({
    type: 'message.complete',
    session_id: 's1',
    profile: 'default',
    payload: {
      status: 'complete',
      usage: { input_tokens: 100, output_tokens: 50, reasoning_tokens: 10, cache_read_tokens: 5, cache_write_tokens: 2, calls: 3, cost_usd: 0.01 },
    },
  })
  const kinds = events.map((e) => e.kind)
  assert.deepEqual(kinds, ['TURN_FINISHED', 'TASK_COMPLETED', 'USAGE_UPDATED'])
  const finished = events[0]
  assert.equal(finished.status, 'ok')
  assert.equal(finished.usage.input, 100)
  assert.equal(finished.usage.cost_usd, 0.01)
  assert.equal(finished.session_id, 's1')
  assert.equal(events[2].final, true)
})

test('message.complete status=error → TURN_FINISHED(error) + ERROR (no TASK_COMPLETED)', () => {
  const events = normalizeEventList({ type: 'message.complete', payload: { status: 'error', error: 'boom' } })
  const kinds = events.map((e) => e.kind)
  assert.deepEqual(kinds, ['TURN_FINISHED', 'ERROR'])
  assert.equal(events[0].status, 'error')
  assert.equal(events[1].reason, 'boom')
})

test('message.complete status=interrupted → TURN_FINISHED(interrupted) + ERROR', () => {
  const events = normalizeEventList({ type: 'message.complete', payload: { status: 'interrupted' } })
  assert.equal(events[0].status, 'interrupted')
  assert.equal(events[1].kind, 'ERROR')
})

test('missing usage fields are null — never 0 (null ≠ 0 contract)', () => {
  const usage = normalizeUsage(undefined)
  assert.deepEqual(usage, {
    input: null, output: null, reasoning: null, cache_read: null, cache_write: null,
    calls: null, cost_usd: null, context_used: null, context_max: null, context_percent: null,
  })
  const partial = normalizeUsage({ input_tokens: 7 })
  assert.equal(partial.input, 7)
  assert.equal(partial.output, null)
  assert.equal(partial.cost_usd, null)
  assert.equal(partial.context_used, null)
})

test('context fields pass through when present', () => {
  const usage = normalizeUsage({ input_tokens: 1, context_used: 1200, context_max: 8192, context_percent: 14.6 })
  assert.equal(usage.context_used, 1200)
  assert.equal(usage.context_max, 8192)
  assert.equal(usage.context_percent, 14.6)
})

test('garbage usage values degrade to null, not 0', () => {
  const usage = normalizeUsage({ input_tokens: 'many', output_tokens: NaN, calls: Infinity })
  assert.equal(usage.input, null)
  assert.equal(usage.output, null)
  assert.equal(usage.calls, null)
})

test('hasMeasurableUsage: at least one counter present', () => {
  assert.equal(hasMeasurableUsage(normalizeUsage({ input: 1 })), true)
  assert.equal(hasMeasurableUsage(normalizeUsage({ calls: 0 })), true)
  assert.equal(hasMeasurableUsage(normalizeUsage({})), false)
  assert.equal(hasMeasurableUsage(normalizeUsage(undefined)), false)
  // context-only snapshots are NOT measurable for settlement
  assert.equal(hasMeasurableUsage(normalizeUsage({ context_used: 5 })), false)
})

test('session.usage heartbeat → USAGE_UPDATED provisional (final:false, never persisted)', () => {
  const event = normalizeEvent({ type: 'session.usage', payload: { usage: { input_tokens: 1 } } })
  assert.equal(event.kind, 'USAGE_UPDATED')
  assert.equal(event.final, false)
})

test('session.info → SESSION_INFO with model/provider (turn attribution input)', () => {
  const event = normalizeEvent({ type: 'session.info', session_id: 's1', payload: { model: 'deepseek-chat', provider: 'deepseek' } })
  assert.equal(event.kind, 'SESSION_INFO')
  assert.equal(event.model, 'deepseek-chat')
  assert.equal(event.provider, 'deepseek')
})

test('tool events → internal TOOL_ACTIVITY with phase + name', () => {
  const event = normalizeEvent({ type: 'tool.start', payload: { name: 'clarify' } })
  assert.equal(event.kind, 'TOOL_ACTIVITY')
  assert.equal(event.phase, 'start')
  assert.equal(event.name, 'clarify')
})

test('message.start / error / reconnecting map to their normalized kinds', () => {
  assert.equal(normalizeEvent({ type: 'message.start' }).kind, 'TURN_STARTED')
  assert.equal(normalizeEvent({ type: 'error', payload: { message: 'x' } }).kind, 'ERROR')
  const reconnecting = normalizeEvent({ type: 'gateway.reconnecting', payload: { attempt: 2 } })
  assert.equal(reconnecting.kind, 'CONNECTION_CHANGED')
  assert.equal(reconnecting.phase, 'reconnecting')
  assert.equal(reconnecting.attempt, 2)
})

test('gateway.ready → CONNECTION_CHANGED(ready) with replay epoch', () => {
  const event = normalizeEvent({ type: 'gateway.ready', payload: { replayEpoch: 7 } })
  assert.equal(event.kind, 'CONNECTION_CHANGED')
  assert.equal(event.phase, 'ready')
  assert.equal(event.replay_epoch, 7)
})

test('approval.cancelled → internal APPROVAL_CLEARED', () => {
  assert.equal(normalizeEvent({ type: 'approval.cancelled' }).kind, 'APPROVAL_CLEARED')
})

test('envelope replayed flag rides on TURN_FINISHED', () => {
  const live = normalizeEvent({ type: 'message.complete', payload: {} })
  assert.equal(live[0].replayed, false)
  const replayed = normalizeEvent({ type: 'message.complete', replayed: true, replayEpoch: 3, payload: {} })
  assert.equal(replayed[0].replayed, true)
})

test('unknown / malformed events → null (and empty list)', () => {
  assert.equal(normalizeEvent({ type: 'something.new' }), null)
  assert.equal(normalizeEvent(null), null)
  assert.equal(normalizeEvent({}), null)
  assert.deepEqual(normalizeEventList({ type: 'something.new' }), [])
})

test('message.complete with no status defaults to complete (lenient envelope)', () => {
  const events = normalizeEventList({ type: 'message.complete', payload: {} })
  assert.equal(events[0].status, 'ok')
  assert.equal(events[1].kind, 'TASK_COMPLETED')
})

test('createNormalizer counts dropped unknown events without breaking purity', () => {
  const n = createNormalizer()
  n.normalize({ type: 'message.complete', payload: { status: 'complete', usage: { input: 1 } } })
  n.normalize({ type: 'totally.unknown' })
  n.normalize({ type: 'totally.unknown' })
  n.normalize({ type: 'another.unknown' })
  n.normalize({ notAnEvent: true })
  const stats = n.stats()
  assert.equal(stats.seen, 5)
  assert.equal(stats.emitted, 3) // complete → TURN_FINISHED + TASK_COMPLETED + USAGE_UPDATED
  assert.equal(stats.droppedUnknown, 3)
  assert.deepEqual(stats.unknownTypes, { 'totally.unknown': 2, 'another.unknown': 1 })
  // instances are isolated (no module-global counters)
  assert.deepEqual(createNormalizer().stats().droppedUnknown, 0)
})
