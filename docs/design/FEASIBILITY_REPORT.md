# FEASIBILITY_REPORT — Hermes Whale Widget 可行性报告

> 日期：2026-10-03。依据：三份调研文档（`DEEPSEEK_WHALE_ANALYSIS.md`、`HERMES_ARCHITECTURE_AUDIT.md`、`REFERENCE_PROJECTS.md`）+ 对 `D:\hermes\hermes-agent`（commit `0ff4c748`，v0.21.5+369）的只读抽查复核。
> **硬约束**：本项目禁止修改 Hermes Core（工作区外只读）。凡「干净实现需 Core 扩展」的能力，一律给降级路径而非 patch 假设。
> 配套文档：`docs/design/FEATURE_MATRIX.md`（A–E 分级矩阵）。

---

## 1. 功能级结论表

判定含义：**YES** = 本项目约束内可实现（含 C 级桥，注明条件）；**PARTIAL** = 部分可实现/需降级；**NO** = 不可实现；**UNVERIFIED** = 证据不足以判定。

| 功能 | 结论 | 证据 |
|---|---|---|
| Usage accounting（usage ledger / 单轮消费 / 今日消费 / 7 日历史） | **YES** | 实时面：`ctx.onEvent('message.complete')` 携带权威 usage 终值（`gateway-contract.generated.ts:4555-4571`）+ `session.usage` 1s 心跳（审计 §5.1）。历史面：state.db `session_model_usage`（复合 PK 幂等账本，`hermes_state_common.py:481`，本机实证 174 行）+ `sessions`（`:381`）经 Python 半体 `mode=ro` 聚合（参考 §6.1 正解）。审计 §5.3 同结论 |
| DeepSeek / Provider 余额 | **YES**（条件：统一包 Python 半体启用） | 桌面插件无凭据 API，但 `plugin_api.py` 可经 `agent.secret_scope.get_secret`（profile 作用域，`hermes_cli/config.py:1583-1594`）解析 key 直调 provider REST；ai-usage-tracker 同型范式已验证（其 `plugin_api.py:268-276` `_runtime_key`，"Secrets are resolved in-process and never serialized"） |
| Transparent whale（OS 级透明窗口） | **YES**（Windows，C 级独立进程）/ **UNVERIFIED**（macOS/Linux） | 插件层无窗口 API（见 §2-①）；hermes-pet 已在 Windows 验证 pywebview frameless+transparent+on_top 全套补丁（`pet_window.py:139-160, 438-450, 46-51`，参考 §2.1）；macOS 透明路径与素材双格式未验证 |
| Transparent whale（app 内浮卡形态） | **YES** | pane `placement:'floating'`：非 tiling、固定定位、可拖拽、不占布局宽度的浮卡（`sdk/index.ts:1794-1799`，已抽查） |
| 置顶（always on top） | **YES**（独立进程路线）/ 内嵌仅 app 内常驻 | pywebview `on_top` + `WS_EX_TOOLWINDOW`（hermes-pet 已验证）；内嵌形态受 app 窗口约束 |
| Bubble（泡泡） | **YES** | 纯前端 DOM/Canvas，DSH 渲染引擎与优先队列逻辑可整体照抄（DSH 分析 §C2/D3）；宿主面 floating pane + `host.notify` toast 兜底 |
| Bubble editor（泡泡编辑器） | **YES**（工作量大） | ROUTES_AREA 设置页 + SDK 基础件（`sdk/index.ts:1801-1874`）；DSH 编辑器约 5700 行、建议四阶段切分（DSH 分析 §C4） |
| Task finished event | **YES** | `message.complete` 事件即 turn 结束边沿（status: complete/error/interrupted）；`host.state.busy`（`sdk/index.ts:680`）下降沿兜底；无需 DSH 式秒轮询 |
| Approval event | **PARTIAL** | **无 approval asked 网关事件**：approval 是 Server→Client JSON-RPC（`ServerRequestMap`，`gateway-contract.generated.ts:5641`），事件流仅有 `approval.cancelled`（`:5689`）。可靠观测走 agent 半体 hook `pre_approval_request`/`post_approval_response`（`hermes_cli/plugins.py:143-148`，触发点 `tools/approval.py:914` 等，已抽查）→ 状态文件 → REST 轮询（C 级）；无 agent 半体时只剩 busy 停滞启发式（可靠性有限）。**不能代答**（hook 明示 returns ignored；SDK 无 respond 面） |
| Question event | **YES**（源码核实；端到端未实测） | **修正调研文档的悲观结论**：clarify 本体虽是 JSON-RPC（`gateway-contract.generated.ts:5643`），但 clarify 是工具且属 `_TOOL_LIFECYCLE_UI_TOOLS`（`tui_gateway/server.py:2141-2157`），其 `tool.start`/`tool.complete` 生命周期事件**无视 tool_progress 设置必发**（门控短路 `tool_progress.py:291`）→ 插件 `ctx.onEvent('tool.start')` name==='clarify' 即可观测，payload.args 含问题文本。仅不能代答 |
| 音效 / 自定义音效 | **YES** | Web Audio 全套为 renderer 标准 API（DSH 引擎照抄，DSH 分析 §E1）；自定义音频经 File API 拖拽导入 + IndexedDB 存储；`ctx.os.pickOpenPath` 备选（`contrib/plugin.ts:59-65`） |
| 自定义角色 / 图片库 | **YES** | IndexedDB + 对象 URL；透明命中测试照抄 DSH；素材须自产（DSH 分析 §G：DSH 素材不在 MIT 内，不可再分发） |
| API Key（密钥管理） | **PARTIAL** | 读取：YES——Python 半体 profile 作用域 `get_secret` 只读解析，密钥永不过桥。写入/管理 UI：**NO**——桌面插件无凭据写 API（审计 §8），写 config.yaml 属 hack 不做；降级为「Hermes 原生侧配置（.env/config/secret sources）+ 插件只读显示指纹」。`ctx.storage` 明文严禁存 key（`contrib/plugin.ts:143-163`） |
| 自定义 HTTP Provider | **YES** | plugin_api.py 模板注册表 + httpx 为纯 Python（ai-usage-tracker 探针表范式，参考 §1.3）；凭据目的地白名单/URL 校验逻辑从 DSH 移植（DSH 分析 §F2） |
| Quota | **YES** | ai-usage-tracker 已验证：探针注册表 + 复用内置 `agent.account_usage.fetch_account_usage`（其 `plugin_api.py:315-321`）；无 quota API 的 provider 显式 unavailable |
| Pricing | **YES** | core 原生计价：`UsageStats.cost_usd`（`types/hermes.ts:869`）+ state.db `estimated_cost_usd/actual_cost_usd` + `pricing_version`；注意 `subscription_included` 行 cost=0（`cost_status='included'`）的 None/0 语义差（参考 §附）；自定义单价覆盖为插件侧显示层兜底 |
| 拖拽 / 吸附 / 点击 | **YES** | floating pane（`sdk/index.ts:1794-1799`）+ 标准 pointer 事件；DSH 算法照抄 |
| 角色动画 | **YES** | avatar_pet 已验证 Canvas 精灵图范式（参考 §3.3）；`createBudgetedLoop` rAF 预算（`sdk/index.ts:1930`） |
| 余额提醒 / 预算提醒 | **YES** | 数据源（余额/账本）为 C 级桥 + JS 阈值逻辑；阈值去重语义照抄 DSH（DSH 分析 §D1） |
| 设置页面 | **YES** | ROUTES_AREA + SIDEBAR_NAV_AREA + STATUSBAR chip（ai-usage-tracker 已验证组合，参考 §1.3） |
| 数据持久化 | **YES** | `ctx.storage`（官方，`contrib/plugin.ts:143-163`）+ IndexedDB（媒体）+ 插件数据目录（Python 半体写账本，原子写/退避照抄 DSH） |
| 随 Hermes 启动 | **YES** | runtime-loader 启动扫描自动加载（审计 §1.1）；OS 开机自启属 App 层设置（`main.ts` 无 `setLoginItemSettings`，未验证、非插件职责） |
| Hermes 退出后挂件退出 | **YES** | 内嵌形态随渲染进程消失（天然）；独立进程靠文件心跳自退（hermes-pet 已验证，参考 §2.2）。注意 App 退出不执行插件 disposer（审计 §10） |
| 多 profile | **YES** | `host.profiles/profileRoutes/requestProfile/listPersistedSessions`（审计 §2.1）+ ContextVar 换 HERMES_HOME（ai-usage-tracker `plugin_api.py:95-113`） |
| 多 session | **YES** | `host.state.busyBySession`（`sdk/index.ts:682`）+ 事件 envelope.session_id（审计 §4） |
| 远程 Hermes | **UNVERIFIED**（内嵌）/ **NO**（独立窗口） | OAuth remote 上 `ctx.socket` no-op、必须轮询 fallback（`api/plugins.ts:89-94` 已抽查）；`ctx.rest` 远端支持未验证；Python 半体与 spawn 都在远端主机 → 独立窗口会开在远端机器上，形态性不可用 |
| Windows | **YES** | Electron 渲染层平台无关（本机 ai-usage-tracker 实证）；独立窗口 Windows 补丁已验证（hermes-pet） |
| macOS | **YES**（内嵌）/ **UNVERIFIED**（独立透明窗口） | 渲染层平台无关；透明窗口/pywebview macOS 路径未验证；透明视频需 HEVC 替代 webm alpha（参考 §5.2） |
| Linux | **YES**（内嵌）/ **UNVERIFIED**（独立窗口） | 同上 |

