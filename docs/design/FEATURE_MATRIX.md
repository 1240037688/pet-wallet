# FEATURE_MATRIX — 功能可行性矩阵

> 依据：`docs/research/DEEPSEEK_WHALE_ANALYSIS.md`（DSH 逆向，下称「DSH 分析」）、`docs/research/HERMES_ARCHITECTURE_AUDIT.md`（Hermes v0.21.5+369 审计，下称「审计」）、`docs/research/REFERENCE_PROJECTS.md`（参考项目，下称「参考」）。
> 关键结论已对 `D:\hermes\hermes-agent` 源码做只读抽查复核（本文引用的 `file:line` 均相对该仓库，除非注明调研文档章节）。
> 复核日期：2026-10-03。

## 硬约束与分级定义

- **本项目禁止修改 Hermes Core**（工作区外只读）。D 级功能在本项目内等于不可用，必须给替代/降级方案。
- 账本、凭据、provider HTTP 一律放 **Python 半体**（dashboard `plugin_api.py`）——`ctx.storage` 是明文 localStorage（`contrib/plugin.ts:143-163`），密钥不能进 JS。
- UI 交互放 **desktop floating pane**（pane `placement:'floating'`：app 内固定、可拖拽浮卡，`sdk/index.ts:1794-1799`）。

| 级别 | 定义 |
|---|---|
| **A** | Hermes 官方 API 原生支持 |
| **B** | 插件可以干净实现（纯 desktop 侧 JS，无需桥） |
| **C** | 需要 Pet/Backend Bridge（Python 半体承担后端 REST，或 spawn 独立进程） |
| **D** | 需要小范围 Hermes Core 扩展（**本项目禁用** → 标注「本项目内不可用」并给替代方案） |
| **E** | 当前无法可靠实现 |

---

## 一、数据面（记账 / 用量）

