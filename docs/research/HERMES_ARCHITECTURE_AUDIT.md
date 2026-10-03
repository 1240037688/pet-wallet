# Hermes Agent 插件体系架构审计

> 审计方式：本机源码只读审计（未打开/写入 state.db，schema 全部来自源码类型定义与 DDL）。
> 所有 `file:line` 引用均相对 `D:\hermes\hermes-agent\`（除非另有说明）。未实测行为处标注「未验证」。

---

## 0. 版本与环境事实

| 项 | 事实 | 证据 |
|---|---|---|
| 源码位置 | `D:\hermes\hermes-agent`（git checkout，main 分支） | `git log -1` |
| commit | `0ff4c748658ff5b92661fa2b453fcf8ed813414d`，2026-10-02 | `git log -1` |
| 版本描述 | `git describe` = `rc.35-v0.21.5-369-g0ff4c74865`（即 v0.21.5 之后 369 个 commit；用户所述安装版本 v0.21.5+6188.g0ff4c74 / 2026-09-24，本 checkout 更新） | `git describe --tags` |
| Python 包版本 | `pyproject.toml` `version = "0.0.0"`（版本由 git/发布流程注入） | `pyproject.toml:7` |
| HERMES_HOME | `D:\hermes\`（state.db、desktop-plugins、plugins 都在此） | 目录结构 |
| 已装 agent 插件源码 | `D:\hermes\plugins\{ai-usage-tracker, hermes-lcm, hermes-vault, hindsight, prompt-optimizer, ssh-plugin}` | 目录列举 |
| desktop-plugins 产物 | `D:\hermes\desktop-plugins\{ai-usage-tracker, hermes-paper-reader, hermes-ssh, hermes-vault, prompt-enhancer, prompt-snippets, ssh-plugin}`，其中 ai-usage-tracker / hermes-paper-reader / hermes-ssh / ssh-plugin 带 `.hermes-package.json`（统一包桌面半体），hermes-vault / prompt-enhancer / prompt-snippets 为裸 `plugin.js` | 目录列举 |

---

## 1. Desktop Plugin 体系：加载、注册、执行

### 1.1 加载管线

桌面插件 = 一段**纯 ESM JS**（`plugin.js`），在 Electron **渲染进程内**求值。管线（`apps/desktop/src/contrib/runtime-loader.ts:1-33` 文件头自述，实现 `runtime-loader.ts:380-544`）：

```
源码文本 → import 白名单校验（只允许 @hermes/plugin-sdk 与 react*）
        → bare specifier 改写为 shim blob URL（sdk/runtime.ts）
        → blob import()（10s 超时，IMPORT_TIMEOUT_MS=66 行）
        → 校验 default export 的 HermesPlugin（有 id + register 函数）
        → plugin.register(createPluginContext(id, ...))
```

- **import 白名单**：`unsupportedImports()`（`runtime-loader.ts:339-358`）拒绝一切非 `@hermes/plugin-sdk` / `react` / `react/jsx-runtime` / `react/jsx-dev-runtime` 的导入；URL scheme（`https://`、`file:`）也被拒——插件不能拉第二段远程代码。
- **SDK 注入**：`sdk/runtime.ts:26-39` 把整个 SDK 命名空间挂到 `globalThis.__HERMES_PLUGIN_SDK__`（另有 `__HERMES_REACT__` / `__HERMES_REACT_JSX__` / `__HERMES_REACT_JSX_DEV__`），shim blob 从全局重导出（`runtime.ts:43-56`，映射表 `sdkImportMap:61-70`）。React 用 app 的单例，避免双实例破坏 hooks。
- **来源（磁盘门）**（`runtime-loader.ts:546-563`）：
  1. `<HERMES_HOME>/desktop-plugins/<id>/plugin.js` — 独立桌面插件（app 级，跨 profile 常驻）；
  2. `<HERMES_HOME>/plugins/<id>/desktop/plugin.js` — 统一包的桌面半体，由 Electron **复制**到 1 的位置（见 §7）。
- **自维护**：每个 plugin.js 有 fs-watch（保存即热重载，`watchDiskPluginFile:787-803`）；根目录也有 watch，新文件夹出现即加载、删除即卸载（`scanDiskPlugins:810-906`）；老 shell 退化为 5s 可见态轮询（`DISK_POLL_MS:565`）。手动命令「Reload desktop plugins」重读所有已知条目（`runtime-loader.ts:955-957`）。
- **源码上限**：专用 `readPluginSource` IPC 上限 16 MiB；老 shell 的 512 KiB 预览读在截断时**报错**而不是求值半截文件（`readPluginSourceText:666-690`）。
- **加载失败隔离**：错误 toast + 独立清单行，绝不拖垮 app（`loadRuntimePlugin` catch 分支：528-543）；`register()` 半途抛出会回滚全部已注册内容（`failRegistration:469-482`）；每个 disposer 独立 try/catch（`unloadRuntimePlugin:360-378`，#126338）。

### 1.2 `.hermes-package.json` 的作用

统一包桌面半体的**来源标记**（`runtime-loader.ts:587-592` `PACKAGE_MARKER`；`apps/desktop/electron/desktop-plugins-root.ts:23-31`）：

```json
{ "package": "ai-usage-tracker", "source": "D:\\hermes\\plugins\\ai-usage-tracker\\desktop",
  "sourceMtimeMs": 1789822864176.915, "catalogName": "ai-usage-tracker",
  "repo": "https://github.com/lvabarajithan/hermes-ai-usage-tracker", "sha": "14e844f6..." }
```

- 三个作用：(a) 标识此文件夹是包的桌面半体（可被更新/回收）；(b) 使插件**默认关闭**（opt-in，`runtime-loader.ts:868-879`：`marker ? false : undefined`，对齐 GHSA-mcfc-hp25-cjv7）；(c) 记录 catalog/repo/sha 溯源，供 Plugins 页把桌面行与 agent 行配对（`runtime-loader.ts:629-641` 读标记）。
- 由 Electron 在复制半体时写入（`desktop-plugins-root.ts:163-246` `writeDesktopHalfMarker` / `materializeDesktopHalf`），来源取 `.hermes-catalog.json` sidecar 或 `.git/config` 的 origin（`packageOrigin:41-77`）。源文件 mtime 更新则重复制；源包被卸载则删除半体（`reconcileUnifiedDesktopHalves:301+`）。

### 1.3 插件能注入的 UI（area 清单）

