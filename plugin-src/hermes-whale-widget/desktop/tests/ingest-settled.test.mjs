/**
 * WP-1/WP-2 cross-package contract on the ingest client (node:test):
 * the response MAY carry `settled: [{dedup_key, estimated_cost_units, currency,
 * cost_basis}]` — forwarded to onSettled(results, batchTurns) ONLY when the
 * response carries a settled ARRAY; a throwing onSettled never breaks the
 * flush; responses without settled keep the previous behaviour exactly.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { createIngestClient } from '../src/core/ingest-client.js'

const TURN = (session_id = 's1') => ({
  session_id,
  profile: null,
  model: 'm',
  usage: { input: 10, output: 5 },
  received_at: 1,
  status: 'complete',
  after_reconnect: false,
})

const instantDelay = () => Promise.resolve()

test('a settled ARRAY in the response reaches onSettled with (results, batchTurns)', async () => {
  const calls = []
  const settled = [{ dedup_key: 'k1', estimated_cost_units: 42_000_000, currency: 'CNY', cost_basis: 'whale_pricing' }]
  const client = createIngestClient({
    rest: async () => ({ status: 'accepted', accepted: 1, duplicate: 0, settled }),
    delay: instantDelay,
    onSettled: (results, turns) => calls.push({ results, turns }),
  })
  client.submitTurn(TURN())
  await client.flushAndWait()
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].results, settled)
  assert.equal(calls[0].turns.length, 1)
  assert.equal(calls[0].turns[0].session_id, 's1')
  assert.equal(client.stats().sent, 1)
})

test('each batch fires one onSettled with its own turns', async () => {
  const batches = []
  const client = createIngestClient({
    rest: async (path, body) => {
      return {
        status: 'accepted',
        accepted: body.turns.length,
        settled: body.turns.map((t) => ({ dedup_key: `k:${t.session_id}`, estimated_cost_units: 1 })),
      }
    },
    maxBatch: 1,
    delay: instantDelay,
    onSettled: (results, turns) => batches.push({ results, turns }),
  })
  client.submitTurn(TURN('a'))
  client.submitTurn(TURN('b'))
  await client.flushAndWait()
  assert.deepEqual(batches.map((b) => b.turns[0].session_id), ['a', 'b'])
  assert.deepEqual(batches.map((b) => b.results[0].dedup_key), ['k:a', 'k:b'])
})

test('a response WITHOUT settled (or with a non-array) keeps the old behaviour', async () => {
  const calls = []
  let respond = () => ({ status: 'accepted', accepted: 1, duplicate: 0 })
  const client = createIngestClient({
    rest: async () => respond(),
    delay: instantDelay,
    onSettled: (results) => calls.push(results),
  })
  client.submitTurn(TURN())
  await client.flushAndWait()
  assert.deepEqual(calls, []) // no settled → no callback

  respond = () => ({ status: 'accepted', settled: 'not-an-array' })
  client.submitTurn(TURN('b'))
  await client.flushAndWait()
  assert.deepEqual(calls, []) // non-array settled → ignored, no throw
  assert.equal(client.stats().sent, 2)
})

test('a throwing onSettled never breaks the flush', async () => {
  let boom = false
  const client = createIngestClient({
    rest: async () => ({ status: 'accepted', accepted: 1, settled: [{ dedup_key: 'k' }] }),
    delay: instantDelay,
    onSettled: () => {
      if (boom) throw new Error('bubble engine exploded')
    },
  })
  client.submitTurn(TURN())
  await client.flushAndWait()
  assert.equal(client.stats().sent, 1)

  boom = true
  client.submitTurn(TURN('s2'))
  await client.flushAndWait()
  assert.equal(client.stats().sent, 2)
  assert.equal(client.stats().unavailable, false)
})

test('no onSettled provided → settled responses are simply ignored', async () => {
  const client = createIngestClient({
    rest: async () => ({ status: 'accepted', accepted: 1, settled: [{ dedup_key: 'k' }] }),
    delay: instantDelay,
  })
  client.submitTurn(TURN())
  await client.flushAndWait()
  assert.equal(client.stats().sent, 1)
})
