# DSH_REPLICATION_MATRIX — DSH 小鲸鱼挂件功能复刻矩阵（WP-matrix）

> 分析日期：2026-10-05（基线 = DR-16 后工作区现状）。
> 依据：`docs/research/DEEPSEEK_WHALE_ANALYSIS.md`（下称 [DSH]，产品能力清单 §0-§G）＋ `docs/design/FEATURE_MATRIX.md` / `FEASIBILITY_REPORT.md`（A-E 可行性）＋ `docs/research/HERMES_PET_SYSTEM.md`（下称 [PET]）＋ `docs/design/ARCHITECTURE_DECISION.md`（DR-15/16）。
> **代码现状逐项核对过**（非照抄文档）：本文所有 file:ref 均相对 `plugin-src/hermes-whale-widget/`；Hermes core 侧引用保持 `仓库:行号` 原样（来自 [PET]/FEASIBILITY 只读抽查）。
> 测试基线（本轮实测）：`node --test` **205 条 / 204 通过 / 1 失败**（main-wiring「pane 注册」断言是 DR-16 前写的——面板注册已改为 config 载入后延迟注册，断言未同步，见 §6 附注）；`pytest` **188 passed**。

## 汇总表

| 复刻状态 | 定义 | 数量 | 占比 |
|---|---|---:|---:|
| ✅ 已复刻 | 有代码 + 测试证据（含「由 Hermes 宿主核心原生承接」的功能，注明承接面） | **59** | 52.7% |
| 🔶 部分复刻 | 缺一块，补齐路径与量级（S≤1 天 / M≤1 周 / L≥1 周）已给 | **14** | 12.5% |
| 🔜 可复刻未做 | 路径明确，纯排期问题（V1/V2 队列见文末） | **30** | 26.8% |
| ❌ 不可复刻 | 详细理由分三类：① Hermes 核心所有权 ② 平台机制缺失 ③ DSH 特有技术/素材依赖 | **9** | 8.0% |
| 合计 | （对照 [DSH] 产品能力清单逐项对齐，可增不可减） | **112** | 100% |

❌ 明细（9 条）：四边吸附①、左右翻转①、透明像素穿透①、自定义角色图导入①、移动端触摸交互②、默认音效/图片素材③、滚轮让位③、IME 组字保护③、DSH 宿主适配层③。逐条理由见各章。

> 与 FEASIBILITY_REPORT 的口径差：那份报告回答「**能不能**做」（结论 PARTIAL 趋近 FULL）；本矩阵回答「**做了没有**」——大量 C 级能力（余额/校正/等待桥/通知去重）已落码并测试，故 ✅ 占比过半；而 UI 类（编辑器/图表/设置页）全部未动工，故 🔜 集中在表现层。

---

## 一、记账与显示系统（[DSH] §A，33 项）

