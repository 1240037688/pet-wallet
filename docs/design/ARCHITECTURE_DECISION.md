# hermes-whale-widget 架构决策（ARCHITECTURE_DECISION）

> 版本 v1.0（2026-10-03）。上游输入：
> - `docs/research/DEEPSEEK_WHALE_ANALYSIS.md`（下称 **[DSH]**）
> - `docs/research/HERMES_ARCHITECTURE_AUDIT.md`（下称 **[AUDIT]**）
> - `docs/research/REFERENCE_PROJECTS.md`（下称 **[REF]**）
> - `D:\hermes\hermes-agent` 源码只读抽查（commit `0ff4c748`，[AUDIT] §0；本文 file:line 未加前缀者均指该仓库，已抽查核实）
>
> 数据侧细节见配套 `docs/design/DATA_MODEL.md`（下称 **[DM]**）。本文遵守 AGENTS.md 全部红线；未验证处显式标注。

---

## 1. 背景与硬约束

**产品目标**：Hermes 桌面鲸鱼记账挂件——常驻鲸鱼形象 + 泡泡系统（余额/今日已用/每轮消耗/提醒）+ 完整记账（usage 估算账 + 余额观测账 + 显式校正闭环）+ 设置界面。

**硬约束**（用户/AGENTS.md §0、§7-§9）：

| # | 约束 | 架构影响 |
|---|---|---|
| C1 | **禁止修改 Hermes Core**（含 `D:\hermes` 一切） | 只能建立在插件机制上；排除一切 core patch 路线 |
| C2 | 凭据安全：JS/UI 只见凭据 id/name，密钥永不进渲染层、localStorage、日志 | 密钥解析必须发生在 Python 半体 |
| C3 | 记账正确性：幂等、五类金额分离、余额 API 失败 ≠ 0 | 需要可靠持久层（localStorage 不够） |
| C4 | 生命周期：退出无孤儿进程；disable/reload/gateway restart 可恢复 | 需要明确的进程所有权与自退机制 |
| C5 | 最小可用，不过度工程化 | 每个组件都要有存在理由（§11） |

**Hermes 插件机制的两个关键事实**（[AUDIT]）：
- 桌面插件（`desktop/plugin.js`）在渲染进程求值，有完整 SDK（事件订阅 `host.onEvent`、状态 `host.state`、REST/WS 桥 `ctx.rest`/`ctx.socket`），但**无凭据 API、无文件、无子进程、无独立窗口**（[AUDIT] §2.3、§8、§9.2）。
- Dashboard 插件（`dashboard/plugin_api.py`）作为 FastAPI router 挂载进**每个 profile 的 `hermes serve` 进程**（`_mount_plugin_api_routes`，`hermes_cli/web_server_dashboard.py:805-905`，include 于 :869-875），能读凭据（`get_secret`，`hermes_cli/config.py:1583-1594`）、能出网（httpx）、能持文件——受 `plugins.enabled` 白名单信任门约束（:775-802）。

---

## 2. 候选路线比较与选择

### 2.1 四条路线定义

| 路线 | 内容 |
|---|---|
| **A 纯 desktop plugin** | 单 `desktop/plugin.js`：UI + 记账 + 余额轮询全在渲染进程，数据存 `ctx.storage`（localStorage） |
| **B Unified Package（基座）** | `desktop/plugin.js`（UI/事件转发）+ `dashboard/plugin_api.py`（账本/provider HTTP/凭据/SQLite），挂载 `/api/plugins/whale-widget/` |
| **C = B + 独立透明鲸鱼窗** | B 之上，Python 半体 spawn 独立 pywebview 透明置顶进程（hermes-pet 骨架），Phase 2 可选开关 |
| **D 改 Hermes Core** | 在 core 中为插件开放透明窗口/凭据/事件新 API，鲸鱼成为 core 特性或深度依赖 core patch |

### 2.2 打分对比表（按本项目约束加权；5=完全满足，0=违反）

| 维度 | A | B | C | D | 依据 |
|---|---|---|---|---|---|
| C2 凭据安全（硬约束） | **1**：`ctx.storage` 明文 localStorage，桌面插件无凭据 API，key 进渲染层即违规 | **5**：`get_secret`/env 在 Python 半体解析，线上只出指纹/标签 | 5（同 B；独立窗经桥取数，不持密钥） | 5 | [AUDIT] §8 表格、`contrib/plugin.ts:143-163` |
| C3 记账持久化（红线） | **1**：localStorage 易失、无事务、无并发读 | **5**：SQLite WAL 单写者 | 5（同 B） | 5 | [AUDIT] §2.3；[DM] §7 |
| 余额 API 可达性 | **2**：渲染进程直连厂商 API → CORS 不可控 + 密钥必须在 JS | **5**：httpx 服务端出网 + 出站白名单 | 5（同 B） | 5 | [DSH] F2 `credentialMayGoTo`/`assertSafeApiUrl` 思路 |
| C1 禁改 Core（硬约束） | 5 | 5 | 5 | **0——直接出局** | AGENTS.md §0 |
| 实时事件可达 | 5：`host.onEvent` 直连 | 5：同 A 事件面 + Python 落库 | 5（独立窗消费桥数据） | 5 | [AUDIT] §2.1 `host.onEvent:1466` |
| 热加载 / 运维 | 5：纯热载 | **3**：JS 热载；dashboard 启用需重启 App 一次 | 3 + 独立窗进程管理复杂度 | — | [REF] §1.1「启用后需重启桌面 App」；[AUDIT] §6.1 |
| 分发/启用摩擦 | 5：复制目录即用 | **4**：unified 包 + `plugins.enabled` 白名单 + 一次重启 | **2**：另需 pywebview venv 依赖链 | — | [AUDIT] §6.1、§7.3；[REF] §2.4 ④ |
| 窗口形态上限 | **2**：仅 app 内（floating pane） | 3：floating pane；OS 级窗口被 deny（`window-open-policy.ts:1-30`） | **5**：OS 级透明置顶常驻 | 5：core 自有 HUD/pet 透明窗（`electron/main.ts:1506-1509`）但不许碰 | [AUDIT] §9.2 |
| **合计** | 26 | **35** | 35 | — | |

