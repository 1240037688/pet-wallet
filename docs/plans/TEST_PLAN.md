# hermes-whale-widget 测试计划（TEST_PLAN）

> 版本 v1.0（2026-10-03）。Phase 5 产物，配套 `docs/plans/IMPLEMENTATION_PLAN.md`（下称 **[IP]**）。
> 上游依据：`AGENTS.md`（§0 部署红线、§7 安全、§8 记账正确性）、`docs/design/DATA_MODEL.md`（下称 **[DM]**）、`docs/design/ARCHITECTURE_DECISION.md`（下称 **[AD]**）、`docs/research/DEEPSEEK_WHALE_ANALYSIS.md`（下称 **[DSH]**，行为语义基准）。
> 测试编号（`ACC-01` 等）被 [IP] 各 Milestone 的「涉及测试」直接引用，**编号一经 [IP] 引用不得改名**。

---

## 0. 目标与硬约束

1. **记账正确性可证明**：每条写入路径能在 duplicate / restart / reconnect / reload 场景下回答「会不会重复记账」（[DM] §3.4 场景矩阵逐行有测试）。
2. **安全红线可证明**：密钥不进日志 / REST / DB / `ctx.storage`；余额 API 失败不产生任何金额写入。
3. **不打真实付费 API**：一切 provider 测试走 mock（见 §2）；CI 与本地测试**禁止外网请求**（`tools/check-security.mjs` 可加测试内断言：httpx 客户端测试实例绑定 mock transport）。
4. **`D:\hermes` 只读**（[IP] §0.5）：自动化止步于本项目目录内（静态检查 + 单元 + 契约 + 重放集成 + 预览页）；一切「写 `D:\hermes` / 改 config.yaml / 真机重启」的验证由**用户手动执行或逐次显式授权**，本计划以「手动验收清单」（§4.10）承载。

### 0.1 自动化可行性总矩阵

| 层 | 内容 | 运行位置 | 自动化 | 说明 |
|---|---|---|---|---|
| L1 单元 | 纯逻辑（dedup 公式、定价、定点运算、状态机、规则、schema、resolver、渲染模型） | 项目内 | ✅ 全自动 | pytest（Python 半体）+ node:test（JS 半体） |
| L2 契约 | REST/WS 端点（FastAPI TestClient + httpx mock） | 项目内 | ✅ 全自动 | 不需要真实 `hermes serve`；覆盖鉴权/命名/NULL 语义 |
| L3 集成 | 事件重放 harness（fixtures → 归一化 → ingest → 规则 → 通知）+ 本地 mock provider server | 项目内 | ✅ 全自动 | 用 Hermes contract 推导的 fixtures 替代真实网关 |
| L4 手动 | 真机部署 / 视觉手感 / 音频 / DPI / 多显示器 / 事件端到端 | `D:\hermes` 真机 | ❌ 用户配合 | §4.10 清单；结果回写 WORKLOG |

---

## 1. 测试分层与工具链

### 1.1 L1 单元

