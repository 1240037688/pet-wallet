/**
 * Bubble renderer (M7) — RenderModel → React. Style mapping per module
 * (font/size/bold/italic/underline/color/background); row merging already
 * happened in the resolver/schema; `—` text flows through untouched (the
 * missing-value honesty lives in resolver.js). Image modules render a
 * placeholder box until M10 asset management lands.
 */
import { useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { createResolver } from './resolver.js'

export const RENDERER_VERSION = 1

function moduleStyle(style) {
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

function ModuleView({ mod }) {
  if (mod.type === 'image') {
    return jsx('div', {
      style: {
        width: '100%',
        minHeight: 40,
        borderRadius: 8,
        background: 'repeating-linear-gradient(45deg, #e8f1fb, #e8f1fb 6px, #d5e7f8 6px, #d5e7f8 12px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#5b7fa6',
        fontSize: 10,
      },
      children: `image: ${mod.ref} (M10)`,
    })
  }
  return jsx('span', {
    style: { whiteSpace: 'pre-wrap', ...moduleStyle(mod.style) },
    children: mod.text ?? '—',
  })
}

function PageView({ page }) {
  return jsx('div', {
    style: { display: 'flex', flexDirection: 'column', gap: 2 },
    children: page.rows.map((row, i) =>
      jsx('div', { key: i, style: { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }, children: row.modules.map((mod, j) => jsx(ModuleView, { key: j, mod })) }, void 0),
    ),
  })
}

/** Click-layer bubble: renders the queue's current view, or nothing. */
export function BubbleLayer({ model }) {
  if (!model || !model.def) return null
  const resolver = createResolver()
  let page
  try {
    page = resolver.resolve(model.def, { stepIndex: model.stepIndex, data: model.data })
  } catch {
    return null // invalid definition → bubble silently absent, never broken UI
  }
  return jsx('div', {
    className: 'whale-bubble',
    style: {
      maxWidth: 260,
      padding: '8px 10px',
      borderRadius: 12,
      background: '#ffffff',
      boxShadow: '0 4px 14px rgba(15, 43, 69, 0.18)',
      border: '1px solid #d8e6f3',
      fontSize: 12,
      color: '#25384c',
    },
    children: jsx(PageView, { page }),
  })
}

/** Convenience for previews/tests: render a whole definition's pages. */
export function BubblePreview({ def, data }) {
  const resolver = createResolver()
  const pages = resolver.resolveAll(def, { data })
  return jsxs('div', { children: [pages.length, ' pages'] }, void 0)
}