### 2.3 决策

- **选择 B 为基座**：两条硬约束（凭据、持久化）上 A 直接不及格；B 与 C 同分，但 C 的额外得分全部来自「OS 级窗口形态」这一 Phase 2 诉求，其代价（分发摩擦、进程管理、Windows GPU/透明补丁风险）在 Phase 1 不必付。**B 先行，C 作为 B 的纯增量开关**——C 不改变任何 B 的数据流，只多一个消费者（独立窗从 Python 半体拉渲染数据），随时可加可拆。
- **排除 D**：违反用户硬约束 C1（AGENTS.md §0 最高约束）；且现有插件机制覆盖度已被审计证实足够（事件面 [AUDIT] §4、桥 [AUDIT] §6、凭据经 Python 半体 [AUDIT] §8）。core 的透明窗/凭据/子进程能力对插件关闭是**有意的安全姿态**（GHSA 修复史，[AUDIT] §1.5、§9.2），靠改 core 换便利会把升级维护成本转嫁给用户。
- **A 的 salvage**：A 的 UI 形态（状态栏芯片/路由页）保留为 B 内的低配降级面（Python 半体不可用时鲸鱼仍能显示 `host.state.focusedUsage` 实时数，只是不记账）。

---

## 3. 总体数据流

```
                         Hermes Desktop App（Electron）
┌───────────────────────────────────────────────────────────────────────────────┐
│  渲染进程（React）                          Electron main 进程                  │
│  ┌────────────────────────────────┐        ┌────────────────────────────────┐ │
│  │ desktop/plugin.js（JS 半体）     │        │ REST/WS 代理（持会话 token，    │ │
│  │  WhalePane（floating pane 内）  │        │ 渲染进程不接触原始凭据）         │ │
│  │   ├ WhaleState（状态机/动画）    │        └───────────────┬────────────────┘ │
│  │   ├ BubbleRenderer（泡泡）       │                        │ IPC hermes:api   │
│  │   ├ EventNormalizer（归一化层）  │                        ▼                  │
│  │   └ IngestClient（转发/重试）    │        ┌──────────────────────────────────┐
│  └────┬─────────────────┬──────────┘        │ hermes serve 进程（每 profile）   │
│       │                 │                   │  ┌────────────────────────────┐ │
│  host.onEvent      ctx.rest / socket ──────►│  │ dashboard/plugin_api.py    │ │
│  (session.usage    (/api/plugins/           │  │  (Python 半体，进程内)      │ │
│   message.complete  whale-widget/*)         │  │   ├ IngestAPI（幂等去重）   │ │
│   gateway.* 等)                             │  │   ├ AccountingCore         │ │
│       │                                     │  │   │   ├ 轨① UsageLedger   │ │
│       ▼                                     │  │   │   ├ 轨② BalanceLedger │ │
│  host.state.focusedUsage / busy /           │  │   │   ├ Rules（预算/预警） │ │
│  busyBySession / model / profile            │  │   │   └ SQLite whale.db   │ │
│  （仅 UI 实时显示，不落库）                    │  │   ├ ProviderGateway(凭据内)│ │
│                                             │  │   └ (P2) WhaleWindowSupervisor
│                                             │  └────────────────────────────┘ │
│                                             │   tui_gateway(WS) + FastAPI     │
└─────────────────────────────────────────────┴─────────────────────────────────┘
        │                                            │                    │
        ▼                                            ▼                    ▼
  泡泡/鲸鱼动画（渲染进程内）              Provider balance/quota API      state.db（只读，轨③
                                          （密钥只在 Python 半体内）        可选交叉校验，schema_version 门）

Phase 2 增量：WhaleWindowSupervisor ──spawn──► 独立 pywebview 透明鲸鱼进程
              （固定 argv / 握手文件 / app-online.json 心跳 / 60s 超时自退 / 两级 REST 桥）
```

**管线视角**（泡泡引擎解耦，已定方向）：

```
Bubble Definition（Row/Module schema，[DSH] C2）
      → Resolver（balance / today / cost / session / random 模块；choice 加权随机 + avoidIdx 防连续重复；图片独占行）
      → Render Model（纯数据：行×模块×样式×数值，取不到= null）
      → Renderer（floating pane 内泡泡 | 居中卡片降级 | P2 独立窗同模型渲染）
```

Resolver 只读 Render Model 所需快照（WhaleState/REST 缓存），**渲染器与数据源互不感知**——这是把 DSH 约 5700 行泡泡编辑器可控分阶段的前提（[DSH] C4）。

---

## 4. 事件流表（Hermes 信号 → 归一化鲸鱼事件 → 行为）

归一化鲸鱼事件集：`TURN_STARTED / TURN_FINISHED / USAGE_UPDATED / TASK_COMPLETED / USER_INPUT_REQUIRED / APPROVAL_REQUIRED / BALANCE_LOW / BUDGET_REACHED / ERROR`。上层（WhaleState、Rules、泡泡）只依赖归一化事件（已定方向）。

