/**
 * Whale Wallet dashboard page (WP-dashboard) — the in-app routes page.
 *
 * Mirrors ai-usage-tracker's structure (ROUTES page + sidebar.nav row +
 * statusbar chip navigation) but renders the whale ledger: provider balance
 * cards (five-state semantics), today estimate, 7-day CSS bar chart, per-model
 * table, recent turns, price tables. ALL numbers come from the Python half's
 * REST surface — nothing is fabricated (DATA_MODEL §8.3: missing ≠ 0, estimates
 * always labelled 估算).
 *
 * Layout discipline: inline styles only (no tailwind in runtime plugins);
 * SDK components for interactive/empty/error surfaces (Button / ToggleRow /
 * Select / EmptyState / ErrorState). Tone colors reuse the balance-view
 * semantics (ok green / zero cyan / stale grey / error red / unknown grey).
 *
 * No react hooks: state lives in nanostores atoms (useValue/useQuery only),
 * so the page keeps working without react-dom in the runtime import map.
 * JSX note: the automatic runtime takes (type, props, key) ONLY — children
 * always go inside props (never varargs).
 *
 * Exports two halves:
 *   - PURE view-model helpers (providerCards / barHeights / bubbleBalanceText /
 *     …) — unit-tested with fake data, no DOM;
 *   - createDashboard({ rest, host, atoms }) — the wiring factory returning the
 *     `routes` contribution, the `sidebar.nav` data contribution and a chip
 *     navigation wrapper (host.navigate is feature-detected).
 *
 * Hidden-list contract (synced with the main session's docs): the pet bubble
 * shows balances for the provider ids in config `bubble.balance_providers`;
 * an EMPTY list means "every configured provider". The page's ToggleRows write
 * that key via PUT /config and mirror it into the shared runtime atom so the
 * bubble text updates without waiting for the next /config poll.
 */
import {
  atom,
  Button,
  EmptyState,
  ErrorState,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  ToggleRow,
  useQuery,
  useQueryClient,
  useValue,
} from '@hermes/plugin-sdk'
import { jsx } from 'react/jsx-runtime'
import { formatMoney } from '../core/money.js'

export const ROUTE_PATH = '/pet-wallet'
export const ROUTE_TITLE = 'Pet Wallet'

// Balance tone colors (balance-view.js semantics; moodAccent palette).
export const TONE_COLORS = {
  ok: 'var(--ui-green)',
  zero: 'var(--ui-cyan)',
  stale: 'var(--ui-text-tertiary)',
  error: 'var(--ui-red)',
  unknown: 'var(--ui-text-tertiary)',
}

export function toneColor(tone) {
  return TONE_COLORS[tone] ?? TONE_COLORS.unknown
}

// Statusbar health dot ($health states).
export const HEALTH_COLORS = {
  ok: TONE_COLORS.ok,
  degraded: 'var(--ui-orange)',
  unreachable: TONE_COLORS.error,
  checking: TONE_COLORS.unknown,
}

// Bubble text currency symbols (formatMoney stays code-based otherwise).
const CURRENCY_SYMBOLS = { CNY: '¥', USD: '$', EUR: '€', JPY: '¥' }

const CHART_DAY_OPTIONS = [7, 14, 30]

// ---------------------------------------------------------------------------
// pure view-model helpers
// ---------------------------------------------------------------------------

/** Config readback → normalized show-list (strings only). */
export function normalizeSelectedProviders(value) {
  if (!Array.isArray(value)) return []
  return value.filter((id) => typeof id === 'string' && id)
}

/** Bubble filter: EMPTY list = show every configured provider. */
export function visibleBalanceProviders(rows, selectedIds) {
  const list = Array.isArray(rows) ? rows.filter((row) => row && typeof row === 'object') : []
  const selected = normalizeSelectedProviders(selectedIds)
  if (selected.length === 0) return list
  return list.filter((row) => selected.includes(row.provider_id))
}

/** One provider row → `deepseek ¥1.10` or `Codex 5h剩75% · 周剩68%` (or `—` when unobserved). */
export function providerBalanceText(row) {
  if (!row || typeof row !== 'object' || typeof row.provider_id !== 'string') return null
  if (row.kind === 'quota') {
    const windows = Array.isArray(row.windows) ? row.windows : []
    const winTexts = windows.map((w) => {
      const rem = w.remaining_percent ?? (w.used_percent != null ? Math.max(0, 100 - w.used_percent) : null)
      const lbl = w.label === 'Session' ? '5h' : w.label === 'Weekly' ? '周' : w.label
      return rem != null ? `${lbl}剩${Math.round(rem)}%` : `${lbl}—`
    })
    const name = row.name ?? (row.provider_id === 'openai-codex' ? 'Codex' : row.provider_id)
    return winTexts.length > 0 ? `${name} ${winTexts.join(' · ')}` : `${name} 额度正常`
  }
  const units = row.observed_balance_units
  if (units === null || units === undefined || !Number.isFinite(Number(units))) {
    return `${row.provider_id} —`
  }
  const amount = formatMoney(Number(units), { decimals: 2 })
  const symbol = CURRENCY_SYMBOLS[row.currency]
  if (symbol) return `${row.provider_id} ${symbol}${amount}`
  return row.currency ? `${row.provider_id} ${amount} ${row.currency}` : `${row.provider_id} ${amount}`
}

/** Visible rows → single bubble text (' | ' joined) or null when nothing shows. */
export function bubbleBalanceText(rows, selectedIds) {
  const texts = visibleBalanceProviders(rows, selectedIds)
    .map(providerBalanceText)
    .filter((text) => typeof text === 'string')
  return texts.length > 0 ? texts.join(' | ') : null
}

