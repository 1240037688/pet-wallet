# hermes-whale-widget 数据模型设计（DATA_MODEL）

> 版本 v1.0（2026-10-03）。上游输入：
> - `docs/research/DEEPSEEK_WHALE_ANALYSIS.md`（下称 **[DSH]**）
> - `docs/research/HERMES_ARCHITECTURE_AUDIT.md`（下称 **[AUDIT]**）
> - `docs/research/REFERENCE_PROJECTS.md`（下称 **[REF]**）
> - `D:\hermes\hermes-agent` 源码只读抽查（commit `0ff4c748`，见 [AUDIT] §0；本文 file:line 未加前缀者均指该仓库，已抽查核实）
>
> 本文遵守 `AGENTS.md` §7（安全规则）、§8（记账正确性红线）、§9（生命周期红线）。所有未实测行为显式标注「未验证」。

---

## 0. 设计原则

1. **五类金额显式分离，禁止混字段**（AGENTS.md §8）——任何金额字段必须能从名字看出属于哪一类（§1）。
2. **聚合 → turn 结束 → 落库**：`session.usage` 心跳只进内存渲染，永不写库；落库唯一入口是 turn 终值（AGENTS.md §8；[DSH] A3）。
3. **幂等优先**：每条写入路径必须能在 restart / reload / WS 重连场景下证明不重复记账（§3）。
4. **估算值永不伪装成真实账单**：命名前缀、置信度字段、UI 语义三层区分（§8）。
5. **最小可用**：只建账面需要的表；演进不确定处用 JSON 列 + 自有 `schema_version` 迁移兜底，不预建抽象。每个表的存在理由见 §2 各行「为什么需要」。

---

## 1. 金额体系：五类金额显式分离

### 1.1 五类金额定义

| # | 金额类别 | 定义 | 来源 | 写入者 | 用途 | 字段命名 |
|---|---|---|---|---|---|---|
| 1 | `observed_balance` | Provider 官方余额接口返回的**账户余额快照值**（含赠金/充值分项原样留存） | Provider balance/quota API（Python 半体发起） | Balance Ledger（轨②） | 余额显示、差分基准、余额预警 | `observed_*` |
| 2 | `observed_spend` | 相邻两次余额观测的**下降额累计**（差分记账）。上升额（充值/赠金）单独记 credit，**绝不冲销消费** | 轨②观测差分（[DSH] A2：`accounting.mjs:176-179`） | Balance Ledger（轨②） | 「今日已用（观测口径）」、与轨①互校 | `observed_*` |
| 3 | `local_usage_cost` | 本地由 usage tokens × 单价换算的**估算成本**，或复用 Hermes 核心已算出的 `cost_usd` 估算。**永远是估算** | 轨①（`message.complete` usage）+ pricing（§2.2） | Usage Ledger（轨①） | 每轮消耗泡泡、模型占比、图表、预算（默认口径） | `estimated_*` |
| 4 | `provider_reported_usage` | Provider 官方接口**报告的已用额度**（订阅 quota 的 used / 手动额度口径） | Provider quota API 或用户手填 | Quota 模块 | 订阅额度窗口显示、额度预警 | `reported_*` |
| 5 | `manual_adjustment` | 用户**显式校正**：本区间累计到账金额（credits）与非调用扣减（otherDebits），经校正公式换算 | 用户在校正窗口输入 | 校正闭环（§2.6） | 把「无法解释的余额上升」变成「已校正」，闭环 `needs_review` | `adjustment_*` |

**禁止事项**（AGENTS.md §8）：五类金额不得存入同一列；不得把 `estimated_*` 求和后伪装成 `observed_*`；余额 API 失败不得产生任何金额写入（见 §6 状态机）。

### 1.2 精度与运算规则

- **定点整数**：`SCALE = 100_000_000`（1e8，8 位小数），所有金额列以 `*_units INTEGER` 存储，i64 安全整数运算、越界抛错。沿用 DSH 记账内核（[DSH] A2：`accounting.mjs:4-20`）。
- 显示层统一 `toFixed(2)`；存储层永不浮点（SQLite `REAL` 只允许出现在**原样留存**的 provider 原始响应 JSON 列中，不参与运算）。
- **币种规则**：账本以 `(scope, currency)` 分桶（scope 见 §3.5）；观测币种变化只重置基准、不记差值（历史教训：币种跳变被记成消费、单日虚记数千元，[DSH] A2 引 `whale-widget-prompt.md:62`）；**不做自动汇率折算**——多币种各自成账、分别展示，显示层折算仅作参考且标注「按显示汇率折算」。
- token 数量为整数列，不参与定点体系。

---

## 2. 实体清单

共 **10 个核心实体 + 3 类支撑结构**。类型以 SQLite 亲和类型表示（§7 DDL 为准）。

| 实体 | 主键 | 主要外键 | 所属轨 | 为什么必须存在 |
|---|---|---|---|---|
| Provider | `id` | — | ①② | 余额/额度 API 的目标与凭据引用载体；无它则凭据与观测无法归属 |
| Model | `id` | `provider_id?` → Provider | ① | usage 按模型归因与定价载体 |
| UsageEvent | `id` + `dedup_key`(UQ) | `session_id`（逻辑） | ① | token 原始明细，估算成本的唯一输入，去重的锚点 |
| TurnCost | `id` + `dedup_key`(UQ) | 逻辑关联 UsageEvent（同 turn） | ① | 每轮结算金额——「每轮消耗」泡泡与预算的直接数据源 |
| BalanceSnapshot | `id` + 观测唯一键(UQ) | `provider_id` → Provider | ② | 差分记账的原始观测，缺它则 observed_spend 无从谈起 |
| BalanceAdjustment | `id` | scope（逻辑） | ② | 「充值不冲销消费」闭环的校正记录（[DSH] A2） |
| DailySummary | `(scope, day)` | scope（逻辑） | ①②③ | 展示、保留策略与互校的日聚合单元 |
| Budget | `id` | scope_ref（逻辑） | 规则 | 今日预算提醒的配置（DSH 四类提醒之一，[DSH] D1） |
| Quota | `id` | `provider_id` → Provider | ④(quota) | 订阅额度/手动额度的配置与观测归属 |
| Notification | `id` + `dedup_key`(UQ) | — | 规则输出 | 提醒去重（重启不重响）与优先队列的持久支撑 |
| 支撑：SessionWatermark | `session_id` | — | ① | 会话累计计数器水位，turn 增量与重置检测（§3.3） |
| 支撑：WhaleMeta | `key` | — | 全部 | 自有 `schema_version` 与迁移标记（§7.3） |
| 支撑：*_archive 表 | 同源表 | — | ①② | 超期数据归档不删除（§5） |