| Hermes 信号 | 来源（SDK 面） | 归一化事件 | 触发行为 | 落库 |
|---|---|---|---|---|
| `message.start` | `ctx.onEvent`（`gateway-contract.generated.ts:5733` 邻域，[AUDIT] §4.1） | `TURN_STARTED` | thinking 状态/动画、turn 计时开始 | 否 |
| `message.delta` | `ctx.onEvent` | （内部 `STREAM_TICK`） | 流式动画；**刻意不因每个 delta 重置动画**（avatar_pet 防抖纪律，[REF] §3.3） | 否 |
| `session.usage`（turn 中 1s 心跳） | `ctx.onEvent`（`server.py:3451-3475` ticker；event 定义 :5790-5791 已抽查） | `USAGE_UPDATED`（provisional） | 泡泡/芯片实时数字；**心跳永不落库**（AGENTS.md §8） | 否 |
| `message.complete`（status=complete） | `ctx.onEvent`（payload :4555-4571 已抽查；usage 权威终值 `server.py:2393`） | `TURN_FINISHED{ok}` + `USAGE_UPDATED{final}` + `TASK_COMPLETED` | IngestClient POST `/ingest/turn`（幂等去重落库，[DM] §3）→ 每轮消耗泡泡 + 任务结束音 → 预算/余额规则复评 | **是**（唯一落库入口） |
| `message.complete`（status=error/interrupted） | 同上（`TurnStatus`） | `TURN_FINISHED{status}` + `ERROR`（如有 error 字段） | 有 usage 则 provisional 结算（[DM] §2.4）；错误表情 | 是（provisional） |
| `error` | `ctx.onEvent` | `ERROR` | 表情/通知 | 否 |
| `tool.start / tool.complete / tool.generating` | `ctx.onEvent` | （内部 `TOOL_ACTIVITY`） | 工作动画（avatar_pet 启发式词表作初始参考，[REF] §3.3） | 否 |
| 审批/提问 | **不是事件**——是服务端→客户端 JSON-RPC 请求（`ServerRequestMap` :5639-5666），插件**不能**代答、无直接订阅面（[AUDIT] §4.2）；仅 `approval.cancelled` 事件可见（:5689） | `APPROVAL_REQUIRED` / `USER_INPUT_REQUIRED` | **启发式**：单槽位 pending 状态机（参考 DSH `notePendingEvent` 思路，[DSH] D2）——turn busy 但流静默（无 delta/usage tick）超阈值 → 进入 pending；`message.complete` / `approval.cancelled` / turn 结束 → 清除。**未验证**：busy 停流启发式在 Hermes 的可靠性，Phase 1 作为实验开关默认关，靠 `approval.cancelled` 与 `notification.show`（:5747）等间接信号补 | 否（pending 状态内存+meta） |
| `gateway.reconnecting` / `host.state.gateway` | 合成事件（`gateway-events.ts:23-29`）/ 状态 atom（:708） | （内部 `CONNECTION_CHANGED`） | 停转发 → 重连后首条 complete 只对齐 watermark（[DM] §3.4） | 否 |
| 余额刷新（Python 半体 60s 轮询） | ProviderGateway | `BALANCE_LOW`（规则触发） | balance ≤ 阈值且 >0 → 系统泡泡（rank 2）+ 可选 `ctx.os.notify`（仅用户离开 App 时，[AUDIT] §9.1） | 是（snapshot + notification） |
| 今日预算复评（turn 结算后） | Rules | `BUDGET_REACHED` | today_usage ≥ budget（口径按 `budget.basis`，币种校验宁不比较）→ rank 1 泡泡 | 是（notification） |
| 等待解除 | 上述清除信号 | （pending 清除） | 常驻等待泡收起；声音去重键持久化（[DM] §2.10） | notification 表 |

**通知投递**：Python 半体产生的 `BALANCE_LOW/BUDGET_REACHED` 经 `ctx.socket`（`/api/plugins/whale-widget/` WS）推送 JS；**必须保留轮询 fallback**（OAuth 远程后端上 `ctx.socket` 不可用，[AUDIT] §6.3/§12）——轮询 3s（可调），单实例。

---

## 5. 进程模型

| 进程/半体 | 宿主 | 职责 | 拉起者 | 清理者 |
|---|---|---|---|---|
| JS 半体（desktop/plugin.js） | Electron **渲染进程**（runtime-loader 加载，`runtime-loader.ts:380-544`；统一包半体由 Electron 从 `plugins/<id>/desktop/` 物化到 `desktop-plugins/<id>/`，`desktop-plugins-root.ts:163-246`） | UI、事件订阅与转发、泡泡渲染 | Hermes 加载管线（保存即热重载，[AUDIT] §1.1） | 插件卸载/禁用：disposer 链（`runtime-loader.ts:360-378`）；App 退出：**无 disposer，随进程消失**（[AUDIT] §10） |
| Python 半体（dashboard/plugin_api.py） | **serve 进程内**（Electron main spawn `hermes serve --host 127.0.0.1 --port 0`，`backend-command.ts:20-26` 已抽查；FastAPI include_router 挂载） | 账本（SQLite）、凭据解析、Provider HTTP、Rules、轨③只读、（P2）窗口监督 | Electron main 拉 serve → serve 启动时挂载路由 | serve 进程随 Electron teardown；禁用后路由仍在但每请求查开关（`web_server_dashboard.py:649` 描述）→ 返回 409/403，插件轮询线程见连续拒绝即自停 |
| 独立鲸鱼窗（P2 可选） | 独立 `pythonw` 进程（pywebview + WebView2，frameless+transparent+on_top） | 渲染 Render Model（只读数据面，零业务逻辑） | Python 半体 `WhaleWindowSupervisor`：固定 argv + `DETACHED_PROCESS` spawn + 握手状态文件（pid/port/token 原子写，10s 等待）——hermes-pet 已验证骨架（[REF] §2.2/§2.5：`pet_window.py:139-160`、`plugin_api.py:312-394`） | 三重：(1) 用户关闭 → 桥发 `WM_CLOSE`（线程安全，`pet_window.py:121-133`）；(2) 插件禁用 → `/api/quit`；(3) 孤儿防护 → 每 4s 读 `app-online.json`，超 60s 未更新自退（文件缺失视为在线，宁多活不误杀；`pet_window.py:325-338`、`plugin_api.py:62-78`） |

**所有权原则**：
- 任何轮询/定时器单实例：余额轮询、轨③读取、归档 tick 都在 Python 半体；JS 半体只有「转发 + 投递轮询」两个轻量循环（AGENTS.md §8「禁止重复轮询 timer」）。
- 独立窗是**纯消费者**：不写账本、不持凭据、不直连 provider；桥数据 = Render Model JSON。
- Phase 2 窗口技术要点（照搬 hermes-pet 已验证件）：Windows 逐像素透明必须 `before_show` 手动 `SetWindowLongPtrW` 打 `WS_EX_LAYERED` + `WS_EX_TOOLWINDOW` 隐藏任务栏（pywebview 不自设）；移动后 `RedrawWindow` 清重影；`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--disable-gpu --disable-gpu-compositing` 防 WebView2 透明窗口原生崩溃（[REF] §2.1）。

