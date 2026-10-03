# REMAINING_WORK（Goal 模式 · 2026-10-04 建档）

> 状态标记：`OPEN` / `FIXED` / `VERIFIED` / `DEFERRED-BY-DESIGN`（附理由）。
> 基线：commit 239859c，node 185 / pytest 180 全绿。

## P0 — 阻塞核心流程

### P0-1 `/wait-state` 契约不匹配 — 等待提醒全链路断裂
- 状态：`FIXED + VERIFIED`（node main-wiring 真实契约 mock + pytest test_wait_state/test_e2e_flow 场景 3）
- 模块：`desktop/src/main.js`（pollWaitState）↔ `dashboard/whale_core/wait_api.py`
- 现象：main.js 读 `data?.slots`，实际契约是 `{question_slots[], approval_slots[], fired_dedup_keys[]}`——两端各自实现但从未连通，question/approval 等待泡泡与情绪**永远不触发**；且 question/approval 被混为一个布尔。
- 验收：main-wiring 测试用真实契约形状 mock；question 槽→`syncWaiting({question:true, approval:false})`；approval 槽→approval:true；端到端测试（Python 侧 open→GET /wait-state 断言 + JS 侧映射断言）。
- 测试方式：`npm test`（main-wiring）+ `pytest tests/test_wait_state.py`。

### P0-2 提醒通知无消费者 — budget/balance_low/turn_cost 永不显示
- 状态：`FIXED + VERIFIED`（notifications_api.py 新建 + 挂载；桌面 10s 轮询→泡泡；test_notifications_api 5 条 + test_e2e_flow 场景 1/2/4 端到端）
- 模块：`dashboard/whale_core/notifications.py`（查询面已备）→ **缺 `/notifications` REST 端点** → **缺桌面轮询** → controller 泡泡队列
- 验收：GET /notifications 返回未过期未消除通知（按 rank）；POST /notifications/dismiss；桌面 10s 轮询把 budget/balance_low/turn_cost 映射为对应 rank 的泡泡（wait_* 由 /wait-state 链负责，跳过防重复）；金额字段遵守 §8.1；端到端：ingest→rules fire→REST→（mock ctx）泡泡出现。
- 测试方式：pytest（新 notifications_api 契约测试）+ node main-wiring/notifications 测试。

## P1 — 核心功能缺失

### P1-1 音效引擎未接线（M9 收尾）
- 状态：`FIXED + VERIFIED`（main.js attachSoundEngine + controller.attachSound 挂点；config.sound 三键默认 enabled=false；controller.test 19 条 + main-wiring；无素材时天然无声）
- 模块：`desktop/src/sound/engine.js`（已实现，27 测试）→ main.js/WhaleActor 未调用
- 验收：pointer down/up → engine.press()/release()；TASK_COMPLETED→play('task_finished')；等待首次出现→play('question'/'approval')；config 增 `sound: {enabled, muted, volume_global}`（默认 enabled=false，无 clip 时天然无声）；dispose 清理。
- 测试方式：main-wiring 测试扩展（fake contextFactory）。

### P1-2 INSTALL.md（部署/卸载/回滚/凭据配置）
- 状态：`FIXED`（INSTALL.md 11 节交付；真机步骤 NOT VERIFIED——需用户执行复制/重启）
- 验收：手动部署步骤（复制→plugins.enabled→重启→opt-in）凭据三种方式（secret_scope env / credentials.json）、卸载与回滚、数据目录说明；与 README 一致。

## P2 — 集成与稳定性

### P2-1 combo≥4 idle-line 同 rank 被遮挡
- 状态：`FIXED + VERIFIED`（controller.click 先 dismiss greeting；controller.test 断言 idle-line 可见）
- 修复：click combo≥4 时先 dismiss greeting 同 rank 队头再 show idle-line。
- 测试：controller.test 补断言。

### P2-2 `core/pricing.js` 误导性 stub
- 状态：`FIXED`（已删除——零引用方，JS 半体不做计价由 Python 权威承担）
- 修复：JS 半体不做计价（Python 是记账权威）——将文件改为明确的重导出/说明或删除引用；避免"假实现"观感。

## P3 — 测试、文档、清理（部分 DEFERRED-BY-DESIGN）

### P3-1 `ui/settings/index.js` M12 设置页 stub — `DEFERRED-BY-DESIGN`（V1 范围）
- 核心流程不依赖：配置经 `config.json`（PUT /config）与凭据文件/环境变量完成（INSTALL.md 说明）。V1 交付。

### P3-2 `track3.py` state.db 只读交叉校验桩 — `DEFERRED-BY-DESIGN`（V2）
- 架构决策记录于 DATA_MODEL §4.1 / DR-11；轨①+轨②已闭环，轨③为增强校验。

### P3-3 catalog `repo/sha` 占位 — `DEFERRED-BY-DESIGN`（M13 打包时定稿；手动部署不依赖 catalog）

### P3-4 鲸鱼正式素材（M10）— `DEFERRED-BY-DESIGN`（占位 SVG 可用；DSH 素材不可复用，需自制）

### P3-5 USER_FLOW_CHECKLIST.md / FINAL_VALIDATION.md / FINAL_GOAL_REPORT.md
- 状态：`FIXED`（CHECKLIST 10/10 流程含自动化映射；真机项 NOT VERIFIED 如实标注）

### P3-6 README / WORKLOG 同步
- 状态：`FIXED`（README 已按当前真实状态修订；WORKLOG Goal 条目已追加）

## M11 多 Provider / M12 完整设置 UI / M13 打包 — V1 范围（非本轮 Goal 阻塞项，理由见上）
