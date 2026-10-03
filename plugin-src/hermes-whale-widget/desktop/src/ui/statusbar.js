/**
 * Statusbar chip — the M0 placeholder surface.
 *
 * Shows "Whale widget placeholder" plus dashboard-half connectivity:
 *   ● ok / ◐ degraded (ledger_error) / ○ unreachable / ◌ checking
 * Real numeric display (estimated today / observed balance) arrives in M5.
 */
import { useValue } from '@hermes/plugin-sdk'
import { jsx } from 'react/jsx-runtime'

const GLYPHS = {
  ok: '●',
  degraded: '◐',
  unreachable: '○',
  checking: '◌',
}

function healthLabel(health) {
  switch (health.state) {
    case 'ok':
      return `ok · v${health.version ?? '?'} (schema ${health.schema_version ?? '?'})`
    case 'degraded':
      return `degraded${health.detail ? ' · ledger error' : ''}`
    default:
      return health.state
  }
}

export function WhaleChip({ $health }) {
  const health = useValue($health)
  const glyph = GLYPHS[health.state] ?? GLYPHS.checking
  return jsx('span', {
    className: 'whale-widget-chip',
    title: 'Whale widget — dashboard connectivity',
    style: { display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'default' },
    children: `${glyph} Whale widget placeholder · ${healthLabel(health)}`,
  })
}

export function renderWhaleChip($health) {
  return jsx(WhaleChip, { $health })
}
