/**
 * Event normalization — Hermes gateway events → normalized whale events.
 *
 * M1: full mapping (ARCHITECTURE_DECISION §4 event table). Everything here is
 * PURE — node:test target, no SDK/React imports, no I/O, no module state.
 * Unknown events are dropped; the createNormalizer() wrapper counts them
 * ("未知事件透传丢弃并计数") without breaking purity of the map itself.
 *
 * Normalized whale events (ARCH §4):
 *   TURN_STARTED / TURN_FINISHED / USAGE_UPDATED / TASK_COMPLETED /
 *   USER_INPUT_REQUIRED / APPROVAL_REQUIRED / BALANCE_LOW / BUDGET_REACHED / ERROR
 *   (BALANCE_LOW / BUDGET_REACHED are RULE outputs of the Python half — they
 *   are never produced from gateway events; USER_INPUT_REQUIRED /
 *   APPROVAL_REQUIRED come from M8's wait observation, not here.)
 * Internal (not whale events): STREAM_TICK, TOOL_ACTIVITY, CONNECTION_CHANGED,
 *   SESSION_INFO, APPROVAL_CLEARED.
 *
 * Discipline (AUDIT §12 / DATA_MODEL R4): `Usage` fields are ALL OPTIONAL —
 * missing → null, NEVER 0 ("null ≠ 0" serialization contract). The envelope
 * flags `replayed` / `replayEpoch` are carried on TURN_FINISHED so the ingest
 * half can tag reconnect replays (DATA_MODEL §3.4).
 */

/**
 * Extract usage numbers from a Usage-shaped object, NULL-aware.
 * Returns {input, output, reasoning, cache_read, cache_write, calls,
 * cost_usd, context_used, context_max, context_percent} with null for every
 * missing field (never fabricates 0). Whitelist only (DATA_MODEL §8.4):
 * no free-form payload fields survive.
 */
export function normalizeUsage(usage) {
  if (!usage || typeof usage !== 'object') {
    return {
      input: null, output: null, reasoning: null, cache_read: null, cache_write: null,
      calls: null, cost_usd: null, context_used: null, context_max: null, context_percent: null,
    }
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
    context_used: num(usage.context_used),
    context_max: num(usage.context_max),
    context_percent: num(usage.context_percent),
  }
}

/** True when the snapshot carries at least one measurable counter (R4). */
export function hasMeasurableUsage(usage) {
  if (!usage || typeof usage !== 'object') return false
  return [usage.input, usage.output, usage.reasoning, usage.cache_read, usage.cache_write, usage.calls]
    .some((v) => v !== null && v !== undefined)
}

/**
 * Normalize one gateway event envelope into a whale event (or an internal
 * marker). Returns `null` for unrecognized/uninteresting events.
 *
 * @param {{type?: string, payload?: object, session_id?: string, profile?: string,
 *          replayed?: boolean, replayEpoch?: number}} raw
 */
export function normalizeEvent(raw) {
  if (!raw || typeof raw !== 'object' || typeof raw.type !== 'string') return null
  const type = raw.type
  const payload = raw.payload ?? {}
  const base = { session_id: raw.session_id ?? null, profile: raw.profile ?? null }
  const replayed = raw.replayed === true

  switch (type) {
    case 'message.start':
      return { kind: 'TURN_STARTED', ...base }
    case 'message.delta':
      return { kind: 'STREAM_TICK', ...base } // internal: never resets animation (M6 discipline)
    case 'session.usage':
      // 1s heartbeat: provisional display only — NEVER persisted (AGENTS.md §8)
      return { kind: 'USAGE_UPDATED', final: false, usage: normalizeUsage(payload.usage), ...base }
    case 'session.info':
      // per-session live facts (model/provider) — feeds turn attribution (AUDIT §4.1)
      return {
        kind: 'SESSION_INFO',
        model: typeof payload?.model === 'string' && payload.model ? payload.model : null,
        provider: typeof payload?.provider === 'string' && payload.provider ? payload.provider : null,
        ...base,
      }
    case 'message.complete': {
      // ARCH §4: status=complete → TURN_FINISHED{ok}; error/interrupted pass through.
      // Missing status is treated as complete (lenient envelope) — re-checked
      // against recorded real events at the M5 smoke.
      const rawStatus = payload?.status
      const status = rawStatus === 'error' || rawStatus === 'interrupted' ? rawStatus : 'ok'
      const events = [
        { kind: 'TURN_FINISHED', status, usage: normalizeUsage(payload?.usage), replayed, ...base },
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
      return { kind: 'CONNECTION_CHANGED', phase: 'reconnecting', attempt: payload?.attempt ?? null, ...base }
    case 'gateway.ready':
      // first frame after (re)connect: carries the new replay epoch (AUDIT §4.1)
      return { kind: 'CONNECTION_CHANGED', phase: 'ready', replay_epoch: payload?.replayEpoch ?? null, ...base }
    case 'host.state.gateway':
      return { kind: 'CONNECTION_CHANGED', phase: 'state', ...base }
    case 'approval.cancelled':
      // pending approval ended (deny/timeout) — clears the M8 wait slot
      return { kind: 'APPROVAL_CLEARED', ...base }
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

/**
 * Stateful-but-in-memory wrapper that COUNTS what the pure map drops.
 * The counting state lives in the factory instance (never module-global), so
 * the mapping itself stays a pure function and hot reload cannot leak counters.
 */
export function createNormalizer() {
  const stats = { seen: 0, emitted: 0, droppedUnknown: 0, unknownTypes: {} }
  return {
    normalize(raw) {
      stats.seen++
      const events = normalizeEventList(raw)
      if (events.length === 0 && (raw && typeof raw === 'object' && typeof raw.type === 'string')) {
        stats.droppedUnknown++
        const t = raw.type
        stats.unknownTypes[t] = (stats.unknownTypes[t] ?? 0) + 1
      }
      stats.emitted += events.length
      return events
    },
    stats() {
      return { ...stats, unknownTypes: { ...stats.unknownTypes } }
    },
  }
}
