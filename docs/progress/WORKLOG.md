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
