# RESEARCH_LOG

按时间倒序追加。每条记录：日期、做了什么、关键发现、产出文档。

## 2026-10-03 — 工作区与 Hermes 环境探测（Phase 0）

- 新建项目 `E:\hermes_plugin\hermes-whale-widget`（git init，含 docs 体系）。
- 工作区 `E:\hermes_plugin` 已有项目：astock-quotes、prompt-snippets（均为用户自研 Hermes desktop plugin，bundled plugin.js 形式）、ssh、refs/hermes-vault。未提交修改风险：各项目独立成目录，本项目建设互不干扰。
- **Hermes Agent v0.21.5+6188.g0ff4c74 (2026.9.24)**，安装方式 git，源码在 `D:\hermes\hermes-agent`。
- `D:\hermes\desktop-plugins\` 已安装 7 个插件；`D:\hermes\plugins\` 存放插件源码，结构为
  `catalog/<id>.yaml + dashboard/{manifest.json,plugin_api.py} + desktop/`（Unified Package 结构确认存在）。
- 本机已装 **ai-usage-tracker**（来自 lvabarajithan fork，desktop 端 plugin.js 21KB + dashboard/plugin_api.py）。
- 用户约束追加：**只改工作区代码，Hermes 及其它外部位置一律只读。**
- 下一步：clone 参考仓库到 `references/`，三路并行调研（DSH 剖析 / Hermes 架构审计 / 参考插件）。

## 2026-10-03 — 三路并行调研完成（Phase 1-3）

- **DEEPSEEK_WHALE_ANALYSIS.md**（子代理产出）：DSH 记账内核仅 289 行纯函数可整体移植；余额差分记账（上升额永不冲销消费，显式校正闭环，1e8 定点整数）；按密钥指纹分账本；泡泡 Row/Module schema 完整（choice 加权随机 + avoidIdx 防连续重复）；提醒走页内泡泡优先队列；Web Audio 自研引擎；34 个 provider 模板（20 家 noBalanceApi 显示「—」）；**代码 MIT 但 assets/ 素材不在 MIT 内，不可再分发，鲸鱼图与音效必须自制**；泡泡编辑器约 5700 行建议分四阶段。
- **HERMES_ARCHITECTURE_AUDIT.md**（子代理产出，全程只读 D:\）：usage 实时来源 = `hermes serve` 推 `session.usage`（1s 节流）+ `message.complete`（权威 usage+cost），插件走 `ctx.onEvent` + `host.state.focusedUsage`；持久层 state.db `sessions` + `session_model_usage`（六键幂等 upsert）；**desktop plugin 开独立窗口被主进程全量 deny**（CVE-2026-70608 姿态），app 内透明窗口是核心专用，SDK 最接近的是 `floating` pane；JS↔Python 桥 = plugin_api.py import 进 serve 进程挂 `/api/plugins/<name>/`，JS ctx.rest → IPC → localhost HTTP，ctx.socket 直连 WS（token 鉴权）；**ctx.storage 是明文 localStorage，插件侧无 keychain** → 密钥只能放 Python 半体；`host.state` 含 focusedSessionId/focusedStoredSessionId/focusedUsage/busy/awaitingResponse/busyBySession/model/profile 全部所需字段；~70 种后端事件；**question/approval 不是事件而是 JSON-RPC 请求**，插件不能代答；插件能力面 = notify/openExternal/revealPath/文件对话框/剪贴板/作用域定时器，**无子进程/任意文件 IO/系统凭据**；import 白名单 `@hermes/plugin-sdk` + `react*`，无官方 plugin.js 打包工具（手写单文件 ESM）；catalog yaml 强制 SHA pin。
- **REFERENCE_PROJECTS.md**（子代理产出）：ai-usage-tracker **没有 usage 账本**（纯 quota API 展示，README 自述无 token 计数），结论 = 自建最小账本层、只借其只读 state.db 范式（`file:...?mode=ro` + schema_version 兼容门）；hermes-pet = 独立透明窗口已验证骨架（pywebview/WebView2 + 手动 WS_EX_LAYERED + --disable-gpu + app-online.json 心跳 60s 自退防孤儿），**素材禁商用**；avatar_pet = Desktop 内嵌 Canvas 样板（host.onVoiceEvent/voiceLifecycle + readFileDataUrl 桥）；官方 examples 演示 ctx.llm.complete_structured 等官方范式；窗口路线结论 = Phase 1 走 in-desktop floating pane，Phase 2 可选 Python 半体 spawn 独立透明窗。
- 交叉验证结论一致：**账本双轨（usage ledger + balance observation）+ 凭据隔离在 Python 半体 + Phase 1 in-desktop UI** 的架构方向成立。
