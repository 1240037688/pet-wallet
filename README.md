# hermes-whale-widget

Hermes 桌面「小鲸鱼记账挂件」：AI 用量记账 + 余额/消费展示 + 桌面角色交互。
参考 [MeteorNOX/DeepSeek-Balance-Whale-Widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget)
的产品体验，但**架构完全按 Hermes 本机版本重新设计**，不做代码移植。

> 核心理念：鲸鱼只是表现层。真正的核心是一个可靠的
> **Hermes AI Usage + Accounting + Notification System**（账本、规则、配额），
> 鲸鱼角色让它直观、有趣、可交互。

## 项目状态

**MVP（M0–M8）代码闭环完成（2026-10-04）**：usage 捕获→幂等账本→计价→余额差分→鲸鱼浮窗显示→单轮消费泡泡→今日消费→提醒（余额/预算/等待/审批观测）全部落地；音效引擎核心完成（待接线）。测试：pytest 180 / node 185 全绿。
后续：M9 音效接线、M10 自制素材、M11 多 Provider、M12 设置 UI、M13 打包。

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
  research/    DEEPSEEK_WHALE_ANALYSIS / HERMES_ARCHITECTURE_AUDIT / REFERENCE_PROJECTS / RESEARCH_LOG
  design/      FEATURE_MATRIX / FEASIBILITY_REPORT / ARCHITECTURE_DECISION / DATA_MODEL
  plans/       IMPLEMENTATION_PLAN / TEST_PLAN
  progress/    WORKLOG / CHANGELOG
plugin-src/    插件源码（Milestone 0 建立）
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

记账（usage ledger / 双轨余额观察 / 幂等去重）、余额与今日消费展示、单轮消费、桌面常驻角色
（点击/拖拽/互动）、泡泡消息系统、消费与任务事件提醒、音效、自定义角色图片、自定义 Provider、
Hermes 会话 usage 联动、设置与持久化。完整可行性分级见 `docs/design/FEATURE_MATRIX.md`。

## 已实现 / 未实现 / 已知限制

**已实现（MVP）**：usage 事件捕获与归一化（幂等去重 + 断线重连对齐）、SQLite 账本（幂等落库/水位/归档）、
三级计价（hermes_estimate > 价目表 > 诚实 NULL）、DeepSeek 余额轨②（差分记账/五状态机/显式校正 409/观测缺口 partialDay）、
state.db 只读交叉校验（轨③留桩）、鲸鱼 floating pane（可拖拽，SDK 原生浮卡）、五态情绪状态机、
泡泡引擎（DSH Row/Module schema 子集 + 加权随机 + avoidIdx + 优先队列）、余额/预算/每轮消费提醒（持久去重）、
question（clarify 工具事件）与 approval（agent 半体 hook → 状态文件）等待观测、statusbar 芯片、
Web Audio 音效引擎核心（DSH 语义：同步起播/衔接排期/音量三态/mute）。

**未实现**：音效引擎 main.js 接线（M9 收尾）、正式鲸鱼素材（M10，DSH 素材不可复用需自制）、
多 Provider 模板（M11，现仅 DeepSeek）、设置 UI（M12）、打包安装（M13）、独立透明窗口（Phase 2 可选）。

**已知限制**：估算值与真实观测严格分列（UI 带「估算」角标）；DSH 同分钟同内容两轮的残留风险 R2；
余额 API 字段时效未自动探测（模板带 unverified 标注）；未计价轮成本显示「—」绝不按 0 计；
Python 半体启用需重启 App；真机冒烟（事件 payload 实形状/浮窗视觉）待用户部署验证。

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

待架构决策与 Milestone 13（Packaging）后回填本节。凭据将优先走 Hermes 官方机制（调查确认后更新）。
