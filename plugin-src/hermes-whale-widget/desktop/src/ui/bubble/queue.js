/**
 * Bubble queue (M7) — the page-level system bubble priority queue ([DSH] D:
 * reminders ride the SAME bubble surface; no OS notifications in Phase 1).
 *
 * Ranks (lower = more urgent; DSH §D):
 *   1 budget  2 balance_low  3 turn_cost (LIFO-topped)  4 waiting (ttl=0,
 *   sticky, preempts)  5 info (click sequences, greetings).
 *
 * Semantics: show() stores by dedup key (same key replaces, never
 * duplicates); waiting rank preempts the visible bubble; ttl expiry via the
 * injectable clock; advance() walks tapAdvance definitions; dismiss()
 * removes. The queue never fires sounds/network — that's main.js's job.
 */

export const RANKS = { budget: 1, balance_low: 2, turn_cost: 3, waiting: 4, info: 5 }

export function createBubbleQueue({ now = () => Date.now() } = {}) {
  /** @type {Map<string, {key, rank, def, data, ttl_ms, sticky, shown_at, stepIndex}>} */
  let items = new Map()

  function sweep(ts) {
    items = new Map(
      [...items].filter(([, it]) => it.sticky || it.ttl_ms === 0 || ts < it.shown_at + it.ttl_ms),
    )
  }

  function topItem(ts) {
    sweep(ts)
    let best = null
    for (const it of items.values()) {
      if (!best || it.rank < best.rank) best = it
    }
    return best
  }

  return {
    /**
     * Put/refresh a bubble. `def` is a validated Bubble definition; `data`
     * the resolver snapshot; `ttlMs=0` + `sticky` = persists until dismissed.
     */
    show({ key, kind = 'info', def, data = {}, ttlMs = 5000, sticky = false }) {
      const rank = RANKS[kind] ?? RANKS.info
      const existed = items.get(key)
      items.set(key, {
        key,
        rank,
        kind,
        def,
        data,
        ttl_ms: sticky ? 0 : ttlMs,
        sticky: sticky || kind === 'waiting',
        shown_at: existed ? existed.shown_at : now(),
        stepIndex: existed ? existed.stepIndex : 0,
      })
      return this.view()
    },

    /** Tap advance on the visible bubble (tapAdvance definitions only). */
    advance() {
      const ts = now()
      const top = topItem(ts)
      if (!top || !top.def?.tapAdvance) return null
      top.stepIndex = (top.stepIndex + 1) % top.def.items.length
      top.shown_at = ts // re-arm ttl per page
      return this.view()
    },

    /** Dismiss by key (or the visible one when key omitted). */
    dismiss(key) {
      const ts = now()
      if (key === undefined) {
        const top = topItem(ts)
        if (top) items.delete(top.key)
      } else {
        items.delete(key)
      }
      return this.view()
    },

    /** Current visible render input: {key, kind, rank, step, stepIndex} | null. */
    view() {
      const ts = now()
      const top = topItem(ts)
      if (!top) return null
      return { key: top.key, kind: top.kind, rank: top.rank, stepIndex: top.stepIndex, def: top.def, data: top.data }
    },

    /** All pending (dismiss/observe surface; tests). */
    pending() {
      sweep(now())
      return [...items.values()].map(({ key, kind, rank }) => ({ key, kind, rank }))
    },

    clear() {
      items = new Map()
    },
  }
}
