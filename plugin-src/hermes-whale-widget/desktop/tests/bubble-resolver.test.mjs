/**
 * M7 bubble resolver (node:test): {placeholder} resolution with missing → `—`
 * (NEVER 0/undefined), data modules, random_text avoidIdx anti-repeat with the
 * ≤6 reroll cap, weighted choice (repeats allowed), stepIndex wrap, full-page
 * resolution, schema errors surfaced as BubbleSchemaError.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { createResolver, MAX_REROLLS, BubbleSchemaError } from '../src/ui/bubble/resolver.js'

const page = (modules, extra = {}) => ({ v: 1, tapAdvance: false, items: [{ kind: 'custom', modules }], ...extra })
const text = (t, row) => ({ type: 'text', text: t, ...(row !== undefined ? { row } : {}) })

/** Deterministic rng: replays a queued list of [0,1) rolls, then repeats the last. */
function rngOf(...rolls) {
  let i = 0
  return () => {
    const v = rolls[Math.min(i, rolls.length - 1)]
    i++
    return v
  }
}

test('text placeholders resolve from the data snapshot', () => {
  const r = createResolver()
  const out = r.resolve(page([text('花了 {turn_cost} 元')]), { data: { turn_cost: '0.42' } })
  assert.equal(out.kind, 'page')
  assert.equal(out.rows[0].modules[0].text, '花了 0.42 元')
  assert.equal(out.rows[0].modules[0].missing, false)
})

test('missing placeholder → `—` + missing flag (never 0/undefined)', () => {
  const r = createResolver()
  const out = r.resolve(page([text('余额 {balance}')]), { data: {} })
  assert.equal(out.rows[0].modules[0].text, '余额 —')
  assert.equal(out.rows[0].modules[0].missing, true)
})

test('data modules render `—` when their value is missing', () => {
  const r = createResolver()
  const out = r.resolve(
    page([
      { type: 'balance' },
      { type: 'today', row: 1 },
      { type: 'estimated_today', row: 2 },
      { type: 'turn_cost', row: 3 },
      { type: 'session', row: 4 },
    ]),
    { data: {} },
  )
  const mods = out.rows.flatMap((row) => row.modules)
  assert.deepEqual(mods.map((m) => m.text), ['—', '—', '—', '—', '—'])
  assert.ok(mods.every((m) => m.missing === true))
})

test('data modules render present values (money/session honesty flows through)', () => {
  const r = createResolver()
  const out = r.resolve(page([{ type: 'balance' }, { type: 'turn_cost', row: 1 }, { type: 'session', row: 2 }]), {
    data: { balance_text: '110.00 CNY', turn_cost_text: '0.42 CNY', session_name: '会话A' },
  })
  const mods = out.rows.flatMap((row) => row.modules)
  assert.deepEqual(mods.map((m) => m.text), ['110.00 CNY', '0.42 CNY', '会话A'])
  assert.ok(mods.every((m) => m.missing === false))
})

test('random_text avoidIdx picks a DIFFERENT entry than last time when the rng allows', () => {
  // rolls: first pick 0 → 0; second pick 0 (= last) → reroll → 0.5 → index 1
  const r = createResolver({ rng: rngOf(0, 0, 0.5) })
  const def = page([{ type: 'random_text', texts: ['甲', '乙', '丙'] }])
  const first = r.resolve(def, { data: {} }).rows[0].modules[0].text
  const second = r.resolve(def, { data: {} }).rows[0].modules[0].text
  assert.equal(first, '甲')
  assert.equal(second, '乙')
})

test('random_text reroll caps at MAX_REROLLS (a hostile rng cannot spin forever)', () => {
  assert.equal(MAX_REROLLS, 6)
  const r = createResolver({ rng: () => 0 }) // always index 0 = always the last pick
  const def = page([{ type: 'random_text', texts: ['甲', '乙'] }])
  assert.equal(r.resolve(def, { data: {} }).rows[0].modules[0].text, '甲')
  assert.equal(r.resolve(def, { data: {} }).rows[0].modules[0].text, '甲') // cap reached → repeats
})

test('single-entry random_text never consults the avoid map', () => {
  let calls = 0
  const r = createResolver({ rng: () => { calls++; return 0 } })
  const def = page([{ type: 'random_text', texts: ['唯一'] }])
  assert.equal(r.resolve(def, { data: {} }).rows[0].modules[0].text, '唯一')
  assert.equal(calls, 0)
})

test('choice steps are weighted (deterministic under an injected rng)', () => {
  const def = {
    v: 1,
    tapAdvance: false,
    items: [
      {
        kind: 'choice',
        options: [
          { w: 3, item: { kind: 'custom', modules: [text('A')] } },
          { w: 2, item: { kind: 'custom', modules: [text('B')] } },
        ],
      },
    ],
  }
  // roll 0.4 * 5 = 2.0 → lands inside w:3 → A
  assert.equal(createResolver({ rng: () => 0.4 }).resolve(def, { data: {} }).rows[0].modules[0].text, 'A')
  // roll 0.6 * 5 = 3.0 → w:3 exhausted → B
  assert.equal(createResolver({ rng: () => 0.6 }).resolve(def, { data: {} }).rows[0].modules[0].text, 'B')
  // repeats allowed: the same roll keeps giving the same option
  const repeats = createResolver({ rng: () => 0.6 })
  assert.equal(repeats.resolve(def, { data: {} }).rows[0].modules[0].text, 'B')
  assert.equal(repeats.resolve(def, { data: {} }).rows[0].modules[0].text, 'B')
})

test('resolve wraps stepIndex modulo the item count; resolveAll walks every page', () => {
  const def = page([text('一')], {})
  def.items.push({ kind: 'custom', modules: [text('二', 1)] })
  const r = createResolver()
  assert.equal(r.resolve(def, { stepIndex: 0, data: {} }).rows[0].modules[0].text, '一')
  assert.equal(r.resolve(def, { stepIndex: 1, data: {} }).rows[0].modules[0].text, '二')
  assert.equal(r.resolve(def, { stepIndex: 5, data: {} }).rows[0].modules[0].text, '二') // 5 % 2
  const all = r.resolveAll(def, { data: {} })
  assert.equal(all.length, 2)
  assert.equal(all[1].rows[0].row, 1)
})

test('row merge happens in the resolver too (same consecutive row → one visual row)', () => {
  const r = createResolver()
  const out = r.resolve(page([text('a', 0), text('b', 0), text('c', 1)]), { data: {} })
  assert.equal(out.rows.length, 2)
  assert.equal(out.rows[0].modules.length, 2)
})

test('invalid definitions throw BubbleSchemaError from resolve/resolveAll', () => {
  const r = createResolver()
  const bad = { v: 9, items: [{ kind: 'custom', modules: [text('x')] }] }
  assert.throws(() => r.resolve(bad, { data: {} }), (err) => err.constructor.name === 'BubbleSchemaError')
  assert.throws(() => r.resolveAll(bad, { data: {} }), BubbleSchemaError)
})

test('style flows into the render model untouched', () => {
  const r = createResolver()
  const out = r.resolve(page([{ type: 'text', text: 'x', style: { bold: true, size: 13 } }]), { data: {} })
  assert.deepEqual(out.rows[0].modules[0].style, { bold: true, size: 13 })
})
