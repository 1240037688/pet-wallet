/**
 * Money — 1e8 fixed-point arithmetic and display (node:test). The SAME
 * vectors are pinned Python-side (whale_core pricing tests, ACC-07):
 * "110.00" → 110e8, null → `—`, illegal input throws, no float arithmetic.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { toUnits, unitsToDecimalString, formatMoney, SCALE } from '../src/core/money.js'

test('SCALE is 1e8 fixed-point', () => {
  assert.equal(SCALE, 100_000_000)
})

test('toUnits parses decimal strings exactly (same vectors as Python)', () => {
  assert.equal(toUnits('110.00'), 11_000_000_000)
  assert.equal(toUnits('0.00'), 0)
  assert.equal(toUnits('0.00000001'), 1) // smallest unit
  assert.equal(toUnits('1'), 100_000_000)
  assert.equal(toUnits('12.5'), 1_250_000_000)
  assert.equal(toUnits('-1.5'), -150_000_000)
  assert.equal(toUnits('-0.00000001'), -1)
  assert.equal(toUnits('33.33333333'), 3_333_333_333)
  // >8 fractional digits truncate (never round — mirrors the Python half)
  assert.equal(toUnits('1.123456789'), 112_345_678)
})

test('toUnits accepts numbers via their string form (no float drift)', () => {
  assert.equal(toUnits(110), 11_000_000_000)
  assert.equal(toUnits(0.1), 10_000_000) // String(0.1) = "0.1" — exact
})

test('toUnits rejects missing/boolean/garbage input', () => {
  for (const bad of [null, undefined, true, false, '', '-', '.', 'abc', '1.2.3', '1e5', '  ']) {
    assert.throws(() => toUnits(bad), TypeError, `expected throw for ${String(bad)}`)
  }
})

test('toUnits throws beyond the safe fixed-point range (ledger stays Python-side)', () => {
  assert.throws(() => toUnits('99999999999999999'), RangeError) // 1e17 whole → 1e25 units
  assert.equal(toUnits('90071992.54740991'), Number.MAX_SAFE_INTEGER) // exact boundary below the throw
})

test('unitsToDecimalString renders exact 8-decimal fixed point', () => {
  assert.equal(unitsToDecimalString(11_000_000_000), '110.00000000')
  assert.equal(unitsToDecimalString(1), '0.00000001')
  assert.equal(unitsToDecimalString(0), '0.00000000')
  assert.equal(unitsToDecimalString(-150_000_000), '-1.50000000')
  assert.equal(unitsToDecimalString(3_333_333_333), '33.33333333')
})

test('unitsToDecimalString(null) → null (missing is NOT zero)', () => {
  assert.equal(unitsToDecimalString(null), null)
  assert.equal(unitsToDecimalString(undefined), null)
})

test('formatMoney display rules: 2 decimals, currency suffix, negatives', () => {
  assert.equal(formatMoney(11_000_000_000), '110.00')
  assert.equal(formatMoney(11_000_000_000, { currency: 'CNY' }), '110.00 CNY')
  assert.equal(formatMoney(150_000_000), '1.50')
  assert.equal(formatMoney(-250_000_000), '-2.50')
  assert.equal(formatMoney(0), '0.00') // a REAL zero is a zero
  assert.equal(formatMoney(1), '0.00') // sub-cent renders honestly as 0.00
  assert.equal(formatMoney(3_333_333_333), '33.33')
})

test('formatMoney decimals option clamps 0..8', () => {
  assert.equal(formatMoney(1_500_000_000, { decimals: 4 }), '15.0000')
  assert.equal(formatMoney(1_500_000_000, { decimals: 0 }), '15')
  assert.equal(formatMoney(1_500_000_000, { decimals: 99 }), '15.00000000')
  assert.equal(formatMoney(1_500_000_000, { decimals: -1 }), '15')
})

test('formatMoney(null) → `—` (missing is NEVER zero)', () => {
  assert.equal(formatMoney(null), '—')
  assert.equal(formatMoney(undefined), '—')
  assert.equal(formatMoney(null, { currency: 'CNY' }), '—')
})

test('roundtrip: toUnits → unitsToDecimalString is lossless at 8 decimals', () => {
  for (const text of ['0.00', '110.00', '33.33333333', '-0.00000001', '900719.9254740991']) {
    assert.equal(unitsToDecimalString(toUnits(text)), unitsToDecimalString(toUnits(unitsToDecimalString(toUnits(text)))))
  }
})