| DSH 功能 | 复刻状态 | 本项目实现（file:ref） | 差距/理由 |
|---|---|---|---|
| 余额自动刷新（60s 级轮询） | ✅ | `dashboard/whale_core/poller.py:37-50,61-77`（单实例守护线程，间隔来自 `config.py:44 balance_poll_seconds`）+ `desktop/src/core/data-service.js:58-70`（显示面轮询，15s~600s 钳制） | 与 DSH 前端 setInterval 不同：轮询单实例在 Python 半体（AGENTS §8 禁重复 timer），语义等价 |
| 点击手动刷新余额 | 🔶 | 后端端点已有：`dashboard/whale_core/api.py:282-286`（POST /balance/refresh，loopback 门控） | 前端未接线：`desktop/src/ui/pet-layer.js:256-265` 点击只推进泡泡序列，未调 /balance/refresh。补齐 = S（click handler 加一个 restPost + 防抖） |
| 服务端缓存 + 在途请求去重（25s TTL） | 🔶 | `dashboard/whale_core/poller.py:31-35`（单线程串行，天然无在途并发）+ `balance_ledger.py:41 FRESH_TTL_MS=120s`（显示 stale 判定） | 无显式 25s TTL 内存缓存；单实例轮询下 DSH 的 `balanceInFlight` 去重场景不存在。补齐 = S（若未来多消费者再引入） |
| 瞬时失败沿用旧值（stale 标记） | ✅ | `balance_ledger.py:370-385`（stale/error 态保留 `observed_balance_units`）+ `desktop/src/ui/balance-view.js:33-45`（「未刷新」「获取失败」badge + tone）+ `whale-pane.js:41-49` toneColor | 语义与 DSH 一致（绝不当 0） |
| 双通道余额（API key + 账号登录态互备） | ❌ | `dashboard/whale_core/providers/gateway.py:46-69`（仅 key 通道：Hermes secret → env → credentials.json 兜底） | **理由③（DSH 特有宿主依赖）**：DSH 通道②依赖 DSH 宿主的 `deepseekAccount` 登录态服务（[DSH] §A1，`lib/index.js:1060-1142`），token/请求头/失效清理全由宿主负责——Hermes 无对应服务，且插件无凭据写 API（FEASIBILITY §2-③），无法自建登录态管理。**替代**：仅 key 通道 + 引导用户经 Hermes secret_sources 配 key；「任一失败回退另一条」的双保险语义由「secret→env→文件」三级解析近似 |
| 多币种选择规则（CNY>0 → 任一非零 → CNY → 首项） | ✅ | `dashboard/whale_core/providers/deepseek.py:49-65`（`select_currency` 纯函数，[DSH] F1 语义逐条对齐） | 单元测试覆盖（dashboard/tests/test_balance.py） |
| 赠金/充值余额单独取数（取不到 = NULL 非 0） | ✅ | `deepseek.py:104-119`（`granted_units/topped_up_units` optional→None） | 数据已入 `balance_snapshot` 列，供 bonus/recharge 模块取用（模块未做，见三章） |
| 余额五态显示（unknown/zero/error/stale/ok） | ✅ | `balance_ledger.py:328-390`（状态机）+ `balance-view.js:19-49`（文本/tone/badge/hint 映射）+ `whale-pane.js:85-129` DataCard 余额行 | DATA_MODEL §6 硬规则「API 失败 ≠ 0」落地（test_balance.py 断言） |
| 数字滚动动画（700ms ease-out + 消耗泡期间冻结） | 🔜 | 无代码 | 纯前端 rAF 动画（[DSH] §A1 `animateAmount` 可整体照抄）。量级 **S**（V1） |
| 余额变化泡泡（仅自动刷新路径弹） | 🔜 | `notifications.py:38-41` KINDS 已预留 `balance_change`，无 fire 方 | 触发点在 `record_snapshot` 差分处（spend/credit delta ≠ 0 时 fire）。量级 **S**（V1） |
| 余额差分记账（下降额累计为消费） | ✅ | `balance_ledger.py:106-112`（`delta<0 → spend_delta`）+ 每日行物化 `:166-206` | [DSH] A2 `observeBalance` 同构；重复/乱序样本忽略（UNIQUE + fetched_at 单调，`:83-104`） |
| 充值不冲销消费（上升额单独记） | ✅ | `balance_ledger.py:113-114`（`delta>0 → credit_delta`，注释 "never cancels spend"） | 与 [DSH] A2 逐字对齐；credit 只触发校正闭环 |
| 待核对 + 显式校正闭环（revision 409） | ✅ | `balance_ledger.py:213-263`（implied 公式 `opening+credits−otherDebits−last` + 乐观并发 revision + `balance_adjustment` 审计表）+ `api.py:289-323`（409/404 映射）+ `needs_review` 汇总 `:397-429` | 与 [DSH] `reconcileBalance` 同构且更强（审计入库、revision 持久化）；测试 test_ledger_accounting.py |
| 观测缺口 partialDay（>10 分钟标部分数据） | ✅ | `balance_ledger.py:42 GAP_PARTIAL_THRESHOLD_S=600` + `:115-116`（gap/partial 计算）+ `usage_ledger.py:196-213,307-310`（partial_days/provisional_turns 汇总面） | 与 [DSH] PARTIAL_GAP_MS 同值；UI 尚不展示 observedFrom/To 与缺口时长（随 7 日历史 UI，S） |
| 8 位定点记账 + 越界抛错 | ✅ | `pricing.py:47 SCALE=1e8` + `:74-105`（Decimal 转换/i64 越界）+ JS 镜像 `desktop/src/core/money.js:11-27`（ACC-07 双侧同向量） | 与 [DSH] SCALE 同值；显示两位 `money.js:40-48` |
| 密钥指纹分账本（换/删 key 数据不丢） | ✅ | `gateway.py:41-43`（sha256(key)[:24]）→ scope = 指纹；`balance_ledger.py:60-90`（provider+scope+currency 三键记账） | 与 [DSH] A2 scope 同构（DSH 亦为 24 hex） |
| 历史账本不与当前相加显示 | 🔶 | `balance_ledger.py:397-429` balance_summary **跨 scope 按日+币种合并**（docstring "across scopes (merged per day+currency)"） | 语义差异：DSH 刻意不合并（[DSH] A2 issue #163「无法判断是否同一账户」）。当前单 provider 单 key 等价；多 key 场景需按 scope 拆行。补齐 = **S**（GROUP BY 加 scope） |
| 币种跳变重置基准不记差值 | ✅ | `balance_ledger.py:83-90`（prev 查询含 currency——币种变了即无 prev，不 diff） | [DSH] A2 历史教训（单日虚记数千元）已吸收 |
| 逐轮明细 90 天/2 万条 + 逐日 365 天 + 归档不删除 | ✅ | `archive.py:28-33`（RETENTION_DAYS=90/20k/SUMMARY_DAYS=365/ARCHIVE_MAX_ROWS=200k）+ `:47-145`（move-不-delete + 档案超限丢最旧）+ `:148-166`（每日一 tick，结算顺手执行） | 与 [DSH] pruneLedgerUsage 同量级 |
| 账本 IO 健壮性（原子写/损坏拒覆盖/退避） | ✅ | `db.py` + `api.py:71-76`（LedgerCorruptError → fail-closed 503 + ledger_error 透出）+ `config.py:193-205`（tmp+os.replace 原子写）+ `poller.py:75-77`（线程崩溃不倒 serve） | 实现载体不同且更强：SQLite WAL 替代 DSH 的 JSON+EBUSY 退避重试；「账本读不出 fail-closed、记账失败不吞余额」语义对齐（[DSH] §A1） |
| 日键 = 北京时间 | ✅（有意差异） | `ingest.py:93-96` local_day_key（**本地时区**，DR-12） | 峰谷时段是 DeepSeek 特有需求；本项目不绑北京时区（DR-12「诚实分账优于黑盒折算」）。若 V2 做峰谷价再引入可选时区 |
| 每轮消费：真实 usage（input/cache/output/reasoning） | ✅ | `desktop/src/core/normalize.js:31-51`（NULL-aware 白名单）+ `main.js:99-109`（订阅 message.complete/session.usage 等九类事件） | 字段全可选 → 缺失即 null（R4），不造 0 |
| 轮次判定 + session 分桶（防主/子会话串账） | ✅ | `desktop/src/core/turn-tracker.js:97-171`（turns Map by session_id + heartbeat/salvage 三级兜底 `:125-134`） | 等价 DSH turnAggs（[DSH] A3）；多会话并发按 session_id 分桶 |
| turn/end 结算落库（唯一入口） | ✅ | DR-13 + `ingest.py:521-647`（message.complete 才结算；心跳永不落库）+ `ingest-client.js:16-22`（有界重试+死信） | 与 DSH turn/end 结算同构；断线重连只对齐 watermark 不结算（`ingest.py:531-541`） |
| reasoning 不单独计费（⊆ output） | ✅ | `pricing.py:11-16`（docstring 引 [DSH] A3 issue #89）+ `:381-390`（billed = miss/hit/out 三项） | 避免输出侧重复计费（实测偏高约一倍的坑） |
| 每轮消费防重（刷新/重放不重复） | ✅ | `ingest.py:104-139`（dedup_key = sha256(14 字段)[:40]）+ `:390-434`（同分钟精确 + 10min fuzz 窗口双重查重）+ watermark 对齐 `:531-541` | 比 DSH seq 双持久化更强：内容指纹 + DB UNIQUE 持久化 + 重放窗口；对账测试 test_ingest_contract.py（固定向量钉死） |
| 消耗泡泡 + 任务结束音 | ✅ | `controller.js:146-154`（settled → turn_cost 泡）+ `rules.py:197-244`（turn:{dedup_key} 继承结算幂等）+ `controller.js:136-139`（TASK_COMPLETED → play('task_finished')）+ `main.js:151-170`（ingest 响应 settled 防御性消费） | ttl 5s 同 DSH 默认（config.py:64） |
| Usage Ledger 数据面（today/7 日/全部/逐轮） | ✅ | `usage_ledger.py:138-311`（summary：today + trailing days + per_model + partial flags）+ `:314-359`（turns）+ `api.py:208-223`（/usage/summary?days、/usage/turns） | 每币种独立分桶不合并（DR-12）；unpriced 计数不折 0（null≠0） |
| 模型占比条 UI（彩色条 + 百分比） | 🔜 | 数据已有：`usage_ledger.py:243-290` per_model（tokens + per-currency cost） | 纯 UI（ROUTES_AREA 设置页或 pane 扩展）。量级 **S**（V1） |
| 近 30 天柱状图（canvas + 悬停 + 点柱跳转） | 🔜 | 数据已有：`usage_ledger.py:184-241` estimated_days[] | 量级 **M**（V2；SDK 内可用 SVG/Canvas，无 devicePixelRatio 之外的障碍） |
| 按日期/模型名搜索 | 🔜 | 数据已有（/usage/turns + summary） | 前端过滤即可。量级 **S** |
| 模型友好名/旧名标注 | 🔜 | 无 | 静态映射表即可。量级 **S** |
| 峰谷电价（工作日高峰/周末/节假日表） | 🔜 | `pricing.py:131-148` BUILTIN_PRICES 取**峰档上价**（conservative；note 明说 "peak/valley split is V2"） | 补齐 = 移植 [DSH] `isPeakTime` + 节假日表（需按年维护）。量级 **M**（V2；仅对 DeepSeek 直连计费有意义） |
| 自定义单价覆盖（0..1e6 校验 + 快照冻结 + 最长键匹配） | ✅ | `pricing.py:164-196`（validate，与 DSH F3 同界）+ `:199-245`（set/clear）+ `:151-157`（longest-key-first，防 "pro" 误伤）+ `compute_settlement :379-407`（价格冻结进 pricing_snapshot，改价不重写历史）+ `api.py:237-255` | **语义差异**：USD 单价按 USD 记账、不自动折 CNY（DR-12）；DSH 是 USD+汇率折 CNY 统一记账。内置表 DeepSeek 不允许被覆盖（builtin 优先级低于 custom，与 DSH 相反方向但结果一致：内置 4 条即兜底） |

