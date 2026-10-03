# REFERENCE_PROJECTS — Hermes 参考插件研究

> 调研日期：2026-10-03。研究对象：本机 clone 的 3 个参考仓库（只读）、本机安装的 ai-usage-tracker（只读）、本机 Hermes `state.db`（只读实证）、以及 ≤15 分钟的 WebSearch 补充检索。
> 结论速览见文末「结论：对 whale widget 架构选型的启示」。

---

## 1. hermes-ai-usage-tracker（最重要）

| 项 | 内容 |
|---|---|
| 项目 | hermes-ai-usage-tracker（lvabarajithan fork，本机安装版 v1.0.2） |
| URL | https://github.com/lvabarajithan/hermes-ai-usage-tracker（本机源码：`D:\hermes\plugins\ai-usage-tracker\`；打包产物：`D:\hermes\desktop-plugins\ai-usage-tracker\plugin.js`，已 diff 确认与源码一致） |
| 用途 | 在 Hermes Desktop 内展示**每个 provider 的订阅配额窗口**（plan、window、% remaining、reset 倒计时）：侧边栏页 + 状态栏 chip + per-profile 切换。**刻意不做** token 计数、成本估算、时段过滤（README 明示） |
| License | MIT（Copyright (c) 2026 Abarajithan） |

### 1.1 机制剖析（不看 UI，看数据流）

**它不截获、不订阅、不 hook 任何 Hermes usage 事件。** 数据流是两条独立通道：

1. **quota 通道（主要）**：后端直接拿 profile 的凭据去调各家 provider 的 quota API。
   - `dashboard/plugin_api.py:604-616` `_PROBES` 注册表：11 个 provider 各一个探针函数；
   - `plugin_api.py:315-321` `_probe_standard` → 复用 **Hermes 内置模块** `agent.account_usage.fetch_account_usage(provider)`（anthropic/openai-codex/openrouter 三家走这条官方路）；
   - 其余为手写 httpx 探针：copilot（`plugin_api.py:341-400`）、opencode-go/zen、zai、kimi、minimax、deepseek；nous 走 portal 账号（`plugin_api.py:324-338`）；
   - **token 数据来源：没有。** 全插件无任何 token/cost 采集。
2. **activity 通道（唯一次读 Hermes 数据）**：只读打开 `state.db`，查 `session_model_usage` 表判断"最近 30 天哪些 provider 活跃"，仅用于决定给哪些 provider 出卡片——**不读 token 数值，无任何写入**。
   - `plugin_api.py:199-221` `_active_providers()`：`sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)`，`SELECT billing_provider, MAX(last_seen) FROM session_model_usage WHERE last_seen >= ? GROUP BY billing_provider`。

**usage ledger 与 SQLite schema：插件自身没有账本、没有自己的表。** 它的持久化只有：60s 内存缓存（`plugin_api.py:36,722-736`，锁 + dict）和 UI 偏好 `ctx.storage`（hidden/profile/chip 三个 key，`desktop/plugin.js:49-62`）。

**per-session / model attribution：不归它管，归 Hermes 管。** 真正的账本在 Hermes 自己的 `state.db`（本机 `D:\hermes\state.db`，**已实证**，143MB，WAL 模式，`schema_version=31`）：

- **`session_model_usage`**（per-session × per-model 账本，174 行）：
  - 复合主键 `PK(session_id, model, billing_provider, billing_base_url, billing_mode, task)` —— **幂等/去重即"按主键 upsert 累加"**；
  - 字段：`api_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, estimated_cost_usd, actual_cost_usd, cost_status, cost_source, first_seen, last_seen`；
  - 已有索引 `idx_session_model_usage_session` / `idx_session_model_usage_model`；
  - 样本：`billing_mode='subscription_included'` 的行 `cost_status='included', cost_source='none'`，estimated_cost_usd=0；同 session 不同 `task`（如 `background_review`）分计。
- **`sessions`**（session 级汇总）：`source, model, billing_provider, input/output/cache_read/cache_write/reasoning_tokens, estimated_cost_usd, actual_cost_usd, cost_status, cost_source, pricing_version, profile_name, started_at/ended_at, message_count, tool_call_count, cwd, git_branch...` —— 会话归属、成本、profile 归属一应俱全。
- ⚠️ 这是 Hermes **内部实现**，不是公开 API；schema 可能随版本演进（`schema_version` 表可做兼容检查）。此风险等级：未验证（未在官方文档中找到 schema 承诺）。

