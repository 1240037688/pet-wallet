# whale-widget 开发命令（M0 脚手架）

> 全部命令在项目根 `E:\hermes_plugin\hermes-whale-widget\` 的 Git Bash 下执行。
> `.venv` 由 `F:\anaconda3\python.exe` 创建（Python 3.13）；Node ≥ 22（本机 `F:\software\nodejs\node.exe`）。
> 所有依赖只装进项目内（`.venv/`、`node_modules/`），禁止全局安装（AGENTS.md §0）。

## 一次性初始化

```bash
# Python venv（测试/安全检查用）
"F:/anaconda3/python.exe" -m venv .venv
.venv/Scripts/python.exe -m pip install pytest fastapi httpx

# Node 构建链（esbuild 本地 devDependency；理由见 package.json comments 字段）
npm install
```

## 构建（desktop 半体）

```bash
node tools/build-desktop.mjs
# 产物 1: plugin-src/hermes-whale-widget/desktop/plugin.js   ← 真机部署复制这一份
# 产物 2: dist/desktop/plugin.js                             ← 验收用副本（gitignored）
```

无 esbuild 环境时的回退：按 `desktop/src/main.js` 的模块结构手写单文件 ESM
（范式参考本机 `D:\hermes\desktop-plugins\ai-usage-tracker\desktop\plugin.js`，
import 白名单只保留 `@hermes/plugin-sdk` + `react*`），产物同样必须过
`tools/check-security.mjs`。

## 静态安全检查（每次提交前两条都跑）

```bash
.venv/Scripts/python.exe tools/check-security.py   # 项目全源码扫描（含 allowlist 说明，见文件头）
node tools/check-security.mjs                       # 构建产物单文件 ESM 检查（官方 admission lint 同构）
```

- `sk-test-fake-…` 是测试假 key 的约定前缀（TEST_PLAN §2.1），不算命中。
- `logging_setup.py` / `security.py` / `check-security.py` 因实现脱敏逻辑而
  含密钥形态字符串，在 allowlist 中逐文件列明理由。

## 测试

```bash
# L1+L2 Python（单元 + FastAPI TestClient 契约）
.venv/Scripts/python.exe -m pytest plugin-src/hermes-whale-widget/dashboard/tests -q

# L1 JS（纯逻辑单测；node 内置 test runner）
node --test plugin-src/hermes-whale-widget/desktop/tests/

# 产物语法检查
node --check plugin-src/hermes-whale-widget/desktop/plugin.js
```

Python 测试通过 `HERMES_HOME` 环境变量注入临时数据目录（conftest fixture），
**永不写真实数据目录**；时间经 `whale_core/clock.py` 注入（TEST_PLAN §2.3 约定）。

## 预览页（无 Hermes 环境走查 UI）

```bash
node tools/dev-preview.mjs          # 默认 http://127.0.0.1:8123/
node tools/dev-preview.mjs --port 0 # 随机端口（输出里看实际地址）
```

打开后应看到：底部状态栏右侧出现
`● Whale widget placeholder · ok · v0.1.0 (schema 1)`，页面顶部弹出
`host.notify: Whale widget placeholder loaded (M0)` toast，且
`window.__preview.errors` 为空。健康数据来自内置 mock（Python 半体未运行）。

## 真机部署（用户手动执行；本项目不自动写 D:\hermes）

1. 复制 `plugin-src/hermes-whale-widget/` → `D:\hermes\plugins\whale-widget\`；
2. `config.yaml` 的 `plugins.enabled` 列表加入 `whale-widget`；
3. 重启 App（dashboard 半体只在 serve 启动时挂载）；
4. Plugins 页 opt-in 启用桌面半体；
5. 验证：statusbar 出现鲸鱼芯片，`GET /api/plugins/whale-widget/health` 返回
   `schema_version`。
   （M13 会产出正式 INSTALL.md 与发布包；以上为 M0 草稿路径。）

## 里程碑命令速查（随里程碑回填 TEST_PLAN §2.4 / AGENTS.md §5）

| 里程碑 | 新增命令 |
|---|---|
| M1 | `node tools/replay-events.mjs <fixtures.jsonl>`（事件重放） |
| M4 | `node tools/mock-provider-server.mjs --port 0`（假 provider） |
