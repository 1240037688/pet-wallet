# DeepSeek-Balance-Whale-Widget 源码级逆向分析

> 分析对象：`E:\hermes_plugin\hermes-whale-widget\references\DeepSeek-Balance-Whale-Widget`（版本 0.3.18，main 分支，只读）
> 分析日期：2026-10-03
> 代码规模：宿主 `lib/index.js` 4198 行 + 记账内核 `lib/accounting.mjs` 289 行 + 前端 `assets/whale-widget.js` 17294 行（单文件 IIFE，零依赖零构建）。
> 所有行号引用均基于当前 checkout。未验证的点已显式标注。

---

## 产品能力清单（摘要，用于与 Hermes 可行性对照）

1. **常驻桌宠挂件**：右下角鲸鱼（cut-out PNG，气泡由 SVG 代码绘制），随宿主页面每次打开自动出现；点击/拖拽/吸附/翻转/缩放/按压 Q 弹。
2. **余额显示**：60s 自动刷新 + 点击手动刷新；API key 与「账号登录态」双通道（key 优先，任一失败回退另一条）；25s 服务端缓存 + 在途请求去重 + 瞬时失败沿用旧值（stale 标记）；余额变化触发数字滚动动画（700ms ease-out）+ 变化泡泡。
3. **今日已用（余额差分记账）**：不需要任何流水 API——把每次余额观测的**下降额**累计为消费、**上升额**（充值/赠金）单独记录不冲销消费；检测到余额上升时提示「待核对余额调整」，由用户按实际到账金额**显式校正**；8 位小数定点记账、显示两位；按北京时间跨天归档；逐轮明细留 90 天/2 万条、逐日汇总留 365 天，超期归档不删除；按「密钥指纹」分账本。
4. **每轮对话消耗**：监听宿主会话事件，取模型**真实 usage**（input/cache/output/reasoning tokens），按峰谷价目表（可被自定义单价覆盖）换算金额，一轮结束（turn/end）结算，弹消耗泡泡 + 任务结束音；seq 机制防刷新后重复弹。
5. **Usage Ledger**：今日模型消费、近 7 天、全部记录；模型占比条 + 近 30 天柱状图 + 按日展开逐条明细；按日期或模型名搜索。
6. **自定义泡泡（核心）**：点击序列（首次点击泡 + 「再次点击」队列）；两泡可并列为 A/B 加权随机；每泡由若干模块按行组成（文本/超链接/随机语句/图片/随机图片/余额/赠金/充值余额/今日已用/峰谷/对话名/自定义模型余额·今日·额度·订阅额度）；逐模块字体/字号/粗斜下划线/跑马灯渐变色/底色；拖拽排版（每行≤6 模块、每泡≤6 行、图片独占一行且全泡唯一）；模块库复用；悬浮快捷编辑；可选「点按角色推进队列」。
7. **提醒**：余额预警（balance < threshold）、今日预算（today_usage >= budget）、每轮消耗、Agent 等待用户回答（提问/授权）——全部走同一个「系统泡泡优先队列」（预算 > 预警 > 消耗 > 等待），泡泡不可用时退化为居中卡片；各提醒内容均可模块化编辑（含图片模块）；同一未回答提问只响一次（localStorage 去重，刷新不重响）。
8. **音效**：按压/松开、任务结束音、提问音、授权音四类事件；Web Audio 预解码同步起播、按压音剩余时长精确排期松开音；一条全局音量 + 三条事件音量（未显式设置则跟随全局）；每音效独立「响不响」开关；自定义音效组（槽位可留空=静音）+ 音频片段导入（可视化裁剪/试听）。
9. **角色与图片**：自定义角色图（png/gif/apng，导入裁剪、置顶、删除、回退默认）；泡泡图库（内置 2 张语义图 + 用户上传）。
10. **多厂商自定义 API**：34 个厂商模板（凭据名/币种/接口/JSON 字段路径/scale/探活地址自动带好）；「有余额接口」与「无余额接口（探活 + 会话估算）」两类；订阅额度接口（单/多窗口已用% + 重置倒计时）；手动额度（token 口径 input+cacheRead+output，不重置/每日/每月）；逐模型余额预警/今日预算；可选自定义单价（缓存命中/未命中/输出，CNY 或 USD+汇率，统一折 CNY 记账）。
11. **安全边界**：所有路由过浏览器信任栅栏（回环 Host / 拒跨站 / Origin=Host）；写请求仅限本机；凭据只发往厂商模板内置端点（自定义地址需本机显式确认）；密钥永不落插件配置文件。
12. **移动端**：触摸拖拽（自研接管防页面滚动误判）、长按 1.5s 唤出菜单、编辑器长按 0.4s 拖拽排序、去点击高亮。

---

## 0. 总体架构

```
DSH Web 页面（index.html）
  └─ <script defer src="/dsh-whale/widget.js">   ← tapIndex 注入（web）/ 结构化注入行（Electron 桌面）
       └─ assets/whale-widget.js（前端，IIFE，全部 UI/交互/轮询/音效都在浏览器）
            ↕ fetch /dsh-whale/*（23 条路由，全部过信任栅栏）
lib/index.js（宿主侧 Cordis 插件：路由 + 记账调用 + 余额拉取 + 资产服务 + 会话事件监听）
  └─ lib/accounting.mjs（记账内核：定点金额 + 观测/校正账本，纯函数、不碰文件）
```

- 插件形态：标准 DSH bundle（npm 包 + `cordis.patch.yml` 挂载声明，见 `cordis.patch.yml:13-15`；`package.json:29-33` 的 `dsh.bundle.patch`）。前端由宿主**按 mtime 热读取**（`lib/index.js:613-630`），改前端只需硬刷新，改宿主要重启。
- 运行时数据全在 `$DSH_HOME`（默认 `~/.dsh`）：`.dshw-size.json`（外观/开关）、`.dshw-usage.json`（账本+提醒设置）、`.dshw-turn.json`（消耗 seq）、`.dshw-bubble.json`（泡泡配置）、`.dshw-api.json`（自定义模型注册表，**不含密钥**）、`.dshw-usage-archive.json`（归档）、`.dshw-codex.json`（Codex 缓存）、`whale-roles/`、`whale-audio/`、`whale-bubble-imgs/`。文件候选表一律 `$DSH_HOME` 优先（`lib/index.js:37-44, 404-443`）。
- 前端启动有「主界面守卫」：只在检测到聊天输入区（composer）的页面初始化，插件市场等 SPA 视图不碰 DOM（`assets/whale-widget.js:16-77`）——这是 DSH 宿主环境适配，属 **DSH 特有技术**，不是产品能力。

---

## A. 记账与显示系统

### A1. 余额

**数据来源（双通道，API key 永远优先，二者互不回退到对方的账本口径）**