| 功能 | DSH 实现方式 | Hermes 可用数据/接口 | 实现位置 | 可行性 | 是否需 Core 修改 | 风险 |
|---|---|---|---|---|---|---|
| 余额查询 | 双通道（key→`api.deepseek.com/user/balance` / 账号登录态），25s 缓存 + 在途去重 + 瞬时失败沿用旧值（DSH 分析 §A1） | 无官方余额 API。`plugin_api.py` 经 `agent.secret_scope.get_secret`（profile 作用域，`hermes_cli/config.py:1583-1594`）解析 key 后直调 provider REST；同型范式见 ai-usage-tracker `_runtime_key`（其 `plugin_api.py:268-276`）；JS 经 `ctx.rest('/balance')` 取数，密钥永不过桥 | dashboard plugin_api.py（Python 半体）+ floating pane（显示） | **C** | 否 | 需统一包 Python 半体启用（`plugins.enabled` 白名单 + 重启，审计 §6.1）；provider 接口时效；「取不到数显示 — 而非 0」语义照抄 DSH |
| 今日消费 | 余额差分记账内核（`accounting.mjs` observeBalance：8 位定点、充值不冲销、待核对显式校正；DSH 分析 §A2） | 主路径：ro 读 state.db `sessions.estimated_cost_usd/actual_cost_usd` 按日聚合（DDL `hermes_state_common.py:381`）；补充路径：余额差分法处理无 usage 口径的 provider（内核 289 行纯函数 MIT，几乎可原样移植） | dashboard plugin_api.py + 插件数据目录（账本 JSON） | **C** | 否 | cost 语义因 billing_mode/task 而异：`subscription_included` 行 `estimated_cost_usd=0, cost_status='included'`，None 与 0 必须区分（参考 §附）；state.db 属内部 schema，需 `schema_version` 兼容门 + 缺列降级；Hermes 关闭期消耗无事件 |
| 单轮消费 | `session/event` usage + turn/end 结算 + seq 防重弹泡（DSH 分析 §A3） | `ctx.onEvent('message.complete')` payload.usage 终值（`gateway-contract.generated.ts:4555-4571`，已抽查）+ `session.usage` turn 中 1s 心跳（审计 §5.1）；envelope `session_id` 分桶防主/子会话串账；cost_usd 缺省时按自备价目折算 | floating pane（desktop plugin.js 直收事件） | **A** | 否 | Usage 载荷字段**增量出现**（cost_usd/context_* 可能缺省，`sdk/index.ts:347` 注释明示）必须带 fallback；seq 双持久化防重照抄 DSH |
| usage ledger | `.dshw-usage.json`（逐轮 events 90 天/2 万条 + books + 归档 20 万条 + EBUSY 退避/原子写；DSH 分析 §A4） | 权威账本已在 core：state.db `session_model_usage`（复合 PK 幂等 upsert，`hermes_state_common.py:481`，本机实证 174 行）；插件 ro 读 + 自建聚合展示层，**不自建写入账本**（避免重复记账与并发写） | dashboard plugin_api.py + 插件数据目录（可选自管明细/归档文件） | **C** | 否 | schema 演进风险（`schema_version` 门）；读取范式照抄 `mode=ro` + 全容错（参考 §1.3：ai-usage-tracker `plugin_api.py:199-221`） |
| 7 日历史 | `usageRecordsPayload()`（today/days7/all）+ 模型占比条 + canvas 柱状图 + 搜索（DSH 分析 §A4） | `plugin_api.py` ro 读 state.db 按日/按模型聚合；`host.listPersistedSessions(route, {profile, limit})`（`sdk/index.ts:1560-1590`）可作会话清单辅助（字段覆盖未验证）；RPC `usage.bars` 是 **Nous 账户口径**（`agent/billing_usage.py:169-180` 走 portal fetch），**不可用作本地历史** | dashboard plugin_api.py + floating pane / 设置页图表 | **C** | 否 | `ctx.rest` 被硬限制在 `/api/plugins/<id>/` 命名空间（`apps/desktop/src/api/plugins.ts:56-71`「the namespace IS the boundary」，已抽查）→ `/api/analytics/*` 不可达，必须经 Python 半体 |
| provider | 34 厂商模板 + matchIds 会话事件归因（DSH 分析 §F1/F3） | 实时：`host.state.model`（`sdk/index.ts:710`）+ `session.info` 事件（模型/provider/approval mode，审计 §4.1）；历史 per-provider：state.db `session_model_usage.billing_provider`（经 Python 半体聚合） | floating pane（实时）+ dashboard plugin_api.py（历史归因） | **A** | 否 | 实时显示面原生 A；历史聚合部分为 C（见 ledger 行）；多 profile 归因需逐 profile 查询 |
| pricing | 峰谷价目表 + 自定义单价覆盖（USD 汇率折 CNY 统一记账；DSH 分析 §A3/F3） | core 原生计价：`UsageStats.cost_usd`（`apps/desktop/src/types/hermes.ts:869`，已抽查）、`sessions.estimated_cost_usd/actual_cost_usd` + `pricing_version`；自定义单价覆盖为插件侧纯数据（cost 缺省时的 B 级兜底） | floating pane（直用 core cost）+ desktop plugin.js（自定义价目表数据） | **A** | 否 | 0 与 None 语义区分（订阅口径 cost=0 是「包含」不是「免费」）；自定义覆盖仅显示层，不与 core 重复记账；DSH 峰谷节假日表仅适用于 DeepSeek 直连场景 |
| quota | 订阅额度接口（单/多窗口已用% + 重置倒计时）+ 手动/token 口径额度（DSH 分析 §F1/F3） | ai-usage-tracker 已验证范式：`plugin_api.py` 探针注册表（11 provider）+ 复用 Hermes 内置 `agent.account_usage.fetch_account_usage(provider)`（其 `plugin_api.py:315-321`）；`?profile=` 经 `_plugin_route_secret_scope` 进入目标 profile 作用域（`web_server_dashboard.py:791-803`） | dashboard plugin_api.py + floating pane 显示 | **C** | 否 | 探针逐家维护、接口时效；无 quota API 的 provider 显式 `_unavailable(reason)`，不伪造进度条（参考 §1.1） |