贡献点模型：`ctx.register({ id, area, render?, data?, order?, when? })`，id 自动加 `<pluginId>:` 前缀、source 自动盖 `plugin:<id>` 章（`contrib/plugin.ts:275-298`）；集中注册表按 area 缓存/失效（`contrib/registry.ts:19-80`）。

SDK 导出的常量 area（`sdk/index.ts`）：

| Area 常量 | 行 | 用途 |
|---|---|---|
| `PANES_AREA`（='panes'） | 1979 | 工作区 pane（会话 tile 同款 dock/tab 体系；`host.openWorkspace` 的落点，:1304-1354；`'floating'` placement 是 app 内拖拽浮卡，:1794-1799） |
| `STATUSBAR_AREAS.left/right` | 1980 | 状态栏左右槽 |
| `TITLEBAR_AREAS.center/left/right` | 1985 | 标题栏槽（常驻挂载） |
| `ROUTES_AREA` / `SIDEBAR_NAV_AREA` | 1739-1744 | 注册页面路由 + 侧栏导航项 |
| `COMPOSER_AREAS`（+ ComposerMiddleware 等） | 1671-1678 | 输入框扩展（@补全源、附件 provider、model pill provider 等） |
| `PALETTE_AREA` | 1697 | ⌘K 命令面板命令 |
| `KEYBINDS_AREA` | 1953 | 快捷键 |
| `SESSION_ROW_AREAS.leading/.trailing` | 1994 | 会话行首/尾装饰 |
| `APPEARANCE_AREAS.extra` | 1750 | 外观设置页末尾控件 |
| `THEMES_AREA` | 2062 | 主题 |
| `MODEL_MENU_ROW_AREA` | 1780 | 模型菜单行装饰 |
| `SIDEBAR_NAV_PREFS_AREA` | 2031 | 侧栏 nav 隐藏/排序偏好 |
| `TRANSCRIPT_DIRECTIVE_AREA` | 2008 | 转录内 `::directive{...}` 自定义组件 |
| `CHAT_EMPTY_AREA` | 1933 | 空会话占位 |
| `WORKSPACE_PAGE_HEADER_AREA` / `WorkspacePageHeaderControl` | 1743, 1698-1703 | 页头控件 |
| `SIDEBAR_PROFILE_GROUP_HEADER_AREA` | 1741-1744 | 侧栏 profile 组头 |
| `Contribute`（挂载域贡献） | 1891 | 组件挂载期间渲染到目标 area |

实测样例（本机 ai-usage-tracker 的 plugin.js 尾部）：注册 `ROUTES_AREA` 页面 + `SIDEBAR_NAV_AREA` 导航 + `STATUSBAR_AREAS.right` 状态芯片。

### 1.4 bundled plugin 与打包

- **Bundled**：`apps/desktop/src/plugins/<name>/plugin.{ts,tsx,js}` 由 **vite glob**（`contrib/plugins.ts:17` `import.meta.glob(..., { eager: true })`）在 app 构建时打进主 bundle；`@hermes/plugin-sdk` 由 vite alias 指向 `src/sdk/index.ts`（`apps/desktop/vite.config.ts:221`）。同目录 `plugin.js` 形态是被收编的独立仓库插件，保持纯 ESM 以便 runtime 门也能加载（`contrib/plugins.ts:1-15`）。
- **Runtime plugin.js 的打包**：仓库内**没有**官方「把 TS/JSX 编译成 plugin.js」的工具（`hermes_cli/` 与 `apps/desktop/scripts` 均无对应命令；已 grep 确认）。官方引导是 `hermes-example-plugins` 仓库（`src/plugins/README.md`）+ `hermes plugins doctor`（agent 侧校验，`hermes_cli/plugin_dev.py`）。本机 ai-usage-tracker 的 desktop/plugin.js（21KB，手写单文件 ESM，desktop-plugins 与 plugins/desktop/ 两份字节相同）说明小插件直接手写即可；大插件需作者自行用 esbuild/rollup 打单文件（未验证官方推荐链）。
- **Admission lint**：catalog 安装的 plugin.js 会过静态检查 `hermes_cli/plugin_validate_desktop.py:17-52`——禁止原型补丁、eval/new Function、白名单外动态 import、`<script>` 注入、触碰 app DOM（`data-slot` 等选择器）。这是评审 tripwire，不是沙箱。

### 1.5 信任模型（重要）

`runtime-loader.ts:21-33` 明示：**这不是能力边界**。加载的插件在渲染进程 realm 以完整 app 权限求值（React 单例、全部 SDK、`host.request` 网关 RPC、`ctx.rest`、navigate、以及可触达的 `window.hermesDesktop`）。隔离只有**错误隔离**。本地磁盘文件本来就可信（能写盘就能跑代码）；catalog 信任来自人工评审的精确 SHA pin + 上述静态 lint。

---

## 2. `@hermes/plugin-sdk` 完整 API 面

实现：`apps/desktop/src/sdk/index.ts`（2104 行）；bundled 走 vite alias（`vite.config.ts:221`），runtime 走 `__HERMES_PLUGIN_SDK__` shim（§1.1）。

### 2.1 `host`（对象，`sdk/index.ts:668-1644`）

**只读状态 `host.state.*`**（全部 nanostores 只读 atom，:669-715；React 里用 `useValue(atom)` 订阅，:2089）：

| 键 | 行 | 含义 |
|---|---|---|
| `activeSessionId` | 671 | 活动会话 runtime id（草稿为 null） |
| `awaitingResponse` | 673 | 发送后到首个 assistant payload 之间（聚焦会话） |
| `busy` | 680 | 聚焦会话 turn 进行中（含等待首 token + 流式全程）；跟随 tile 焦点 |
| `busyBySession` | 682 | runtime session id → 是否 mid-turn 的 map |
| `connectionId` | 684 | 活动网关所属的 registry source |
| `cwd` | 686 | 活动工作区 cwd |
| `focusedSessionId` | 690 | **聚焦**会话的 runtime id（交互 tile 优先于主视图） |
| `focusedSessionOwner` | 693 | `{connectionId, profile}` 连接限定属主 |
| `focusedSessionProfile` | 697 | 聚焦会话的 profile（兼容投影） |
| `focusedStoredSessionId` | 700 | 聚焦会话的持久 id |
| `focusedUsage` | 706 | 聚焦会话实时 usage（`UsageStats`：context_used/max/percent、tokens、cost_usd） |
| `gateway` | 708 | 网关 socket 状态（'idle'/'connecting'/'open'/…），非 turn-busy |
| `model` | 710 | 当前主模型 slug |
| `profile` | 712 | 活动网关路由到的 profile |
| `viewport` | 714 | 窗口几何 `{width,height,narrow}` |

