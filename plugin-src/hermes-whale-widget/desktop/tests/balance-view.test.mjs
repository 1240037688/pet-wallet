/**
 * M5 balance/summary → view-model mapping (node:test). Pins the DATA_MODEL
 * §8.3 semantics: five balance states → text/tone/badge/hint, error keeps the
 * last known value (never 0), unconfigured → `—` + hint, zero is a REAL zero,
 * estimates always labelled, unreachable → salvage marked 未记账.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { balanceView, todayView, salvageView } from '../src/ui/balance-view.js'

const CRED = { credential: { configured: true } }

test('missing payload → `—` with a waiting hint (never 0)', () => {
  assert.deepEqual(balanceView(null), { text: '—', tone: 'unknown', badge: null, hint: '等待数据…' })
  assert.deepEqual(balanceView(undefined).text, '—')
})

test('unconfigured credential → `—` + configuration hint, regardless of state', () => {
  const v = balanceView({ state: 'ok', observed_balance_units: 100, credential: { configured: false } })
  assert.equal(v.text, '—')
  assert.equal(v.tone, 'unknown')
  assert.equal(v.hint, '未配置 Provider 凭据')
})

test('ok state → formatted observed balance with currency', () => {
  const v = balanceView({ ...CRED, state: 'ok', observed_balance_units: 11_000_000_000, currency: 'CNY' })
  assert.equal(v.text, '110.00 CNY')
  assert.equal(v.tone, 'ok')
  assert.equal(v.badge, null)
  assert.equal(v.hint, null)
})

test('zero state is a REAL zero observation — distinct text/tone/hint from failure', () => {
  const v = balanceView({ ...CRED, state: 'zero', observed_balance_units: null, currency: 'CNY' })
  assert.equal(v.text, '0.00 CNY')
  assert.equal(v.tone, 'zero')
  assert.equal(v.hint, '余额为 0（API 实测）')
})

test('stale state keeps the last known units + 未刷新 badge', () => {
  const v = balanceView({ ...CRED, state: 'stale', observed_balance_units: 7_500_000_000, currency: 'USD' })
  assert.equal(v.text, '75.00 USD')
  assert.equal(v.tone, 'stale')
  assert.equal(v.badge, '未刷新')
  assert.ok(v.hint.includes('过期'))
})

test('error state KEEPS the last known units (API failure ≠ 0) + 获取失败 badge', () => {
  const v = balanceView({
    ...CRED,
    state: 'error',
    observed_balance_units: 5_000_000_000,
    currency: 'CNY',
    error: { kind: 'auth' },
  })
  assert.equal(v.text, '50.00 CNY')
  assert.equal(v.tone, 'error')
  assert.equal(v.badge, '获取失败')
  assert.ok(v.hint.includes('auth'))
  assert.ok(v.hint.includes('最近一次已知值'))
})

test('error with no last known value degrades to `—` honestly', () => {
  const v = balanceView({ ...CRED, state: 'error', observed_balance_units: null, error: { kind: 'network' } })
  assert.equal(v.text, '—')
  assert.equal(v.tone, 'error')
})

test('unknown state → `—` + 状态未知', () => {
  const v = balanceView({ ...CRED, state: 'something-new', observed_balance_units: 1 })
  assert.equal(v.text, '—')
  assert.equal(v.tone, 'unknown')
  assert.equal(v.hint, '状态未知')
})

test('todayView(null) → `—` estimated (no fabricated zeros)', () => {
  const v = todayView(null)
  assert.equal(v.text, '—')
  assert.equal(v.estimated, true)
  assert.equal(v.turns, 0)
})

test('todayView renders estimated_today_units with the first bucket currency + hint', () => {
  const v = todayView({
    estimated_today_units: 456_700_000,
    turns_today: 12,
    unpriced_today: 3,
    estimated_today: [{ currency: 'CNY' }],
  })
  assert.equal(v.text, '4.56 CNY') // fixed-point truncates at 2 decimals (never rounds up)
  assert.equal(v.estimated, true)
  assert.equal(v.turns, 12)
  assert.equal(v.hint, '另有 3 轮未计价')
})

test('todayView without unpriced turns carries no hint', () => {
  const v = todayView({ estimated_today_units: 100_000_000, turns_today: 1, unpriced_today: 0 })
  assert.equal(v.text, '1.00')
  assert.equal(v.hint, null)
})

test('todayView with NULL estimate → `—` even when turns exist', () => {
  const v = todayView({ estimated_today_units: null, turns_today: 5 })
  assert.equal(v.text, '—')
  assert.equal(v.turns, 5)
})

test('salvageView: null/empty focusedUsage → null (nothing fabricated)', () => {
  assert.equal(salvageView(null), null)
  assert.equal(salvageView(undefined), null)
  assert.equal(salvageView({}), null)
  assert.equal(salvageView({ input: null, output: null }), null)
})

test('salvageView renders a token-only snapshot, marked 未记账', () => {
  const v = salvageView({ input: 1234, output: 567 })
  assert.equal(v.text, '本会话 tokens: 1234 入 / 567 出')
  assert.equal(v.estimated, false)
  assert.equal(v.badge, '未记账')
  assert.ok(v.hint.includes('无法计价'))
})

test('salvageView accepts the token-count alias fields', () => {
  const v = salvageView({ input_tokens: 10, output_tokens: 20 })
  assert.equal(v.text, '本会话 tokens: 10 入 / 20 出')
})
