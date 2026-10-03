/**
 * Event normalization — Hermes gateway events → normalized whale events.
 *
 * M0: minimal, honest subset (ARCHITECTURE_DECISION §4 event table). M1
 * completes the full mapping + payload whitelist extraction (DATA_MODEL §8.4)
 * and locks fixtures (IMPLEMENTATION_PLAN M1). Everything here is a PURE
 * function — node:test target, no SDK/React imports.
 *
 * Normalized whale events (ARCH §4):
 *   TURN_STARTED / TURN_FINISHED / USAGE_UPDATED / TASK_COMPLETED /
 *   USER_INPUT_REQUIRED / APPROVAL_REQUIRED / BALANCE_LOW / BUDGET_REACHED / ERROR
 * Internal (not whale events): STREAM_TICK, TOOL_ACTIVITY, CONNECTION_CHANGED.
 *
 * Discipline (AUDIT §12 / DATA_MODEL R4): `Usage` fields are ALL OPTIONAL —
 * missing → null, NEVER 0 ("null ≠ 0" serialization contract).
 */

/**
 * Turn status from message.complete (TurnStatus): 'complete' | 'error' | 'interrupted'.
 * 'complete' is normalized to 'ok' (ARCH §4); unknown/missing values fall back
 * to 'ok' leniently — M1 re-checks against recorded real events.
 */

/**
 * Extract usage numbers from a Usage-shaped object, NULL-aware.
 * Returns {input, output, reasoning, cache_read, cache_write, calls, cost_usd}
 * with null for every missing field (never fabricates 0).
 */
export function normalizeUsage(usage) {
  if (!usage || typeof usage !== 'object') {
    return { input: null, output: null, reasoning: null, cache_read: null, cache_write: null, calls: null, cost_usd: null }
  }
  const num = (value) => (Number.isFinite(value) ? value : null)
  return {
    input: num(usage.input_tokens ?? usage.input),
    output: num(usage.output_tokens ?? usage.output),
    reasoning: num(usage.reasoning_tokens ?? usage.reasoning),
    cache_read: num(usage.cache_read_tokens ?? usage.cache_read),
    cache_write: num(usage.cache_write_tokens ?? usage.cache_write),
    calls: num(usage.calls),
    cost_usd: num(usage.cost_usd),
  }
}

/**
 * Normalize one gateway event envelope into a whale event (or an internal
 * marker). Returns `null` for unrecognized/uninteresting events.
 *
 * @param {{type?: string, payload?: object, session_id?: string, profile?: string}} raw
 */
export function normalizeEvent(raw) {
  if (!raw || typeof raw !== 'object' || typeof raw.type !== 'string') return null
  const type = raw.type
  const payload = raw.payload ?? {}
  const base = { session_id: raw.session_id ?? null, profile: raw.profile ?? null }

  switch (type) {
    case 'message.start':
      return { kind: 'TURN_STARTED', ...base }
    case 'message.delta':
      return { kind: 'STREAM_TICK', ...base } // internal: never resets animation (M6 discipline)
    case 'session.usage':
      // 1s heartbeat: provisional display only — NEVER persisted (AGENTS.md §8)
      return { kind: 'USAGE_UPDATED', final: false, usage: normalizeUsage(payload.usage), ...base }
    case 'message.complete': {
      // ARCH §4: status=complete → TURN_FINISHED{ok}; error/interrupted pass through.
      // Missing status is treated as complete (lenient envelope) — M1 re-checks
      // against recorded real events.
      const raw = payload?.status
      const status = raw === 'error' || raw === 'interrupted' ? raw : 'ok'
      const events = [
        { kind: 'TURN_FINISHED', status, usage: normalizeUsage(payload?.usage), ...base },
      ]
      if (status === 'ok') {
        events.push({ kind: 'TASK_COMPLETED', ...base })
      } else {
        events.push({ kind: 'ERROR', reason: payload?.error ?? `turn ${status}`, ...base })
      }
      if (payload?.usage) events.push({ kind: 'USAGE_UPDATED', final: true, usage: normalizeUsage(payload.usage), ...base })
      return events
    }
    case 'tool.start':
    case 'tool.complete':
    case 'tool.generating':
      return { kind: 'TOOL_ACTIVITY', phase: type.slice(5), name: payload?.name ?? null, ...base }
    case 'error':
      return { kind: 'ERROR', reason: payload?.message ?? 'unknown error', ...base }
    case 'gateway.reconnecting':
    case 'host.state.gateway':
      return { kind: 'CONNECTION_CHANGED', ...base }
    default:
      return null
  }
}

/** Convenience: flatten normalizeEvent's array-or-object result into a list. */
export function normalizeEventList(raw) {
  const result = normalizeEvent(raw)
  if (result === null) return []
  return Array.isArray(result) ? result : [result]
}
