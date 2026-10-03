/**
 * Whale Widget — desktop half entry (M0 skeleton).
 *
 * Minimal register, per IMPLEMENTATION_PLAN M0 task 1:
 *   - statusbar chip placeholder (STATUSBAR_AREAS.right — the avatar_pet-verified
 *     combination; the floating pane proper arrives in M5 after the SDK probe);
 *   - ctx.rest health probe against the dashboard half
 *     (`/health` → /api/plugins/whale-widget/health — ctx.rest is
 *     namespace-relative BY CONSTRUCTION, apps/desktop/src/api/plugins.ts);
 *   - one self-check toast (host.notify);
 *   - a counting event subscription standing in for the M1 normalization
 *     pipeline (register-time subscriptions are retired with the plugin).
 *
 * Build: source of `desktop/plugin.js` (single-file ESM). Import whitelist is
 * exactly `@hermes/plugin-sdk` + `react` / `react/jsx-runtime` (Hermes
 * runtime-loader rule — IMPLEMENTATION_PLAN §3.3). No JSX syntax: explicit
 * jsx() calls keep the artifact transform-free (ai-usage-tracker style).
 */
import { STATUSBAR_AREAS, atom, host } from '@hermes/plugin-sdk'
import { jsx } from 'react/jsx-runtime'
import { renderWhaleChip } from './ui/statusbar.js'
import { normalizeEvent } from './core/normalize.js'

const ID = 'whale-widget'

// Chip-visible connectivity state: { state: 'checking'|'ok'|'unreachable', version, schema_version, detail }
export const $health = atom({ state: 'checking', version: null, schema_version: null, detail: null })

const HEALTH_POLL_MS = 60_000

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

export default {
  id: ID,
  name: 'Whale Widget',

  register(ctx) {
    // ── event surface: counting stand-in for the M1 normalization pipeline ──
    // M1 replaces this with normalizeEvent → ingest-client wiring; the
    // register-time subscription is retired automatically on unload.
    let eventCount = 0
    try {
      ctx.onEvent?.('*', (event) => {
        eventCount++
        // touch the normalizer so M1 wiring cannot rot silently (no-op result)
        if (event && typeof event === 'object') normalizeEvent(event)
      })
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
      render: () => renderWhaleChip($health),
    })

    // M0 self-check toast (IMPLEMENTATION_PLAN M0 task 1)
    try {
      host.notify?.({ message: 'Whale widget placeholder loaded (M0)' })
    } catch {
      /* toast is best-effort */
    }
  },
}
