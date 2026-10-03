# USER_FLOW_CHECKLIST — 用户真实使用流程检查清单

> Goal 收尾产物（2026-10-03 建档）。按用户真实使用顺序组织，每条流程给出：
> **入口 → 链路各环节 → 预期结果 → 验证方式（自动化测试名 / 人工步骤）→ 状态**。
>
> 基线：commit `49e895b`（P0-1/P0-2 修复 + M9 接线），**node 190 / pytest 184 全绿**（本清单建档时实测）。
>
> ## 状态标记约定
>
> - **AUTO**：该环节已被自动化测试覆盖（括号内为测试文件/用例名；`pytest` 测试位于
>   `plugin-src/hermes-whale-widget/dashboard/tests/`，node 测试位于
>   `plugin-src/hermes-whale-widget/desktop/tests/`）。
> - **NOT VERIFIED（待真机）**：需把插件部署到 `D:\hermes\plugins\whale-widget\`（用户手动执行，
>   步骤见 [`../../INSTALL.md`](../../INSTALL.md)）后人工验证。原因：AGENTS.md §0 规定 `D:\hermes`
>   只读，agent 不得代为部署；真机才有的因素（真实网关事件 payload、真实 DeepSeek API、真实
>   Electron 音频面、真实审批流）无法在 TestClient / node:test 中复现。
>
> **汇总**：10 条流程的链路核心环节均已有自动化覆盖（10/10）；全部 10 条的端到端真机验证待用户
> 部署后执行（0/10 完成）。

---

## 流程 1：首次启用 → 浮窗出现 →「—」未配置凭据语义

| # | 环节 | 预期结果 | 验证方式 | 状态 |
|---|---|---|---|---|
| 1.1 | 部署 + 启用（INSTALL §4–§5） | serve 启动挂载 `/api/plugins/whale-widget/`，数据目录自动创建 | 人工：重启后查看 `whale-widget/logs/whale-widget.log` 出现 `runtime started` | NOT VERIFIED（需部署） |
| 1.2 | Plugins 页 opt-in 桌面半体 | floating pane 出现占位鲸鱼，状态栏出现芯片 | AUTO：`register.test.mjs`（pane/chip 贡献注册、area 断言）+ `main-wiring.test.mjs` 'floating pane contribution: area panes + native floating data + WhalePane render' | AUTO ✅；真机视觉 NOT VERIFIED |
| 1.3 | `/health` 可用 | `{"ok":true,"plugin":"whale-widget","schema_version":1,...}` | AUTO：`test_health.py`（CON-00） | AUTO ✅；真机探活 NOT VERIFIED |
| 1.4 | 未配置凭据时的余额语义 | 余额显示 `—` + 配置提示（不是 0、不是报错） | AUTO：`balance-view.test.mjs` 'unconfigured credential → `—` + configuration hint, regardless of state'、'missing payload → `—` ... (never 0)' | AUTO ✅；真机 NOT VERIFIED |

## 流程 2：配置凭据 → 余额轮询 → ok 显示

| # | 环节 | 预期结果 | 验证方式 | 状态 |
|---|---|---|---|---|
| 2.1 | 配置凭据（secret_scope / env / credentials.json 三选一，INSTALL §7） | REST 只暴露 `{configured, source, credential_id, fingerprint}`，无密钥本体 | AUTO：`test_balance.py`（gateway 凭据解析/指纹/无密钥断言） | AUTO ✅ |
| 2.2 | 余额轮询（`balance_poll_seconds=60`）→ 状态机 | ok / stale / error / unknown / zero 五态正确；API 失败 ≠ 0；in-flight 去重 | AUTO：`test_balance.py` 17 条（mock provider 8 类响应、单调忽略、轮询间隔钳制） | AUTO ✅ |
| 2.3 | 浮窗/芯片展示 ok 余额 | 格式化金额 + 币种；stale/error 保留上次值 + 角标 | AUTO：`balance-view.test.mjs`（ok/stale/error/zero/unknown 五态文本断言）、`data-service.test.mjs`（config → 轮询） | AUTO ✅ |
| 2.4 | 真实 DeepSeek API 端到端（真实 key + 真实 `/user/balance`） | 轮询进入 ok，浮窗显示真实余额 | 人工：部署后配真实 key（INSTALL §7 方式 A/B/C），观察浮窗 | NOT VERIFIED（需部署；真实接口字段时效未自动探测） |

## 流程 3：发起对话 → turn 结算 → 单轮消费泡泡（估算角标）→ 今日消费更新

| # | 环节 | 预期结果 | 验证方式 | 状态 |
|---|---|---|---|---|
| 3.1 | 网关事件捕获 → 归一化 | `message.complete` 按 status 分流；usage 字段缺省 → null 不造 0 | AUTO：`normalize.test.mjs`、`turn-tracker.test.mjs` | AUTO ✅ |
| 3.2 | turn 终值转发 → 幂等落库 → 三级计价 | `POST /ingest/turn` 幂等（重放 → duplicate）；hermes_estimate > whale_pricing > token_only | AUTO：`test_ingest_contract.py`、`test_ledger_accounting.py`（ACC-01 幂等/重放）、`test_pricing_endpoints.py` | AUTO ✅ |
| 3.3 | settled 契约 → 单轮消费泡泡（含「估算」角标） | 响应 `settled[]` → turn_cost 泡泡 + money 表情；金额带估算语义；未计价轮显示 `—` | AUTO：`main-wiring.test.mjs` 'settled turn cost (WP-2 contract) → controller turn_cost bubble + money mood'、'ingest response without settled → no bubble'；`controller.test.mjs` 'turn_cost notification carries formatted estimate (est. honesty)'、'syncNotifications maps ... (— on missing money)' | AUTO ✅ |
| 3.4 | 今日消费更新 | `/usage/summary` 即时刷新（turn 触发 poke）+ 周期轮询 | AUTO：`main-wiring.test.mjs` 'config → data service start'；`test_usage_endpoints.py` | AUTO ✅ |
| 3.5 | 真实网关一轮对话端到端 | 发一轮对话 → 泡泡弹出 → 今日消费跳动；重放/重启不重复扣 | 人工：部署后发一轮对话观察；断言重放不重复由 AUTO 覆盖 | NOT VERIFIED（真实 `message.complete` payload 实形状待冒烟核对） |

## 流程 4：余额跌破阈值 → 余额不足常驻泡泡 → 回升自动消失

| # | 环节 | 预期结果 | 验证方式 | 状态 |
|---|---|---|---|---|
| 4.1 | 阈值评估（`thresholds.balance_low`，货币值；null = 规则关） | 快照成功后评估；`0 ≤ balance < 阈值` 触发（`balance_low:{scope}:{day}` 持久去重） | AUTO：`test_reminders.py`（触发/同日静默/跨日再响/规则关/非法值降级） | AUTO ✅ |
| 4.2 | 通知 → REST → 泡泡 | `GET /notifications` 按 rank 返回；桌面轮询映射为常驻泡（wait 类跳过防双显） | AUTO：`test_notifications_api.py`、`controller.test.mjs` 'syncNotifications maps rules-engine items to ranked bubbles' | AUTO ✅ |
| 4.3 | 回升 ≥ 阈值 → 常驻泡自动消失 | 服务端自动 dismiss 未过期预警 → 下轮轮询收泡 | AUTO：`test_reminders.py` '回升自动消除'；`controller.test.mjs` 'recovered standing alert is dismissed' | AUTO ✅ |
| 4.4 | 重启 App 不重响（DR-14） | 通知表持久去重，reset_runtime 重放 → duplicate | AUTO：`test_reminders.py` 重启模拟 | AUTO ✅ |
| 4.5 | 真机端到端 | 阈值设为高于当前余额的真实现金数 → 常驻泡出现；充值后消失 | 人工：改 config.json → 观察浮窗 | NOT VERIFIED（需部署） |

## 流程 5：今日消费达预算 → 预算泡泡

| # | 环节 | 预期结果 | 验证方式 | 状态 |
|---|---|---|---|---|
| 5.1 | 预算评估（`thresholds.daily_budget`，货币值） | turn 结算后评估 usage 轨当日估算合计；逐币种 scope 比较、不跨币种求和；`budget:{scope}:{day}` 按日去重 | AUTO：`test_reminders.py`（触发/重复/跨日重置/开关） | AUTO ✅ |
| 5.2 | 预算泡泡显示 | 预算 rank=1 最高优先，抢占上屏；文案带「估算值」标注 | AUTO：`controller.test.mjs`（ranked bubbles）、`bubble-*` 测试（默认内容含预算文案） | AUTO ✅ |
| 5.3 | 状态机非 ok 时禁止比较 | 余额 unknown/error/stale 不误报 | AUTO：`test_reminders.py`（比较前置门） | AUTO ✅ |
| 5.4 | 真机端到端 | 设小额预算跑一轮 → 泡泡弹出；次日重置 | 人工：改 config.json → 对话 → 观察 | NOT VERIFIED（需部署） |

## 流程 6：Agent 提问（clarify）→ 等待泡泡 + 等待表情 → 回答后消失

| # | 环节 | 预期结果 | 验证方式 | 状态 |
|---|---|---|---|---|
| 6.1 | clarify `tool.start/complete` 捕获 → `/ingest/wait-event` | open/close 按 `tool_id` 配对转发；其它工具静默；转发失败不影响记账 | AUTO：`main-wiring.test.mjs` 'clarify tool.start/complete → POST /ingest/wait-event open/close; other tools silent'、'failing /ingest/wait-event is silent' | AUTO ✅ |
| 6.2 | Python 侧挂起/解除 + 通知 | 白名单校验（畸形 400 不回显值）；`wait:question:<tool_id>` fire/dismiss；重放幂等 | AUTO：`test_wait_state.py`（挂起/解除/幂等/畸形 400×11） | AUTO ✅ |
| 6.3 | `/wait-state` 真实契约 → 常驻等待泡 + waiting 表情 | `{question_slots[], approval_slots[], fired_dedup_keys[]}`（P0-1 修复后两端契约一致）；槽位存在 → 常驻泡（ttl=0）+ `?` 徽章；轮询失败 → 视为无等待不崩溃 | AUTO：`main-wiring.test.mjs` 'wait-state poll: slots → sticky waiting + waiting mood'、'wait-state failure (WP-2 not deployed) → treated as no waiting, no crash'；`whale-state.test.mjs`（waiting 状态） | AUTO ✅ |
| 6.4 | 回答后解除收泡 | close 事件 → 槽位消除 → 通知 dismiss → 泡泡收起 | AUTO：`test_wait_state.py` + `controller.test.mjs`（waiting 同步） | AUTO ✅ |
| 6.5 | 真机端到端 | 真实网关中 clarify 工具生命周期事件触发等待泡出现/收起 | 人工：让 agent 触发一次 clarify | NOT VERIFIED（clarify 生命周期事件端到端从未实测——实施计划 M8 已标注的真机冒烟项） |

## 流程 7：触发审批 → 审批等待 → 批准后消失（approval hook）

| # | 环节 | 预期结果 | 验证方式 | 状态 |
|---|---|---|---|---|
| 7.1 | agent 半体 hook 写状态文件 | `pre_approval_request` → `approval-state.json` 原子写（仅 `{id,kind,tool,since}`，无 command/description/pattern）；`post_approval_response` → 精确 id 移除 + 会话前缀兜底 | AUTO：`test_wait_state.py`（hook 直调、隐私断言、配对、多会话、吞异常） | AUTO ✅ |
| 7.2 | `/wait-state` 合并 approval 槽位 → 常驻等待泡 | 槽位存在 → `syncWaiting({approval:true})`；仅 `surface=='gateway'` 观测 | AUTO：`main-wiring.test.mjs`（approval 槽位映射）、`test_wait_state.py`（approval_slots 合并） | AUTO ✅ |
| 7.3 | 批准后消失 | post hook 移除 → 轮询收泡 + `wait:approval:<id>` dismiss | AUTO：`test_wait_state.py`（前向后向配对/兜底清槽） | AUTO ✅ |
| 7.4 | 真机端到端 | 真实审批流（gateway 面）触发 → 等待泡出现 → 批准收泡；`session_key` 与 gateway 会话对应关系核对 | 人工：执行一次需审批的工具调用 | NOT VERIFIED（hook kwargs `surface` 取值已源码核实，端到端未跑） |

## 流程 8：音效开启 → 按压/松开/任务完成发声（无素材时无声）

| # | 环节 | 预期结果 | 验证方式 | 状态 |
|---|---|---|---|---|
| 8.1 | 接线与开关门控（P1-1 修复） | `config.sound.enabled`（默认 **false**）开启时才构建引擎；`muted` 即时静音；`volume_global` 0–100 | AUTO：`controller.test.mjs`（sound sink 挂接与门控）、`sound-engine.test.mjs` 27 条（mute/音量三态/开关关零副作用） | AUTO ✅ |
| 8.2 | 按压/松开发声（−40ms 衔接排期） | `controller.press()/release()` → sink `press()/release()`；短按无缝衔接 | AUTO：`controller.test.mjs`（press/release sink 调用）、`sound-engine.test.mjs`（排期计算） | AUTO ✅（发声逻辑）；真实发声 NOT VERIFIED |
| 8.3 | 任务完成/等待出现发声 | `TASK_COMPLETED` → `task_finished`；等待首次出现 → `question`/`approval`（去重，只响一次） | AUTO：`controller.test.mjs` 'TASK_COMPLETED plays task_finished through the sound sink'、'syncWaiting first appearance plays question/approval sound once' | AUTO ✅ |
| 8.4 | 无素材时无声（当前默认态） | 不发货默认音效素材（M10 自产前）→ 无 clip 天然无声，不报错 | AUTO：`sound-engine.test.mjs`（缺 clip 路径）；人工确认默认安静 | AUTO ✅（逻辑） |
| 8.5 | 真实音频端到端 | Electron 渲染进程 AudioContext 解锁、非手势 `task_finished` 发声、最小化恢复无爆音 | 人工：开启 `sound.enabled` + 提供素材 → 实听 | NOT VERIFIED（自动播放策略为实施计划 M9 已标注的未验证项；且默认无素材） |

## 流程 9：断网 / 后端不可达 → 芯片「○」+ 浮窗降级「未记账」快照

| # | 环节 | 预期结果 | 验证方式 | 状态 |
|---|---|---|---|---|
| 9.1 | 芯片连通性四态 | `●` ok / `◐` 账本降级 / `○` 后端不可达 / `◌` 探测中；dashboard 挂 → 死信 + 「记账暂不可用」 | AUTO：`register.test.mjs`（chip 贡献 + 健康探测渲染、'M1 degraded surface: dashboard down → dead letter + 记账暂不可用 on the chip'） | AUTO ✅ |
| 9.2 | 浮窗降级快照 | Python 半体不可达 → `host.state.focusedUsage` 救济快照，带**「未记账」**角标（display-grade，不进账本）；无快照 → 不造数 | AUTO：`balance-view.test.mjs` 'salvageView renders a token-only snapshot, marked 未记账'、'null/empty focusedUsage → null' | AUTO ✅ |
| 9.3 | 断连 → 重连对齐 | 网关重连期间暂停转发，恢复后首条 complete 打 `after_reconnect`（不重复结算） | AUTO：`ingest-client.test.mjs`、`normalize.test.mjs`、`test_ledger_accounting.py`（对齐不结算） | AUTO ✅ |
| 9.4 | 真机端到端 | 停 serve / 断网 → 芯片变 `○`、浮窗转「未记账」快照；恢复后自动回到 ok | 人工：真机断网观察 | NOT VERIFIED（需部署） |

## 流程 10：关闭 Hermes → 无孤儿进程

| # | 环节 | 预期结果 | 验证方式 | 状态 |
|---|---|---|---|---|
| 10.1 | 架构保证（Phase 1 无子进程） | JS 半体在渲染进程、Python 半体在 serve 进程内，插件**不拉起任何独立进程**（独立透明窗属 P2，未实现）→ App 退出即全部随宿主消失 | 设计事实（`docs/design/ARCHITECTURE_DECISION.md` §5 生命周期矩阵），无需运行时清理 | AUTO ✅（by design） |
| 10.2 | 插件内定时器/订阅清理 | dispose 停健康探测（60s）、UI 轮询（10s：wait-state + notifications + tick）与数据服务 | AUTO：`main-wiring.test.mjs` 'lifecycle: dispose stops health poll, UI poll and the data service' | AUTO ✅ |
| 10.3 | 真机进程级确认 | 关闭 App 后任务管理器无 whale-widget 相关进程、无遗留 python 子进程、`whale.db` 无异常锁 | 人工：关闭 App → 任务管理器检查 | NOT VERIFIED（需部署；进程级检查无法离线自动化） |

---

## 汇总

| 流程 | 自动化覆盖 | 待真机人工验证 |
|---|---|---|
| 1 首次启用/「—」语义 | ✅ | ⏳ |
| 2 凭据→余额轮询 ok | ✅ | ⏳（真实 DeepSeek API） |
| 3 turn 结算→消费泡泡→今日消费 | ✅ | ⏳（真实事件 payload） |
| 4 余额预警→常驻→回升消失 | ✅ | ⏳ |
| 5 预算泡泡 | ✅ | ⏳ |
| 6 clarify 等待泡 | ✅ | ⏳（clarify 端到端未实测） |
| 7 审批等待泡 | ✅ | ⏳（真实审批流） |
| 8 音效 | ✅（引擎/接线/去重） | ⏳（真实发声 + 无素材静音确认） |
| 9 断网降级 | ✅ | ⏳ |
| 10 无孤儿进程 | ✅（架构保证 + dispose） | ⏳（任务管理器确认） |

**结论**：10/10 条流程的链路核心环节已有自动化测试覆盖（node 190 + pytest 184 全绿）；
10/10 条的端到端真机验证待用户手动部署到 `D:\hermes\plugins\whale-widget\` 后执行
（NOT VERIFIED 原因统一为：AGENTS.md §0 只读约束，agent 禁止代写部署）。真机执行时请按
[`../../INSTALL.md`](../../INSTALL.md) §4–§6 部署启用，逐条勾验并把结果回写
`docs/progress/WORKLOG.md`。