---

## 二、交互系统（[DSH] §B，13 项）

> 总原则（DR-16）：宠物本体的拖拽/姿态/窗口由 Hermes core 负责，插件监听只做 **tap 判定**（捕获阶段、不 preventDefault、拖拽让位核心）。

| DSH 功能 | 复刻状态 | 本项目实现（file:ref） | 差距/理由 |
|---|---|---|---|
| 拖拽移动（1:1 跟手 + settle 吸附动画） | ✅（宿主承接） | core 宠物自带拖拽（[PET] §2，floating-pet.tsx onPointerDown）；管家面板 = core floating pane 原生拖拽（`whale-pane.js:12-19` SDK probe 结论）；`pet-layer.js:13-15` 明确「拖拽完全留给核心」 | 不需要插件实现——DR-16 刻意不重复造；判定 = tap slop 6px（`pet-layer.js:27,32-37`，10 条纯函数测试） |
| 单击 = 推进泡泡序列 + 音效 | ✅ | `pet-layer.js:235-265`（pointerdown/up/click 捕获链）→ `controller.js:118-130` click()（greeting→advance→idle-line） | DSH 的「单击同时手动刷新余额」未接（见一章 🔶） |
| 连续点击序列/连击窗口 + 彩蛋 | ✅ | `whale-state.js:22 CLICK_WINDOW_MS=1200` + `:63-69`（combo 计数）+ `controller.js:122-125`（combo≥4 → dismiss greeting + 随机 idle line） | DSH 无双击概念、以序列/续时表达——本项目 combo + tapAdvance 序列等价 |
| 四边吸附（ratio/px/off + 可视化设置窗） | ❌ | 无 | **理由①（Hermes 核心所有权）**：宠物弹出窗几何（位置/尺寸）是 core 内部 atom/store（[PET] §3：SDK 对宠物零导出、pet RPC 核心内部 `tui_gateway/server.py:180`）；插件建窗被 deny-all（`window-open-policy.ts:74-93` 无条件 deny；透明窗核心专用 `electron/main.ts:1506-1509`）。**替代**：core floating pane 自带视口钳制与拖拽摆位；upstream `host.pet.getBounds()`（FEASIBILITY §3.1 已提案）落地后可在面板侧做吸附摆位 |
| 左右翻转（贴左必 scaleX(-1)） | ❌ | 无 | **理由①**：翻转作用于 core 渲染的宠物 canvas，插件无 transform 注入面。**替代**：皮肤包 Codex 行序自带 running-left/right 方向性姿态（[PET] §2，`assets/whale-pet-pack` 按规格生成），运动朝向由 core 姿态机表达 |
| 自由摆放 + 位置记忆（净距离格式 + 自愈） | ✅（宿主承接） | core floating pane / 宠物 overlay 各自管理位置（`whale-pane.js:18` 注释 "position persistence is unnecessary (core owns it)"） | DSH 的 localStorage 锚点自愈逻辑在宿主形态下不需要 |
| 按压 Q 弹（scaleY 过冲回弹） | 🔶 | press/release 状态机 `whale-state.js:49-59` → mood=press → 面板 accent 变色（`controller.js:29-39`）+ 按压/松开音效（`controller.js:99-113`） | 视觉 squash 动画无法施加于 core 宠物（同上①）；面板无角色可弹。补齐路径 = upstream `host.pet.react(kind)` 或 M10 面板微动画。量级 **S** |
| 菜单（悬停 ☰）/ 右键 / 长按唤出菜单 | 🔜 | 无 | pet-layer 已有 pointer 事件链，加长按计时 + fixed 菜单层即可。量级 **S/M**（V2） |
| 移动端触摸拖拽 + 长按 1.5s 菜单 + 去点击高亮 | ❌ | 无 | **理由②（平台机制缺失）**：目标宿主是 Hermes 桌面 Electron 应用，不存在移动端形态；DSH 的自研触摸接管（防页面滚动误判）无适用场景。**替代**：无（产品边界，README 可注明） |
| 透明像素穿透（canvas alpha + 凸包 clip-path） | ❌ | 无 | **理由①**：宠物 canvas 的命中/指针处理归 core；插件 tap 判定用 composedPath 包含性（`pet-layer.js:40-43`），矩形粒度已够。DSH 该技术解决的是「img 透明边距吞事件」，问题在宿主形态下不存在 |
| 滚轮让位（找出指针下可滚容器代滚） | ❌ | 无 | **理由③（DSH 特有 DOM Hack）**：DSH 挂件浮在宿主聊天页面上需要处理滚轮冲突；本项目泡泡宿主 `pointer-events:none`（`pet-layer.js:134`）、面板为独立 floating 卡片，无页面滚动冲突面 |
| IME 组字保护（compositionend 排队） | ❌ | 无 | **理由③**：当前实现无键盘拦截、无 body 增删热区（泡泡层 pointer-events:none）；DSH issue #179 的冲突面（body 挂载登记器）本项目不引入。教训已记录——未来若加 DOM 注入型菜单/编辑器需复查此坑 |
| tapIndex 注入 / 桌面注入行 / composer 主界面判定 / body 登记器 | ❌ | 无 | **理由③（DSH 宿主适配层）**：[DSH] §B 已明确「Hermes 有自己的扩展机制，不需要这层」（约占 DSH 前端 15% 的宿主 hack）；Hermes 侧等价物 = runtime-loader 插件加载 + SDK area 注册（`main.js:322-327,418-434`） |

