/**
 * Bubble schema (M7) — DSH §C2 v1 subset, validated.
 *
 * Definition shape:
 *   Bubble { v: 1, tapAdvance: bool, items: Step[], lib?: Module[] }
 *   Step  = { kind: 'custom', modules: Module[] }            (one bubble page)
 *         | { kind: 'choice', options: [{ w: int, item: Step }] }  (≤2, weighted)
 *   Module (M7 subset of DSH's 12 types):
 *     { type: 'text', row, text, style? }                    — {placeholder} templates
 *     { type: 'random_text', row, texts: [..], style? }      — avoidIdx anti-repeat
 *     { type: 'balance' | 'today' | 'estimated_today' | 'turn_cost' | 'session', row, style? }
 *     { type: 'image', row, ref }                            — RESERVED M10 (validate only)
 *
 * Row-merge rules ([DSH] C2): modules with the SAME consecutive `row` merge
 * into one visual row; image modules always take their own row and are the
 * only module on it; ≤6 modules per row; ≤6 rows per bubble page.
 * All money placeholders resolve to `—` when unknown (never 0/undefined —
 * DATA_MODEL §8.3; enforced in resolver.js).
 */

export const BUBBLE_SCHEMA_VERSION = 1
export const BUBBLE_PIPELINE_VERSION = 1

export const MAX_MODULES_PER_ROW = 6
export const MAX_ROWS_PER_BUBBLE = 6
export const MAX_CHOICE_OPTIONS = 2

const MODULE_TYPES = new Set([
  'text',
  'random_text',
  'image',
  'balance',
  'today',
  'estimated_today',
  'turn_cost',
  'session',
])

const STYLE_KEYS = new Set(['font', 'size', 'bold', 'italic', 'underline', 'color', 'background'])

export class BubbleSchemaError extends TypeError {}

function fail(path, reason) {
  throw new BubbleSchemaError(`bubble schema invalid at ${path}: ${reason}`)
}

function validateModule(mod, path) {
  if (!mod || typeof mod !== 'object') fail(path, 'module must be an object')
  if (!MODULE_TYPES.has(mod.type)) fail(path, `unknown module type ${JSON.stringify(mod.type)}`)
  if (mod.row !== undefined && (!Number.isInteger(mod.row) || mod.row < 0)) fail(path, 'row must be a non-negative integer')
  if (mod.style !== undefined) {
    if (typeof mod.style !== 'object' || mod.style === null) fail(path, 'style must be an object')
    for (const key of Object.keys(mod.style)) {
      if (!STYLE_KEYS.has(key)) fail(path, `unknown style key ${key}`)
    }
  }
  switch (mod.type) {
    case 'text':
      if (typeof mod.text !== 'string' || mod.text.length === 0) fail(path, 'text module needs non-empty text')
      break
    case 'random_text': {
      if (!Array.isArray(mod.texts) || mod.texts.length === 0) fail(path, 'random_text needs texts[]')
      if (!mod.texts.every((t) => typeof t === 'string' && t.length > 0)) fail(path, 'random_text entries must be non-empty strings')
      break
    }
    case 'image':
      if (typeof mod.ref !== 'string' || mod.ref.length === 0) fail(path, 'image needs ref (M10 asset id)')
      break
    default:
      break // data modules carry no payload of their own
  }
}

function validateStep(step, path) {
  if (!step || typeof step !== 'object') fail(path, 'step must be an object')
  if (step.kind === 'custom') {
    if (!Array.isArray(step.modules) || step.modules.length === 0) fail(path, 'custom step needs modules[]')
    step.modules.forEach((mod, i) => validateModule(mod, `${path}.modules[${i}]`))
    const rows = mergeRows(step.modules)
    if (rows.length > MAX_ROWS_PER_BUBBLE) fail(path, `too many rows (${rows.length} > ${MAX_ROWS_PER_BUBBLE})`)
    for (const row of rows) {
      if (row.modules.length > MAX_MODULES_PER_ROW) fail(path, `row ${row.row} has too many modules`)
      if (row.modules.length > 1 && row.modules.some((m) => m.type === 'image')) {
        fail(path, 'image modules must be alone on their row')
      }
    }
    return
  }
  if (step.kind === 'choice') {
    if (!Array.isArray(step.options) || step.options.length === 0) fail(path, 'choice needs options[]')
    if (step.options.length > MAX_CHOICE_OPTIONS) fail(path, `choice supports ≤${MAX_CHOICE_OPTIONS} options`)
    step.options.forEach((opt, i) => {
      if (!opt || typeof opt !== 'object') fail(`${path}.options[${i}]`, 'option must be an object')
      if (!Number.isInteger(opt.w) || opt.w <= 0) fail(`${path}.options[${i}]`, 'option weight w must be a positive integer')
      validateStep(opt.item, `${path}.options[${i}].item`)
    })
    return
  }
  fail(path, `unknown step kind ${JSON.stringify(step.kind)}`)
}

/** Validate a full Bubble definition (throws BubbleSchemaError). */
export function validateBubble(def) {
  if (!def || typeof def !== 'object') throw new BubbleSchemaError('bubble definition must be an object')
  if (def.v !== BUBBLE_SCHEMA_VERSION) fail('v', `expected ${BUBBLE_SCHEMA_VERSION}`)
  if (!Array.isArray(def.items) || def.items.length === 0) fail('items', 'needs at least one step')
  def.items.forEach((step, i) => validateStep(step, `items[${i}]`))
  if (def.lib !== undefined) {
    if (!Array.isArray(def.lib)) fail('lib', 'lib must be an array of modules')
    def.lib.forEach((mod, i) => validateModule(mod, `lib[${i}]`))
  }
  return def
}

/**
 * Merge modules into visual rows: SAME CONSECUTIVE row index merges
 * (non-consecutive same row numbers do NOT merge — DSH §C2 exact semantics);
 * row defaults to the module's array position.
 */
export function mergeRows(modules) {
  const rows = []
  let current = null
  modules.forEach((mod, index) => {
    const row = Number.isInteger(mod.row) ? mod.row : index
    if (current && current.row === row) {
      current.modules.push(mod)
    } else {
      current = { row, modules: [mod] }
      rows.push(current)
    }
  })
  return rows
}