---

## 6. 持久化布局

```
<HERMES_HOME>/whale-widget/              ← 每 profile 作用域（dashboard 请求被 _plugin_route_secret_scope
│                                           放进目标 profile 的 home/secret scope，web_server_dashboard.py:791-803）
├── whale.db / whale.db-wal / whale.db-shm   SQLite，WAL，全部账本（[DM] §7）
├── config.json                          外观/阈值/泡泡配置/轮询开关——无密钥（与 ctx.storage 的 UI 偏好分工：
│                                        跨端/跨重载需要 Python 持久化的放这里；纯 UI 偏好可放 ctx.storage）
├── credentials.json                     兜底凭据文件，仅当 secret_sources 与 env 都不可用时启用（§8.1）
├── logs/whale-widget.log                轮转 5×1MB，脱敏规则 §8.4
└── window/                              （P2）whale-window-state.json（握手）、app-online.json（心跳）
```

- **为什么不放 `plugins/<name>/` 内**：该目录属代码，catalog 更新按 SHA 原子发布/回收会清掉它（[AUDIT] §7.3）；数据必须与代码分离。
- **为什么 per-profile**：serve 进程与 secret scope 都是按 profile 隔离的（[AUDIT] §6.3 步骤 3），数据自然按 profile 分账；跨 profile 汇总列为非目标（Phase 2+ 再议，[REF] §1.4 对 per-profile 部署负担的评估）。
- **凭据文件权限**：Windows 无 POSIX 0600；缺省依赖用户目录 ACL（HERMES_HOME 在用户 profile 下）；进一步用 DPAPI 加密为**未验证**（Electron `safeStorage` 是 core 专用，`connection-config.ts:355-394`，插件不可达 [AUDIT] §8）——文件兜底方案在文档中标注风险，优先引导用户配 secret_sources（Bitwarden/1Password/Command，[AUDIT] §8）。

---

## 7. 生命周期矩阵

| 场景 | JS 半体 | Python 半体 | 独立鲸鱼窗（P2） |
|---|---|---|---|
| **Hermes 启动** | runtime-loader 加载；统一包半体默认关（opt-in，`runtime-loader.ts:868-879`），用户在 Plugins 页启用 | serve 启动时挂载路由（:805-905）；账本打开、watermark 恢复、余额轮询启动（幂等：重启后首样本对齐） | 不应存在；若上次残留 → 心跳文件超时 60s 内自退 |
| **Hermes 退出** | 渲染进程消失，无 disposer（[AUDIT] §10）——无需要清理的子资源 | serve 随 Electron teardown | ≤60s 心跳超时自退（C4 无孤儿） |
| **插件禁用（desktop 开关，实时生效）** | `unloadRuntimePlugin` 全量清理（注册/订阅/定时器/socket，:360-378） | 路由仍挂载但每请求查开关 → 拒绝（:649）；Python 半体感知连续拒绝后自停轮询、关闭账本句柄 | 桥发 `/api/quit` 立即退 |
| **插件重载（保存 plugin.js）** | fs-watch 热重载（[AUDIT] §1.1）；JS 无状态 → 无重复记账（[DM] §3.4） | 无感 | 无感 |
| **启用 dashboard 半体（`plugins.enabled`）** | — | **需重启 App** 生效（[REF] §1.1；[AUDIT] §6.1） | 重启后可开 |
| **gateway 重启（`host.restartGateway`）** | 事件 replay（replayEpoch 变化）→ 对齐模式；计数器重置检测（[DM] §3.3） | 同进程不受影响（gateway 是 serve 内组件；若 serve 整体重启 → 等价「Hermes 启动」行） | 心跳断流 → 60s 自退（再开由用户/设置触发） |
| **JS 半体崩溃/加载失败** | 错误隔离：toast + 清单行，不拖垮 app（:528-543） | 轨②继续记账（不依赖 JS）；轨①漏记标 partial（[DM] §4.3）；UI 降级显示 `host.state.focusedUsage` | 不受影响（数据源在 Python 半体） |
| **DB 损坏** | UI 提示 | fail-closed：转储损坏文件、拒写、待用户确认重建；余额显示不中断（[DM] §7.4） | 降级为只显示余额（桥数据来自内存缓存） |
| **余额 API 持续失败** | 泡泡显示 `—`/stale | 状态机 §6（[DM]）；**绝不当 0** | 同左 |

---

## 8. 升级兼容性与安全/失败边界

### 8.1 凭据流（安全边界核心）

```
用户配置 key ──► Hermes secret_sources（Bitwarden/1Password/Command，[AUDIT] §8）
                 或 env /（兜底）credentials.json
                        │ 只在 Python 半体进程内解析（get_secret，config.py:1583-1594）
                        ▼
        ProviderGateway（httpx，出站白名单：origin 必须等于模版端点，自定义 host 需本机确认——
                        [DSH] F2 credentialMayGoTo/assertSafeApiUrl 思路：禁云元数据 169.254/metadata、禁 userinfo）
                        │ 只输出：余额数值/额度/状态 + credential_fingerprint（sha256 前 24 位）
                        ▼
        SQLite / REST 响应 / 日志 —— 任何环节都不含密钥本体
JS 半体只见：{credential_id, name, configured, source}（AGENTS.md §7）
```

### 8.2 REST/WS 端点边界

- `ctx.rest` 被硬限制在 `/api/plugins/<id>/` 命名空间且有 `..` 穿越防护（`apps/desktop/src/api/plugins.ts:56-64` 已抽查）——本插件不绕行、不用 `window.hermesDesktop` 裸门（信任模型下技术上可行但非受支持面，[AUDIT] §9.2）。
- 鉴权链：渲染进程不接触原始 token；REST 经 IPC 由 Electron main 附 `X-Hermes-Session-Token`，WS 用 `?token=`（`electron/connection-config.ts:16-21`）。
- 纵深防御（本插件自己的门）：全部**写端点**校验来源为回环 + 会话 token（对应 DSH「写请求仅限本机，远端能改配置=能外带 key」威胁模型，[DSH] F2）；独立窗两级桥只绑 `127.0.0.1` + 写端点 `X-Pet-Token`（随机 16B hex 经握手文件传递，[REF] §2.3）。
- 独立窗资产路径白名单正则 + resolve 后前缀校验防穿越（[REF] §2.5）。