**pricing 数据从哪来**：Hermes core 自己算（`estimated_cost_usd` 已写入两表，`sessions.pricing_version` 字段暗示 core 内有定价表版本机制）；插件完全不碰定价。
**subscription quota 如何处理**：见上，逐 provider 探针 + 显式"不可用原因"（`_unavailable(reason)`，`plugin_api.py:255-257`）——没有 quota API 的 provider 明说，不伪造进度条。
**refresh 机制**：进程内 60s TTL 缓存 + `refresh=1` 强制绕过（`plugin_api.py:714-736`）；桌面端页面 120s 轮询、chip 300s 轮询（`plugin.js:41-42`）。
**profile 归因**：`_run_in_home()`（`plugin_api.py:95-113`）用 `hermes_constants` 的 **ContextVar**（线程局部）把目标 profile 的 `HERMES_HOME` 绑进探针，ThreadPool worker 各自重绑——单进程读多 profile 凭据且不污染服务进程自身。这是本仓库最有含金量的技巧之一。

**backend（dashboard/plugin_api.py）承担什么**：FastAPI router 挂载在 `/api/plugins/ai-usage-tracker/`，负责全部数据工作（profile 枚举、凭据解析、并发探针 ThreadPool 6 workers、缓存、序列化，且**凭据永不出进程**，线上只带 `configured/source` 标签）。
**desktop（desktop/plugin.js）承担什么**：纯 UI。`register(ctx)`（`plugin.js:566-617`）注册三个 area：`ROUTES_AREA`（页面 `/ai-usage`）、`SIDEBAR_NAV_AREA`（导航项）、`STATUSBAR_AREAS.right`（chip，order 125）；`ctx.rest` 调后端、`ctx.storage` 持久化、`atom/useValue` 跨组件状态、`useQuery` 轮询（`plugin.js:198-214`）。

**recorder 生命周期 / 是否要求重启**：agent 侧 `__init__.py:17-19` 是空 `register(ctx)` no-op（无工具/hook/命令，仅为让 `plugins.enabled` 信任门能按名寻址）。**desktop 半侧热加载无需重启；dashboard 后端路由在 web-server 启动时挂载 → 启用后需重启桌面 App**（README "Relaunch the desktop app after enabling"）。无 recorder 常驻，无后台线程。

### 1.2 两个关键问题的回答

**(a) 我们自己的记账系统能否建立在相同 Hermes usage source 上？——能，且这就是正解。**
- Hermes core 已在 `state.db` 维护了完整的 per-session × per-model 账本（五类 token、estimated/actual cost、cost_status/source、first/last_seen、task 维度、profile 归属、pricing_version），复合主键天然幂等。鲸鱼不需要自建写入账本、不需要截获 provider 请求、不需要事件订阅——**只读订阅 `state.db`**（`mode=ro`，WAL 模式下读写互不阻塞，已实证本机为 WAL）即可拿到全部原始数据，自己只做"展示聚合层"（今日/本周/每 token 类别/每 provider 汇总）。
- 若还需要配额数据，优先复用 Hermes 内置 `agent.account_usage.fetch_account_usage(provider)`（ai-usage-tracker 的 standard 探针即此），其次才考虑手写探针。
- 读取范式照抄 `plugin_api.py:206`：`file:{path}?mode=ro` URI + timeout + try/except 全包（DB 锁定/缺失绝不能 500）。加 `schema_version` 兼容检查。

**(b) 依赖这个第三方插件，还是参考其实现自建最小账本层？——自建最小账本层（默认倾向得到证实）。**
- 该插件与鲸鱼需求**正交**：它只做 quota 窗口，没有 token/cost 数据，鲸鱼核心诉求（消费记账 + 喂食动画）它一样都不提供；依赖它等于多一个弱相关强部署耦合（per-profile symlink + 每 profile enable + 重启）。
- 正确姿势：把它的**工程范式**搬过来（ro 打开 state.db、ContextVar 换 profile、探针表驱动、显式不可用原因、60s 缓存、desktop 半侧纯 UI + ctx.rest/storage），账本读 `session_model_usage`/`sessions` 自建聚合。零运行时依赖第三方。

### 1.3 值得参考的代码（file:line）

- `dashboard/plugin_api.py:199-221` — 只读打开 `state.db` 的标准姿势（mode=ro + 容错）。
- `dashboard/plugin_api.py:95-113` — ContextVar 线程局部绑定 `HERMES_HOME` 实现 per-profile 探测。
- `dashboard/plugin_api.py:604-616` + `315-321` — 探针注册表模式；`agent.account_usage.fetch_account_usage` 官方 quota API 的用法。
- `dashboard/plugin_api.py:655-701` — `_build_payload`：活跃∪已配置 ∩ quota_capable 的目标筛选 + 并发探针 + 单探针失败不连坐。
- `desktop/plugin.js:566-617` — desktop plugin `register(ctx)` 三 area 挂载完整范例（route/nav/statusbar chip）。
- `desktop/plugin.js:198-214` — useQuery 轮询 + `placeholderData` 防切换 profile 白屏。
- `__init__.py` 全文 — "desktop-only 插件 agent 侧 no-op" 的规范写法。