**关键修正说明（相对任务方示例结论）**：示例中「Approval event PARTIAL、Question event PARTIAL」经源码核实应区分——**Question 升为 YES**（clarify 工具生命周期事件必发，`server.py:2141`）；**Approval 维持 PARTIAL**（asked 无事件，可靠观测需 agent 半体 hook 桥）。「macOS transparency UNVERIFIED」维持。

---

## 2. 缺失能力清单（Hermes 当前限制，以及为什么插件无法解决）

### ① 插件不能开独立 / 透明 / 置顶窗口
- `window.open`/`target=_blank` 在 main 进程**全量 deny**（`window-open-policy.ts:74-93`：无条件 `return { action: 'deny' }`，GHSA-9f4c-93c8-jc8g/CVE-2026-70608 姿态，已抽查）；preload 无 `createWindow`/`openWindow` IPC；透明窗口（HUD、pet overlay、quick entry、wake indicator）与玻璃态均为核心专用（`electron/main.ts:1506-1509`，已抽查）。
- **为什么插件无法解决**：渲染进程内没有任何建窗通道；这是安全姿态（防沙箱 iframe 外带）刻意收紧的，插件层绕过等于绕过 CVE 缓解。
- 插件层的极限 = app 内 floating pane（受 app 窗口边界约束，最小化即不可见）。