## 二、窗口与交互

| 功能 | DSH 实现方式 | Hermes 可用数据/接口 | 实现位置 | 可行性 | 是否需 Core 修改 | 风险 |
|---|---|---|---|---|---|---|
| 拖拽 | document 级 pointer capture，位移平方 ≥9 区分拖/点（DSH 分析 §B） | pane `placement:'floating'` 本身是 app 内可拖浮卡（`sdk/index.ts:1794-1799`，已抽查）；pane 内自研 pointer 逻辑照抄 DSH | floating pane | **B** | 否 | 内嵌形态拖拽边界 = app 窗口而非桌面；独立窗口形态拖拽经 pywebview `js_api.move`（C 级，参考 §2.1） |
| 吸附 | snapConfig 四边吸附（ratio/px/off）+ 图像中心判定（DSH 分析 §B） | floating pane 内坐标计算，算法照抄（净距离格式 + 脏数据自愈） | floating pane | **B** | 否 | 吸附目标是视口（app 窗口）内边缘；独立窗口形态才是桌面级吸附 |
| 透明窗口 | 页内透明 PNG 元素（宿主即浏览器页面） | **无插件窗口 API**：`window.open`/`target=_blank` 全量 deny（`window-open-policy.ts:74-93` `return { action: 'deny' }`，已抽查）、preload 无建窗 IPC、透明窗口（HUD/pet overlay/quick entry）为核心专用（`electron/main.ts:1506-1509`，已抽查）。可行路径 = Python 半体 spawn 独立 pywebview 进程（frameless+transparent+`WS_EX_LAYERED` 补丁，hermes-pet `pet_window.py:139-160` Windows 已验证） | 独立进程（Python spawn） | **C** | 否（官方 overlay 窗口 API 属 Core 扩展，仅作 upstream 建议，本项目不做） | pywebview venv 依赖链（分发摩擦）；GPU 合成崩溃需 `--disable-gpu` 兜底（`pet_window.py:46-51`）；远程 Hermes 不可用（见下）；macOS/Linux 透明未验证；素材须自备（DSH 素材许可不允许再分发，DSH 分析 §G） |
| 置顶 | 桌面常驻（宿主页面即前台） | 同上：pywebview `on_top` + `WS_EX_TOOLWINDOW` 隐藏任务栏（hermes-pet 已验证）；内嵌形态仅有「app 内常驻」（floating pane 不占布局、可锚定角落） | 独立进程（Python spawn） | **C** | 否 | 同透明窗口行；app 最小化时内嵌形态不可见——产品上若要求「主窗口外常驻」必须走 C 级独立进程 |
| 点击 | 单击 = 推进泡泡序列 + 手动刷新余额（DSH 分析 §B） | floating pane 内 DOM click；链接经 `ctx.os.openExternal(url)`；系统通知动作经 `ctx.os.notify` actions | floating pane | **B** | 否 | 无 |

## 三、角色与泡泡