/** Show/hide toggle → next persisted list (empty = show all configured). */
export function toggleBubbleProvider(selectedIds, providerId, on, allConfiguredIds) {
  const current = normalizeSelectedProviders(selectedIds)
  if (on) {
    if (current.length === 0) return [] // already "show all" — keep the compact form
    return current.includes(providerId) ? current : [...current, providerId]
  }
  if (current.length === 0) {
    // materialize against every configured provider, minus the hidden one
    const all = Array.isArray(allConfiguredIds) ? allConfiguredIds.filter((id) => typeof id === 'string') : []
    return all.filter((id) => id !== providerId)
  }
  return current.filter((id) => id !== providerId)
}

/** GET /providers/status rows → balance-card view models (five-state semantics). */
export function providerCards(rows, selectedIds) {
  const list = Array.isArray(rows) ? rows : []
  const selected = normalizeSelectedProviders(selectedIds)
  return list.map((row) => {
    const providerId = typeof row.provider_id === 'string' ? row.provider_id : '?'
    const configured = row.configured === true
    const units = row.observed_balance_units
    const base = {
      provider_id: providerId,
      configured,
      source: typeof row.source === 'string' ? row.source : 'none',
      shownInBubble: selected.length === 0 ? true : selected.includes(providerId),
    }
    if (!configured) {
      return {
        ...base,
        stateLabel: '未配置',
        tone: 'unknown',
        amountText: '—',
        badge: null,
        hint: '未配置凭据 — 配置后此处显示五状态余额或配额',
      }
    }
    if (row.kind === 'quota') {
      return {
        ...base,
        kind: 'quota',
        name: row.name ?? row.provider_id,
        plan: row.plan ?? null,
        windows: Array.isArray(row.windows) ? row.windows : [],
        details: Array.isArray(row.details) ? row.details : [],
        stateLabel: row.state === 'ok' ? (row.plan ? `${row.plan} 订阅` : '正常') : '未配置',
        tone: row.state === 'ok' ? 'ok' : 'unknown',
        amountText: null,
        badge: row.plan ? row.plan : null,
        hint: null,
      }
    }
    const amountText =
      units !== null && units !== undefined ? formatMoney(units, { currency: row.currency ?? null }) : null
    switch (row.state) {
      case 'ok':
        return { ...base, stateLabel: '正常', tone: 'ok', amountText: amountText ?? '—', badge: null, hint: null }
      case 'zero':
        return {
          ...base,
          stateLabel: '零余额',
          tone: 'zero',
          amountText: formatMoney(0, { currency: row.currency ?? null }),
          badge: null,
          hint: '余额为 0（API 实测，非获取失败）',
        }
      case 'stale':
        return {
          ...base,
          stateLabel: '未刷新',
          tone: 'stale',
          amountText: amountText ?? '—',
          badge: '未刷新',
          hint: '数据已过期 — 等待下次轮询或手动刷新',
        }
      case 'error':
        return {
          ...base,
          stateLabel: '获取失败',
          tone: 'error',
          amountText: amountText ?? '—',
          badge: '⚠ 获取失败',
          hint: '余额 API 出错 — 显示最近一次已知值（绝不显示为 0）',
        }
      default:
        return { ...base, stateLabel: '暂无观测', tone: 'unknown', amountText: '—', badge: null, hint: '尚未获取到余额观测' }
    }
  })
}

/** Today card VM (DATA_MODEL §8.3: estimated figures carry the 估算 badge). */
export function todayCardView(summary) {
  if (!summary || typeof summary !== 'object') {
    return { amountText: '—', currency: null, turns: 0, tokens: null, unpriced: 0, basisText: null }
  }
  const buckets = Array.isArray(summary.estimated_today_by_currency) ? summary.estimated_today_by_currency : []
  const unpriced = buckets.reduce(
    (sum, bucket) => sum + (Number.isFinite(bucket?.unpriced_turns) ? bucket.unpriced_turns : 0),
    0,
  )
  const basisText =
    summary.estimated_today_basis === 'turn_cost'
      ? '按已结算轮次计价汇总'
      : summary.estimated_today_basis === 'token_only'
        ? '仅 token 估算（当日无成交价快照）'
        : null
  return {
    amountText: formatMoney(summary.estimated_today_units ?? null, { currency: null }),
    currency: summary.estimated_today_currency ?? null,
    turns: Number.isFinite(summary.turns_today) ? summary.turns_today : 0,
    tokens: summary.tokens_today ?? null,
    unpriced,
    basisText,
  }
}

function formatDayLabel(day) {
  return typeof day === 'string' && day.length >= 10 ? day.slice(5) : String(day ?? '')
}

/** estimated_days → normalized CSS bar VMs (heights share one max; missing → 0). */
export function barHeights(estimatedDays, maxHeight = 120) {
  const days = Array.isArray(estimatedDays) ? estimatedDays : []
  const finite = days.map((d) => (Number.isFinite(d?.estimated_cost_units) ? d.estimated_cost_units : 0))
  const maxUnits = finite.reduce((m, u) => (u > m ? u : m), 0)
  return days.map((entry, index) => {
    const units = Number.isFinite(entry?.estimated_cost_units) ? entry.estimated_cost_units : null
    const height = units === null || maxUnits === 0 ? 0 : Math.max(2, Math.round((maxHeight * units) / maxUnits))
    const unpriced = Array.isArray(entry?.estimated_by_currency)
      ? entry.estimated_by_currency.reduce(
          (sum, b) => sum + (Number.isFinite(b?.unpriced_turns) ? b.unpriced_turns : 0),
          0,
        )
      : 0
    const titleParts = [formatDayLabel(entry?.day)]
    titleParts.push(
      units === null ? '无数据' : `${formatMoney(units, { currency: null })}${entry?.currency ? ` ${entry.currency}` : ''} · 估算`,
    )
    if (entry?.basis === 'token_only') titleParts.push('仅 token 估算')
    if (entry?.partial) titleParts.push('部分观测')
    if (unpriced > 0) titleParts.push(`${unpriced} 轮未计价`)
    return {
      day: entry?.day ?? null,
      units,
      currency: entry?.currency ?? null,
      basis: entry?.basis ?? null,
      partial: entry?.partial === true,
      unpriced,
      height,
      hasValue: units !== null,
      tokenOnly: entry?.basis === 'token_only',
      title: titleParts.join(' · '),
      index,
    }
  })
}

