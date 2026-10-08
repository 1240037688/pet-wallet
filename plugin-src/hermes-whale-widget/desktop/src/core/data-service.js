/**
 * Data service (M5) — the pane's single polling surface over the Python half.
 *
 * Discipline (AGENTS.md §8):
 *   - two timers TOTAL (balance / summary), intervals from /config with sane
 *     bounds; USAGE_UPDATED events trigger one immediate summary refresh
 *     (coalesced) instead of extra timers;
 *   - REST failures are DATA (they surface via /balance five-state); a fully
 *     unreachable Python half flips $dashboard.state='unreachable' so the
 *     pane can fall back to the focusedUsage salvage view;
 *   - JS never persists any of this.
 */
import { atom } from '@hermes/plugin-sdk'

export const BALANCE_FLOOR_MS = 15_000
export const BALANCE_CEIL_MS = 600_000
export const SUMMARY_FLOOR_MS = 10_000
export const SUMMARY_CEIL_MS = 300_000

export const $balance = atom(null) // GET /balance payload as-is
export const $summary = atom(null) // GET /usage/summary payload as-is
export const $dashboard = atom({ state: 'checking', detail: null })

const clamp = (n, lo, hi) => Math.min(Math.max(n, lo), hi)

export function createDataService({ rest, now = () => Date.now(), getScope = () => '' } = {}) {
  let balanceTimer = null
  let summaryTimer = null
  let lastSummaryRefresh = 0
  let disposed = false
  const SUMMARY_COALESCE_MS = 2_000

  async function refreshBalance() {
    if (disposed) return
    const scope = getScope()
    try {
      const data = await rest('/balance')
      if (disposed || scope !== getScope()) return
      $balance.set(data ?? null)
      $dashboard.set({ state: 'ok', detail: null })
    } catch (err) {
      if (disposed || scope !== getScope()) return
      $dashboard.set({ state: 'unreachable', detail: String(err?.message || err || 'unknown') })
    }
  }

  async function refreshSummary() {
    if (disposed) return
    const scope = getScope()
    lastSummaryRefresh = now()
    try {
      const data = await rest('/usage/summary')
      if (disposed || scope !== getScope()) return
      $summary.set(data ?? null)
      $dashboard.set({ state: 'ok', detail: null })
    } catch (err) {
      if (disposed || scope !== getScope()) return
      $dashboard.set({ state: 'unreachable', detail: String(err?.message || err || 'unknown') })
    }
  }

  return {
    /** Start polling (idempotent); intervals re-read from config each cycle. */
    start(config = {}) {
      if (disposed) return
      const balanceMs = clamp(Number(config.balance_poll_seconds ?? 60) * 1000, BALANCE_FLOOR_MS, BALANCE_CEIL_MS)
      const summaryMs = clamp(Number(config.usage_summary_poll_seconds ?? 30) * 1000, SUMMARY_FLOOR_MS, SUMMARY_CEIL_MS)
      if (balanceTimer === null) {
        void refreshBalance()
        balanceTimer = setInterval(() => void refreshBalance(), balanceMs)
      }
      if (summaryTimer === null) {
        void refreshSummary()
        summaryTimer = setInterval(() => void refreshSummary(), summaryMs)
      }
    },

    /** USAGE_UPDATED hook: immediate, coalesced summary refresh. */
    pokeSummary() {
      if (summaryTimer !== null && now() - lastSummaryRefresh >= SUMMARY_COALESCE_MS) {
        void refreshSummary()
      }
    },

    stop() {
      disposed = true
      if (balanceTimer) clearInterval(balanceTimer)
      if (summaryTimer) clearInterval(summaryTimer)
      balanceTimer = summaryTimer = null
    },

    /** Test seam. */
    _refreshers: { refreshBalance, refreshSummary },
  }
}
