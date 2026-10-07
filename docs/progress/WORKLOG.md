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

## 2026-10-03 — M9 音效引擎核心（WP-3 子代理：engine.js + 引擎单测；main.js 接线与构建留待集成步骤/WP-1）

### 完成了什么

- `desktop/src/sound/engine.js`（重写 M0 stub，≈420 行）：DSH §E1 语义的 Web Audio 引擎核心，**全部 Web Audio 对象经注入的 `contextFactory` 创建**（单测跑 fake context，绝不触碰真实音频设备）。能力：
  - **同步起播路径**：`press()`/`release()`/`play()`/`preview()` 全同步、不 await 解码 promise——clip 未就绪跳过本次播放，后台 fetch+decode 继续并进缓存；
  - **URL 级缓存**：同 URL 只 fetch 一次、decode 一次，跨事件共享；`fetchClip` 返回 null（204 风格空响应）→ `empty` 终态、0 字节绝不进 decodeAudioData；decode 失败 → `failed` 终态**不再重试**，经 `onDebug` 记 debug 风格回调、不 throw；
  - **release 排期**：`press()` 记锚点（起播音频时刻 + 按压音时长），`release()` 用纯函数 `computeReleaseStart` 排期到「按压起点 + 按压音长 − 40ms」（`RELEASE_LEAD_SEC=0.04`），取 `max(now, 排期点)`——短按无缝衔接、长按立即播；无锚点（按压音未就绪/被静音截断）退化为松手立即播；
  - **音量三态**：每事件槽位 `{vol, volSet}`，`volSet=false`（未显式拖过滑块）跟随全局按压音量（纯函数 `resolveVolume`），`explicit=true` 用自身值（区分「默认 100%」与「设了 100%」）；`setVolume('global'|kind, v)` 带 [0,1] clamp、非数值忽略；**mute 最高优先级**——静音时不建 context、不取流、停掉在播/已排期节点；
  - **AudioContext 生命周期**：懒创建（首次非静音播放/预热时，`latencyHint:'interactive'`），**绝不 close**（任务结束音非手势触发）；空闲 `IDLE_SUSPEND_MS=60s` → `suspend()`（注入时钟可测，节流只挂起一次），再次播放前 `resume()` 先于 `start()`；主动 60s 定时器为**严格 opt-in**（`setTimer` 注入，序列号中和陈旧句柄，无需 clearTimer）——不注入则退化为「下次引擎调用时惰性检查挂起」，node 测试零悬挂定时器；
  - **事件→clip 映射**：`SOUND_EVENTS = press/release/task_finished/question/approval`，`DEFAULT_CLIPS` 全 null=无声（结构先立）；`setClip/setClips/setSoundGroup`；**sound group 最小实现**——激活期间组槽位覆盖基础映射，空槽位 `''` = 该事件静音（不回退预设，DSH 语义），缺省槽位回退基础映射，`setSoundGroup(null)` 还原；
  - `preview(event)` 试听：绕过总静音（面板用户手势），仍遵循映射与音量解析；`warm()` 预取+预解码（返回仍在解码的 url 列表）；`dispose()` 停全部节点+取消定时器，不 close context。
- `desktop/tests/sound-engine.test.mjs`（新增，27 个测试组）：fake AudioContext/AudioBufferSourceNode/GainNode/decodeAudioData + 注入时钟/定时器，断言 start/stop/suspend/resume/decode 调用序列与精确排期时刻；覆盖上述全部可测子集 + `computeReleaseStart`/`resolveVolume`/`clampVolume` 纯函数向量。

### 设计变化 / 与计划偏差

1. **warm 不随 setClip 自动触发**：`setClip/setSoundGroup` 只改映射，预取需集成层在解锁手势后显式 `engine.warm()`——避免建 context 早于首个手势（自动播放策略）；冷缓存首次播放跳过一次后后台解码，与 DSH「预热后起播走同步路径」等价。
2. **空闲 suspend 惰性兜底 + 定时器 opt-in**：无 `setTimer` 时挂起由下一次引擎调用惰性判定（纯注入时钟可测）；注入后才有主动 60s 定时器（生产接线建议传 `setTimeout` 包装）。
3. **mute 强于 DSH 原语义**：除守卫外还 `stop()` 在播/已排期节点并清按压锚点（「总开关关=立即静」）；DSH 仅 135 处守卫。
4. **DSH `_alt` 备用路由（204/失败切换重取）不进引擎**：属取流策略，留给注入的 `fetchClip` 实现；引擎只按 URL 缓存终态（empty/failed 不重试）。
5. **`pending` 态（超出 DSH 的小扩展）**：静音期间已到达的字节挂起持有，解除静音时才解码（静音期间绝不建 context）；代价是持有一份已取流数据。
6. `play(event, {at})` 的 `at` 定为**绝对音频时钟时刻**（`max(now, at)` 钳制），与 release 排期同一语义；DSH 原生 `playAt(delay)` 为相对时延——集成层如需相对时延自行加 `ctx.currentTime`。

### 测试结果（真实输出）

- `node --test plugin-src/hermes-whale-widget/desktop/tests/sound-engine.test.mjs` → **27 passed, 0 failed**（时长 284ms）。
- `node tools/check-security.mjs` → **OK**（产物未被本任务触碰：engine.js 尚未被 main.js import，不进构建产物）。
- `.venv/Scripts/python.exe tools/check-security.py` → **OK**（扫描 97 文件，含新增 engine.js 与测试文件）。
- 未运行 `node tools/build-desktop.mjs`（任务书禁止；WP-1 负责构建）；未 commit。

### 未解决问题

- main.js 尚未接线（本任务书禁止）：引擎无人调用，真实声音路径未验证；M9 验收的「真机四类事件音各触发一次/最小化无爆音」留待集成 + 真机冒烟。
- 真实 AudioContext 行为差异（设备切换、Electron 自动播放策略、suspend 后时钟冻结细节）未验证——计划内 M9 风险项。
- 试听「不误伤真实事件音」的 UI 侧登记（DSH `dshwvPreviewMark`）属设置面板职责，不在引擎层。

### 下一阶段

集成步骤：main.js 按 engine 接口接线（见下）→ WP-1 构建回归 → 素材（M10：自产/CC0）落 `assets/` 后由 `setClip` 注入。

**main.js 接线接口（供集成参考）**：`createSoundEngine({ contextFactory: () => new AudioContext({ latencyHint: 'interactive' }), now: () => Date.now(), fetchClip, onDebug, setTimer: (fn, ms) => setTimeout(fn, ms) })`；`fetchClip(url) → Promise<ArrayBuffer|null>`（null=空响应；_alt 备路由在此实现）；解锁手势后 `warm()`；`setClip(event, url)`/`setSoundGroup({id, clips})` 配映射；`setVolume('global'|kind, v, {explicit})`（volSet 需在 storage 里与 vol 分开持久化）；`press()`/`release()` 挂 M6 交互，`play('task_finished'/'question'/'approval')` 挂事件沿，`preview(event)` 挂面板试听，`dispose()` 挂卸载。

## 2026-10-03 — WP-1 完成：desktop 集成接线（M5/M6/M7/M8-A 进 main.js）+ 单元测试全覆盖

### 完成了什么