### 2.1 Provider（已配置的厂商账户）

模版数据（34 厂商接口定义）放**代码内**随包分发（纯数据，[DSH] F1 的 `API_TEMPLATES` 模式），本表只存**用户已配置实例**。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | 稳定 id（如 `prov_deepseek_main`） |
| `template_key` | TEXT | NOT NULL | 代码内模版键（如 `deepseek`）；决定端点/字段路径/币种缺省 |
| `name` | TEXT | NOT NULL | 用户可见名 |
| `kind` | TEXT | CHECK IN ('balance','quota','none') | 有余额接口 / 订阅额度 / 无余额接口（[DSH] F1 三类） |
| `currency` | TEXT | NOT NULL | 记账币种（CNY/USD/…），建账后不可变（变币种=新建 scope） |
| `credential_ref` | TEXT | NOT NULL | **凭据引用名**（Hermes secret 名或插件凭据文件键），**永不存密钥本体**（§8.2） |
| `credential_fingerprint` | TEXT | NOT NULL | sha256(密钥) 前 24 位——分账 scope（[DSH] A2：`lib/index.js:1240`）；换 key 即换账本，数据不丢不混 |
| `base_url_override` | TEXT | NULL | 需 `{base}` 的模版才允许；写入须本机确认（`allow_custom_host`，[DSH] F2 `credentialMayGoTo` 同思路） |
| `match_ids` | TEXT(JSON) | NULL | 会话事件→provider 归属的模型名子串列表（缺省用模版） |
| `balance_json_paths` | TEXT(JSON) | NULL | 用户对模版字段路径/scale 的覆盖（空字段不覆盖模版默认，[DSH] F2 `mergeNonEmpty`） |
| `enabled` | INTEGER | 0/1 | 禁用后停止轮询，历史保留 |
| `created_at` / `updated_at` | INTEGER | NOT NULL | epoch ms |

### 2.2 Model（模型与定价）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | Hermes 模型 slug（`Usage.model`，`gateway-contract.generated.ts:558`） |
| `display_name` | TEXT | NULL | 友好名（只标注不合并数据，[DSH] A4 旧名处理） |
| `provider_id` | TEXT | FK→Provider, NULL | 归属厂商；NULL=未匹配（Hermes 事件只带 model 名） |
| `pricing_json` | TEXT(JSON) | NULL | 自定义单价 `{hit, miss, out, currency}`（每 1M tokens），校验沿用 [DSH] F3：单价 0–1000000、币种合法 |
| `pricing_source` | TEXT | CHECK IN ('hermes_estimate','whale_pricing','none') | 成本口径优先级：Hermes 核心已算 `cost_usd` → 用之；否则 whale 定价；都无 → 只记 token 不记钱（诚实降级） |
| `enabled` | INTEGER | 1 | 软删除保留历史归因 |

> 定价快照不建独立表：TurnCost 行内冻结当轮 `pricing_json`（§2.4），改价不重写历史。

### 2.3 UsageEvent（usage ledger 明细，轨①）

一行 = 一次**被采纳的 turn 终值 usage 快照差分**（不是逐 step、不是心跳）。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `dedup_key` | TEXT | **UNIQUE NOT NULL** | §3.2 公式 |
| `session_id` | TEXT | NOT NULL | Hermes runtime session id（事件 envelope `session_id`，`gateway-events.ts:36-54`） |
| `turn_seq` | INTEGER | NOT NULL | 插件本地 turn 序号（按 session 计数，见 §3.2——Hermes 无稳定 turn id） |
| `source_event` | TEXT | NOT NULL | 固定 `message.complete`（当前唯一落库入口，扩展位） |
| `model` | TEXT | NOT NULL | |
| `provider_id` | TEXT | FK→Provider, NULL | 归属（match_ids 命中才填） |
| `input_tokens` / `output_tokens` / `reasoning_tokens` / `cache_read_tokens` / `cache_write_tokens` | INTEGER | NOT NULL DEFAULT 0 | 五类 token（[AUDIT] §5.2 `session_model_usage` 同口径）；**reasoning 不另计费**（reasoning ⊆ output，[DSH] A3 issue #89） |
| `calls_delta` | INTEGER | NULL | 会话累计 API 调用差分（`Usage.calls`） |
| `context_used` / `context_max` / `context_percent` | INTEGER/REAL | NULL | 原样留存（可选字段，缺省 NULL 不造 0） |
| `cumulative_json` | TEXT(JSON) | NOT NULL | 落库时的会话累计快照原样留存（`Usage` 全量），审计与重放用 |
| `raw_payload_json` | TEXT(JSON) | NOT NULL | `message.complete` 的 usage 子对象原样留存（脱敏后，§8.4） |
| `profile_name` | TEXT | NULL | envelope `profile` |
| `day` | TEXT | NOT NULL | 本地时区日键 `YYYY-MM-DD`（§5.2） |
| `received_at` | INTEGER | NOT NULL | epoch ms（落库时刻） |

### 2.4 TurnCost（每轮成本，轨①结算产物）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `dedup_key` | TEXT | **UNIQUE NOT NULL** | 与 UsageEvent 同公式（§3.2）——一个 turn 一条，天然幂等 |
| `session_id` / `turn_seq` / `model` / `provider_id` / `day` | 同 UsageEvent | NOT NULL | |
| `estimated_cost_units` | INTEGER | NOT NULL | **定点 1e8**。命名前缀 `estimated_` 强制（§8） |
| `currency` | TEXT | NOT NULL | |
| `cost_basis` | TEXT | CHECK IN ('hermes_estimate','whale_pricing','token_only') | `hermes_estimate`=直接采用 Hermes `Usage.cost_usd`（存在且 cost_status 非 'included' 时）；`whale_pricing`=tokens×pricing；`token_only`=无价可算，只记 token |
| `pricing_snapshot_json` | TEXT(JSON) | NULL | 结算当轮所用单价快照（改价不重写历史） |
| `status` | TEXT | CHECK IN ('final','provisional') | turn `status='complete'` → final；`error/interrupted` 但有 usage → provisional（部分消耗，仍计入，UI 标注） |
| `settled_at` | INTEGER | NOT NULL | |