---

## 三、泡泡系统（[DSH] §C，23 项）

| DSH 功能 | 复刻状态 | 本项目实现（file:ref） | 差距/理由 |
|---|---|---|---|
| 点击序列（首次泡 + 再次点击队列推进） | ✅ | 默认序列 `desktop/src/ui/bubble/defaults.js:8-28`（3 步）+ 队列 `bubble/queue.js:58-66` advance（tapAdvance 定义按页推进、重置 ttl）+ `controller.js:118-130` | 运行时序列 = 固定默认定义；「第 n 次点击可编辑」随编辑器（四章） |
| choice A/B 加权随机（允许连续重复） | ✅ | `bubble/resolver.js:17-25` pickWeighted（累减抽样）+ `defaults.js:20-25`（默认 w:3 余额 / w:2 今日估算） | 注释明示 "repeats allowed"，与 [DSH] `bubblePickChoiceStep` 不防连续重复语义一致 |
| random_text avoidIdx 防连续重复（≤6 重抽） | ✅ | `resolver.js:12,27-37`（avoid Map + MAX_REROLLS=6） | 与 [DSH] `bubblePickLine` 同构 |
| text 模块（{placeholder} 模板） | ✅ | `bubble/schema.js:28-37`（类型集）+ `resolver.js:42-45,100-111`（占位符替换，缺失→`—` 并 flag missing） | 占位符集合为 DSH 子集（5/12+，见下） |
| link 模块（可点开新页） | 🔜 | 无 | 打开通道换 `ctx.os.openExternal`（FEATURE_MATRIX §三）。量级 **S** |
| random_text 模块 | ✅ | 同上 random_text 行 | — |
| image 模块 | 🔶 | schema 校验+独占行已备 `schema.js:66-68,83-85`；渲染为占位盒 `bubble/renderer.js:27-43` / pet-layer `:139-144` | 缺真图渲染（图库未建，见五章）。补齐 = IndexedDB 图库 + objectURL，量级 **S**（引擎侧） |
| randimg 随机图片模块（带权池） | 🔜 | 无 | 加权抽样函数已备（pickWeighted 复用）。量级 **M**（含图库） |
| balance 模块（总余额） | ✅ | `resolver.js:51-52` + 数据喂入 `main.js:353-376`（$balance 订阅 → controller.setData） | 缺失 → `—`（fmt） |
| bonus 模块（赠金） | 🔜 | 数据已有（`deepseek.py:104-119` granted_units 入库） | 加一种数据模块 + 占位符即可。量级 **S** |
| recharge 模块（充值余额） | 🔜 | 数据已有（topped_up_units） | 同上。量级 **S** |
| today 模块（今日已用） | ✅ | `resolver.js:53-56` estimated_today + `whale-pane.js` DataCard 今日行（带「估算」badge） | 本项目额外区分 estimated_today 与（观测口径的）today——估算/观测分层比 DSH 更显式（DATA_MODEL §8.1） |
| session 模块（对话名） | 🔶 | `resolver.js:59-60`（session 模块，data.session_name）| 当前喂入的是 `session_id`（`main.js:151-170` settled 项），非 DSH 的可读对话名；对话名需 `host.listPersistedSessions`/标题事件（FEASIBILITY 标注字段覆盖未验证）。补齐 = **S/M** |
| peak/nextpeak 峰谷模块（含倒计时 ticker） | 🔜 | 无 | 随峰谷电价（一章 🔜）+ 每秒 ticker 渲染。量级 **M**（V2） |
| quota/plan 订阅额度模块（多窗口 planWin） | 🔜 | 无 | 随 provider quota（六章）。量级 **M**（V2） |
| 逐模块样式 7 键（font/size/bold/italic/underline/color/background） | ✅ | `schema.js:39 STYLE_KEYS` + `renderer.js:14-25` moduleStyle + `pet-layer.js:78-89` moduleCss（双渲染面同映射） | DSH 的 size 是 1..50 档线性映射 `--dshw-u`；本项目直用 px——等价简化 |
| 跑马灯渐变文字/渐变底色/峰谷两态配色/系统字体下拉 | 🔜 | 无 | 纯 CSS（background-clip:text + 动画）。量级 **M** |
| 行合并规则（相邻同 row 合并/图片独占行/每行≤6 每泡≤6 行） | ✅ | `schema.js:24-25`（MAX 常量）+ `:120-133` mergeRows（SAME CONSECUTIVE row 才合并——[DSH] C2 精确语义）+ `:80-85` 校验 | 与 DSH 逐条对齐（含「非连续同 row 不合并」的边角语义，schema.js:115-118 注释） |
| 占位符引擎（取不到数显示 `—` 而非 0） | ✅ | `resolver.js:100-115`（resolveText/fmt，`—` ≠ 0 全链路） | 覆盖 5 个占位符（balance/today/estimated_today/turn_cost/session）；DSH 12+ 个中 bonus/recharge/quota/plan/countdown 未做（各行已列） |
| 泡泡编辑器（四阶段：数据层→渲染→基础编辑→进阶） | 🔶 | ①数据层 ✅（schema/resolver/queue 全测）；②渲染引擎基础 ✅（行合并/样式/占位符；跑马灯/ticker/图片缺）；③基础编辑 UI ❌；④进阶 ❌（`ui/settings/index.js:1-10` 是显式 stub，REMAINING_WORK P3-1 DEFERRED） | 补齐路径 = [DSH] C4 四阶段切分；注意**泡泡定义当前不持久化**（config.py DEFAULTS 无 items 键，默认内容硬编码）——数据层→config.json 持久化是编辑器前置（S）。总工作量 **L** |
| 悬浮快捷编辑 / 模块库（另存复用）/ 系统字体枚举 | 🔜 | schema 已预留 lib 字段（`schema.js:108-111`） | 全部属编辑器第④阶段。量级 **M**（含在编辑器 L 内） |
| 编辑器实时预览（与真实泡泡同排版） | 🔜 | 雏形已有：`renderer.js:86-90` BubblePreview（resolveAll） | 双渲染面（renderer.js 与 pet-layer.js）本就共用 resolver，预览天然同排版。量级 **S** |
| 系统泡泡优先队列（预算1 > 预警2 > 消耗3 > 等待4） | ✅ | `bubble/queue.js:15 RANKS` + `notifications.py:32-36`（两端同序）+ show 按 key 去重替换 `:41-56` | **一处语义差**：DSH 等待档会抢占在显示的消耗/预警泡（[DSH] D3 whaleSysPush wait 分支）；本项目 waiting rank=4 排队等待消耗泡 ttl 到期（最长 5s）。对齐 = 抢占逻辑 3 行。量级 **S**（V1） |
| TTL 自动关 + 等待泡常驻（ttl=0）+ 过期巡检 | ✅ | `queue.js:21-25` sweep（注入时钟）+ sticky（`kind==='waiting'` 强制 sticky `:51`） | DSH 的后台标签页 setTimeout 节流三路兜底不适用（Electron 常驻渲染进程无该节流场景） |