**集成（`desktop/src/main.js` 重写装配；`desktop/src/core/ingest-client.js` 最小改动）**：
- **M5 floating pane**：`ctx.register({id: PANE_ID, area: PANES_AREA, title: 'Whale Widget', data: {placement:'floating', anchor:'bottom-right', width:'280px'}, render})`，render 返回 `jsx(WhalePane, {$balance,$summary,$dashboard,$whale,$bubble,controller})`（组件元素形式，保证 WhalePane/useValue 以 React 组件方式渲染）；statusbar chip 原样保留。
- **M5 dataService**：`createDataService({rest})`；`GET /config` 失败→内建 DEFAULT_UI_CONFIG（60s/30s，镜像 whale_core DEFAULTS 的 JS 消费键）；启动后 `dataService.start(config)`；onDispose 统一调 `dataService.stop()`。
- **M6 mood 接线**：`MOOD_EVENTS = {TASK_COMPLETED, USAGE_UPDATED, ERROR, APPROVAL_CLEARED}`——每个归一化事件命中即同步 `controller.event(kind)`；STREAM_TICK/TOOL_ACTIVITY 等不进 mood（动画纪律）。
- **M7 turn-cost 泡泡（跨包契约，防御式）**：`createIngestClient` 新增可选 `onSettled(results, batchTurns)`——仅当响应带 `settled` 数组才回调（try/catch 包裹，UI 永不破坏 ingest 管线）；main.js 把每项转 `controller.turnSettled({dedup_key, estimated_cost_text: formatMoney(units,{currency}), session_id})`；units 非有限数→null→「—」，currency==='none'（M2 占位币种）→null；session_id 取 settled 项，单 turn 批次回退取批内 payload（dedup_key 是 Python 侧计算的，JS 无法反向匹配多 turn 批次）。
- **M8-A clarify 转发**：SUBSCRIBED_EVENTS 增加 `tool.start`/`tool.complete`（此前 main.js 实际未订阅，任务书背景与现状不符，已按任务要求补齐）；TOOL_ACTIVITY 且 name==='clarify'（phase start/complete）→ `POST /ingest/wait-event`，body `{kind:'question', phase:'open'|'close', tool_id, session_id}`，tool_id 从原始 envelope payload 防御提取（tool_id→toolId→null）；fire-and-forget + 双层 catch，失败绝对静默（wait bridge 不影响记账）。
- **M8 wait-state 轮询**：10s 间隔（与 `controller.tick()` 共用一个定时器，注册后立即先跑一次）→ `GET /wait-state` → `controller.syncWaiting({question: slots.length>0, approval: 同值})`；404/异常一律视为无等待（WP-2 未部署不报错、不崩溃）。
- **生命周期**：单个 onDispose 钩子清三个定时器（health 60s / UI 10s）+ dataService.stop()；async 初始化与 dispose 竞态由 dataService 的 disposed 守卫兜住。
- **main.js 新增 re-export**：`$whale/$bubble/$balance/$summary/$dashboard`（供 preview/测试观察产物内部状态）。

**预览工具（最小改动）**：`tools/dev-preview.mjs` 增加 /config、/balance、/usage/summary、/wait-state、/ingest/turn（带 settled 示例）、/ingest/wait-event mock，使预览页能真实展示「余额/今日/泡泡」全链路；`tools/preview/preview-host.js` 将 `area==='panes'` 的贡献挂载进 #pane-slot（原生拖拽/钳制属 pane-shell，不在 shim 范围）。

**测试（新增 10 个文件，node:test，沿用 tests/ 现有 shims/loader 写法）**：
- `whale-state.test.mjs`（11）：press→release、连击窗口（注入时钟，含窗口边界=自上次点击起算）、TASK_COMPLETED/USAGE_UPDATED 瞬态与 2.5s 过期、waiting 粘住直至 cleared、STREAM_TICK 零影响（不续瞬态）、ERROR 清 waiting、press 压过瞬态、快照形状。
- `money.test.mjs`（10）：与 Python 同向量——"110.00"→110e8、0.00000001→1、>8 位小数截断不进位、null/非法输入 throw（含越界 RangeError）、unitsToDecimalString、formatMoney 2 位/币种/负数/decimals 钳制、null→「—」、往返无损。
- `balance-view.test.mjs`（14）：五状态→文本/徽标/hint 全钉——error 保留 last known 绝不显示 0（error+无旧值→「—」）、未配置→「—」+hint、zero 是真实 0、stale/error 徽标、todayView 估算徽标+未计价 hint、salvageView「未记账」token 快照。
- `bubble-schema.test.mjs`（10）：结构拒绝（v/items）、行合并边界（连续同 row 合并、**非连续同 row 不合并**、缺省 row=数组下标）、≤6 模块/行、≤6 行/页（6 过 7 拒）、图片独占行、choice ≤2 与正整数权重、text/random_text/image/style 键校验、lib 校验。
- `bubble-resolver.test.mjs`（10）：占位符缺失→「—」+missing 旗标、五类数据模块缺省/取值、random_text avoidIdx 换轴+MAX_REROLLS=6 封顶+单条不掷骰、choice 加权（注入 rng 确定性）且允许重复、stepIndex 环回、resolveAll、schema 错误冒泡、style 透传。
- `bubble-queue.test.mjs`（12）：rank 优先级与抢占（budget>turn_cost>waiting>info）、同 rank 先插入可见、dedup 替换且**不重置 ttl**、ttl 过期（注入时钟）、sticky 不过期、advance 仅 tapAdvance+环回+重置 ttl、dismiss 按 key/可见顶、waiting 抢占可逆、clear、view 携带 resolver 输入。
- `data-service.test.mjs`（7）：start 即刷+置 $dashboard ok、start 幂等、pokeSummary 2s 合流（注入时钟：1999 不刷 2000 刷）、start 前/stop 后 poke 安全、不可达→$dashboard unreachable+detail、stop 后零请求、floor 常量。
- `controller.test.mjs`（13）：click 序列→greeting 出现→tap advance→stepIndex 推进；combo≥4 入队 idle-line（见偏差 4）；turnSettled 入队/缺省「—」/turnCostEnabled=false 静音/自定义 ttl 过期；syncWaiting 开（sticky+mood）与关（回 idle）；press/release；tick 重发布；setData。
- `ingest-settled.test.mjs`（5）：onSettled 只在 settled 数组时以 (results, batchTurns) 触发、按批各自触发、无 settled/非数组保持旧行为、回调 throw 不破坏 flush、未提供回调时忽略。
- `main-wiring.test.mjs`（9，经 loader 加载**构建产物**+mock ctx）：floating pane 贡献（area/data/title/render→whale-widget-pane 根节点）+chip 保留；/config→dataService 起轮询（$balance/$summary 置值）；settled→turn:k1 泡泡「0.42 CNY」+money mood；无 settled→行为不变；clarify open/close POST 形状+非 clarify 静默；wait-event 失败静默且记账继续；wait-state 有 slots→waiting mood、失败→无等待不崩；dispose 后零 REST 流量。
- 既有 `register.test.mjs` 仅一处断言最小更新：原 `deepEqual(restCalls.paths, ['/health'])` 改为首调用为 '/health'+其余路径容忍（集成后 /config 等属合法新增面，在 main-wiring 中细断言）。

### 测试结果（全部真实输出）

- `npm test` → **185 passed, 0 failed**（既有 49 + WP-1 新增 109 + WP-3 sound-engine 27；node v22.19.0）。
- `node tools/build-desktop.mjs` → OK（`desktop/plugin.js` 53.6KB 单文件 ESM；`dist/desktop/plugin.js` 副本同步；`node --check` 通过）。
- `node tools/check-security.mjs` → OK；`.venv/Scripts/python.exe tools/check-security.py` → OK（97 文件）。
- `.venv/Scripts/python.exe -m pytest plugin-src/hermes-whale-widget/dashboard/tests -q --basetemp=.pytest-tmp-a` → **1 failed, 123 passed**：`test_ledger_accounting.py::test_acc01_usage_event_and_turn_cost_written` 失败原因为 WP-2 并发改动自身滞后——`whale_core/ingest.py:626-637` 已按 M8 契约给 accepted 响应加了 `settled` 数组，而该测试仍断言旧响应形状（无 settled）。**属 WP-2 文件，未修**；该失败同时实锤了 WP-1 消费的契约形状（{dedup_key, estimated_cost_units, currency, cost_basis}，1e8 定点，仅 accepted 响应携带），与 main-wiring/ingest-settled 测试的防御式消费一致。
- dev-preview：服务器与全部端点 curl 200（含 /config、/balance、/usage/summary、/wait-state、POST /ingest/turn 带 settled、POST /ingest/wait-event）；浏览器视觉走查本子代理无浏览器工具，留人工一次（`node tools/dev-preview.mjs` → pane 挂载于 pane-slot、余额 12.35 CNY、今日 4.56 CNY、window.__preview.errors 空）。

### 与 WP-2 契约的消费方式（跨包）

- `POST /ingest/turn` 响应 `settled: [{dedup_key, estimated_cost_units, currency, cost_basis}]`：**只在响应携带 settled 数组时处理**（`Array.isArray` 门），字段逐个防御（非有限数→null→「—」；'none' 币种→null；dedup_key 非字符串→null）；端点未就绪/字段缺失时行为与集成前完全一致。
- `POST /ingest/wait-event` body `{kind:'question', phase:'open'|'close', tool_id, session_id}`：失败静默。
- `GET /wait-state` → `{slots:[...]}`：非数组/失败→视为无等待。