### ② JS 侧无子进程能力
- `preload.ts` 无任何 spawn/exec/child_process 通道（grep 复核确认，审计 §9.2）。
- **为什么插件无法解决**：独立窗口进程（pywebview/Electron overlay）只能由 **Python 半体 spawn**（hermes-pet 模式：固定 argv + `DETACHED_PROCESS` + 握手文件，参考 §2.2）。JS→进程的链路必须经 `ctx.rest` → plugin_api.py 两级桥。

### ③ 桌面插件无凭据 API，`ctx.storage` 明文
- `ctx.storage` 是明文 localStorage（键 `hermes.plugin.<id>.`，`contrib/plugin.ts:143-163` 已抽查）；`ctx.os` 六件事里无 keychain；Electron safeStorage 不对渲染层开放（审计 §8）。
- **为什么插件无法解决**：凭据门是产品级安全边界（远程会话/恶意页面读 localStorage 即可外带 key）。密钥只能留在 Python 半体（`get_secret`，profile 作用域，启动时从 Hermes 原生源解析，只回传非敏感结果）。

### ④ `ctx.rest` 被硬限制在插件命名空间
- `pluginPathSuffix` 拒绝 `..` 穿越，注释明示「today the namespace IS the boundary」（`api/plugins.ts:56-71`，已抽查）——`/api/analytics/*`、`/api/profiles/*` 等核心 REST 不可达。
- **为什么插件无法解决**：这是防插件越权访问核心路由/其他插件 API 的构造性边界。核心聚合统计只能经 `host.request`（JSON-RPC 面）或 **Python 半体 ro 读 state.db**（ai-usage-tracker 范式）。注意 RPC `usage.bars` 是 **Nous 账户口径**（`agent/billing_usage.py:169-180` 走 portal fetch），不能替代本地会话历史——这是本次抽查新确认的坑。

### ⑤ approval / clarify 不能代答（观测与代答要分开评）
- `ServerRequestMap`（approval/clarify/secret/sudo/…）由 app 内置 UI 处理；SDK 未暴露任何 respond 面（`gateway-contract.generated.ts:5639-5666`，已抽查）。
- agent 半体的 approval hook 明示 **observer-only**（「returns ignored — plugins cannot veto or pre-answer」，`hermes_cli/plugins.py:144`）。
- **评价**：对挂件而言「观测」够用、「代答」本来就不应该给插件（安全上正确）。这不是可绕的缺陷，是设计意图。