### 1.4 不适合直接复制的地方

- 它**没有** token/cost 账本——照抄它就等于放弃了鲸鱼的核心数据面；必须下沉到 `state.db`。
- 探针硬编码 11 家 provider 的私有 endpoint，维护成本高且非本项目诉求。
- 强 US-centric 细节（如 chip 时区硬编码 IST，`plugin.js:108-133`）。
- per-profile 部署模型（symlink + 逐 profile enable）对我们是负担而非特性。

---

## 2. hermes-pet（独立透明窗口路线）

| 项 | 内容 |
|---|---|
| 项目 | hermes-pet（ghoststarz/hermes-pet，dsh-pet 的 Hermes 移植，2026-08-26） |
| URL | https://github.com/ghoststarz/hermes-pet（上游：https://github.com/PC2005-cloud/dsh-pet） |
| 用途 | Hermes Desktop 独立透明置顶桌宠（pywebview/WebView2），91 段 640×360 透明 webm 动画；动画链/漫游/点击/拖拽/朝向；顶部栏按钮 + 控制子页 |
| License | MIT（Copyright (c) 2026 ghoststarz）；**注意素材承继 dsh-pet 的资产许可：开源可用但禁止商用**（来自 dsh-pet GitHub 页，未逐字核对其 LICENSE 文件——未验证） |

### 2.1 独立透明窗口实现

- **进程形态**：不是 Electron、不是主窗口内嵌。后端桥 spawn 一个独立 `pythonw` 进程跑 `scripts/pet_window.py`，pywebview 创建 **frameless + transparent + on_top** WebView2 窗口（`pet_window.py:438-450`）。
- **透明关键补丁**：pywebview 自身不设 `WS_EX_LAYERED`，Windows 上逐像素透明**必须**在 `before_show` 手动 `SetWindowLongPtrW` 打上（`pet_window.py:139-160` `_apply_layered`），并清 `WS_EX_APPWINDOW`、加 `WS_EX_TOOLWINDOW` 隐藏任务栏图标；移动后要 `RedrawWindow` 清残留重影（`pet_window.py:382-388`）。
- **GPU 兼容**：WebView2 透明窗口 + 硬件合成在拖拽/动画时易 native 崩溃，创建窗口前设 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--disable-gpu --disable-gpu-compositing`（`pet_window.py:46-51`）软件合成兜底。
- **点击/拖拽**：easy_drag=False；页面拖拽经 pywebview `js_api.move(screen_x, screen_y)` 位移窗口（`pet_window.py:363-390`）；点击=随机回应动画；朝向=webm 镜像。
- **动画/宠物包**：`assets/packs/<id>/pet.json` 声明 idle/turn/drag/clicks/moves/categories 及权重（`pet.json`）；渲染页（`assets/render/render.html`，本次未逐行读——动画链权重选择、双缓冲交叉淡入细节**未验证**，仅 PROJECT.md 描述）经本地 HTTP 服务 `http://127.0.0.1:<随机端口>/render.html` 加载，webm 走自实现 Range 206 流式响应（`pet_window.py:208-252`）。

### 2.2 进程生命周期与防孤儿

- **谁拉起**：桌面插件控制页开关 → `desktop/plugin.js` 经 `ctx.rest('/start')` → 后端桥 `plugin_api.py:312-394` 校验参数后以**固定 argv + pythonw + DETACHED_PROCESS** spawn（无 shell、无注入），随后轮询握手状态文件 `pet-state.json`（pid/port/token，原子写 tmp+os.replace）最长 10s。
- **心跳（App 在线判定）**：后端桥路由级依赖 `_touch_app`（`plugin_api.py:62-78`）——**任何** API 请求（控制页 8s 轮询 /start/config 等）+ 桌面插件显式 10s `GET /ping`（`plugin.js:259-263`）都原子刷新 `app-online.json` 的 `lastSeen`。
- **防孤儿（自决式，无看门狗线程）**：pet 进程每 4s 读 `app-online.json`，超 60s 未更新判定 App 已退出 → 自退；文件缺失/损坏视为在线（宁可多活不误杀）。退出统一走 `PostMessage WM_CLOSE`（线程安全，`pet_window.py:121-133`），最后清理状态文件。多 gateway/serve 实例并存安全（共享文件，无共享可变内存状态）。
- **Hermes 退出清理**：靠上述超时自退兜底；关闭开关则立即 `/api/quit`。

### 2.3 REST bridge 与安全