**动作/门**：

| API | 行 | 用途/签名 |
|---|---|---|
| `host.settings` | 718, `sdk/settings.ts:47-86` | 白名单桌面外观偏好 get/set：`backdrop.v1`、`composerPopoutGesturesEnabled`、`intro-splash.v1`、`reasoning.collapsedByDefault`、`sessionListDensity`、`tabStripDefault` |
| `host.notify` / `notifyError` | 721-722 | app 内 toast（复用 `store/notifications`） |
| `host.logs(...)` | 729 | tail app 日志（agent/errors/gateway/gui/…） |
| `host.completeMcpOAuth(opt)` | 733-750 | 为 pinned bot profile 完成 MCP OAuth（可先装 catalog 条目） |
| `host.navigate(path)` | 753-764 | 跳 hash 路由 |
| `host.warmProfile(profile)` | 778-786 | 后台预热 profile 网关（池上限保护） |
| `host.deleteProfile(name\|route)` | 798-878 | 走 Electron teardown 的删 profile |
| `host.activeConnectionId()` | 889 | 当前 RPC 命中的 registry 连接 id |
| `host.connections()` | 893-904 | registry 连接列表（不含 token） |
| `host.agents()` | 910-918 | 跨源 agent 花名册（Bot Mode 门） |
| `host.warmAgent(connId, profile)` | 926-928 | 按 (source, profile) 预热 |
| `host.ensureAgent(connId, profile)` | 936-937 | 激活 agent 网关 |
| `host.sessions` | 940, `sdk/sessions.ts:40-77` | `pin/unpin`、`reorder`、`reorderPinned`、`setColor`（写 app 自己的 store） |
| `host.skills` / `host.toolsets` / `host.profiles` | 944-947, `sdk/bridge.ts:28-56` | list/setEnabled（与 Capabilities 页同门）；`host.pluginDecisions`（:58+）**只读**插件开关表 |
| `host.openSession(storedId, opts)` | 956-1291 | 以核心同款方式打开持久会话（opts :383-422：awaitHydration/expectHistory/forceResume/refreshInPlace/profile/route/workspaceMode/tabTitle/…） |
| `host.openWorkspace(id, {render, dock, title, onClose, ...})` | 1304-1354 | 开插件自己的主区 tab/pane；返回关闭 disposer |
| `host.setWorkspaceOwnerLabel` / `setWorkspaceScope` | 1359, 1362-1366 | workspace 归属标签/切换可见主 pane |
| `host.newChat(profile?, opts?)` | 1371-1401 | 新草稿（可指向别的 profile） |
| `host.focusOpenWorkspaceSession(owner, isStaleTile?, onlyIds?)` | 1416-1420 | 前置 Bot owner 已开的 tab |
| `host.paneVisibility(paneId)` | 1428 | pane 可见性只读 atom |
| `host.undismissPane` / `revealPane` | 1437-1457 | 恢复/显现贡献 pane |
| `host.onEvent(type\|'*', listener)` | 1466, `contrib/events.ts:31-47` | 听网关事件流；返回 disposer；register 期间的订阅随插件卸载 |
| `host.restartGateway()` | 1469 | 重启后端网关 |
| `host.status()` | 1472 | 一次性系统状态快照 |
| `host.profileRoutes()` | 1476-1494 | 免凭据路由描述符（connectionId+profile+targetProfile） |
| `host.requestProfile(route, method, params, timeoutMs?, opts?)` | 1512-1518 | 经路由描述符的网关 JSON-RPC（不前台化；`spawnPriority` 可抢交互槽） |
| `host.retainProfileSocket(route)` | 1526-1533 | 钉住路由 socket（多次 requestProfile 复用） |
| `host.retainProfile(route, opts?)` | 1543-1556 | 会话级多 RPC 序列持锁 |
| `host.listPersistedSessions(route, {profile, limit})` | 1560-1590 | 从源主 primary 直接读 state.db 持久会话（REST `/api/profiles/sessions`） |
| `host.setPersistedSessionHidden(route, {...})` | 1595-1615 | PATCH 持久会话 hidden |
| `host.request(method, params, timeoutMs?)` | 1621-1629 | **活动**网关的 JSON-RPC（session/config/skills/cron/kanban 全量方法面） |
| `host.getGateway()` | 1636 | 活动 `HermesGateway` 实例（给要 prop 的组件） |
| `host.composer` | 1638, `sdk/composer.ts:65+` | `getDraft/setDraft/insertText/submit/focus`（按 session 地址 fail-closed 路由到主 composer 或 tile） |
| `host.i18n` | 1643, `sdk/i18n.ts` | `registerAppLocale(id, {endonym, rtl?, translations})` 运行时加语言；`languageOptions()` |

### 2.2 UI / 工具导出（节选，均有 : 行号）

- 组件：`CapabilitiesView:1657`、`ConnectorsTab:1666`、`SessionStatusDot:1686`、`SidebarRowLead:1691`、`ConnectionGlyph:1695`、`Panel* 全家 :1717-1734`、`ListRow/ToggleRow:1756`、`ToolsetConfigPanel:1761`、`ModelCatalogMenu:1768`、`MessageTextContent:1790`、基础件 `Button/Badge/Dialog/ContextMenu/DropdownMenu/Popover/Select/Switch/Tabs/TabsList/Tooltip/ScrollArea/Skeleton/ConfirmDialog/EmptyState/…:1801-1874`、`SandboxedFrame:1864`（外链内容的唯一许可原语）、`LogView:1855`。
- React/状态：`useValue:2089`（nanostores-react useStore 别名）、`useQuery/useMutation/useQueryClient:2093`（与 app 共用一个 QueryClient）、`atom/computed:2100`、`queryClient:1974`、`Contribute:1891`。
- 主题/色：`useTheme:2054`、`requestTheme:2059`、`retintTheme/themeHue:2060`、`$accentOverride/setAccentOverride:2036`、OKLCH 数学 :2041-2051、`profileColor* :1970`。
- 工具：`icons:1948`、`haptic:1945`、`createBudgetedLoop:1930`（rAF 动画预算，禁用插件 0 帧）、`LruCache:1958`、`cn:2012`、时间格式化 :2004、`isSubmitEnter:1952`、`compactNumber:2072`、`Streamdown:2103`、`Blobatar:2096-2097`、`reasoningEffort* :2079-2084`、`APPROVAL_RESPOND_TIMEOUT_MS:2076`（=后端 300s）。
- 类型：`GatewayEvent as RpcEvent:2065`、`SessionListRow/ProfileSessionPreview:2069`、`HermesGateway:1898`、`Contribution:1895`、`HermesPlugin/PluginContext/PluginOs/PluginStorage/PluginRestOptions/PluginNativeNotificationInput:1876-1885`、`StatusbarItem:1785`、`TitlebarTool:1786`。

