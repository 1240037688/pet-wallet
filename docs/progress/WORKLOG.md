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

## 2026-10-03 — M0 完成：三半体骨架 + 配置/日志/DB 脚手架 + 构建/测试/预览/安全脚手架

### 完成了什么

**只读探查（M0 任务 2，供 M8 用）**：
1. **dashboard 半体挂载机制**（`hermes_cli/web_server_dashboard.py:805-905` `_mount_plugin_api_routes`）：`dashboard/plugin_api.py` 以 **`importlib.util.spec_from_file_location("hermes_dashboard_plugin_<name>", api_path)` 按文件路径导入**（非包上下文），先注册 `sys.modules` 再 `exec_module`；要求模块级 `router: APIRouter`；以 `app.include_router(router, prefix="/api/plugins/<name>", dependencies=[Depends(_plugin_route_secret_scope)])` 挂载；信任门 = 仅 bundled/user 源 + `plugins.enabled` 白名单。→ **结论：`plugin_api.py` 做 sys.path bootstrap 后 `import whale_core`**（已实现，tests 用同款 spec_from_file_location 导入验证）。
2. **agent 半体导入布局**（`hermes_cli/plugins_loader.py:640` `_load_directory_module`）：插件 `__init__.py` 作为包 `hermes_plugins.<slug>` 导入，`submodule_search_locations=[插件目录]`、`__path__=[插件目录]`。→ **结论：M8 的 `from .whale_agent.approval_hook import ...` 相对导入可用**；`register(ctx)` 有加载超时，失败会整体回滚登记。
3. **SDK 面核实**：`ctx.rest` **相对插件命名空间**（`'/health'` → `/api/plugins/whale-widget/health`，`apps/desktop/src/api/plugins.ts:52-80`，有 `..` 穿越防护）；`host.notify({message})` 存在（`store/notifications.ts:249`）；`host.onEvent/ctx.onEvent('*', fn)` 返回 disposer、register 期订阅随卸载清理（`sdk/index.ts:1462-1467`）；`STATUSBAR_AREAS={left,right}`、`atom/useValue`（nanostores 再导出，`sdk/index.ts:2089-2100`）。

**交付物**（`plugin-src/hermes-whale-widget/`）：
- catalog 半体：`catalog/whale-widget.yaml`（M0 草稿；repo/sha 占位并注明 M13 定稿；M8 需把 provides_hooks 改为审批观察 hook）。
- agent 半体：`plugin.yaml` + `__init__.py`（no-op register + M8 TODO）+ `whale_agent/` 占位。
- dashboard 半体：`manifest.json` + `plugin_api.py`（薄 shell：sys.path bootstrap → 转授 whale_core）+ `whale_core/`（config 原子写/深合并/白名单校验、logging 5×1MB 轮转 + 四类脱敏、SQLite WAL/synchronous=FULL/fail-closed、migrations v1=DATA_MODEL §7.2 全量 DDL 17 表 4 索引 + 写前 bak-<ver> 备份、security 回环守卫 + REST 命名 lint + 密钥形态扫描、clock 可注入时钟、api 路由工厂）。端点：`GET /health`、`GET /meta`、`GET|PUT /config`（PUT 回环守卫 + 白名单，拒绝类凭据字段名）。
- desktop 半体：`desktop/src/`（main.js 最小 register：状态栏芯片占位 + health 轮询探活 + host.notify 自检 toast + `'*'` 事件订阅；core/normalize.js 可测子集 NULL 感知；其余 M1-M9 模块占位）→ esbuild 产出 `desktop/plugin.js`（5.0KB 单文件 ESM，externals 白名单，chrome120）+ `dist/desktop/plugin.js` 副本。
- tools/：`build-desktop.mjs`、`check-security.mjs`（产物级：import 白名单/eval/原型补丁/URL/sk-/Bearer）、`check-security.py`（全源码级：Python+JS 模式与 import allowlist，allowlist 逐条注明理由）、`dev-preview.mjs` + `preview/`（SDK shim + import map + mock /health）、`dev.md`（命令文档）。
- `package.json`（devDependencies：esbuild；react/react-dom 仅预览 shim 用——理由在 comments 字段）。
- `.gitignore` 增加 `.venv/`、`tools/.preview-build/`、`.pytest-tmp/`。