- 通道：`desktop/plugin.js` --`ctx.rest`--> `/api/plugins/hermes-pet/*`（FastAPI router）--`urllib`--> pet 进程 `http://127.0.0.1:<port>/api/*`。两级桥。
- 鉴权：pet 进程写端点（cmd/quit）需 `X-Pet-Token`（随机 16B hex，经握手文件传递，桥内缓存）；页面只读端点（init/pull）免 token（同源拿不到 token，只能读）。HTTP 只绑 127.0.0.1。
- 路径安全：pack/anim 名白名单正则 + resolve 后前缀校验防穿越（`plugin_api.py:143-150`）；play 指令校验动画名在当前包清单内。
- 配置持久化：`config.json` 逐字段类型/范围清洗（`plugin_api.py:492-551`）；asset 加载全走插件目录相对路径，自包含不依赖 Hermes 内部模块。

### 2.4 评价：鲸鱼是否适合复用/扩展这个架构？

- **架构模式值得照搬**（若走独立窗口路线）：握手状态文件、`app-online.json` 心跳 + 超时自退、WS_EX_LAYERED 补丁、固定 argv spawn、两级 REST bridge、路径白名单——这套在 Windows 上被验证过的"桌面附属进程"骨架可直接复用。
- **不建议整仓 fork**：① 它是"纯动画桌宠"，没有记账/数据面；② 91 段 webm 素材承继 dsh-pet **禁止商用**许可，鲸鱼必须自备素材；③ 依赖链重（用户需自建 pywebview venv，`HERMES_PET_PYTHONW` 或 `%LOCALAPPDATA%/hermes/hermes-pet-venv`），对"装完即用"的分发体验是显著摩擦；④ MIT 代码复用时需保留其与 dsh-pet 的署名链。
- 若鲸鱼定位需要"在 Hermes 主窗口之外常驻"（最小化/聚焦其它应用时仍可见），这是唯一成熟路径；否则见 §3 的窗口内路线成本更低。两者可组合：窗口内挂件 + 可选外挂鲸鱼进程（复用其生命周期骨架）。

### 2.5 值得参考的代码 / 不适合直接复制的地方

值得参考：
- `scripts/pet_window.py:139-160` — WS_EX_LAYERED/TOOLWINDOW 窗口样式补丁（Windows 逐像素透明的必要条件）。
- `scripts/pet_window.py:46-51` — WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS 禁 GPU 防崩溃。
- `scripts/pet_window.py:325-338, 465-488` — 原子握手文件 + 4s 轮询 60s 超时自退的防孤儿设计。
- `scripts/pet_window.py:121-133` — PostMessage WM_CLOSE 线程安全关窗。
- `dashboard/plugin_api.py:62-78, 462-478` — 路由级依赖刷心跳 + 显式 /ping 双保险。
- `dashboard/plugin_api.py:312-394` — 固定 argv spawn + 10s 握手等待。
- `desktop/plugin.js:256-283` — `titleBar.tools.right` 按钮注册 + `ctx.onDispose` 清理定时器。
- `assets/packs/default/pet.json` — 动画包清单 schema（idle/turn/drag/clicks/moves/categories + 权重）。

不适合直接复制：
- 91 段 dsh-pet webm 素材（非商用许可）。
- pythonw/venv 依赖链与两级 HTTP 桥的复杂度——只有确需独立窗口才付这个成本。
- 硬编码 640×360 / 16:9 假设（`pet_window.py:425` 高度=size×9/16）。
- 中文文件名动画资产带来的 URL unquote 处理（若鲸鱼用英文命名可省）。

---

## 3. hermes-plugin-avatar_pet（Hermes Desktop 内 Canvas/Sprite 路线）

| 项 | 内容 |
|---|---|
| 项目 | hermes-plugin-avatar_pet（Hermes Avatar — NIVO V5.1，实验性社区原型） |
| URL | https://github.com/Icarus-B4/hermes-plugin-avatar_pet（本机 clone HEAD 97c7b7d，2026-08-18 "use public voice lifecycle events"） |
| 用途 | Hermes Desktop **主窗口内**的动画角色：pane（右侧 250px）+ 状态栏 chip 弹层；对 voice lifecycle 和 agent 事件做表情/动作反应；Canvas sprite atlas 渲染 |
| License | MIT（Copyright (c) 2026 Icarus-B4） |

### 3.1 机制

