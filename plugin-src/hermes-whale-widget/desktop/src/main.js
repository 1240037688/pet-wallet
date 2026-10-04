/**
 * Whale Widget — desktop half entry (M1 pipeline + M5/M6/M7/M8-A wiring).
 *
 * Pet hosting (架构修订 DR-15): the whale CHARACTER is Hermes' built-in pet
 * wearing our whale skin pack (docs/research/HERMES_PET_SYSTEM.md — the only
 * legal integration surface is the skin-pack file; the plugin SDK exports no
 * pet API). The floating pane below is de-roled into the 鲸鱼管家 ledger panel
 * (whale-actor.js retired): bubbles + data card + mood accent, dragged next to
 * the pet. Nothing in this file renders a character.
 *
 * register(ctx) wires:
 *   - the M1 usage-capture pipeline: normalizer → turn tracker ((session,
 *     turn) bucketing, turn-end settle) → POST /ingest/turn (bounded retry,
 *     in-memory dead letter, pause during gateway.reconnecting);
 *   - the M5 floating pane (area 'panes', placement floating, native drag)
 *     rendering WhalePane over the data-service atoms ($balance/$summary/
 *     $dashboard) and the controller atoms ($whale/$bubble); the statusbar
 *     chip stays as the connectivity/ledger surface;
 *   - M6 mood: every mood-relevant normalized event (TASK_COMPLETED /
 *     USAGE_UPDATED / ERROR / APPROVAL_CLEARED) is forwarded to the whale
 *     controller synchronously — everything else is mood-neutral;
 *   - M7 turn-cost bubbles: the ingest response MAY carry per-turn settled
 *     costs (WP-2 contract `settled: [{dedup_key, estimated_cost_units,
 *     currency, cost_basis}]`); consumed defensively — a missing array keeps
 *     the behaviour identical to before (onSettled hook in ingest-client);
 *   - M8-A clarify wait bridge: tool.start/tool.complete named 'clarify' are
 *     forwarded to POST /ingest/wait-event (fire-and-forget, silent failure —
 *     the wait bridge must never affect accounting);
 *   - M8 wait-state poll (10s, same timer as controller.tick()): GET
 *     /wait-state → controller.syncWaiting; endpoint failure/404 means "no
 *     waiting" (WP-2 may not be deployed yet — defensive by design);
 *   - host.state.focusedUsage is captured as the reconnect/missing-usage
 *     salvage snapshot (display-grade; the ledger stays Python-side).
 *
 * JS NEVER persists anything (AGENTS.md §8): no ctx.storage writes for
 * accounting, no timers beyond the health poll + the single UI poll.
 *
 * Build: source of `desktop/plugin.js` (single-file ESM). Import whitelist is
 * exactly `@hermes/plugin-sdk` + `react` / `react/jsx-runtime` (Hermes
 * runtime-loader rule — IMPLEMENTATION_PLAN §3.3). No JSX syntax: explicit
 * jsx() calls keep the artifact transform-free (ai-usage-tracker style).
 */
import { STATUSBAR_AREAS, PANES_AREA, atom, host } from '@hermes/plugin-sdk'
import { jsx } from 'react/jsx-runtime'
import { renderWhaleChip } from './ui/statusbar.js'
import { WhalePane, PANE_ID } from './ui/whale-pane.js'
import { createWhaleController, $whale, $bubble } from './ui/controller.js'
import { createDataService, $balance, $summary, $dashboard } from './core/data-service.js'
import { formatMoney } from './core/money.js'
import { CLARIFY_TOOL_NAME } from './core/wait-events.js'
import { createNormalizer } from './core/normalize.js'
import {
  applyFocusedUsage,
  createTurnTracker,
  ingestWhaleEvent,
  markReconnecting,
  markReconnected,
} from './core/turn-tracker.js'
import { createIngestClient } from './core/ingest-client.js'
import { createSoundEngine } from './sound/engine.js'

// Re-exported for preview/tests: the pane's whale, bubble and data atoms.
export { $whale, $bubble }
export { $balance, $summary, $dashboard }

const ID = 'whale-widget'

// Chip-visible connectivity state: { state: 'checking'|'ok'|'unreachable', version, schema_version, detail }
export const $health = atom({ state: 'checking', version: null, schema_version: null, detail: null })
// Chip-visible ledger/ingest state: { unavailable, queued, deadLetters, dropped }
export const $ingest = atom({ unavailable: false, queued: 0, deadLetters: 0, dropped: 0 })

const HEALTH_POLL_MS = 60_000
const WAIT_POLL_MS = 10_000 // wait-state poll + controller.tick share one timer

const INGEST_WAIT_EVENT_PATH = '/ingest/wait-event'
const WAIT_STATE_PATH = '/wait-state'
const NOTIFICATIONS_PATH = '/notifications'

// Mirror of whale_core.config.DEFAULTS (only the keys the JS half consumes).
// Used when GET /config fails — a dashboard outage must never break the UI.
const DEFAULT_UI_CONFIG = {
  balance_poll_seconds: 60,
  usage_summary_poll_seconds: 30,
  sound: { enabled: false, muted: false, volume_global: 100 },
}