### 测试结果（全部真实输出）

- `pytest plugin-src/hermes-whale-widget/dashboard/tests -q --basetemp=.pytest-tmp` → **37 passed**（config 深合并/白名单/原子写、迁移幂等+备份+损坏 fail-closed、health/meta/config 契约、脱敏 SEC-01、回环 403）。
- `node --test "…/desktop/tests/*.test.mjs"` → **16 passed**（normalize NULL 感知/status 分流、产物 import 白名单、scanner 正反例 smoke、**经 loader hook 加载构建产物 + mock ctx 完成 register + health 探活**）。
- `node --check` 对 `desktop/plugin.js` 与 `dist/desktop/plugin.js` 均通过。
- `node tools/check-security.mjs` 与 `.venv/Scripts/python.exe tools/check-security.py`（62 文件）均 OK。
- `node tools/dev-preview.mjs`：服务器与全部端点（页面/产物/三 shim/mock health）curl 验证 200；**页面内视觉验证未做**（本子代理无浏览器），已在 dev.md 写明人工验收步骤；register 路径已由 node 运行时测试覆盖。

### 环境事实与设计偏差（实现 vs 计划）

- **共享 SQLite 连接需 `check_same_thread=False`**（db.py）：FastAPI sync 端点跑在线程池线程，默认 check_same_thread=True 在真机会 ProgrammingError；测试亦暴露了跨线程 close 失败导致句柄泄漏、残留 -wal 掩盖主库损坏的坑。M2 落库时如需并发再评估 per-request 连接。
- **pytest 需 `--basetemp=.pytest-tmp`**：本机默认 `%TEMP%\pytest-of-<user>` 存在 PermissionError（环境问题，非代码问题）。
- 目录命名按 IMPLEMENTATION_PLAN §3.1 执行（desktop 源码在 `desktop/src/`、产物 `desktop/plugin.js`；测试在 `dashboard/tests/`、`desktop/tests/`），与任务清单里的 `desktop-src/`、`dist/`、`tests/` 略有出入，`dist/` 副本额外保留以对齐验收。
- 新增 `whale_core/clock.py`（可注入时钟，TEST_PLAN §2.3 要求 M0 立约定）与 `whale_core/api.py`（路由工厂，保持 plugin_api.py 薄壳可按路径导入）——计划模块清单之外的最小补充。
- normalize.js M0 即实现可测子集（status complete→ok 映射、五类 token 全 NULL 感知），M1 扩全并钉 fixtures。

### 未解决问题

- floating pane 的确切 SDK API（M5 第一项探查）；`session.usage`/`message.complete` 真实 payload 形状（M1/M5 真机冒烟）；catalog 的 repo/sha（M13）。
- dev-preview 页面的真浏览器走查待人工执行一次（`node tools/dev-preview.mjs` → 芯片显示 `● Whale widget placeholder · ok · v0.1.0 (schema 1)`、无未捕获错误）。
- 按本轮任务约束（docs/ 仅允许追加 WORKLOG），AGENTS.md §5 命令区、README 开发测试节、TEST_PLAN §2.4 命令回填**留待下一轮**回填。

### 下一阶段

M1 Usage 捕获与归一化（normalize 全量映射 + ingest-client 退避重试 + `/ingest/turn` 契约 stub + replay harness）。

## 2026-10-03 — M1+M2 完成：Usage 捕获与归一化 + 账本落库（幂等 dedup / watermark / 日聚合 / 归档）

### 完成了什么

