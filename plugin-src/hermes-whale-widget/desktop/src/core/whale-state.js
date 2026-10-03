/**
 * Whale mood state machine (M6) — pure, clock-injectable.
 *
 * Product behaviours modelled (DSH §B semantics, no DSH DOM hacks):
 *   - press / release: physical squash feedback while the pointer is down;
 *   - clicks inside CLICK_WINDOW_MS accumulate a combo (bubble sequences in
 *     M7 read the count);
 *   - TASK_COMPLETED  → brief `happy` mood;
 *   - USAGE_UPDATED   → brief `money` mood (only for turns with measurable
 *     usage — the tracker already filters);
 *   - USER_INPUT_REQUIRED / APPROVAL_REQUIRED raise a sticky `waiting` flag
 *     that outlives transient moods until the matching cleared event;
 *   - STREAM_TICK never touches the mood (animation discipline, [AUDIT] voice
 *     lessons: streaming tokens must not reset the actor);
 *   - transient moods auto-expire (injectable clock) back to idle/waiting.
 *
 * The machine holds NO side effects; main.js renders its snapshots.
 */

export const MOODS = ['idle', 'press', 'happy', 'money', 'waiting']

export const CLICK_WINDOW_MS = 1_200
export const TRANSIENT_MS = 2_500

export function createWhaleState({
  now = () => Date.now(),
  clickWindowMs = CLICK_WINDOW_MS,
  transientMs = TRANSIENT_MS,
} = {}) {
  let s = {
    mood: 'idle',
    clickCount: 0,
    lastClickAt: 0,
    transient: null, // { mood, until }
    waiting: null, // { kind: 'question'|'approval', since }
  }

  const settle = (ts) => {
    if (s.transient && ts >= s.transient.until) s.transient = null
    s.mood = s.transient
      ? s.transient.mood
      : s.waiting
        ? 'waiting'
        : 'idle'
  }

  return {
    /** Pointer down: physical press wins over everything but stays honest. */
    press() {
      const ts = now()
      settle(ts)
      s.mood = 'press'
      return snapshot(s)
    },

    release() {
      const ts = now()
      settle(ts)
      return snapshot(s)
    },

    /** Primary interaction: combo counting + immediate acknowledgement. */
    click() {
      const ts = now()
      s.clickCount = ts - s.lastClickAt <= clickWindowMs ? s.clickCount + 1 : 1
      s.lastClickAt = ts
      settle(ts)
      return { ...snapshot(s), clickCount: s.clickCount, combo: s.clickCount }
    },

    /** Normalized whale event in; returns the new snapshot. */
    event(kind) {
      const ts = now()
      switch (kind) {
        case 'TASK_COMPLETED':
          s.transient = { mood: 'happy', until: ts + transientMs }
          break
        case 'USAGE_UPDATED':
          s.transient = { mood: 'money', until: ts + transientMs }
          break
        case 'USER_INPUT_REQUIRED':
          s.waiting = { kind: 'question', since: ts }
          break
        case 'APPROVAL_REQUIRED':
          s.waiting = { kind: 'approval', since: ts }
          break
        case 'APPROVAL_CLEARED':
        case 'USER_INPUT_CLEARED':
          s.waiting = null
          break
        case 'ERROR':
          // an error clears waiting (the agent came back with something) but
          // has no mood of its own yet (M10 asset work)
          s.waiting = null
          break
        default:
          break // STREAM_TICK / TURN_STARTED / ... are mood-neutral
      }
      settle(ts)
      return snapshot(s)
    },

    /** Periodic settle (timers): expire transient, resolve waiting/idle. */
    tick() {
      const ts = now()
      settle(ts)
      return snapshot(s)
    },

    snapshot() {
      return snapshot(s)
    },
  }
}

function snapshot(s) {
  return { mood: s.mood, clickCount: s.clickCount, waiting: s.waiting ? s.waiting.kind : null }
}
