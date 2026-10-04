/**
 * Whale pane (M5/M7/M9 shell — pet-hosting de-roling, DR-15).
 *
 * ROLE NOTE (架构修订 DR-15, docs/research/HERMES_PET_SYSTEM.md): the whale
 * CHARACTER is carried by Hermes' built-in pet system wearing our whale skin
 * pack (pets/<slug>/, Codex-format spritesheet). This pane no longer renders
 * the self-made SVG whale actor (ui/whale-actor.js retired) — it is the pet's
 * 随身账本 (pocket ledger): title row + bubble layer + data card, with the mood
 * state machine surfacing only as the header accent dot + bubbles. Users drag
 * this floating pane next to the Hermes pet for the "pet + ledger" combo.
 *
 * SDK probe conclusion (recorded M5, hermes-agent file:line):
 *   `PANES_AREA = 'panes'` (sdk/index.ts:1979) + registration data
 *   `placement: 'floating'` renders a NON-tiling, fixed-position, DRAGGABLE
 *   card above the layout tree — no tab, docks nowhere, viewport-clamped with
 *   an always-reachable handle (pane-shell/tree/renderer/floating-rect.ts,
 *   floating-adoption.test.ts:43). That native card IS the ledger container;
 *   plugin-side dragging/position persistence is unnecessary (core owns it).
 *   OS-level transparency/topmost stays Phase 2 (Python-spawned process).
 *
 * The pane renders: title row (🐋 鲸鱼管家 + mood→accent dot, moodAccent() in
 * controller.js) + bubble layer (M7 queue) + data card (balance five-state +
 * today estimate, DATA_MODEL §8.3 semantics via balance-view.js). Interaction
 * wiring (press/click → state machine + bubble advance + sound hook) is
 * injected via `controller` built in main.js; a tap anywhere on the panel is
 * the pet-interaction surface. All display mapping is pure and tested
 * elsewhere.
 */
import { useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { moodAccent } from './controller.js'
import { balanceView, salvageView, todayView } from './balance-view.js'
import { BubbleLayer } from './bubble/renderer.js'

export const PANE_ID = 'whale-widget-pane'

const PANE_HINT =
  '角色由 Hermes 内置宠物承载（见 docs/research/HERMES_PET_SYSTEM.md）；' +
  '本面板是其随身账本，建议拖到宠物旁。点击面板与它互动（泡泡 + 音效）。'

function toneColor(tone) {
  switch (tone) {
    case 'ok': return '#2e7d32'
    case 'zero': return '#6b7280'
    case 'stale': return '#9a8c1f'
    case 'error': return '#b3261e'
    default: return '#5b6472'
  }
}

/** Title row: 「🐋 鲸鱼管家」+ mood→accent dot (mood semantics, not a face). */
function HeaderRow({ mood }) {
  return jsxs('div', {
    className: 'whale-pane-header',
    title: PANE_HINT,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      alignSelf: 'stretch',
      fontSize: 12,
      fontWeight: 600,
      color: '#25384c',
    },
    children: [
      jsx('span', { key: 't', children: '🐋 鲸鱼管家' }),
      jsx('span', {
        key: 'dot',
        'data-mood': mood,
        role: 'img',
        'aria-label': `mood: ${mood}`,
        style: {
          width: 8,
          height: 8,
          borderRadius: '50%',
          flexShrink: 0,
          background: moodAccent(mood),
          transition: 'background 160ms ease',
        },
      }),
    ],
  })
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
 * Full pane body (de-roled): the whole panel is the interaction surface —
 * press/release/click feed the mood machine + bubble queue + sound hook via
 * `controller`. No character/actor is rendered here (the Hermes pet carries
 * the role); mood shows up as the header dot's accent colour.
 */
export function WhalePane({ $balance, $summary, $dashboard, $whale, $bubble, controller }) {
  const whale = useValue($whale)
  const bubble = useValue($bubble)
  return jsxs('div', {
    className: 'whale-widget-pane',
    role: 'button',
    tabIndex: 0,
    onPointerDown: () => controller.press(),
    onPointerUp: () => controller.release(),
    onClick: () => controller.click(),
    style: {
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 10,
      padding: 8,
      userSelect: 'none',
    },
    children: [
      jsx(HeaderRow, { mood: whale.mood }),
      jsx(BubbleLayer, { model: bubble }),
      jsx(DataCard, { $balance, $summary, $dashboard }),
    ],
  })
}
