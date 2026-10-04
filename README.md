# hermes-whale-widget

Hermes 桌面「小鲸鱼记账挂件」：AI 用量记账 + 余额/消费展示 + 桌面角色交互。
参考 [MeteorNOX/DeepSeek-Balance-Whale-Widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget)
的产品体验，但**架构完全按 Hermes 本机版本重新设计**，不做代码移植。

> 核心理念：鲸鱼只是表现层。真正的核心是一个可靠的
> **Hermes AI Usage + Accounting + Notification System**（账本、规则、配额），
> 鲸鱼角色让它直观、有趣、可交互。

## 项目状态

**MVP（M0–M8）代码闭环 + Goal 收尾完成（2026-10-04）**：usage 捕获→幂等账本→计价→余额差分→鲸鱼浮窗显示→单轮消费泡泡→今日消费→提醒（余额/预算/等待/审批观测）全部落地；音效引擎**已接线**（默认关，无素材时天然无声）；`/notifications` 消费链路与 `/wait-state` 真实契约接线修复完成。测试：pytest 184 / node 190 全绿。部署文档 `INSTALL.md` 与流程清单 `docs/plans/USER_FLOW_CHECKLIST.md` 已交付（真机端到端待用户手动部署验证）。
后续：M10 自制素材、M11 多 Provider、M12 设置 UI、M13 打包；未完成项总账见 [`docs/plans/REMAINING_WORK.md`](docs/plans/REMAINING_WORK.md)。

**2026-10-04 追加：宠物宿主化（DR-15）**——宿主角色改为 **Hermes 内置宠物（穿鲸鱼皮肤包）** +
whale 管家面板（floating pane 去角色化，只承载泡泡/数据/提醒/音效）。皮肤包生成器
`tools/build-whale-pet-pack.py`、面板去角色化与文档本轮交付；**真机宠物装载待用户执行**
（[`INSTALL.md`](INSTALL.md) §12）。系统调研与 file:line 证据见
[`docs/research/HERMES_PET_SYSTEM.md`](docs/research/HERMES_PET_SYSTEM.md)。

## 环境事实

| 项 | 值 |
|---|---|
| Hermes 版本 | v0.21.5+6188.g0ff4c74 (2026.9.24)，git 安装 |
| Hermes 源码（只读） | `D:\hermes\hermes-agent` |
| HERMES_HOME（只读） | `D:\hermes` |
| 已装 desktop-plugins（只读参考） | ai-usage-tracker, hermes-paper-reader, hermes-ssh, hermes-vault, prompt-enhancer, prompt-snippets, ssh-plugin |
| 已装插件源码（只读参考） | `D:\hermes\plugins\{ai-usage-tracker, hermes-lcm, hermes-vault, hindsight, prompt-optimizer, ssh-plugin}` |
| 平台 | Windows x64 |
| 项目目录 | `E:\hermes_plugin\hermes-whale-widget`（唯一可写代码区） |

**硬性约束：只修改本项目目录内代码；`D:\hermes` 等外部位置一律只读。**

## 核心目录

```text
docs/
  research/    DEEPSEEK_WHALE_ANALYSIS / HERMES_ARCHITECTURE_AUDIT / REFERENCE_PROJECTS / RESEARCH_LOG / HERMES_PET_SYSTEM
  design/      FEATURE_MATRIX / FEASIBILITY_REPORT / ARCHITECTURE_DECISION / DATA_MODEL
  plans/       IMPLEMENTATION_PLAN / TEST_PLAN / REMAINING_WORK / USER_FLOW_CHECKLIST
  progress/    WORKLOG / CHANGELOG
plugin-src/    插件源码（Milestone 0 建立）
INSTALL.md     安装/启用/凭据/配置项/卸载/回滚指南
references/    参考项目 clone（gitignore）
experiments/   一次性脚本（gitignore）
tools/         开发脚本
```

## 开发与测试

在项目根目录执行（Python 用项目内 `.venv`）：

```text
node tools/build-desktop.mjs                  # 构建 desktop 半体单文件 ESM
npm test                                      # JS 测试（node:test）
.venv/Scripts/python.exe -m pytest plugin-src/hermes-whale-widget/dashboard/tests -q --basetemp=.pytest-tmp
node tools/check-security.mjs                 # 产物级安全自检（必须通过）
.venv/Scripts/python.exe tools/check-security.py   # 全源码安全自检（必须通过）
node tools/dev-preview.mjs                    # SDK shim 预览页（不触碰 Hermes）
```

