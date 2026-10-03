/**
 * Turn tracker — (sessionId, turn) bucketing over normalized whale events.
 *
 * Pure in-memory logic (M1, IMPLEMENTATION_PLAN M1 / AGENTS.md §8):
 *   - `session.usage` heartbeats only refresh the open turn's provisional
 *     snapshot IN MEMORY; they are never forwarded for persistence
 *     ("心跳永不落库", "aggregate → turn end → persist").
 *   - TURN_FINISHED settles the turn exactly once: authoritative usage =
 *     message.complete snapshot; fallback = last heartbeat of the open turn;
 *     last resort = a focusedUsage salvage snapshot (host.state.focusedUsage,
 *     captured at reconnect / when the plugin loaded mid-turn). A turn with
 *     no measurable usage at all is NOT forwarded (nothing to record).
 *   - The first settle produced after a gateway reconnect is tagged
 *     `after_reconnect: true` (Python aligns the watermark without settling —
 *     DATA_MODEL §3.4); replayed completions carry `replayed: true` (envelope
 *     flag) and Python treats them the same way.
 *   - JS keeps NO persistence: buckets die with the process; dedup and
 *     turn_seq are Python-side (DATA_MODEL §3.2 — "JS 半体无状态").
 *
 * No I/O, no clocks of its own: `receivedAt` and model/profile hints are
 * always passed in via `meta`. node:test target.
 */
import { hasMeasurableUsage, normalizeUsage } from './normalize.js'

export function createTurnTracker() {
  return {
    turns: new Map(),      // session_id -> open-turn bucket
    sessions: new Map(),   // session_id -> {model, profile} durable-per-process facts
    reconnecting: false,   // set by gateway.reconnecting; consumed by first settle
    salvage: null,         // {session_id, usage} from host.state.focusedUsage
  }
}

/** Record a per-session fact (model/provider) from SESSION_INFO. */
export function rememberSessionInfo(tracker, event) {
  if (!event || event.kind !== 'SESSION_INFO' || !event.session_id) return
  const known = tracker.sessions.get(event.session_id) ?? { model: null, profile: null }
  if (event.model) known.model = event.model
  if (event.provider) known.provider = event.provider
  tracker.sessions.set(event.session_id, known)
  const bucket = tracker.turns.get(event.session_id)
  if (bucket && event.model) bucket.model = event.model
}

/** Enter reconnect mode: pause tagging + capture the focusedUsage salvage. */
export function markReconnecting(tracker, { salvageUsage = null, salvageSessionId = null } = {}) {
  tracker.reconnecting = true
  if (salvageUsage) {
    const usage = normalizeUsage(salvageUsage)
    if (hasMeasurableUsage(usage)) tracker.salvage = { session_id: salvageSessionId, usage }
  }
}

/** Leave reconnect mode (gateway ready / first successful settle). */
export function markReconnected(tracker) {
  tracker.reconnecting = false
}

/**
 * Capture `host.state.focusedUsage` as a salvage snapshot (display-grade
 * fallback when a completion carries no usage of its own).
 */
export function applyFocusedUsage(tracker, focusedUsage, { sessionId = null } = {}) {
  if (!focusedUsage) return false
  const usage = normalizeUsage(focusedUsage)
  if (!hasMeasurableUsage(usage)) return false
  tracker.salvage = { session_id: sessionId, usage }
  return true
}

function resolveModel(tracker, event, meta, sessionId) {
  const bucket = tracker.turns.get(sessionId)
  if (bucket?.model) return bucket.model
  // per-session fact (session.info) outranks the focused-session hint
  const known = tracker.sessions.get(sessionId)
  if (known?.model) return known.model
  if (meta?.model) return meta.model
  return null
}

function resolveProfile(event, meta, sessionId) {
  if (event.profile) return event.profile
  if (meta?.profile) return meta.profile
  return null
}

/** Hermes TurnStatus ('complete'|'error'|'interrupted') for the ingest payload. */
function payloadStatus(event) {
  if (event.status === 'error' || event.status === 'interrupted') return event.status
  return 'complete' // normalized 'ok'
}

/**
 * Feed one normalized whale event; returns an /ingest/turn payload when the
 * event settles a turn, else null. `meta` = {receivedAt, model, profile}.
 */
export function ingestWhaleEvent(tracker, event, meta = {}) {
  if (!tracker || !event || typeof event !== 'object') return null
  const sessionId = event.session_id

  switch (event.kind) {
    case 'TURN_STARTED': {
      if (!sessionId) return null
      if (!tracker.turns.has(sessionId)) {
        tracker.turns.set(sessionId, {
          session_id: sessionId,
          profile: event.profile ?? null,
          model: meta.model ?? null,
          startedAt: meta.receivedAt ?? null,
          lastHeartbeat: null,
        })
      }
      return null
    }
    case 'SESSION_INFO':
      rememberSessionInfo(tracker, event)
      return null
    case 'USAGE_UPDATED': {
      if (event.final) return null // final snapshot travels with TURN_FINISHED
      if (!sessionId || !event.usage || !hasMeasurableUsage(event.usage)) return null
      const bucket = tracker.turns.get(sessionId)
      if (bucket) bucket.lastHeartbeat = event.usage
      return null
    }
    case 'TURN_FINISHED': {
      if (!sessionId) return null
      const bucket = tracker.turns.get(sessionId)
      const known = tracker.sessions.get(sessionId)
      const usage =
        (hasMeasurableUsage(event.usage) ? event.usage : null) ??
        (bucket?.lastHeartbeat && hasMeasurableUsage(bucket.lastHeartbeat) ? bucket.lastHeartbeat : null) ??
        (tracker.salvage && (tracker.salvage.session_id === sessionId || tracker.salvage.session_id == null)
          ? tracker.salvage.usage
          : null)
      // bucket facts remembered even when there is nothing to settle
      if (event.profile || known?.profile || bucket?.profile) {
        tracker.sessions.set(sessionId, {
          model: known?.model ?? bucket?.model ?? null,
          profile: event.profile ?? known?.profile ?? bucket?.profile ?? null,
        })
      }
      tracker.turns.delete(sessionId)

      const afterReconnect = tracker.reconnecting === true
      const payload = {
        session_id: sessionId,
        profile: resolveProfile(event, meta, sessionId) ?? null,
        model: resolveModel(tracker, event, meta, sessionId),
        usage: usage ?? null,
        received_at: meta.receivedAt ?? null,
        status: payloadStatus(event),
        after_reconnect: afterReconnect,
        replayed: event.replayed === true,
        usage_source: hasMeasurableUsage(event.usage)
          ? 'complete'
          : usage
            ? (bucket?.lastHeartbeat === usage ? 'heartbeat' : 'focused')
            : null,
      }
      if (usage) {
        // only a settle that actually carries usage consumes the reconnect flag
        tracker.reconnecting = false
        tracker.salvage = null
        return payload
      }
      return null // nothing measurable: no payload, no flag consumption
    }
    default:
      return null // STREAM_TICK / TOOL_ACTIVITY / ERROR / ... never settle
  }
}