**desktop 半体（M1，全部纯逻辑可 node:test）**：
- `desktop/src/core/normalize.js`（158 行）：Hermes 网关事件 → 归一化鲸鱼事件全量映射。`message.complete` 按 status 分流（complete→`TURN_FINISHED{ok}`+`TASK_COMPLETED`；error/interrupted→`TURN_FINISHED`+`ERROR`）；`session.usage`→`USAGE_UPDATED{final:false}`（心跳只进内存，永不落库）；`session.info`→`SESSION_INFO`（turn 归因输入）；`tool.*`→内部 `TOOL_ACTIVITY`；`gateway.reconnecting/ready`、`host.state.gateway`→`CONNECTION_CHANGED`；envelope `replayed` 旗标随 `TURN_FINISHED` 透传。usage 全字段 NULL 感知（缺省→null 不造 0，AUDIT §12/R4），payload 白名单提取（DM §8.4）；未知事件丢弃并由 `createNormalizer()` 计数（含 unknownTypes 分布）。
- `desktop/src/core/turn-tracker.js`（新增，171 行）：(sessionId, turn) 分桶累加；心跳只刷新开启轮次的内存快照；`TURN_FINISHED` 结算一次——usage 取值优先级 = complete 快照 > 本轮最后心跳 > focusedUsage salvage；`after_reconnect`（重连后首个带 usage 的结算打标，只消费一次）与 `replayed` 透传；`usage_source`（complete/heartbeat/focused）溯源；无 measurable usage 不产生载荷、不消耗重连标记。
- `desktop/src/core/ingest-client.js`（新增，216 行）：`{turns:[...]}` 批量 POST `/ingest/turn`（≤20/批，队列上限 200，丢最旧计数）；指数退避重试 ≤3 次后进内存死信（上限 50）并置 `unavailable`（芯片提示「记账暂不可用」）；`gateway.reconnecting` 期间 `pause()` 不发送，`resume()` 时死信回队重试；fire-and-forget 不阻塞退出、不落盘（AGENTS.md §8：JS 半体无持久化）。
- `desktop/src/main.js`（重写装配）：订阅 `message.start/session.usage/message.complete/session.info/gateway.reconnecting/gateway.ready/error`（register 期订阅随卸载自动清理）；重连前后捕获 `host.state.focusedUsage` 兜底快照（防漏记；幂等最终由 Python dedup_key 保证）；`$health`/`$ingest` 状态出芯片；60s health 轮询。

**dashboard 半体（M2）**：
- `whale_core/ingest.py`（612 行，替换 M1 stub）：幂等结算引擎——`dedup_key` 按 DM §3.2 公式实现（sha256 截 40，固定测试向量钉住）；内容查重先于 turn_seq 分配（同 session+同分钟+同累计快照→duplicate），±10min 模糊窗承接重连重放的分钟漂移，UNIQUE 索引作并发竞态兜底；SessionWatermark upsert（逐字段单调 max，永不回拖）；计数器重置检测（快照<水位 → provisional + token_only + 重置后绝对值（新基线 0，绝无负增量）+ reset_count+1）；`after_reconnect:true`/`replayed:true` 首条 complete 只对齐水位不结算（DM §3.4）；无 measurable usage 跳过不落行（不造 0）；`daily_summary(track='usage')` 每 turn upsert（total+per-model token 计数合并）；单 turn 单事务。
- `whale_core/usage_ledger.py`（新增，189 行）：`/usage/summary`（今日汇总 + 7 天窗、per_model 分组、partial_flags{partial_days, provisional_turns}、estimated 字段 M2 阶段恒 null + basis='token_only' 声明）、`/usage/turns`（最近 N 轮 join TurnCost、session 过滤、limit 1..100）。命名 lint 遵守 DM §8.1（无裸 cost/spend/used，有测试）。
- `whale_core/archive.py`（新增，166 行）：保留策略执行器（90d/2 万条→archive 不删除、archive 20 万上限丢最旧、daily_summary 365d→summary_archive、notification/watermark 直删）；`maybe_daily_tick` 每本地日一次（whale_meta 记 guard），ingest 后顺手 prune，无 timer（AGENTS.md §8）。
- `whale_core/api.py`（扩展）：`POST /ingest/turn`（单条或 `{turns:[...]}` ≤100、畸形 400 且错误信息不回显 payload 值、账本损坏 fail-closed 503、回环守卫）、`GET /usage/summary`、`GET /usage/turns`。
- `desktop/src/ui/statusbar.js`（扩展）：芯片显示 ingest 可用性（unavailable/queued/deadLetters/dropped）。

### 设计变化 / 与计划偏差