### 2.3 `ctx`（PluginContext，`contrib/plugin.ts:76-126`）

| 成员 | 行 | 说明 |
|---|---|---|
| `ctx.source` | 78 | `'plugin:<id>'`（自动盖章） |
| `ctx.register(c)` / `registerMany(cs)` | 80-82 | 注册贡献（id 命名空间化）；返回 disposer |
| `ctx.onDispose(fn)` | 85 | 卸载/禁用/重载时执行的任意清理 |
| `ctx.onEvent(type, listener)` | 92 | 同 host.onEvent，但**始终**被追踪（register 之后订阅也不会泄漏） |
| `ctx.setTimeout/setInterval` | 97-98 | 作用域定时器，随插件卸载清理 |
| `ctx.addEventListener(target, ...)` | 101-106 | 作用域 DOM 监听 |
| `ctx.rest(path, opts?)` | 111 | REST 到 `/api/plugins/<id>/...`（见 §6 桥） |
| `ctx.socket(path, onMessage)` | 116 | `/api/plugins/<id>/...` 的 WS（自动重连、JSON 帧；OAuth remote 上 no-op） |
| `ctx.os` | 120 | 系统门（见 §9） |
| `ctx.storage` | 122 | `get/set/remove`，localStorage 键 `hermes.plugin.<id>.`（:34-38, 143-163），**明文 JSON** |
| `ctx.i18n` | 125 | 插件自有 locale 包 |

`HermesPlugin` 契约（:128-141）：`{ id, name?, description?, defaultEnabled?, register(ctx) }`。

---

## 3. 插件可见状态（审计问题 3）

**全部确认存在**，均来自 `host.state`（`sdk/index.ts`）：

| 状态 | 是否存在 | 定义 | 更新时机 |
|---|---|---|---|
| `focusedSessionId` | ✅ :690 | 聚焦会话 **runtime id**（`$focusedRuntimeId`）；交互中的 tile 优先于主视图 | tab/tile 切换、会话 open/resume |
| `focusedStoredSessionId` | ✅ :700 | 聚焦会话**持久 id**（`store/session-focus`），重载后仍有效 | 同上 |
| `focusedUsage` | ✅ :347, :706 | `$focusedSessionState.usage ?? null`；即 `UsageStats`（`types/hermes.ts:856-873`） | 见 §5 |
| `busy` | ✅ :680 | `$focusedBusy`（:139）：聚焦视图的 turn 标志；草稿/主视图回落全局 flag，tile 聚焦时读 tile 自己的 slice（`focusedTurnFlag:129-144`） | 发送 → turn 结束 |
| `awaitingResponse` | ✅ :673 | 发送后到首个 assistant payload（`$focusedAwaitingResponse:141`） | 同上 |
| `busyBySession` | ✅ :682, :236-244 | 由 `$sessionStates`（每个 runtime 会话的 live slice）投影的 id→bool map | 任意会话 turn 状态变化 |
| `model` | ✅ :710 | `$currentModel`（主模型 slug） | 模型切换 RPC/事件 |
| `profile` | ✅ :712 | `$activeGatewayProfile`（活动网关路由的 profile） | profile 切换 |

额外语义：`busy`/`awaitingResponse` 是「跟随用户视线」的（statusbar busy 脉冲同源）；要监控**后台**会话用 `busyBySession` 或逐 tile 的 `$sessionStates`（未直接导出，但 `host.onEvent('*')` 可自行维护）。

---

## 4. Gateway/Session 事件（审计问题 4）

插件经 `ctx.onEvent` / `host.onEvent(type|'*')` 收到**全部**网关事件（`contrib/events.ts:49-64` 在 app 分发前 fan-out；监听器隔离，抛错只记日志）。事件 envelope：`{ type, payload?, session_id?, profile?, connectionId?, seq?, replayed?, replayEpoch? }`（`apps/shared/src/gateway-events.ts:36-54`）。

### 4.1 后端事件全集（`apps/shared/src/gateway-contract.generated.ts:5685-5836`，由 Python `tui_gateway/contracts` 生成）

对 whale widget 最相关的（payload 类型行号同文件）：

| 事件 | payload | 说明 |
|---|---|---|
| `message.start` | `{}`（:5733） | turn 开始流式 |
| `message.delta` | `StreamDeltaPayload {text, rendered?, verbose?}`（:4544） | 流式回复块 |
| `message.complete` | `MessageCompletePayload`（:4555-4571）：`text?/usage?/status?('complete'|'error'|'interrupted')/reasoning?/warning?/error?/failure_reason?/partial?/persisted_turn?/billing?...` | **turn 结束 + 权威 usage** |
| `tool.start` | `ToolStartPayload {tool_id, name, args?, args_text?, preview?, labels?}`（:4624） | 工具开始 |
| `tool.complete` | `ToolCompletePayload {tool_id, name, duration_s?, result?, summary?, result_text?, inline_diff?, todos?...}`（:4634） | 工具结束 |
| `tool.generating` | `{name}`（:4648） | 模型正在产出工具参数 |
| `session.usage` | `{usage: Usage}`（:4607） | **turn 中每 1s 的 usage 心跳**（§5） |
| `session.info` | `SessionLiveInfo`（:5783） | 会话实时快照（模型/provider/approval mode 等） |
| `session.title` / `session.reclaimed` / `session.resume_progress` / `session.control.update` | :5789/:5785/:5787/:5781 | 自动命名 / 后端回收会话 / resume 进度 / goal-loop-heartbeat |
| `error` | `{message}`（:4536） | turn 外的会话级失败 |
| `notice` / `notification.show` / `notification.clear` / `status.update` | :4540/:5747/:5745/:5799 | 能力刷新提示 / 键控 OOB 通知 / 瞬态状态行（compacting/goal/loop/…） |
| `subagent.start/progress/tool/complete/thinking` | :5807/:5803/:5811/:5801/:5809 | 子代理生命周期 |
| `todo.updated` | `{todos, revision}`（:4660） | todo 快照 |
| `voice.status/voice.transcript/voice.interrupted/wake.detected` | :5831/:5833/:5829/:5835 | 语音 |
| `reasoning.delta/.available`、`thinking.delta` | `StreamDeltaPayload` :5775/:5773/:5815 | 思维流 |
| `approval.cancelled` | :5689 | 待审批被中断（以 deny 收场） |
| `tool.output_risk` | `{tool_id, name, risk, findings, redacted}`（:4652） | 注入/泄密风险 |
| `sessions.changed` / `cron.changed` / `pairing.changed` / `platforms.changed` / `projects.changed` | ChangeSignal :5793 等 | 对应 db/文件变更 → 客户端 refetch |
| `gateway.ready` | :5721 | 首帧：skin + replay epoch |
| 其他 | `agent.terminal.output`、`terminal.close`、`background.complete`、`btw.complete`、`browser.progress`、`browser.controller.*`、`connection.request/.update`、`display.*`、`layout.apply`、`moa.*`、`pet.*`、`preview.open/.close/.restart.*`、`review.summary`、`setup.ready`、`skin.changed`、`tip.show`、`billing.step_up.verification`、`bot_relay.outbox.pending`、`message.reaction/.interim`、`reaction`、`message.interim`、`pane.reveal` | 完整清单见 :5685-5836 |