### 2.5 BalanceSnapshot（余额观测，轨②）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `provider_id` | TEXT | FK→Provider NOT NULL | |
| `scope` | TEXT | NOT NULL | `<credential_fingerprint>`（API key 路）；分账本键（[DSH] A2） |
| `currency` | TEXT | NOT NULL | |
| `observed_balance_units` | INTEGER | NOT NULL | 定点 1e8 |
| `granted_units` / `topped_up_units` | INTEGER | NULL | 赠金/充值分项；**取不到是 NULL 不是 0**（[DSH] A1：`lib/index.js:1231-1240`） |
| `raw_response_json` | TEXT(JSON) | NOT NULL | provider 原始响应留存（字段白名单过滤后，§8.4） |
| `fetched_at` | INTEGER | NOT NULL | epoch ms |
| `fetch_state` | TEXT | CHECK IN ('ok','stale_cache') | 只允许成功观测入库；`stale_cache` 标注此行为缓存重放（避免与真实观测混淆）——正常路径只写 `ok` |
| UQ | — | `UNIQUE(provider_id, scope, currency, observed_balance_units, fetched_at)` | 同值同时刻重复观测去重（双路由/重试竞态） |

差分规则（写入 BalanceLedger 聚合，物化进 DailySummary §2.7）：
- 相邻同 `(scope, currency)` 观测，`delta = prev.observed_balance_units - cur.observed_balance_units`；
- `delta > 0` → `observed_spend += delta`；`delta < 0` → `credit += -delta`（**不冲销**，[DSH] A2 `accounting.mjs:176-179`）；
- 乱序/重复样本：`cur.fetched_at <= prev.fetched_at` 直接忽略（[DSH] A2 `accounting.mjs:167` 单调规则）。

### 2.6 BalanceAdjustment（余额校正，轨②闭环）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `scope` / `currency` | TEXT | NOT NULL | 校正按账本 scope 生效 |
| `day` | TEXT | NOT NULL | 归属统计日 |
| `credits_units` | INTEGER | NOT NULL | 用户填：本区间**累计到账金额**（未充值填 0） |
| `other_debits_units` | INTEGER | NOT NULL DEFAULT 0 | 非调用扣减 |
| `implied_usage_units` | INTEGER | NOT NULL | 校正公式结果：`opening + credits − otherDebits − last`（[DSH] A2 `accounting.mjs:207-242`） |
| `revision` | TEXT | NOT NULL | 乐观并发串（active 行 + 日期 + lastUnits + debit/credit + revision），不匹配返回 409（[DSH] `accounting.mjs:118-121, 213-217`） |
| `correction_log_json` | TEXT(JSON) | NULL | 校正说明，保留最近 50 条（[DSH] `accounting.mjs:232-234`） |
| `created_at` | INTEGER | NOT NULL | |

`needs_review` 判定：`credit_units > (最近一次校正已解释的 credit)` → 当日标「待核对」（[DSH] A2 `balanceSummary, accounting.mjs:123-142`）。

### 2.7 DailySummary（日聚合，互校载体）

复合 PK `(scope, day)`。scope 语义按轨不同：轨① scope=`profile+currency`（usage 估算账），轨② scope=`credential_fingerprint+currency`（观测账）——**两轨行分开存**，用 `track` 列区分，禁止跨轨同键合并。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `scope` / `day` | TEXT | PK | |
| `track` | TEXT | CHECK IN ('usage','balance') | PK 实际为 `(scope, day, track)` |
| `currency` | TEXT | NOT NULL | |
| `opening_units` / `last_units` | INTEGER | NULL | 轨②：当日首末观测（跨零点新建行时 opening 取「此刻余额」，起点前消费**漏记**，如实标注，[DSH] A2 `accounting.mjs:32-65`） |
| `observed_spend_units` / `credit_units` | INTEGER | NULL | 轨②：差分结果与到账累计 |
| `estimated_cost_units` | INTEGER | NULL | 轨①：当日 `sum(estimated_cost_units)` |
| `tokens_json` | TEXT(JSON) | NULL | 轨①：按 token 类别与按 model 聚合（展示直接读） |
| `partial` | INTEGER | 0/1 | 观测缺口标记（§4.3，[DSH] `partialDay` 思路） |
| `observed_from` / `observed_to` | INTEGER | NULL | 当日有效观测窗口（epoch ms） |
| `gap_seconds` | INTEGER | NULL | 缺口时长 |
| `deviation_units` / `deviation_ratio` | REAL | NULL | 互校结果（§4.2）；仅两轨同币种时可算 |
| `needs_review` | INTEGER | 0/1 | 待核对（§2.6） |
| `updated_at` | INTEGER | NOT NULL | |

### 2.8 Budget（预算配置）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | |
| `scope_type` | TEXT | CHECK IN ('global','provider','model') | 逐 provider/model 独立预算（[DSH] F1 能力） |
| `scope_ref` | TEXT | NULL | provider_id / model_id |
| `period` | TEXT | CHECK IN ('daily','monthly') | |
| `amount_units` | INTEGER | NOT NULL | 定点 1e8 |
| `currency` | TEXT | NOT NULL | |
| `basis` | TEXT | CHECK IN ('estimated_local','observed_balance') | 比较口径声明：默认估算口径；`observed_balance`=观测口径。**币种不一致且无汇率 → 不比较、不误报**（[DSH] D1 `runApiModelAlerts` 原则） |

触发状态不在此表——见 Notification（§2.10）的 dedup_key 设计。

### 2.9 Quota（订阅/手动额度）