- 通道 ①：`GET https://api.deepseek.com/user/balance`，`Authorization: Bearer <key>`，key 从宿主凭据服务 `ctx.credentials.resolve('DEEPSEEK_API_KEY')` 读（`lib/index.js:1170-1198, 1201-1253`）。多币种选择规则：优先「CNY 且 >0」→ 任意非零 → CNY → 第一项（`pickBalanceInfo`，`lib/index.js:1049-1058`）。官方响应里的 `granted_balance`（未过期赠金）与 `topped_up_balance`（充值）单独下发给前端供「赠金/充值余额」模块使用，取不到给 `null` 而不是 0（`lib/index.js:1231-1240`）。
- 通道 ②：无 key 时走 DSH 的 `deepseekAccount` 账号登录态服务（**不自己拼 HTTP**，token/请求头/失效清理全由宿主负责，`lib/index.js:1060-1142`）。余额 = 充值钱包 + 赠金钱包合计（与 API key 路 `total_balance` 同口径，否则余额差推算的今日已用会偏小）；**「只有赠金、充值钱包为空」必须算成功**（新用户常态，`lib/index.js:1098-1115`）。可选服务用 `ctx.get('deepseekAccount')` 读取而不是写进 `inject`——写进 inject 会让老宿主上整个插件永不 apply（`lib/index.js:1064-1066` 注释明确警告）。
- v781 兜底：key 路**任何**失败（401/结构异常/超时/凭据服务报错）都再试一次账号路，两条路都失败才报错，且把两条路的原因都带上（`accountFallback`，`lib/index.js:1144-1169`）。

**刷新频率 / 手动刷新 / 缓存**

- 前端 `setInterval(refresh, 60000)` 自动刷新；点击鲸鱼触发 `refresh(true)` 手动刷新（附带 `?refresh=1` 绕过服务端缓存）（`assets/whale-widget.js:350, 17184, 16977-16982`；路由层 `lib/index.js:3340-3351`）。
- 服务端 25 秒内存缓存（`BALANCE_TTL_MS=25000`，`lib/index.js:477`）+ **在途请求去重**（`balanceInFlight` promise 复用，`lib/index.js:2882-2923`）。
- 前端 fetch 带 25s AbortController（`FETCH_TIMEOUT_MS`，`assets/whale-widget.js:354, 14403-14414`）；失败后快速重试两次（1.5s / 3s），解决「冷启动第一次必失败」（`balanceRetryLater`，`assets/whale-widget.js:14396-14402`）。

**API 错误处理**

- 宿主：网络错误/超时/5xx 重试 1 次（500ms 间隔），4xx 不重试；**瞬时失败且有缓存时返回最近一次成功值并标 `stale:true`**（界面继续显示旧余额 + 「余额未刷新」，不闪错误）；4xx 不回退（`lib/index.js:1246-1252, 2912-2914`；前端在 `assets/whale-widget.js:14432` 拼 `usageLabel += ' · 余额未刷新'`）。
- 「记账失败不吞余额」：余额已拿到但账本写入失败时，仍返回余额并附 `ledgerError` 字段；但「账本整个读不出来」必须 fail-closed 报错（`lib/index.js:2891-2910` 注释解释了两者的语义区分）。

**数字滚动动画**

- `animateAmount(from,to,currency,700ms)`：requestAnimationFrame，`eased = 1 - Math.pow(1 - t, 3)`（ease-out 三次方），逐帧写 `amountEl.textContent`；余额变化后延迟 300ms 才起滚、900ms 后状态落定（`assets/whale-widget.js:14208-14239, 14437-14451`；常量 `ANIM_MS=700, CHANGE_MS=900`）。
- 消耗泡泡显示期间（`costBubbleActive`）动画与 render 全部早退，防止余额行覆盖金额行（`assets/whale-widget.js:14209-14224, 14240-14242`）。
- 只有「余额实际变化且币种没变」才弹变化泡泡 + 动画；自动刷新路径才弹，手动刷新只滚动数字不弹泡（`assets/whale-widget.js:14420, 14437-14456`）。

### A2. 今日已用（小鲸鱼记账 = 余额差分记账）

记账内核 `lib/accounting.mjs` 是纯函数模块（"Mutates the caller-owned ledger; this module itself never reads or writes files"，`accounting.mjs:144`），宿主负责 IO。

**五种情况的区分（`observeBalance`，`accounting.mjs:145-192`）**

- 每次成功取到余额 → 记一次观测（scope+币种维度）。
- **余额下降**：`delta = row.lastUnits - units > 0` → `row.debitUnits += delta`（累计为「已观测消费」）（`accounting.mjs:176-178`）。
- **余额上升**（充值/赠金）：`delta < 0` → `row.creditUnits -= delta`，**只单独记账、绝不从消费里扣**（`accounting.mjs:179`）。这是「充值不冲销消费」的实现：消费只来自下降观测的累加，上升量只用于触发「待核对」提示。
- **API 消费**：不是独立信号——它就是余额下降的原因；与「非调用扣减」（如纠错扣款）在观测层面不可区分，靠用户校正区分。
- **人工校正**（`reconcileBalance`，`accounting.mjs:207-242`）：用户填 `credits`（本统计区间**累计到账金额**，未充值填 0）与 `otherDebits`（非调用扣减），校正公式：
  ```
  amountUnits = row.openingUnits + creditsUnits - otherDebitsUnits - row.lastUnits
  ```
  带乐观并发校验：`revision` 串（active 本 + 日期 + firstAt + lastUnits + debit/credit + revision）不匹配返回 409「请重新打开校正窗口」（`accounting.mjs:118-121, 213-217`）；校正日志 `correctionLog` 保留最近 50 条（`accounting.mjs:232-234`）。
- **待核对判定**：`needsReview = row.creditUnits > (correction ? correction.creditUnits : 0)`——即观测到的余额增加量还没有被一次校正解释掉 → 标签「已观测消费 · 待核对余额调整」；已校正 → 「已校正消费」；否则「已观测消费」（`balanceSummary`，`accounting.mjs:123-142`）。UI 层在余额上升时显示「待核对余额调整」提示（README:424）。

**口径与边界**

- 观测只在「客户端界面开着 + 余额能取到」时发生：DSH 关闭期间的消耗**漏记**（从下次观测的新基准起算）；跨零点新建当日行时 `openingUnits` 直接取「此刻余额」，起点前消费被吞（`accounting.mjs:32-65` 的长注释）。为此 v789 引入 `partialDay` 判定：观测起点距当日 00:00 或最后一次观测距次日 00:00 超过 **10 分钟**（`PARTIAL_GAP_MS`）→ 该日标记为部分数据，UI 展示 `observedFrom/To` 与缺口时长（`accounting.mjs:38-65`）。
- 重复/乱序样本忽略（`at <= book.lastAt` 直接返回，`accounting.mjs:167`）。
- **按密钥指纹分本**：scope = sha256(key) 前 24 位（API key 路，`lib/index.js:1240`）或 sha256('dsh-account:'+userId) 前 24 位（账号路，`lib/index.js:1139`）。换/删 key = 换一本账，数据不丢：界面把历史本的日子显示为「已观测消费 · 历史账户」，**不与当前本相加**（无法判断是否同一账户）（`daySummary`，`accounting.mjs:249-289`；issue #163）。

**数据精度**

- 定点整数：`SCALE = 100000000`（8 位小数），`moneyUnits/preciseMoney/sumMoney` 全部走安全整数运算、越界抛错（`accounting.mjs:4-20`）；显示层 toFixed(2)（`fmt`，`assets/whale-widget.js:14203-14207`）。
- 币种感知：观测币种变化只重置基准不记差值（历史教训：币种跳变被记成消费，单日虚记数千元，`whale-widget-prompt.md:62`）。日键按北京时间（`beijingDay`，`accounting.mjs:22-26`）。

