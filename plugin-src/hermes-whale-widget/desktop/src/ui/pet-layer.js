/**
 * Pet interaction layer (DR-16) — the whale-widget interaction attached to
 * the Hermes BUILT-IN pet itself, whatever skin is equipped.
 *
 * How it works (facts verified in hermes-agent source, docs/research/HERMES_PET_SYSTEM.md):
 *   - the in-window mascot renders `<canvas aria-label="… pet">` inside a
 *     position:fixed container (floating-pet.tsx:467-481) — the accessibility
 *     label suffix `" pet"` is the STABLE locator (official a11y attribute,
 *     never UI-text state scraping);
 *   - `react-dom` is NOT in the runtime import map (sdk/runtime.ts:61-67), so
 *     this layer is raw DOM and subscribes to nanostores atoms directly
 *     ($bubble / $balance / $summary all expose .subscribe without React);
 *   - core handles pet drag itself (floating-pet.tsx onPointerDown) — we
 *     listen in the CAPTURE phase, never preventDefault/stopPropagation, and
 *     respond only to taps (movement < TAP_SLOP_PX) so drag stays native.
 *
 * Interaction: tapping the pet = controller.click() (bubble sequence, sounds);
 * the bubble host follows the pet (roam/drag) via rAF while a bubble shows.
 *
 * Limitation (documented): the POPPED-OUT pet overlay is a separate OS window
 * where plugin JS does not load — interaction covers the in-window pet;
 * pet-attached bubbles inside the overlay need the upstream pet API
 * (FEASIBILITY_REPORT §3.1).
 */

export const PET_CANVAS_SELECTOR = 'canvas[aria-label$=" pet"]'
export const TAP_SLOP_PX = 6
export const BUBBLE_MARGIN_PX = 8
export const LOCATE_INTERVAL_MS = 2000

/** Pure: a pointer pair counts as a tap when movement stays within slop. */
export function isTap(down, up, slop = TAP_SLOP_PX) {
  if (!down || !up) return false
  const dx = up.x - down.x
  const dy = up.y - down.y
  return Math.hypot(dx, dy) <= slop
}

/** Pure: did this event's path go through the pet canvas? */
export function isPetHit(composedPath, petCanvas) {
  if (!petCanvas || !Array.isArray(composedPath)) return false
  return composedPath.includes(petCanvas)
}

/**
 * Pure: place the bubble above the pet, horizontally centred, clamped to the
 * viewport; flips below when there is no room above.
 */
export function placeBubble(petRect, bubbleW, bubbleH, viewport, margin = BUBBLE_MARGIN_PX) {
  const vw = viewport?.width ?? 0
  const vh = viewport?.height ?? 0
  const bottom = petRect.bottom ?? petRect.top + petRect.height // DOMRect always has bottom; tolerate plain objects
  const petCx = petRect.left + petRect.width / 2
  let left = Math.round(petCx - bubbleW / 2)
  left = Math.max(margin, Math.min(left, Math.max(margin, vw - bubbleW - margin)))
  let top = Math.round(petRect.top - bubbleH - margin)
  if (top < margin) top = Math.round(bottom + margin)
  top = Math.max(margin, Math.min(top, Math.max(margin, vh - bubbleH - margin)))
  return { left, top }
}

/** Locate the mascot: canvas via the a11y selector, container = fixed ancestor. */
export function locatePet(doc) {
  if (!doc) return null
  const canvas = doc.querySelector(PET_CANVAS_SELECTOR)
  if (!canvas || !canvas.isConnected) return null
  let el = canvas.parentElement
  const view = doc.defaultView
  while (el && el !== doc.body) {
    const position = view && view.getComputedStyle ? view.getComputedStyle(el).position : null
    if (position === 'fixed') return { canvas, container: el }
    el = el.parentElement
  }
  return { canvas, container: canvas.parentElement }
}

/** Pure: bubble render model → style object for one module span. */
export function moduleCss(style) {
  const css = {}
  if (!style) return css
  if (style.font) css.fontFamily = style.font
  if (style.size) css.fontSize = typeof style.size === 'number' ? `${style.size}px` : style.size
  if (style.bold !== undefined) css.fontWeight = style.bold ? 700 : 400
  if (style.italic) css.fontStyle = 'italic'
  if (style.underline) css.textDecoration = 'underline'
  if (style.color) css.color = style.color
  if (style.background) css.background = style.background
  return css
}

const BUBBLE_CSS = {
  background: '#ffffff',
  border: '1px solid #d8e6f3',
  borderRadius: '12px',
  boxShadow: '0 4px 14px rgba(15, 43, 69, 0.18)',
  boxSizing: 'border-box',
  color: '#25384c',
  fontSize: '12px',
  maxWidth: '260px',
  padding: '8px 10px',
  pointerEvents: 'auto',
  position: 'fixed',
}

/**
 * The layer. `doc` is injectable (node tests pass null → start() is a no-op);
 * `resolve` is a bubble resolver; `raf`/`interval` injectable for tests.
 */