配置与观测分离：本表存配置与**最新观测**，历史观测进 `quota_observations`（append-only，归档同 §5）。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PK | |
| `provider_id` | TEXT | FK→Provider NOT NULL | |
| `mode` | TEXT | CHECK IN ('api','cumulative','manual') | api=官方接口；cumulative=会话 token 累计（口径 `input+cacheRead+output`，[DSH] F3）；manual=面板手填 |
| `unit` | TEXT | CHECK IN ('tokens','money','percent') | 单位=金额时自动统计不成立 → 回退 manual（[DSH] F3） |
| `reset` | TEXT | CHECK IN ('none','daily','monthly','window') | |
| `base_at` | INTEGER | NULL | cumulative 模式基准 |
| `manual_used_units` | INTEGER | NULL | manual 模式当前值 |
| `windows_json` | TEXT(JSON) | NULL | 多窗口（如 5h/weekly/monthly）：`[{key,label,percent,used,total,reset_at}]`，归一化结构（[DSH] F1 quota.windows） |
| `last_observed_at` | INTEGER | NULL | |
| `last_state` | TEXT | CHECK IN ('ok','unavailable','error',NULL) | 显式不可用原因进 `last_error`——**没有 quota API 不算错误、不伪造进度条**（[REF] §1.1 / §5.1 fail-open 诚实设计） |

### 2.10 Notification（提醒与去重）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `kind` | TEXT | CHECK IN ('budget','balance_low','turn_cost','wait_input','wait_approval','error','balance_change') | 对应归一化事件（ARCHITECTURE_DECISION §事件流表） |
| `rank` | INTEGER | NOT NULL | 优先级：预算 1 > 预警 2 > 消耗 3 > 等待 4（等待类**抢占式**上屏，[DSH] D3） |
| `dedup_key` | TEXT | **UNIQUE NOT NULL** | 见下 |
| `payload_json` | TEXT(JSON) | NOT NULL | 泡泡渲染所需数据（Render Model 输入，脱敏） |
| `fired_at` | INTEGER | NOT NULL | |
| `ttl_ms` | INTEGER | NOT NULL DEFAULT 0 | 0=常驻（等待类），>0=自动关（[DSH] D3） |
| `dismissed_at` | INTEGER | NULL | |

**dedup_key 规则**（重启/重载不重响的唯一持久依据）：
| kind | dedup_key | 语义 |
|---|---|---|
| budget | `budget:<budget_id>:<day>` | 同日同预算只弹一次（对应 [DSH] D1 `usageBudgetFiredKey='日期:金额'`，但改为持久化，避免重启重响——对 DSH 行为的有意改进） |
| balance_low | `low:<scope>:<threshold>` | 边沿触发：恢复高于阈值后删除该键才可再响（迟滞，[DSH] D1 内存布尔语义 + 持久化） |
| turn_cost | 无键（由 turn dedup_key 承接） | 每轮一响，seq 对齐防重放（[DSH] A3 seq 双持久化思路，落库侧即 TurnCost UNIQUE） |
| wait_input / wait_approval | `wait:<kind>:<slot_id>` | 同一挂起只响一次；声音与泡泡共用键（[DSH] D1/D4 localStorage 去重的 DB 版） |

---

## 3. 幂等与去重

### 3.1 Hermes 侧稳定 ID 可得性（事实基础）

| 候选 ID | 可用性 | 依据 |
|---|---|---|
| 事件全局唯一 id | **无**。envelope 只有 `{type, payload?, session_id?, profile?, connectionId?, seq?, replayed?, replayEpoch?}` | `apps/shared/src/gateway-events.ts:36-54` |
| `seq` | 不可跨连接使用：WS 重连后 replayEpoch 变化，seq 属于连接内重放序 | 同上 + [AUDIT] §4.3 |
| turn id | **无稳定 turn id**。`MessageCompletePayload` 无 turn 字段（有 `persisted_turn` 但语义为持久化回执，非稳定轮次 ID） | `gateway-contract.generated.ts:4555-4571`（已抽查） |
| usage 数值口径 | `Usage` 的 input/output/calls 等是**会话级累计值**（agent 内存计数器），非单轮值 | `tui_gateway/server.py:2178-2223`（[AUDIT] §5.1）；`Usage` 接口字段全可选 `gateway-contract.generated.ts:558-581`（已抽查） |
| 权威终值 | `message.complete` 携带 usage，且 ticker 在 complete 前停表（晚到 tick 会回滚终值）→ complete 是唯一可信终值 | `server.py:3451-3475` 注释、`server.py:2393`、`_session_usage_snapshot:2274-2279` |

**结论**：turn 增量 = 相邻两次会话累计快照之差，必须自建去重。

### 3.2 dedup_key 公式（轨①主键去重）

```
dedup_key = sha256_hex(
    session_id            -- 会话分桶（防跨会话串账，[DSH] A3 Map 分桶思路）
  | day_bucket            -- 本地日 YYYY-MM-DD（防跨天碰撞）
  | minute_bucket         -- received_at 截断到分钟（时间窗，§3.4）
  | turn_seq              -- 插件本地 turn 序号
  | source_event          -- 事件类型
  | model
  | input | output | cache_read | cache_write | reasoning   -- 内容哈希
  | cost_basis | estimated_cost_units                       -- 结算内容哈希
)[: 40]
```

- **内容哈希 + (sessionId, turn) 分桶 + 分钟时间窗**：同一 turn 若因重连重放/热重载重发两次，minute_bucket 与内容完全一致 → UNIQUE 约束拒绝第二条；`turn_seq` 由 Python 半体按 session 持久计数（SessionWatermark 表），JS 半体无状态，重载后从终值推断不产生新键。
- UNIQUE 冲突 → `INSERT OR IGNORE`，返回 `duplicate` 给调用方，**不报错不重复弹泡**。

### 3.3 SessionWatermark 与计数器重置

```
session_watermark(session_id PK,
  last_input / last_output / last_cache_read / last_cache_write / last_reasoning INTEGER,
  last_calls INTEGER NULL,
  last_seen_at INTEGER, reset_count INTEGER DEFAULT 0)
```