### ⑥ App 退出不执行插件 disposer
- 无 before-quit 插件清理钩子；退出序列只处理 Electron 自身事务（审计 §10）。
- **为什么插件无法解决**：渲染进程随 app 消失，来不及清理。独立子进程必须自管生命周期（文件心跳 + 超时自退，hermes-pet 已验证的「自决式防孤儿」）。

### ⑦ `ctx.os.notify` 门控
- 系统级原生通知**仅用户离开 Hermes 时**触发 + Settings 门控 + 按插件节流（`contrib/plugin.ts:46-52`，已抽查）。
- **影响**：用户正在看 Hermes 时，提醒只能走 app 内泡泡/toast（`host.notify`）。对桌宠形态反而是合理语义（人在看时就用泡泡）。

### ⑧ usage/cost 数据的两处坑
- Usage 载荷字段**增量出现**（cost_usd/context_* 可能缺省，`sdk/index.ts:347` 注释明示）→ 读取必须带 fallback。
- `subscription_included` 行 `estimated_cost_usd=0, cost_status='included'`；同 session 不同 `task` 行 `cost_status=None`（本机实证，参考 §附）→ 0 / None / included 三种语义必须区分，否则「今日消费」对订阅用户恒显 0 或虚报。

---

## 3. 最小 Core API 扩展建议（仅作 upstream 建议记录，本项目不实施）

| 建议 | 内容 | 为什么值得向 Hermes upstream 提 |
|---|---|---|
| ① 网关事件流补 `approval.requested`（或把既有 `pre_approval_request` hook 在 gateway surface 同步转发为一条事件） | 让**纯 desktop 插件**（无 agent 半体）也能实时观测审批等待，正如 clarify 已有工具生命周期事件一样 | ① 对称性：clarify 观测已是事件面一等公民，approval 却只有 cancelled；② 生态需求：dsh-pet/hermes-pet/DSH whale 全部把「等待用户授权」当核心提醒（DSH 分析 §D2）；③ 实现极小：gateway 在审批挂起处多发一条带 session_id 的只读事件即可，不新增任何能力面 |
| ② 官方 floating/overlay 窗口 API（插件作用域） | 受限 `BrowserWindow`：`transparent+alwaysOnTop+skipTaskbar` 预设、尺寸/位置白名单、无 Node 集成、固定 preload、来源锁定插件 id | ① 当前 deny-all 是 CVE 姿态下的正确保守选择，但桌宠/挂件生态（DSH whale 987⭐ 上游、hermes-pet、avatar_pet）证明需求真实；② 官方 API 能消除第三方「spawn pythonw + 自建 venv + 心跳防孤儿」的重依赖与故障面；③ 核心自己已有 4 种透明窗口（HUD/pet/quick entry/wake），抽象成插件面是顺势而非开新面 |
| ③ 桌面插件凭据门 | safeStorage 后端、插件作用域命名空间、write-only（写后不可读回明文）或转发到系统 keychain | 当前明文 `ctx.storage` 迫使一切涉密逻辑进 Python 半体，纯 UI 插件永远无法安全接 provider API；这是把「统一包部署 + 白名单 + 重启」门槛压到「纯桌面插件即可用」的关键 |
| ④ before-quit 插件 disposer | App 退出序列先跑各插件 `ctx.onDispose` 再 teardown | 附属进程/临时文件目前只能靠超时自退兜底（最长 60s 残留窗口）；已有 disposer 基建（unload/disable 已跑），只缺退出路径 |
| ⑤ 官方只读 usage 聚合面（可选） | 把 `/api/analytics/usage` 暴露为 SDK 方法或允许声明式只读 rest 能力 | state.db schema 是内部实现（`schema_version` 已到 31），第三方插件 ro 读是 schema 耦合；官方聚合面能让账本类插件摆脱版本演进风险 |

---

## 4. 替代方案（对每个缺失能力的降级路径）