---

## 四、提醒系统（[DSH] §D，10 项）

| DSH 功能 | 复刻状态 | 本项目实现（file:ref） | 差距/理由 |
|---|---|---|---|
| 余额预警（balance ≤ threshold） | ✅ | `rules.py:79-133`（阈值 None=off、钱值 1e8 units 比较）+ `notifications.fire`（dedup `balance_low:{scope}:{day}`）+ 恢复自动消除 `:126-133` + `notifications.py:145-173` dismiss_active | 去重**优于 DSH**：DSH 内存布尔（刷新重响）；本项目 DB 持久 + 恢复边沿 + 跨日重置（DR-14） |
| 今日预算（today_usage ≥ budget） | ✅ | `rules.py:140-190`（per-currency scope 各自比较，永不合并跨币种——DR-12；dedup `budget:{scope}:{day}`） | 币种校验「宁可不比较不误报」由分币种 scope 结构性保证 |
| 每轮消耗提醒 | ✅ | `rules.py:197-244`（turn:{dedup_key} 继承结算幂等 + turn_cost_min 地板 + ttl 5s）+ 消费链 `ingest.py:638-646`（best-effort，不碰结算事务） | 重放轮只结算一次 → 只响一次 |
| 提问等待（question） | ✅ | `main.js:226-240`（clarify tool.start/complete → POST /ingest/wait-event）+ `wait_api.py:76-112`（白名单校验+槽位+通知）+ `main.js:246-261` pollWaitState → `controller.js:157-180` sticky 泡泡 + 首次出现音 | A 级事件面（clarify 生命周期事件必发，FEASIBILITY 源码核实）；不能代答（设计意图） |
| 授权等待（approval） | ✅ | `whale_agent/approval_hook.py`（observer-only hook，`SURFACE_FILTER='gateway'` :57，只落 {id,kind,tool,since}）+ `wait_bridge.py:113-144,200-210`（approval-state.json → wait-state 合流） | C 级桥（agent 半体 hook，`hermes_cli/plugins.py:143-148` returns-ignored）；无 asked 网关事件的降级路径已按 FEASIBILITY §4 首选方案落地 |
| 等待去重持久化（刷新/重启不重响） | ✅ | `wait_api.py:92-100`（INSERT OR IGNORE，dedup `wait:question:{tool_id}`）+ `wait_bridge.py:156-197`（解除自动 dismiss）+ `fired_dedup_keys` 重载对齐（`notifications.py:123-131`）+ `controller.js:172-177`（transition-detect 防重复播声） | 优于 DSH localStorage 单键：DB 持久 + 解除联动 |
| 提醒内容模块化编辑（含图片模块） | 🔜 | 默认提醒文案已是模块化 Bubble 定义（`defaults.js:62-90` budget/balance_low） | 「可编辑」随泡泡编辑器（三章）。量级并入编辑器 L |
| 泡泡/音效独立开关（每事件粒度） | 🔶 | 全局独立 ✅：`config.py:48-71`（reminders.{balance_low,budget,turn_cost}_enabled 与 sound.enabled/muted 互不干扰；「不响仍可冒泡」） | per-kind bubble/sound 双开关无（DSH 每行两个 ✓）。补齐 = config 段扩展 + 读取点。量级 **S** |
| 自定义 API 模型独立 alert/budget | 🔜 | 无 | 随 provider 注册表（六章 M11）——阈值评估函数已通用，缺逐模型配置面。量级 **M** |
| OS 级系统通知（用户离开 Hermes 时） | 🔜 | 无 | `ctx.os.notify` 门控通道存在（仅离开 App 时触发，FEATURE_MATRIX §四）——与 DSH「泡泡优先」语义互补。量级 **S**（V1） |