export function createPetLayer({ controller, $bubble, doc = null, resolve, now = () => Date.now(), raf = null, interval = null } = {}) {
  const view = typeof document !== 'undefined' && !doc ? document : doc
  const resolver = resolve ?? null
  let started = false
  let petCanvas = null
  let petContainer = null
  let downPos = null
  let host = null
  let bubbleEl = null
  let locateTimer = null
  let followRaf = 0
  let unsubscribeBubble = null
  let lastPlacement = ''

  function locate() {
    const found = locatePet(view)
    petCanvas = found?.canvas ?? null
    petContainer = found?.container ?? null
    return petCanvas != null
  }

  function ensureHost() {
    if (host || !view?.body) return host
    host = view.createElement('div')
    host.id = 'whale-pet-bubble-host'
    host.style.cssText = 'pointer-events:none;position:fixed;inset:0;z-index:9999;'
    view.body.appendChild(host)
    return host
  }

  function buildModule(mod, mk) {
    if (mod.type === 'image') {
      const box = mk('div')
      box.textContent = `🖼 ${mod.ref}`
      return box
    }
    const span = mk('span')
    const text = mod.text ?? '—'
    span.textContent = text
    const css = moduleCss(mod.style)
    for (const [k, v] of Object.entries(css)) span.style[k] = v
    span.style.whiteSpace = 'pre-wrap'
    return span
  }

  function render(view0) {
    if (!host || !resolver) return
    if (bubbleEl) {
      bubbleEl.remove()
      bubbleEl = null
    }
    if (!view0 || !view0.def) {
      stopFollow()
      return
    }
    let page
    try {
      page = resolver.resolve(view0.def, { stepIndex: view0.stepIndex, data: view0.data })
    } catch {
      stopFollow()
      return
    }
    const mk = (tag) => view.createElement(tag)
    bubbleEl = mk('div')
    for (const [k, v] of Object.entries(BUBBLE_CSS)) bubbleEl.style[k] = v
    for (const row of page.rows) {
      const rowEl = mk('div')
      rowEl.style.cssText = 'display:flex;gap:6px;align-items:center;flex-wrap:wrap;'
      for (const mod of row.modules) rowEl.appendChild(buildModule(mod, mk))
      bubbleEl.appendChild(rowEl)
    }
    bubbleEl.addEventListener('click', (e) => {
      e.stopPropagation()
      controller.click()
    })
    host.appendChild(bubbleEl)
    startFollow()
  }

  function petRect() {
    const target = petContainer ?? petCanvas
    if (!target || !target.isConnected) return null
    return target.getBoundingClientRect()
  }

  function reposition() {
    if (!bubbleEl) return
    const rect = petRect()
    if (!rect || rect.width === 0) return
    const placement = placeBubble(
      rect,
      bubbleEl.offsetWidth || 200,
      bubbleEl.offsetHeight || 48,
      { width: view.defaultView.innerWidth, height: view.defaultView.innerHeight },
    )
    const key = `${placement.left},${placement.top}`
    if (key !== lastPlacement) {
      bubbleEl.style.left = `${placement.left}px`
      bubbleEl.style.top = `${placement.top}px`
      lastPlacement = key
    }
  }

  function startFollow() {
    lastPlacement = ''
    reposition()
    if (raf && !followRaf) {
      const loop = () => {
        if (!bubbleEl) {
          followRaf = 0
          return
        }
        reposition()
        followRaf = raf(loop)
      }
      followRaf = raf(loop)
    }
  }

  function stopFollow() {
    if (followRaf && raf) {
      // no cancel API injected — the loop self-terminates on next frame
    }
    followRaf = 0
  }

  function onPointerDown(e) {
    if (!petCanvas) locate()
    const path = typeof e.composedPath === 'function' ? e.composedPath() : null
    if (isPetHit(path, petCanvas)) {
      downPos = { x: e.clientX, y: e.clientY }
      try {
        controller.press()
      } catch { /* cosmetic */ }
    } else {
      downPos = null
    }
  }

  function onPointerUp(e) {
    if (!downPos) return
    try {
      controller.release()
    } catch { /* cosmetic */ }
    downPos = { ...downPos, __up: { x: e.clientX, y: e.clientY } }
  }

  function onClick(e) {
    if (!downPos || !downPos.__up) return
    const up = downPos.__up
    const wasTap = isTap(downPos, up)
    downPos = null
    if (!wasTap) return // drag — core owns it
    try {
      controller.click()
    } catch { /* cosmetic */ }
  }

  return {
    start() {
      if (started || !view) return
      started = true
      ensureHost()
      locate()
      const retry = () => {
        if (!petCanvas) locate()
      }
      locateTimer = interval
        ? interval(retry, LOCATE_INTERVAL_MS)
        : (typeof setInterval === 'function' ? setInterval(retry, LOCATE_INTERVAL_MS) : null)
      view.addEventListener('pointerdown', onPointerDown, true)
      view.addEventListener('pointerup', onPointerUp, true)
      view.addEventListener('click', onClick, true)
      if ($bubble?.subscribe) {
        unsubscribeBubble = $bubble.subscribe((v) => render(v))
      }
      // first paint of an already-visible bubble
      render($bubble?.get?.() ?? null)
    },

    stop() {
      if (!started) return
      started = false
      try {
        view.removeEventListener('pointerdown', onPointerDown, true)
        view.removeEventListener('pointerup', onPointerUp, true)
        view.removeEventListener('click', onClick, true)
      } catch { /* already gone */ }
      if (locateTimer) {
        try {
          clearInterval(locateTimer)
        } catch { /* noop */ }
        locateTimer = null
      }
      if (unsubscribeBubble) {
        try {
          unsubscribeBubble()
        } catch { /* noop */ }
        unsubscribeBubble = null
      }
      stopFollow()
      if (host) {
        try {
          host.remove()
        } catch { /* noop */ }
        host = null
        bubbleEl = null
      }
    },

    /** Test/inspection surface. */
    status() {
      return { started, petFound: petCanvas != null, bubbleVisible: bubbleEl != null }
    },

    /** Test seam: re-run locate + reposition on demand. */
    _locateAndPlace() {
      locate()
      reposition()
      return { petFound: petCanvas != null, placement: lastPlacement }
    },
  }
}
