/**
 * L1 tests for the M1 ingest client (node:test, mock ctx.rest):
 * batched forwarding, bounded backoff retry → in-memory dead letter +
 * unavailable signal, reconnect pause/resume, queue caps, exit-safe flush.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { createIngestClient, INGEST_TURN_PATH } from '../src/core/ingest-client.js'

const TURN = (session_id = 's1') => ({
  session_id,
  profile: null,
  model: 'deepseek-chat',
  usage: { input: 10, output: 5 },
  received_at: 1_792_000_000_000,
  status: 'complete',
  after_reconnect: false,
})

const instantDelay = () => Promise.resolve()

function okRest(calls) {
  return async (path, body) => {
    calls.push({ path, body })
    return { status: 'accepted', accepted: body.turns.length, duplicate: 0 }
  }
}

test('submits a settled turn as a {turns:[...]} POST to /ingest/turn', async () => {
  const calls = []
  const client = createIngestClient({ rest: okRest(calls), delay: instantDelay })
  client.submitTurn(TURN())
  await client.flushAndWait()
  assert.deepEqual(
    calls.map((c) => c.path),
    [INGEST_TURN_PATH],
  )
  assert.deepEqual(calls[0].body, { turns: [TURN()] })
  const stats = client.stats()
  assert.equal(stats.sent, 1)
  assert.equal(stats.queued, 0)
  assert.equal(stats.unavailable, false)
})

test('batches the queue (max 20 per POST)', async () => {
  const calls = []
  const client = createIngestClient({ rest: okRest(calls), delay: instantDelay })
  for (let i = 0; i < 25; i++) client.submitTurn(TURN(`s${i}`))
  await client.flushAndWait()
  assert.deepEqual(calls.map((c) => c.body.turns.length), [20, 5])
})

test('retries with backoff up to the cap, then dead-letters and flags unavailable', async () => {
  const calls = []
  let failures = 0
  const delays = []
  const client = createIngestClient({
    rest: async () => {
      calls.push(1)
      failures++
      if (failures <= 2) throw new Error('rest down')
      return { status: 'accepted', accepted: 1, duplicate: 0 }
    },
    maxRetries: 3,
    delay: (ms) => {
      delays.push(ms)
      return Promise.resolve()
    },
  })
  client.submitTurn(TURN())
  await client.flushAndWait()
  assert.equal(calls.length, 3) // first try + 2 failures then success
  assert.deepEqual(delays, [250, 500]) // exponential backoff
  assert.equal(client.stats().unavailable, false)
})

test('exhausted retries → dead letter + unavailable, queue paused for later resume', async () => {
  const calls = []
  const unavailable = []
  const client = createIngestClient({
    rest: async () => {
      calls.push(1)
      throw new Error('dashboard unreachable')
    },
    maxRetries: 2,
    delay: instantDelay,
    onUnavailable: (info) => unavailable.push(info.reason),
  })
  client.submitTurn(TURN('a'))
  client.submitTurn(TURN('b'))
  await client.flushAndWait()
  assert.equal(calls.length, 3) // 1 + maxRetries (first batch only; loop stops on failure)
  const stats = client.stats()
  assert.equal(stats.unavailable, true)
  assert.equal(stats.deadLetters, 1)
  assert.equal(stats.sent, 0)
  assert.deepEqual(unavailable, ['dashboard unreachable'])
  assert.equal(stats.deadLetterItems[0].turns, 2)
})

test('resume() after recovery flushes the retained queue', async () => {
  const calls = []
  let down = true
  const client = createIngestClient({
    rest: async (path, body) => {
      calls.push(body.turns.length)
      if (down) throw new Error('down')
      return { status: 'accepted', accepted: body.turns.length, duplicate: 0 }
    },
    maxRetries: 0,
    delay: instantDelay,
  })
  client.submitTurn(TURN('a'))
  await client.flushAndWait()
  assert.equal(client.stats().unavailable, true)

  down = false
  client.resume()
  await client.flushAndWait()
  const stats = client.stats()
  assert.equal(stats.unavailable, false)
  assert.equal(stats.sent, 1)
})

test('pause() holds the queue during gateway.reconnecting; nothing is sent', async () => {
  const calls = []
  const client = createIngestClient({ rest: okRest(calls), delay: instantDelay })
  client.pause()
  client.submitTurn(TURN())
  await client.flushAndWait()
  assert.deepEqual(calls, [])
  assert.equal(client.isPaused(), true)
  assert.equal(client.stats().queued, 1)

  client.resume()
  await client.flushAndWait()
  assert.equal(calls.length, 1)
  assert.equal(client.isPaused(), false)
})

test('queue cap drops the oldest and counts the drop', async () => {
  const calls = []
  const client = createIngestClient({ rest: okRest(calls), delay: instantDelay, queueLimit: 2 })
  client.submitTurn(TURN('a'))
  client.submitTurn(TURN('b'))
  client.submitTurn(TURN('c'))
  await client.flushAndWait()
  // 'a' was dropped; the POST carries b + c
  assert.deepEqual(calls[0].body.turns.map((t) => t.session_id), ['b', 'c'])
  assert.equal(client.stats().dropped, 1)
})

test('submitTurn never blocks and survives a throwing rest adapter', async () => {
  assert.throws(() => createIngestClient({ rest: undefined }), TypeError)
  const boom = createIngestClient({
    rest: async () => {
      throw new Error('sync-ish failure')
    },
    maxRetries: 0,
    delay: instantDelay,
  })
  boom.submitTurn(TURN())
  await boom.flushAndWait()
  assert.equal(boom.stats().deadLetters, 1)
})

test('flushAndWait is re-entrant safe (no double send)', async () => {
  const calls = []
  const client = createIngestClient({ rest: okRest(calls), delay: instantDelay })
  client.submitTurn(TURN())
  await Promise.all([client.flushAndWait(), client.flushAndWait()])
  assert.equal(calls.length, 1)
})