- **形态**：纯 `desktop-plugins/<id>/plugin.js` 单文件 + 两张 PNG atlas，无 backend、无 plugin.yaml。安装形态是 `$HERMES_HOME/desktop-plugins/hermes-avatar-v5/`（README）。
- **lifecycle/注册**：`plugin.js:828-839` — `ctx.i18n.register`（en/de）+ 两个挂载点：`area:'panes'`（`data:{placement:'right',width:'250px'}`）和 `area:'statusBar.right'`（order 135）。chip 点击弹出 `position:fixed` 浮层承载完整角色（`plugin.js:815-826`）。
- **voice events（公开 SDK 面）**：`plugin.js:253-273` `useHermesVoiceStatus()` — 读 `host.state.voiceLifecycle.get()` 初始态 + `host.onVoiceEvent('*', sync)` 订阅，映射为 `speaking/listening/transcribing|thinking/muted/idle` 五态；序列选择优先级：voice > action > talk > blink > expression > idle（`plugin.js:699-712`），TALK 序列 10fps、精确口播同步感。
- **agent 事件→状态（启发式正则）**：`plugin.js:658-697` `host.onEvent('*')` 按事件 type 关键词映射：error/fail→sad+glitch FX；subagent/agent→agent 动作+data FX；tool/run/exec→processing+scan FX；done/complete→ok+sparkle FX；stream/token/delta→thinking（**刻意不因每个流式 token 重置动画**，thinking 已激活就保持——防抖关键细节）。
- **sprite 渲染**：`plugin.js:275-402` `CharacterSprite` — Canvas 2D + rAF，`drawImage` 按 `row/col` 切 96×104 格；离散帧切换不做 alpha 插值（防 IDLE 闪烁/重影，`plugin.js:344-352`），仅表情序列末段 22% 做 smoothstep 交叉淡化（`plugin.js:353-377`）；`FRAME_ALIGN`（`plugin.js:78-90`）逐帧像素对齐表防 atlas 帧间头部漂移；`resetKey` 强制重挂载重启序列。FX 层独立 atlas（13 格）+ CSS FX 兜底（hover/scan/data/loading/glitch，`plugin.js:455-462`）。
- **asset 加载**：`plugin.js:199-251` — 经 `window.hermesDesktop.desktopPluginsRoot()` + `readFileDataUrl()` **Desktop 文件系统桥**把 PNG 读成 data URL（含旧目录名 hermes-avatar/hermes-avatar-v5 兼容回退）。此桥 API 在本机版本的可用性**未验证**。
- **交互**：点击角色=8 帧 pet 互动序列（阶段机 idle→hand approach→…→purr）；idle 22s 无操作自动 sleep（`plugin.js:644-656`）；2.6-5.4s 随机眨眼。

### 3.2 两条路线对比（结合 Windows）

| 维度 | 独立透明窗口（hermes-pet，pywebview/WebView2） | Desktop 内 UI（avatar_pet，Canvas in pane/chip） |
|---|---|---|
| 可见性 | App 最小化/失焦仍在，真桌面常驻 | 仅在 Hermes 主窗口内；最小化即消失 |
| 依赖 | python venv + pywebview + WebView2 运行时 | 零外部依赖，单 plugin.js + PNG |
| 分发/启用 | 需装依赖 + Settings 启用 + 后端重启挂载 | 复制目录 + Settings 启用，热加载 |
| 事件获取 | 需自建两级 REST 桥 + 心跳文件 | 直接订阅 `host.onEvent` / `host.onVoiceEvent` / `host.state` |
| 生命周期 | 自管进程，需防孤儿工程（已解决但复杂） | 随 App 生命周期，零管理 |
| 素材能力 | webm 视频级（海量帧、全动效果） | atlas 精灵图（几十帧级，程序化补间） |
| Windows 风险 | WS_EX_LAYERED 补丁、GPU 合成崩溃、任务栏残留 | 基本无（普通 DOM/Canvas） |
| 数据面 | 桥两端都要写代码 | `host`/`ctx.rest` 直接可用，最短路径 |

### 3.3 值得参考的代码 / 不适合直接复制的地方

值得参考：
- `plugin.js:828-839` — `panes` area（placement/width）+ `statusBar.right` chip + `ctx.i18n.register` 组合。
- `plugin.js:253-273` — `host.state.voiceLifecycle` + `host.onVoiceEvent('*')` 公开语音状态订阅范式。
- `plugin.js:658-697` — `host.onEvent('*')` 启发式状态机（含"流式 token 不重置动画"防抖、manualLock 手动操作优先窗口）。
- `plugin.js:275-402` — 离散帧切换 vs 末段交叉淡化的 Canvas 渲染纪律；`plugin.js:78-90` FRAME_ALIGN 对齐表思路。
- `plugin.js:199-251` — `window.hermesDesktop.readFileDataUrl` 文件系统桥读取插件目录资产。