- turn 增量 = `complete 快照 − watermark`；watermark 落库（Python 半体权威），**JS 半体重载零影响**。
- **重置检测**：`快照 < watermark`（gateway 重启 / agent 重建导致内存计数器归零）→ 不产生负增量：本 turn 标 `status='provisional'`、`cost_basis='token_only'`（增量未知），watermark 对齐新值、`reset_count += 1`，交给轨③交叉校验补正（§4）。**此为已知盲区，诚实标记而非静默错记。**
- 会话结束（`sessions.changed` 移除 / 长期无活动 24h）→ watermark 行保留至保留期清理（§5），期间重复快照差值=0 天然幂等。

### 3.4 场景矩阵（每行都要能回答「会不会重复记账」）

| 场景 | 发生什么 | 处理 | 是否重复 |
|---|---|---|---|
| WS 重连（同 gateway） | 事件流重放（`replayed=true` + 新 replayEpoch） | 重放事件进同一 dedup 公式（minute_bucket+内容哈希不变）→ UNIQUE 拒绝；JS 半体重连后**首条 complete 只对齐 watermark 不结算**（[DSH] A3「首次对齐不弹」思路） | 否 |
| gateway 重启（`host.restartGateway`） | agent 重建，内存计数器可能清零 | §3.3 重置检测 → provisional + 轨③校验 | 否（但该 turn 增量可能缺失，残留风险 §3.6-R1） |
| JS 半体热重载 | fs-watch 重载，ctx 订阅重建 | JS 无状态转发；watermark/turn_seq 在 Python+DB | 否 |
| 插件禁用再启用 | 事件窗口出现空洞 | 空洞即漏记：轨②下一次观测差分会**包含**空洞期消耗（余额差分天然补记），轨①漏记并标 partial（§4.3）——两轨互补是设计的一部分 | 否 |
| App 强退/崩溃 | 未落库的当前 turn 丢失 | 该 turn 消耗由轨②下次观测差分兜住；轨①接受漏一轮（诚实缺口） | 否 |
| 双路由重试竞态（余额） | 两次观测同值同刻 | §2.5 UQ + `fetched_at <= last` 单调忽略 | 否 |
| Hermes 事件 payload 重复（同一 complete 重发同内容） | 同 turn 同内容 | minute_bucket+内容哈希 → UNIQUE 拒绝 | 否 |

### 3.5 scope（分账本键）约定

- 轨①：`usage:<profile>:<currency>`（profile 来自 envelope；跨 profile 各自成账，不合并）。
- 轨②：`balance:<credential_fingerprint>:<currency>`（换/删 key = 换一本账，历史账显示为「历史账户」不相加，[DSH] A2 issue #163 语义）。
- 轨③：Hermes `state.db` 只读，不产生 scope，按 `(profile, billing_provider)` 对齐到轨①比较。

### 3.6 残留风险（显式记录，不掩盖）

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | 计数器重置窗口的 turn 增量缺失/失真 | 轨①当日估算偏低 | provisional 标记 + 轨③ `session_model_usage` 校验（该表按六键 PK upsert 累加、天然幂等，`hermes_state_common.py:481-503` 已抽查） |
| R2 | 极小概率内容哈希碰撞：同 session 同分钟两个真实 turn 的五类 token 与结算完全一致 | 少记一轮估算（金额影响 ≤ 一轮） | minute_bucket 已将概率压到可忽略；轨②不受影响 |
| R3 | Hermes resume 后 session_id 变化 → 同一逻辑会话被拆两本 | watermark 重开，增量断点 | 可接受：turn 级仍各自正确；`session.reclaimed`/resume 事件（[AUDIT] §4.1）用于清理 watermark（未验证其时序，列为 probe 项） |
| R4 | `Usage` 字段缺省语义（可选字段） | 把 NULL 当 0 记账 | 全字段 NULL 感知，NULL 不参与求和（[AUDIT] §12 已警示） |
| R5 | 轨②非 API 扣减（纠错扣款等）与 API 消耗在观测层面不可区分 | observed_spend 虚高 | 靠校正闭环（§2.6），UI 标「已观测消费」而非「消费」（[DSH] A2 语义） |

---

## 4. 双轨交叉验证

### 4.1 三轨定义

| 轨 | 数据 | 权威性 | 失败语义 |
|---|---|---|---|
| 轨① usage ledger | `message.complete` → token × pricing / Hermes cost_usd | **估算**（即使来自 Hermes 也是 estimate） | 漏 turn = 漏记，标 partial |
| 轨② balance ledger | 余额观测差分 + 校正 | **观测**（余额真值推演） | 插件/App 离线期漏记，partial 标记 |
| 轨③ state.db 交叉校验（可选） | 只读 `session_model_usage` / `sessions` 的 token、`estimated_cost_usd`、`actual_cost_usd`、`cost_status` | Hermes 核心账本（内部实现，非公开 API） | 只读、fail-open：读不到不影响主轨 |

> 与 [REF] §6.1 结论的关系：REF 推荐「只读订阅 state.db 是正解」，本文将其采纳为**第三轨交叉校验 + 降级数据源**而非主源（已定架构方向；理由：轨①②不依赖 Hermes 内部 schema，兼容面最小；state.db 的价值在互校与 R1 补正）。若未来 Hermes 提供官方只读 usage API，轨③可升级为权威校验源。

### 4.2 互校公式与偏差分类

对同 `(日, 币种)`：

```
deviation = observed_spend(轨②) − estimated_cost(轨①)
deviation_ratio = deviation / max(observed_spend, ε)
|deviation_ratio| ≤ 5%（可配） → consistent
```

| 偏差模式 | 典型原因 | UI 呈现 |
|---|---|---|
| 轨① < 轨②，持续多日 | 定价表过时/未覆盖模型；未归因扣减 | 「观测高于估算」，提示补定价 |
| 轨① > 轨② | 免费额度/订阅内消耗（`cost_status='included'`，[REF] 附：实证样本）；币种口径差 | 「估算高于观测」，不告警只标注 |
| 轨② credit > 0 且未校正 | 充值/赠金 | 「待核对余额调整」（§2.6） |
| 轨② 缺失整天 | provider 无余额接口 / 轮询关闭 | 轨②列显示 `—`，不显示 0 |
| 两轨皆缺 | 无数据 | `—` |