| 功能 | DSH 实现方式 | Hermes 可用数据/接口 | 实现位置 | 可行性 | 是否需 Core 修改 | 风险 |
|---|---|---|---|---|---|---|
| 角色动画 | cut-out PNG + 按压 Q 弹（scaleY 过冲回弹）+ 翻转/朝向（DSH 分析 §B/E2） | Canvas/PNG 渲染纪律照抄 avatar_pet：离散帧切换 + 末段 smoothstep 淡化 + FRAME_ALIGN（参考 §3.3）；动画循环用 SDK `createBudgetedLoop`（rAF 预算，`sdk/index.ts:1930`） | floating pane | **B** | 否 | 素材必须自产（DSH/avatar_pet/dsh-pet 素材均不可再分发）；透明像素命中测试 + 凸包 clip-path 照抄 DSH |
| 泡泡 | 模块化泡泡渲染引擎（Row→Module schema、占位符、跑马灯渐变、ticker 原地刷新；DSH 分析 §C2） + 系统泡泡优先队列（预算>预警>消耗>等待，§D3） | floating pane 内 DOM 气泡，渲染引擎/优先队列/合批/TTL 巡检逻辑整体照抄（纯前端）；「泡泡不可用退化为居中卡片」→ 退化为 `host.notify` app 内 toast | floating pane | **B** | 否 | z-index 依赖宿主布局（avatar_pet 硬编码 9999 的教训，参考 §3.3）——用 SDK Dialog/Popover 基础件优先；pane 锚点（`anchor:'top-right'`）与尺寸需适配 |
| 泡泡编辑器 | ~5700 行（schema+行合并+加权抽样+A/B 并列+模块库+悬浮快捷编辑+预览；DSH 分析 §C3/C4） | ROUTES_AREA 设置页 + SDK 基础件（Dialog/Tabs/Select…，`sdk/index.ts:1801-1874`）；配置持久化经 `ctx.rest` 存 Python 半体或 `ctx.storage`；按 C4 四阶段切分（数据层→渲染→基础编辑器→进阶） | desktop plugin.js（ROUTES_AREA 设置页） | **B** | 否 | 工作量最大单块（占 DSH 前端 1/3）；触摸长按拖拽、系统字体枚举属第④阶段可延后 |

## 四、提醒

| 功能 | DSH 实现方式 | Hermes 可用数据/接口 | 实现位置 | 可行性 | 是否需 Core 修改 | 风险 |
|---|---|---|---|---|---|---|
| 余额提醒 | `balance <= threshold` 每次刷新后检查，内存布尔去重（DSH 分析 §D1） | 数据源为 C 级（plugin_api.py 取余额）；阈值判断 + 泡泡在 JS；升级通道 `ctx.os.notify`（**仅用户离开 Hermes 时**触发 + 设置门控，`contrib/plugin.ts:46-52` 已抽查） | dashboard plugin_api.py + floating pane | **C** | 否 | 依赖 Python 半体轮询节奏（建议 60s + 手动刷新）；恢复高于阈值才复位照抄 DSH |
| 预算提醒 | `today_usage >= budget`，同日同额只弹一次（DSH 分析 §D1） | 数据源为 C 级账本聚合；去重键 `'日期:金额'` 照抄 | dashboard plugin_api.py + floating pane | **C** | 否 | 同上；币种不一致且无汇率时「宁可不比较不误报」照抄 DSH |
| 任务完成提醒 | last-turn seq 每秒轮询 + 任务结束音（DSH 分析 §D1/D4） | **无需轮询**：`ctx.onEvent('message.complete')` 即边沿事件（status 含 complete/error/interrupted）；`host.state.busy` 下降沿兜底（`sdk/index.ts:680`）；`host.notify` app 内 toast 随时可发 | floating pane | **A** | 否 | error/interrupted 状态需过滤或区分显示；seq 防重照抄（多客户端/重载场景） |
| Question 提醒 | 从会话事件流推断 `ask_user_question` 挂起 + 单槽位 + 声音 localStorage 去重（DSH 分析 §D2） | **源码核实（抽查修正）**：clarify 是工具且属 `_TOOL_LIFECYCLE_UI_TOOLS`（`tui_gateway/server.py:2141-2157`），其 `tool.start`/`tool.complete` 生命周期事件**无视 tool_progress 设置必发**（门控短路：`tool_progress.py:291`）→ `ctx.onEvent('tool.start')` name==='clarify' 置 pending（payload.args 含问题文本），`tool.complete` 同 tool_id 解除。注意：clarify 本体是 Server→Client JSON-RPC（`gateway-contract.generated.ts:5643`），**只能观测不能代答**（SDK 无 respond 面） | floating pane（desktop plugin.js 直收事件） | **A** | 否 | 已核实源码、端到端未实测；若未来 clarify 脱离工具执行路径则失效（回退：`busyBySession` 停滞启发式，B 级）；多会话并发提问需按 session_id 建多槽位（DSH 是单槽位） |
| Approval 提醒 | 事件流推断 `approval/asked` + 单槽位（DSH 分析 §D2） | 事件流仅有 `approval.cancelled`（`gateway-contract.generated.ts:5689`），**无 asked 事件**（approval 是 ServerRequestMap JSON-RPC，`:5641`）。可靠路径 = agent 半体 hook：`pre_approval_request`/`post_approval_response`（`hermes_cli/plugins.py:143-148`，observer-only、returns ignored；触发点 `tools/approval.py:914`、`tools/approval_gateway_wait.py:110,198` 等，已抽查）→ 写插件数据目录状态文件 → `plugin_api.py` REST 暴露 → 桌面 1s 轮询。降级近似：`host.state.awaitingResponse` + `busyBySession` 停滞 + `approval.cancelled`（B 级，可靠性有限） | dashboard plugin_api.py（桥）+ 插件数据目录（状态文件）+ floating pane（轮询/显示） | **C** | 否 | 需 agent 半体安装启用（统一包，与 Python 半体同一部署约束）；hook kwargs 带 `command/description/session_key/surface`（`:144-147`）够用但 surface 需过滤 gateway；不能代答也不应代答；后台 profile 的审批需逐 profile 轮询 |
| 音效 | Web Audio 预解码同步起播 + press/release 精确排期 + AudioContext 生命周期守卫（DSH 分析 §E1） | renderer 内同一引擎整体照抄（纯前端 Web API，无 Hermes 依赖）；任务结束音由 `message.complete` 事件驱动 | floating pane | **B** | 否 | AudioContext 需首次手势解锁（非手势触发的任务结束音不能 close context，DSH :95-133 注释经验）；音效总开关关闭时不建 context |
| 自定义音效 | wav 导入（可视化裁剪/试听）+ 音效组 + 槽位留空=静音（DSH 分析 §E1） | 拖拽导入（renderer File API）或 `ctx.os.pickOpenPath` 选路径（返回后端文件系统语义路径，`contrib/plugin.ts:59-65` 已抽查）→ 经 `ctx.rest` 上传/读取；存储用 renderer IndexedDB（不受 localStorage 5MB 限制）；Web Audio decode | floating pane | **B** | 否 | IndexedDB 随 App 数据清理而丢 → 提供导出/导入对冲；独立窗口形态的资产需经桥同步到插件数据目录（C 级补充） |
| 自定义角色 | png/gif/apng 导入裁剪 + 置顶 + 删除回退默认（DSH 分析 §E2） | 同上：File API 导入 → IndexedDB；透明像素命中测试照抄；`os.pickOpenPath` 备选 | floating pane | **B** | 否 | 大 GIF 内存占用；APNG 的 dataURL 是 image/png 需额外字段区分（DSH 经验） |
| 图片库 | 泡泡图库 + 内置语义 id 常驻（bimg_petpet/money1；DSH 分析 §E3） | IndexedDB + 「内置语义 id 不随用户图库清空而失效」逻辑照抄 | floating pane | **B** | 否 | 无 |