| 半体 | 框架 | 位置 | 约定 |
|---|---|---|---|
| Python（dashboard 半体 + agent 半体 hook） | **pytest** | `plugin-src/hermes-widget/` 不存在——统一放 `plugin-src/hermes-whale-widget/dashboard/tests/` | 纯逻辑模块（whale_core/*）与 REST 分离测试；fixtures 同级 `fixtures/` |
| JS（desktop 半体） | **node:test**（`node --test`） | `plugin-src/hermes-whale-widget/desktop/tests/` | 只测 `desktop/src/core/**` 与泡泡 `schema/resolver/queue` 等**无 React 依赖的纯模块**；UI 组件走预览页人工走查 |

### 1.2 L2 契约

- FastAPI `TestClient` 直接挂 `dashboard/plugin_api.py` 的 router（无需起进程）；鉴权依赖（回环校验、插件启用开关）用依赖覆盖注入模拟。
- 每个端点的响应 schema 测试同时充当 **[DM] §8.1 命名规范 lint**（禁止裸 `cost/spend/used`；`null` ≠ `0` 的序列化契约）。

### 1.3 L3 集成（重放 + mock provider）

- `tools/replay-events.mjs`：读 fixtures JSONL（Hermes 网关事件，字段形状按 `gateway-contract.generated.ts` 推导）→ 喂 `desktop/src/core/normalize.js` → 经 ingest-client POST 到本地拉起的 FastAPI（uvicorn 随机端口或 TestClient 内嵌）→ 断言 DB 行与 REST 输出。
- `tools/mock-provider-server.mjs`：本地 HTTP server（默认 `127.0.0.1:<随机端口>`），按 query 参数或场景文件返回预设响应（200/401/429/500/超时/坏 JSON/缺字段/零余额/仅赠金），供 L2/L3 与预览页使用。

### 1.4 L4 手动验收

- 见 §4.10；每条含「前置（部署状态）/步骤/期望/记录位置」；全部需要用户配合或显式授权（[IP] 修正 e）。

---

## 2. Mock 与测试数据策略

### 2.1 假 provider（核心原则：余额 API 用本地 mock，永不打真实付费 API）

| 场景 | 手段 |
|---|---|
| 单元级（Python） | `httpx.MockTransport`（或 respx，M0 定夺后回填）挂到 `providers/base.py` 的客户端工厂——**生产代码必须允许注入 transport**（设计要求，M4 落实） |
| 集成级 / 预览页 | `tools/mock-provider-server.mjs` 本地 HTTP；场景文件（JSON）驱动响应码/延迟/坏 JSON/字段缺失 |
| 探活 | mock 同源 `/v1/models` 式端点 |
| quota（V2） | mock 订阅接口 + 多窗口形状 fixtures（本版仅预留定义，PRV-11） |
| 凭据 | 测试 key 一律 `sk-test-fake-...` 显式假值；**禁止任何真实 key 进 fixtures/git**（AGENTS.md §7）；指纹断言用预计算的 sha256 值 |

### 2.2 Hermes 事件替代物（不 mock Hermes 进程）

- **fixtures 重放**为唯一自动化路径：`dashboard/tests/fixtures/events/*.jsonl` + `desktop/tests/fixtures/`，事件形状按 contract 类型手写；真机冒烟时（M5/M8）可用 `ctx.onEvent('*')` 临时录制真实事件 → **脱敏后**（去 payload 文本，保留形状）补充进 fixtures。
- 断连/重放场景：fixtures 标注 `replayed:true`、`replayEpoch` 变化、`after_reconnect` 标记（[DM] §3.4）。

### 2.3 环境与时间

- **tmp HERMES_HOME**：pytest fixture 为每个测试建临时目录注入 `HERMES_HOME`（`<tmp>/whale-widget/`），**测试永不写真实数据目录**。
- **可注入时钟**：`whale_core` 的时间源统一走可注入函数（M0 约定），支撑跨零点日键、minute_bucket、FRESH_TTL/90s、partial 缺口、单调样本规则的确定性测试。
- **损坏 DB fixture**：预置截断/乱码 SQLite 文件验证 fail-closed（转储 `.corrupt-<ts>`、拒写）。
- **Windows 文件占用**（可选）：monkeypatch 触发 EBUSY/EPERM 模拟索引器短暂锁（[DM] §7.4 退避重试）；不做真实锁文件（脆弱）。

### 2.4 命令规划（M0 落地后回填确切命令到本节与 AGENTS.md §5）

> 以下为**规划值**；M0 验收时以脚手架实测为准回填（含 Python 路径：开发机 `F:\anaconda3\python.exe`）。

```bash
# L1+L2 Python（单元 + 契约）
python -m pytest plugin-src/hermes-whale-widget/dashboard/tests -q

# L1 JS（单元）
node --test plugin-src/hermes-whale-widget/desktop/tests/

# 构建产物 + 静态安全检查（每次提交前）
node tools/build-desktop.mjs
node tools/check-security.mjs

# L3：本地 mock provider + 事件重放（集成）
node tools/mock-provider-server.mjs --port 0
node tools/replay-events.mjs dashboard/tests/fixtures/events/<case>.jsonl

# 预览页（L4 的项目内预演 + UI 走查）
node tools/dev-preview.mjs
```

---

## 3. 测试矩阵（按域）

> 列「层」= L1/L2/L3/L4；「自动化」= ✅ 项目内全自动 / 🔶 预览页半自动 / ❌ 用户配合（真机）。
> 每行给出断言要点；具体 fixture 文件名在对应 Milestone 建立时落位（本计划锁行为，不锁文件名）。

### 3.1 Accounting（ACC）

| ID | 场景 | 层 | 自动化 | 断言要点 |
|---|---|---|---|---|
| ACC-01 | usage event 落库 | L3 | ✅ | 一条 `message.complete`（status=complete，usage 全字段）→ `usage_event`+`turn_cost` 各 1 行；五类 token、`turn_seq`、`day`（本地时区）、`cumulative_json`/`raw_payload_json` 白名单留存 |
| ACC-02 | duplicate event | L3 | ✅ | 同一 turn 载荷重放 N 次（同分钟/跨重连 `replayed=true`/进程重载后重发）→ 恒 1 行，响应 `duplicate`，不报错；minute_bucket+内容哈希向量测试钉死 dedup 公式（[DM] §3.2） |
| ACC-03 | restart | L3 | ✅ | 关闭并重建 db 句柄（模拟重启）后继续 ingest → watermark 恢复、无重复、无负增量；`turn_seq` 续号不归零 |
| ACC-04 | multi-turn / multi-session | L3 | ✅ | 同会话多轮 `turn_seq` 递增、增量=相邻快照差；主会话与 subagent 不同 `session_id` 分桶不串账；两个会话并发交错到达结果与顺序无关 |
| ACC-05 | counter reset | L3 | ✅ | 快照 < watermark（网关重启计数器清零模拟）→ 行标 `provisional` + `cost_basis='token_only'`、`reset_count+=1`、无负增量（[DM] §3.3）；后续正常轮恢复 final |
| ACC-06 | pricing | L1 | ✅ | 三级 basis 决策表全覆盖（cost_usd 存在/缺省 × 有无自定义价 × 未知模型）；reasoning 不另计费（⊆ output）；`pricing_snapshot_json` 冻结（改价后历史行不变）；币种分账不合并 |
| ACC-07 | rounding | L1 | ✅ | 1e8 定点：累加 1000 次无浮点误差（与 JS 侧 `money.js` 同向量对拍）；越界抛错；显示 `toFixed(2)`；`token_only` 行不计入估算金额 |
| ACC-08 | balance decrease / increase | L1/L2 | ✅ | 降 3 元 → `observed_spend+3`；升 10 元 → `credit+10` 且 **spend 不变**（充值不冲销）+ `needs_review=1`；乱序/同刻样本忽略（单调规则）；币种跳变只重置基准不记差值 |
| ACC-09 | manual adjustment | L2 | ✅ | 校正公式 `implied = opening + credits − otherDebits − last`；错误 revision → 409；校正后 `needs_review` 归零、`correction_log` 保留 50 条；UI 分支（409 重开提示）在预览页走查（🔶） |
| ACC-10 | 日聚合 / 归档 / 缺口 | L1/L3 | ✅ | `daily_summary` 双轨分存（track 列）；跨零点新建轨②日行 opening=此刻余额且标 partial；`PARTIAL_GAP_MS` 缺口标记；保留策略（90 天/2 万条 → archive 不删除；365 天 → summary_archive）；Notification/Watermark 直删 |

### 3.2 Provider（PRV）

| ID | 场景 | 层 | 自动化 | 断言要点 |
|---|---|---|---|---|
| PRV-01 | valid key | L2 | ✅ | mock 200 正常体 → 余额解析正确（多币种选择规则：CNY>0 → 任意非零 → CNY → 首项）；granted/topped_up 缺失 = **NULL 不是 0**；状态 → `ok` |
| PRV-02 | invalid key（401） | L2 | ✅ | 4xx 不重试；状态 → `error`（文案区分凭据失效）；**无任何金额写入** |
| PRV-03 | timeout | L2 | ✅ | 15s 超时（mock 挂起）→ 网络/5xx 路径重试 1 次 → `stale`（有历史值）/`error`（无）；in-flight 去重（并发两次只发一次） |
| PRV-04 | 429 | L2 | ✅ | 4xx 不重试；不回退缓存覆盖；状态机不进入 `zero` |
| PRV-05 | 5xx | L2 | ✅ | 重试 1 次（500ms）；两连败 → stale/error；`stale` 时 REST 返回旧值 + `stale:true`，UI 语义「余额未刷新」 |
| PRV-06 | invalid JSON | L2 | ✅ | 坏 JSON/HTML 体 → 视同失败路径；不崩溃、不写库 |
| PRV-07 | missing path | L2 | ✅ | 模板 `balance.json` 路径取不到 → 字段 NULL + `unavailable_reason`，**不造 0**；`scale` 乘数正确（如 0.0001） |
| PRV-08 | zero balance / 仅赠金 | L2 | ✅ | 明确 `total==0` → `zero`（唯一允许显示 0 的路径）；「只有赠金且赠金>0、充值钱包为空」必须算**成功**（新用户常态，[DSH] A1） |
| PRV-09 | 多厂商模板取数 | L2 | ✅ | registry 模板驱动（≥2 家 mock 模板）：URL/auth/json 路径实例化正确；`balance_json_paths` 用户覆盖（空字段不覆盖默认）；base_url_override 需 allow_custom_host |
| PRV-10 | 无余额接口类 | L2 | ✅ | kind='none'：探活成功 → 可用（余额显示 `—`，今日已用=事件估算）；探活失败 → `last_state='unavailable'` + 原因，**不算错误、不伪造进度条** |
| PRV-11 | quota 订阅额度 | — | — | **V2 预留**：mock 订阅接口、单/多窗口归一、reset 倒计时、`plan.hide` 语义；本版不实现 |

### 3.3 Whale（WHL）

| ID | 场景 | 层 | 自动化 | 断言要点 |
|---|---|---|---|---|
| WHL-01 | start / stop / restart | L3/L4 | 🔶 | 预览页：装载/卸载/再装载无泄漏（定时器/订阅计数归零）；真机（❌）：统一包启用、App 重启后 pane 恢复、禁用开关实时生效 |
| WHL-02 | Hermes exit | L4 | ❌ | 内嵌形态随 App 进程消失；任务管理器确认无残留进程（Phase 1 无子进程，天然满足——仍需确认 esbuild 产物无隐藏 worker） |
| WHL-03 | drag | L1/L4 | ✅/🔶 | 位移平方 ≥9 区分拖/点（单测几何判定）；预览页走查跟手与 settle 动画；真机手感（❌） |
| WHL-04 | snap | L1 | ✅ | 四边吸附几何（ratio/px/off、图像中心判定、角落组合）；净距离位置记忆脏数据自愈（负值/越界夹回）单测 |
| WHL-05 | flip / press | L1/L4 | ✅/🔶 | 贴左 scaleX(-1)、贴右不翻、自由摆放按中线；按压 transform 参数与回弹曲线常量断言；视觉走查🔶 |
| WHL-06 | screen resize / 位置记忆 | L1/L4 | ✅/❌ | resize 后按锚点恢复（净距离格式 v2）单测；真机改变窗口尺寸验证（❌） |
| WHL-07 | 音效引擎 | L1 | ✅ | mock AudioContext：预解码缓存命中、`playAt` 排期（短按衔接 40ms lead / 长按松手即播）、总开关关闭零副作用（不建 context 不解锁）、空闲 suspend |
| WHL-08 | 命中测试 | L1 | ✅ | 合成 alpha 数据：>10 命中、凸包裁剪、画布污染/加载失败降级矩形且不吞事件 |
| WHL-09 | multi-monitor / DPI | L4 | ❌ | 真机：跨显示器拖动 Hermes 主窗口、100%/125%/150% 缩放下 pane/泡泡渲染与坐标正确（Phase 1 在 app 内；V2 独立窗另列 WIN-04/05） |

### 3.4 Bubble（BUB）

| ID | 场景 | 层 | 自动化 | 断言要点 |
|---|---|---|---|---|
| BUB-01 | click / sequence | L1 | ✅ | 点击推进序列（首泡→队列→收起）；`tapAdvance` 开/关语义（续时 vs 回首）；系统泡泡显示期间点鲸鱼不动作 |
| BUB-02 | sequence 重载对齐 | L3 | ✅ | 重载/重启后已弹轮次不补弹（notification dedup + JS storage 标记双保险）；首拉只对齐不弹（[DSH] A3 seq 语义） |
| BUB-03 | random 模块 | L1 | ✅ | 随机语句池抽取、avoidIdx 最多重抽 6 次防连续重复（choice 层**不**防连续重复——语义区别测试） |
| BUB-04 | weighted random | L1 | ✅ | 大样本分布近似权重（±容差）；choice 每次独立抽样；权重越界（1..99）校验 |
| BUB-05 | system queue | L1 | ✅ | rank 优先级（预算>预警>消耗>等待）；等待抢占（消耗退队、立即上屏）；同批 30ms 合批；TTL 自动关 + 巡检兜底；等待 ttl=0 常驻；降级 `host.notify` toast |
| BUB-06 | image 模块 | L1/L4 | ✅/❌ | 图片独占一行且全泡唯一（schema 拒绝违规）；内置语义 id 常驻（用户图库删空不坏默认内容）；真机看 GIF/APNG 渲染（❌） |
| BUB-07 | placeholder / missing value | L1 | ✅ | 全占位符表（balance/bonus/recharge/expense_est/expense_obs/session…）；取值缺失 → null → 渲染 `—`；**`—` 与 0 语义区分**（null ≠ 0 序列化契约） |
| BUB-08 | 编辑器③流程 | L2/L4 | 🔶 | save/cancel/恢复默认/脏检查（预览页走查）；「恢复默认」与 Python 出厂默认逐字段一致（一致性探针，L2 ✅）；配置写 `/config` 白名单校验（L2 ✅） |

### 3.5 Reminder（REM）

| ID | 场景 | 层 | 自动化 | 断言要点 |
|---|---|---|---|---|
| REM-01 | balance threshold | L1/L2 | ✅ | `0 < balance ≤ threshold` 触发 rank2；`balance==0`（zero 态）**不**触发余额预警；恢复高于阈值删 dedup 键才可再响（迟滞）；`stale/error/unknown` 态禁止比较（M4 状态机约束） |
| REM-02 | budget threshold | L1/L2 | ✅ | `today_usage ≥ amount` 触发 rank1；按日去重键 `budget:<id>:<day>`；币种不一致且无汇率 → **不比较不误报**；`basis` 口径（estimated/observed）各测 |
| REM-03 | duplicate suppression | L2 | ✅ | 全 kind dedup 键表（[DM] §2.10）：同日同预算一次、同挂起 id 一次、turn_cost 由 turn dedup 承接；`INSERT OR IGNORE` 冲突路径 |
| REM-04 | restart 后不重响 | L3 | ✅ | 触发 → 模拟重启（新句柄/新进程内实例）→ 同条件再评估 → 不再写 notification（持久去重，优于 DSH 内存语义的验证） |
| REM-05 | question 事件链路 | L3 | ✅/🔶 | clarify `tool.start` → 挂起（按 tool_id/session_id 分槽）；`tool.complete` 同 id 解除；同 id 重放只响一次；**端到端真机冒烟 ❌**（clarify 必发为源码核实结论，端到端未实测——[IP] M8） |
| REM-06 | approval hook 桥 | L1/L2 | ✅/❌ | hook 函数直调 → `approval-state.json` 原子写内容断言；`/wait-state` 合并 question+approval；`surface` 过滤；**实验开关（busy 停流启发式）默认关闭**断言；真机审批端到端 ❌ |

### 3.6 Security（SEC）

| ID | 场景 | 层 | 自动化 | 断言要点 |
|---|---|---|---|---|
| SEC-01 | API key not logged | L1/L2 | ✅ | 注入形如 `sk-test-...` 的假 key 跑全链路 → 捕获日志输出断言无 key / 无 `Bearer `/`Authorization` 值；轮转日志脱敏 Filter 单测 |
| SEC-02 | key not returned to UI / not persisted | L2/L1 | ✅ | `/balance`、`/providers`、`/config` 响应只含 `{credential_id,name,configured,source,fingerprint}`；`provider` 表只有 `credential_ref`；`ctx.storage` 相关键抽查无敏感值（运行时断言 + check-security 静态扫描）；DB 抽查无明文 key |
| SEC-03 | 余额失败不产生金额写入 | L1/L2 | ✅ | `unknown/stale/error` 态下调差分与预算比较 → 无任何 `*_units` 写入（[DM] §6 硬规则 1）；`zero` 是唯一合法「0 值」来源 |
| SEC-04 | 出站白名单 / URL 校验 | L1 | ✅ | origin 必须等于模板端点；`169.254.169.254`/`metadata.google.internal`/userinfo/非 http(s) 全拒；自定义 host 无 `allow_custom_host` 拒绝携凭据 |
| SEC-05 | 写端点回环校验 | L2 | ✅ | 模拟非回环来源的 POST/PUT/DELETE → 403（DSH「远端能改配置=能外带 key」威胁模型） |
| SEC-06 | path traversal blocked | L2 | ✅ | 资产/配置端点构造 `../`、编码穿越（`%2e%2e`）、绝对路径、盘符路径 → 4xx；`ctx.rest` 命名空间静态检查（产物内无越界调用） |
| SEC-07 | asset path validated + 准入自检 | L1/L3 | ✅ | 资产 id 白名单正则 + resolve 后前缀校验（[REF] §2.5 范式）；`tools/check-security.mjs`：import 白名单、eval/原型补丁/动态 import/`<script>` 注入、`sk-`/`Bearer ` 扫描（对齐官方 admission lint） |

### 3.7 Contract（CON，REST/WS 端点）

| ID | 端点组 | 层 | 自动化 | 断言要点 |
|---|---|---|---|---|
| CON-00 | `/health` | L2 | ✅ | schema_version、track3 状态、插件启用开关模拟（禁用 → 409/403 语义） |
| CON-01 | `/ingest/turn`、`/ingest/wait-event` | L2 | ✅ | 请求/响应 schema；非法载荷 4xx 且不回显原始 payload；`accepted`/`duplicate` 二值 |
| CON-02 | `/usage/*`、`/balance*` | L2 | ✅ | 响应 schema + [DM] §8.1 前缀命名（`estimated_*`/`observed_*`）；null ≠ 0 序列化；`stale`/`partial`/`needs_review` 字段存在性 |
| CON-03 | 全端点命名 lint | L2 | ✅ | 通用断言：任何响应体禁止裸 `cost`/`spend`/`used` 键（递归检查） |
| CON-04 | `/notifications`、`/wait-state`、`/config` | L2 | ✅ | rank/ttl/payload 形状；config 白名单字段（越权字段 4xx、密钥字段永不存在） |
| CON-05 | `/providers` CRUD + test | L2 | ✅ | 模板实例校验（currency 建账后不可变、fingerprint 重算）；`/test` 走 mock transport |

### 3.8 Integration / Replay（INT）

| ID | 场景 | 层 | 自动化 | 断言要点 |
|---|---|---|---|---|
| INT-01 | 事件重放端到端 | L3 | ✅ | fixtures（正常轮/错误轮/中断轮/多模型轮/缺省字段轮）→ normalize → ingest → DB/REST 断言全链 |
| INT-02 | 断连 / 重放 / gateway 重启 | L3 | ✅ | `replayed=true` 事件去重；`after_reconnect` 首条只对齐；断连期暂停转发、恢复续传；插件禁用再启用空洞 → 轨①partial + 轨②下次观测补记（两轨互补验证） |
| INT-03 | 提醒全链路模拟 | L3 | ✅ | mock 余额下降到阈值 + turn fixtures → rules → notification → `/notifications` → 队列渲染模型（bubble 侧 mock 数值）全链断言 |

### 3.9 Windows 专项（WIN）

> Phase 1（floating pane）大多数条目随宿主 App 表现，真机验证；标 **V2** 的条目在独立窗里程碑才激活（pywebview/WebView2 直测）。

| ID | 场景 | 自动化 | 要点 |
|---|---|---|---|
| WIN-01 | WebView2 / 渲染层 | 🔶 | Phase 1 为 Electron 渲染层（本机 ai-usage-tracker 实证可用）；预览页 + 真机确认字体/清晰度/暗色主题 |
| WIN-02 | 透明窗口 | ❌（V2） | Phase 1 泡泡/pane 半透明在 app 内验证即可；V2：`WS_EX_LAYERED` 补丁后逐像素透明 + 拖动无重影（RedrawWindow） |
| WIN-03 | 置顶 / 任务栏 | ❌（V2） | V2：`on_top` 生效、`WS_EX_TOOLWINDOW` 无任务栏图标；Phase 1 N/A（app 内常驻语义） |
| WIN-04 | DPI 缩放 | ❌ | 真机 100%/125%/150%：pane/泡泡/Canvas 无模糊错位（Canvas 按 devicePixelRatio 高清绘制——[DSH] 图表纪律） |
| WIN-05 | 多显示器 | ❌ | 跨屏移动主窗口、混合 DPI 双屏：显示与交互正常；V2 独立窗的窗口归属屏测试 |
| WIN-06 | 全屏 | ❌ | Hermes 全屏模式下 pane/泡泡不被遮挡异常（app 内层级观察） |
| WIN-07 | 路径处理 | ✅ | 单元：反斜杠/正斜杠/中文/空格/长路径（>260 字符可选）经 `path` API 归一；数据目录含中文用户名场景（fixture 模拟） |
| WIN-08 | pythonw / 进程退出 | ❌（V2 + L4） | V2：pythonw spawn、握手 10s、心跳 60s 自退、`WM_CLOSE`；Phase 1 真机确认 App 退出无孤儿（WHL-02） |
| WIN-09 | 音频 | ❌ | 真机：默认设备播放、设备热切换、独占模式占用时的失败降级（不崩溃不卡 UI） |
| WIN-10 | 文件选择器 | ❌ | `ctx.os.pickOpenPath` 返回后端语义路径 → 导入链路走通（角色/音效导入） |

### 3.10 手动验收清单（MAN，全部用户配合）

| ID | 时机（Milestone） | 内容 | 前置 |
|---|---|---|---|
| MAN-01 | M0 | 统一包部署走通：复制 → `plugins.enabled` → 重启 → 桌面半体 opt-in 启用 → `/health` 可达 | 用户复制/授权 |
| MAN-02 | M5 | 闭环冒烟第一段：真发一轮对话 → 芯片/pane 数字变化 → 与 Hermes 会话 usage 一致 | MAN-01 |
| MAN-03 | M4/M5 | 余额真机：真实 key 配置（Hermes 原生方式）→ 余额显示 → 断网制造 stale → 恢复 | MAN-01 |
| MAN-04 | M5 | 降级面：临时禁用 Python 半体 → UI 显示「记账暂不可用」+ focusedUsage 实时数 | MAN-02 |
| MAN-05 | M6 | 交互手感：拖/吸/翻/压逐项与 DSH 参考体验比对，记录调参项 | MAN-02 |
| MAN-06 | M6 | 位置记忆：resize/重启 App 后恢复位置 | MAN-05 |
| MAN-07 | M8 | Question 端到端：真实触发 clarify → 等待泡 → 回答后收泡（验证「tool 生命周期事件必发」的端到端结论） | MAN-02 |
| MAN-08 | M8 | Approval 端到端：触发审批 → 等待泡 → 批准/拒绝后收泡；后台 profile 审批可见性 | MAN-02 |
| MAN-09 | M9 | 音效真机：四类事件音、音量、静音开关、最小化恢复 | MAN-02 |
| MAN-10 | M10 | 素材真机：导入角色（png/gif/apng）、透明命中、置顶删除回退 | MAN-05 |
| MAN-11 | M12 | 设置页全走查：编辑器、校正窗口、阈值设置、Provider 管理 | MAN-02 |
| MAN-12 | M13 | 发布包按 INSTALL.md 全程安装→验证→卸载→数据清理 | MAN-11 |
| MAN-13 | 升级时 | Hermes 升级冒烟五项：事件面 / ctx.rest 桥 / 凭据解析 / 热加载 / 轨③ schema_version 门 | 任意版本 |

---

## 4. 里程碑 ↔ 测试映射（回归底线）

| Milestone | 新增测试 | 回归底线（必须保持绿的既有子集） |
|---|---|---|
| M0 | CON-00、SEC-01/02、迁移/配置/脱敏单测 | — |
| M1 | CON-01、INT-01（stub 阶段） | M0 全部 |
| M2 | ACC-01~05、ACC-10、CON-02/03、INT-02 | M1 全部 |
| M3 | ACC-06/07 | ACC-01~05、CON-02 |
| M4 | ACC-08/09、PRV-01~08、SEC-03/04/05 | ACC-01~07 |
| M5 | WHL-01/02（预览部分）、MAN-01~04 | ACC/PRV 全部 |
| M6 | WHL-03~06（单测部分）、MAN-05/06 | M5 |
| M7 | BUB-01~07、CON-04 | ACC 全部 + M5/M6 |
| M8 | REM-01~06、SEC-06、INT-03、MAN-07/08 | BUB + ACC + PRV |
| M9 | WHL-07、WIN-09、MAN-09 | M8 |
| M10 | WHL-08、BUB-06（实装）、SEC-07、MAN-10 | M9 |
| M11 | PRV-09/10、CON-05 | SEC-04 + M10 |
| M12 | BUB-08、SEC-06（config 面）、MAN-11 | 全部既有 |
| M13 | SEC-07（准入扩展）、MAN-12 | **全量回归**（L1-L3 全绿 + 发布走查） |

---

## 5. 冒烟清单（每次真机部署 / Hermes 升级后最小执行集）

1. `GET /api/plugins/whale-widget/health` 返回 schema_version 与启用态。
2. 发送一轮对话 → `turn_cost` 通知 + 消耗泡泡恰好一次（重复刷新不补弹）。
3. 余额显示非 `—`（或显式 unknown 原因）；今日消费双轨数字与预期一致。
4. 把余额阈值临时调到当前值以上 → 预警泡泡一次；重启 App → 不重响。
5. 触发一次 clarify（提问）→ 等待泡出现、回答后收泡。
6. `node --test` + `pytest` 全绿 + `check-security` 通过（项目内，无需真机）。

---

## 6. 维护规则

- 新增 REST 端点必须同时新增/扩展 CON 条目；新增金额字段必须同时新增 ACC 断言与命名 lint 通过。
- 真机验收结果（MAN-*）记入 `docs/progress/WORKLOG.md`；发现的行为与计划不符 → 先改 [IP]/本文再改代码。
- fixtures 形状随真机录制更新时，保留旧 fixtures（向后兼容回归），新增版本号子目录。
- 本文件命令区在 M0 验收后回填为确切命令并同步 `AGENTS.md` §5。