**每日归档与历史保留**

- 每日行结构：`{ day, firstAt, lastAt, openingUnits, lastUnits, debitUnits, creditUnits, revision, correction, correctionLog }`（`accounting.mjs:171-174, 227-235`）。
- 兼容层：`ledger.history[day] = amount`、`ledger.todayUsage`、`ledger.dayStart/lastBalance` 持续维护给旧 UI（`accounting.mjs:189-191`）。
- 保留策略：逐轮 events 保留 **90 天或最多 2 万条**；逐日 history 保留 **365 天**；超期数据移入 `.dshw-usage-archive.json`（archive 本身上限 20 万条），不删除（`pruneLedgerUsage`，`lib/index.js:1298-1356`）。
- 账本 IO 健壮性：Windows 索引器短暂占用 → EBUSY/EPERM/EACCES 退避重试（`ledgerIo`，`lib/index.js:1256-1265`）；原子写（tmp + rename，`lib/index.js:1276-1297`）；结构异常的账本**拒绝覆盖**（fail-closed，`readUsageLedger` 抛错，`lib/index.js:1266-1275`）+ 首次写新版前自动备份 `.before-recharge-fix.bak`（`lib/index.js:1281-1287`）。

### A3. 每轮消费

**DSH 提供的 usage event**

- 宿主监听全局 `session/event`（Cordis 事件流，`lib/index.js:1011-1015`）。捕获 `type === 'assistant/message'` 且带 `data.usage` 的事件，usage = `{ inputTokens, cacheReadTokens, outputTokens, reasoningTokens }`——模型返回的真实 token 计数，非估算（`handleSessionEvent`，`lib/index.js:863-912`）。
- **轮次判定**：`data.turn` + `session.id` 双键分桶（`turnAggs = Map<sessionId, agg>`，`lib/index.js:818`）——Map 分桶避免主会话与子代理（spawn/fork）并行时串账。同一轮多 step 的 usage 累加；收到新 turn 号时先把上一轮 finalize。
- **轮结束**：`type === 'turn/end'` → `finalizeTurn(sessionId)`（`lib/index.js:870-871`）：写 `lastTurn = {turn, amount, tokens, ts}`、`lastTurnSeq++` 并持久化到 `.dshw-turn.json`（防热重载后 seq 归零导致前端把新轮当旧轮，`lib/index.js:417-423, 823-839`）。

**token 取值与费用计算**

- 口径修正（issue #89）：`reasoningTokens ⊆ outputTokens`（DSH 保证），所以**不再单独累加 reasoning**，否则输出侧按输出价重复计费（实测偏高约一倍）：`outputBilled = output`（`lib/index.js:887-891`）。
- 成本：`costMsg = cache/1e6 * p.hit[off] + input/1e6 * p.miss[off] + outputBilled/1e6 * p.out[off]`，`off = isPeakTime(now) ? 1 : 0`（高峰档下标 1）（`lib/index.js:897-899`）。
- 峰谷规则（`lib/index.js:493-602`）：高峰 = 北京时间工作日 9–12 与 14–18 点；2026-08-23 起周末全天谷价（`WEEKEND_VALLEY_FROM_SEC`）；2026-09-19 起法定节假日全天谷价（硬编码 `HOLIDAY_VALLEY` 表，注释要求每年国务院发布后补下一年日期）。价格表：Flash `[hit 0.02/0.04, miss 1/2, out 4/8]`，Pro 3 倍（`BASE_PRICE/PRO_PRICE/PRICING`，`lib/index.js:498-509`）。
- 模型价格匹配（`priceFor`，`lib/index.js:522-533`）：① `CUSTOM_PRICES`（用户自定义单价，matchIds 子串匹配，**按键长降序**防 "pro" 误伤）→ ② 内置 `PRICING`（模型名子串匹配）→ ③ `_default`。自定义单价若为 USD，按用户填汇率折成 CNY 记账（`lib/index.js:901-904`）。每轮结算前 10 秒节流刷新一次自定义单价表（`refreshCustomPrices`，`lib/index.js:2542-2570`）。
- 结算时**按模型拆分**写入用量事件：每个模型一条 `appendUsageEvent`（明细唯一来源）+ `apiAttributeEvent`（归属到自定义模型注册表，作为无余额接口模型的今日已用兜底）（`lib/index.js:846-859`）。

**防止重复记账 / 重复弹泡**

- 后端：seq 持久化 + 前端 localStorage `dshw-last-seq` 双保险（`lib/index.js:823-839`；`assets/whale-widget.js:17188-17194`）。
- 前端 `pollLastTurn()` 每秒轮询 `/dsh-whale/last-turn.json`（`assets/whale-widget.js:17255-17290`）：首次拿到数据只**对齐** seq（不弹旧轮次）；此后 `seq > lastCostSeq` 才播任务结束音 + 弹消耗泡泡。若本地记忆值大于服务端（宿主重置/文件丢失），拉齐到服务端值避免永久不弹。
- （Codex 本地统计的防重复是另一套：`total_token_usage` 单调递增，按**累计差值**累加天然免疫一轮多条记录，`lib/index.js:1594-1697`。）

### A4. Usage Ledger（用量记录）

**数据结构（`.dshw-usage.json`）**

```js
{
  date, lastBalance, todayUsage, history: { 'YYYY-MM-DD': amount },   // 兼容层
  events: [ { ts, day, model, cost, tokens } ],                       // 逐轮明细（90天/2万条上限）
  accounting: {                                                       // v1 新账本
    version: 1, active: '<scope>-CNY', migratedAt,
    legacyHistory: {...},                                             // 迁移前旧 totals 存档
    books: { '<scope>-CNY': { currency, days: { '<day>': 每日行 } } }
  },
  settings: { taskEnd, alert, budget, turnCost, wait, events, models } // 提醒/音效设置也存这里
}
```
（`accounting.mjs:154-192`；`lib/index.js:1361-1374`；`lib/index.js:1449-1496`）

- **单轮记录**：内存 `lastTurn` + `/dsh-whale/last-turn.json` 路由（`lib/index.js:3353-3364`）。
- **每日记录**：`accounting.books[scope].days[day]`（权威）+ `ledger.history[day]`（兼容）。
- **7 天 / 全部**：`usageRecordsPayload()`（`lib/index.js:1376-1413`）返回 `{ today, days7[7], total7, total7ByCurrency, all: { days[], events[] } }`；`all.days` 取「今天 ∪ history 键 ∪ 各账本日期 ∪ events 日期」的并集倒序；`all.events` 取最近 500 条。日期并集跨账本（`accountingDays`，`accounting.mjs:107-111`）。
- **模型占比**：前端聚合 `usageAggModels`（按模型求和降序）+ 彩色占比条（`USAGE_PALETTE` 10 色，宽度=cost/sum，右列百分比+金额）（`assets/whale-widget.js:5632-5711`）。
- **图表**：原生 canvas 柱状图（近 30 天，devicePixelRatio 高清绘制、悬停 tooltip、点柱跳转当日明细）（`usageDrawBarChart`，`assets/whale-widget.js:5713-5823`）。
- **模型搜索**：「消费记录(全部)」窗口有搜索框，按日期/模型名过滤（`renderGroups(q)`，`assets/whale-widget.js:6093`）。
- **模型友好名**：`deepseek-flash` → "DeepSeek-V4.1-Flash"，旧名标注「旧名·同 V4.1 Flash」，只做标注不合并数据（`usageModelLabel`，`assets/whale-widget.js:5645-5652`）。