/** per_model rows sorted for the table (turns desc, then estimated cost desc). */
export function sortModelRows(perModel) {
  const rows = Array.isArray(perModel) ? perModel.filter((row) => row && typeof row === 'object') : []
  return [...rows].sort((a, b) => {
    const turns = (b.turns ?? 0) - (a.turns ?? 0)
    if (turns !== 0) return turns
    return (b.estimated_cost_units ?? 0) - (a.estimated_cost_units ?? 0)
  })
}

function formatTimestamp(ms) {
  if (!Number.isFinite(ms)) return '—'
  const date = new Date(ms)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

// ---------------------------------------------------------------------------
// small styled primitives (inline styles — no tailwind in runtime plugins)
// ---------------------------------------------------------------------------

// Apple-style surface: soft layered shadow, hairline stroke, continuous-feel radius
const CARD = {
  background: 'var(--ui-bg-card)',
  border: '1px solid var(--ui-stroke-tertiary)',
  borderRadius: 16,
  boxShadow: '0 1px 2px rgba(0,0,0,0.04), 0 6px 20px rgba(0,0,0,0.05)',
  boxSizing: 'border-box',
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
  padding: '16px 18px',
}

// Apple-type system stack — the workspace may render with its own font; the
// dashboard opts into the platform feel explicitly.
const FONT_STACK =
  '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei UI", "Helvetica Neue", sans-serif'

const TH = {
  textAlign: 'left',
  fontSize: 11,
  color: 'var(--ui-text-tertiary)',
  fontWeight: 600,
  padding: '6px 10px',
  borderBottom: '1px solid var(--ui-stroke-tertiary)',
  whiteSpace: 'nowrap',
  letterSpacing: '0.01em',
}
const TD = {
  fontSize: 12.5,
  color: 'var(--ui-text-secondary)',
  padding: '8px 10px',
  borderBottom: '1px solid var(--ui-stroke-tertiary)',
  fontVariantNumeric: 'tabular-nums',
  whiteSpace: 'nowrap',
}

function Badge({ text, color }) {
  return jsx('span', {
    style: {
      fontSize: 11,
      lineHeight: '18px',
      padding: '0 8px',
      borderRadius: 999,
      background: `color-mix(in srgb, ${color} 12%, transparent)`,
      color,
      fontWeight: 500,
      whiteSpace: 'nowrap',
    },
    children: text,
  })
}

function EstimateBadge() {
  return jsx(Badge, { text: '估算', color: 'var(--ui-text-tertiary)' })
}

function StateDot({ tone, size = 8 }) {
  return jsx('span', {
    'aria-hidden': true,
    style: {
      display: 'inline-block',
      width: size,
      height: size,
      borderRadius: '50%',
      background: toneColor(tone),
      flexShrink: 0,
    },
  })
}

function HealthDot({ health }) {
  const state = health?.state ?? 'checking'
  const label =
    state === 'ok'
      ? '记账后端已连接'
      : state === 'degraded'
        ? `记账后端降级${health?.detail ? '（ledger 错误）' : ''}`
        : state === 'unreachable'
          ? '记账后端不可达'
          : '连接中…'
  const tone = state === 'ok' ? 'ok' : state === 'degraded' ? 'stale' : state === 'unreachable' ? 'error' : 'unknown'
  return jsx('span', {
    title: `Whale Wallet 记账后端：${label}`,
    style: { display: 'inline-flex' },
    children: jsx(StateDot, { tone, size: 9 }),
  })
}

function sectionTitle(text, key = 't') {
  // a bare span: the page column is a flex layout, no wrapper needed
  return jsx('span', {
    key,
    style: { fontSize: 13, fontWeight: 600, color: 'var(--ui-text-secondary)', margin: '6px 2px -4px' },
    children: text,
  })
}

function DataTable({ headers, rows, emptyText }) {
  if (rows.length === 0) return jsx(EmptyState, { title: emptyText })
  return jsx('div', {
    style: { overflowX: 'auto' },
    children: jsx('table', {
      style: { borderCollapse: 'collapse', width: '100%' },
      children: [jsx('thead', { key: 'head', children: headers }), jsx('tbody', { key: 'body', children: rows })],
    }),
  })
}

// ---------------------------------------------------------------------------
// page sections
// ---------------------------------------------------------------------------

function BalanceCard({ card, onToggle, onRefresh, refreshing }) {
  return jsx('div', {
    style: { ...CARD, opacity: card.configured ? 1 : 0.6 },
    children: [
      jsx('div', {
        key: 'head',
        style: { display: 'flex', alignItems: 'center', gap: 8 },
        children: [
          jsx(StateDot, { tone: card.tone }),
          jsx('span', {
            style: { fontSize: 14, fontWeight: 600, color: 'var(--ui-text-primary)' },
            children: card.name ?? card.provider_id,
          }),
          jsx('span', { style: { fontSize: 12, color: 'var(--ui-text-tertiary)' }, children: card.stateLabel }),
          jsx('span', { style: { flex: 1 } }),
          card.badge ? jsx(Badge, { text: card.badge, color: toneColor(card.tone) }) : null,
        ],
      }),
      card.kind === 'quota'
        ? jsx('div', {
            key: 'quota-windows',
            style: { display: 'flex', flexDirection: 'column', gap: 10, margin: '8px 0' },
            children: (card.windows ?? []).map((win, idx) => {
              const rem = win.remaining_percent ?? (win.used_percent != null ? Math.max(0, 100 - win.used_percent) : null)
              const barColor = rem == null ? 'var(--ui-border)' : rem < 15 ? 'var(--ui-red)' : rem < 35 ? 'var(--ui-orange)' : 'var(--ui-green)'
              return jsx('div', {
                key: `win-${idx}`,
                style: { display: 'flex', flexDirection: 'column', gap: 4 },
                children: [
                  jsx('div', {
                    style: { display: 'flex', justifyContent: 'space-between', fontSize: 12 },
                    children: [
                      jsx('span', { style: { fontWeight: 500, color: 'var(--ui-text-primary)' }, children: win.label }),
                      jsx('span', {
                        style: { color: barColor, fontWeight: 600, fontVariantNumeric: 'tabular-nums' },
                        children: rem != null ? `剩 ${Math.round(rem)}%` : '—',
                      }),
                    ],
                  }),
                  jsx('div', {
                    style: {
                      width: '100%',
                      height: 6,
                      borderRadius: 3,
                      background: 'var(--ui-border)',
                      overflow: 'hidden',
                    },
                    children: jsx('div', {
                      style: {
                        width: `${rem ?? 0}%`,
                        height: '100%',
                        borderRadius: 3,
                        background: barColor,
                        transition: 'width 0.3s ease',
                      },
                    }),
                  }),
                  win.reset_at
                    ? jsx('div', {
                        style: { fontSize: 11, color: 'var(--ui-text-tertiary)' },
                        children: `重置时间：${new Date(win.reset_at).toLocaleString('zh-CN', { hour12: false, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`,
                      })
                    : null,
                ],
              })
            }),
          })
        : jsx('div', {
            key: 'amount',
            style: { display: 'flex', alignItems: 'baseline', gap: 6 },
            children: jsx('span', {
              style: {
                fontSize: 28,
                fontWeight: 600,
                letterSpacing: '-0.02em',
                color: 'var(--ui-text-primary)',
                fontVariantNumeric: 'tabular-nums',
              },
              children: card.amountText,
            }),
          }),
      card.details?.length
        ? jsx('div', {
            key: 'details',
            style: { fontSize: 11.5, color: 'var(--ui-text-secondary)', display: 'flex', flexDirection: 'column', gap: 2 },
            children: card.details.map((d, i) => jsx('span', { key: i, children: `💡 ${d}` })),
          })
        : null,
      card.hint
        ? jsx('div', { key: 'hint', style: { fontSize: 11.5, color: 'var(--ui-text-tertiary)' }, children: card.hint })
        : null,
      jsx(ToggleRow, {
        key: 'toggle',
        label: card.kind === 'quota' ? '泡泡显示额度' : '泡泡显示余额',
        description: '关闭后 Pet 泡泡不再显示该家的状态（写入 bubble.balance_providers）',
        checked: card.shownInBubble,
        onChange: (on) => onToggle(card.provider_id, on),
      }),
      jsx('div', {
        key: 'foot',
        style: { display: 'flex', justifyContent: 'flex-end' },
        children: jsx(Button, {
          variant: 'ghost',
          disabled: refreshing,
          onClick: onRefresh,
          children: refreshing ? '刷新中…' : (card.kind === 'quota' ? '刷新额度' : '刷新余额'),
        }),
      }),
    ],
  })
}

function TodayCard({ view }) {
  const tokens = view.tokens ?? {}
  const metrics = [
    ['轮次', view.turns],
    ['输入', tokens.input],
    ['输出', tokens.output],
    ['推理', tokens.reasoning],
    ['缓存读', tokens.cache_read],
    ['缓存写', tokens.cache_write],
  ]
  return jsx('div', {
    style: CARD,
    children: [
      jsx('div', {
        key: 'head',
        style: { display: 'flex', alignItems: 'center', gap: 8 },
        children: [
          jsx('span', { style: { fontSize: 13, color: 'var(--ui-text-tertiary)' }, children: '今日费用' }),
          jsx(EstimateBadge, {}),
        ],
      }),
      jsx('div', {
        key: 'amount',
        style: { display: 'flex', alignItems: 'baseline', gap: 6 },
        children: [
          jsx('span', {
            style: {
              fontSize: 32,
              fontWeight: 600,
              letterSpacing: '-0.02em',
              color: 'var(--ui-text-primary)',
              fontVariantNumeric: 'tabular-nums',
            },
            children: view.amountText,
          }),
          view.currency
            ? jsx('span', { style: { fontSize: 13, color: 'var(--ui-text-tertiary)' }, children: view.currency })
            : null,
        ],
      }),
      view.basisText
        ? jsx('div', { key: 'basis', style: { fontSize: 11, color: 'var(--ui-text-quaternary)' }, children: view.basisText })
        : null,
      view.unpriced > 0
        ? jsx('div', {
            key: 'unpriced',
            style: { fontSize: 11.5, color: 'var(--ui-orange)' },
            children: `另有 ${view.unpriced} 轮未计价（未知模型或价目缺失）`,
          })
        : null,
      jsx('div', {
        key: 'metrics',
        style: { display: 'flex', flexWrap: 'wrap', gap: '6px 18px', marginTop: 4 },
        children: metrics.map(([label, value]) =>
          jsx('span', { key: label, style: { fontSize: 11.5, color: 'var(--ui-text-tertiary)' }, children: [
            `${label} `,
            jsx('span', {
              key: 'v',
              style: {
                color: 'var(--ui-text-secondary)',
                fontWeight: 500,
                fontVariantNumeric: 'tabular-nums',
              },
              children: value ?? '—',
            }),
          ] }),
        ),
      }),
    ],
  })
}

function ChartCard({ bars, days, onDaysChange, refreshing }) {
  const barRows = bars.map((bar) =>
    jsx('div', {
      key: bar.index,
      title: bar.title,
      style: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, minWidth: 0 },
      children: [
        jsx('div', {
          key: 'track',
          style: {
            width: '100%',
            maxWidth: 34,
            height: 140,
            display: 'flex',
            alignItems: 'flex-end',
            justifyContent: 'center',
          },
          children: jsx('div', {
            style: {
              width: '100%',
              height: `${bar.height}%`,
              minHeight: bar.hasValue ? 2 : 1,
              borderRadius: '6px 6px 3px 3px',
              background: bar.hasValue
                ? 'linear-gradient(180deg, var(--ui-accent) 0%, color-mix(in srgb, var(--ui-accent) 72%, transparent) 100%)'
                : 'var(--ui-stroke-secondary)',
              opacity: bar.hasValue ? 0.92 : 0.6,
              ...(bar.tokenOnly
                ? { backgroundImage: 'repeating-linear-gradient(135deg, transparent 0 3px, rgba(127,127,127,0.35) 3px 5px)' }
                : {}),
            },
          }),
        }),
        jsx('span', {
          key: 'label',
          style: { fontSize: 10.5, color: 'var(--ui-text-tertiary)', whiteSpace: 'nowrap' },
          children: formatDayLabel(bar.day),
        }),
      ],
    }),
  )
  return jsx('div', {
    style: CARD,
    children: [
      jsx('div', {
        key: 'head',
        style: { display: 'flex', alignItems: 'center', gap: 8 },
        children: [
          jsx('span', { style: { fontSize: 12, color: 'var(--ui-text-tertiary)' }, children: `近 ${days} 日估算` }),
          jsx(EstimateBadge, {}),
          jsx('span', { style: { flex: 1 } }),
          jsx(Select, {
            value: String(days),
            onValueChange: (value) => onDaysChange(Number(value)),
            children: [
              jsx(SelectTrigger, {
                key: 'trigger',
                'aria-label': '统计天数',
                style: { height: 24, fontSize: 11 },
                children: jsx(SelectValue, {}),
              }),
              jsx(SelectContent, {
                key: 'content',
                children: CHART_DAY_OPTIONS.map((option) =>
                  jsx(SelectItem, { key: option, value: String(option), children: `近 ${option} 日` }),
                ),
              }),
            ],
          }),
        ],
      }),
      refreshing
        ? jsx('div', { key: 'refreshing', style: { fontSize: 11, color: 'var(--ui-text-quaternary)' }, children: '刷新中…' })
        : null,
      jsx('div', { key: 'bars', style: { display: 'flex', alignItems: 'flex-end', gap: 10, paddingTop: 6, borderBottom: '1px solid var(--ui-stroke-tertiary)', paddingBottom: 2 }, children: barRows }),
      jsx('div', {
        key: 'note',
        style: { fontSize: 11, color: 'var(--ui-text-tertiary)' },
        children: '虚纹柱 = 仅 token 估算（当日无成交价快照）；悬停查看数值。',
      }),
    ],
  })
}