### 8.3 日志脱敏（AGENTS.md §7 落地）

1. 禁止输出 Authorization 头、完整 provider 响应；响应留白名单字段（[DM] §8.4）。
2. 凭据在日志中只以 fingerprint（前 24 hex）出现。
3. 提交/发布前扫描 `sk-`、`Bearer ` 模式（AGENTS.md §7）。
4. `raw_*_json` 列入库前过滤（[DM] §8.4）——日志与 DB 同规则。

### 8.4 失败恢复速查

| 故障 | 降级行为 |
|---|---|
| JS 半体崩溃 | 见 §7 生命周期矩阵；数据面不丢（Python 半体独立记账） |
| Python 半体/serve 不可达 | JS 半体 `ctx.rest` 失败 → 指数退避 + UI 明示「记账暂不可用」；实时数字走 `host.state.focusedUsage` 继续显示（低配降级面，§2.3 salvage） |
| DB 损坏 | fail-closed 拒写 + 备份转储 + 确认后重建（[DM] §7.4）；余额显示不中断（`ledger_error` 语义，[DSH] `lib/index.js:2891-2910`） |
| 余额 API 失败 | 状态机 stale/error，绝不当 0（[DM] §6） |
| 独立窗孤儿 | 心跳 60s 自退（§5）；心跳文件缺失视为在线（宁多活不误杀，[REF] §2.2） |
| 时钟回拨/乱序观测 | 单调规则忽略旧样本（[DM] §2.5） |

### 8.5 Hermes 升级风险点与本项目的兼容门

| 风险点 | 证据 | 兼容门设计 |
|---|---|---|
| gateway 事件 payload 变化 | `Usage` 接口字段**全可选**（`gateway-contract.generated.ts:558-581` 已抽查），官方明示读取要带 fallback（`sdk/index.ts:347` 邻域注释，[AUDIT] §12） | 归一化层是唯一接触面（§4）；字段全 NULL 感知；缺失 → 降级（不造 0） |
| contract 版本跳变 | `DESKTOP_BACKEND_CONTRACT = 8`（`tui_gateway/server.py:2270`） | 启动时记录探测到的 contract 值入 `whale_meta`；与已验证值不符 → UI 提示「未验证版本」但不阻断 |
| `state.db` schema 演进 | `schema_version` 表（`hermes_state_common.py:372`；本机实证 v31）；非公开 API | 轨③ schema_version 门（[DM] §4.4）：未知版本 → 轨③自动禁用 + 告警，主轨不受影响 |
| SDK area/常量变化 | area 清单随版本演进（[AUDIT] §1.3） | 只用三个高稳定面：事件订阅、`ctx.rest/socket`、floating pane（`host.openWorkspace` :1304-1354 + placement `'floating'` :1794-1799；**确切 API 形状未验证**，实现前以本机 SDK 实测为准，缺失则退 `panes` area + chip，avatar_pet 已验证组合 [REF] §3.3） |
| 桌面插件加载策略变化 | 统一半体 opt-in、SHA pin 等安全演进（[AUDIT] §1.2、§7.3） | 跟随机制本身，不 hack；FEASIBILITY_REPORT 记录每次 Hermes 升级后的冒烟清单（事件面/桥/凭据/热载四项） |

---

## 9. 最小可用性说明（每个组件为什么必须存在）

| 组件 | 不存在会怎样 | 结论 |
|---|---|---|
| JS 半体 | 没有任何半体能订阅 gateway 事件（`host.onEvent` 仅渲染进程可及，[AUDIT] §2.1）→ 轨①无从谈起；UI 无宿主 | 必须 |
| Python 半体 | 凭据（C2）、服务端 HTTP、持久化（C3）三者均无解（[AUDIT] §8/§9.2 渲染进程三缺） | 必须 |
| SQLite | localStorage 满足不了幂等/事务/并发只读（轨③同构）——自造 JSON 账本会重蹈 DSH 原子写/EBUSY/fail-closed 全套复杂度且更弱 | 必须 |
| EventNormalizer（归一化层） | Hermes payload 全可选且会演进（§8.5）；没有它，事件语义散落 UI 各处，升级即碎 | 必须 |
| Bubble Definition→Resolver→RenderModel→Renderer 解耦 | DSH 前端 1/3（约 5700 行）在泡泡编辑器的教训（[DSH] C4）；不解耦则渲染与配置互相锁死，无法分阶段交付 | 必须（结构解耦），编辑器分 4 阶段交付 |
| Rules（预算/预警） | DSH 四类提醒中的两类是产品核心（[DSH] D1）；且 `BUDGET_REACHED/BALANCE_LOW` 需要跨 turn 状态 | 必须（几十行的阈值机，不做成规则引擎） |
| 轨③（可选） | 不装它主轨也能跑；它买的是 R1 补正与「估算 vs 核心账本」的可信度 | 可选开关，默认开（读-only、fail-open） |
| 独立鲸鱼窗（P2） | Phase 1 floating pane 已满足 app 内常驻；OS 级常驻是唯一增量价值（[AUDIT] §9.2 已确认插件层无窗） | Phase 2 纯增量开关 |

---

## 10. 决策记录（Decision Records）

> 修订规则：任何决策变更必须新增一行 `DR-x (修订 of DR-y)` 并注明反证/新事实，不得原地改写历史条目（AGENTS.md §4 精神）。