---

## B. 交互系统

> 按任务要求区分：**【产品】**=要模仿的产品能力；**【DSH 技术】**=依附 DSH 宿主环境的实现手段（Hermes 不复制）。

| 交互 | 分类 | 实现要点 |
|---|---|---|
| 拖拽移动 | 【产品】 | document 级 `pointerdown/move/up` capture；位移平方 ≥ 9（>3px）判拖拽、否则判点击（`CLICK_SQ=9`，`assets/whale-widget.js:349, 16727-16729`）；拖拽中 `transition:none` 1:1 跟手（`.dshwv-dragging`，CSS `assets/whale-widget.js:368`），松手 `settle()` 带动画滑向吸附位 |
| 点击（单击） | 【产品】 | `endDrag` 里 `clickAllowed && !drag.moved` → `whaleClick()`（推进泡泡序列）+ `refresh(true)`（手动刷新余额）（`assets/whale-widget.js:16977-16982`） |
| 连续点击 | 【产品】 | 无双击概念；连续点击 = 序列推进/续时（见 C1）。点泡泡本体 = 下一项/关闭（`bubbleNext`，`assets/whale-widget.js:13912-13926`） |
| 四边吸附 | 【产品】 | 自定义吸附区（`snapConfig`：`mode 'ratio' 比例 / 'px' 绝对 / 'off' 关闭`，`assets/whale-widget.js:12014-12024`）；横纵两轴独立判定可组合成角落；判定点用**图像中心**而非挂件盒中心（`artCenterAt`：img 占盒右下 59.45%，`assets/whale-widget.js:14387-14392`；`snapZones`，14350-14363）；有可视化的吸附设置窗口（网格预览 + 可拖手柄，CSS 539-561） |
| 左右翻转 | 【产品】 | 贴左吸附必 `scaleX(-1)`、贴右不翻、自由摆放按图像中心 vs 视口中线（`refreshFlip`，`assets/whale-widget.js:14367-14383`）；文字块同步反向镜像保持可读；**关键坑**：文字块 transition 必须按属性拆分 `transition:opacity .16s ease .36s, transform .3s ease`，否则翻转文字滞后闪烁（`assets/whale-widget.js:414`；`whale-widget-prompt.md:119`） |
| 自由摆放 + 位置记忆 | 【产品】 | localStorage `dshw-pos` v:2「净距离」格式（相对最近边的距离），窗口 resize 后按锚点恢复；脏数据（负数/超视口）自愈夹回并落盘（`saveAnchorPos/applyAnchorPos`，`assets/whale-widget.js:14575-14597, 17024-17056`；issue #102） |
| 按压 Q 弹 | 【产品】 | `scaleY(0.88) scaleX(1.05)`，`transform-origin:50% 100%`（按压时底部坐标不变），`transition: transform .22s cubic-bezier(.34,1.56,.64,1)`（过冲回弹）（`assets/whale-widget.js:14769, 14885-14889`；CSS 369） |
| 菜单 | 【产品】 | 悬停鲸鱼显形右上角 ☰ 按钮（`onDocPointerMoveCursor`，`assets/whale-widget.js:16926-16949`）；菜单 fixed 定位锚定按钮一侧、底边悬在素材顶部上方（`positionMenu`，14982-15006）；`color-scheme:light` 保证暗色主题可读 |
| 右键 / 长按唤出菜单 | 【产品】 | 「隐藏菜单按钮」开启后：桌面右键鲸鱼 `contextmenu` → toggleMenu（16763-16784）；移动端长按 **1.5s** 唤出（`TOUCH_LONG_PRESS_MS=1500`，位移 >10px 取消，`assets/whale-widget.js:16805-16824`），并吞掉系统补发的原生 contextmenu 防止重复开合 |
| 移动端拖拽 | 【产品】 | 自研触摸接管：只在「起点命中鲸鱼」的那次手势 `preventDefault`，防浏览器把手势判成页面滚动派发 pointercancel（`onDocTouchStart`，`assets/whale-widget.js:16789-16875`）；多点触控（双指缩放）立刻放行 |
| 透明像素穿透 | 【产品】 | canvas 读 alpha（`data[3] > 10`）判命中 + **凸包 clip-path** 裁掉 img 透明边距（`setupHitTest/buildHitClipPath/isWhaleHit`，`assets/whale-widget.js:16539-16684`）；Firefox resistFingerprinting 抹白画布 / 图片加载失败 → 降级矩形判定，绝不吞整页事件 |
| 滚轮让位 | 【产品】 | 鲸鱼接住指针期间，滚轮临时把 img `pointer-events:none` 找出指针下方真正可滚动容器并代为滚动（`onWhaleWheel`，`assets/whale-widget.js:16892-16925`） |
| IME 组字保护 | 【产品】 | 组字期间（`isComposing`/keyCode 229）不解锁音频、body 增删全部排队到 compositionend 之后（issue #179：装插件后微软拼音打字上屏错乱）（`assets/whale-widget.js:309-344`） |
| tapIndex 注入 / 桌面注入行 / 主界面判定 / body 挂载登记器 | 【DSH 技术】 | `webServer.tapIndex` 在 `</body>` 前注入 `<script defer>`（`lib/index.js:4175-4180`）；Electron 桌面端唯一通道是 `webserver/index-inject` 结构化行，且必须用**内联 script 行**并吞掉 onerror（`script-src` 行加载失败会 reject 整个应用 boot，issue #154）（`lib/index.js:632-672`）；composer 特征判定主界面（`assets/whale-widget.js:16-33`）；`dshwBodyAppend` 登记器防 React removeChild 冲突（905-951）。**Hermes 有自己的扩展机制，不需要这层** |

---

## C. 泡泡系统（重点）

### C1. 点击序列 → Bubble 1→2→3

- **数据**：运行时 `bubbleSeq` = 步骤数组，`bubbleSeqIdx` 指向下一项（`assets/whale-widget.js:12282-12283`）。默认 = `BUBBLE_DEFAULT_ITEMS` 深拷贝：第 1 项「余额内容」（标题+总余额+今日已用+两个峰谷模块），第 2 项「A/B 加权 choice」（A=随机语句大池 w:10 / B=petpet 动图 w:1）（`assets/whale-widget.js:7064-7429`）。
- **推进逻辑**（`whaleClick`，`assets/whale-widget.js:13881-13910`）：
  - 消耗/预警系统泡泡显示期间点鲸鱼不动作（点泡泡才关）；
  - 无泡泡 → 开新轮从第 1 项开始；
  - 等待泡泡期间点角色：开了「点按角色关闭提示气泡」才收起（默认关）；
  - `tapAdvance` 开启（v727）→ 点角色 = 推进一项（`bubbleNext`），最后一项收起；
  - 默认（关）→ 显示第 1 项时点角色只**续时**不清内容；显示第 2+ 项时回到第 1 项。