// M6 mood surface: the ONLY normalized events that drive the mood machine
// (bubbles + the pane's accent dot — no rendered face, DR-15 de-roling).
// USER_INPUT_REQUIRED/APPROVAL_REQUIRED arrive via the /wait-state poll
// (syncWaiting), not from gateway events; STREAM_TICK/TOOL_ACTIVITY are
// mood-neutral by design (animation discipline, [AUDIT] §12).
const MOOD_EVENTS = new Set(['TASK_COMPLETED', 'USAGE_UPDATED', 'ERROR', 'APPROVAL_CLEARED'])

// Accounting + tool-surface events. tool.start/tool.complete join in M8-A for
// the clarify wait bridge (forwarding is name-gated inside the handler).
export const SUBSCRIBED_EVENTS = [
  'message.start',
  'session.usage',
  'message.complete',
  'session.info',
  'tool.start',
  'tool.complete',
  'gateway.reconnecting',
  'gateway.ready',
  'error',
]

/** GET /config → UI-relevant config; any failure falls back to defaults. */
async function loadUiConfig(rest) {
  try {
    const data = await rest('/config')
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      return { ...DEFAULT_UI_CONFIG, ...data }
    }
  } catch {
    /* defaults below — dashboard down must not break the pane */
  }
  return { ...DEFAULT_UI_CONFIG }
}

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

/**
 * Ingest response `settled: [...]` → controller.turnSettled (per-turn cost
 * bubble). Defensive field-by-field: anything missing degrades to the money
 * display rules (null → `—`, never a fabricated 0). session_id is taken from
 * the settled item when provided, else from the batch when it holds exactly
 * one turn (the dedup_key itself is computed Python-side and cannot be
 * matched back to a batch entry JS-side).
 */
function handleSettledResults(controller, results, batchTurns) {
  if (!Array.isArray(results)) return
  for (const item of results) {
    if (!item || typeof item !== 'object') continue
    const units = Number.isFinite(item.estimated_cost_units) ? item.estimated_cost_units : null
    // 'none' is the Python-side placeholder currency (M2 convention) — display as null
    const currency = typeof item.currency === 'string' && item.currency !== 'none' ? item.currency : null
    const batchSession =
      Array.isArray(batchTurns) && batchTurns.length === 1 ? batchTurns[0]?.session_id ?? null : null
    try {
      controller.turnSettled({
        dedup_key: typeof item.dedup_key === 'string' ? item.dedup_key : null,
        estimated_cost_text: formatMoney(units, { currency }),
        session_id: typeof item.session_id === 'string' ? item.session_id : batchSession,
      })
    } catch {
      /* a bubble must never break the ingest pipeline */
    }
  }
}

/**
 * M9 wiring (Goal pass P1-1): build the sound sink from config. Inert until
 * clips exist (setClip/sound groups, M10 assets); a missing AudioContext
 * (preview/node) or any construction failure keeps the widget fully usable.
 * Volume input is 0..100 (config scale); the engine clamps 0..1.
 */
function attachSoundEngine(controller, sound = {}) {
  if (typeof AudioContext !== 'function') return null
  const engine = createSoundEngine({
    contextFactory: () => new AudioContext({ latencyHint: 'interactive' }),
    now: () => Date.now(),
    fetchClip: async (url) => {
      const res = await fetch(url)
      if (!res.ok) return null
      return await res.arrayBuffer()
    },
  })
  engine.setMuted(sound.muted === true)
  const vol = Number(sound.volume_global)
  engine.setVolume('global', Number.isFinite(vol) ? vol / 100 : 1, { explicit: true })
  controller.attachSound(engine)
  return engine
}

