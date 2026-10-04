/**
 * Default bubble content (M7) — built-in sequences shown before the user
 * configures their own (the editor lands in M12). Definitions are validated
 * at module load; a regression here fails fast in tests, not at runtime.
 */
import { validateBubble } from './schema.js'

export const DEFAULT_GREETING = validateBubble({
  v: 1,
  tapAdvance: true,
  items: [
    {
      kind: 'custom',
      modules: [
        { type: 'text', text: '嗨，我是记账小鲸鱼 🐋', style: { bold: true, size: 16 } },
        { type: 'text', text: '点点我，看看花了多少～', style: { size: 14 } },
      ],
    },
    {
      kind: 'choice',
      options: [
        { w: 3, item: { kind: 'custom', modules: [{ type: 'balance', row: 0, style: { bold: true } }, { type: 'text', row: 1, text: '这是 API 余额（真实观测）' }] } },
        { w: 2, item: { kind: 'custom', modules: [{ type: 'estimated_today', row: 0, style: { bold: true } }, { type: 'text', row: 1, text: '这是今日估算消费（估算值）' }] } },
      ],
    },
    { kind: 'custom', modules: [{ type: 'text', text: '有预算和余额提醒的话，我会第一时间告诉你！', style: { size: 14 } }] },
  ],
})

export const DEFAULT_TURN_COST = validateBubble({
  v: 1,
  tapAdvance: false,
  items: [
    {
      kind: 'custom',
      modules: [
        { type: 'text', text: '本轮消耗', style: { size: 12, color: '#5b6472' } },
        { type: 'turn_cost', row: 1, style: { bold: true, size: 17 } },
        { type: 'text', row: 2, text: '（估算值）', style: { size: 11, color: '#8a93a1' } },
      ],
    },
  ],
})

export const DEFAULT_IDLE_LINES = validateBubble({
  v: 1,
  tapAdvance: false,
  items: [
    {
      kind: 'custom',
      modules: [
        {
          type: 'random_text',
          texts: ['今天也一起加油呀～', '记得看看今日花了多少哦', '余额不足时我会提醒你的！', '咕噜咕噜…', '点我可以看余额和今日消费'],
        },
      ],
    },
  ],
})

/** Standing alerts (Goal pass P0-2) — persisted server-side, ttl 0. */
export const DEFAULT_BUDGET_REACHED = validateBubble({
  v: 1,
  tapAdvance: false,
  items: [
    {
      kind: 'custom',
      modules: [
        { type: 'text', text: '今日预算已达 ⚠', style: { bold: true, color: '#b3261e' } },
        { type: 'estimated_today', row: 1, style: { bold: true } },
        { type: 'text', row: 2, text: '（估算值；可在设置中调整预算）', style: { size: 10, color: '#8a93a1' } },
      ],
    },
  ],
})

export const DEFAULT_BALANCE_LOW = validateBubble({
  v: 1,
  tapAdvance: false,
  items: [
    {
      kind: 'custom',
      modules: [
        { type: 'text', text: '余额不足 ⚠', style: { bold: true, color: '#b3261e' } },
        { type: 'balance', row: 1, style: { bold: true } },
        { type: 'text', row: 2, text: '（API 实测余额；记得充值哦）', style: { size: 10, color: '#8a93a1' } },
      ],
    },
  ],
})
