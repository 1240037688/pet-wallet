/**
 * Bubble resolver (M7) — Definition + data snapshot → RenderModel.
 *
 * Pure and clock-injectable. Placeholder resolution: `{balance}` `{today}`
 * `{estimated_today}` `{turn_cost}` `{session}` — a missing value resolves to
 * `—` (NEVER 0/undefined; DATA_MODEL §8.3). random_text uses avoidIdx
 * anti-repeat (≤6 rerolls, DSH §C2); choice steps are weighted (repeats
 * allowed). The data snapshot is injected, so tests pin everything.
 */
import { BubbleSchemaError, mergeRows, validateBubble } from './schema.js'

export const MAX_REROLLS = 6

export function createResolver({ rng = Math.random } = {}) {
  const avoid = new Map() // module key -> last chosen index (random_text)

  function pickWeighted(options) {
    const total = options.reduce((sum, o) => sum + o.w, 0)
    let roll = rng() * total
    for (const opt of options) {
      roll -= opt.w
      if (roll < 0) return opt.item
    }
    return options[options.length - 1].item
  }

  function pickRandomText(mod, key) {
    if (mod.texts.length === 1) return { text: mod.texts[0], index: 0 }
    const last = avoid.get(key)
    for (let attempt = 0; attempt <= MAX_REROLLS; attempt++) {
      const index = Math.floor(rng() * mod.texts.length) % mod.texts.length
      if (index !== last || attempt === MAX_REROLLS) {
        avoid.set(key, index)
        return { text: mod.texts[index], index }
      }
    }
  }

  function resolveModule(mod, data, key) {
    const base = { type: mod.type, style: mod.style ?? {}, row: mod.row }
    switch (mod.type) {
      case 'text': {
        const m = resolveText(mod.text, data)
        return { ...base, text: m.text, missing: m.missing }
      }
      case 'random_text': {
        const { text } = pickRandomText(mod, key)
        const r = resolveText(text, data)
        return { ...base, text: r.text, missing: r.missing }
      }
      case 'balance':
        return { ...base, text: fmt(data.balance_text), missing: data.balance_text == null }
      case 'today':
        return { ...base, text: fmt(data.today_text), missing: data.today_text == null }
      case 'estimated_today':
        return { ...base, text: fmt(data.estimated_today_text), missing: data.estimated_today_text == null }
      case 'turn_cost':
        return { ...base, text: fmt(data.turn_cost_text), missing: data.turn_cost_text == null }
      case 'session':
        return { ...base, text: data.session_name ?? '—', missing: data.session_name == null }
      case 'image':
        return { ...base, ref: mod.ref } // rendering arrives with M10 assets
      default:
        return { ...base, text: '—', missing: true }
    }
  }

  function resolveStep(step, data, path) {
    if (step.kind === 'choice') {
      const item = pickWeighted(step.options) // repeats allowed ([DSH] C2)
      return resolveStep(item, data, `${path}~choice`)
    }
    const rows = mergeRows(step.modules).map((row) => ({
      row: row.row,
      modules: row.modules.map((mod, i) => resolveModule(mod, data, `${path}.${row.row}.${i}`)),
    }))
    return { kind: 'page', rows }
  }

  return {
    /** Resolve one step (page render model). Throws BubbleSchemaError. */
    resolveStep,

    /** Resolve the bubble's NEXT display step for a tap sequence position. */
    resolve(def, { stepIndex = 0, data } = {}) {
      validateBubble(def)
      const step = def.items[stepIndex % def.items.length]
      return resolveStep(step, data, `items[${stepIndex}]`)
    },

    /** Full sequence (previews / non-advancing bubbles). */
    resolveAll(def, { data } = {}) {
      validateBubble(def)
      return def.items.map((step, i) => resolveStep(step, data, `items[${i}]`))
    },
  }
}

/** `{placeholder}` substitution; missing value → `—`, flagged. */
function resolveText(template, data) {
  let missing = false
  const text = String(template).replace(/\{(\w+)\}/g, (_, name) => {
    const value = data[name]
    if (value === null || value === undefined) {
      missing = true
      return '—'
    }
    return String(value)
  })
  return { text, missing }
}

function fmt(value) {
  return value === null || value === undefined ? '—' : String(value)
}

export { BubbleSchemaError }