| ID | 决策 | 一句话理由 | 依据 |
|---|---|---|---|
| DR-1 | **形态 = Unified Package（B）**：`desktop/plugin.js` + `dashboard/plugin_api.py` 挂 `/api/plugins/whale-widget/` | 凭据+持久化两条硬约束只有 Python 半体能满足，且 unified 包是 Hermes 官方标准形态 | §2 打分表；[AUDIT] §6/§7；[REF] §1.1/§4.2 |
| DR-2 | **记账双轨 + 可选第三轨**：① usage ledger（JS 订阅事件→REST 推 Python 幂等落库）② balance observation ledger（Python 定期观测差分 + 显式校正闭环）③ state.db 只读交叉校验（schema_version 门） | 估算与观测互为印证，谁都不足以单独当「账」；充值不冲销消费、校正显式闭环 | [DM] §3/§4；[DSH] A2/A3；[AUDIT] §5 |
| DR-3 | **凭据只存在于 Python 半体**；优先 Hermes secret_sources，兜底凭据文件；JS/UI 只见 id/name/指纹 | 渲染进程无凭据 API 且 localStorage 明文，密钥进 JS 即违反 C2 | [AUDIT] §8；AGENTS.md §7；§8.1 |
| DR-4 | **窗口：Phase 1 = in-desktop floating pane；Phase 2 可选 = Python 半体 spawn 独立透明 pywebview 进程**（hermes-pet 骨架按件复用：WS_EX_LAYERED 补丁、--disable-gpu、app-online.json 心跳 60s 自退防孤儿） | B 与 C 同分但 C 的代价是 Phase 2 才需要付的；插件层无 OS 窗口是既定安全姿态 | §2/§5；[AUDIT] §9.2；[REF] §2 |
| DR-5 | **泡泡引擎解耦**：Bubble Definition（Row/Module schema，choice 加权随机 + avoidIdx + 图片独占行）→ Resolver → Render Model → Renderer | DSH 编辑器占前端 1/3 的教训；解耦才能分阶段且渲染器可复用到独立窗 | §3；[DSH] C2/C4 |
| DR-6 | **事件归一化层**：Hermes 事件 → 9 个归一化鲸鱼事件，上层只依赖归一化事件；审批/提问类因插件面不可见采用「busy 停流启发式 + approval.cancelled 清除」（未验证，实验开关） | Hermes payload 全可选且演进，单点适配是唯一可持续接触面 | §4；[AUDIT] §4.2；`gateway-contract.generated.ts:558-581` |
| DR-7 | **生命周期**：JS 热加载可实时禁用；Python 半体启用需重启 App；独立窗心跳失败自退；一切轮询单实例；turn 结束才落库 | 各半体生命周期由宿主机制决定，不自造常驻；心跳自退是 Windows 已验证防孤儿方案 | §7；[AUDIT] §10；[REF] §2.2 |
| DR-8 | **五类金额显式分离 + 1e8 定点整数**；估算值在命名/UI/置信度三层与真实账单区分 | AGENTS.md §8 红线的模型化落地 | [DM] §1/§8；[DSH] A2（SCALE 沿用） |
| DR-9 | **存储 = SQLite（Python 半体，插件数据目录，WAL）**，自有 schema_version 迁移，fail-closed | 单写者 + 只读并发 + 单文件；结构损坏拒写不吞数据 | [DM] §7；[REF] §1.3（ro 范式实证） |
| DR-10 | **排除 D（改 Core）** | 违反最高约束 C1；且插件机制覆盖度经审计足够；core 的关闭面是有意安全姿态 | §2.3；AGENTS.md §0；[AUDIT] §1.5/§9.2 |
| DR-11 | **轨③定位为交叉校验而非主源**（与 [REF] §6.1「state.db 是正解」的取舍） | 主轨不依赖 Hermes 内部 schema 使兼容面最小；state.db 的幂等账本用于互校与计数器重置补正；官方 API 出现后可升级为权威源 | [DM] §4.1/§4.4；[REF] §6.1 |
| DR-12 | **日键用本地时区**（DSH 为北京时间系 DeepSeek 峰谷价特定需求）；币种跳变重置基准不记差值；不自动折算汇率 | 本项目不绑 DeepSeek 时段；诚实分账优于黑盒折算 | [DM] §1.2/§5.2；[DSH] A2 教训 |
| DR-13 | **落库唯一入口 = `message.complete`**；`session.usage` 心跳只进内存；dedup_key = 内容哈希 + (session, day, minute) 分桶 + 本地 turn 序号；watermark 落库 + 计数器重置检测 | Hermes 无稳定事件/turn ID，ticker 停表保证 complete 是权威终值；心跳落库违反 AGENTS.md §8 | [DM] §3；`server.py:3451-3475, 2393`；[DSH] A3 |
| DR-14 | **通知去重持久化**（budget 按日、balance_low 边沿迟滞、wait 按挂起 id），优于 DSH 的内存/刷新重响语义 | Python 半体有 DB，去重成本为零；重载不重响是明确更好的行为 | [DM] §2.10；[DSH] D1 |
| DR-15 | **宿主角色 = Hermes 内置宠物（穿鲸鱼皮肤包）+ whale 管家面板（去角色化）**（修订 of DR-4 的窗口形态目标） | 宠物侧插件唯一合法接口 = 皮肤包文件（SDK 零 pet 导出）；core 宠物窗 = 零进程管理成本的 OS 级常驻角色；busy→run / awaiting→waiting 官方语义对齐，无需注入 | §11 修订节；[PET]（docs/research/HERMES_PET_SYSTEM.md）§2-§4 |

### 未决/待验证清单（移交 FEASIBILITY_REPORT）

1. floating pane 的确切 SDK 形状（`host.openWorkspace` + placement `'floating'` vs `panes` area）——本机实测（§8.5）。
2. 审批/提问「busy 停流启发式」可靠性；`notification.show` / `pet.*` 事件语义是否可作等待信号（§4）。
3. 本机 Hermes 的鉴权模式（local token vs OAuth）对 `ctx.socket` 可用性的影响（[AUDIT] §12 标注未验证）。
4. `session_model_usage` 在未来版本的字段稳定性（轨③门的已知集随冒烟清单更新）。
5. DPAPI/凭据文件加密在 Python 侧的可行方案（§6，未验证）。

---

## 11. 修订 2026-10-04：宠物宿主化（DR-15）

> 修订依据：用户决策（**不再自建宠物角色**）+ 新事实 `docs/research/HERMES_PET_SYSTEM.md`（下称 **[PET]**，2026-10-04，本机 v0.21.5 源码只读核查，file:line 全附）。
> 遵守本文修订规则（§10）：只增不改——§1-§10 与 DR-1~14 保留历史原状，与 DR-15 的逐条关系见 §11.4。