### 4.2 问题/审批不是事件——是服务端→客户端 JSON-RPC 请求

`ServerRequestMap`（:5639-5666）：`approval`（危险命令审批，超时 300s）、`clarify`（1-5 个提问）、`secret`（遮蔽 env var）、`sudo`、`display.install.sudo`、`vault.code / vault.save_login / vault.unlock_prompt`、`window.read`、`preview.act/read`、`terminal.read`、`tour`。这些经 app 内置 UI 处理；插件只能通过 `approval.cancelled` 等事件间接感知，**不能**代答审批（SDK 未暴露 approval.respond）。

### 4.3 断线/传输层（客户端本地合成事件）

`apps/shared/src/gateway-events.ts:23-29`：`gateway.reconnecting {attempt, delay_ms}`、`gateway.stderr {line}`、`gateway.start_timeout`、`gateway.protocol_error`、`dashboard.new_session_requested`。socket 状态还可直接读 `host.state.gateway`（:708；`store/gateway.ts:649,676`）。

---

## 5. Usage 数据源（审计问题 5）

### 5.1 实时链路（插件主通道）

1. **后端构造**：`tui_gateway/server.py:2178-2223 _get_usage(agent)` — 从 agent 对象的内存计数器取数：`session_input_tokens/session_output_tokens/session_reasoning_tokens/session_total_tokens/session_api_calls`（prompt/completion 别名回落），加上 `context_usage_fields(comp)`（context_used/max/percent/source/estimated）、`compressions`、`cache_hit_pct`（cache_read/prompt）、`avg_latency_s/avg_tps`（`conversation_loop` 维护的最近 10 次 API 延迟/输出 deque）、`active_subagents`、dev 模式下的 credits。
2. **turn 中推送**：`server.py:3451-3475 _start_usage_ticker` — turn 运行期间**每 1s** emit `session.usage {usage}`（计数冻结时去重不重绘；`message.complete` 前必须停表，晚到 tick 会回滚最终值）。
3. **turn 终值**：`message.complete` 携带 `usage`（`server.py:2393`，`_session_usage_snapshot:2274-2279` 从 agent 或 metadata mirror 取）。
4. **桌面入库**：`app/session/hooks/use-message-stream/gateway-event/session-info.ts:506-521` — `session.usage` 更新 per-session slice（`updateSessionState`）+ 活动会话全局 `setCurrentUsage`；`host.state.focusedUsage` 即读聚焦 slice（`sdk/index.ts:347`）。
5. **任意会话拉取**：RPC `session.usage`（`app/session/hooks/use-session-actions/index.ts:1668`）与账单两栏图 `usage.bars`（`tui_gateway/methods_session.py:1861`；`server.py:177` 列入方法白名单）。插件可直接 `host.request('session.usage', {session_id})`（未验证参数形状，建议先 `host.onEvent('*')` 观察）。

### 5.2 持久层（state.db，schema 全部来自源码 DDL）

- **`sessions` 表**（`hermes_state_common.py:380-431`）：`model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, api_call_count, billing_provider, billing_base_url, billing_mode, estimated_cost_usd, actual_cost_usd, cost_status, cost_source, pricing_version, message_count, tool_call_count, started_at, ended_at, cwd, profile_name, ...`
- **`session_model_usage` 表**（:487-508）：按 `(session_id, model, billing_provider, billing_base_url, billing_mode, task)` 六键 upsert 的**按模型/任务归因**用量行（含上述 token 列 + 成本 + first_seen/last_seen）；`task` 维度区分主循环与辅助调用（vision/compression 等）。
- **写入器**：`hermes_state_usage.py:38-68` — 合并后台 token 写线程（`queue_token_counts:107+`；CLI 每调用 delta 模式 vs 网关累计 absolute 模式，:27-35），计费路由列 COALESCE 填充。库文件：`<HERMES_HOME>/state.db`（及各 profile 自己的库）。本审计未触碰 db（schema 自源码读取，无需打开）。
- **聚合 REST**：`GET /api/analytics/usage?days=&profile=`（`hermes_cli/web_routers/analytics.py:144-154`，`_get_usage_analytics:79-142`，辅助用量从 session_model_usage 折入 :111-115）、`GET /api/analytics/models:306`。桌面插件可用 `host.request`（JSON-RPC）或 `ctx.rest` 走不到这些核心路由——核心 REST 需用 `hermesApi`/`host.listPersistedSessions` 之类的门（注意 `ctx.rest` 被硬限制在 `/api/plugins/<id>/` 命名空间，`api/plugins.ts:56-64` 有 `..` 穿越防护）。

### 5.3 结论

usage 事件总线**存在**（`session.usage` 心跳 + `message.complete` 终值），无需读 db 即可驱动实时 widget；跨会话/跨 profile 的历史聚合用 `/api/analytics/*` REST 或直接（只读）查询 `state.db` 的 `sessions`/`session_model_usage`。

---

## 6. Dashboard Plugin / Python 后端（审计问题 6）