| 缺失能力 | 降级路径 | 代价 / 可靠性 |
|---|---|---|
| 独立透明置顶窗口（①②） | **Phase 1（默认）**：app 内 floating pane（`placement:'floating'` + `anchor` + 宽高，`sdk/index.ts:1794-1799`）+ Canvas 精灵图（avatar_pet 渲染纪律）。**Phase 2（可选增强）**：Python 半体 spawn 独立 pywebview 进程——照搬 hermes-pet 骨架：`WS_EX_LAYERED`/`WS_EX_TOOLWINDOW` 补丁（`pet_window.py:139-160`）、`--disable-gpu`（`:46-51`）、原子握手文件 + 4s/60s 心跳自退（`:325-338, 465-488`）、127.0.0.1+token 两级 REST 桥 | Phase 1：零依赖零进程管理，但最小化不可见。Phase 2：真桌面常驻，代价 = pywebview venv 分发摩擦 + GPU 合成兼容 + 远程 Hermes 不可用 |
| approval 观测（⑤） | **首选**：agent 半体 `pre_approval_request`/`post_approval_response` hook → 写插件数据目录状态文件 → `plugin_api.py` GET 端点 → 桌面 1s 轮询（hook kwargs 带 `command/description/session_key/surface`，够构提醒文案）。**兜底**：`host.state.awaitingResponse`/`busyBySession` 停滞启发式（turn 进行中超过 N 秒无 tool/message 事件 → 疑似等待）+ `approval.cancelled` 事后确认 | 首选：可靠、事件语义完整，代价 = 统一包 agent 半体启用（与 Python 半体同一部署前提）。兜底：纯 desktop 可用但**可靠性有限**（长工具调用会误报），UI 上必须标「疑似等待」 |
| question 观测（⑤） | 首选：`ctx.onEvent('tool.start'/'tool.complete')` name==='clarify'（已核实必发）。兜底：同上 busy 停滞启发式 | 首选：A 级、实时。兜底仅在 Hermes 未来把 clarify 改出工具路径时启用 |
| 密钥管理（③） | 密钥经 Hermes 原生机制配置（profile `.env` / config / secret_sources）；`plugin_api.py` profile 作用域 `get_secret` 只读解析；JS 只见指纹（sha256 前 8 位）用于分账本与显示 | 失去「插件内一键配 key」体验；换来密钥永不过桥。写 config.yaml 的 hack 明确不做 |
| 核心统计 REST 不可达（④） | Python 半体 `sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)` 读 `sessions`/`session_model_usage`（范式照抄 ai-usage-tracker `plugin_api.py:199-221`）+ `schema_version` 兼容门 + 列存在性检查 + 缺列降级 + `ContextVar` 换 HERMES_HOME 支持 per-profile | schema 演进风险由兼容门兜住；数据量级 10² 行聚合无性能问题 |
| 退出清理（⑥） | 文件心跳自退：子进程 4s 读 `app-online.json`，60s 未刷新即自退；文件缺失/损坏视为在线（宁可多活不误杀）；退出统一 `PostMessage WM_CLOSE`（hermes-pet 已验证全套） | 最长 60s 残留窗口；跨 gateway/serve 实例并存安全 |
| 系统通知门控（⑦） | 用户在场：app 内泡泡（主通道）+ `host.notify` toast；用户离开：`ctx.os.notify` 原生通知自动接管 | 与 DSH「泡泡优先、卡片兜底」语义天然契合，无需额外工程 |
| usage/cost 缺省与语义（⑧） | 读值一律 fallback 链：`cost_usd` → 自备价目表折算（B 级）→ 显示「—」；聚合时 `cost_status='included'` 行按口径单独归类（订阅内不进现金消费），None 与 0 分开渲染 | 「取不到显示 — 而非 0」贯穿全 UI（DSH 语义） |
| 远程 Hermes | 首版明确不支持「远程 + 独立窗口」组合；内嵌形态保留轮询 fallback（`ctx.socket` OAuth remote no-op）并实测后给结论 | 功能边界写进 README，不静默降级 |

---

## 5. 总体结论

**PARTIAL（趋近 FULL）：在「不改 Core、Windows 优先」约束下，Phase 1 内嵌形态的功能全集——实时记账/账本/7 日历史/泡泡/泡泡编辑器/角色动画/音效/自定义资产/全部提醒/设置/多 profile/多 session/数据持久化——在 A/B/C 三级内全部可实现且无需修改 Hermes Core（其中 Question 提醒经源码核实为 A 级事件面、Approval 提醒为 C 级 agent 半体 hook 桥）；Windows 的 OS 级透明置顶鲸鱼经 C 级独立进程桥可行（hermes-pet 已验证）；明确降级项仅三处：Approval 无 asked 事件只能观测不能代答、完整密钥管理 UI 降级为 Hermes 侧配置 + 插件只读、远程 Hermes 的独立窗口形态不可用（内嵌待实测）；D 级为 0。**