---

## 五、音效 / 角色 / 图片（[DSH] §E，15 项）

| DSH 功能 | 复刻状态 | 本项目实现（file:ref） | 差距/理由 |
|---|---|---|---|
| 五类事件音（press/release/task_finished/question/approval） | ✅ | `desktop/src/sound/engine.js:40 SOUND_EVENTS` + 接线：press/release（`controller.js:99-113` ← pet-layer）、task_finished（`controller.js:136-139`）、question/approval 首次出现（`controller.js:172-177` transition-detect）+ `main.js:178-194`（config.sound.enabled 才建引擎，默认关） | 引擎 27 条测试；无素材时天然无声（结构性静默） |
| Web Audio 预解码缓存 + 同步起播 | ✅ | `engine.js:97`（URL 级 cache）+ `:201-258`（204/0 字节显式拦截 + 解码失败终态缓存不重试）+ `:302-340` playEvent（**同步路径**，未就绪跳过该次不 await） | 与 [DSH] dshvSound 纪律逐条对齐 |
| press/release 无缝衔接（40ms lead 音频时钟排期） | ✅ | `engine.js:38 RELEASE_LEAD_SEC=0.04` + `:69-71` computeReleaseStart（短按排期到按压音尾、长按 clamp 到 now）+ `:342-359` press/release 锚点 | 与 [DSH] pressUp 同构；主线程抖动免疫（音频线程时间轴） |
| 音量三态（volSet=false 跟随全局 / 显式设置用自己值） | ✅ | `engine.js:53-62` resolveVolume + `:375-392` setVolume（explicit 标志区分「默认 100%」与「设了 100%」） | 与 [DSH] v778 三态语义一致 |
| 每音效独立开关 / 音效组空槽 = 静音 | ✅ | `engine.js:187-199` resolveClipUrl（`''` 槽 = 该事件静音、**不回退**基础映射）+ `:416-424` setClip(s) | [DSH] E1 槽位留空=静音语义照抄 |
| mute 总开关（不建 context / 停节点 / 挂起解码） | ✅ | `engine.js:394-413` setMuted（停 active nodes + pending 解码挂起，解除静音补解码）+ 静音时不建 AudioContext（`:222-227`） | [DSH]「音效关不建 context」纪律照抄 |
| 试听（设置面板手势，绕过总静音） | ✅ | `engine.js:366-369` preview（ignoreMute） | UI 侧试听按钮随设置页（六章） |
| AudioContext 生命周期（空闲 suspend / 绝不 close） | ✅ | `engine.js:39 IDLE_SUSPEND_MS=60s` + `:127-185`（seq 中和的惰性+主动 suspend/resume）+ `:459-467` dispose 绝不 close | [DSH] §E1 macOS PreventUserIdleSystemSleep 经验照抄 |
| 默认音效素材 / 预设片段（ya/D 系列、exp_orb 等） | ❌ | 引擎 clip 默认全 null（`engine.js:43-45`） | **理由③（DSH 素材许可）**：DSH 素材不在 MIT 覆盖内、不可再分发（[DSH] §G PROVENANCE）；正式素材 = REMAINING_WORK P3-4 DEFERRED（M10 自制）。**替代**：自制或自由许可素材，引擎 `setClip` 接口已备，落素材即响 |
| 自定义 clip 导入（base64 ≤8MB）+ 可视化裁剪 UI | 🔜 | 引擎已备（setClip/warm）；导入/裁剪/管理 UI 无 | File API 导入 + IndexedDB 存储（FEATURE_MATRIX §四）+ 波形双滑块（[DSH] E1）。量级 **M** |
| 音效组管理 UI（多组/置顶/预设组不可删） | 🔶 | 引擎最小音效组 ✅：`engine.js:426-435` setSoundGroup（组槽位覆盖基础映射，空槽=静音、缺省回退） | 管理 UI、多组切换、预设组与置顶逻辑无。量级 **M** |
| 默认鲸鱼角色 | 🔶 | `assets/whale-pet-pack/`（pet.json + Codex 规格 spritesheet 1536×1872，8 列×9 行，9 态×6 帧）+ `tools/build-whale-pet-pack.py`（生成器自检断言） | DR-15 宿主化：角色 = Hermes 内置宠物穿皮肤包；**真机装载 NOT VERIFIED**（用户复制到 `pets/whale/` + 图库选择，INSTALL.md §12；REMAINING_WORK P1-3） |
| 自定义角色图（png/gif/apng 导入裁剪/置顶/删除回退） | ❌ | 无 | **理由①（Hermes 核心所有权）**：宠物图库（petdex）、激活（`display.pet.slug`）、AI 生成（/pet-generate）全是 core 一等公民（[PET] §2-§3：SDK 对宠物零导出、pet RPC 核心内部）；插件自建角色库会与 core 图库形成双轨且不可注入宠物窗。**替代**：用户经 Hermes 图库安装任意皮肤包（含 /pet-generate 自生成）；本交互层定位锚 = 官方 a11y 属性 `canvas[aria-label$=" pet"]`（`pet-layer.js:26`），**对任意皮肤通用** |
| 泡泡图库（导入/删除/持久化 + 资源管理窗） | 🔜 | image 模块 schema/渲染占位已备（三章） | IndexedDB + 对象 URL，路径明确（FEATURE_MATRIX §四）。量级 **M** |
| 内置语义图常驻（bimg_petpet/money1 类，删光图库不破坏默认内容） | 🔜 | 无 | 机制照抄点：默认定义引用的语义 id 与用户图库解耦（DSH DEFAULT_BUBBLE_IMGS 先查用户后回退包内）；素材须自制（同上③）。量级 **S**（随图库） |