## 五、Provider 与凭据

| 功能 | DSH 实现方式 | Hermes 可用数据/接口 | 实现位置 | 可行性 | 是否需 Core 修改 | 风险 |
|---|---|---|---|---|---|---|
| API Key | `ctx.credentials.set/resolve/unset` + 凭据名白名单 + sha256 指纹分账本（DSH 分析 §A2/F2） | **桌面插件无任何凭据 API**（审计 §8：ctx.storage 明文、ctx.os 无 keychain、safeStorage 不对渲染层开放）。密钥由用户经 Hermes 原生机制配置（profile `.env` / config / secret_sources：Bitwarden/1Password/Command，审计 §8）；`plugin_api.py` 经 `agent.secret_scope.get_secret` 在 profile 作用域**只读**解析（`hermes_cli/config.py:1583-1594`，已抽查）；JS 侧只见指纹/掩码 | dashboard plugin_api.py | **C** | 否 | **无写入 API**：完整「密钥管理 UI」降级为「Hermes 侧配置 + 插件只读显示指纹」（写 config.yaml 属 hack，不做）；ctx.storage 严禁存 key；账本按密钥指纹分本照抄 |
| 自定义 HTTP Provider | 34 模板（凭据名/币种/接口/JSON 路径/scale/探活）+ 凭据目的地白名单 + URL 校验（DSH 分析 §F1/F2） | `plugin_api.py` 模板注册表（纯 Python 数据 + httpx）+ `credentialMayGoTo` 白名单逻辑移植 + `assertSafeApiUrl`（禁云元数据/userinfo）移植；「无余额接口」类 provider 走探活 + 会话事件估算 | dashboard plugin_api.py | **C** | 否 | 模板接口地址/字段路径需逐一验证时效（原仓库自己记录过接口下线案例，DSH 分析 §G）；写请求仅限本机来源的校验照抄 |