不适合直接复制：
- NIVO 角色的全部美术（atlas 是作者自制资产，无再授权说明）；鲸鱼需要自己的 atlas/帧动画。
- 事件关键词正则映射是脆弱的启发式（event type 命名变化即失效），应作为初始词表参考而非照抄。
- chip 弹层用 `position:fixed; zIndex:9999` 硬编码（`plugin.js:821`）——依赖宿主布局巧合。
- 状态全部 `useState` + timer ref，规模变大后应考虑 reducer/状态机。

---

## 4. hermes-example-plugins（官方示例 —— 官方范式事实来源）

| 项 | 内容 |
|---|---|
| 项目 | hermes-example-plugins（NousResearch 官方参考插件库） |
| URL | https://github.com/NousResearch/hermes-example-plugins |
| License | MIT（Copyright (c) 2026 Nous Research） |

### 4.1 示例清单与演示的 API/模式

| 示例插件 | Surface | 演示的 API/模式 | 关键位置 |
|---|---|---|---|
| `plugin-llm-example` | agent 侧斜杠命令 | `ctx.llm.complete_structured()`：host 托管的结构化 LLM 调用（插件永不接触 API key/OAuth）；JSON Schema 校验；image/text 输入块；trust-gate 配置（`plugins.entries.<id>.llm.allowed_models`）；`ctx.register_command` | `__init__.py:126-134`（complete_structured 调用）、`__init__.py:155-163`（register_command）、`__init__.py:55-65`（schema）、`__init__.py:81-101`（image/text 输入块） |
| `plugin-llm-async-example` | agent 侧斜杠命令 | `ctx.llm.acomplete()` + `asyncio.gather()` 并发双调用（forward + back-translation 打分）；async lane 的存在意义=并发降墙钟 | `__init__.py:1-41`（docstring 契约） |
| `example-dashboard` | dashboard 插件（web UI） | 最小 dashboard 插件全件：`manifest.json`（tab+slots+entry+api）、IIFE bundle 用 `window.__HERMES_PLUGIN_SDK__`（React/components/hooks/api/utils）、`window.__HERMES_PLUGINS__.register/registerSlot`、slot 注入（`sessions:top`）、FastAPI 后端路由 | `dashboard/manifest.json`（schema）、`dashboard/dist/index.js:93,118`（register/registerSlot）、`dashboard/dist/index.js:66-86`（SDK 全景注释）、`dashboard/plugin_api.py:11-14` |
| `strike-freedom-cockpit` | dashboard 主题 + slot 插件 | 全量换肤：主题 YAML（palette/typography/`layoutVariant: cockpit`/assets→CSS 变量/customCSS/componentStyles）、插件填充 `sidebar/header-left/footer-right` slot、`tab.hidden:true`（纯 slot 插件不进导航）、`tab.override` 可整体替换内建路由、10 个命名 shell slot（backdrop/header-left/right/banner/sidebar/pre-main/post-main/footer-left/right/overlay） | `theme/strike-freedom.yaml`、`dashboard/manifest.json:12`（slots）、`README.md`（capability 清单） |

### 4.2 对本项目特别相关的官方结论

- **两代插件 UI SDK 并存**：`example-dashboard` 是 **web dashboard** 旧代（IIFE + `window.__HERMES_PLUGINS__`，安装于 `~/.hermes/plugins/<id>/dashboard/`）；`ai-usage-tracker`/`hermes-pet`/`avatar_pet` 是 **desktop plugin** 新代（ESM `@hermes/plugin-sdk` + `ctx.register(area)`，安装于 `desktop-plugins/<id>/` 或 unified 包的 `desktop/` 子目录）。鲸鱼目标形态（AGENTS.md：Hermes Desktop Plugin）走**新代 desktop SDK**。
- 官方明确的对 author 约定（README）：自包含、单一 surface、<200 LOC、production-shaped。
- 后端 Python 路由的官方挂载点 = `<plugins_root>/<id>/dashboard/plugin_api.py` + `manifest.json`（`{name, label, description, icon, version, api}`），受 `plugins.enabled` 白名单约束——hermes-pet 把它当"进程能力层"用是合规扩展。
- `dashboard` 后端路由在 web-server 启动时挂载 → 新增/启用需重启或 `GET /api/dashboard/plugins/rescan`。

---

## 5. 其它参考项目（WebSearch 补充检索）

> 检索关键词：`hermes-agent desktop plugin`、`hermes-agent token usage cost tracker analytics`、`hermes-agent plugin pet/widget/overlay/notification`、GitHub topic `hermes-plugin`（411 repos 首页）、`dsh-pet`。**无果项**："hermes-agent 专用 token/cost tracker 插件"未检索到除 ai-usage-tracker 之外的成熟项目；plugins.omarchy.org 目录页为 JS 渲染无法抓取（显示 0 entries），其搜索摘要中提到的 quickshell "Hermes Agent Widget" 无法定位到仓库——未验证其存在。

