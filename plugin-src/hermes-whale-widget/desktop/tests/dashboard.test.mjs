/**
 * WP-dashboard pure logic tests — the dashboard page's view-model helpers with
 * fake data only (no DOM, no build artifact, no react): provider list merge +
 * five-state card VMs, bubble show/hide filtering, balance text joining, bar
 * height normalization, today card mapping, and the createDashboard wiring
 * shape (routes page / sidebar nav / chip navigation feature-detect).
 *
 * The source module is imported through tests/loader.mjs so the bare
 * '@hermes/plugin-sdk' import resolves to the shim (atom/ROUTES_AREA/…).
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register('./loader.mjs', import.meta.url)

const {
  ROUTE_PATH,
  ROUTE_TITLE,
  normalizeSelectedProviders,
  visibleBalanceProviders,
  providerBalanceText,
  bubbleBalanceText,
  toggleBubbleProvider,
  providerCards,
  todayCardView,
  barHeights,
  sortModelRows,
  toneColor,
  createDashboard,
} = await import('../src/ui/dashboard.js')

const UNITS_110 = 110_000_000 // 1.10 in 1e8 fixed point
const UNITS_42 = 42_000_000 // 0.42

const OK_ROW = {
  provider_id: 'deepseek',
  known: true,
  configured: true,
  source: 'hermes_secret',
  credential_id: 'deepseek:abcd1234',
  fingerprint: 'fp0000000000000000000001',
  state: 'ok',
  observed_balance_units: UNITS_110,
  currency: 'CNY',
}

// ---------------------------------------------------------------------------
// list merge / filtering (bubble show-list semantics: empty = show all)
// ---------------------------------------------------------------------------

test('normalizeSelectedProviders keeps strings only', () => {
  assert.deepEqual(normalizeSelectedProviders(['deepseek', 3, null, 'openai', true]), ['deepseek', 'openai'])
  assert.deepEqual(normalizeSelectedProviders(undefined), [])
  assert.deepEqual(normalizeSelectedProviders('deepseek'), [])
})

test('visibleBalanceProviders: empty selection shows every configured row', () => {
  const rows = [OK_ROW, { provider_id: 'openai', configured: true, state: 'unknown' }]
  assert.deepEqual(visibleBalanceProviders(rows, []).map((r) => r.provider_id), ['deepseek', 'openai'])
  assert.deepEqual(visibleBalanceProviders(rows, null).length, 2)
})

test('visibleBalanceProviders: non-empty selection filters by provider_id', () => {
  const rows = [OK_ROW, { provider_id: 'openai', configured: true, state: 'unknown' }]
  assert.deepEqual(visibleBalanceProviders(rows, ['openai']).map((r) => r.provider_id), ['openai'])
  assert.deepEqual(visibleBalanceProviders(rows, ['gone']), [])
  assert.deepEqual(visibleBalanceProviders('not-a-list', []), [])
})

// ---------------------------------------------------------------------------
// bubble balance text joining
// ---------------------------------------------------------------------------

test('providerBalanceText: symbol currencies → `deepseek ¥1.10`', () => {
  assert.equal(providerBalanceText(OK_ROW), 'deepseek ¥1.10')
  assert.equal(providerBalanceText({ provider_id: 'x', observed_balance_units: UNITS_110, currency: 'USD' }), 'x $1.10')
})

test('providerBalanceText: unknown currency keeps the code; unobserved → —', () => {
  assert.equal(providerBalanceText({ provider_id: 'x', observed_balance_units: UNITS_110, currency: 'XYZ' }), 'x 1.10 XYZ')
  assert.equal(providerBalanceText({ provider_id: 'x', currency: 'CNY' }), 'x —')
  assert.equal(providerBalanceText({ provider_id: 'x', observed_balance_units: null }), 'x —')
  assert.equal(providerBalanceText(null), null)
  assert.equal(providerBalanceText({ observed_balance_units: UNITS_110 }), null)
})

test('bubbleBalanceText joins multiple providers with " | "', () => {
  const rows = [
    { provider_id: 'deepseek', observed_balance_units: UNITS_110, currency: 'CNY' },
    { provider_id: 'openai', observed_balance_units: UNITS_42, currency: 'USD' },
  ]
  assert.equal(bubbleBalanceText(rows, []), 'deepseek ¥1.10 | openai $0.42')
})

test('bubbleBalanceText: selection filter + null when nothing shows', () => {
  const rows = [
    { provider_id: 'deepseek', observed_balance_units: UNITS_110, currency: 'CNY' },
    { provider_id: 'openai', observed_balance_units: UNITS_42, currency: 'USD' },
  ]
  assert.equal(bubbleBalanceText(rows, ['openai']), 'openai $0.42')
  assert.equal(bubbleBalanceText(rows, ['gone']), null)
  assert.equal(bubbleBalanceText([], []), null)
})

// ---------------------------------------------------------------------------
// show/hide toggle → next persisted list
// ---------------------------------------------------------------------------

test('toggleBubbleProvider: show on the compact (empty) list is a no-op', () => {
  assert.deepEqual(toggleBubbleProvider([], 'deepseek', true, ['deepseek']), [])
})

test('toggleBubbleProvider: show adds, idempotent', () => {
  assert.deepEqual(toggleBubbleProvider(['openai'], 'deepseek', true, ['deepseek', 'openai']), ['openai', 'deepseek'])
  assert.deepEqual(toggleBubbleProvider(['openai', 'deepseek'], 'deepseek', true, ['openai', 'deepseek']), [
    'openai',
    'deepseek',
  ])
})

test('toggleBubbleProvider: hide from the compact list materializes minus the hidden one', () => {
  assert.deepEqual(toggleBubbleProvider([], 'deepseek', false, ['deepseek', 'openai']), ['openai'])
  assert.deepEqual(toggleBubbleProvider([], 'deepseek', false, undefined), [])
})

test('toggleBubbleProvider: hide from an explicit list removes only that id', () => {
  assert.deepEqual(toggleBubbleProvider(['deepseek', 'openai'], 'deepseek', false, ['deepseek', 'openai']), ['openai'])
})

// ---------------------------------------------------------------------------
// balance cards: five-state semantics (DATA_MODEL §6 / balance-view parity)
// ---------------------------------------------------------------------------

test('providerCards: ok state shows amount + green tone, badge-free', () => {
  const [card] = providerCards([OK_ROW], [])
  assert.equal(card.stateLabel, '正常')
  assert.equal(card.tone, 'ok')
  assert.equal(card.amountText, '1.10 CNY')
  assert.equal(card.badge, null)
  assert.equal(card.shownInBubble, true)
})

test('providerCards: zero keeps a real 0 distinct from failure', () => {
  const [card] = providerCards([{ ...OK_ROW, state: 'zero', observed_balance_units: 0 }], [])
  assert.equal(card.tone, 'zero')
  assert.equal(card.amountText, '0.00 CNY')
  assert.match(card.hint, /API 实测/)
})

test('providerCards: stale keeps the last known amount + grey 未刷新 badge', () => {
  const [card] = providerCards([{ ...OK_ROW, state: 'stale' }], [])
  assert.equal(card.tone, 'stale')
  assert.equal(card.amountText, '1.10 CNY')
  assert.equal(card.badge, '未刷新')
})

test('providerCards: error keeps the last known amount + ⚠ badge, never 0', () => {
  const [card] = providerCards([{ ...OK_ROW, state: 'error' }], [])
  assert.equal(card.tone, 'error')
  assert.equal(card.amountText, '1.10 CNY')
  assert.equal(card.badge, '⚠ 获取失败')
  assert.match(card.hint, /绝不显示为 0/)
})

test('providerCards: configured-but-unobserved → — (never a fabricated 0)', () => {
  const [card] = providerCards([{ provider_id: 'deepseek', configured: true, source: 'hermes_secret', state: 'unknown' }], [])
  assert.equal(card.tone, 'unknown')
  assert.equal(card.amountText, '—')
  assert.equal(card.badge, null)
})

test('providerCards: unconfigured → — + guidance, no credential fields surfaced', () => {
  const [card] = providerCards([{ provider_id: 'deepseek', known: true, configured: false, source: 'none', state: 'unknown' }], [])
  assert.equal(card.configured, false)
  assert.equal(card.amountText, '—')
  assert.equal(card.tone, 'unknown')
  assert.match(card.hint, /未配置凭据/)
  assert.equal(JSON.stringify(card).includes('fingerprint'), false)
})

test('providerCards: shownInBubble honours the explicit list', () => {
  const [visible, hidden] = providerCards([OK_ROW, { ...OK_ROW, provider_id: 'openai' }], ['deepseek'])
  assert.equal(visible.shownInBubble, true)
  assert.equal(hidden.shownInBubble, false)
})

test('toneColor maps the five tones with an unknown fallback', () => {
  assert.equal(toneColor('ok'), toneColor('ok'))
  assert.notEqual(toneColor('error'), toneColor('ok'))
  assert.equal(toneColor('nonsense'), toneColor('unknown'))
})

// ---------------------------------------------------------------------------
// today overview + chart normalization + model sort
// ---------------------------------------------------------------------------

test('todayCardView: null summary → — with no fabricated numbers', () => {
  const view = todayCardView(null)
  assert.equal(view.amountText, '—')
  assert.equal(view.turns, 0)
  assert.equal(view.unpriced, 0)
})

test('todayCardView: buckets fold unpriced turns; basis text distinguishes token_only', () => {
  const view = todayCardView({
    estimated_today_units: 456_700_000,
    estimated_today_currency: 'CNY',
    estimated_today_basis: 'token_only',
    turns_today: 12,
    tokens_today: { input: 100, output: 50, reasoning: 10, cache_read: 0, cache_write: 5 },
    estimated_today_by_currency: [{ currency: 'CNY', estimated_cost_units: 456_700_000, unpriced_turns: 3 }],
  })
  assert.equal(view.amountText, '4.56') // formatMoney default = 2 decimals
  assert.equal(view.turns, 12)
  assert.equal(view.unpriced, 3)
  assert.match(view.basisText, /仅 token 估算/)
})

test('barHeights: normalized to the max day; missing day → 0 with 无数据 title', () => {
  const days = [
    { day: '2026-10-01', estimated_cost_units: 400_000_000, currency: 'CNY', basis: 'turn_cost' },
    { day: '2026-10-02', estimated_cost_units: 200_000_000, currency: 'CNY', basis: 'turn_cost' },
    { day: '2026-10-03', estimated_cost_units: null, currency: null, basis: null },
  ]
  const bars = barHeights(days, 100)
  assert.equal(bars.length, 3)
  assert.equal(bars[0].height, 100)
  assert.equal(bars[1].height, 50)
  assert.equal(bars[2].height, 0)
  assert.equal(bars[2].hasValue, false)
  assert.match(bars[2].title, /无数据/)
  assert.match(bars[0].title, /4\.00 CNY · 估算/)
  assert.equal(bars.every((bar) => Number.isFinite(bar.height)), true)
})

test('barHeights: all-empty window → zero heights (no divide-by-zero), tokenOnly + unpriced flags', () => {
  const bars = barHeights([{ day: '2026-10-01', estimated_cost_units: null, basis: 'token_only', estimated_by_currency: [{ unpriced_turns: 2 }] }], 120)
  assert.equal(bars[0].height, 0)
  assert.equal(bars[0].tokenOnly, true)
  assert.equal(bars[0].unpriced, 2)
  assert.match(bars[0].title, /仅 token 估算/)
  assert.match(bars[0].title, /2 轮未计价/)
  const empty = barHeights(undefined, 120)
  assert.deepEqual(empty, [])
})

test('sortModelRows: turns desc, tie broken by estimated cost desc', () => {
  const rows = sortModelRows([
    { model: 'a', turns: 2, estimated_cost_units: 900 },
    { model: 'b', turns: 5, estimated_cost_units: 100 },
    { model: 'c', turns: 2, estimated_cost_units: 1000 },
  ])
  assert.deepEqual(rows.map((r) => r.model), ['b', 'c', 'a'])
})

// ---------------------------------------------------------------------------
// createDashboard wiring shape (fake rest + shim host; minimal DOM)
// ---------------------------------------------------------------------------

function makeHost({ withNavigate = true } = {}) {
  return withNavigate ? { navigate: () => {} } : {}
}

test('createDashboard: routes page + sidebar.nav contributions match the app contract', async () => {
  const { contribution, navContribution } = createDashboard({
    rest: async () => ({}),
    host: makeHost(),
    atoms: { $health: { get: () => ({ state: 'ok' }) }, $bubbleProviders: { get: () => [] } },
  })
  assert.equal(contribution.area, 'routes')
  assert.equal(contribution.title, ROUTE_TITLE)
  assert.equal(contribution.data.path, ROUTE_PATH)
  assert.equal(ROUTE_PATH, '/whale') // one segment, no params (app/routes.ts)
  assert.equal(typeof contribution.render, 'function')
  const vnode = contribution.render()
  assert.equal(typeof vnode.type, 'function') // SDK renders the page component
  assert.equal(navContribution.area, 'sidebar.nav')
  assert.equal(navContribution.data.path, ROUTE_PATH)
  assert.equal(navContribution.data.label, ROUTE_TITLE)
  assert.equal(typeof navContribution.data.codicon, 'string')
})

test('createDashboard: chip wrapper navigates to /whale when host.navigate exists', async () => {
  const navigated = []
  const host = { navigate: (path) => navigated.push(path) }
  const { wrapChip } = createDashboard({ rest: async () => ({}), host, atoms: {} })
  const inner = { type: 'span', props: { children: 'chip' } }
  const wrapper = wrapChip(inner)
  assert.equal(typeof wrapper.type, 'function') // ChipNavigate component
  const rendered = wrapper.type(wrapper.props)
  assert.equal(rendered.type, 'span')
  assert.equal(typeof rendered.props.onClick, 'function')
  rendered.props.onClick({ preventDefault: () => {} })
  assert.deepEqual(navigated, ['/whale'])
})

test('createDashboard: chip wrapper degrades to a plain span without host.navigate', async () => {
  const { wrapChip } = createDashboard({ rest: async () => ({}), host: {}, atoms: {} })
  const rendered = wrapChip({ type: 'span', props: {} }).type({ children: 'chip' })
  assert.equal(rendered.type, 'span')
  assert.equal(rendered.props.onClick, undefined)
})