### 6.1 机制：没有独立进程

Python 后端**不是**为插件单独拉起的进程。每个 profile 的后端是 Electron spawn 的 `hermes serve --host 127.0.0.1 --port 0`（`apps/desktop/electron/backend-command.ts:3-26`），这一个 Python 进程内同时跑：
- `tui_gateway`（WS JSON-RPC，事件流 §4）；
- FastAPI web server（`hermes_cli/web_server.py`），启动时执行 `_mount_plugin_api_routes()`（`hermes_cli/web_server_dashboard.py:805-905`）。

`_mount_plugin_api_routes`：扫描 `<plugins root>/*/dashboard/manifest.json`（:548-580 `_discover_dashboard_plugins`；搜索根含 user/bundled/project，:464-505）→ 校验 manifest `api` 字段必须在 dashboard 目录内（:439-462，防绝对路径 RCE）→ `importlib` 导入该 Python 模块 → 取模块级 `router`（FastAPI APIRouter）→ `app.include_router(router, prefix=f"/api/plugins/{name}", dependencies=[Depends(_plugin_route_secret_scope)])`（:869-875）。**信任门**（:775-802）：user 源必须在 `config.yaml` 的 `plugins.enabled` 白名单里（GHSA-mcfc-hp25-cjv7）；bundled 可显式禁用；project 源（`./.hermes/plugins`）永不自动导入（GHSA-5qr3-c538-wm9j）。插件被禁用后路由仍在直到重启（:648-649），每次请求再查一次开关（:649 描述）。

### 6.2 manifest.json 字段（实例：ai-usage-tracker）

```json
{ "name": "ai-usage-tracker", "label": "AI Usage Tracker",
  "description": "...", "icon": "Graph", "version": "1.0.2", "api": "plugin_api.py" }
```
`api` 指向 dashboard 目录内一个导出 `router` 的 Python 模块。`plugin_api.py` 示例（`D:\hermes\plugins\ai-usage-tracker\dashboard\plugin_api.py:31-34, 709-741`）：`router = APIRouter()` + `@router.get("/usage")` / `/profiles` / `/health`。

### 6.3 JS ↔ Python 桥

1. 插件 JS 调 `ctx.rest('/usage?profile=x')` → `pluginRest`（`apps/desktop/src/api/plugins.ts:72-87`）拼出 `/api/plugins/<id>/usage`，经 `hermesApi`；
2. `hermesApi` → `window.hermesDesktop.api(request)` → **IPC `hermes:api`**（`electron/preload.ts:342`）→ **Electron main 进程**发 HTTP 到该 profile 后端的 `127.0.0.1:<port>`；
3. FastAPI 在 `hermes serve` 进程内命中插件 router；`?profile=` 查询参数经 `_plugin_route_secret_scope`（`web_server_dashboard.py:791-803`）把请求放进目标 profile 的 HERMES_HOME/secret scope。
4. WS：`ctx.socket` → `pluginSocket`（`api/plugins.ts:95-147`）直接从渲染进程连 `ws://<backend>/api/plugins/<id>/...?token=<session token>`（token 模式；OAuth cookie 模式下解析 null，要求插件保留轮询 fallback）；指数退避重连。
5. 鉴权：REST 用 `X-Hermes-Session-Token` 头，WS 用 `?token=`（`electron/connection-config.ts:16-21`）；连接描述符/token 由 Electron main 持有，渲染进程不接触原始凭据。

**结论**：统一包（agent+dashboard+desktop 三件套）才有 Python 后端；纯 `desktop-plugins/<id>/plugin.js` 的 `ctx.rest` 会 404。JS↔Python 的桥 = 「渲染进程 → IPC → Electron main → localhost HTTP/WS → `hermes serve` 进程内 FastAPI router」。

### 6.4 `window.__HERMES_PLUGIN_SDK__`

**不是** Electron 桥（那是 `window.hermesDesktop`，preload 暴露，见 §9）。`__HERMES_PLUGIN_SDK__` 是 runtime 插件的 SDK 注入全局：`sdk/runtime.ts:26-39 installPluginSdk()` 把整个 `@hermes/plugin-sdk` 命名空间 assign 到 globalThis，加载器把插件代码里的 `import ... from '@hermes/plugin-sdk'` 改写成从该全局重导出的 shim blob（`runtime.ts:43-70`）。同族全局：`__HERMES_REACT__`、`__HERMES_REACT_JSX__`、`__HERMES_REACT_JSX_DEV__`。

---

## 7. Unified Package（审计问题 7）

### 7.1 组成

`<HERMES_HOME>/plugins/<name>/` 一个目录三半体：
- **agent 半体**：`plugin.yaml`（name/version/description）+ Python（`__init__.py`、hooks/tools，跑在该 profile 网关进程里，经 `PluginManager` 发现）；
- **dashboard 半体**：`dashboard/manifest.json` + `dashboard/plugin_api.py`（§6）；
- **desktop 半体**：`desktop/plugin.js`（§1）；
- （上游开发时）`catalog/<name>.yaml`：提交到 `NousResearch/hermes-agent` plugin-catalog 的 PR sidecar，随包携带便于开 PR（本机 ai-usage-tracker 即此形态）。

### 7.2 `catalog/<name>.yaml` 字段（`hermes_cli/plugin_catalog.py:76-116` + 本机实例）

`name`（catalog 键）、`repo`（https git URL，**强制**）、`sha`（40 hex 精确 pin，**强制**，:135-148 校验）、`description`、`maintainer`、`tier`（curated/community）、`requires_hermes`、`platforms`、`docs_url`、`capabilities`（`provides_tools/hooks/middleware`、`requires_env`，须与实际注册一致——admission 规则 6，`plugin-catalog/README.md`）、可选 `version/image(GitHub 域)/screenshots/subdir/known_issues`。在库目录内**存在即信任信号**（人工合并 PR、SHA pin、禁止自更新代码，README 准入规则 1-6）。

### 7.3 安装/更新