- **weighted random 两处**：
  1. **choice 步骤**（并列 A/B）：每次走到该步独立抽一个，`total=Σw; r=Math.random()*total; 按权重累减`，**不防连续重复**（注释明说「不记忆上次，允许连续几轮同泡」）（`bubblePickChoiceStep`，`assets/whale-widget.js:12621-12634`）。
  2. **随机语句/随机图片模块**：同款加权抽样，但带 `avoidIdx`（上一把的下标存模块的 `_lastPick`/`_lastPickImg`），最多重抽 6 次避免与上一条相同（`bubblePickLine`，`assets/whale-widget.js:13268-13285`）。旧「随机台词段」（`pickRandomLines`，12134-12143）是 6 组台词带权重的同款实现，现在作为 `kind:'random'` 步骤的兜底池。

### C2. 模块系统与 Row→Module Schema

**配置文件 `.dshw-bubble.json` 的完整 schema**（写入侧校验见 `lib/index.js:4024-4052`；运行时结构见 `assets/whale-widget.js:12306-12332, 12419-12489`）：

```js
{
  v: 1,
  tapAdvance: true|false,
  items: [ Step, ... ],            // items[0]=首次点击泡，其余=再次点击队列
  lib:   [ { id:'bmod_xxx', name:'≤20字', module: Module } ]   // 模块库
}

Step =
  { kind:'custom', modules: Module[] }                        // 自定义内容（模块平铺数组）
| { kind:'random' }                                          // 随机台词段（旧式）
| { kind:'normal' }                                          // 默认余额视图
| { kind:'choice', options: [ { w:int(1..99), item:Step }, ... ] }  // 并列 A/B 加权（最多 2）

Module = {                                   // 平铺数组；行合并靠 row 标记
  type: 'text'|'link'|'random'|'image'|'randimg'
      | 'balance'|'bonus'|'recharge'|'today'|'session'
      | 'peak'|'nextpeak'(旧)|'quota'|'plan',
  row: 正整数?,            // 仅相邻同 row 模块合并为一行；无 row = 每模块独占一行（旧配置兼容）
  // —— 通用样式 ——
  size: 1..50,             // 字号档，线性映射 40..240 倍 --dshw-u（bubbleModuleFontU，12658）
  bold/italic/ul: bool,
  rgb: ''|'macaron'|'candy'|'rouge'|'bamboo'|'galaxy'|'champagne'|'indigo'|...,  // 文字跑马灯渐变方案
  color: '#hex',           // 纯色（与 rgb 互斥使用）
  bgRgb: 方案|'', bg: '#hex',   // 底色（同样分纯色/跑马灯，画在行底、可叠文字渐变）
  fontFamily: 'css 字体串',
  // —— 类型特有 ——
  text?: string,  url?: string,                                  // text/link
  lines?: [ { t, w, size?, bold?, rgb?, italic?, ul? } ],        // random（带权重句子池）
  imgId?: 'bimg_xxx',  imgScale?: 0.1..1,                        // image
  imgs?:  [ { imgId, w } ],                                      // randimg（带权重图片池）
  tpl?: string,                                                  // 占位符模板（见下）
  len?: int,               // session 模块「保留长度」，0=不截断（默认 12）
  peakStyle?: 'default'|'liangwen'|'qiangqiang'|'count'|'mini',  // peak 模块显示样式
  peakColor/offColor/peakRgb/offRgb/peakBgRgb/offBgRgb,          // peak 按峰/谷两态分别配色
  modelId?: 'api_xxx',     // 自定义模型数值模块的归属
  planWin?: 'all'|'rolling'|'weekly'|'monthly',                  // plan 模块窗口选择
}
```

**行合并规则**（`bubbleRowsOf/bubbleRowsFlat/bubbleRowsCanon`，`assets/whale-widget.js:12419-12489`）：仅当**相邻**两模块带同一个正整数 `row` 才并入一行；图片类模块（image/randimg）永远独占一行并打断合并；渲染上限 **每行 6 模块、每泡 6 行**（`bubbleRowsTo`，`assets/whale-widget.js:13538-13539`）；一个泡泡只允许一个图片模块（`bubbleItemHasImage`，9166）。

**占位符**（`bubbleContentTokenMap`，`assets/whale-widget.js:13025-13073`）：
- 内置数值：`{balance_ds}` 总余额、`{bonus_ds}` 赠金、`{recharge_ds}` 充值余额、`{expense_ds}` 今日已用、`{session}` 对话名、`{status}` 峰谷状态字、`{countdown}` 时段倒计时；
- 自定义模型模块：`{balance}`/`{today}`（该模型自己的数）、`{quota}`/`{quota_used}`/`{quota_left}`/`{quota_total}`/`{quota_reset}`、`{plan}`/`{plan_left}`/`{plan_reset}`（订阅额度，多窗口按 `planWin` 取）。
- 取不到数显示 `—`（读不到）而非 `0`（真的没了）——两者语义被刻意区分（`bubbleBonusText` 注释，`assets/whale-widget.js:12671-12683`）。

**渲染引擎**（`bubbleRowsTo`，`assets/whale-widget.js:13534-13800`）：每模块一个 `.dshw-trow` 块；底色画在行层、文字（含文字渐变）放内层 span，两者可叠加；峰谷「倒计时样式」注册到**每秒 ticker** 原地刷新文案与配色（数字用 `tabular-nums` 等宽防底色抖动）；峰谷非 count 样式也登记 ticker，状态切换原地刷新；超宽判定（scrollWidth > 560u）才允许折行；link 模块只在真实泡泡里可点（`window.open(url,'_blank','noopener')`）；文字渐变动画时长每次渲染随机 1.5–4.5s（各行速度不同，`bubbleMarqueeDur`，13220）。

### C3. 编辑器

- **主窗口**（点击队列）：列表行「第 n 次点击 · 编辑内容」+ 拖拽手柄 ⠿ + 删除 ✕；choice 行显示 A/B 两组（各带权重输入 1~99）+ ⊕ 拆开钮（`renderBubbleMore/bubbleChoiceRowUI`，`assets/whale-widget.js:7787-8037`）。
- **拖拽排序**：桌面用原生 HTML5 DnD，落点分区 = 左右 22% 边带 → 与目标行**并列/替换该侧**，中间上/下半 → 插到目标行前/后（`bubbleRowZone`，`assets/whale-widget.js:7862-7868`）；并例行只能整行拖（手柄），A/B 单泡可拆出（`bubbleSideSplitDrop` 7909-7941）；并列组合默认权重 1:1（`bubblePairDrop` 7943-7978）。触摸端自研长按 400ms 拖拽（`ROW_TOUCH_HOLD_MS=400`，8069-8190），拖拽成立后抑制随之而来的 click，触感用 `navigator.vibrate(10)`。
- **模块编辑**（`renderModuleEditor`，`assets/whale-widget.js:10424+`）：类型差异化的字段面板 + 占位符 `?` 帮助弹层（`bubbleTplHelpItems`，13075-13106）+ 自定义字体下拉（`refreshSystemFonts`，10183+，枚举系统字体）。
- **悬浮快捷编辑**：真实泡泡显示期间可直接点击文本/随机句/数值模块弹 qedit 悬浮窗就地改（9222-9225）。
- **模块库**：模块可「另存」入库（`bubbleLibAdd`，12294-12302），之后点击或拖入任意泡泡复用；库条目悬浮右上角 ✕ 删除。
- **预览**：编辑器里的泡泡预览与真实泡泡**同宽度同排版**（复用 `.dshw-text` 与同一 CSS 变量，只是裁掉底部两个小气泡）（`bubblePreviewInto`，`assets/whale-widget.js:13817-13875`）。
- **save/cancel/default**：打开时快照，`bubbleEditorDirty` 判脏；保存 = POST `/dsh-whale/bubble.json`（host 只收 `{v:1, items, lib, tapAdvance}`，`lib/index.js:4024-4052`）；「恢复默认」= `BUBBLE_DEFAULT_ITEMS`。**跨端一致性约定**：提醒内容的出厂默认在宿主（新用户所见）与前端（编辑器恢复默认目标）**各存一份且必须逐字段一致**，有 CI 探针钉住（`lib/index.js:1420-1430, 1459-1462` 注释）。
- 删除自定义模型时，自动从所有泡泡步骤（含 choice 内层）与模块库中摘除引用该模型的模块（`apiDeleteModel`，`lib/index.js:2491-2538`）。

