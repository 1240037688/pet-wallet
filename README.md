# hermes-whale-widget

Hermes 桌面「小鲸鱼记账挂件」：AI 用量记账 + 余额/消费展示 + 桌面角色交互。
参考 [MeteorNOX/DeepSeek-Balance-Whale-Widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget)
的产品体验，但**架构完全按 Hermes 本机版本重新设计**，不做代码移植。

> 核心理念：鲸鱼只是表现层。真正的核心是一个可靠的
> **Hermes AI Usage + Accounting + Notification System**（账本、规则、配额），
> 鲸鱼角色让它直观、有趣、可交互。

## 项目状态

**Phase：调研与文档阶段（Milestone 0 之前）** — 尚未开始业务编码。
当前在执行：参考项目剖析 → Hermes 架构审计 → 可行性矩阵 → 架构决策 → 实施计划。

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

Milestone 0 建立脚手架后回填。（注意：本机约束禁止直接写 `D:\hermes\desktop-plugins` 部署调试，
需要用户手动复制或另行授权；详见 AGENTS.md §0。）

## 功能清单（目标）

记账（usage ledger / 双轨余额观察 / 幂等去重）、余额与今日消费展示、单轮消费、桌面常驻角色
（点击/拖拽/互动）、泡泡消息系统、消费与任务事件提醒、音效、自定义角色图片、自定义 Provider、
Hermes 会话 usage 联动、设置与持久化。完整可行性分级见 `docs/design/FEATURE_MATRIX.md`。

## 已实现 / 未实现 / 已知限制

- 已实现：无（尚未编码）。
- 未实现：全部（见 `docs/plans/IMPLEMENTATION_PLAN.md` 的 Milestone 划分）。
- 已知限制：随调查更新。

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