## 六、系统与平台

| 功能 | DSH 实现方式 | Hermes 可用数据/接口 | 实现位置 | 可行性 | 是否需 Core 修改 | 风险 |
|---|---|---|---|---|---|---|
| 设置页面 | 前端设置面板（外观/泡泡/音效/提醒/模型） | `ROUTES_AREA` + `SIDEBAR_NAV_AREA` + `STATUSBAR_AREAS.right` chip（ai-usage-tracker 已验证组合，参考 §1.3）；`APPEARANCE_AREAS.extra` 可挂外观页控件 | desktop plugin.js | **A** | 否 | 无 |
| 数据持久化 | `$DSH_HOME` 文件族 + 候选表（DSH 分析 §0） | 三层：① `ctx.storage`（官方；明文 localStorage，键 `hermes.plugin.<id>.`，`contrib/plugin.ts:143-163` 已抽查）存偏好/布局/去重标记；② IndexedDB 存媒体资产（B）；③ 账本/大文件由 Python 半体写插件数据目录（原子写 tmp+rename、EBUSY 退避、fail-closed 拒绝覆盖损坏账本——照抄 DSH ledgerIo） | desktop plugin.js（ctx.storage/IndexedDB）+ 插件数据目录（Python 半体写） | **A** | 否 | ctx.storage 明文 → 只放非敏感数据；「已提醒过」状态不持久化（预警/预算刷新后再响一次）是 DSH 刻意行为，照抄与否需产品决策 |
| 开机 / 随 Hermes 启动 | 随 DSH 页面每次打开自动出现 | desktop plugin 由 runtime-loader 启动扫描自动加载（审计 §1.1）；统一包半体随 App 启动物化到 `desktop-plugins/`（审计 §7.3）。OS 开机自启属 App 层能力（`main.ts` 未发现 `setLoginItemSettings`，未验证）——插件不承担 | desktop plugin.js（自动加载） | **A** | 否 | 统一包桌面半体默认 **opt-in**（`.hermes-package.json` marker ⇒ `defaultEnabled:false`，审计 §1.2），首次安装需用户在设置启用一次 |
| Hermes 退出后挂件退出 | 随宿主页面关闭消失 | 内嵌形态：渲染进程同生命周期，**天然满足**；注意 App 退出**不执行**插件 disposer（审计 §10，无 before-quit 插件钩子）。独立进程形态：文件心跳自退（`app-online.json` 4s 轮询/60s 超时，hermes-pet `plugin_api.py:62-78,462-478` 已验证） | desktop plugin.js + 独立进程（心跳自退） | **A** | 否 | 独立进程必须靠心跳而非插件清理（无 before-quit）；心跳文件原子写照抄 |
| 多 profile | 按密钥指纹分账本（近似需求） | 官方路由面：`host.profiles` / `host.profileRoutes` / `host.requestProfile` / `host.listPersistedSessions(route, {profile})`（审计 §2.1）；Python 侧 ContextVar 线程局部换 `HERMES_HOME` 实现 per-profile 探测（ai-usage-tracker `plugin_api.py:95-113`） | floating pane（路由面）+ dashboard plugin_api.py（数据面） | **A** | 否 | `ctx.rest`/`hermesApi` 默认当前 profile 作用域；跨 profile 聚合账本需逐 profile 请求（数据面为 C 级桥） |
| 多 session | turnAggs 按 session.id 分桶（DSH 分析 §A3） | `host.state.busyBySession`（id→mid-turn map，`sdk/index.ts:682` 已抽查）+ 全部事件 envelope 带 `session_id`（审计 §4）+ `host.state.focusedUsage/focusedSessionId`；逐会话 usage 拉取 `host.request('session.usage', {session_id})`（参数形状未验证，建议先 `ctx.onEvent('*')` 观察） | floating pane | **A** | 否 | 后台会话 usage 载荷字段增量出现需 fallback；question/approval 多槽位按 session_id 建（DSH 单槽位需改造） |
| 远程 Hermes | —（DSH 无此概念） | 内嵌形态：事件面走网关 WS 理论可用，但 OAuth remote 上 `ctx.socket` **no-op**、必须保留轮询 fallback（`api/plugins.ts:89-94` 已抽查）；`ctx.rest` 经 Electron main 代理对远端后端的支持**未验证**；Python 半体（余额/账本/探针）运行在**远端**主机上（数据可经 REST 回传，但其 spawn 的窗口进程会开在远端机器上）。独立窗口形态：**不可用** | 不可用（独立进程形态）/ 未验证（内嵌形态） | **E** | 否 | 首版明确不支持「远程 Hermes + 独立窗口」组合；内嵌形态需实测远程 REST/事件后才能给结论 |
| Windows | — | Electron 渲染层平台无关（本机 ai-usage-tracker Windows 实证）；独立窗口路线的 Windows 补丁已被 hermes-pet 验证（WS_EX_LAYERED/RedrawWindow/`--disable-gpu`） | floating pane / 独立进程 | **A**（内嵌） | 否 | 独立窗口细节照抄 hermes-pet；MSIX/Store 分发与桌面插件目录的兼容未验证 |
| macOS | — | 内嵌渲染层平台无关；音效需 AudioContext 空闲 suspend（防持有 `PreventUserIdleSystemSleep`，DSH 分析 §E1）；独立窗口透明（pywebview macOS 路径）**未验证**；透明视频需 HEVC mov 替代 webm alpha（dsh-pet 双格式策略，参考 §5.2） | floating pane | **A**（内嵌） | 否 | 独立窗口形态 UNVERIFIED（任务方示例中 macOS transparency UNVERIFIED 结论维持） |
| Linux | — | 内嵌渲染层平台无关；独立窗口未验证（hermes-pet 为 Windows 专测；webm alpha 在 Linux 可用，参考 §5.2） | floating pane | **A**（内嵌） | 否 | 独立窗口形态 UNVERIFIED；WM/合成器变异性大 |