---

## 六、自定义 API / Provider + 设置与持久化（[DSH] §F + §0，18 项）

| DSH 功能 | 复刻状态 | 本项目实现（file:ref） | 差距/理由 |
|---|---|---|---|
| Provider 模板抽象（name/currency/kind/balance{url,auth,json}/probe/matchIds/noBalanceApi） | 🔶 | `dashboard/whale_core/providers/deepseek.py:31-44` TEMPLATE（含 verified 标签）+ `registry.py:6-7` docstring 锚定 [DSH] F1 shape + `base.py`（错误分类 ProviderTimeout/NetworkError/BadResponse） | 模板**引擎**（JSON path/scale/matchIds 归因/POST body 占位）未通用化——deepseek 字段为直读。量级 **M** |
| 34 厂商模板库 | 🔜 | 无（1/34） | registry.py:1-7 明示 M11 generalises；模板是纯数据，但接口地址/字段路径需逐家验证时效（[DSH] §G：原仓库自己记录过硅基流动接口下线）。量级 **M~L**（V2） |
| 凭据解析（Hermes secret → env → 文件兜底）+ 指纹外显 | ✅ | `gateway.py:46-69`（三级解析，永不 raises/永不记 key）+ `:41-43` 指纹 + `:72-83` credential_status（唯一可出半体的凭据形状） | 与 DSH ctx.credentials 等价且不落密钥（C2/DR-3） |
| 余额端点对接（GET + Bearer + 防御性字段读取） | ✅ | `deepseek.py:72-123`（超时/网络/HTTP/JSON 四类错误映射 + raw body 防密钥混入 `:126-130`） | [DSH] A1 通道①等价 |
| JSON 字段路径（a.b[0].c）+ scale 乘数通用取数 | 🔜 | 无（字段直读） | 纯函数 + 模板字段。量级 **S/M** |
| 探活 probe（验证 key 连通性，多为 /v1/models） | 🔜 | 无 | httpx GET + 状态码判定。量级 **S**（随模板引擎） |
| 无余额接口类（探活 + 会话事件估算 + 「不算错误」） | 🔶 | 会话事件估算 ✅：`pricing.py:348-367` hermes_estimate basis（core 自带 cost_usd）+ `:369-377` whale_pricing 兜底——对**全部**模型生效，等效覆盖「无余额接口模型的今日已用」；unpriced → NULL 不造 0 | 探活验证、`apiNote` 原因标注、`entry.error=null` 语义未做（随 34 模板）。量级随模板 **M** |
| 订阅额度 quota（单/多窗口已用% + 重置倒计时） | 🔜 | 无 | ai-usage-tracker 探针范式已验证（FEASIBILITY §一 quota 行）。量级 **M**（V2） |
| 手动额度（token 口径 input+cacheRead+output / 不重置/每日/每月） | 🔜 | 无 | token 累计口径已在 usage_event 全量留存，缺累计视图。量级 **M** |
| 逐模型余额预警 / 今日预算 | 🔜 | 阈值评估函数已通用（`rules.py`），缺逐模型配置与余额观测面 | 随 provider 注册表 M11。量级 **M** |
| 凭据目的地白名单 + 写请求仅限本机 | ✅ | `gateway.py:86-90` assert_allowed_origin（origin 必须等于模板钉死端点）+ `security.py:32-37` verify_loopback（全部写端点 Depends，`api.py:159,182,237,282,289` 等） | [DSH] F2 credentialMayGoTo + 「远端能改配置=能外带 key」威胁模型照抄 |
| 密钥永不落配置/日志/响应 | ✅ | `config.py:41,149-176`（FORBIDDEN_KEY_SUBSTRINGS 白名单拒写）+ `security.py:59-67`（sk-/Bearer 形状扫描，入库前断言）+ `logging_setup.py` 脱敏 + `tests/test_logging_redaction.py` | AGENTS §7 落地；ctx.storage 明文禁区（JS 半体零持久化，AGENTS §8） |
| 多 key 并存 | 🔶 | 指纹分账本 ✅（换/删 key = 新 scope 新账本，数据不丢——`balance_ledger.py` scope 键） | 并存管理面（多 key 同时配置/切换/逐 key 显示）无：CREDENTIAL_ENV 每 provider 一个键（`gateway.py:34-36`）。量级 **M** |
| 设置持久化（外观/开关/阈值/泡泡配置） | ✅ | `config.py:43-77` DEFAULTS + `:119-146`（deep-merge 读取 + 损坏隔离改名）+ `:149-190`（写白名单 + 原子写）+ `:208-213` reset_defaults | 机制完整且 fail-open/fail-closed 分层；对比 DSH 七个 JSON 文件族收敛为单 config.json + SQLite |
| 设置 UI（外观/泡泡/音效/提醒/模型五面板） | 🔜 | `ui/settings/index.js:1-10` 显式 stub；REST 面完整（`api.py` /config GET/PUT、/pricing/custom、/balance/adjustment…） | ROUTES_AREA + SIDEBAR_NAV_AREA + STATUSBAR chip 组合已验证（FEATURE_MATRIX §六）。量级 **M**（M12，REMAINING_WORK P3-1） |
| 管家面板 / 宠物本体双形态开关 | ✅ | `config.py:74-76` pane.enabled（默认 false）+ `main.js:394-402`（条件注册 registerPane；宠物本体为主交互面） | DR-16 交付；⚠ 附注：main-wiring 一条断言仍假定「register 即注册 pane」，需随 DR-16 更新（唯一红测） |
| 安装 / 更新 / 卸载 | 🔶 | `INSTALL.md`（部署/启用/凭据/卸载/回滚/数据目录 + §12 皮肤包）+ `plugin.yaml`/`catalog/whale-widget.yaml` + unified 包 opt-in | catalog `repo/sha` 占位（REMAINING_WORK P3-3，M13 定稿）；全链路真机 NOT VERIFIED（需用户执行部署步骤） |
| 常驻生命周期（随宿主启动出现 / 退出消失 / 禁用清理） | ✅ | `main.js:196-443` register（runtime-loader 自动加载）+ `:404-413` ctx.onDispose（定时器/轮询/层清理）+ 内嵌形态随渲染进程同生命周期 | 无孤儿面（无子进程）；P2 独立窗路线已由 core 宠物窗承接（DR-15） |

