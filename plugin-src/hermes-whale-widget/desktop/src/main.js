/**
 * Whale Widget — desktop half entry (M1).
 *
 * register(ctx) wires the M1 usage-capture pipeline (IMPLEMENTATION_PLAN M1):
 *   - subscribes the accounting-relevant gateway events via ctx.onEvent
 *     (register-time subscriptions are retired with the plugin);
 *   - normalizer → turn tracker ((session, turn) bucketing, turn-end settle);
 *   - settled turns POST /ingest/turn through the ingest client (bounded
 *     retry, in-memory dead letter, pause during gateway.reconnecting);
 *   - host.state.focusedUsage is captured as the reconnect/missing-usage
 *     salvage snapshot (display-grade; the ledger stays Python-side);
 *   - the statusbar chip surfaces dashboard connectivity + ledger availability.
 *
 * JS NEVER persists anything (AGENTS.md §8): no ctx.storage writes for
 * accounting, no timers beyond the health poll.
 *
 * Build: source of `desktop/plugin.js` (single-file ESM). Import whitelist is
 * exactly `@hermes/plugin-sdk` + `react` / `react/jsx-runtime` (Hermes
 * runtime-loader rule — IMPLEMENTATION_PLAN §3.3). No JSX syntax: explicit
 * jsx() calls keep the artifact transform-free (ai-usage-tracker style).
 */
import { STATUSBAR_AREAS, atom, host } from '@hermes/plugin-sdk'
import { jsx } from 'react/jsx-runtime'
import { renderWhaleChip } from './ui/statusbar.js'
import { createNormalizer } from './core/normalize.js'
import {
  applyFocusedUsage,
  createTurnTracker,
  ingestWhaleEvent,
  markReconnecting,
  markReconnected,
} from './core/turn-tracker.js'
import { createIngestClient } from './core/ingest-client.js'

const ID = 'whale-widget'

// Chip-visible connectivity state: { state: 'checking'|'ok'|'unreachable', version, schema_version, detail }
export const $health = atom({ state: 'checking', version: null, schema_version: null, detail: null })
// Chip-visible ledger/ingest state: { unavailable, queued, deadLetters, dropped }
export const $ingest = atom({ unavailable: false, queued: 0, deadLetters: 0, dropped: 0 })

const HEALTH_POLL_MS = 60_000

// Accounting-relevant event surface (M1). tool.*/approval/notification events
// join in M6/M8; every subscribed-but-unmapped event is counted by the
// normalizer as dropped-unknown (never silently ignored).
export const SUBSCRIBED_EVENTS = [
  'message.start',
  'session.usage',
  'message.complete',
  'session.info',
  'gateway.reconnecting',
  'gateway.ready',
  'error',
]

export async function probeHealth(ctx) {
  try {
    const data = await ctx.rest('/health')
    $health.set({
      state: data && data.ok ? 'ok' : 'degraded',
      version: data?.version ?? null,
      schema_version: data?.schema_version ?? null,
      detail: data?.ledger_error ?? null,
    })
  } catch (err) {
    $health.set({ state: 'unreachable', version: null, schema_version: null, detail: String(err?.message || err || 'unknown') })
  }
}

function publishIngestStats(client) {
  const s = client.stats()
  $ingest.set({ unavailable: s.unavailable, queued: s.queued, deadLetters: s.deadLetters, dropped: s.dropped })
}

export default {
  id: ID,
  name: 'Whale Widget',

  register(ctx) {
    const normalizer = createNormalizer()
    const tracker = createTurnTracker()

    // ctx.rest adapter — POST shape (method/body JSON) mirrors the fetch-style
    // opts bag; exact production shape re-verified at the M5 real-machine smoke.
    const client = createIngestClient({
      rest: (path, body) => ctx.rest(path, { method: 'POST', body: JSON.stringify(body) }),
      onUnavailable: () => publishIngestStats(client),
      onRecovered: () => publishIngestStats(client),
      onStats: () => publishIngestStats(client),
    })

    const captureFocusedSalvage = () => {
      const focusedUsage = host.state?.focusedUsage ?? null
      const sessionId = host.state?.focusedSessionId ?? null
      if (focusedUsage) applyFocusedUsage(tracker, focusedUsage, { sessionId })
    }

    const handleGatewayEvent = (raw) => {
      const events = normalizer.normalize(raw)
      if (events.length === 0) return
      const meta = {
        receivedAt: Date.now(),
        model: host.state?.model ?? null,
        profile: raw?.profile ?? host.state?.profile ?? null,
      }
      for (const event of events) {
        if (event.kind === 'CONNECTION_CHANGED') {
          if (event.phase === 'reconnecting') {
            markReconnecting(tracker)
            captureFocusedSalvage()
            client.pause()
          } else if (event.phase === 'ready') {
            markReconnected(tracker)
            captureFocusedSalvage()
            client.resume()
          }
          continue
        }
        const payload = ingestWhaleEvent(tracker, event, meta)
        if (payload) client.submitTurn(payload)
      }
      publishIngestStats(client)
    }

    // ── event surface: register-time subscriptions, retired with the plugin ──
    try {
      for (const type of SUBSCRIBED_EVENTS) ctx.onEvent?.(type, handleGatewayEvent)
    } catch {
      /* event surface unavailable (e.g. preview shim) — chip still works */
    }

    // ── health probe: immediate + 60s poll, cleaned up on dispose ──────────
    void probeHealth(ctx)
    const timer = setInterval(() => void probeHealth(ctx), HEALTH_POLL_MS)
    try {
      ctx.onDispose?.(() => clearInterval(timer))
    } catch {
      /* shim without onDispose; interval dies with the preview page */
    }

    // ── contributions ──────────────────────────────────────────────────────
    ctx.register({
      id: 'chip',
      area: STATUSBAR_AREAS.right,
      order: 126,
      render: () => renderWhaleChip($health, $ingest),
    })

    // M1 self-check toast (replaces the M0 placeholder toast)
    try {
      host.notify?.({ message: 'Whale widget loaded (M1: usage capture → ledger ingest)' })
    } catch {
      /* toast is best-effort */
    }
  },
}