### C4. 编辑器工作量评估

- 泡泡编辑器相关代码约 `assets/whale-widget.js:6562-12250`，**约 5700 行（占前端 1/3）**，是最大的单块；其中触摸拖拽、A/B 并列、模块库、预览、快捷编辑各自独立。
- 评估：**适合分阶段**。建议切分：① 数据层（schema + 行合并 + 加权抽样 + 持久化路由，很小）→ ② 渲染引擎（bubbleRowsTo，含样式/占位符/ticker）→ ③ 基础编辑器（队列增删排序 + 文本/随机模块编辑 + save/cancel）→ ④ 进阶（A/B 并列拖拽交互、图片/随机图片、模块库、悬浮快捷编辑、系统字体枚举、触摸长按拖拽）。①②③ 是「可用的自定义泡泡」，④ 全是增益。一次做完的风险主要在拖拽落点分区与触摸端自研拖拽的边界情况。

---

## D. 提醒系统

### D1. 四类提醒与触发

| 提醒 | 触发条件 | 触发源 | 去重机制 |
|---|---|---|---|
| 余额预警 | `0 < balance <= below`（阈值可配，默认 5 元） | 每次余额成功刷新后 `checkUsageAlerts`（`assets/whale-widget.js:5455-5482`） | 内存布尔 `usageAlertBelowFired`，**恢复高于阈值才复位** → 刷新页面会重新提醒一次（状态不持久化） |
| 今日预算 | `todayUsage >= amount`（默认 10 元） | 同上 | 内存键 `usageBudgetFiredKey = '日期:金额'`，同日同额只弹一次；刷新后键重置 → 会再弹一次 |
| 每轮消耗 | `/dsh-whale/last-turn.json` 的 seq 变大 | 每秒轮询 `pollLastTurn`（`assets/whale-widget.js:17255-17290`） | seq 双持久化（host `.dshw-turn.json` + 前端 localStorage `dshw-last-seq`）→ **刷新不重复**；首次拉取只对齐不弹 |
| 提问/授权等待 | `wait.json` 返回非空 `pending` | 每秒轮询 `pollWaitState`（`assets/whale-widget.js:17206-17254`） | 声音：localStorage `dshw-wait-sound = kind:id`，**刷新也不重响**；泡泡：常驻（见下）；被点掉的挂起记 `waitDismissedId`（内存）不再自动弹回 |

自定义 API 模型各有独立的 alert/budget（`runApiModelAlerts`，`assets/whale-widget.js:5484-5539`），带币种一致性检查：今日已用与预算阈值币种不同且无汇率时**宁可不比较也不误报**（控制台 warn）。

### D2. Agent 等待（提问/授权）的宿主侧信号

`notePendingEvent`（`lib/index.js:960-1008`）从会话事件流推断：
- `tool/call` 且 `data.name === 'ask_user_question'` → `pending = {kind:'question', id, ts}`；
- `approval/asked` → `{kind:'approval', id}`；
- `tool/result`（callId 匹配或兜底清空）/ `approval/*` / `turn/start|end` → 清除；
- 对话名三个来源按可靠性排序：`sessionTitle` 服务（可折叠日志，含启动前的标题）→ `session/title` 事件 → session 对象字段（`lib/index.js:921-983`）。
- 只保留**最新一条**挂起（单槽位，不做多会话队列）。
- 为什么不靠 `turn/end`：`ask_user_question` 是挂起的工具调用，等待期间 seq 不变、turn/end 不来（`lib/index.js:914-918` 注释）。

### D3. 系统泡泡优先队列（Bubble 与「通知」的组合）

- **没有 OS 级系统通知**——全部是页内鲸鱼泡泡；泡泡不可用（被占用/关闭）时退化为**居中卡片**（`usagePopupCard`，`assets/whale-widget.js:5569-5606`，卡片内也渲染图片模块）。
- 优先队列 `whaleSysQueue`（`assets/whale-widget.js:13971-14077`）：**rank 1 今日预算 > 2 余额预警 > 3 每轮消耗 > 4 等待交互**；同批 30ms 窗口合批排序；**消耗档后入先出**（新一轮消耗置顶，旧的排队）；等待交互享最高实际优先级——会把正在显示的消耗/预警退回队列、立即上屏（`whaleSysPush` 的 wait 分支，14007-14046）。
- 前三档自动关闭（消耗 `turnCostCloseMs` 默认 5000ms；预警/预算 `autoClose`+`ttlSec` 默认 6.5s）；**等待泡泡常驻（ttl=0 不布计时器）**，直到宿主说挂起解除（`showWaitBubble/sceneOpen`，`assets/whale-widget.js:14091-14142, 12526-12570`）。
- 队列项结束时有下一项则**保持打开、内容淡切**（`whaleSysSwapNext`），不做开-关-开闪烁。
- 泡泡 TTL 的后台标签页兜底：`setTimeout` 会被节流 → 同时记截止时刻，`visibilitychange/focus/pageshow` + 每秒巡检三路补收（`bubbleTtlSweep`，`assets/whale-widget.js:12255-12280`）。

### D4. 音效时机（与泡泡独立）

- 任务结束音：`pollLastTurn` 里 seq 变化时 `playTaskEndSound()`（先于泡泡）；门控 = `usageSet.taskEnd.on` + `soundOn`（`assets/whale-widget.js:1482-1508`）。
- 提问/授权音：挂起**首次出现**时播一次（`pollWaitState`，`assets/whale-widget.js:17250`）；门控 = 事件总开关 `on` + 选了音效 + 该行 `[✓] soundOn` + `soundOn`。
- 提醒泡泡与音效是**各自独立的开关**（`bubbleOn` vs `soundOn` vs 每行 `[✓]`），「不响 = 仍可冒泡」。
- 提醒是否持久化：**提醒内容与开关**持久化（`.dshw-usage.json` settings）；**「已提醒过」状态不持久化**（预警/预算刷新后会再响一次；等待的声音去重用 localStorage 持久化——这是四者中唯一跨刷新去重的）。

---

## E. 音效 / 角色 / 图片系统

### E1. 音效引擎