- `hermes plugins install <name>`：catalog 命中则克隆 repo 并 checkout **恰好**该 sha → 静态扫描 → 原子发布到 `plugins/<name>` → 写 `.hermes-catalog.json` sidecar（记录 `sha`=实际 checkout、`pin`=评审 sha）（`hermes_cli/plugins_cmd_install.py:310-438`）。
- 更新：catalog 安装**只经 SHA-bump**（新 PR 重评审）；非 catalog 的 git 插件走 `git pull`（pinned checkout 拒绝 pull）（`plugins_cmd_update.py:70-92`，`_reclone_plugin_update:50`）。Dashboard 侧更新同核心（:275-276）。
- **桌面半体物化**：Electron 每次启动 reconcile 所有本地 home 的 `plugins/*/desktop/plugin.js`，staging 复制到 `desktop-plugins/<name>/` 并写 `.hermes-package.json`（`desktop-plugins-root.ts:171-246` `materializeDesktopHalf`；staging+rename 原子发布 :249-270；源 mtime 新则重复制；源消失则删除半体 :301+）。标记里的 `repo/sha/catalogName` 来自 sidecar 或 git remote（:41-77）。本机实证：`D:\hermes\desktop-plugins\ai-usage-tracker\.hermes-package.json`（sha `14e844f6…`，比 catalog PR 草稿里的 `98010ea…` 新）。
- 桌面半体默认 opt-in（marker ⇒ `defaultEnabled:false`，§1.2）。

---

## 8. 凭据/密钥存储（审计问题 8）