### 5.1 rarf/hermes-quota-plugin

- URL：https://github.com/rarf/hermes-quota-plugin （MIT；74⭐）
- 用途：per-provider 配额/限流的 desktop 插件：状态栏 chip + 右侧 300px docked pane + `/quota` 命令 + CLI（`hermes quota status/refresh/provider`）。
- 值得参考（据其 README，**未 clone 源码验证**）：① **"UI 永不做网络 IO"** 的缓存文件模式——Python 端并发扫 provider 写 `$HERMES_HOME/quota_cache.json`，UI 两阶段轮询（先读缓存 `--cached`，过期再带外触发 refresh，20s 墙钟预算防挂死）；② fail-open 诚实设计：坏 provider 显式 unavailable、不伪造百分比、DeepSeek 余额不折算成 quota %、凭据永不打印/缓存。
- 不适合直接复制：同为 quota 探针集合（与 ai-usage-tracker 重叠）；Grok 走浏览器 cookie、Antigravity 模拟 CLI UA 等灰色手段不该进鲸鱼。
- License：MIT。

### 5.2 PC2005-cloud/dsh-pet（hermes-pet 上游）

- URL：https://github.com/PC2005-cloud/dsh-pet （987⭐ / 74 forks）
- 用途：DeepSeek Harness 透明桌宠（idle/漫游/拖拽/余额展示/聊天/工作状态动画）。
- 值得参考：① **DIY 素材管线**：AI 生成绿幕视频 → Python/ffmpeg 色键抠像/归一化/转码 → VP9-Alpha 透明 webm（640×360）——鲸鱼自产素材可直接借用此管线；② 透明动画的**双格式策略**（webm alpha for Win/Linux，HEVC mov for macOS/Safari——webm alpha Safari 不支持）；③ Electron 透明置顶窗口是独立窗口路线的另一种实现选择（对比 hermes-pet 的 pywebview）。
- 不适合直接复制：**素材许可禁止商用**（衍生作品须署名）；其余额展示档位与 DeepSeek 绑定。
- License：代码 MIT；素材（动画/提示词/源视频）开源可用但禁商用（据 GitHub 页，未逐字核对 LICENSE——未验证）。

### 5.3 其它次相关（仅记录，不建议深挖）

| 项目 | URL | 用途 | 参考价值 | License |
|---|---|---|---|---|
| mykeura/minimalist-themes-for-hermes | https://github.com/mykeura/minimalist-themes-for-hermes | Hermes Desktop 18 套浅色主题（installable plugin） | 证明 desktop plugin 可做主题类 UI 注入；对鲸鱼 UI 配色有参考 | 未验证（未打开仓库） |
| thomasbek3/hermes-bot-kit | https://github.com/thomasbek3/hermes-bot-kit | iMessage 风格聊天气泡 + 远程 bot 机器 live view | UI 组件化思路 | 未验证 |
| allmodels-io/hermes-speech | https://github.com/allmodels-io/hermes-speech | TTS/STT 插件 | 与 avatar_pet 的 voice lifecycle 事件面相互印证 | 未验证 |
| NousResearch/hermes-agent `apps/desktop` | https://github.com/nousresearch/hermes-agent | 官方桌面 App 源码（本机 `D:\hermes\hermes-agent` 同源，只读） | SDK/area 定义、`host.onEvent`/voiceLifecycle 实现、state.db 写入方的一手事实来源 | 未验证（主仓 MIT） |

---

## 6. 结论：对 whale widget 架构选型的启示

### 6.1 usage 来源结论（最高置信）

**鲸鱼记账层 = 只读订阅 Hermes 自有账本 `state.db`，自建最小聚合展示层，零第三方运行时依赖。**

1. Hermes core 已在 `state.db` 维护 per-session × per-model 完整账本 `session_model_usage`（input/output/cache_read/cache_write/reasoning 五类 token、api_call_count、estimated/actual cost、cost_status/source、task 维度、first/last_seen，复合 PK 天然幂等）+ `sessions` 会话汇总（source/profile_name/pricing_version/git 上下文）。本机实证（WAL、schema_version=31）。
2. 建账不等于写库：鲸鱼**不要**自建写入账本（会与 core 重复记账、产生并发写风险），要做的是 ro 打开 + 聚合视图（今日/本周、per provider/model、token 类别分布）。读取范式照抄 ai-usage-tracker 的 `mode=ro` + 全容错（`plugin_api.py:199-221`）。
3. 幂等/去重/归因无需我们解决——core 的 PK upsert 已保证；我们只需处理"读到增量"（可按 `last_seen` 水位或全量重聚合，数据量级 10² 行完全无所谓）。
4. 配额（quota）是可加项：优先复用 `agent.account_usage.fetch_account_usage`，或移植 ai-usage-tracker 探针表；非首期范围。
5. 风险与对策：`state.db` schema 属 Hermes 内部实现，随版本演进（已实证本机 v0.21.5 形态）。对策：ro 读 + 列存在性检查 + `schema_version` 兼容门 + 缺列降级。另：未验证未来版本是否提供官方只读 usage API（若有则切换）。
6. 明确**不依赖 ai-usage-tracker 插件本身**：它 quota-only、无 token/cost 数据、部署面重（per-profile symlink + 重启）；其价值全部在可搬走的工程范式。