### 偏差与备注

1. `desktop/src/core/ingest-client.js` 属「唯一允许改的 src 文件是 main.js」约束之外的改动——但任务交付 1 第 4 条明确要求给 createIngestClient 加 onSettled（最小改动：工厂参数 + 响应处理分支），已按任务书执行；该文件不在 WP-2/WP-3 所有权清单内，无冲突。
2. SUBSCRIBED_EVENTS 实际此前**未含** tool.start/tool.complete（任务书背景表述与 main.js 现状不符）——已按交付 5 的要求补上，register.test 的事件面断言随导出常量自动一致。
3. pane render 用 `jsx(WhalePane, {...})` 组件元素而非直接函数调用 `WhalePane({...})`：WhalePane/DataCard 内部使用 useValue hook，直接调用会在真实 React 渲染路径外破坏 hooks 语义；register.test 的「render 返回元素→type(props) 执行」模式不受影响。
4. **产品级观察（WP-owned 文件，未动）**：controller.click() 的 combo≥4 走 `queue.show('idle-line')`，但 idle-line 与仍存活的 greeting 同为 info rank（queue 同 rank 先插入者可见，且 tap advance 会重置 greeting 的 ttl）→ idle-line 实际被 greeting 遮住不可见。controller.test 按现状钉住并注释；建议后续在 controller/queue 层让 idle-line 顶替同 rank 或缩短 greeting。
5. turn_cost 的 config 键（reminders.turn_cost_enabled / bubbles.turn_cost_ttl_ms）暂未从 /config 喂给 controller（controller 工厂参数在创建时固化，而 config 是异步取回；任务书仅要求 dataService.start(config)）——当前用与 config 默认一致的内置默认，如需热更新需 controller 支持重配置（后续里程碑）。
6. wait-state 失败时按任务书「视为无等待」处理并调用 syncWaiting(false,false)（dismiss 等待泡泡）——若真实等待期间出现瞬时网络抖动，10s 内的下一次成功轮询会恢复；极端抖动下可能有短暂等待泡泡闪烁，属任务书语义的直接推论。
7. `tools/preview/preview-host.js` 在「dev-preview.mjs 如需最小改动」授权的延伸范围内（pane 贡献需要挂载点才能可视化验收），改动仅 +6 行。
8. 未 commit（按任务约束）；工作区中 dashboard/*、whale_agent/*、plugin.yaml、sound/* 等改动属 WP-2/WP-3 并行工程师。

### 下一阶段

真机冒烟（M5 计划项：ctx.rest POST 形状、tool.start/complete 与 message.complete 真实 payload 形状核对）；WP-2 test_acc01 断言更新后回归 pytest；M8-B/C 级 approval 提醒桥接；M10 素材替换占位 SVG。

## 2026-10-03 — M8 提醒（WP-2 Python 半体）：提醒规则引擎 + 等待桥 + 审批观察 hook

### Hook 探查结论（只读 D:\hermes，供本次实现钉死）

1. **hook 名称与语义**：`hermes_cli/plugins.py:144-148` — `VALID_HOOKS` 含 `pre_approval_request` / `post_approval_response`，为 **observer-only**（返回值被忽略，插件不能否决/预答审批）；kwargs = `command, description, pattern_key, pattern_keys, session_key, surface("cli"|"gateway"|"smart")`，post 追加 `choice`（once/session/always/deny/timeout/smart_approve/smart_deny/cancelled）与 `decided_by`。
2. **注册 API 与真实范例**：`hermes_cli/plugins.py:974-976` — `ctx.register_hook(hook_name: str, callback: Callable) -> PluginRegistration`；真实插件范式见 `D:\hermes\plugins\hermes-lcm\__init__.py:448-453`（`getattr(ctx, "register_hook", None)` 防御式注册 + 每项 try/except）。fire 点：`tools/approval_gateway_wait.py:147-152,198`（gateway 面）与 `tools/approval.py:912-917`（CLI 面）；`tools/approval_context.py:54-73` 会追加注入 `turn_id`/`tool_call_id`/`session_id` 并保证 dispatch 永不 raise（回调异常被 invoke_hook 吞掉）。
3. **运行位置**：审批 hook 在 serve 进程（与 dashboard 半体同进程不同线程，AUDIT §6.1）→ approval-state.json 的原子写 + 只读端天然安全，无需跨进程锁。

### 交付（全部在任务书文件所有权内）

- **`whale_core/notifications.py`**（实现替换占位）：`fire()`（INSERT OR IGNORE on dedup_key UNIQUE → `fired`/`duplicate`，DR-14 持久去重）、`pending()`（未过期未消除按 rank 排序：预算 1 > 预警 2 > 消耗 3 > 等待 4）、`active_dedup_keys()`、`dismiss()`、`dismiss_active()`（按 kind+前缀自动消除）、`count_all()`。payload 金额字段全部遵守 DATA_MODEL §8.1（estimated_*/observed_* + *_units + currency，无裸 cost/spend/used）。
- **`whale_core/rules.py`**（实现替换占位）：`evaluate_balance_low()`（`observed_balance_units < thresholds.balance_low` 触发，dedup `balance_low:{scope}:{day}`；回升 ≥ 阈值自动消除未过期通知；配置 None/非法 → 规则关闭；跨日重置）、`evaluate_daily_budget()`（逐 `daily_summary` usage 轨 scope 行比较 `estimated_cost_units ≥ thresholds.daily_budget`，dedup `budget:{scope}:{day}`，**币种永不合并**（DR-12）、NULL 桶跳过）、`evaluate_turn_cost()`（`reminders.turn_cost_enabled` 且已计价轮 ≥ `thresholds.turn_cost_min`（新 config 键，默认 None）→ dedup `turn:{turn_dedup_key}`，ttl 取 `bubbles.turn_cost_ttl_ms`；未计价轮诚实跳过）。阈值经 `pricing.to_units` 转定点，解析失败降级为「规则关」并告警。
- **触发 hook（最小插入，全部 try/except + log.warning 包裹，不改返回值/事务语义）**：`ingest.py` 结算成功路径末尾（`evaluate_turn_cost` + `evaluate_daily_budget`）、`balance_ledger.record_snapshot()` 末尾 commit 后（`evaluate_balance_low`）。
- **`whale_core/wait_bridge.py`**（实现替换占位）：question 槽位读写（whale_meta 键 `wait.question.<tool_id>` JSON `{session_id, since}`）、`approval_slots()` 读 `approval-state.json`（损坏/缺失 → []，fail-open）、`wait_state()` 合并输出并在读路径同步 wait 类通知（新挂起 → fire `wait:question:<tool_id>` / `wait:approval:<id>` ttl=0 常驻；解除 → 自动 dismiss「等待解除收泡」），fired_dedup_keys = 当前活跃通知键（前端重载对齐不补响）。
- **`whale_core/wait_api.py`**（新增，独立 APIRouter；`api.py` 一行 `router.include_router(wait_api.router)`）：`POST /ingest/wait-event`（回环守卫 + 严格白名单：kind/phase 枚举、tool_id/session_id 类型长度、**未知字段拒绝**——回答内容/密钥形态无法进账，畸形 → 400 且不回显值）、`GET /wait-state`（契约形状 `{question_slots:[{tool_id,session_id,since}], approval_slots:[...], fired_dedup_keys:[]}`）。
- **跨包 REST 契约（交付 2）**：`ingest.py` 响应新增 `settled` 数组——仅成功结算的 turn，字段精确为 `{dedup_key, estimated_cost_units(int|null), currency(str|null), cost_basis}`；duplicate/aligned/skipped 响应保持旧形状；batch 聚合 accepted 项。旧字段（status/accepted/duplicate/aligned/skipped）全部保留。
- **`whale_agent/approval_hook.py`**（实现替换占位，stdlib-only + 防御式复用 `whale_core.config.data_dir()`）：`_on_pre_approval_request` → 原子写 `approval-state.json`（`{approvals:[{id,kind,tool,since}]}`，**只含 id/kind/tool/since**，绝不写 command/description/pattern/secret；tmp + os.replace + 模块锁；≤32 条上限）；`_on_post_approval_response` → 精确 id 移除 + 会话前缀兜底（关联 id 缺失时按 session 清槽；审批阻塞会话，无名列串行）。仅 `surface == 'gateway'` 观测；回调与注册全部吞异常仅记日志。id = `<session>#<tool_call_id|turn_id|pending>`。
- **`__init__.py`（agent 半体入口）**：register(ctx) 按真实插件范式（hermes-lcm）接线 `register_approval_hooks(ctx)`，整体 try/except（注册失败仅记日志，插件照常加载）；**`plugin.yaml`** 增加 `provides_hooks: [pre_approval_request, post_approval_response]`（与实际注册一致，admission 规则 6）。
- **config.py**：DEFAULTS["thresholds"] 增加 `turn_cost_min: None`（最小改动）。