币种不同**不比较**（宁可不比较也不误报，[DSH] D1 原则）；轨① `cost_basis='token_only'` 的轮次不计入 estimated_cost 参与 dev_ratio（避免把「无价」算成 0 偏差）。

### 4.3 观测缺口标记（partialDay 思路）

- 规则：当日首次观测距 00:00 > `PARTIAL_GAP_MS`（10 分钟，沿用 [DSH] A2 `accounting.mjs:38-65`），或末次观测距次日 00:00 > 10 分钟 → `partial=1`，记录 `observed_from/observed_to/gap_seconds`。
- 插件离线期（App 关闭/禁用）：消耗漏记于轨②当日行（下次观测新基准起算），partial=1；轨①同一时期按 turn 有则记无则缺。互校时 `partial=1` 的日期 dev_ratio **不参与**「定价漂移」判定（缺口会污染结论），只显示缺口时长。
- 跨零点新建轨②日行：`opening` = 此刻余额（起点前消费被吞，如实标注，[DSH] `accounting.mjs:32-65` 长注释），UI 显示「观测起点 HH:MM」。

### 4.4 轨③兼容门（schema_version gate）

- 只读打开范式：`sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)` 全容错（[REF] §1.3 `plugin_api.py:199-221`；WAL 读写不阻塞，本机实证）。
- **门 1**：读 `schema_version` 表（`hermes_state_common.py:372`；本机实证 v31）。已知可用集 {30, 31}（本机审计版本）——未知版本：**轨③自动禁用 + UI 告警**（fail-closed 只作用于这条可选轨），主轨不受影响。
- **门 2**：列存在性检查（`PRAGMA table_info(session_model_usage)`），缺列降级为可用列子集。
- **门 3**：读频 ≤ 60s 一次、单实例（生命周期矩阵约束）；查询失败静默降级为「轨③不可用」状态，绝不 500 到 UI。
- 成本语义处理：`estimated_cost_usd`、`actual_cost_usd`、`cost_status` 因 `billing_mode/task` 填充策略不同，`None` 与 `0` 语义不同（[REF] 附：一手数据点）——NULL 一律按「未计费」处理，不并入偏差分子。

---

## 5. 每日归档与保留策略

### 5.1 保留阈值（沿用 [DSH] A2：`lib/index.js:1298-1356` 量级）

| 数据 | 热表保留 | 超期动作 | 归档上限 |
|---|---|---|---|
| UsageEvent + TurnCost | 90 天 **或** 2 万条（先到） | 移入 `*_archive` 表，**不删除** | archive 20 万条 |
| BalanceSnapshot | 90 天 | 移入 archive | 20 万条 |
| DailySummary | 365 天 | 移入 `summary_archive`（超期数据长期可查） | 20 万条 |
| Quota 观测 | 90 天 | 直接删除（有日聚合即可） | — |
| Notification | 30 天 | 直接删除（无归档价值） | — |
| SessionWatermark | 无活动 30 天 | 删除 | — |

### 5.2 日键与执行时机

- 日键 `day = 本地时区 YYYY-MM-DD`。DSH 硬编码北京时间是 DeepSeek 峰谷价的特定需求；本项目定价不绑 DeepSeek 时段（自定义单价无峰谷，Phase 1），故用**本地时区**；若未来引入峰谷价目，按 provider 模版声明目标时区。*
- 归档执行：Python 半体每日 tick + 每次 turn 结算后顺手 prune（单实例，无并发写冲突）；archive 满则丢弃最旧（与 DSH 一致）。
- 迁移归档只搬不删原则的例外：Notification/Watermark 类无审计价值数据直接删。

---

## 6. 余额状态机

状态存 Python 半体内存 + `WhaleMeta`（`balance_state:<provider_id>`），**API 失败绝不当 0**（AGENTS.md §8 / §10）。

```
             ┌─────────┐  首次成功且 balance>0        ┌────────────┐
             │ unknown │ ───────────────────────────► │     ok     │
             └────┬────┘                              └──┬──────┬──┘
                  │ 首次成功且 balance==0                │ 刷新失败 │ 明确返回 total==0
                  ▼                                    ▼          ▼
             ┌─────────┐                          ┌──────────┐ ┌─────────┐
             │  zero   │ ◄──────────────────────── │  stale   │ │  zero   │
             └─────────┘                          └────┬─────┘ └─────────┘
                  ▲     失败但有历史成功值（显示旧值+「未刷新」）│
                  │                                        │ 连续失败且无缓存
                  │        ┌─────────┐                     ▼
                  └────────│  error  │ ◄──────────── 失败且无任何成功值
              失败但唯一历史值就是 0
```

| 状态 | 进入条件 | UI 语义 | 依据 |
|---|---|---|---|
| `unknown` | 无任何成功观测 | 余额模块显示 `—`（读不到 ≠ 0） | [DSH] C2「`—` 与 `0` 语义刻意区分」（`whale-widget.js:12671-12683`） |
| `ok` | 最近观测成功且 `now − fetched_at < FRESH_TTL`（90s，> 25s 服务端缓存 TTL） | 正常显示 | [DSH] A1（BALANCE_TTL_MS=25000 + stale 标记机制） |
| `stale` | 有历史成功值，最近刷新失败 | 显示旧值 + 「余额未刷新」，**不清零不闪错** | [DSH] A1 `lib/index.js:1246-1252` |
| `error` | 连续失败且无缓存 | `—` + 错误原因（4xx 凭据失效/5xx 网络，文案区分） | [DSH] A1 v781 双通道都失败才报错并带原因 |
| `zero` | **API 明确返回** total==0（或仅有赠金且赠金==0） | 显示 0 | 「只有赠金、充值钱包为空」必须算成功的新用户常态，[DSH] A1 `lib/index.js:1098-1115` |

