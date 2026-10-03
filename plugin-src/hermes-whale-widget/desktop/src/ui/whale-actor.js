/**
 * Whale actor (M5/M6) — renders the mood state machine's snapshot as a
 * placeholder whale (inline SVG, self-made — DSH assets are NOT licensed for
 * reuse, AGENTS.md §1; M10 replaces this with the produced character pack).
 *
 * Mood → visual (product behaviour, DSH §B):
 *   idle    calm bob; press squashed scale; happy jump+smile; money sparkle;
 *   waiting tilted with a "?" badge. All CSS transitions, zero timers here.
 */
import { jsx } from 'react/jsx-runtime'

export const WHALE_STATES = ['idle', 'press', 'happy', 'money', 'waiting']

const MOOD_STYLE = {
  idle: { transform: 'translateY(0px) scale(1)', filter: 'none' },
  press: { transform: 'translateY(2px) scale(0.92, 0.86)', filter: 'brightness(0.95)' },
  happy: { transform: 'translateY(-4px) scale(1.04)', filter: 'brightness(1.06)' },
  money: { transform: 'translateY(-2px) scale(1.02)', filter: 'saturate(1.35) brightness(1.05)' },
  waiting: { transform: 'rotate(-6deg) scale(1)', filter: 'none' },
}

const MOOD_BADGE = { idle: null, press: null, happy: '✓', money: '¥', waiting: '?' }

export function whaleTransform(mood) {
  const s = MOOD_STYLE[mood] ?? MOOD_STYLE.idle
  return { transform: s.transform, filter: s.filter }
}

export function whaleBadge(mood) {
  return MOOD_BADGE[mood] ?? null
}

/** Placeholder whale — one compact SVG, colour-shifted per mood. */
export function WhaleActor({ mood = 'idle', size = 84, onPress, onRelease, onClick }) {
  const fill = mood === 'money' ? '#5aa8e8' : mood === 'happy' ? '#4fa3e3' : mood === 'waiting' ? '#7f9db8' : '#68a5dd'
  const badge = whaleBadge(mood)
  return jsx('div', {
    className: `whale-actor whale-${mood}`,
    role: 'button',
    tabIndex: 0,
    onPointerDown: onPress,
    onPointerUp: onRelease,
    onClick,
    style: {
      position: 'relative',
      width: size,
      height: size * 0.72,
      cursor: 'grab',
      userSelect: 'none',
      transition: 'transform 160ms cubic-bezier(.34,1.56,.64,1), filter 160ms ease',
      ...whaleTransform(mood),
    },
    children: [
      jsx('svg', {
        key: 'svg',
        viewBox: '0 0 100 72',
        width: '100%',
        height: '100%',
        children: [
          jsx('ellipse', { key: 'body', cx: '48', cy: '42', rx: '44', ry: '26', fill }),
          jsx('path', { key: 'tail', d: 'M88 40 Q 100 28 96 14 Q 88 30 78 34 Z', fill }),
          jsx('path', { key: 'fin', d: 'M40 46 Q 52 58 62 48 Q 52 44 40 46 Z', fill: '#3d7fb8' }),
          jsx('circle', { key: 'eye', cx: '26', cy: '36', r: '3.2', fill: '#0d2b45' }),
          jsx('path', {
            key: 'mouth',
            d: mood === 'happy' ? 'M14 44 Q 22 52 30 44' : 'M16 46 Q 22 50 28 46',
            stroke: '#0d2b45',
            strokeWidth: '2',
            fill: 'none',
            strokeLinecap: 'round',
          }),
          jsx('path', { key: 'spout', d: 'M30 14 Q 34 6 40 10', stroke: '#9ed0f2', strokeWidth: '3', fill: 'none', strokeLinecap: 'round' }),
        ],
      }),
      badge
        ? jsx('div', {
            key: 'badge',
            style: {
              position: 'absolute',
              top: -6,
              right: -6,
              width: 18,
              height: 18,
              borderRadius: '50%',
              background: mood === 'waiting' ? '#e8a13a' : '#3f97de',
              color: '#fff',
              fontSize: 12,
              lineHeight: '18px',
              textAlign: 'center',
              fontWeight: 700,
            },
            children: badge,
          })
        : null,
    ],
  })
}