### 测试（全部真实输出；`--basetemp=.pytest-tmp-c`）

- `pytest plugin-src/hermes-whale-widget/dashboard/tests -q --basetemp=.pytest-tmp-c` → **180 passed, 0 failed**（本 WP 新增 44 条：test_reminders.py 25 + test_wait_state.py 19；既有 136 条回归全绿）。
  - REM 域覆盖：余额阈值触发/重复抑制/回升自动消除/同日静默/跨日再响；预算逐 scope 触发（币种不合并）/重复/跨日重置/开关；turn 通知开关/下限/未计价/turn-dedup 继承；重启模拟（reset_runtime 后重放 → duplicate 不重响，DR-14）；wait-event 挂起/解除/重放幂等/畸形 400×11/凭据形态 400/回环 403；wait-state 形状/多会话槽位/重复轮询不重复通知/审批槽位合并/损坏文件兜底；approval-state.json 原子写（无 tmp 残留）/隐私断言（文件中无 command/description/pattern 字样）/损坏兜底/前后向配对（精确 id + 会话前缀兜底）/多会话互不干扰/回调吞异常/注册缺失与注册失败静默/plugin.yaml provides_hooks 声明；hook 崩溃不破坏结算与记账（monkeypatch 抛 RuntimeError → 200 + 行照写）；REST 命名 lint（ingest 响应/wait-state/通知 payload 全查 `find_bare_money_keys` == []）。
- `node tools/check-security.mjs` → OK；`.venv/Scripts/python.exe tools/check-security.py` → OK（99 文件）。

### 跨包契约确认（WP-1 消费面）

1. `POST /ingest/turn` 成功响应 = 旧字段 + `settled: [{dedup_key, estimated_cost_units(int|null), currency(str|null), cost_basis}]`；duplicate/aligned/skipped 响应**不含** settled 键（旧形状逐键不变）。
2. `POST /ingest/wait-event` body 白名单 = 恰好 `{kind:'question', phase:'open'|'close', tool_id, session_id}`；未知字段/枚举外值/类型错 → 400（信息只含字段名）；open/close 均幂等可重放。
3. `GET /wait-state` = `{question_slots:[{tool_id,session_id,since}], approval_slots:[{id,kind,tool,since}], fired_dedup_keys:[...]}`；fired_dedup_keys 含当前活跃通知 dedup（含 wait/turn/budget/balance_low 类）。
4. `approval-state.json` 位于插件数据目录（`<HERMES_HOME>/whale-widget/`），条目仅 `{id,kind,tool,since}`；缺失/损坏对 /wait-state 无害（空列表）。
5. desktop 若需在重载后对齐「已响」标记：以 /wait-state 的 fired_dedup_keys 为准（通知表持久化，DR-14）。

### 偏差与说明（实现 vs 任务书/既有测试）

1. **既有测试 2 处断言机械更新**（test_ingest_contract.py::test_batch_shape_counts、test_ledger_accounting.py::test_acc01_*）：二者以 `==` 钉死旧的 accepted 响应形状，与交付 2「响应新增 settled」直接冲突且不可兼容（pytest 全绿是硬约束）。仅把整字典相等断言改为「旧字段断言 + settled 数组存在性」，未改动任何测试语义/场景；其余既有测试文件未动。
2. **balance_low 去重键采用任务书口径** `balance_low:{scope}:{day}`（DATA_MODEL §2.10 的 `low:<scope>:<threshold>` 与计划的「恢复后删键可再响」迟滞语义被任务书取代）：回升≥阈值只自动消除未过期通知（显示层迟滞），同日再跌破不重响（DR-14 优先），次日键重置后再响。已用测试钉死。
3. **wait-event 在 open/close 时同步维护 wait_input 通知**（fire/dismiss，dedup `wait:question:<tool_id>`）：任务书只要求槽位增删，但 IMPLEMENTATION_PLAN M8 任务 2 明确「交 Python 统一写 notification（wait:question:<tool_id>）」，且 fired_dedup_keys 需要它才有对齐语义——按计划补齐，测试钉死不重复响。
4. **GET /wait-state 读路径同步 wait_approval 通知**（新 id → fire、消失 id → dismiss）：IMPLEMENTATION_PLAN M8 任务 3 要求「新挂起 id → notification 行」；INSERT OR IGNORE 保证 1s 轮询零重复。任务书未列，按计划补齐。
5. **审批条目字段收窄**：IMPLEMENTATION_PLAN M8 写「id/command/description/session_key/ts」，任务书明确收窄为「只含 id/kind/tool/at」——按任务书执行（更严格的隐私边界），`since` 即时间戳；session_key 编码进 id 前缀以支撑配对与兜底清槽，不单独落字段。
6. **今日预算的口径**：按任务书「usage 轨当日 estimated_cost_units 合计」实现为**逐 daily_summary scope 行**（scope=usage:<profile>:<currency>，行内即当日合计）比较，跨币种不求和（DR-12「币种不一致不比较」）；预算配置无币种字段（budget 表/UI 属 M12），数值直比。
7. **未计价轮（token_only）不发 turn_cost 通知**：estimated_cost_units 为 NULL 无从与下限比较、也无金额可展示；泡泡链路若需「本轮 —」可后续在消费端处理。
8. 未 commit（按任务约束）；未触碰 desktop/src、desktop/tests、desktop/plugin.js、sound/（WP-1/WP-3 所有权）；tools/preview、main.js、ingest-client.js 等工作区改动属并行工程师。

### 未解决问题 / 下一阶段

- 真机冒烟（用户配合）：clarify tool.start/complete → /ingest/wait-event 端到端；approval hook 在 gateway 面触发一次审批 → 等待泡出现 → 批准收泡；`session_id` 与 gateway `session_key` 的对应关系核对（审批 hook 只拿 session_key）。
- 通知 WS 推送未接（MVP 用 3s/1s 轮询 fallback，OAuth remote 本就必需）；/notifications REST 端点留待 M7/M8 桌面接线需要时再加（查询函数已备）。
- 预算/阈值设置 UI、budget 表实体 CRUD 属 M12；当前 thresholds 走 config.json。

## 2026-10-04 — MVP 收口（M0-M8 全绿；三工作包并行 + 主会话集成）

- 并行工作包（用户恢复子代理配额后三路并行，文件所有权严格隔离）：
  - WP-1（desktop 集成）：main.js 完成 floating pane 注册（PANES_AREA + placement floating）、controller/dataService 接线、clarify→/ingest/wait-event 转发、wait-state 10s 轮询、ingest 响应 settled→每轮消费泡泡（防御式消费）；新增 10 个测试文件 109 条。
  - WP-2（M8 Python）：notifications/rules（余额预警/每日预算/每轮消费，DR-14 持久去重）、wait_bridge+wait_api（/ingest/wait-event、/wait-state）、whale_agent approval hook（hermes_cli/plugins.py:144-148 observer-only 签名核实）、ingest 响应 settled 契约；新增 44 条测试。
  - WP-3（M9 核心）：Web Audio 引擎（DSH 语义全量：同步起播/−40ms 衔接排期/音量三态/mute/60s suspend/缓存），27 条测试，未接线（后续集成）。
- 合并回归（主会话）：npm test **185 passed**、pytest **180 passed**、构建+node --check+双重安全自检全部 OK。
- README 已实现/未实现/已知限制与命令节已回填。
- 遗留：音效接线、combo≥4 idle-line 同 rank 遮挡（WP-1 观察）、M10-M13。

## 2026-10-04 — Goal Completion 收尾（P0×2/P1×2/P2×2 全部关闭）

- **状态审计**发现两处 P0 级集成断点（两模块各自测试通过但从未真实连接）：
  1. main.js pollWaitState 读 `data?.slots`，实际契约是 `{question_slots[], approval_slots[]}` → 等待提醒全链路静默失效；
  2. rules 引擎通知只写表，无 /notifications 端点、无桌面消费者 → 三类提醒永不显示。