- **Web Audio 自研播放器**（`dshvSound`，`assets/whale-widget.js:224-307`）：不经过 `<audio>` media element（系统媒体控件/Touch Bar 不会出现）；`AudioBufferSourceNode` + GainNode；**URL 级预取+预解码缓存**（`dshvWarm` 预热 → 起播走同步路径，不再等 Promise，`assets/whale-widget.js:149-187`）；`playAt(delay)` 用音频线程时间轴排期；备用路由 `_alt`（首选 204/失败自动切换一次）；204 显式拦截（0 字节进 decodeAudioData 会抛 EncodingError → 静音）。
- **AudioContext 生命周期**：`latencyHint:'interactive'`；空闲 60s `suspend()`（防 macOS 上 running context 持有 `PreventUserIdleSystemSleep`）；`close()` 不能用——任务结束音不是手势触发的（`assets/whale-widget.js:95-133` 注释）；音效总开关关闭时**不建 context、不预热、不解锁**（135 处 `dshwvSoundOff` 守卫）。
- **按压/松开衔接**（`pressUp`，`assets/whale-widget.js:14885-14913`）：按住超时 → 松开音在松手时播；短按 → 把松开音 `playAt(remainSec - RELEASE_LEAD_MS/1000)`（`RELEASE_LEAD_MS=40`，14861）排期到按压音结束前 40ms，衔接精确且不受主线程抖动影响。
- **音量三态**（v778）：①区按压音量 = 全局基准 `soundVol`；②③④区（消耗/提问/授权）各一条 `events.<kind>.vol`，`volSet=false`（默认）= 跟随①区、显式拖过 = 用自己的值（`soundVolumeOf`，`assets/whale-widget.js:1423-1452`；宿主默认结构 `lib/index.js:1441-1447`）。
- **试听**：面板里每行「试听」；试听名单只登记 `dshwvPreviewMark > 0` 期间创建的元素，绝不误伤真实事件音（`dshwvPreviewEls`，`assets/whale-widget.js:198-223`）。
- **自定义片段/音效组**：导入 wav（base64 ≤ 8MB）存 `whale-audio/<id>.wav` + `audio.json` 索引；音效组 `{id,name,press,release}`，**槽位留空 '' = 该事件静音**（host 返回 204 + 前端 `empty` 判定，`lib/index.js:3907-3908`；`assets/whale-widget.js:14785-14797`）；预设组（duck/fx1）与预设片段（ya1/ya2/d1/d2/exp_orb/end_a）不可删；组引用的片段被删 → 回退预设（`groupFragmentId`，`lib/index.js:3271-3288`）；组支持置顶。
- 前端可视化裁剪：导入时 canvas 画波形 + 双滑块选区间（`dshwv-dualrange` CSS，`assets/whale-widget.js:499-502`）。

### E2. Character（角色）

- 存储：`whale-roles/<id>.png|.gif` + `roles.json`（`{id,name,format:'png'|'gif'|'apng',pinnedAt,createdAt}`）（`lib/index.js:3042-3147`）。默认小鲸鱼 `pinnedAt=1` 作置顶基线，任何新置顶都排它上面（3054-3062）。
- 导入：base64 dataURL ≤ 20MB（body 上限 30MB），客户端显式告知 gif/apng（APNG 的 dataURL 是 image/png，必须额外字段区分）（`lib/index.js:3601-3645`）；导入前有裁剪窗口（缩放/翻转/命名）。
- 前端：角色选择列表（缩略图/当前项高亮/GIF 角标/置顶/删除/名称溢出循环滚动 `bindNameMarquee`）；当前角色 id 存 localStorage `dshw-role`；被删角色自动回退默认鲸鱼（`assets/whale-widget.js:15008-15039`）。角色图同样走透明像素命中测试与 clip-path。
- 没有独立的 "character pack" 概念——就是图库 + 单选。（未验证是否有批量导入包格式，从代码看没有。）

### E3. 泡泡图库（Image Library）

- 存储：`whale-bubble-imgs/<id>.png|.gif` + `bubble-imgs.json`；上传 ≤ 8MB（`lib/index.js:4054-4119`）。
- **内置语义 id 常驻**：`bimg_petpet` / `bimg_money1`（`DEFAULT_BUBBLE_IMGS`，`lib/index.js:446-449`）——用户图库不含同 id 时总是列出；`/dsh-whale/bubble-img.png?id=...` 先查用户图库再回退包内 assets。意义：全新安装时，默认泡泡配置引用的语义 id 也能出图；用户删光图库不破坏默认内容。
- 资源管理窗口：图片/音频两折叠区统一查看/试听/删除/导入，入口行右侧显示数量（前端 `resOpenBtn` 相关，约 5100-5300 行）。

---

## F. 自定义 API / Provider 系统（重点）

### F1. Provider 模板抽象（`API_TEMPLATES`，`lib/index.js:113-399`，共 34 个）

```js
API_TEMPLATES[key] = {
  name, currency: 'CNY'|'USD', keyRef: 'XXX_API_KEY',
  kind: 'balance'(默认) | 'quota'(订阅额度) | 'codex'(本地会话),
  noBalanceApi: true?,          // 官方没有「用 key 查余额」的接口
  apiNote: '面板里显示的原因说明',
  needsBaseUrl: true?,          // 需要用户填 Base URL（{base} 占位）
  matchIds: ['模型名子串', ...], // 会话事件归属匹配
  probeUrl: '探活地址（测 key 连通性）',
  balance: {
    url, auth: 'Bearer {key}'|'{key}'|'',
    method?, body?,             // v789：支持 POST + body 占位符 {key}/{base}/{自定义params}
    json: { remaining?, total?, used?, scale? },   // JSON 字段路径 a.b[0].c + 乘数
    usage?: { url, auth, json: { used, scale } },  // 可选的第二接口（已用量）
  },
  quota: {                      // kind:'quota' 订阅额度
    url, auth,
    json: {
      percent?|remainPct?|remain+total?|resetAt?|resetAtMs?|level?,
      windows?: [ { key, label, percent, resetAt,
                    pick?: { list, types[], unit, number } } ],  // 多窗口（OpenCode Go 3 窗口）
    },
  },
}
```

三类厂商（UI 上的处理差异）：
1. **可直接查余额**（DeepSeek、OpenRouter、Kimi CN/国际、StepFun、Novita、OpenAI 兼容中转站、自定义 HTTP）：余额 = 按 `balance.json` 路径取值；`total`+`used` 可组合出 `remaining = total - used`（`fetchModelBalance`，`lib/index.js:2339-2381`）。
2. **无余额接口**（`noBalanceApi:true`，20 家：OpenAI/Anthropic/Gemini/xAI/Groq/Mistral/Together/Fireworks/DeepInfra/Cerebras/硅基流动/火山方舟/阿里/百度/腾讯/讯飞/魔搭/Ollama 等）：**UI 处理**——下拉里标注「（无余额接口）」；选中后 `hasBalanceApi=false` → `balanceMode='events'`、余额显示「—」、「今日已用」按会话事件估算（CNY）、`apiNote` 显示原因；「测试连通性」走 `probeUrl`（多为 `/v1/models`）验证 key；**没有余额接口不算错误**（`entry.error = null`，`lib/index.js:2794-2813`）。Anthropic 特殊：探活需要双请求头，干脆不提供探活（268 行注释）。
3. **订阅额度**（`kind:'quota'`，智谱/Kimi Coding/MiniMax Coding/国际变体/OpenCode Go）：读厂商官方接口的「窗口已用% + 重置时间」；智谱的扁平数组选择用 `pick:{list,types,unit}` 按 type+unit 选条目（v789 修：5h 窗口不保证排 [0]）（`pickQuotaEntry`，`lib/index.js:2223-2242`）；多窗口归一成 `windows[]` 并把第一个回填成主窗口保持兼容（2311-2320）。厂商回报「没有该订阅套餐」→ `plan.hide=true` 前端不显示（`apiPlanNoPlan`，2331-2337）。