export default {
  id: ID,
  name: 'Whale Widget',
  register(ctx) {
    const normalizer = createNormalizer()
    const tracker = createTurnTracker()

    // ctx.rest adapter — POST shape (method/body JSON) mirrors the fetch-style
    // opts bag; exact production shape re-verified at the M5 real-machine smoke.
    const restPost = (path, body) => ctx.rest(path, { method: 'POST', body: JSON.stringify(body) })

    const dataService = createDataService({ rest: (path) => ctx.rest(path) })
    const controller = createWhaleController()

    const client = createIngestClient({
      rest: restPost,
      onUnavailable: () => publishIngestStats(client),
      onRecovered: () => publishIngestStats(client),
      onStats: () => publishIngestStats(client),
      onSettled: (results, batchTurns) => handleSettledResults(controller, results, batchTurns),
    })

    const captureFocusedSalvage = () => {
      const focusedUsage = host.state?.focusedUsage ?? null
      const sessionId = host.state?.focusedSessionId ?? null
      if (focusedUsage) applyFocusedUsage(tracker, focusedUsage, { sessionId })
    }

    /** M8-A: clarify open/close → wait bridge. Silent by contract: a failing
     *  wait-event POST must never affect accounting (or anything else). */
    const forwardClarify = (event, raw) => {
      const phase = event.phase === 'complete' ? 'close' : 'open'
      const body = {
        kind: 'question',
        phase,
        tool_id: raw?.payload?.tool_id ?? raw?.payload?.toolId ?? null,
        session_id: event.session_id ?? null,
      }
      try {
        const pending = restPost(INGEST_WAIT_EVENT_PATH, body)
        void Promise.resolve(pending).catch(() => {}) // silent — best effort only
      } catch {
        /* silent — wait bridge must never break the event loop */
      }
    }

    /** M8 wait-state poll (REAL contract: {question_slots[], approval_slots[],
     *  fired_dedup_keys[]} — Goal-pass P0-1 fix: the previous `data?.slots`
     *  read never matched and silently disabled waiting). Slots present →
     *  sticky waiting bubble + mood; 404/failure → no waiting (defensive). */
    const pollWaitState = async () => {
      let question = false
      let approval = false
      try {
        const data = await ctx.rest(WAIT_STATE_PATH)
        question = Array.isArray(data?.question_slots) && data.question_slots.length > 0
        approval = Array.isArray(data?.approval_slots) && data.approval_slots.length > 0
      } catch {
        question = approval = false
      }
      try {
        controller.syncWaiting({ question, approval })
      } catch {
        /* UI must never break the poll loop */
      }
    }

    /** Goal-pass P0-2: rules-engine notifications → bubbles. The wait_*
     *  kinds are filtered controller-side (wait-state chain owns them);
     *  endpoint absence (older Python half) is tolerated silently. */
    const pollNotifications = async () => {
      try {
        const data = await ctx.rest(NOTIFICATIONS_PATH)
        controller.syncNotifications(data?.notifications)
      } catch {
        /* no consumer endpoint / transient failure — keep last known bubbles */
      }
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
        // M6: mood-relevant events drive the mood machine synchronously
        // (de-roled: mood surfaces as bubbles + the pane's accent dot)
        if (MOOD_EVENTS.has(event.kind)) {
          try {
            controller.event(event.kind)
          } catch {
            /* mood is cosmetic */
          }
        }
        // M8-A: clarify tool lifecycle → wait bridge (open on start, close on complete)
        if (
          event.kind === 'TOOL_ACTIVITY' &&
          event.name === CLARIFY_TOOL_NAME &&
          (event.phase === 'start' || event.phase === 'complete')
        ) {
          forwardClarify(event, raw)
        }
        const payload = ingestWhaleEvent(tracker, event, meta)
        if (payload) {
          client.submitTurn(payload)
          dataService.pokeSummary() // settled turn → coalesced summary refresh
        }
      }
      publishIngestStats(client)
    }

    // ── event surface: register-time subscriptions, retired with the plugin ──
    try {
      for (const type of SUBSCRIBED_EVENTS) ctx.onEvent?.(type, handleGatewayEvent)
    } catch {
      /* event surface unavailable (e.g. preview shim) — chip still works */
    }

    // ── timers: health probe (60s) + UI poll (10s: wait-state + tick) ───────
    void probeHealth(ctx)
    const timer = setInterval(() => void probeHealth(ctx), HEALTH_POLL_MS)

    try {
      controller.tick()
    } catch {
      /* cosmetic */
    }
    void pollWaitState()
    const uiTimer = setInterval(() => {
      try {
        controller.tick()
      } catch {
        /* cosmetic */
      }
      void pollWaitState()
      void pollNotifications()
    }, WAIT_POLL_MS)

    // ── data service: config-driven polling + optional sound engine ─────────
    void loadUiConfig((path) => ctx.rest(path)).then((config) => {
      dataService.start(config)
      try {
        const sound = config?.sound ?? {}
        if (sound.enabled) attachSoundEngine(controller, sound)
      } catch {
        /* audio is cosmetic — never blocks the widget */
      }
    }, () => dataService.start({ ...DEFAULT_UI_CONFIG }))

    try {
      ctx.onDispose?.(() => {
        clearInterval(timer)
        clearInterval(uiTimer)
        dataService.stop()
      })
    } catch {
      /* shim without onDispose; intervals die with the preview page */
    }

    // ── contributions ──────────────────────────────────────────────────────
    // M5 floating pane (SDK probe: PANES_AREA + placement floating → native
    // draggable card, viewport-clamped; no plugin-side dragging needed).
    // De-roled title: the pane is the 鲸鱼管家 ledger panel; the whale
    // CHARACTER itself is the Hermes built-in pet (DR-15).
    ctx.register({
      id: PANE_ID,
      area: PANES_AREA,
      title: 'Whale Wallet 管家',
      order: 0,
      data: { placement: 'floating', anchor: 'bottom-right', width: '280px' },
      render: () => jsx(WhalePane, { $balance, $summary, $dashboard, $whale, $bubble, controller }),
    })

    ctx.register({
      id: 'chip',
      area: STATUSBAR_AREAS.right,
      order: 126,
      render: () => renderWhaleChip($health, $ingest),
    })

    // self-check toast (M1 pipeline + M5/M6/M7/M8-A surface; DR-15 de-roling)
    try {
      host.notify?.({ message: 'Whale Wallet 管家已加载（角色 = Hermes 内置宠物；usage capture → ledger ingest + 随身账本面板）' })
    } catch {
      /* toast is best-effort */
    }
  },
}