| 层 | 机制 | 证据 |
|---|---|---|
| 后端（agent/serve 进程） | **secret_sources 框架**：启动时从外部密钥管理器（**Bitwarden**、**1Password**、通用 **Command**）解析凭据进 env；只读、同步、启动时一次、超时/不抛错 | `agent/secret_sources/base.py:17-34`、`registry.py:36-50`（`_BUILTIN_SOURCES:41-47`）、`SECRET_SOURCE_API_VERSION=1`（base.py:34） |
| 插件扩展点 | **agent 插件**可通过 `PluginContext.register_secret_source()` 注册自定义源 | `agent/secret_sources/registry.py:27-29` |
| 读取 | `agent.secret_scope.get_secret(name)`；profile 作用域（跨 profile 未作用域读取抛 `UnscopedSecretError`） | `hermes_cli/config.py:1583-1594, 2882-2887`；`web_server_dashboard.py:791-803`（/api/plugins/* 每 profile scope） |
| 桌面 Electron | 远程网关 token 用 **safeStorage** 加密存储（`encoding: 'safeStorage'` 信封） | `apps/desktop/electron/connection-config.ts:355-394` |
| 会话级 | 服务端→客户端 `secret` 请求（遮蔽 env var 读取）、`vault.code/save_login/unlock_prompt`（OTP/保存登录/解锁外部密码管理器） | `gateway-contract.generated.ts:5651, 5658-5663` |
| **桌面插件** | **无**官方凭据 API：`ctx.storage` 是 localStorage 明文（`contrib/plugin.ts:143-163`）；`ctx.os` 无 keychain；`window.hermesDesktop` 未暴露 safeStorage 给渲染层 | 同前 |

**结论**：凭据机制存在且成体系，但**对 desktop plugin 不开放**。桌面插件要拿密钥，现实路径是把自己的 Python 半体（plugin_api.py）当代理，用 `get_secret`/env 解析后只回传非敏感结果（ai-usage-tracker 即此模式：「Secrets are resolved in-process and never serialized」，其 plugin_api.py 模块 docstring）。

---

## 9. 系统能力（审计问题 9）

### 9.1 `ctx.os`（`contrib/plugin.ts:45-68`，实现 :168-216）——全部系统能力

| 成员 | 说明 |
|---|---|
| `os.notify(input)` | **系统级**原生通知（Electron Notification）：`icon`、`activate`（深链如 `hermes://...`）、`actions[{id,label,onAction}]`、`onActivate`、`silent`。受 Settings▸Notifications▸"Plugin notifications" 门控，**仅用户离开 Hermes 时**触发；按插件节流（:46-53；分发 `store/native-notifications.ts:346-370`） |
| `os.openExternal(url)` | OS 默认处理器打开 URL；不可用 resolve false |
| `os.revealPath(path)` | 文件管理器中显示 |
| `os.pickSavePath/pickOpenPath(opts?)` | 原生文件对话框（filters/title/defaultPath）；路径在**后端**文件系统语义上（交给 rest 用） |
| `os.writeClipboard(text)` | 写系统剪贴板 |

每个成员 fail-open 为 false/null（桥缺失或旧 shell 时），永不抛（:165-196）。

### 9.2 明确缺失的能力

- **任意文件读写**：无（只有用户经对话框选的路径 + Electron 内部读插件源码的 IPC；插件要读文件须通过自己后端的 REST 或 `host.request` 的 files 路由）。
- **子进程**：`preload.ts` 无任何 spawn/exec 通道（grep 确认）；desktop plugin 不能启动进程。
- **新窗口**：**不能**。`window.open`/`target=_blank` 在 main 进程被**全量 deny**（`electron/window-open-policy.ts:1-30`，GHSA-9f4c-93c8-jc8g/CVE-2026-70608 姿态；唯一例外是固定 origin 的 Skills Hub 文档链接走 `openExternal`，且从不创建窗口）。preload 无 `createWindow`/`openWindow` IPC。app 内部的透明窗口（HUD、pet overlay、quick entry、wake indicator，`electron/main.ts:1506-1509`）与玻璃态（Windows `setBackgroundMaterial`/macOS `setVibrancy`，`main.ts:1587-1625`）均为核心专用，未对插件暴露。
- 最接近「悬浮窗」的替代：pane placement `'floating'`——app 内固定、可拖拽、不占布局宽度的浮卡（`sdk/index.ts:1794-1799` + `host.openWorkspace`）。
- `window.hermesDesktop`（preload，:28-560+）还有插件**不经 SDK 也能**摸到的门（信任模型下无强制）：`api`（REST 代理）、`getConnection/getProfileRoutes/getAgentRoster`、`connections.*`、`readFileText/readPluginSource/readDir`、`selectPaths/selectSavePath`、`writeClipboard`、`openExternal`、`revealPath`、`watchPreviewFile/watchDirectory`、`desktopPluginsRoot`、`removeDesktopPlugin`、`onNotificationAction/onNotificationActivate` 等——但这属于「完整 app 权限」，非受支持插件面。

---

## 10. App 生命周期与插件清理（审计问题 10）

- **启用状态**：`localStorage['hermes.desktop.pluginDecisions.v2']`（id→bool；缺省回落插件 `defaultEnabled`，统一包半体被根级 cap 为 opt-in）（`contrib/plugins-store.ts:33-77`；cap 逻辑 `runtime-loader.ts:47-51, 523`）。切换是**实时**的：每条清单记录带 activate/deactivate 句柄，toggle 不需重启（`plugins-store.ts` 头注）。
- **Disable/重载**：`unloadRuntimePlugin`（`runtime-loader.ts:360-378`）先从映射表摘除再逐个跑 disposer（每个独立 try/catch）；会清理：registry 贡献、`ctx.onEvent` 网关订阅（`contrib/events.ts:19-28` 的 tracker）、`ctx` 定时器/DOM 监听、`ctx.socket`、i18n 包。文件保存 → fs-watch → 重载（§1.1）；改了 plugin id 或语法错误 → 旧实例也卸载（:714-717）。
- **ID 冲突**：bundled 赢过磁盘副本（后者以 `id:disk-shadowed` 行可见地跳过，:435-447）；两文件争一 id 先到先得（:449-457）。
- **卸载**：Capabilities▸Plugins 垃圾桶 → Electron `removeDesktopPlugin`（main 进程强制路径包含在 root 内）→ `retireDiskPlugin`（:930-953, 908-923）；统一包半体由 agent 侧卸载联动回收（§7.3）。
- **App 退出**：桌面插件与渲染进程同生命周期——**退出时不执行 ctx disposer**（没有 before-quit 插件清理钩子；进程消失即一切消失）。Electron main 的退出序列只处理自身事务：`before-quit` flush 设置写盘、`will-quit` 杀 git 子进程/keepalive/通知/`quitFinalization.arm`（`electron/main.ts:18215-18230`）、各 profile 后端进程随主进程 teardown（backend-exit/backstop 系列，未逐行验证）。

---

## 11. App 主体技术栈（审计问题 11）

| 项 | 事实 | 证据 |
|---|---|---|
| 壳 | **Electron 40.10.2**（非 Tauri）+ electron-builder/electron-updater（MSIX/Store 分发，Windows/macOS/Linux） | `apps/desktop/package.json:186,123`；`BUILDING.md:10-19` |
| 渲染层构建 | **Vite 8.2.0** + TypeScript 6.0.3；Electron main 由 esbuild 0.28.1 打包 | `package.json:186-194`；`scripts/bundle-electron-main.mjs` |
| 前端框架 | **React 19.2.7** + react-router 8.3.0；Tailwind 4；@assistant-ui/react、streamdown | `package.json:140-144` 等 |
| 状态管理 | **nanostores 1.4.2 + @nanostores/react**（不是 jotai——atom/computed/useStore 同源 API 但不同库）+ @tanstack/react-query 5.101.2（单一 QueryClient） | `package.json:97,135,105` |
| 后端 | 每 profile 一个 **Python `hermes serve`**（FastAPI + tui_gateway WS JSON-RPC），headless 127.0.0.1 随机端口；GUI↔后端合同版本 `DESKTOP_BACKEND_CONTRACT = 8` | `backend-command.ts:20-26`；`tui_gateway/server.py:2270` |
| 渲染层→后端 | REST 经 IPC `hermes:api` 由 main 进程代理；事件经网关 WS（带 replay epoch/seq） | `preload.ts:342`；`gateway-events.ts:36-54` |

**插件能触碰的边界**：渲染进程内的 React 树贡献 + 经 SDK/IPC 门到后端的 RPC/REST/WS + `ctx.os` 六件事 + localStorage。进程边界（子进程、新窗口、任意 FS、凭据）默认不可越——但信任模型下插件**技术上**拥有渲染进程全权（§1.5），边界是约定与 lint 而非隔离。

---

## 12. 对 whale widget 的可行性影响速记

**确认存在、可直接用**
- **usage 实时流**：`ctx.onEvent('session.usage')`（1s 心跳）+ `'message.complete'`（终值含 cost）+ `host.state.focusedUsage/busyBySession/model/profile`——单窗口挂件的数据面完全够；历史聚合走 `/api/analytics/usage`（需经 `hermesApi` 门而非 ctx.rest）或只读查询 state.db 的 `sessions`/`session_model_usage`（§5）。
- **存储**：`ctx.storage`（localStorage，`hermes.plugin.<id>.` 命名空间）可存布局/阈值/静音偏好；**明文**，勿放密钥。
- **通知**：`host.notify`（app 内 toast，随时）+ `ctx.os.notify`（系统原生，仅用户离开时+设置门控）。
- **事件全景**：`ctx.onEvent('*')` 可见 tool.start/complete、subagent、voice、error、断线（`gateway.reconnecting` 合成事件）—— whale 的「拖船动画」触发器齐全。
- **UI 注入**：`STATUSBAR_AREAS.right` 芯片 + `ROUTES_AREA`/`SIDEBAR_NAV_AREA` 页面是 ai-usage-tracker 已验证的成熟组合；`host.openWorkspace` 可开主区 tab；pane `'floating'` 可做 app 内悬浮卡。
- **热重载**：保存 `desktop-plugins/whale-widget/plugin.js` 即生效，开发体验好。

**确认缺失（需绕行或放弃）**
- **独立/透明/置顶窗口：无 API**。`window.open` 全量 deny、preload 无建窗 IPC、透明窗口（HUD/pet）为核心专用。whale 若必须是 OS 级独立透明挂件，desktop plugin 体系做不到；替代：(a) app 内 floating pane；(b) 核心改造（不可行于插件层）；(c) 独立 Electron/Tauri 进程自读 `state.db` + 旁路订阅（脱离 Hermes 插件体系，未验证网关 WS 能否被第三方客户端复用）。
- **子进程/任意文件/OS 凭据**：无。透明度设置、AlwaysOnTop 等系统级效果对插件关闭。

**待定/注意**
- 统一包 Python 半体可作数据代理（如读 `state.db` 聚合、调 provider 配额 API），但要求用户安装 agent 半体并加入 `plugins.enabled` 白名单，且每个 profile 的 serve 进程才挂载（§6 信任门）——纯 widget 尽量不要依赖它。
- `ctx.socket` 在 OAuth 远程后端上不可用（需保留轮询 fallback）；本机 local 模式无碍（未验证本机 auth 模式）。
- `session.usage` 的 `Usage` 载荷字段是**增量出现**的（context_*/cost_usd 可能缺省），读取要带 fallback（`sdk/index.ts:702-706` 注释明示）。
- 插件 id 与 bundled 冲突会被静默遮蔽（清单里出现 disk-shadowed 行）；命名避开 `hermes-bots`/`kanban`/`radio`/`hello-runtime`。