### 11.1 背景（用户决策）

Hermes 桌面已内置宠物子系统（皮肤包 + 图库 petdex + 独立透明置顶窗 + 姿态状态机，[PET] §1-§2）。继续自建角色（DR-4 Phase 1 现状的 SVG 鲸鱼）会与之形成「双宠物」角色重复，且自建素材链（M10）长期缺位。用户决策：宿主角色改为 **Hermes 内置宠物（穿鲸鱼皮肤包）+ whale 管家面板（floating pane 去角色化）**。

### 11.2 候选比较

| 候选 | 内容 | 结论 |
|---|---|---|
| A 自建角色面板（现状） | floating pane 内自建 SVG 鲸鱼 + 泡泡（DR-4 Phase 1 现状；M10 正式素材未完成，占位 SVG 简陋） | 放弃：与内置宠物系统角色重复；自建素材成本高、DSH 素材不可复用（[REF] §G） |
| **B 宠物皮肤包 + 管家面板（选定）** | 官方宠物穿鲸鱼皮肤包（`<HERMES_HOME>/pets/<slug>/` 自动发现、无需注册，[PET] §2——**唯一合法接口 = 皮肤包文件**）；管家面板去角色化，只承载泡泡/数据/提醒/音效 | 见 §11.3 |
| C monkey-patch 内部 store | patch `store/pet.ts` / `pet-overlay.ts` 的 atom/组件，向宠物泡泡注入文案或触发反应 | **禁止**：违反 AGENTS.md §10（禁 monkey patch Hermes 内部对象）与 C1；且事实上不可达——插件是渲染进程 blob ESM、import 白名单，core 内部 store 不在面内（[PET] §3） |
| D upstream API（`host.pet.*`） | 官方插件面驱动宠物泡泡/反应/姿态 | 未来项：当前版本 SDK 对宠物零导出（[PET] §3）；已提案于 FEASIBILITY_REPORT §3.1，本项目不实施；upstream 落地后可把「并列摆位」升级为「泡泡合流」 |

### 11.3 选 B 的理由

1. **合法性**：`@hermes/plugin-sdk` 对宠物零导出（sdk/index.ts 全文 grep 无 pet）；泡泡短语硬编码（pet-bubble.tsx:33-67）、姿态纯派生（pet.ts:107 derivePetState）、pet RPC 全部核心内部（tui_gateway/server.py:180）——插件侧唯一受支持扩展面就是皮肤包文件（[PET] §2/§3），完全不触碰 C1。
2. **形态跃迁**：宠物可弹出为 core 自有 OS 级透明置顶窗（pet-overlay popOutPet/restorePetOverlay，pet-overlay.ts:197-242，Alt+滚轮缩放 / 未读徽标 / 反应动画）——插件自建窗被 deny-all（§8.2/[AUDIT] §9.2），穿皮肤包即**零进程管理成本**获得原 Phase 2（DR-4 C 路线 pywebview 独立窗）想要的桌面常驻角色形态；pywebview 路线降为后备。
3. **语义对齐免费**：core 已把会话状态派生为宠物姿态——busy→run、awaiting（attention）→waiting（pet.ts:107，[PET] §2），与本项目的忙碌/等待提醒语义天然一致，**核心自有行为，无需注入**。
4. **职责单一**：管家面板去角色化后聚焦本项目真正的核心（记账账本 + 规则提醒 + 音效，README 核心理念「鲸鱼只是表现层」）；角色动画/交互/缩放/图库全部由 core 官方维护，砍掉 M10 自建角色素材长尾。
5. **数据/代码分离一致**：皮肤包定性为**用户数据**（§11.6），与 §6「数据必须与代码分离」原则同构。

### 11.4 与 DR-1~14 的关系（无冲突；一处修订点）

| 关系 | 说明 |
|---|---|
| DR-1/DR-2/DR-3（形态/记账/凭据） | 不变——宠物宿主化只影响表现层宿主角色，三半体与数据流原样 |
| **DR-4（修订点）** | 窗口形态目标重述：OS 级常驻**角色**改由 core 宠物窗口承接（皮肤包着装）；DR-4 Phase 1 floating pane 保留 = 管家面板本体；DR-4 Phase 2 pywebview 独立窗降为后备（仅用户不使用内置宠物时才有意义） |
| DR-5（泡泡解耦） | 不变——Bubble Definition→Resolver→RenderModel→Renderer 原样，仅 Renderer 宿主从「鲸鱼角色面板」改为「管家面板」（去角色渲染） |
| DR-6（归一化层） | 不变——9 个归一化事件集不变；表现消费端由「鲸鱼动画」改为「泡泡内容 + 面板强调色」 |
| DR-7~DR-14 | 不变（生命周期/进程/记账/去重/时区语义均与角色无关） |
| DR-10（排除改 Core） | 重申一致——候选 C 出局；皮肤包是文件级接口；候选 D（upstream）仅记录提案不实施 |

### 11.5 修订后组件图

```
┌──────────────────────────────────────────────────────────────────────┐
│ ① 官方宠物窗口（Hermes core 自有，非本项目组件）                         │
│    独立透明置顶 overlay（popOut / Alt+滚轮缩放 / 未读徽标 / 反应动画）     │
│    角色 ◄── 鲸鱼皮肤包（用户数据，pets/whale/，宠物图库选择激活）           │
│    姿态 ◄── 会话状态派生（core 自有行为，无需注入）：                      │
│              busy→run、awaiting→waiting                               │
│    泡泡文字 = core 硬编码短语（插件不可注入；upstream 提案见              │
│              FEASIBILITY_REPORT §3.1）                                │
└──────────────────────────────────────────────────────────────────────┘
                  ▲ 并列摆位（用户把管家面板拖到宠物旁）
┌──────────────────────────────────────────────────────────────────────┐
│ ② whale 管家面板（本插件 floating pane，去角色化——自建 SVG 鲸鱼移除）      │
│    泡泡   ◄── 余额 / 预算 / 单轮消费 / 等待提醒（DR-5 解耦不变）           │
│    数据卡 ◄── 余额 / 今日 / 7 日（DR-1/DR-2 数据流不变）                  │
│    提醒   ◄── Rules（BALANCE_LOW / BUDGET_REACHED / wait，DR-14）      │
│    音效   ◄── sound engine（默认关）                                    │
│    情绪状态机 ──► 泡泡内容 / 面板强调色（原鲸鱼动画位）                    │
└──────────────────────────────────────────────────────────────────────┘

皮肤包数据流（一次性安装，非运行时依赖）：
assets/whale-pet-pack/（构建产物） ──用户复制──► D:\hermes\pets\whale\ ──自动发现/图库选择──► 宠物着装
```

