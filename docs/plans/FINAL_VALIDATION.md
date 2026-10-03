# FINAL_VALIDATION（验收矩阵 · 2026-10-04）

> 证据规则：每个 PASS 都有对应命令/测试名；无法在本环境验证的项如实标 `NOT VERIFIED` 并说明原因。
> 基线 commit：49e895b（Goal 收尾）+ 本轮清理提交。测试规模：**node 190 / pytest 188，全绿**。

## 一、功能验收矩阵

| 功能 | 实现 | 单元测试 | 集成测试 | 用户流程验证（自动化） | 状态 |
|---|---|---|---|---|---|
| usage 事件捕获/归一化/分桶 | ✅ | normalize/turn-tracker（node） | main-wiring 全链（mock ctx→REST） | ✅ test_e2e_flow 场景 1 | PASS |
| 幂等账本落库（去重/水位/重置） | ✅ | test_ledger_accounting 20 条 | ingest 契约 + 重放/重启模拟 | ✅ 场景 1（重复提交→duplicate） | PASS |
| 三级计价（估算诚实性） | ✅ | pricing/ACC-07 定点对拍 | 结算接线契约 | ✅ 场景 1（精确 60_000_000 units） | PASS |
| DeepSeek 余额轨②（差分/五状态机/校正） | ✅ | test_balance 30 条（PRV 全 mock） | 余额 REST 契约 | ✅ 场景 2（110→90 触发→回升消除） | PASS |
| 提醒规则（预算/余额/每轮消费，DR-14 去重） | ✅ | test_reminders 25 条 | notifications REST 契约 | ✅ 场景 1/2/4 | PASS |
| 通知消费链路（表→REST→桌面泡泡） | ✅ | controller.test syncNotifications | test_notifications_api | ✅ 场景 1 dismiss 往返 | PASS |
| question 等待（clarify→桥→泡泡） | ✅ | main-wiring（真实契约） | test_wait_state 21 条 | ✅ 场景 3（open/close/畸形 400） | PASS |
| approval 观测（agent hook→状态文件→REST） | ✅ | test_wait_state approval 段 | hook 状态文件读写/损坏兜底 | ⚠ 链路自动化 ✅；真实审批流 NOT VERIFIED | PASS（链路）/ NOT VERIFIED（真机） |
| 鲸鱼浮窗（floating pane/情绪状态机） | ✅ | whale-state 11 条 | main-wiring pane 注册断言 | ⚠ 逻辑 ✅；视觉/拖拽 NOT VERIFIED | PASS（逻辑） |
| 泡泡引擎（schema/加权随机/优先队列） | ✅ | bubble-schema/resolver/queue 34 条 | renderer smoke | ✅ 经 controller/main-wiring | PASS |
| 每轮消费泡泡（settled 契约） | ✅ | ingest-settled 5 条 | main-wiring settled→泡泡 | ✅ 场景 1 | PASS |
| 音效（M9 接线，默认关） | ✅ | sound-engine 27 条 | controller 挂点断言 | ⚠ 接线 ✅；真实发声 NOT VERIFIED | PASS（接线） |
| 数据服务轮询/降级（未记账快照） | ✅ | data-service/balance-view | main-wiring 降级分支 | ✅（失败路径自动化） | PASS |
| 生命周期（dispose 零残留） | ✅ | poller/reset_runtime 测试 | main-wiring lifecycle | ✅（dispose 零流量断言） | PASS |
| 安全（凭据不外泄/回环守卫/命名 lint） | ✅ | SEC/PRV/CON 域 | check-security 双工具 | ✅（响应无 key 断言） | PASS |

## 二、四层验证结果

- **L1 静态**：`node --check` 产物 ✅；`check-security.mjs`（产物 import 白名单/禁用模式）✅；`check-security.py`（全源码 100 文件）✅。
- **L2 模块**：node 190（模块 20 文件）+ pytest 188（模块 16 文件）全绿。
- **L3 集成**：契约测试（ingest settled/wait-state/notifications REST）+ test_e2e_flow 4 场景全绿。
- **L4 用户流程**：10 条流程链路级自动化 10/10（USER_FLOW_CHECKLIST.md）；**真机端到端 NOT VERIFIED**——受「D:\hermes 只读」约束，需用户按 INSTALL.md 手动部署后执行 CHECKLIST 人工步骤（真实网关事件 payload、真实 DeepSeek API、真实审批流、真实音频设备、浮窗视觉/拖拽）。

## 三、异常路径已验证

无效凭据 401/403、429、5xx、坏 JSON、缺字段、0 余额≠失败、超时、后端不可达降级、DB 损坏 fail-closed、
畸形 REST 400（不回显值）、loopback 外写 403、凭据形态拒存、重放/重启不重复扣费/不重响、时钟推进跨日重置。

## 四、已知限制（如实声明）

1. 真机部署/真机端到端：NOT VERIFIED（环境约束，替代验证=L3/L4 自动化链路 + dev-preview）。
2. DSH 同分钟同内容两轮的极小重复记账残留风险（DATA_MODEL R2，已记录）。
3. 音效无内置素材（enabled 默认 false；素材就位前开启也无声）。
4. 鲸鱼视觉为占位 SVG（M10 自制素材）；DSH 素材 License 不可复用。
5. M11 多 Provider / M12 设置 UI / M13 catalog 定稿 = V1 范围（REMAINING_WORK.md）。
6. track③ state.db 只读交叉校验 = V2 设计内延期（DR-11）。