硬规则：
1. `error/stale/unknown` 状态下**禁止**任何差分记账与预算比较（无基准）。
2. 瞬时失败重试策略：网络/5xx 重试 1 次（500ms），4xx 不重试（[DSH] A1）；在途请求去重（in-flight 复用，[DSH] `lib/index.js:2882-2923`）。
3. 「记账失败不吞余额」：账本写入异常时余额照常返回 + `ledger_error` 字段；但账本整体不可读必须 fail-closed（§7.4），（[DSH] `lib/index.js:2891-2910` 语义区分）。
4. 轮询：单实例 60s（[DSH] 同频）+ 点击手动刷新（`refresh=1` 绕缓存）；Phase 2 独立窗自身不轮询，只消费 Python 半体推送。

---

## 7. 存储选型：SQLite 表结构草案

### 7.1 为什么是 SQLite（最小可用论证）

- 唯一写者是 Python 半体（serve 进程内，单进程多线程）——SQLite WAL 足够，无需外部 DB；
- 轨③需要**只读并发**打开 Hermes `state.db`（WAL 下互不阻塞，[REF] §1 实证），同构技术栈；
- 插件数据目录内单文件，备份/迁移/删除 = 拷一个目录；
- Hermes 对桌面插件不提供任何服务端存储（`ctx.storage` 是渲染层明文 localStorage，[AUDIT] §2.3）——Python 半体自管存储是必然。

### 7.2 DDL 草案（whale.db，WAL 模式，`PRAGMA foreign_keys=ON`）

```sql
-- ── 支撑 ─────────────────────────────────────────────
CREATE TABLE whale_meta (
  key   TEXT PRIMARY KEY,            -- 'schema_version' | 'balance_state:<pid>' | 迁移标记…
  value TEXT NOT NULL
);
-- schema_version：本插件自有版本（当前 1），独立于 Hermes state.db 的 schema_version

CREATE TABLE session_watermark (
  session_id    TEXT PRIMARY KEY,
  last_input    INTEGER NOT NULL DEFAULT 0,
  last_output   INTEGER NOT NULL DEFAULT 0,
  last_cache_read  INTEGER NOT NULL DEFAULT 0,
  last_cache_write INTEGER NOT NULL DEFAULT 0,
  last_reasoning   INTEGER NOT NULL DEFAULT 0,
  last_calls    INTEGER,
  last_seen_at  INTEGER NOT NULL,
  reset_count   INTEGER NOT NULL DEFAULT 0
);

-- ── 轨① usage ledger ────────────────────────────────
CREATE TABLE provider (
  id TEXT PRIMARY KEY, template_key TEXT NOT NULL, name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN('balance','quota','none')),
  currency TEXT NOT NULL,
  credential_ref TEXT NOT NULL,             -- 引用名，永不存密钥本体
  credential_fingerprint TEXT NOT NULL,     -- sha256 前 24 位 = 轨② scope
  base_url_override TEXT, allow_custom_host INTEGER NOT NULL DEFAULT 0,
  match_ids TEXT, balance_json_paths TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);

CREATE TABLE model (
  id TEXT PRIMARY KEY, display_name TEXT,
  provider_id TEXT REFERENCES provider(id) ON DELETE SET NULL,
  pricing_json TEXT,                        -- {hit,miss,out,currency} 每 1M tokens
  pricing_source TEXT NOT NULL DEFAULT 'none'
    CHECK(pricing_source IN('hermes_estimate','whale_pricing','none')),
  enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE usage_event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dedup_key TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL, turn_seq INTEGER NOT NULL,
  source_event TEXT NOT NULL DEFAULT 'message.complete',
  model TEXT NOT NULL,
  provider_id TEXT REFERENCES provider(id) ON DELETE SET NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0,
  calls_delta INTEGER, context_used REAL, context_max REAL, context_percent REAL,
  cumulative_json TEXT NOT NULL, raw_payload_json TEXT NOT NULL,
  profile_name TEXT, day TEXT NOT NULL, received_at INTEGER NOT NULL
);
CREATE INDEX idx_usage_event_session ON usage_event(session_id, turn_seq);
CREATE INDEX idx_usage_event_day     ON usage_event(day);

CREATE TABLE turn_cost (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dedup_key TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL, turn_seq INTEGER NOT NULL,
  model TEXT NOT NULL,
  provider_id TEXT REFERENCES provider(id) ON DELETE SET NULL,
  estimated_cost_units INTEGER NOT NULL,    -- 定点 1e8；命名红线：estimated_
  currency TEXT NOT NULL,
  cost_basis TEXT NOT NULL CHECK(cost_basis IN('hermes_estimate','whale_pricing','token_only')),
  pricing_snapshot_json TEXT,
  status TEXT NOT NULL DEFAULT 'final' CHECK(status IN('final','provisional')),
  day TEXT NOT NULL, settled_at INTEGER NOT NULL
);
CREATE INDEX idx_turn_cost_day ON turn_cost(day, currency);

-- ── 轨② balance ledger ──────────────────────────────
CREATE TABLE balance_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider_id TEXT NOT NULL REFERENCES provider(id) ON DELETE CASCADE,
  scope TEXT NOT NULL, currency TEXT NOT NULL,
  observed_balance_units INTEGER NOT NULL,  -- 定点 1e8
  granted_units INTEGER, topped_up_units INTEGER,   -- NULL ≠ 0
  raw_response_json TEXT NOT NULL,
  fetched_at INTEGER NOT NULL,
  fetch_state TEXT NOT NULL DEFAULT 'ok' CHECK(fetch_state IN('ok','stale_cache')),
  UNIQUE(provider_id, scope, currency, observed_balance_units, fetched_at)
);
CREATE INDEX idx_balance_snapshot_scope ON balance_snapshot(scope, currency, fetched_at);

CREATE TABLE balance_adjustment (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT NOT NULL, currency TEXT NOT NULL, day TEXT NOT NULL,
  credits_units INTEGER NOT NULL, other_debits_units INTEGER NOT NULL DEFAULT 0,
  implied_usage_units INTEGER NOT NULL,
  revision TEXT NOT NULL, correction_log_json TEXT,
  created_at INTEGER NOT NULL
);

-- ── 聚合与规则 ───────────────────────────────────────
CREATE TABLE daily_summary (
  scope TEXT NOT NULL, day TEXT NOT NULL,
  track TEXT NOT NULL CHECK(track IN('usage','balance')),
  currency TEXT NOT NULL,
  opening_units INTEGER, last_units INTEGER,
  observed_spend_units INTEGER, credit_units INTEGER,
  estimated_cost_units INTEGER, tokens_json TEXT,
  partial INTEGER NOT NULL DEFAULT 0,
  observed_from INTEGER, observed_to INTEGER, gap_seconds INTEGER,
  deviation_units REAL, deviation_ratio REAL,
  needs_review INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY(scope, day, track)
);

CREATE TABLE budget (
  id TEXT PRIMARY KEY,
  scope_type TEXT NOT NULL CHECK(scope_type IN('global','provider','model')),
  scope_ref TEXT,
  period TEXT NOT NULL CHECK(period IN('daily','monthly')),
  amount_units INTEGER NOT NULL, currency TEXT NOT NULL,
  basis TEXT NOT NULL DEFAULT 'estimated_local'
    CHECK(basis IN('estimated_local','observed_balance')),
  enabled INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL
);

CREATE TABLE quota (
  id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL REFERENCES provider(id) ON DELETE CASCADE,
  mode TEXT NOT NULL CHECK(mode IN('api','cumulative','manual')),
  unit TEXT NOT NULL CHECK(unit IN('tokens','money','percent')),
  reset TEXT NOT NULL CHECK(reset IN('none','daily','monthly','window')),
  base_at INTEGER, manual_used_units INTEGER,
  windows_json TEXT, last_observed_at INTEGER,
  last_state TEXT CHECK(last_state IN('ok','unavailable','error') OR last_state IS NULL),
  last_error TEXT
);
CREATE TABLE quota_observation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  quota_id TEXT NOT NULL REFERENCES quota(id) ON DELETE CASCADE,
  window_key TEXT NOT NULL DEFAULT 'main',
  used_units INTEGER, total_units INTEGER, percent REAL, reset_at INTEGER,
  observed_at INTEGER NOT NULL
);

CREATE TABLE notification (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK(kind IN('budget','balance_low','turn_cost','wait_input',
                                   'wait_approval','error','balance_change')),
  rank INTEGER NOT NULL,
  dedup_key TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL,
  fired_at INTEGER NOT NULL, ttl_ms INTEGER NOT NULL DEFAULT 0,
  dismissed_at INTEGER
);

-- ── 归档（§5）：结构同源表 + archived_at 列，略 ─────
```

