/**
 * M7 bubble schema (node:test): definition validation, DSH §C2 row-merge
 * boundaries (≤6 modules per row, ≤6 rows, image exclusive + alone),
 * non-consecutive same rows do NOT merge, choice ≤2 weighted options,
 * style/text/random_text/image payload validation.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  validateBubble,
  mergeRows,
  BubbleSchemaError,
  MAX_MODULES_PER_ROW,
  MAX_ROWS_PER_BUBBLE,
  MAX_CHOICE_OPTIONS,
} from '../src/ui/bubble/schema.js'

const text = (t, row) => ({ type: 'text', text: t, ...(row !== undefined ? { row } : {}) })
const page = (modules) => ({ v: 1, tapAdvance: false, items: [{ kind: 'custom', modules }] })

test('valid definition passes validation and is returned as-is', () => {
  const def = {
    v: 1,
    tapAdvance: true,
    items: [{ kind: 'custom', modules: [text('hi', 0), text('there', 0)] }],
    lib: [text('lib entry')],
  }
  assert.equal(validateBubble(def), def)
})

test('structural rejects: wrong v / empty items / non-object', () => {
  assert.throws(() => validateBubble(null), BubbleSchemaError)
  assert.throws(() => validateBubble({ v: 2, items: [{ kind: 'custom', modules: [text('x')] }] }), BubbleSchemaError)
  assert.throws(() => validateBubble({ v: 1, items: [] }), BubbleSchemaError)
  assert.throws(() => validateBubble({ v: 1 }), BubbleSchemaError)
})

test('mergeRows: SAME CONSECUTIVE rows merge; defaults are array positions', () => {
  const rows = mergeRows([text('a', 0), text('b', 0), text('c', 1)])
  assert.deepEqual(
    rows.map((r) => ({ row: r.row, count: r.modules.length })),
    [{ row: 0, count: 2 }, { row: 1, count: 1 }],
  )
  const defaulted = mergeRows([text('a'), text('b')])
  assert.deepEqual(defaulted.map((r) => r.row), [0, 1])
})

test('mergeRows: NON-consecutive same row numbers do NOT merge (DSH §C2 exact)', () => {
  const rows = mergeRows([text('a', 0), text('b', 1), text('c', 0)])
  assert.equal(rows.length, 3)
  assert.deepEqual(rows.map((r) => r.row), [0, 1, 0])
})

test('row boundary: exactly 6 modules on one row is valid, 7 throws', () => {
  assert.equal(MAX_MODULES_PER_ROW, 6)
  const six = Array.from({ length: 6 }, (_, i) => text(`t${i}`, 0))
  assert.doesNotThrow(() => validateBubble(page(six)))
  const seven = Array.from({ length: 7 }, (_, i) => text(`t${i}`, 0))
  assert.throws(() => validateBubble(page(seven)), BubbleSchemaError)
})

test('row boundary: exactly 6 rows is valid, 7 throws', () => {
  assert.equal(MAX_ROWS_PER_BUBBLE, 6)
  const sixRows = Array.from({ length: 6 }, (_, i) => text(`t${i}`, i))
  assert.doesNotThrow(() => validateBubble(page(sixRows)))
  const sevenRows = Array.from({ length: 7 }, (_, i) => text(`t${i}`, i))
  assert.throws(() => validateBubble(page(sevenRows)), /too many rows/)
})

test('image modules are alone on their row (same-row company throws)', () => {
  assert.doesNotThrow(() => validateBubble(page([{ type: 'image', ref: 'whale-idle' }])))
  assert.throws(
    () => validateBubble(page([{ type: 'image', ref: 'whale-idle' }, text('x', 0)])),
    /image modules must be alone/,
  )
  // image separated onto its own row is fine
  assert.doesNotThrow(() => validateBubble(page([{ type: 'image', ref: 'x', row: 0 }, text('x', 1)])))
})

test('module payload validation: types / text / texts / ref / row / style keys', () => {
  assert.throws(() => validateBubble(page([{ type: 'marquee' }])), /unknown module type/)
  assert.throws(() => validateBubble(page([{ type: 'text', text: '' }])), /non-empty text/)
  assert.throws(() => validateBubble(page([{ type: 'text' }])), /non-empty text/)
  assert.throws(() => validateBubble(page([{ type: 'random_text', texts: [] }])), /texts\[\]/)
  assert.throws(() => validateBubble(page([{ type: 'random_text', texts: ['ok', ''] }])), /non-empty strings/)
  assert.throws(() => validateBubble(page([{ type: 'image' }])), /ref/)
  assert.throws(() => validateBubble(page([text('x', -1)])), /non-negative integer/)
  assert.throws(() => validateBubble(page([text('x', 1.5)])), /non-negative integer/)
  assert.throws(() => validateBubble(page([{ type: 'text', text: 'x', style: { marquee: true } }])), /unknown style key/)
  assert.doesNotThrow(() => validateBubble(page([{ type: 'text', text: 'x', style: { bold: true, color: '#fff' } }])))
})

test('choice steps: ≤2 options, positive integer weights, nested items validated', () => {
  assert.equal(MAX_CHOICE_OPTIONS, 2)
  const choice = (options) => ({ v: 1, tapAdvance: false, items: [{ kind: 'choice', options }] })
  assert.doesNotThrow(() => validateBubble(choice([{ w: 1, item: { kind: 'custom', modules: [text('a')] } }])))
  assert.throws(
    () =>
      validateBubble(
        choice([
          { w: 1, item: { kind: 'custom', modules: [text('a')] } },
          { w: 1, item: { kind: 'custom', modules: [text('b')] } },
          { w: 1, item: { kind: 'custom', modules: [text('c')] } },
        ]),
      ),
    /≤2/,
  )
  assert.throws(() => validateBubble(choice([{ w: 0, item: { kind: 'custom', modules: [text('a')] } }])), /weight/)
  assert.throws(() => validateBubble(choice([{ w: 1.5, item: { kind: 'custom', modules: [text('a')] } }])), /weight/)
  assert.throws(
    () => validateBubble(choice([{ w: 1, item: { kind: 'custom', modules: [{ type: 'nope' }] } }])),
    /unknown module type/,
  )
})

test('unknown step kind and non-object steps throw', () => {
  assert.throws(() => validateBubble({ v: 1, items: [{ kind: 'ticker' }] }), /unknown step kind/)
  assert.throws(() => validateBubble({ v: 1, items: [null] }), BubbleSchemaError)
})

test('lib modules are validated too', () => {
  assert.throws(() => validateBubble({ v: 1, items: [{ kind: 'custom', modules: [text('x')] }], lib: [{ type: 'bogus' }] }))
  assert.throws(() => validateBubble({ v: 1, items: [{ kind: 'custom', modules: [text('x')] }], lib: 'nope' }))
})