### F2. 取数层与安全

- JSON 路径：`pickJsonPath` 支持 `a.b[0].c`（把 `[n]` 归一成 `.` 分段）（`lib/index.js:1989-1999`）；`scale` 乘数（Novita 的 0.0001）。
- `mergeNonEmpty`/`stripEmptyDeep`（2009-2032）：模型条目里**空字段不覆盖模板默认**——表单没填的字段存空串，直接 assign 会把模板自带的接口地址盖掉；全部为空 = 完全用模板。
- HTTP：`apiFetchJson` 默认 GET、15s 超时；`{key}` 可嵌在 URL（Gemini `?key=`）；业务层错误提炼（HTTP 200 但 body 里 code/msg 报错，如智谱「当前用户不存在coding plan」）（`apiBusinessError`，2167-2177）。
- **凭据目的地白名单**（v761 安全修复）：`credentialMayGoTo`（2084-2089）——只有目标 origin 恰好等于模板写死的端点、或该模型带 `allowCustomHost === true`（该标志只能由**本机来源**的写请求设置，`writeRejection` 751-773）才放行；含 `{base}` 的模板 URL 不算可信。URL 校验 `assertSafeApiUrl`（2040-2056）：仅 http/https、禁云元数据（169.254/`metadata.google.internal`）、禁 userinfo。
- 写请求（POST/PUT/PATCH/DELETE）必须来自回环地址，否则 403（远端会话能改配置 = 能决定凭据发往哪里 = 能外带 key）。
- 密钥管理：`ctx.credentials.set/resolve/unset`，配置文件只存凭据名（正则白名单 `[A-Za-z0-9_]{1,64}`，2578）；换厂商时凭据名自动跟随模板（避免新 key 写进上一家的 ref）。

### F3. 用量/额度/单价

- **逐模型余额差记账**（`apiRecordBalance`，`lib/index.js:2394-2410`）：与 DeepSeek 账本同口径——当天首次观测为起点（`dayStart`），之后累加下降额到 `delta`；充值增加不冲销。`.dshw-api.json` 的 `usage[id]` 结构：`{day, dayStart, lastBalance, delta, eventCost, eventTokens, currency, tokensTotal, month, tokensMonth}`（跨天只重置当日字段，累计量保留，`apiUsageNewDay` 2383-2392）。
- **今日已用双来源**（`apiTodayUsage`，2414-2423）：有余额观测 → `delta`（厂商币种）；无 → `eventCost`（会话事件金额，CNY）。返回值必须带 currency，前端显示与阈值比较都按它走。
- **会话事件归属**（`apiAttributeEvent`，2457-2489）：模型名对每个注册模型的 `matchIds`（默认 [name, id]）做子串匹配，命中则累加 eventCost/eventTokens/tokensTotal/tokensMonth。
- **额度（订阅/资源包，手动口径）**（`apiQuotaAutoUsed`，2431-2455）：`mode:'auto'` = 会话 token 累计（口径 **input + cacheRead + output**，reasoning 已含在 output 内；`reset:'none'` = 累计 − `baseAt` 基准 + 用户填的起始已用；`daily`/`monthly` 用当日/当月值）；`mode:'codex'` = Codex 本地统计；`mode:'manual'` = 面板手填；单位 `tokens`/`money`（单位=金额时自动统计不成立，回退手填）。
- **自定义单价**（`apiSaveModel` 的 price 段，2666-2693）：`{hit, miss, out, cur, rate}`；校验：单价 0–1000000、汇率 0–1000 正数、**USD 必须填汇率**；保存后立即失效 10s 节流缓存（2695-2697）。内置 DeepSeek 不允许被自定义单价覆盖（`refreshCustomPrices` 跳过内置 id，2551-2552）。

---

## G. 许可

- **代码（`lib/`、`cordis.patch.yml`、`package.json`、文档、维护脚本）：MIT License**，Copyright (c) 2026 MeteorNOX（`LICENSE`）。可自由使用/复制/修改/合并/发布/再许可/商用，**唯一义务：在所有副本或实质性部分中保留上述版权声明与本许可声明**（LICENSE 第 12-13 行）。→ Hermes **可以复用其代码逻辑（甚至直接拷代码）**，保留其版权声明即可；用 MIT 兼容的开源协议发布没问题。
- **素材（`assets/**` 图片/动图/音效）：不在 MIT 覆盖范围内**（`PROVENANCE.md` 第 8-10 行）：由维护者提供或 AI 生成，按 **as-is** 随插件分发、**仅供运行本插件使用，不授予再许可（sublicense），也不声明为原创作品**。→ **Hermes 不可把 DSniang1.png、Ya/D 系列 mp3、minecraft-exp-orb.wav、petpet/money1 gif 等素材直接拷走再分发**；需要自制或使用可自由再分发的素材。素材的逐项来源见 PROVENANCE.md 第二节（鲸鱼本体为 AI 生成、元数据已剥离）。
- 权利主张：PROVENANCE 第四节提供 takedown 流程（开 issue 即处理），侧面说明维护者对素材权利状态**不做背书**——即使「引用注明出处」也不构成安全的使用方式，唯一稳妥做法是换素材。

---

## 对 Hermes 移植的初步含义（简短）

1. **可直接借鉴的算法/数据结构**（MIT 代码，含实现参考）：余额差分记账内核（`accounting.mjs` 全文仅 289 行、纯函数、自带 8 位定点与校正公式，几乎可原样移植）；seq 防重复弹泡（宿主持久化 seq + 前端 localStorage 对齐）；等待交互的宿主单槽位状态机 + localStorage 声音去重；系统泡泡优先队列（rank + 合批 + LIFO）；Web Audio 预解码同步起播与 press/release 排期。
2. **产品语义要点**：余额上升（充值）单独记、不冲销消费，靠「待核对 + 显式校正」闭环；「取不到数显示 — 而非 0」贯穿数值模块；提醒泡泡与音效各自独立开关；等待泡泡常驻、其余自动关。
3. **不必复制的部分**：DSH 宿主适配层（tapIndex/桌面注入行/主界面 composer 判定/body 登记器/z-index 守护，约占前端 15%）；Hermes 用自己的插件挂载与扩展机制替代。
4. **需要重做的部分**：素材（许可不允许）；usage 事件源（DSH 的 `session/event` 需换成 Hermes 的等价事件，字段对齐 input/cacheRead/output）；凭据服务（换成 Hermes 的密钥管理）；峰谷节假日表要按年维护。
5. **风险/工作量提示**：泡泡编辑器约 5700 行、占前端 1/3，建议按 C4 的四阶段切分；多厂商模板是纯数据（34 个模板可移植），但模板里的接口地址/字段路径需逐一验证时效性（原仓库自己都记录了硅基流动接口下线这类变化）。
