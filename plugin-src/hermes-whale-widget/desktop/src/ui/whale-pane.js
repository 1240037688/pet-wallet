/**
 * Whale pane (M5/M6/M7 integration shell).
 *
 * SDK probe conclusion (recorded M5, hermes-agent file:line):
 *   `PANES_AREA = 'panes'` (sdk/index.ts:1979) + registration data
 *   `placement: 'floating'` renders a NON-tiling, fixed-position, DRAGGABLE
 *   card above the layout tree — no tab, docks nowhere, viewport-clamped with
 *   an always-reachable handle (pane-shell/tree/renderer/floating-rect.ts,
 *   floating-adoption.test.ts:43). That native card IS the whale container;
 *   plugin-side dragging/position persistence is unnecessary (core owns it).
 *   OS-level transparency/topmost stays Phase 2 (Python-spawned process).
 *
 * The pane renders: whale actor (mood machine) + bubble layer (M7 queue) +
 * data card (balance five-state + today estimate, DATA_MODEL §8.3 semantics
 * via balance-view.js). All display mapping is pure and tested elsewhere.
 */
import { useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { WhaleActor } from './whale-actor.js'
import { balanceView, salvageView, todayView } from './balance-view.js'
import { BubbleLayer } from './bubble/renderer.js'

export const PANE_ID = 'whale-widget-pane'

function toneColor(tone) {
  switch (tone) {
    case 'ok': return '#2e7d32'
    case 'zero': return '#6b7280'
    case 'stale': return '#9a8c1f'
    case 'error': return '#b3261e'
    default: return '#5b6472'
  }
}

function DataCard({ $balance, $summary, $dashboard }) {
  const balance = useValue($balance)
  const summary = useValue($summary)
  const dashboard = useValue($dashboard)

  const unreachable = dashboard?.state === 'unreachable'
  const bv = balanceView(unreachable ? null : balance)
  const tv = unreachable ? salvageView(null) : todayView(summary)
  const todayText = tv ? tv.text : '—'

  return jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 },
    children: [
      jsx('div', {
        style: { display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 },
        title: bv.hint ?? undefined,
        children: [
          jsx('span', { key: 'k', style: { color: '#5b6472' }, children: '余额' }),
          jsxs('span', {
            key: 'v',
            style: { fontWeight: 600, color: toneColor(bv.tone) },
            children: [bv.text, bv.badge ? ` ⚠${bv.badge}` : ''],
          }),
        ],
      }),
      jsx('div', {
        style: { display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 },
        title: tv?.hint ?? undefined,
        children: [
          jsx('span', { key: 'k', style: { color: '#5b6472' }, children: '今日' }),
          jsxs('span', {
            key: 'v',
            style: { fontWeight: 600, color: '#333c48' },
            children: [
              todayText,
              tv?.estimated ? jsx('span', { key: 'b', style: { marginLeft: 4, fontSize: 10, padding: '1px 4px', borderRadius: 4, background: '#e8f1fb', color: '#3f6f9f' }, children: '估算' }) : null,
              unreachable && tv ? jsx('span', { key: 'u', style: { marginLeft: 4, fontSize: 10, padding: '1px 4px', borderRadius: 4, background: '#fdeaea', color: '#b3261e' }, children: tv.badge ?? '未记账' }) : null,
            ],
          }),
        ],
      }),
      jsx('div', { style: { color: '#8a93a1', fontSize: 10 }, children: unreachable ? '记账后端不可达 — 显示会话快照' : `turns today: ${tv?.turns ?? 0}` }),
    ],
  })
}

/**
 * Full pane body. Interaction wiring (press/click → state machine + bubble
 * advance) is injected via `controller` built in main.js (keeps this file
 * render-pure and the machine testable).
 */
export function WhalePane({ $balance, $summary, $dashboard, $whale, $bubble, controller }) {
  const whale = useValue($whale)
  const bubble = useValue($bubble)
  return jsxs('div', {
    className: 'whale-widget-pane',
    style: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: 8 },
    children: [
      jsx(BubbleLayer, { model: bubble }),
      jsx(WhaleActor, {
        mood: whale.mood,
        onPress: () => controller.press(),
        onRelease: () => controller.release(),
        onClick: () => controller.click(),
      }),
      jsx(DataCard, { $balance, $summary, $dashboard }),
    ],
  })
}
