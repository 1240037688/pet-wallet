/**
 * Pet interaction layer (DR-16) — pure-function coverage + fake-DOM smoke.
 *
 * The layer attaches whale-widget interaction to the Hermes BUILT-IN pet
 * (locator = official a11y `canvas[aria-label$=" pet"]`), tap-vs-drag
 * discrimination, and a follow-the-pet bubble host (raw DOM; react-dom is not
 * in the runtime import map).
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  isPetHit,
  isTap,
  locatePet,
  moduleCss,
  placeBubble,
  PET_CANVAS_SELECTOR,
  TAP_SLOP_PX,
} from '../src/ui/pet-layer.js'

// ── tap vs drag ────────────────────────────────────────────────────────────

test('isTap: stationary and small movements count as taps', () => {
  assert.equal(isTap({ x: 10, y: 10 }, { x: 10, y: 10 }), true)
  assert.equal(isTap({ x: 10, y: 10 }, { x: 13, y: 8 }), true)
  assert.equal(isTap({ x: 10, y: 10 }, { x: 10 + TAP_SLOP_PX, y: 10 }), true) // boundary inclusive
})

test('isTap: movement beyond slop is a drag (core owns pet dragging)', () => {
  assert.equal(isTap({ x: 10, y: 10 }, { x: 30, y: 10 }), false)
  assert.equal(isTap({ x: 10, y: 10 }, { x: 10, y: 10 + TAP_SLOP_PX + 1 }), false)
  assert.equal(isTap(null, { x: 1, y: 1 }), false)
})

// ── pet hit via composedPath ───────────────────────────────────────────────

test('isPetHit: true when the pet canvas is in the event path', () => {
  const canvas = { tag: 'canvas' }
  assert.equal(isPetHit([{ tag: 'div' }, canvas, { tag: 'body' }], canvas), true)
})

test('isPetHit: false for other targets and when no pet located', () => {
  assert.equal(isPetHit([{ tag: 'div' }], { tag: 'canvas' }), false)
  assert.equal(isPetHit([{ tag: 'div' }], null), false)
})

// ── bubble placement (follow-the-pet) ──────────────────────────────────────

test('placeBubble: centred above the pet', () => {
  const placement = placeBubble({ left: 100, top: 300, width: 80, height: 60 }, 200, 48, { width: 1200, height: 800 })
  assert.equal(placement.left, 40) // 100+40 - 100 = centre 140 - 100
  assert.equal(placement.top, 300 - 48 - 8)
})

test('placeBubble: clamped inside the viewport horizontally', () => {
  const placement = placeBubble({ left: 0, top: 300, width: 80, height: 60 }, 400, 48, { width: 500, height: 800 })
  assert.equal(placement.left, 8) // pinned to margin, never off-screen
})

test('placeBubble: flips BELOW the pet when there is no room above', () => {
  const placement = placeBubble({ left: 100, top: 20, width: 80, height: 60 }, 200, 48, { width: 1200, height: 800 })
  assert.equal(placement.top, 20 + 60 + 8)
})

// ── locator (official a11y anchor) ─────────────────────────────────────────

function fakeElement({ label, parent = null, position = null } = {}) {
  const el = {
    isConnected: true,
    parentElement: parent,
    ariaLabel: label,
  }
  el.getComputedStyle = () => ({ position })
  return el
}

function fakeDoc(canvas) {
  return {
    defaultView: { getComputedStyle: (el) => el.getComputedStyle() },
    querySelector: (sel) => (sel === PET_CANVAS_SELECTOR ? canvas : null),
    body: { tag: 'body' },
  }
}

test('locatePet: finds the pet via aria-label suffix and climbs to the fixed container', () => {
  const container = fakeElement({ position: 'fixed' })
  const wrap = fakeElement({ parent: container })
  const canvas = fakeElement({ label: 'Butler Whale 鲸鱼管家 pet', parent: wrap })
  // getComputedStyle reads per-element: only the container reports fixed
  container.getComputedStyle = () => ({ position: 'fixed' })
  wrap.getComputedStyle = () => ({ position: 'static' })
  canvas.getComputedStyle = () => ({ position: 'static' })

  const found = locatePet(fakeDoc(canvas))
  assert.equal(found.canvas, canvas)
  assert.equal(found.container, container)
})

test('locatePet: null when no pet canvas exists (pet disabled / not installed)', () => {
  assert.equal(locatePet(fakeDoc(null)), null)
})

// ── module css mapping ─────────────────────────────────────────────────────

test('moduleCss maps style keys and ignores unknowns', () => {
  const css = moduleCss({ bold: true, size: 13, color: '#fff', sparkle: true })
  assert.equal(css.fontWeight, 700)
  assert.equal(css.fontSize, '13px')
  assert.equal(css.color, '#fff')
  assert.equal('sparkle' in css, false)
})