---

## 分级汇总

| 级别 | 数量 | 功能 |
|---|---|---|
| **A** | 14 | 单轮消费、provider、pricing、任务完成提醒、**Question 提醒**、多 session、多 profile、设置页面、数据持久化、随 Hermes 启动、Hermes 退出后挂件退出、Windows、macOS（内嵌）、Linux（内嵌） |
| **B** | 10 | 拖拽、吸附、点击、角色动画、泡泡、泡泡编辑器、音效、自定义音效、自定义角色、图片库 |
| **C** | 12 | 余额查询、今日消费、usage ledger、7 日历史、quota、余额提醒、预算提醒、**Approval 提醒**、API Key、自定义 HTTP Provider、透明窗口、置顶 |
| **D** | **0** | 无——原候选「question/approval 观测」经源码抽查修正：question 走 `tool.start/complete` 生命周期事件（A 级，`server.py:2141`）、approval 走 agent 半体 `pre_approval_request` hook（C 级，`hermes_cli/plugins.py:143-148`），均无需修改 Core |
| **E** | 1 | 远程 Hermes（独立窗口形态不可用；内嵌形态未验证） |

> C 级 12 项中除「透明窗口/置顶」外，全部共享同一个部署前提：**统一包（agent 半体 + dashboard 半体 + desktop 半体）**安装并加入 `plugins.enabled` 白名单后重启 App——这是 ai-usage-tracker 已验证的常规形态，不是额外 hack。