1. **turn_cost.estimated_cost_units 的「无价」表示**：DDL 列 NOT NULL，M2 无 pricing → 存 `0 + cost_basis='token_only' + currency='none'`（文档化占位）；`daily_summary.estimated_cost_units` 存 NULL；查询层把占位币种映射回 null（「null ≠ 0」序列化契约有测试钉住）。M3 接管后由 pricing 决策覆盖。
2. **dedup 硬化（超出 DM §3.2 的 UNIQUE-only）**：`turn_seq` 由 Python 按次分配，重放时键内 turn_seq 变化 → 仅靠 UNIQUE 会漏判。实现为「同 (session, minute_bucket, cumulative_json 内容) 查重 → duplicate」+ ±10min 模糊窗（网关 envelope 无稳定时间戳，AUDIT §3.1），dedup_key 公式仍完整实现且被固定向量钉住、UNIQUE 作竞态兜底。DM §3.6-R2（同分钟同内容真实两轮少记一轮）为已知可接受残留。
3. **归一化事件集口径**：`USER_INPUT_REQUIRED`/`APPROVAL_REQUIRED` 不从网关事件产生（M8 wait 观测/agent hook 桥），`BALANCE_LOW`/`BUDGET_REACHED` 是 Python 规则输出——normalize.js 头注释声明，与 [AD] §4 一致。
4. `received_at` 取 JS 墙钟 `Date.now()`；`day`/`minute_bucket` 由 Python 侧计算（day=本地时区，DR-12；minute=epoch 分钟，时区无关）。
5. `whale_core/track3.py`（计划 M2 任务 5，标注「可选轨」）仍为占位——本轮任务书 M2 交付清单未含，留待后续里程碑；M2 验收的归档/幂等/watermark/日聚合条目均已交付。
6. `tools/replay-events.mjs`（计划 M1 任务 5）未建：INT-01/02 链路已由两层进程内测试等效覆盖（pytest fixtures → ingest → DB/REST 断言；node 事件 → normalize → tracker → mock ctx.rest），JS 载荷键集（register.test）与 Python 校验白名单（ingest contract test）两侧各自钉死防漂移；独立 uvicorn-spawn harness 留待 M5 真机冒烟前补。
7. statusbar 芯片扩展 ingest 状态显示（计划未列）——死信「记账暂不可用」UI 提示要求的最小落点。

### 测试结果（全部真实输出）

- `.venv/Scripts/python.exe -m pytest plugin-src/hermes-whale-widget/dashboard/tests -q --basetemp=.pytest-tmp` → **94 passed**（ingest contract 26 / ledger accounting 18 / usage endpoints 7 / archive 6 + M0 回归 config 14 / logging 9 / migrations 7 / health 7）。
- `node --test`（npm test glob）→ **49 passed, 0 failed**（normalize 17 / turn-tracker 14 / ingest-client 9 / artifact 5 / register 4——register 4 条经 loader hook 加载**构建产物**+mock ctx 走完 M1 全管线：register→事件→结算→POST→断连对齐→降级面）。
- `node tools/build-desktop.mjs` → OK（`desktop/plugin.js` 17.6KB 单文件 ESM；`dist/desktop/plugin.js` 副本同步）。
- `node tools/check-security.mjs` → OK；`.venv/Scripts/python.exe tools/check-security.py` → OK（70 文件）；`node --check plugin.js` → OK。

ACC 域覆盖：ACC-01（五类 token/turn_seq/day/双 JSON 留存）✓；ACC-02（同批重放×3 恒 1 行返回 duplicate；漂移分钟；窗口外真实新轮正常结算）✓；ACC-03（db 句柄重建+重放同批→无重复、turn_seq 续号；API 级 restart 同样覆盖）✓；ACC-04（相邻快照差分、双会话交错不串账、多模型）✓；ACC-05（reset→provisional/token_only/绝对值/reset_count=1，后续轮恢复 final）✓；CON-01（畸形 400×14 形态、不回显、凭据形态拒绝、fail-closed、回环 403）✓；CON-02/03（summary/turns schema、null≠0、无裸金额键）✓；INT-02 切片（after_reconnect/replayed 只对齐不结算，对齐后下一轮差分正确）✓。

