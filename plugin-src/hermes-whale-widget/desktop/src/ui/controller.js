/**
 * Pane controller (M5/M6/M7 glue) — wires the mood machine, bubble queue and
 * event stream into atoms the WhalePane subscribes to. Pure logic lives in
 * core/whale-state.js + ui/bubble/*; this file only orchestrates, so tests
 * drive it with an injected clock and a fake event source.
 */
import { atom } from '@hermes/plugin-sdk'
import { createWhaleState } from '../core/whale-state.js'
import { createBubbleQueue } from './bubble/queue.js'
import { createResolver } from './bubble/resolver.js'
import { formatMoney } from '../core/money.js'
import {
  DEFAULT_GREETING,
  DEFAULT_IDLE_LINES,
  DEFAULT_TURN_COST,
  DEFAULT_BUDGET_REACHED,
  DEFAULT_BALANCE_LOW,
} from './bubble/defaults.js'

// Server notification kinds surfaced as bubbles; wait_input/wait_approval are
// owned by the /wait-state chain (syncWaiting) and MUST be skipped here to
// avoid double display (Goal-pass P0-2).
const NOTIFICATION_KINDS = { budget: 'budget', balance_low: 'balance_low', turn_cost: 'turn_cost' }

export const $whale = atom({ mood: 'idle', clickCount: 0, waiting: null })
export const $bubble = atom(null)

function notificationData(kind, payload) {
  const currency = typeof payload.currency === 'string' && payload.currency !== 'none' ? payload.currency : null
  const units = (v) => (Number.isFinite(v) ? formatMoney(v, { currency }) : null)
  switch (kind) {
    case 'budget':
      return {
        estimated_today_text: units(payload.estimated_cost_units),
        session_name: payload.day ?? null,
        balance_text: null,
        turn_cost_text: null,
      }
    case 'balance_low':
      return {
        balance_text: units(payload.observed_balance_units),
        estimated_today_text: null,
        session_name: payload.day ?? null,
        turn_cost_text: null,
      }
    default:
      return {
        turn_cost_text: units(payload.estimated_cost_units),
        balance_text: null,
        estimated_today_text: null,
        session_name: payload.model ?? null,
      }
  }
}