### 7.3 迁移策略

- `whale_meta.schema_version` 单调递增；启动时 `schema_migrations`（代码内列表）逐级执行，每级一个事务；写前备份 `whale.db → whale.db.bak-<ver>`（对应 DSH「首次写新版前自动备份」思路，[DSH] A2 `lib/index.js:1281-1287`）。
- 迁移失败 → fail-closed：新版本代码拒绝写旧结构库（§7.4），UI 明示并给出备份路径。

### 7.4 IO 健壮性

- 崩溃安全：WAL + `synchronous=FULL`（记账正确性优先于写放大）。
- 结构异常/损坏：**拒绝覆盖**、转储 `.corrupt-<ts>` 后按用户确认重建（fail-closed，对应 [DSH] `readUsageLedger` 拒绝覆盖思路 `lib/index.js:1266-1275`）；恢复期间余额显示不中断（`ledger_error` 语义）。
- Windows 文件占用（索引器）：短锁退避重试（[DSH] `ledgerIo, lib/index.js:1256-1265` 同思路）。
- 写路径全部幂等（UNIQUE 承接），重放安全。

---

## 8. UI 数据契约：估算值永不伪装成真实账单

### 8.1 字段命名规范（契约级，REST payload 强制）

| 前缀/后缀 | 含义 | 例 |
|---|---|---|
| `observed_*` | 余额观测/差分推演 | `observed_balance`, `observed_spend` |
| `estimated_*` | 本地/核心估算成本 | `estimated_cost`, `estimated_today` |
| `reported_*` | provider 官方报告 | `reported_used`, `reported_percent` |
| `adjustment_*` | 用户显式校正 | `adjustment_credits` |
| `*_units` | 定点 1e8 整数（配 `currency` 字段） | `estimated_cost_units` |
| `basis` / `cost_basis` | 该数值的来源口径声明 | `'whale_pricing'` |
| `confidence` | 行级置信标签 | `'observed' \| 'estimated' \| 'reported' \| 'derived'` |
| `partial` / `gap_seconds` | 缺口诚实标注 | §4.3 |
| `stale` / `ledger_error` / `unavailable_reason` | 降级语义 | §6 / §2.9 |

**REST 端点禁止返回**无前缀的裸 `cost` / `spend` / `used` 字段——review checklist 项（AGENTS.md §8 的 API 面落地）。

### 8.2 凭据在数据模型中的形态

- `provider.credential_ref` 只存引用名；任何 API 响应只含 `{credential_id, name, configured, source}`（[AUDIT] §8 结论：凭据解析在 Python 半体进程内完成，从不序列化——ai-usage-tracker 同模式）。
- 密钥本体允许落点仅两处：Hermes secret_sources（优先，`hermes_cli/config.py:1583-1594` get_secret）/ 插件凭据文件（兜底，权限约束见 ARCHITECTURE_DECISION §持久化布局）。

### 8.3 三条 UI 语义铁律（与 DSH 产品语义对齐）

1. 取不到数显示 `—` 而非 `0`（`null` ≠ 0 的序列化契约：JSON 字段缺省/`null` = 读不到；`0` = 真实为零）（[DSH] C2）。
2. 「已观测消费 / 已校正消费 / 待核对余额调整」三态标签由 `needs_review` + 校正记录推导，**observed_spend 永不直接叫「消费」**（[DSH] A2）。
3. 估算口径的图表/占比必须带「估算」角标；双轨数字**并排展示、永不合并**为一个数。

### 8.4 留存原样的脱敏边界

`raw_payload_json` / `raw_response_json` 落库前过滤：只保留白名单字段（token 计数、余额数值、币种、状态码）；丢弃 headers、request id、账号 id、`Authorization` 及一切 `sk-`/`Bearer` 形态字符串（AGENTS.md §7；日志同规则）。