### 6.2 窗口路线对比结论

- **默认（Phase 1）走 avatar_pet 式 desktop SDK 内嵌路线**：`@hermes/plugin-sdk` + `panes`/`statusBar` area + Canvas 渲染 + `host.onEvent` 事件驱动状态机。理由：零依赖、零进程管理、事件面直接可用（onEvent/onVoiceEvent/host.state）、与记账 UI（页面/chip）天然同进程同 SDK；AGENTS.md 的目标形态即 Desktop Plugin。
- **独立透明窗口（hermes-pet 路线）作为可选增强（Phase 2+）**，仅当产品要求"主窗口外常驻"（最小化时可见、贴屏角落）。届时**复用其骨架而非 fork 整仓**：固定 argv spawn、握手状态文件、`app-online.json` 心跳 + 60s 超时自退、WS_EX_LAYERED 补丁、`--disable-gpu` 兜底、127.0.0.1+token 两级桥。需自解 pywebview venv 分发问题（或评估 Electron 透明窗口，见 dsh-pet desktop mode）。
- 素材路线：窗口内挂件用 atlas 精灵图（参考 avatar_pat 的渲染纪律：离散帧切换 + 末段淡化 + FRAME_ALIGN）；独立窗口若追求全动效果用 VP9-Alpha webm（参考 dsh-pet 的绿幕→ffmpeg 抠像自产管线，规避其禁商用素材）。

### 6.3 是否复用 hermes-pet

**不整仓复用，按件复用。** 其价值 = Windows 独立透明窗口 + 附属进程生命周期的已验证工程实践（MIT 代码可复用，保留版权与 dsh-pet 署名链）；其不可复用部分 = dsh-pet 素材（禁商用）、纯桌宠业务逻辑、pythonw 依赖链。鲸鱼的数据面（state.db 记账）与 hermes-pet 完全正交，不存在"基于 hermes-pet 改造"的捷径——它是 UI/进程层参考，不是数据层参考。

### 6.4 留给设计文档的决策输入

- `docs/design/ARCHITECTURE_DECISION.md` 需记录：usage source = state.db ro-read（6.1）；窗口路线 = desktop SDK 内嵌优先（6.2）；若需 App 外常驻再启用 hermes-pet 骨架（6.3）。
- 需在 `docs/design/FEASIBILITY_REPORT.md` 验证项：① `host.onEvent('*')` 在本机 Hermes 版本的实际事件类型清单（avatar_pet 靠正则猜，不可靠）；② `window.hermesDesktop.readFileDataUrl` 桥可用性；③ desktop 半侧热加载边界（后端路由改动是否必须重启 App）；④ `panes` area 的 placement/width 取值规范（AGENTS.md 指引参考 `D:\hermes\desktop-plugins\prompt-snippets\plugin.js`）。

---

## 附：本调研的一手数据点

- `D:\hermes\state.db`（只读）：`session_model_usage` 174 行；样本显示 subscription_included 行 `estimated_cost_usd=0.0, cost_status='included', cost_source='none'`，同 session 的 `background_review` task 行 `cost_status=None`；`sessions.estimated_cost_usd` 有非零样本（0.181，cost_status='included'）——**cost 字段的填充策略因 billing_mode/task 而异，聚合展示时必须处理 None 与 0 的语义差**。
- ai-usage-tracker 打包产物 `D:\hermes\desktop-plugins\ai-usage-tracker\plugin.js` 与源码 `desktop/plugin.js` 头部 2000 字节 diff 一致；`.hermes-package.json` 记录 `source: D:\hermes\plugins\ai-usage-tracker\desktop` —— 证实 desktop 半侧由 Electron 从 `plugins/<id>/desktop/` 打包复制到 `desktop-plugins/<id>/`。
- 两个第三方插件共同遵循的 unified 包结构：`plugin.yaml`（agent 面，可选）+ `dashboard/{manifest.json, plugin_api.py}`（Python 后端路由）+ `desktop/plugin.js`（desktop SDK UI）——鲸鱼包结构可直接沿用。