- 修复：wait-state 真实契约 + question/approval 分离；新建 notifications_api.py + 挂载 + 桌面 10s 轮询→泡泡（wait_* 跳过防双显、常驻类恢复自动消除）；M9 音效接线（attachSoundEngine + controller 挂点，config.sound 默认关）；combo≥4 遮挡修复；删除零引用 pricing.js；4 处过时 STUB 头注释改为如实归属。
- 并行收尾：WP-docs（INSTALL.md 11 节 + USER_FLOW_CHECKLIST 10 流程 + README/catalog 同步）+ WP-e2e（4 场景端到端测试：记账主流程精确到 60_000_000 units、余额预警触发/恢复、等待 open/close/畸形、预算跨日重置）。
- 最终门禁：node **190**（3 连跑稳定，flake 已用 flushAsync 加固）/ pytest **188** / build + node --check + 双重安全自检全绿。
- 产出：REMAINING_WORK.md（P0-P3 全部标记 FIXED/VERIFIED/DEFERRED-BY-DESIGN）、FINAL_VALIDATION.md（验收矩阵）、FINAL_GOAL_REPORT.md。
- **DoD 结论**：环境内可达范围全部达成；真机端到端 NOT VERIFIED（D:\hermes 只读约束），执行路径已备（INSTALL.md + CHECKLIST 人工步骤）。

## 2026-10-04 — WP-ui：desktop 半体去角色化（鲸鱼管家面板，DR-15 宿主化）

- 背景决策：不再自建宠物角色，角色由 Hermes 内置宠物系统承载（穿我们的鲸鱼皮肤包，唯一合法接口 = 皮肤包文件，见 docs/research/HERMES_PET_SYSTEM.md §3-4）；floating pane 改造为「鲸鱼管家」随身账本面板。
- 改造点（全部限 desktop/src + desktop/tests + WORKLOG）：
  - **`desktop/src/ui/whale-pane.js` 重写**：移除 WhaleActor 渲染；结构 = 标题行「🐋 鲸鱼管家」+ mood→强调色小圆点（`data-mood` 属性 + aria-label）+ BubbleLayer + DataCard（原样）；面板注释写明角色承载语义（HERMES_PET_SYSTEM.md）与「拖到宠物旁」使用建议（title 提示）。press/release/click 接线保留并**升级为整面板交互面**（原挂在自建鲸鱼 actor 上，actor 退役后改挂面板根 div，role=button + tabIndex 0），点击面板 = 泡泡交互 + 音效挂点不变。
  - **`desktop/src/ui/whale-actor.js` 删除**（退役）：grep 全仓确认代码引用仅 whale-pane（已重写）与生成产物（已重建）；core/whale-state.js 状态机原样保留，继续驱动泡泡与面板强调色。
  - **`desktop/src/ui/controller.js`**：mood 发布不变；新增导出纯函数 `moodAccent(mood)`（idle #6b7280 灰 / press #3f97de 蓝 / happy #2e7d32 绿 / money #0891b2 青 / waiting #e8a13a 黄；未知 mood 回落 idle 灰）。
  - **`desktop/src/main.js`**：pane 注册 title 改「Whale Wallet 管家」；self-check toast 改「Whale Wallet 管家已加载（角色 = Hermes 内置宠物；…）」；头注释新增 Pet hosting (DR-15) 段落 + 2 处 "whale face" 注释改为 mood→泡泡/强调色表述；其余逻辑（M1 管线/轮询/事件面）零改动。
- 测试（全部真实输出）：
  - npm test → **195 passed, 0 failed**（原 190 + 新增 5，两次连跑稳定；无失败、无跳过）。新增：tests/whale-pane.test.mjs（3 条：去角色结构断言——树内零 whale-actor/零 SVG、标题行+accent 圆点、整面板 press/release/click 接线 + greeting 泡泡渲染；accent 圆点随状态机 press/waiting/idle 变色）；controller.test.mjs 增 moodAccent 映射 2 条。更新：main-wiring.test.mjs pane title 断言 'Whale Widget' → 'Whale Wallet 管家'。
  - `node tools/build-desktop.mjs` 重建产物（68,967 bytes）+ `node --check` 通过；产物内 0 处 WhaleActor/whale-actor 残留（dist/ 同步复制）。
  - `node tools/check-security.mjs` → OK；`.venv/Scripts/python.exe tools/check-security.py` → OK（97 文件）。
  - pytest `--basetemp=.pytest-tmp-u` → **188 passed**（Python 半体不受影响，按任务要求回归确认）。
- 偏差与说明：
  1. **press/release/click 从「鲸鱼图形」改挂「面板根节点」**：任务书要求保留接线且"点击面板=泡泡交互+音效"，actor 退役后交互面唯一合理落点是面板本体（role=button/tabIndex 保持可键盘聚焦）；DataCard 文本因 `userSelect:'none'` 不可划选——交互面语义优先。
  2. **标题行文案「🐋 鲸鱼管家」≠ 注册 title「Whale Wallet 管家」**：前者是面板内标题行（任务书指定），后者是 SDK floating 卡片注册 title（任务书指定），二者按任务书原文各自保留，未强行统一。
  3. **删除退役断言后总数不降反升（190→195）**：whale-actor 原本无专属测试文件（退役零断言损失），新增 5 条全为净增；满足"不许有失败"硬约束。
  4. **moodAccent 颜色取值**：任务书只给语义（灰/蓝/绿/青/黄）未给色值；按项目既有调色板选值（蓝 #3f97de、黄 #e8a13a 沿用原 actor 徽标色，绿/灰沿用 balance-view tone 色），青色 #0891b2 为新增，纯函数映射测试钉死，后续可无风险调整。
  5. **重建产物与 dist/ 副本**属 build 脚本输出（任务书明确要求重建），未手工编辑。
  6. 未 commit（按任务约束）；未触碰 docs/design/、INSTALL.md、README.md、tools/build-whale-pet-pack.py、assets/（WP-docs 与主会话所有权）。
- 未解决问题 / 下一阶段：真机冒烟（面板拖到 Hermes 宠物旁的视觉组合、accent 圆点可读性）待用户配合；upstream 提案（host.pet.say/react/setActivity，HERMES_PET_SYSTEM.md §4-4）落地后面板泡泡可迁移为官方宠物泡泡。

## 2026-10-04 — WP-docs 完成：宠物宿主化文档（DR-15 配套六件套）

### 完成了什么

