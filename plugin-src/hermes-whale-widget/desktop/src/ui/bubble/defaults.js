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
        { type: 'random_text', texts: ['嗨，我是你的 Pet 账本管家 🐾', '主人好呀！今天写代码辛苦啦 💻', 'Pet Wallet 随时为你记账 ✨'], style: { bold: true, size: 15 } },
        { type: 'text', text: '点点我，看看当前额度与花费～', style: { size: 13 } },
      ],
    },
    {
      kind: 'choice',
      options: [
        { w: 3, item: { kind: 'custom', modules: [{ type: 'balance', row: 0, style: { bold: true } }, { type: 'text', row: 1, text: '当前订阅与额度（实时观测）' }] } },
        { w: 2, item: { kind: 'custom', modules: [{ type: 'estimated_today', row: 0, style: { bold: true } }, { type: 'text', row: 1, text: '今日记账估算消费' }] } },
      ],
    },
    { kind: 'custom', modules: [{ type: 'text', text: '双击泡泡或点击侧边栏可直达钱包面板哦！', style: { size: 13 } }] },
  ],
})

export const DEFAULT_QUOTA_REPORT = validateBubble({
  v: 1,
  tapAdvance: false,
  items: [
    {
      kind: 'custom',
      modules: [
        { type: 'text', text: '📊 订阅与额度播报', style: { bold: true, size: 13, color: '#1d4ed8' } },
        { type: 'balance', row: 1, style: { bold: true, size: 15 } },
        { type: 'text', row: 2, text: '（点击我继续查看）', style: { size: 11, color: '#6b7280' } },
      ],
    },
  ],
})

export const DEFAULT_WALLET_OVERVIEW = validateBubble({
  v: 1,
  tapAdvance: false,
  items: [
    {
      kind: 'custom',
      modules: [
        { type: 'text', text: '💰 今日消费概览', style: { bold: true, size: 13, color: '#047857' } },
        { type: 'estimated_today', row: 1, style: { bold: true, size: 15 } },
        { type: 'text', row: 2, text: '记账本已为你稳妥记录', style: { size: 11, color: '#6b7280' } },
      ],
    },
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
          texts: [
            '今天也一起加油呀～ 🚀',
            '记得劳逸结合，喝口水休息下 🍵',
            '额度充足，尽情探索吧！',
            'Pet 管家正在为你守护钱包 🛡️',
            '点我可以看当前额度和今日消费 🐾',
            '咕噜咕噜… 默默陪着你写代码 ✨',
          ],
        },
      ],
    },
  ],
})

export const DEFAULT_COMBO_LINES = validateBubble({
  v: 1,
  tapAdvance: false,
  items: [
    {
      kind: 'custom',
      modules: [
        {
          type: 'random_text',
          texts: [
            '戳我好多次啦！有在认真写代码吗～ 🐾',
            '哎呀，别挠啦，毛都要掉光了！😆',
            '钱包管家正在盯着你的余额呢，别摸鱼～ 👀',
            '连击连击！本 Pet 要被你点晕啦 🌀',
            '再点我，我就把你的消费账单念出来哦！📜',
          ],
          style: { bold: true },
        },
      ],
    },
  ],
})

export const DEFAULT_EASTER_EGG = validateBubble({
  v: 1,
  tapAdvance: false,
  items: [
    {
      kind: 'custom',
      modules: [
        { type: 'text', text: '⚡ 达成神级连击！', style: { bold: true, size: 15, color: '#d97706' } },
        { type: 'text', text: 'Pet 为你释放了「代码无 Bug」专属 Buff 🌟', style: { size: 13 } },
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
