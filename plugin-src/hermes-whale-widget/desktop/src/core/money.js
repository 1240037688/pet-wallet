/**
 * Money — 1e8 fixed-point arithmetic and display (M3, JS mirror of
 * whale_core.pricing; ACC-07 pins the SAME test vectors both sides).
 *
 * Rules (DATA_MODEL §8.3):
 *   - never float arithmetic: integer units only, strings for parsing;
 *   - null/unknown renders as `—` — `—` ≠ 0, and estimates MUST be labelled;
 *   - overflow beyond safe integers throws (the Python side is the ledger).
 */

export const SCALE = 100_000_000 // 1e8

const MAX_UNITS = 2 ** 53 - 1 // JS safe integer bound (tighter than i64)

export function toUnits(value) {
  if (value === null || value === undefined) throw new TypeError('cannot convert missing amount')
  if (typeof value === 'boolean') throw new TypeError('boolean is not a money amount')
  const s = String(value).trim()
  if (!/^-?\d*(\.\d*)?$/.test(s) || s === '' || s === '-' || s === '.') {
    throw new TypeError('unparseable money amount')
  }
  const neg = s.startsWith('-')
  const [whole, frac = ''] = (neg ? s.slice(1) : s).split('.')
  const frac8 = (frac + '00000000').slice(0, 8)
  const units = BigInt(whole || '0') * BigInt(SCALE) + BigInt(frac8)
  if (units > BigInt(MAX_UNITS)) throw new RangeError('money exceeds safe fixed-point range')
  return Number(neg ? -units : units)
}

export function unitsToDecimalString(units) {
  if (units === null || units === undefined) return null
  const sign = units < 0 ? '-' : ''
  const magnitude = Math.abs(Math.trunc(units))
  const whole = Math.floor(magnitude / SCALE)
  const frac = String(magnitude % SCALE).padStart(8, '0')
  return `${sign}${whole}.${frac}`
}

/** Display form: null → `—` (missing is NOT zero), else trimmed decimal. */
export function formatMoney(units, { currency = null, decimals = 2 } = {}) {
  if (units === null || units === undefined) return '—'
  const dec = Math.max(0, Math.min(8, decimals))
  const magnitude = Math.abs(Math.trunc(units))
  const whole = Math.floor(magnitude / SCALE)
  const frac = String(magnitude % SCALE).padStart(8, '0').slice(0, dec)
  const text = `${units < 0 ? '-' : ''}${whole}${dec > 0 ? '.' + frac : ''}`
  return currency ? `${text} ${currency}` : text
}
