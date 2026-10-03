/**
 * Ingest client — POST /ingest/turn forwarding with bounded backoff retry.
 *
 * M1 (IMPLEMENTATION_PLAN M1 task 2 / DATA_MODEL §3.4):
 *   - batches settled turns into `{turns: [...]}` POSTs via ctx.rest
 *     (namespace-relative, apps/desktop/src/api/plugins.ts);
 *   - exponential backoff, max 3 retries per batch, then the batch goes to an
 *     in-memory dead letter (bounded) and the UI is told "记账暂不可用";
 *   - `pause()` during gateway.reconnecting (queue retained, nothing sent);
 *     `resume()` on gateway.ready / first settled turn;
 *   - never blocks process exit: submit/flush are fire-and-forget; no
 *     persistent state (dead letter dies with the plugin — the ledger's
 *     idempotency makes a lost in-flight batch a missed turn, not a double
 *     charge; the focusedUsage salvage keeps the display honest meanwhile).
 */
export const INGEST_TURN_PATH = '/ingest/turn'

export const MAX_RETRIES = 3
export const BACKOFF_BASE_MS = 250
export const MAX_BATCH = 20
export const QUEUE_LIMIT = 200
export const DEAD_LETTER_LIMIT = 50

const defaultDelay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * @param {object} opts
 * @param {(path: string, body: unknown) => Promise<unknown>} opts.rest  ctx.rest adapter
 * @param {number} [opts.maxRetries]  attempts per batch AFTER the first try fails
 * @param {number} [opts.backoffBaseMs]
 * @param {(ms: number) => Promise<void>} [opts.delay]  injectable sleeper (tests)
 * @param {(info: {reason: string}) => void} [opts.onUnavailable]
 * @param {() => void} [opts.onRecovered]
 * @param {() => void} [opts.onStats]  invoked whenever queue/dead-letter state settles
 */
export function createIngestClient({
  rest,
  maxRetries = MAX_RETRIES,
  backoffBaseMs = BACKOFF_BASE_MS,
  maxBatch = MAX_BATCH,
  queueLimit = QUEUE_LIMIT,
  deadLetterLimit = DEAD_LETTER_LIMIT,
  delay = defaultDelay,
  onUnavailable,
  onRecovered,
  onStats,
} = {}) {
  if (typeof rest !== 'function') throw new TypeError('createIngestClient: rest adapter is required')

  const state = {
    queue: [],
    deadLetters: [],
    dropped: 0,
    sent: 0,
    failed: 0,
    unavailable: false,
    paused: false,
    flushing: false,
    scheduled: false,
  }

  function setUnavailable(reason) {
    state.failed++
    if (!state.unavailable) {
      state.unavailable = true
      try {
        onUnavailable?.({ reason })
      } catch {
        /* UI callbacks must never break the client */
      }
    }
  }

  function setRecovered() {
    if (state.unavailable) {
      state.unavailable = false
      try {
        onRecovered?.()
      } catch {
        /* ignore */
      }
    }
  }

  async function postWithRetry(turns) {
    let attempt = 0
    for (;;) {
      try {
        const response = await rest(INGEST_TURN_PATH, { turns })
        setRecovered()
        state.sent += turns.length
        return response
      } catch (err) {
        if (attempt >= maxRetries) {
          if (state.deadLetters.length >= deadLetterLimit) state.deadLetters.shift()
          state.deadLetters.push({ turns, error: String(err?.message || err || 'unknown'), at: Date.now() })
          setUnavailable(String(err?.message || err || 'unknown'))
          return null
        }
        await delay(backoffBaseMs * 2 ** attempt)
        attempt++
      }
    }
  }

  async function flush() {
    if (state.flushing || state.paused) return
    state.flushing = true
    try {
      while (state.queue.length > 0 && !state.paused) {
        const batch = state.queue.splice(0, maxBatch)
        const ok = await postWithRetry(batch)
        if (!ok) {
          // dead-lettered: stop flushing this round; queue keeps the rest
          break
        }
      }
    } finally {
      state.flushing = false
      notifyStats()
    }
  }

  function scheduleFlush() {
    // microtask scheduling: a synchronous burst of submits coalesces into
    // batches, and flushAndWait() can never race an in-flight flush
    if (state.scheduled) return
    state.scheduled = true
    queueMicrotask(() => {
      state.scheduled = false
      void flush()
    })
  }

  function notifyStats() {
    try {
      onStats?.()
    } catch {
      /* UI callbacks must never break the client */
    }
  }

  return {
    /** Enqueue a settled turn payload; schedules a non-blocking flush. */
    submitTurn(payload) {
      if (!payload || typeof payload !== 'object') return
      if (state.queue.length >= queueLimit) {
        state.queue.shift()
        state.dropped++
        notifyStats()
      }
      state.queue.push(payload)
      scheduleFlush() // fire-and-forget: never awaits in the caller's path
    },

    /** Send everything queued right now (tests / resume). Resolves when idle. */
    async flushAndWait() {
      await flush()
      notifyStats()
    },

    pause() {
      state.paused = true
      notifyStats()
    },

    resume() {
      state.paused = false
      // recovery: give dead-lettered batches another chance (bounded by the queue cap)
      while (state.deadLetters.length > 0 && state.queue.length < queueLimit) {
        const item = state.deadLetters.shift()
        state.queue.push(...item.turns)
      }
      void flush()
    },

    isPaused() {
      return state.paused
    },

    isUnavailable() {
      return state.unavailable
    },

    stats() {
      return {
        queued: state.queue.length,
        deadLetters: state.deadLetters.length,
        dropped: state.dropped,
        sent: state.sent,
        failed: state.failed,
        unavailable: state.unavailable,
        paused: state.paused,
        deadLetterItems: state.deadLetters.map((d) => ({ error: d.error, at: d.at, turns: d.turns.length })),
      }
    },
  }
}

/**
 * Build the /ingest/turn payload from a normalized TURN_FINISHED event.
 * (Contract precursor kept for the artifact smoke test; the turn tracker
 * produces the authoritative payload in the live pipeline.)
 */
export function buildTurnPayload(turnFinished, { receivedAt, afterReconnect = false, replayed = false } = {}) {
  return {
    session_id: turnFinished.session_id ?? null,
    profile: turnFinished.profile ?? null,
    model: turnFinished.model ?? null,
    usage: turnFinished.usage ?? null,
    received_at: receivedAt,
    status: turnFinished.status === 'error' || turnFinished.status === 'interrupted' ? turnFinished.status : 'complete',
    after_reconnect: afterReconnect === true,
    replayed: replayed === true,
  }
}