部署验证受「不改 `D:\hermes`」约束：真机部署需用户手动复制插件目录到
`D:\hermes\plugins\whale-widget\` 并在 `config.yaml` 的 `plugins.enabled` 加名后重启 App
（Python 半体启用需重启；桌面半体在 Plugins 页 opt-in）。

## 功能清单（目标）

记账（usage ledger / 双轨余额观察 / 幂等去重）、余额与今日消费展示、单轮消费、
**宿主角色 = Hermes 内置宠物（鲸鱼皮肤包，DR-15；调研见
[`docs/research/HERMES_PET_SYSTEM.md`](docs/research/HERMES_PET_SYSTEM.md)）** +
whale 管家面板（点击/拖拽/互动）、泡泡消息系统、消费与任务事件提醒、音效、自定义角色图片、
自定义 Provider、Hermes 会话 usage 联动、设置与持久化。完整可行性分级见 `docs/design/FEATURE_MATRIX.md`。

## 已实现 / 未实现 / 已知限制

**已实现（MVP）**：usage 事件捕获与归一化（幂等去重 + 断线重连对齐）、SQLite 账本（幂等落库/水位/归档）、
三级计价（hermes_estimate > 价目表 > 诚实 NULL）、DeepSeek 余额轨②（差分记账/五状态机/显式校正 409/观测缺口 partialDay）、
state.db 只读交叉校验（轨③留桩）、管家面板 floating pane（可拖拽，SDK 原生浮卡；DR-15 去角色化）、
五态情绪状态机（驱动泡泡与面板强调色）、宠物宿主化（DR-15 本轮交付：鲸鱼皮肤包生成器
`tools/build-whale-pet-pack.py` 纯 stdlib + 角色形象由内置宠物承载，真机装载待用户执行）、
泡泡引擎（DSH Row/Module schema 子集 + 加权随机 + avoidIdx + 优先队列）、余额/预算/每轮消费提醒（持久去重，
`/notifications` REST + 桌面轮询消费链路）、question（clarify 工具事件 → `/ingest/wait-event`）与
approval（agent 半体 hook → 状态文件）等待观测（`/wait-state` 真实契约 `{question_slots[], approval_slots[],
fired_dedup_keys[]}` 两端接线）、statusbar 芯片（●/◐/○/◌ 四态）、
Web Audio 音效引擎（DSH 语义：同步起播/衔接排期/音量三态/mute；**已接线，默认关**）。

**未实现**：默认音效与管家面板视觉素材（M10——DR-15 后自建鲸鱼角色素材不再需要，占位 SVG 随
管家面板去角色化移除）、多 Provider 模板（M11，现仅 DeepSeek）、设置 UI（M12，现走 config.json）、
打包发布与 catalog 定稿（M13，`INSTALL.md` 已先行交付）、独立透明窗口（Phase 2 可选——OS 级常驻
角色已由内置宠物窗口承接（DR-15），pywebview 路线降为后备）。

**已知限制**：估算值与真实观测严格分列（UI 带「估算」角标）；DSH 同分钟同内容两轮的残留风险 R2；
余额 API 字段时效未自动探测（模板带 unverified 标注）；未计价轮成本显示「—」绝不按 0 计；
无内置音效素材（`sound.enabled` 开启后素材就位前也无声）；Python 半体启用需重启 App；
宠物泡泡文字为 Hermes core 硬编码短语、插件不可注入（当前以「管家面板 + 宠物」并列摆位呈现；
upstream 提案见 `docs/design/FEASIBILITY_REPORT.md` §3.1）；
真机端到端冒烟（事件 payload 实形状/面板视觉/审批与 clarify 等待链路/宠物皮肤装载）待用户部署验证——
逐条清单见 [`docs/plans/USER_FLOW_CHECKLIST.md`](docs/plans/USER_FLOW_CHECKLIST.md)。

## 参考项目

| 项目 | 用途 |
|---|---|
| MeteorNOX/DeepSeek-Balance-Whale-Widget | 产品体验与六大系统剖析对象 |
| NousResearch/hermes-agent | 本地 `D:\hermes\hermes-agent`，第一事实来源 |
| NousResearch/hermes-example-plugins | 官方插件范式 |
| lvabarajithan/hermes-ai-usage-tracker（本机已装） | usage 截获方式与账本 schema |
| ghoststarz/hermes-pet | 独立透明桌宠进程架构 |
| Icarus-B4/hermes-plugin-avatar_pet | Desktop 内 Canvas/Sprite 路线 |

## 安装 / 卸载 / 回滚 / 数据与配置位置 / 凭据

完整步骤、凭据三方式与全部配置项说明见 **[`INSTALL.md`](INSTALL.md)**。速览：

| 项 | 结论 |
|---|---|
| 安装 | 构建产物 `desktop/plugin.js`（`node tools/build-desktop.mjs`）；**用户手动**复制 `plugin-src/hermes-whale-widget/` → `D:\hermes\plugins\whale-widget\` → `config.yaml` 的 `plugins.enabled` 加 `whale-widget` → 重启 App → Plugins 页 opt-in 桌面半体（本项目约束禁止 agent 代写 `D:\hermes`） |
| 卸载 | Plugins 页禁用 → `plugins.enabled` 移除并重启 → 删插件目录；数据目录默认保留 |
| 回滚 | `git checkout <版本>` → 重新构建复制；schema 迁移自带 `whale.db.bak-<ver>` 备份 |
| 数据与配置位置 | `<HERMES_HOME>/whale-widget/`（whale.db / config.json / credentials.json / approval-state.json / logs）——数据与代码分离，绝不写进插件目录 |
| 凭据 | 三方式按优先级：Hermes secret_scope（env 名 `DEEPSEEK_API_KEY`）→ 进程 env → 数据目录 `credentials.json`（明文兜底，风险已标注）；**绝不把 key 写进 config.json**；REST/日志只暴露指纹 |
| 宠物皮肤（可选，推荐） | 构建 `.venv/Scripts/python.exe tools/build-whale-pet-pack.py` → **用户手动**复制 `assets/whale-pet-pack/` → `D:\hermes\pets\whale\` → 宠物图库选择 whale → 管家面板拖到宠物旁；回退 = 删该目录即恢复默认宠物；也可用内置 `/pet-generate`（提示 "cute pixel whale"）——详见 `INSTALL.md` §12 |
