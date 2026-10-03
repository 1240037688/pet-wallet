/**
 * Balance/summary → view-model mapping (M5). PURE: the pane renders whatever
 * this returns; tests pin the DATA_MODEL §8.3 semantics here.
 *
 * Hard rules:
 *   - an API failure is NEVER zero: error/stale keep the last known
 *     `observed_balance_units` and carry a tone + hint;
 *   - unknown/unconfigured renders `—` plus a configuration hint;
 *   - estimated figures always carry the `估算` badge text (never presented
 *     as a real bill);
 *   - Python half unreachable → focusedUsage salvage marked `未记账`.
 */
import { formatMoney } from '../core/money.js'

/**
 * Map GET /balance payload → { text, tone, badge, hint }.
 * tone: ok | stale | error | unknown | zero
 */
export function balanceView(balance) {
  if (!balance) return { text: '—', tone: 'unknown', badge: null, hint: '等待数据…' }
  const cred = balance.credential ?? {}
  if (cred.configured === false) {
    return { text: '—', tone: 'unknown', badge: null, hint: '未配置 Provider 凭据' }
  }
  const units = balance.observed_balance_units
  switch (balance.state) {
    case 'ok':
      return { text: formatMoney(units, { currency: balance.currency }), tone: 'ok', badge: null, hint: null }
    case 'zero':
      // a REAL zero observation — distinct from failure by definition
      return { text: formatMoney(0, { currency: balance.currency }), tone: 'zero', badge: null, hint: '余额为 0（API 实测）' }
    case 'stale':
      return {
        text: formatMoney(units, { currency: balance.currency }),
        tone: 'stale',
        badge: '未刷新',
        hint: '数据已过期（上次获取见时间戳）',
      }
    case 'error':
      return {
        text: formatMoney(units, { currency: balance.currency }),
        tone: 'error',
        badge: '获取失败',
        hint: `余额 API 出错（${balance.error?.kind ?? 'error'}）；显示最近一次已知值`,
      }
    default:
      return { text: '—', tone: 'unknown', badge: null, hint: '状态未知' }
  }
}

/**
 * Map GET /usage/summary payload → today card view.
 * estimated_today_units NULL → `—` (no fabricated zeros).
 */
export function todayView(summary) {
  if (!summary) return { text: '—', estimated: true, turns: 0, hint: null }
  return {
    text: formatMoney(summary.estimated_today_units, { currency: todayCurrency(summary) }),
    estimated: true,
    turns: summary.turns_today ?? 0,
    hint: summary.unpriced_today > 0 ? `另有 ${summary.unpriced_today} 轮未计价` : null,
  }
}

function todayCurrency(summary) {
  const buckets = summary?.estimated_today ?? summary?.cost_buckets ?? []
  const first = Array.isArray(buckets) ? buckets[0] : null
  return first?.currency ?? null
}

/**
 * Salvage view when the Python half is unreachable: host.state.focusedUsage
 * (display-grade token counts only — NO cost is invented).
 */
export function salvageView(focusedUsage) {
  if (!focusedUsage) return null
  const input = focusedUsage.input ?? focusedUsage.input_tokens ?? null
  const output = focusedUsage.output ?? focusedUsage.output_tokens ?? null
  if (input === null && output === null) return null
  return {
    text: `本会话 tokens: ${input ?? '—'} 入 / ${output ?? '—'} 出`,
    estimated: false,
    badge: '未记账',
    hint: '记账后端不可达；仅显示会话 token 快照（无法计价）',
  }
}
