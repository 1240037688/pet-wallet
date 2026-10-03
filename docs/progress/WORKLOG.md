# WORKLOG

## 2026-10-03 — 项目启动 / Milestone -1（调研）

- 建立 `E:\hermes_plugin\hermes-whale-widget` 项目与文档体系（README / AGENTS / docs/*）。
- 确认 Hermes 本机环境（v0.21.5，源码与已装插件位置），用户硬约束：工作区外只读。
- 开始 Phase 1-3 调研。

## 2026-10-03 — Phase 1-5 调研与设计完成（三波并行子代理）

- 完成全部 10 份文档：research×4（DSH 剖析 / Hermes 审计 / 参考项目 / 调研日志）、design×4（FEATURE_MATRIX / FEASIBILITY_REPORT / DATA_MODEL / ARCHITECTURE_DECISION）、plans×2（IMPLEMENTATION_PLAN / TEST_PLAN）。
- 子代理源码抽查修正两条调研结论：Question 提醒 = A 级（clarify 工具事件必发）；Approval 提醒 = C 级（agent 半体 observer hook 桥接）。
- **检查点（任务书§51）全部通过**：无需 Core Patch（D 级=0）；usage 来源=`session.usage`/`message.complete` 事件 + `host.state.focusedUsage`；余额=Python 半体 provider 差分账本 + state.db 只读交叉校验；API Key=Python 半体独占；鲸鱼窗=Phase 1 floating pane / Phase 2 独立透明进程（心跳自退）；生命周期=生命周期矩阵（8 场景）。
- 计划：MVP=M0–M8（完整闭环），V1 至 M13 打包；测试十域约 70 条用例。
- 下一阶段：M0 三半体骨架（catalog/desktop/dashboard/agent）。