- **ARCHITECTURE_DECISION.md**：DR 表新增 DR-15（修订 of DR-4 窗口形态目标）行；文末新增「§11 修订 2026-10-04：宠物宿主化（DR-15）」——背景（用户决策：不再自建宠物角色）、候选比较（A 自建角色面板〔放弃：与内置宠物角色重复〕/ B 皮肤包+管家面板〔选定〕/ C monkey-patch 内部 store〔禁止：AGENTS.md §10 + blob ESM import 白名单事实不可达〕/ D upstream API〔未来：已提案不实施〕）、选 B 五条理由、与 DR-1~14 逐条关系表（仅 DR-4 修订）、修订组件图（官方宠物窗口 ←皮肤包；管家面板 ←泡泡/数据/提醒；并列摆位）、皮肤包=用户数据定性（§11.6）、新增待验证项（§11.7）。
- **FEASIBILITY_REPORT.md**：§3 追加 §3.1 Hermes Pet API upstream 提案——`host.pet.say(lines,{ttl})` / `host.pet.react(kind)` / `host.pet.setActivity(patch)` / `host.pet.getBounds()`；动机附 file:line 证据（SDK 零 pet 导出、泡泡硬编码 pet-bubble.tsx:33-67、姿态纯派生 pet.ts:107、pet RPC 核心内部 tui_gateway/server.py:180，全引 [PET] 调研）；Without it 替代 = 管家面板并列摆位。
- **INSTALL.md**：新增 §12「宠物皮肤（可选，推荐）」（内置宠物系统说明 / 构建 `tools/build-whale-pet-pack.py` → 用户复制 `assets/whale-pet-pack/` → `D:\hermes\pets\whale\` → 图库选择 → 确认鲸鱼 → 面板拖到宠物旁；`/pet-generate` 替代提示 "cute pixel whale"；回退 = 删目录；与管家面板配合）；§2/§6/§10 三处最小同步（管家面板措辞、去角色化后的素材语义）。
- **README.md**：项目状态追加 DR-15 轮次说明；功能清单加「宿主角色 = Hermes 内置宠物（鲸鱼皮肤包）」；已实现/未实现/已知限制同步（管家面板去角色化、M10 收窄为音效与面板素材、宠物泡泡不可注入、Phase 2 独立窗由宠物窗承接）；核心目录 research 行补 HERMES_PET_SYSTEM；安装速览表加宠物皮肤行。
- **REMAINING_WORK.md**：追加 P1-3 宠物宿主化（本轮交付 FIXED；真机宠物装载 NOT VERIFIED 待用户执行）。

### 设计变化 / 与既有决策关系

- DR-15 只修订 DR-4 的窗口形态目标（OS 级常驻角色改由 core 宠物窗承接，pywebview 独立窗降为后备）；DR-1/2/3/5/6/7~14 不变（记账/凭据/泡泡解耦/归一化/生命周期均与角色无关）；DR-10（排除改 Core）重申一致——候选 C 出局、D 仅记录提案不实施。
- 皮肤包定性为用户数据（非代码）：装 `<HERMES_HOME>/pets/<slug>/`，不进插件代码目录与 catalog SHA 面（§7.3 发布/回收不触碰）；插件运行时零依赖（缺失 = 纯外观回退）；写入 `D:\hermes` 由用户执行（AGENTS.md §0）。
- 与 WP-ui 并行条目的衔接：管家面板去角色化已由 WP-ui 落地（whale-actor 退役、mood→强调色，node 195 / pytest 188）；本文档层与之对齐（INSTALL §6 验证行、README 已实现措辞均按「管家面板」表述）；WP-ui 未覆盖的 `host.pet.getBounds()` 一并纳入 §3.1 提案（供面板吸附摆位）。

### 测试结果

- 纯文档轮：无代码/测试改动，未构建、未跑测试（不影响 node 195 / pytest 188 基线）；未 commit（任务约束）。
- 未触碰 `desktop/src`、`desktop/tests`、`tools/`、`assets/`、`plugin-src/`（并行工程师/主会话所有权）。

### 未解决问题 / 下一阶段

- 真机宠物装载三步（复制→图库选择→桌面确认鲸鱼）与「面板拖到宠物旁」视觉组合，待用户执行（INSTALL.md §12）。
- 皮肤包生成器 `tools/build-whale-pet-pack.py` 与 `assets/whale-pet-pack/` 产物由并行/主会话交付，文档已按既定路径引用；若路径/命名有变需回改 INSTALL §12 与 README。
- upstream Hermes Pet API 提案跟进（FEASIBILITY_REPORT §3.1）；采纳前宠物泡泡文字不可注入，维持并列摆位。

## 2026-10-04 — 宠物宿主化（DR-15）：内置宠物为角色 + 管家面板

- **调研**（docs/research/HERMES_PET_SYSTEM.md，全部 file:line）：内置宠物 = Python agent/pet/（皮肤包存储 pets/<slug>/ + petdex 目录 + AI 生成管线）+ 桌面 pet/pet-overlay/pet-gallery store（姿态状态机 idle/wave/run/failed/review/jump/waiting 随会话状态派生 + 弹出式透明窗 + 宠物泡泡〔文字硬编码〕）。**SDK 对宠物零导出，唯一合法接口 = 皮肤包文件**。
- **鲸鱼皮肤包**：tools/build-whale-pet-pack.py（纯 stdlib PNG 编码器 + 参数化像素鲸鱼，9 姿态 × 6 帧，Codex 规格 1536×1872 已断言）→ assets/whale-pet-pack/{pet.json, spritesheet.png}；帧视觉自查通过（experiments/pet-frame-*.png）。安装由用户执行（复制到 D:\hermes\pets\whale\ + 图库选择）。
- **WP-ui（子代理）**：desktop 去角色化——whale-actor.js 退役，floating pane 改造为「🐋 鲸鱼管家」面板（泡泡层+数据卡+音效+mood 强调色 moodAccent()）；node **195** passed。
- **WP-docs（子代理）**：ARCHITECTURE_DECISION DR-15 修订（候选比较+组件图+用户数据定性）、FEASIBILITY upstream 提案（host.pet.say/react/setActivity/getBounds）、INSTALL §12 宠物皮肤节、README/REMAINING_WORK 同步。
- **门禁**：node 195 / pytest 188 / build + 双重安全自检全绿。真机宠物装载 NOT VERIFIED（待用户复制皮肤包并选择）。

## 2026-10-05 — DR-16：宠物本体交互层（点击内置宠物 → 鲸鱼挂件交互）

- 用户纠偏：交互必须长在宠物本体上，不要分离面板。调研补强：PetSprite 为 `<canvas aria-label="… pet">`（官方 a11y 属性 = 稳定跨皮肤定位锚）；react-dom 不在 import map → 原生 DOM 层 + nanostores 直订阅。
- 交付 `desktop/src/ui/pet-layer.js`：捕获阶段 pointer 监听（tap/拖拽 slop=6px 判定，拖拽留给核心）+ `canvas[aria-label$=" pet"]` 定位器 + 跟随宠物（游走/拖动 rAF）的泡泡宿主（视口钳制、下方翻转）；点击宠物 = controller.click()（泡泡序列+音效），bubble 本体可点继续步进。
- 管家面板降级为可选：config.pane.enabled（默认 false）时才注册；$balance/$summary 订阅喂 resolver 占位数据（两渲染面共用）。
- 门禁：node **205**（+10：tap 判定/命中/放置/定位器/样式映射）/ pytest 188 / build + 双重安全自检全绿。
- 边界：弹出态宠物 overlay（独立窗口）不可交互——upstream host.pet.* 提案的正当时机。

## 2026-10-05 — WP-matrix：DSH 功能复刻矩阵（docs/design/DSH_REPLICATION_MATRIX.md 新建）

### 完成了什么

- 新建 `docs/design/DSH_REPLICATION_MATRIX.md`：将 DSH 六大系统（记账与显示 33 项 / 交互 13 项 / 泡泡 23 项 / 提醒 10 项 / 音效·角色·图片 15 项 / Provider+设置 18 项）共 **112 项功能逐行对照本项目代码现状**，每行给出复刻状态（✅/🔶/🔜/❌）+ file:ref 证据 + 差距理由或补齐路径与量级（S/M/L）。
- **全部「已复刻」判定基于本轮真实代码核对与测试复跑**（非照抄文档）：
  - `node --test`：**205 条 / 204 通过 / 1 失败**——失败为 `desktop/tests/main-wiring.test.mjs:70`「pane 注册」断言，系 DR-16 把 pane 改为 config 载入后条件注册（默认关）后断言未同步，属测试过期非功能回归（已在矩阵 §6 附注标注）。
  - `pytest`：**188 passed**。
- 汇总统计（文首汇总表）：✅ **59**（52.7%，含「由 Hermes 宿主核心原生承接」并注明承接面）｜🔶 **14**｜🔜 **30**｜❌ **9**（吸附①/翻转①/透明像素穿透①/自定义角色①/移动端②/默认素材③/滚轮让位③/IME③/DSH 宿主适配层③）。
- 文末「复刻优先级建议」：V1 队列 8 项（设置 UI M12 / 点击刷新接线 / 7 日历史+模型占比 UI / bonus·recharge·link 模块 / 滚动动画+变化泡泡 / OS 通知 / 真机冒烟 / 红测修复），V2 队列 6 项（泡泡编辑器 L / 34 provider 模板 M~L / 峰谷电价 M / 图库+音效素材 M / track③ / upstream pet API），逐项标注量级并引用 REMAINING_WORK（P3-1/P3-2/P3-3/P3-4/M10/M11/M12/M13）。
- ❌ 判定全部按任务要求落到机制：① Hermes 核心所有权（SDK 零 pet 导出 [PET] §3、窗口 deny-all `window-open-policy.ts:74-93`、透明窗核心专用 `electron/main.ts:1506-1509`、pet RPC 核心内部 `tui_gateway/server.py:180`）；② 平台机制缺失（Hermes 无移动端宿主）；③ DSH 特有技术/素材依赖（素材不在 MIT 不可再分发 [DSH] §G、tapIndex/composer/滚轮/IME 为 DSH 宿主页面级 hack）。每条均给最接近替代方案（皮肤包+petdex+/pet-generate、a11y 锚点跨皮肤通用、ctx.os.openExternal 等）。

### 设计变化 / 与既有决策关系

- 无架构决策变更：矩阵是对 DR-1~16 现状的**盘点与排期输入**，不新增 DR；文中如实记录三处「实现与 DSH 语义有差异」供后续决策——① balance_summary 跨 scope 合并 vs DSH「历史本不合并」（多 key 前需拆，S）；② 等待档 rank=4 排队不抢占 vs DSH 等待档抢占（对齐 3 行，S）；③ 自定义 USD 单价不折 CNY vs DSH 折算统一记 CNY（DR-12 有意为之）。
- 新发现并记录两处待办：泡泡定义尚未持久化（config.py 无 items 键，编辑器前置，S）；notifications KINDS 已预留 balance_change 但无 fire 方（S）。

### 测试结果

- 纯分析文档轮：零代码改动、未构建、未 commit（任务约束）。测试复跑仅作现状基线取证：node 204/205（1 条过期断言红，见上）+ pytest 188 全绿，与 REMAINING_WORK 基线（node 205 / pytest 188）一致。
- 只写文件：`docs/design/DSH_REPLICATION_MATRIX.md`（新建）+ 本 WORKLOG 追加条目。

### 未解决问题 / 下一阶段

- 3 条 NOT VERIFIED 真机项（皮肤包装载 / 宠物点击端到端 / 部署链路）仍待用户执行——矩阵 V1 队列第 7 项。
- main-wiring 红测断言需随 DR-16 更新（V1 队列第 8 项，归代码轮处理）。

## 2026-10-05 — WP-dashboard 完成：应用内 Whale Wallet 面板 + providers REST + 泡泡选择性余额

### 完成了什么

- **Python 半体（REST 新面，whale_core/providers_api.py 新建）**：
  - `GET /providers/status` → `{providers:[{provider_id, known, configured, source, credential_id?, fingerprint?, state?, observed_balance_units?, currency?}]}`：遍历 registry.known_ids()，逐家合并 gateway.credential_status 与 balance_ledger.balance_state（五状态）；未配置行 state='unknown' 且绝无 credential 字段；observed_balance_units/currency 仅在真实观测存在时出现（缺失 ≠ 0）。
  - `GET /balance/all` → 同行形、仅 configured（泡泡余额数据源）。api.py 一行挂载（include_router + import 行内追加）；运行时经函数级 `from .api import _require_ledger` 复用懒初始化与 fail-closed 503（同 wait_api/notifications_api 模式）。
  - `whale_core/config.py` DEFAULTS 新增 `bubble: { balance_providers: [] }`（泡泡显示白名单；空 = 显示全部 configured；PUT /config 白名单因此放行该节）。
  - 契约测试 `tests/test_providers_api.py`（7 条）：行形/未配置无凭据字段/balance_all 过滤/ok+error 保持 last known/凭据不泄漏（fake key 不出现在响应）。
- **desktop（dashboard.js 新建，main.js 仅追加接线）**：
  - `createDashboard({ rest, host, atoms })` → `{contribution, navContribution, wrapChip}`：routes 页（id 'dashboard'，title 'Whale Wallet'，data.path '/whale'，契约对齐 app/routes.ts:88-117）+ sidebar.nav 数据行（data: {path, label, codicon:'credit-card'}，形状对齐 routes.ts:131-139）+ 状态栏芯片点击包装（host.navigate 存在性 feature-detect，无 navigate 时退化为纯展示 span）。
  - 页面 8 区块（纯 inline style，无 tailwind；SDK 组件 Button/ToggleRow/Select 系列/EmptyState/ErrorState；tone 色复用 balance-view 语义）：①头部（🐋 Whale Wallet 用量 + /health 连接点 [$health atom] + 刷新按钮 = version atom bump + invalidateQueries）；②余额卡（/providers/status 每家一张：五状态语义 ok=金额绿 / stale=金额+灰「未刷新」/ error=last known+⚠「获取失败」/ zero=实测 0 青 / 未配置=「—」+引导；每卡 POST /balance/refresh 手动刷新 + ToggleRow「泡泡显示余额」→ PUT /config 写 bubble.balance_providers，乐观更新运行时 atom、失败回滚 + host.notify）；③今日概览（estimated_today_units 大字 + 「估算」角标 + turns/五类 tokens/未计价数）；④N 日柱状图（7/14/30 Select；高度按日 estimated 归一化；token_only 虚纹柱；hover title 出数值/部分观测/N 轮未计价）；⑤模型分布表（轮次 desc→估算费用 desc，五类 token 列）；⑥最近轮次前 20（模型/时间/费用/final·provisional 着色）；⑦价目表（builtin+custom 双表 + notes，unverified 标注说明）；⑧泡泡显示规则脚注。加载/错误/空态齐全（真实 REST 数据，零假数据）。
  - 页面无 react hooks：状态全在 nanostores atom（$version/$chartDays/$refreshing 每实例）+ useValue/useQuery/useQueryClient。
  - main.js：注册 routes 页 + sidebar.nav 行；芯片 render 包 `dashboard.wrapChip(renderWhaleChip(...))`；`$bubbleProviders`/`$bubbleBalanceText` 两个新模块 atom 导出；loadUiConfig 启动时用 config.bubble.balance_providers 播种（DEFAULT_UI_CONFIG 镜像加 bubble 键）。
  - **泡泡选择性余额（交付 3）**：syncDisplayData 改为 pushDisplayData + refreshProviderBalances——优先 GET /balance/all（15s 节流，吃轮询顺车、零新定时器），行按 $bubbleProviders 过滤（空 = 全部），`bubbleBalanceText` 拼 `deepseek ¥1.10 | openai $0.42`（' | ' 连接）喂 controller.setData.balanceText；/balance/all 不存在（旧 Python 半体）或失败 → 粘性回退单 /balance 原文本路径；setData 契约不变。
  - 生命周期卫生：三个 atom 订阅的 unsubscriber 收集进 onDispose（修复多 register 场景下共享 atom 的陈旧监听者）。
- **测试**：dashboard.test.mjs 新建 27 条（纯逻辑 + fake host/rest，无 DOM）：show-list 归并过滤 / 余额文本拼接（含多 provider ' | '）/ 五状态卡 VM / toggle 物化语义 / 柱高归一化（max=100%、半值 50%、null=0、全空无 NaN）/ today 卡 / 模型排序 / createDashboard 三贡献形状 + 芯片跳转/降级。

### 设计变化 / 与既有决策关系

- 芯片点击 → host.navigate('/whale') 采用「包装而非改写」：statusbar.js 零改动（不在本 WP 所有权内），renderWhaleChip 原样作为 children。
- 隐藏列表落 config.bubble.balance_providers（非 ctx.storage）：泡泡数据源跨重启生效 + 与主会话文档契约一致；JS 侧 $bubbleProviders 仅为运行时镜像（AGENTS §8 JS 不持久化）。
- 手动刷新沿用既有 POST /balance/refresh（当前 API 不带 provider_id，仅刷新默认 provider；registry 现仅 deepseek，无功能缺口）。
- **修复 V1 队列第 8 项**：main-wiring 面板红测随 DR-16 语义更新——pane 注册是 config 门控异步行为，测试改为 restImpl 开 pane.enabled + await config 落地后断言；makeCtx restImpl 支持 undefined 落回默认链。
- react/jsx-runtime 自动运行时纪律：jsx(type, props, key) 三参封顶、children 一律进 props（本 WP 初稿曾用 varargs children，自动运行时静默丢弃——已全文件修正，此坑对后续 jsx() 手写代码是个警示）。

### 测试结果

- npm test → **237 passed, 0 failed**（基线 205 + dashboard 27 + main-wiring 新接线 5；两次连跑稳定）。
- build（node tools/build-desktop.mjs，产物 114,407 bytes + dist/ 副本）+ `node --check` 通过。
- 双重安全自检：tools/check-security.mjs OK（import 白名单/无禁用模式/无凭据形状）；tools/check-security.py OK（104 文件）。
- pytest `--basetemp=.pytest-tmp-d` → **195 passed**（188 + test_providers_api.py 7 条）。
- 更新的既有测试（最小改动）：main-wiring.test.mjs（makeCtx 增 /balance/all 等默认响应 + fall-through；面板红测按 DR-16 修复；新增 routes/nav/芯片跳转/泡泡文本/回退 5 条）；register.test.mjs（芯片断言加 peel 导航包装 helper，文本断言不变）；tests/shims/sdk-shim.mjs（增量：ROUTES_AREA/SIDEBAR_NAV_AREA/host.navigate/useQuery/useQueryClient/组件空 stub——原有导出零改动）。

### 偏差与说明

1. sdk-shim.mjs / register.test.mjs 不在任务书所有权清单内，但为「npm test 全绿」硬约束所必需（新增 SDK 具名导入 + 芯片包装改变渲染树形状）；全部为增量/最小改动，未动并行工程师的 pet-layer.js / bubble/defaults.js / docs 其它文件。
2. 面板红测（V1 队列第 8 项）一并修复：该断言在 DR-16 面板改 config 门控后即无法同步通过，属遗留红测，非本轮引入。
3. `bubble.balance_providers` 的「隐藏最后一个 → 列表变空 = 回到显示全部」是「空=全部」契约的固有语义，无法表达「全部隐藏」；页面脚注已说明规则。
4. 未 commit（按任务约束）；未触碰 docs 其它文件 / INSTALL / README。
- 未解决问题 / 下一阶段：真机冒烟（/whale 页面视觉、泡泡多 provider 文本「deepseek ¥1.10 | …」实际渲染、PUT /config 回写）待用户配合；M11 provider 泛化后 /providers/status 行形若扩展需同步 dashboard.js providerCards。

## 2026-10-05 — 三项增强：agent 面板 / DSH 大泡泡 / 复刻矩阵

- **WP-dashboard（子代理）**：`/whale` 应用内页面（routes area + sidebar.nav 侧栏入口 + 状态栏芯片点击跳转 host.navigate）——余额卡五状态语义 + 手动刷新 + **泡泡余额显示/隐藏切换（持久化 bubble.balance_providers）**、今日概览（估算角标）、7/14/30 日 CSS 柱状图、模型分布表、最近轮次、价目表；新 REST：GET /providers/status、GET /balance/all（泡泡数据源，多厂商前向兼容）。node 237 / pytest 195。
- **主会话（DSH 大泡泡）**：宠物泡泡升级 DSH 规格——maxWidth 260→420px、字号 12→14、内边距 12×16、圆角 16、**指向宠物的菱形尾巴**（reposition 时按上/下位置翻转朝向）+ 默认内容字号整体上调；renderer（可选面板）同步。
- **WP-matrix（子代理）**：`docs/design/DSH_REPLICATION_MATRIX.md`——112 项逐条对齐：✅ 59 / 🔶 14 / 🔜 30 / ❌ 9（❌ 三大类：核心所有权〔宠物姿态/吸附/翻转/图库〕、平台缺失〔移动端〕、DSH 特有〔素材不可再分发 + 宿主 DOM hack 无对应面〕，全部附 file:line 或约束条款证据 + 替代方案）。
- 门禁：node 237 / pytest 195 / build + 双重安全自检全绿。

## 2026-10-05 — 部署阻塞修复：plugin.yaml YAML 解析错误（用户批准后执行）

- 症状：插件加入 plugins.enabled 后 serve 报 `Could not read plugin manifest ...: mapping values are not allowed here (line 3, column 116)`。
- 根因：plugin.yaml 第 3 行 description 为未加引号的 YAML 纯量，内含 `package: agent` 的「冒号+空格」→ 解析器视为映射分隔符。桌面半体不读此文件，故此前宠物交互正常；加入 enabled 白名单后 serve 首次解析即命中。
- 已排除：provides_hooks 字段写法正确（plugins_manifest.py:33 白名单/:350/:550 实证）；catalog yaml 无同类病灶。
- 修复：description 加双引号；新增 `dashboard/tests/test_plugin_manifest.py` 三条回归门（manifest 字段对齐 Hermes schema、原始文本级「未加引号冒号」tripwire、catalog 必填字段/SHA 引号）；PyYAML 入项目 venv 并加安全白名单。
- 已同步：修复后的 plugin.yaml 已复制到 D:\hermes\plugins\hermes-whale-widget\plugin.yaml（MD5 双侧一致，用户授权路径）。
- 门禁：node 237 / pytest 198（+3 回归门）/ 双重安全自检全绿。
- 待用户：重启 Hermes 验证（芯片 ●、/whale 面板与宠物泡泡出真实金额）。

## 2026-10-05 — agent 半体"装不上"根因：plugins.enabled 白名单缺失（已修复）

- 排查：修复 YAML 后的 pm sync 回执已 `ok`；plugin-check 将 hermes-whale-widget 归类 `manual`（与正常的 hermes-vault 同类）→ manifest 层已通。
- 官方规则（AGENTS.md + hermes_cli/plugins.py:1550+ 实证）：手动本地插件安装 = 文件夹就位 + **plugins.enabled 加 manifest 名或目录名** + 重启；enabled 名匹配 `{目录名, manifest.name}`（对照 hermes-lcm→hermes-lcm-x）。
- 根因：config.yaml 的 enabled 列表既无 `whale-widget` 也无 `hermes-whale-widget` → serve 从不导入 agent 半体/挂载 dashboard REST。
- 修复（用户批准）：备份 config.yaml 后在 enabled 追加 `- whale-widget`（仅此一行）。
- 待用户：重启 Hermes 验证（芯片 ●、/whale 面板真实金额、宠物泡泡余额、审批 hook 激活）。

## 2026-10-07 — 安装规范化迁移（外部修复方案执行；DR-17）

- 症状（外部诊断文件 whale-widget-repair-plan.md）：插件页出现重复/半部关联错误的 Whale Widget 条目——安装目录名（hermes-whale-widget）与 manifest name（whale-widget）不一致，框架按两个身份处理。
- 修复（按方案阶段 1-3 执行，用户全程批准）：备份（experiments/hermes-backup-20261007/，116 文件哈希基线 + 两半体 + marker + config 快照，位于扫描根之外）→ 用户关闭 Hermes → `plugins/hermes-whale-widget`→`plugins/whale-widget`、`desktop-plugins/hermes-whale-widget`→`desktop-plugins/whale-widget` → marker 重写（package=whale-widget、source=新 desktop 路径、sourceMtimeMs 取源文件真实 mtime，与原值精确一致）。
- 阶段 3 验证：迁移后哈希与基线逐文件一致；两个旧目录名在扫描根内均为 0；config enabled=whale-widget（已在 10-05 加入，无需再改）；数据目录 D:\hermes\whale-widget 为空（后端此前从未成功运行，无账本数据）。
- 项目文档核查：INSTALL/README 本就指向 plugins\whale-widget\，无需修正。
- 待用户（阶段 4）：启动 Hermes → 插件页应只有一行 Whale Widget（Agent/Desktop 正确关联）→ 芯片 ●、/whale 面板与宠物泡泡出真实金额 → 再重启一次确认不复发。

## 2026-10-07 — 404 "Plugin not found" 根因：桌面后端运行在 code profile（多 profile 隔离）

- 现象：/whale 面板页面正常加载（routes 页 = 桌面半体 OK），但全部 REST 404 {"detail":"Plugin not found"}。
- 取证链：404 出自 web_server.py:687 守卫中间件（blocked = disabled 或 source==user 且不在 enabled_set）；启用集含 whale-widget 却仍拦截 → 实测后端进程命令行 = `--profile code serve`（PID 99860，端口 9459，经官方 updater closure-repair 启动器）→ **profile 多路复用：code profile 有独立 HERMES_HOME**（profiles/code/：独立 plugins/、config.yaml、desktop-plugins 根）→ 插件只装在默认 profile，对 code 后端不存在。
- 旁证：外部修复方案 Phase 4.7 已预见 profile 维度；code profile 配置里有用户宠物 deepseek-goldwhale-v1。
- 修复（用户批准）：agent 半体复制到 profiles/code/plugins/whale-widget；桌面半体复制到 profiles/code/desktop-plugins/whale-widget（marker.source 指向 profile 内 agent 半体）；profiles/code/config.yaml enabled 追加 whale-widget（已备份 config.yaml.bak-whale-20261007）；__pycache__ 清理。
- 默认 profile 安装保留（切回默认 profile 亦可用）；code profile 将按 DR-9 建立独立账本（profiles/code/whale-widget/whale.db）。
- 待用户：重启 Hermes 验证面板/泡泡真实金额。
