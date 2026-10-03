/**
 * Statusbar chip — connectivity + ledger-availability surface.
 *
 * Shows "Whale widget" plus dashboard-half health and ingest state:
 *   ● ok / ◐ degraded (ledger_error) / ○ unreachable / ◌ checking,
 *   plus「记账暂不可用」while the ingest client is in the dead-letter state.
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

function ingestLabel(ingest) {
  if (!ingest?.unavailable) return ''
  const dead = ingest.deadLetters ?? 0
  return ` · 记账暂不可用${dead > 0 ? ` (${dead})` : ''}`
}

export function WhaleChip({ $health, $ingest }) {
  const health = useValue($health)
  const ingest = $ingest ? useValue($ingest) : { unavailable: false, deadLetters: 0 }
  const glyph = GLYPHS[health.state] ?? GLYPHS.checking
  return jsx('span', {
    className: 'whale-widget-chip',
    title: 'Whale widget — dashboard connectivity',
    style: { display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'default' },
    children: `${glyph} Whale widget · ${healthLabel(health)}${ingestLabel(ingest)}`,
  })
}

export function renderWhaleChip($health, $ingest) {
  return jsx(WhaleChip, { $health, $ingest })
}