### 未解决问题

- `session.usage`/`message.complete` 真实 payload 形状仍属「未验证」（M5 真机冒烟用 `ctx.onEvent('*')` 录制后修正 fixtures）；missing status 按 complete 宽松处理，同在 M5 核对。
- `minute_bucket` 依赖 JS 墙钟 `received_at`；重放时钟漂移由模糊窗兜住，若网关未来提供稳定事件时间戳可换源（计划 M2 风险项）。
- track3.py 与 replay-events.mjs 如偏差 5/6。
- dev-preview 页面 M1 芯片状态的浏览器视觉走查待人工一次。

### 下一阶段

M3 Pricing（`pricing.py` 三级 basis + `money.js` 1e8 定点与 Python 同向量对拍 + `ingest.py` 结算接线 + summary per-model cost 分列）；随后 M4 余额轨②。

## 2026-10-03 — M3 Pricing + M4 DeepSeek 余额轨②（主会话实现；子代理因网络故障中断两次，其 M3 半成品经逐文件核验后采用）

### 交付
- M3：`whale_core/pricing.py`（三级 cost basis：hermes_estimate > whale_pricing（内置 CNY 价目 + 用户覆盖、最长键匹配、reasoning ⊆ output 不另计费、写价不含）> token_only（unknown_model → NULL 永不为 0））+ REST `GET /pricing`、`PUT /pricing/custom`（校验/清除）。
- M4：`providers/base.py`（错误分类学 auth/rate_limited/server/bad_response/network/timeout/not_configured）+ `providers/gateway.py`（凭据解析：Hermes `agent.secret_scope.get_secret`〔已核实 agent/secret_scope.py:219〕→ env → credentials.json 兜底；指纹 sha256[:24]；出站 origin 白名单）+ `providers/deepseek.py`（/user/balance、多币种选择 CNY>0→任意非零→CNY→首项、缺失字段=NULL≠0）+ `providers/registry.py`。
- `balance_ledger.py`：快照幂等（UNIQUE）+ 单调（fetched_at<=last 忽略）、差分（降=observed_spend、升=credit **永不冲销**）、五状态机 unknown/zero/error/stale/ok（API 失败≠0、保留 last known、错误只存 kind+status 于 whale_meta）、观测缺口>10min→partialDay、显式校正（implied usage 公式 + revision 乐观并发 409）；`poller.py`（单实例守护线程、无凭据泊车、reset_runtime 即停、测试经 WHALE_WIDGET_DISABLE_POLLER=1 关闭）。
- REST：`GET /balance`、`GET /balance/summary`、`POST /balance/refresh`、`POST /balance/adjustment`。

### 测试结果（真实输出）
- pytest **124 passed**（新增 PRV 全 mock 域：401/403/429/5xx/坏 JSON/缺路径/0 余额/超时；差分 down/up/连续/校正/409/partial/五状态转移；安全：响应与存储无 key、credentials.json 兜底来源）；npm test **49 passed**；build + 双重安全自检 OK。

### 修复与偏差
- provider 表 `created_at/updated_at NOT NULL` 无默认 → `INSERT OR IGNORE` 静默跳过 → FK 失败（补时间戳修复；教训：OR IGNORE 会吞 NOT NULL 违规）。
- v2 迁移（诚实 NULL 计价）落地后 M2 时代边界断言全面升级：成本 0 占位→真实计价（acc01=60_020 含 cache 命中价）、daily scope 带 currency（`usage:default:CNY`），重置轮（token_only）独立记 `usage:default:none` scope，两行并存。
- `daily_summary` 无 correction_log_json 列 → 审计改存 balance_adjustment 表（每校正一行）。
- check-security.py allowlist 加入 `agent`（附核实理由）。
- **事故记录**：调试脚本曾直连真实 DeepSeek API 得 401（无损害）；纪律强化——provider 交互必须注入 transport（MockTransport），已写入 AGENTS.md §5。
- AGENTS.md §5 命令区已回填实际命令。

### 下一阶段
M5 基础鲸鱼（floating pane SDK 探查 + 透明/置顶边界确认）→ M6 鲸鱼状态。