export function createWhaleController({
  now = () => Date.now(),
  turnCostTtlMs = 5000,
  turnCostEnabled = true,
} = {}) {
  const machine = createWhaleState({ now })
  const queue = createBubbleQueue({ now })
  const resolver = createResolver()
  let soundSink = null
  let lastWaiting = null // 'question' | 'approval' | null (transition detection for sounds)
  const standingNotifKeys = new Set() // balance_low/budget keys currently queued
  const publish = () => {
    $whale.set(machine.snapshot())
    $bubble.set(queue.view())
  }

  publish()

  return {
    $whale,
    $bubble,

    /** Optional sound sink (M9): {press, release, play(event)}. */
    attachSound(sink) {
      soundSink = sink
    },

    press() {
      machine.press()
      try {
        soundSink?.press?.()
      } catch { /* audio is cosmetic */ }
      publish()
    },

    release() {
      machine.release()
      try {
        soundSink?.release?.()
      } catch { /* audio is cosmetic */ }
      publish()
    },

    /** Click: first tap opens the greeting sequence, taps advance it; a
     *  ≥4 combo (DSH §B easter-egg zone) drops a random idle line — the
     *  greeting is dismissed first so the same-rank idle line is visible. */
    click() {
      const { clickCount } = machine.click()
      if (clickCount === 1) {
        queue.show({ key: 'greeting', kind: 'info', def: DEFAULT_GREETING, data: {}, ttlMs: 12_000 })
      } else if (clickCount >= 4) {
        queue.dismiss('greeting')
        queue.show({ key: 'idle-line', kind: 'info', def: DEFAULT_IDLE_LINES, data: {}, ttlMs: 6_000 })
      } else {
        queue.advance()
      }
      publish()
      return clickCount
    },

    /** Normalized whale event → mood + bubble side effects. */
    event(kind, payload = {}) {
      machine.event(kind)
      if (kind === 'TASK_COMPLETED') {
        queue.show({ key: 'task-done', kind: 'info', def: DEFAULT_IDLE_LINES, data: {}, ttlMs: 4_000 })
        try {
          soundSink?.play?.('task_finished')
        } catch { /* audio is cosmetic */ }
      }
      publish()
      return machine.snapshot()
    },

    /** Turn settled (from the tracker): per-turn cost bubble, if enabled. */
    turnSettled(turnPayload) {
      if (!turnCostEnabled) return
      const data = {
        turn_cost_text: turnPayload?.estimated_cost_text ?? '—',
        session_name: turnPayload?.session_id ?? null,
      }
      queue.show({ key: `turn:${turnPayload?.dedup_key ?? 'unknown'}`, kind: 'turn_cost', def: DEFAULT_TURN_COST, data, ttlMs: turnCostTtlMs })
      publish()
    },

    /** Wait-state sync (M8 /wait-state poll): sticky waiting bubbles. */
    syncWaiting({ question, approval }) {
      if (question) {
        queue.show({ key: 'wait:question', kind: 'waiting', def: DEFAULT_TURN_COST, data: { turn_cost_text: '在等你回答问题 ✋' }, ttlMs: 0 })
        machine.event('USER_INPUT_REQUIRED')
      }
      if (approval) {
        queue.show({ key: 'wait:approval', kind: 'waiting', def: DEFAULT_TURN_COST, data: { turn_cost_text: '有一个操作等待你批准 ⚠' }, ttlMs: 0 })
        machine.event('APPROVAL_REQUIRED')
      }
      if (!question && !approval) {
        queue.dismiss('wait:question')
        queue.dismiss('wait:approval')
        machine.event('APPROVAL_CLEARED')
      }
      // first-appearance sounds (waiting → sticky, so transition-detect)
      const nowWaiting = question ? 'question' : approval ? 'approval' : null
      if (nowWaiting && nowWaiting !== lastWaiting) {
        try {
          soundSink?.play?.(nowWaiting)
        } catch { /* audio is cosmetic */ }
      }
      lastWaiting = nowWaiting
      publish()
    },

    /** Rules-engine notifications (Goal pass P0-2): GET /notifications items →
     *  bubbles. wait_* kinds are skipped (the wait-state chain owns them);
     *  standing alerts (ttl 0) that recovered server-side are dismissed. */
    syncNotifications(items) {
      if (!Array.isArray(items)) return
      const seen = new Set()
      for (const n of items) {
        if (!n || typeof n !== 'object' || typeof n.dedup_key !== 'string') continue
        const kind = NOTIFICATION_KINDS[n.kind]
        if (!kind) continue
        seen.add(n.dedup_key)
        const ttl = Number(n.ttl_ms)
        queue.show({
          key: n.dedup_key,
          kind,
          def: kind === 'budget' ? DEFAULT_BUDGET_REACHED : kind === 'balance_low' ? DEFAULT_BALANCE_LOW : DEFAULT_TURN_COST,
          data: notificationData(kind, n.payload ?? {}),
          ttlMs: Number.isFinite(ttl) && ttl > 0 ? ttl : 5000,
          sticky: Number.isFinite(ttl) && ttl === 0,
        })
      }
      // standing alerts no longer pending server-side (recovered/renewed) → drop
      for (const key of [...standingNotifKeys]) {
        if (!seen.has(key)) {
          queue.dismiss(key)
          standingNotifKeys.delete(key)
        }
      }
      for (const key of seen) standingNotifKeys.add(key)
      publish()
    },

    /** Balance/summary snapshot → resolver data (— semantics in resolver). */
    setData({ balanceText, todayText, estimatedTodayText, turnCostText, sessionName } = {}) {
      this._data = { balance_text: balanceText ?? null, today_text: todayText ?? null, estimated_today_text: estimatedTodayText ?? null, turn_cost_text: turnCostText ?? null, session_name: sessionName ?? null }
    },

    /** Periodic settle (main.js interval). */
    tick() {
      publish()
      return machine.snapshot()
    },
  }
}