### 11.6 皮肤包 = 用户数据（非代码）

- **归属**：安装位置 `<HERMES_HOME>/pets/<slug>/`（与 `<HERMES_HOME>/whale-widget/` 数据目录同类），**不进插件代码目录**——catalog SHA 原子发布/回收（[AUDIT] §7.3）不触碰它，插件升级/回滚不影响已装皮肤。
- **运行时依赖方向**：插件**不读取**皮肤包（记账/泡泡/提醒/音效全链路无 `pets/` 依赖）；皮肤包缺失 = 纯外观回退（宠物显示其它皮肤或默认，管家面板全功能）。
- **分发方式**：构建产物 `assets/whale-pet-pack/`（`tools/build-whale-pet-pack.py` 纯 stdlib 生成）随仓库/release zip 提供，由**用户手动复制**到 `D:\hermes\pets\whale\`——HERMES_HOME 一切写入由用户执行（AGENTS.md §0）；步骤见 INSTALL.md §12。
- **替代来源**：Hermes 内置 `/pet-generate` 可自生成同格式皮肤（示例提示 "cute pixel whale"），产物同格式自动入库（[PET] §2）。

### 11.7 新增待验证项（并入移交清单）

1. 真机宠物装载：复制皮肤包 → 图库选择 whale → 桌面出现鲸鱼（**NOT VERIFIED**，待用户执行，INSTALL.md §12）。
2. 管家面板去角色化后的视觉验收（desktop/src 改动由并行工程师落地后）。
3. upstream Hermes Pet API 提案跟进（FEASIBILITY_REPORT §3.1）；采纳前宠物泡泡文字不可注入，维持并列摆位。


---

## §12 修订 2026-10-05：交互面宠物本体化（DR-16，修订 DR-15 的面板定位）

**用户决策**：交互必须直接发生在 Hermes 内置宠物本体上（点击宠物 → 泡泡/数据/音效），而不是旁边挂一个独立面板；无论用户装备哪种宠物皮肤都要生效。

**事实依据**（docs/research/HERMES_PET_SYSTEM.md）：SDK 对宠物零导出；`react-dom` 不在运行时 import 白名单（sdk/runtime.ts:61-67）；窗口内宠物渲染为 `<canvas aria-label="… pet">` + position:fixed 容器（floating-pet.tsx:467-481），核心自带拖拽。

**DR-16**：新增**宠物交互层**（`desktop/src/ui/pet-layer.js`，原生 DOM）：
- 定位锚 = 官方无障碍属性 `canvas[aria-label$=" pet"]`（跨皮肤通用；仅作几何锚点，**绝不解析 UI 文本推断状态**——状态仍来自 gateway 事件/REST）；
- 捕获阶段指针监听 + tap/拖拽判定（slop 6px）→ 点击宠物 = controller.click()（泡泡序列/音效），拖拽完全留给核心；
- 泡泡宿主 = body 下的 fixed 层（pointer-events 仅泡泡本体），rAF 跟随宠物游走/拖动，视口钳制、无空间时翻转到下方；
- nanostores atom 直接订阅（无 React）。

**DR-15 面板降级**：管家 floating pane 改为可选（`config.pane.enabled`，默认 false）——宠物本体是主交互面，面板退为需要常驻数据卡时的 opt-in。皮肤包（DR-15）保持不变：换任何皮肤（含 petdex 商店/AI 生成）交互层均生效。

**已知边界**：弹出式宠物 overlay 是独立 OS 窗口，插件 JS 不在其中加载 → 弹出态的点击交互不可用（upstream `host.pet.*` 提案的正当时机）。

## 2026-10-07 — 当前 profile 的 Wallet 查询作用域

Dashboard 通过 SDK host.state.profile/connectionId 观察当前作用域，以 plugins.manage list 判定 Agent 后端安装与启用情况。所有 Wallet 查询缓存均包含连接和 profile；未安装或未启用时显示单一明确状态而不继续加载四组账本卡片。全局气泡与数据 atom 在作用域改变时清空，异步响应发布前校验作用域。
共享 HTTP 后端必须自行按请求 profile 授权和分派，插件不能用切换启动 profile 或复制到 code 代替此契约。需要 Hermes 核心的通用插件 API 补丁，非启动 profile 通过既有每 profile PluginHost 隔离模块缓存、数据库和后台工作。补丁已在临时 home 验证，实际核心部署待逐次授权。


## 2026-10-07 续修：已安装 profile 独立运行

用户已明确授权默认及 code 等 profile 的复制安装验证。默认/其他 profile 各自正常运行，账本、配置、模块缓存和桌面查询分隔。新增 scoped-ingest-client.js，以连接和 profile 隔离队列、重试及迟到的结算回调；轮次跟踪器按 profile 保存，旧等待/通知响应不得污染新页面。共享后端通过通用请求 profile gate 与每 profile PluginHost 服务，转发保留原客户端身份。核心需 5 个文件（web_server.py、web_server_dashboard.py、web_server_plugin_requests.py、plugin_host.py、plugin_host_child.py），后两个文件保留写接口的 loopback 限制。

JS 244 项、Python 198 项通过；真实 Whale 插件在临时 default/code 复制安装验证，从 default 和 code 两种启动 profile 下，五个端点均 200；16 次并发配置读取隔离，轮次账本隔离与重复提交幂等，远程写 403、未认证 401、未安装/未知 profile 404。实际桌面安装需要运行备份部署脚本并重启验收；测试通过不代表实际部署成功。