### 附注（本轮实测发现的既有问题，非本任务引入）

1. **node 测试 1 条红**：`desktop/tests/main-wiring.test.mjs:70`（「floating pane contribution…」）断言 register 时 pane 即注册；DR-16 已把 pane 改为 config 载入后条件注册（默认关），断言未同步。属测试过期而非功能回归。
2. **泡泡定义未持久化**：config.py 尚无泡泡 items 键——编辑器（三章 🔶）动工前需先补数据面持久化（S）。
3. **balance_summary 跨 scope 合并**（一章 🔶）与 DSH「历史本不合并」语义有别，多 key 前需拆分。

---

## 复刻优先级建议（用户价值 × 工作量，衔接 REMAINING_WORK.md）

### V1 队列（高价值 / 小中工作量——把「已能记账」变成「看得见摸得着」）

| 序 | 项 | 价值 | 量级 | 依赖/引用 |
|---|---|---|---|---|
| 1 | 设置 UI（M12：阈值/提醒开关/音效/轮询间隔） | 高——目前一切配置靠手改 config.json | **M** | REMAINING_WORK P3-1；REST 面已全备 |
| 2 | 点击宠物/面板 = 手动刷新余额（接 /balance/refresh） | 高——DSH 核心交互闭环 | **S** | 一章 🔶 #1 |
| 3 | 7 日历史 + 模型占比条 + 逐轮明细视图（只缺渲染） | 高——账本数据已齐，无 UI 等于没有 | **M** | REMAINING_WORK 之外新增；数据面 ✅ |
| 4 | bonus/recharge/link 模块 + 占位符扩充 + 等待档抢占对齐 | 中——泡泡表现力补齐 | **S**（每项 S） | 三章 🔜/🔶 |
| 5 | 数字滚动动画 + 余额变化泡泡 | 中——DSH 的「活着」感 | **S** | 一章 🔜 |
| 6 | OS 通知接线（用户离开时余额/预算升级通道） | 中 | **S** | 四章 🔜 |
| 7 | 真机冒烟闭环（皮肤包装载 + 宠物点击 + 面板） | 高——当前全部 NOT VERIFIED 项的收口 | **S**（人工） | REMAINING_WORK P1-3 |
| 8 | node 红测修复 + balance_summary 分 scope | 维护性 | **S** | 附注 #1/#3 |

### V2 队列（大工作量 / 依赖项）

| 序 | 项 | 量级 | 依赖/引用 |
|---|---|---|---|
| 1 | 泡泡编辑器（四阶段；先补定义持久化） | **L** | [DSH] C4；REMAINING_WORK P3-1 后续 |
| 2 | 34 provider 模板 + JSON path/scale/probe + quota + 逐模型 alert/budget | **M~L** | registry M11；逐家时效验证 |
| 3 | 峰谷电价 + peak/nextpeak 模块（可选时区） | **M** | pricing note；DR-12 |
| 4 | 泡泡图库 + 内置语义图 + 自定义 clip 导入裁剪 + 音效组 UI + 正式音效素材 | **M** | M10/P3-4；素材许可约束 |
| 5 | track③ state.db 只读交叉校验 | **M** | REMAINING_WORK P3-2（DEFERRED-BY-DESIGN） |
| 6 | upstream `host.pet.say/react/setActivity/getBounds` 跟进 | 外部 | FEASIBILITY §3.1；落地后泡泡合流 + 吸附摆位 |

### 明确不做（与 ❌ 对应）

- 自定义角色图库/角色管理（core 宠物图库所有权）——以皮肤包 + petdex + /pet-generate 承接；
- 移动端交互（平台不存在）；
- DSH 宿主适配层与 DOM Hack（tapIndex/composer 判定/滚轮让位/IME 排队）——Hermes 插件机制下无此问题面；
- DSH 素材搬运（许可不允许）。
