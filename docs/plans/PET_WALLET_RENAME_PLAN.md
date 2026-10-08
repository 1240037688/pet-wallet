# 宠物 Wallet（pet-wallet）插件物理名与标识全面重构方案

## 一、用户决策基线（Grill Me 结论）
- **Q1（标识规范）**：**A** — 插件全局唯一标识为 `pet-wallet`。
- **Q2（数据目录迁移）**：**B** — 彻底重命名，不留旧别名：数据目录由 `D:\hermes\whale-widget/` 直接变更为 `D:\hermes\pet-wallet/`，旧账本就地继承重命名为 `pet-wallet.db`。
- **Q3（配置白名单范围）**：**A** — 全局同步更新主配置 `D:\hermes\config.yaml` 及所有 Profile（如 `code`）的 `config.yaml`，将 `plugins.enabled` 中的 `whale-widget` 替换为 `pet-wallet`。
- **Q4（桌面路由路径）**：**B** — 彻底切断旧路径，内部路由直接规范为 `/pet-wallet`。

---

## 二、详细执行步骤

### 1. 源码清单与核心模块更名
1. `plugin.yaml`：
   - `name: pet-wallet`
2. `dashboard/manifest.json`：
   - `name: pet-wallet`
3. `dashboard/whale_core/api.py`：
   - `PLUGIN_NAME = "pet-wallet"`
4. `dashboard/whale_core/config.py`：
   - `_PLUGIN_DIR_NAME = "pet-wallet"`
   - 数据库文件：`pet-wallet.db`（平滑兼容迁移历史 `whale.db`）
5. `dashboard/whale_core/logging_setup.py`：
   - 日志文件名：`pet-wallet.log`
   - Logger 名：`pet-wallet`
6. `desktop/src/ui/dashboard.js`：
   - `ROUTE_PATH = '/pet-wallet'`
7. `desktop/src/main.js`：
   - 路由注册路径、导航跳转路径、健康检查探针统一变更为 `/pet-wallet`。

### 2. 单元测试同步更新
- 后端 `dashboard/tests/conftest.py`：`MOUNT_PREFIX = "/api/plugins/pet-wallet"`。
- 前端 JS 测试（`main-wiring.test.mjs`、`dashboard.test.mjs` 等）：更新路由断言与插件名断言。
- 执行 `npm test`（248 项）与 `pytest`（199 项），必须 100% 全绿。

### 3. 构建单文件与产物安全核验
- 执行 `node tools/build-desktop.mjs`。
- 执行 `node tools/check-security.mjs` 与 `check-security.py`。

### 4. 生产环境物理迁移与同步（`D:\hermes`）
1. 数据目录重命名：
   - `D:\hermes\whale-widget` → `D:\hermes\pet-wallet`
   - `D:\hermes\pet-wallet\whale.db*` → `pet-wallet.db*`
   - `D:\hermes\profiles\code\whale-widget`（若存在）→ `pet-wallet`
2. 插件安装目录重命名与同步：
   - `D:\hermes\plugins\whale-widget` → `D:\hermes\plugins\pet-wallet`
   - `D:\hermes\profiles\code\plugins\whale-widget` → `D:\hermes\profiles\code\plugins\pet-wallet`
   - `D:\hermes\desktop-plugins\whale-widget` → `D:\hermes\desktop-plugins\pet-wallet`
3. 配置文件更新：
   - `D:\hermes\config.yaml`：`plugins.enabled` 替换为 `pet-wallet`
   - `D:\hermes\profiles\code\config.yaml`：`plugins.enabled` 替换为 `pet-wallet`
4. 真实环境接口冒烟验证。
