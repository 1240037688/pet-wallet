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
import { DEFAULT_GREETING, DEFAULT_IDLE_LINES, DEFAULT_TURN_COST } from './bubble/defaults.js'

export const $whale = atom({ mood: 'idle', clickCount: 0, waiting: null })
export const $bubble = atom(null)

export function createWhaleController({
  now = () => Date.now(),
  turnCostTtlMs = 5000,
  turnCostEnabled = true,
} = {}) {
  const machine = createWhaleState({ now })
  const queue = createBubbleQueue({ now })
  const resolver = createResolver()
  const publish = () => {
    $whale.set(machine.snapshot())
    $bubble.set(queue.view())
  }

  publish()

  return {
    $whale,
    $bubble,

    press() {
      machine.press()
      publish()
    },

    release() {
      machine.release()
      publish()
    },

    /** Click: first tap opens the greeting sequence, taps advance it; a
     *  ≥4 combo (DSH §B easter-egg zone) drops a random idle line. */
    click() {
      const { clickCount } = machine.click()
      if (clickCount === 1) {
        queue.show({ key: 'greeting', kind: 'info', def: DEFAULT_GREETING, data: {}, ttlMs: 12_000 })
      } else if (clickCount >= 4) {
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