function ModelTable({ perModel }) {
  const rows = sortModelRows(perModel)
  const headers = jsx('tr', {
    key: 'head',
    children: ['模型', '轮次', '输入', '输出', '推理', '缓存读', '缓存写', '估算费用'].map((label) =>
      jsx('th', { key: label, style: TH, children: label }),
    ),
  })
  const body = rows.map((row, index) =>
    jsx('tr', {
      key: `${row.model ?? 'unknown'}-${index}`,
      children: [
        jsx('td', {
          style: { ...TD, color: 'var(--ui-text-primary)', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis' },
          children: row.model ?? '未知模型',
        }),
        jsx('td', { style: TD, children: row.turns ?? '—' }),
        jsx('td', { style: TD, children: row.input ?? '—' }),
        jsx('td', { style: TD, children: row.output ?? '—' }),
        jsx('td', { style: TD, children: row.reasoning ?? '—' }),
        jsx('td', { style: TD, children: row.cache_read ?? '—' }),
        jsx('td', { style: TD, children: row.cache_write ?? '—' }),
        jsx('td', {
          style: TD,
          children:
            row.estimated_cost_units != null
              ? formatMoney(row.estimated_cost_units, { currency: row.currency ?? null })
              : '—',
        }),
      ],
    }),
  )
  return jsx(DataTable, { headers, rows: body, emptyText: '窗口期内没有已记账的模型数据' })
}

function TurnsTable({ turns }) {
  const list = Array.isArray(turns) ? turns : []
  const headers = jsx('tr', {
    key: 'head',
    children: ['模型', '时间', '估算费用', '状态'].map((label) => jsx('th', { key: label, style: TH, children: label })),
  })
  const body = list.map((turn, index) =>
    jsx('tr', {
      key: turn.dedup_key ?? index,
      children: [
        jsx('td', {
          style: { ...TD, color: 'var(--ui-text-primary)', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis' },
          children: turn.model ?? '未知模型',
        }),
        jsx('td', { style: TD, children: formatTimestamp(turn.settled_at ?? turn.received_at) }),
        jsx('td', {
          style: TD,
          children:
            turn.estimated_cost_units != null
              ? formatMoney(turn.estimated_cost_units, { currency: turn.currency ?? null })
              : '未计价',
        }),
        jsx('td', {
          style: TD,
          children:
            turn.status === 'final'
              ? jsx('span', { style: { color: TONE_COLORS.ok, fontSize: 11.5, fontWeight: 500 }, children: 'final 最终' })
              : turn.status === 'provisional'
                ? jsx('span', { style: { color: 'var(--ui-orange)', fontSize: 11.5, fontWeight: 500 }, children: 'provisional 临时' })
                : String(turn.status ?? '—'),
        }),
      ],
    }),
  )
  return jsx(DataTable, { headers, rows: body, emptyText: '暂无已结算轮次' })
}

const QUOTE_HEADERS = ['匹配键', '输入(命中)', '输入(未命中)', '输出', '缓存写入', '币种', '来源']

function quoteTable(headersKey, rows) {
  return jsx(DataTable, {
    headers: jsx('tr', {
      key: headersKey,
      children: QUOTE_HEADERS.map((label) => jsx('th', { key: label, style: TH, children: label })),
    }),
    rows,
    emptyText: '无条目',
  })
}

function PricingTables({ pricing }) {
  if (!pricing || typeof pricing !== 'object') {
    return jsx(EmptyState, { title: '价目表不可用' })
  }
  const quoteRow = (entry, index) =>
    jsx('tr', {
      key: `${entry.match ?? entry.model ?? 'row'}-${index}`,
      children: [
        jsx('td', {
          style: { ...TD, color: 'var(--ui-text-primary)', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis' },
          children: entry.match ?? entry.model ?? '—',
        }),
        jsx('td', { style: TD, children: entry.hit ?? '—' }),
        jsx('td', { style: TD, children: entry.miss ?? '—' }),
        jsx('td', { style: TD, children: entry.out ?? '—' }),
        jsx('td', { style: TD, children: entry.write ?? '—' }),
        jsx('td', { style: TD, children: entry.currency ?? '—' }),
        jsx('td', { style: { ...TD, color: 'var(--ui-text-quaternary)' }, children: entry.source ?? '—' }),
      ],
    })
  const builtin = Array.isArray(pricing.builtin) ? pricing.builtin : []
  const custom = Array.isArray(pricing.custom) ? pricing.custom : []
  return jsx('div', {
    style: { display: 'flex', flexDirection: 'column', gap: 10 },
    children: [
      jsx('div', {
        key: 'builtin-title',
        style: { fontSize: 11, color: 'var(--ui-text-tertiary)' },
        children: '内置价目（unverified 标注 = 未经实测核对的文档价）',
      }),
      jsx('div', { key: 'builtin', children: quoteTable('builtin-head', builtin.map(quoteRow)) }),
      custom.length > 0
        ? jsx('div', {
            key: 'custom',
            children: [
              jsx('div', {
                style: { fontSize: 11, color: 'var(--ui-text-tertiary)', marginBottom: 4 },
                children: '自定义价目（替换该模型整份报价）',
              }),
              quoteTable('custom-head', custom.map(quoteRow)),
            ],
          })
        : null,
      jsx('div', {
        key: 'notes',
        style: { display: 'flex', flexDirection: 'column', gap: 2 },
        children: (Array.isArray(pricing.notes) ? pricing.notes : []).map((note, index) =>
          jsx('div', { key: index, style: { fontSize: 11, color: 'var(--ui-text-tertiary)' }, children: `· ${note}` }),
        ),
      }),
    ],
  })
}

// ---------------------------------------------------------------------------
// page assembly + wiring factory
// ---------------------------------------------------------------------------

export function profileBackendView(result, profile = 'default') {
  const row = (result?.plugins ?? []).find(item => item.name === 'pet-wallet' || item.key === 'pet-wallet' || item.name === 'whale-widget' || item.key === 'whale-widget')
  if (!row) return { ready: false, title: '当前 profile 未安装 Pet Wallet 后端',
    description: `当前 profile：${profile}。请切换到已安装的 profile，或在插件页面为此 profile 安装 Agent 半部。` }
  if (row.status !== 'enabled') return { ready: false, title: '当前 profile 未启用 Pet Wallet 后端',
    description: `当前 profile：${profile}。请在插件页面检查 Agent 开关。` }
  return { ready: true }
}

function DashboardPage({ deps }) {
  const profile = useValue(deps.$profile) || 'default'
  const connection = useValue(deps.$connection) || 'local'
  const version = useValue(deps.$version)
  const days = useValue(deps.$chartDays)
  const selected = useValue(deps.atoms.$bubbleProviders)
  const refreshing = useValue(deps.$refreshing)
  const queryClient = useQueryClient()

  const availability = useQuery({
    queryKey: ['whale-dashboard', connection, profile, 'backend', version],
    queryFn: () => deps.host.request('plugins.manage', { action: 'list', profile }),
    refetchInterval: 60_000,
    refetchOnMount: 'always',
    staleTime: 0,
    retry: 1,
  })
  const backend = availability.data ? profileBackendView(availability.data, profile) : null
  const healthQuery = useQuery({
    queryKey: ['whale-dashboard', connection, profile, 'health', version],
    queryFn: () => deps.rest('/health'),
    enabled: backend?.ready === true,
    staleTime: 0,
    refetchOnMount: 'always',
    retry: 1,
  })
  const ready = backend?.ready === true && healthQuery.isSuccess
  const health = { state: healthQuery.isSuccess ? (healthQuery.data?.ok ? 'ok' : 'degraded')
    : healthQuery.error ? 'unreachable' : 'checking', detail: healthQuery.data?.ledger_error }

  const providers = useQuery({
    enabled: ready,
    queryKey: ['whale-dashboard', connection, profile, 'providers', version],
    queryFn: () => deps.rest('/providers/status'),
    refetchInterval: 60_000,
    refetchOnMount: 'always',
    staleTime: 15_000,
    retry: 1,
  })
  const summary = useQuery({
    enabled: ready,
    queryKey: ['whale-dashboard', connection, profile, 'summary', version, days],
    queryFn: () => deps.rest(`/usage/summary?days=${days}`),
    refetchInterval: 30_000,
    refetchOnMount: 'always',
    staleTime: 15_000,
    retry: 1,
  })
  const turns = useQuery({
    enabled: ready,
    queryKey: ['whale-dashboard', connection, profile, 'turns', version],
    queryFn: () => deps.rest('/usage/turns?limit=20'),
    refetchInterval: 60_000,
    refetchOnMount: 'always',
    staleTime: 15_000,
    retry: 1,
  })
  const pricing = useQuery({
    enabled: ready,
    queryKey: ['whale-dashboard', connection, profile, 'pricing', version],
    queryFn: () => deps.rest('/pricing'),
    refetchInterval: 300_000,
    staleTime: 60_000,
    retry: 1,
  })

  const refreshAll = () => {
    deps.$version.set(version + 1)
    try {
      queryClient.invalidateQueries()
    } catch {
      /* queryClient is an optimization; the version bump alone re-fetches */
    }
  }

  const refreshBalances = async () => {
    deps.$refreshing.set(true)
    try {
      await deps.rest('/balance/refresh', { method: 'POST' })
    } catch {
      /* in-band error states carry the failure; the refetch below shows them */
    }
    deps.$version.set(deps.$version.get() + 1)
    try {
      queryClient.invalidateQueries()
    } catch {
      /* ignore */
    }
    deps.$refreshing.set(false)
  }

  const allConfiguredIds = (providers.data?.providers ?? [])
    .filter((row) => row?.configured === true)
    .map((row) => row.provider_id)

  const setBubbleShow = (providerId, on) => {
    if ((deps.$profile.get() || 'default') !== profile || (deps.$connection.get() || 'local') !== connection) return
    const previous = normalizeSelectedProviders(deps.atoms.$bubbleProviders.get?.() ?? [])
    const next = toggleBubbleProvider(previous, providerId, on, allConfiguredIds)
    deps.atoms.$bubbleProviders.set(next) // optimistic runtime mirror (bubble updates now)
    void Promise.resolve(
      deps.rest('/config', { method: 'PUT', body: { bubble: { balance_providers: next } } }),
    )
      .then((merged) => {
        if ((deps.$profile.get() || 'default') !== profile || (deps.$connection.get() || 'local') !== connection) return
        const persisted = merged?.bubble?.balance_providers
        if (Array.isArray(persisted)) deps.atoms.$bubbleProviders.set(normalizeSelectedProviders(persisted))
      })
      .catch(() => {
        deps.atoms.$bubbleProviders.set(previous) // revert on failure
        try {
          deps.host?.notify?.({ message: 'Pet Wallet：泡泡显示列表写入失败' })
        } catch {
          /* toast is best-effort */
        }
      })
  }

  const cards = providerCards(providers.data?.providers ?? [], selected)
  const today = todayCardView(summary.data)
  const bars = barHeights(summary.data?.estimated_days ?? [], 120)

  const sections = []

  // header (renders in EVERY state, ai-usage-tracker discipline)
  sections.push(
    jsx('div', {
      key: 'header',
      style: { display: 'flex', alignItems: 'center', gap: 12, margin: '2px 2px 0' },
      children: [
        jsx('span', {
          style: {
            fontSize: 24,
            fontWeight: 700,
            letterSpacing: '-0.02em',
            color: 'var(--ui-text-primary)',
          },
          children: `🐾 Pet Wallet 用量 · ${profile}`,
        }),
        jsx(HealthDot, { health }),
        jsx('span', { style: { flex: 1 } }),
        jsx(Button, { variant: 'secondary', onClick: refreshAll, children: '刷新' }),
      ],
    }),
  )

  const unavailable = availability.error
    ? { title: '无法检查当前 profile 的插件状态', description: String(availability.error?.message ?? availability.error) }
    : backend && !backend.ready ? backend
    : healthQuery.error ? { title: '当前 profile 的记账后端尚未就绪',
      description: `当前 profile：${profile}。${healthQuery.error?.message ?? healthQuery.error}` }
    : null
  if (unavailable || !ready) {
    sections.push(jsx(unavailable ? ErrorState : EmptyState, {
      key: 'backend-state', title: unavailable?.title ?? '正在连接当前 profile 的记账后端',
      description: unavailable?.description ?? `当前 profile：${profile}`,
      children: jsx(Button, { variant: 'secondary', onClick: refreshAll, children: '重新检查' }),
    }))
    return jsx('div', { style: { display: 'flex', flexDirection: 'column', gap: 20, padding: 16 }, children: sections })
  }

  if (providers.error && !providers.data) {
    sections.push(
      jsx(ErrorState, {
        key: 'providers-error',
        title: '余额状态加载失败',
        description: `${providers.error?.message ?? providers.error} —— 记账后端（whale-widget dashboard）可能未运行。`,
        children: jsx(Button, { variant: 'secondary', onClick: () => providers.refetch(), children: '重试' }),
      }),
    )
  } else if (providers.isLoading) {
    sections.push(
      jsx('div', {
        key: 'providers-loading',
        style: { fontSize: 12, color: 'var(--ui-text-quaternary)' },
        children: '加载余额状态…',
      }),
    )
  } else if (cards.length === 0) {
    sections.push(
      jsx(EmptyState, {
        key: 'providers-empty',
        title: '暂无已知 Provider',
        description: 'whale_core.providers.registry 没有可用模板',
      }),
    )
  } else {
    sections.push(sectionTitle('订阅与额度', 'balances-title'))
    sections.push(
      jsx('div', {
        key: 'cards',
        style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 },
        children: cards.map((card) =>
          jsx(BalanceCard, {
            key: card.provider_id,
            card,
            refreshing,
            onRefresh: () => void refreshBalances(),
            onToggle: setBubbleShow,
          }),
        ),
      }),
    )
    sections.push(
      jsx('div', {
        key: 'bubble-hint',
        style: { fontSize: 11, color: 'var(--ui-text-tertiary)' },
        children: `泡泡显示规则：${selected.length === 0 ? '未选择 = 显示全部已配置 Provider' : `仅显示 ${selected.join('、')}`}（写入配置 bubble.balance_providers）`,
      }),
    )
  }

  // today overview + chart
  if (summary.error && !summary.data) {
    sections.push(
      jsx(ErrorState, {
        key: 'summary-error',
        title: '用量汇总加载失败',
        description: `${summary.error?.message ?? summary.error}`,
        children: jsx(Button, { variant: 'secondary', onClick: () => summary.refetch(), children: '重试' }),
      }),
    )
  } else if (summary.isLoading) {
    sections.push(
      jsx('div', {
        key: 'summary-loading',
        style: { fontSize: 12, color: 'var(--ui-text-quaternary)' },
        children: '加载今日概览…',
      }),
    )
  } else {
    sections.push(sectionTitle('今日概览', 'today-title'))
    sections.push(jsx(TodayCard, { key: 'today', view: today }))
    sections.push(
      jsx(ChartCard, {
        key: 'chart',
        bars,
        days,
        refreshing: summary.isFetching === true,
        onDaysChange: (value) => deps.$chartDays.set(value),
      }),
    )
  }

  // model split + recent turns
  if (turns.error && !turns.data) {
    sections.push(
      jsx(ErrorState, {
        key: 'turns-error',
        title: '轮次明细加载失败',
        description: `${turns.error?.message ?? turns.error}`,
        children: jsx(Button, { variant: 'secondary', onClick: () => turns.refetch(), children: '重试' }),
      }),
    )
  } else if (turns.isLoading) {
    sections.push(
      jsx('div', {
        key: 'turns-loading',
        style: { fontSize: 12, color: 'var(--ui-text-quaternary)' },
        children: '加载轮次明细…',
      }),
    )
  } else {
    sections.push(sectionTitle('模型分布（近窗口期）', 'models-title'))
    sections.push(jsx(ModelTable, { key: 'models', perModel: summary.data?.per_model ?? [] }))
    sections.push(sectionTitle('最近轮次（前 20）', 'turns-title'))
    sections.push(jsx(TurnsTable, { key: 'turns', turns: turns.data?.turns ?? [] }))
  }

  // pricing
  sections.push(sectionTitle('价目表（per 1M tokens）', 'pricing-title'))
  if (pricing.error && !pricing.data) {
    sections.push(
      jsx('div', {
        key: 'pricing-error',
        style: { fontSize: 11, color: 'var(--ui-text-quaternary)' },
        children: `价目表加载失败：${pricing.error?.message ?? pricing.error}`,
      }),
    )
  } else if (pricing.isLoading) {
    sections.push(
      jsx('div', {
        key: 'pricing-loading',
        style: { fontSize: 12, color: 'var(--ui-text-quaternary)' },
        children: '加载价目表…',
      }),
    )
  } else {
    sections.push(jsx(PricingTables, { key: 'pricing', pricing: pricing.data }))
  }

  return jsx('div', {
    className: 'whale-widget-dashboard',
    style: {
      height: '100%',
      overflowY: 'auto',
      boxSizing: 'border-box',
      padding: '24px 28px 44px',
      fontFamily: FONT_STACK,
    },
    children: jsx('div', {
      style: { maxWidth: 920, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 },
      children: sections,
    }),
  })
}

function ChipNavigate({ children, onNavigate }) {
  return jsx('span', {
    className: 'whale-widget-chip-nav',
    title: onNavigate ? '打开 Pet Wallet 用量面板' : undefined,
    onClick: onNavigate
      ? (event) => {
          event?.preventDefault?.()
          try {
            onNavigate()
          } catch {
            /* navigation must never break the chip */
          }
        }
      : undefined,
    style: { display: 'inline-flex', cursor: onNavigate ? 'pointer' : 'default' },
    children,
  })
}

/**
 * Build the dashboard contributions.
 *
 * @param {object} deps
 *   rest   — Hermes ctx.rest(path, opts?) (namespace-relative paths)
 *   host   — SDK host (navigate is feature-detected; notify optional)
 *   atoms  — { $health, $bubbleProviders } shared with main.js
 * @returns { contribution, navContribution, wrapChip }
 */
export function createDashboard({ rest, host, atoms }) {
  // per-instance UI atoms (nanostores) — no react hooks anywhere on the page.
  const $version = atom(0)
  const $chartDays = atom(7)
  const $refreshing = atom(false)

  const $profile = host?.state?.profile ?? atom('default')
  const $connection = host?.state?.connectionId ?? atom('local')
  const deps = { rest, host, atoms: atoms ?? {}, $profile, $connection, $version, $chartDays, $refreshing }

  const contribution = {
    id: 'dashboard',
    area: ROUTES_AREA,
    title: ROUTE_TITLE,
    data: { path: ROUTE_PATH },
    render: () => jsx(DashboardPage, { deps }),
  }
  const navContribution = {
    id: 'nav',
    area: SIDEBAR_NAV_AREA,
    data: { path: ROUTE_PATH, label: ROUTE_TITLE, codicon: 'credit-card' },
  }

  /** Statusbar chip wrapper: click → the dashboard page (feature-detected). */
  const wrapChip = (children) =>
    jsx(ChipNavigate, {
      onNavigate: typeof host?.navigate === 'function' ? () => host.navigate(ROUTE_PATH) : null,
      children,
    })

  return { contribution, navContribution, wrapChip }
}
