# GITHUB_RELEASE_AUDIT — Pet Wallet 开源发布准备与安全审计报告

> 审计基准：按照开源发布最高合规要求执行，确保代码可复现、敏感信息零泄露、开源项目借鉴与版权声明明确、符合 Hermes 官方插件广场标准。
> 执行范围：工作区代码检查、凭据与路径扫描、开源协议合规、目录结构规范化、社区插件目录格式规范。

---

## 一、项目结构与现状分析

### 1. 核心定位与技术栈
- **项目名称**：`pet-wallet`（原 `whale-widget`）
- **类型**：Hermes Agent 官方统一插件包（Unified Package）
- **技术栈**：
  - **后端（Agent / Dashboard 侧）**：Python 3.12+ / FastAPI / SQLite / httpx
  - **桌面前端（Desktop UI 侧）**：ESM JavaScript / React 18 JSX Runtime（微型 shim）/ Nanostores 响应式原子状态管理
- **运行环境**：Hermes Agent（>= 0.21.0）桌面端及多 Profile 环境

### 2. 目录结构梳理与发布分流
| 目录/文件 | 属性分类 | 发布建议 | 说明 |
|---|---|---|---|
| `plugin-src/hermes-whale-widget/` | 核心源码 | **重命名规范发布** | 将内部物理名重命名为 `plugin-src/pet-wallet/`，包含 Python 后端与桌面前端 |
| `dist/desktop/plugin.js` | 构建产物 | **包含发布** | Hermes 桌面端即插即用所需的预构建 ESM 单文件 |
| `tools/` | 开发与构建工具 | **保留发布** | 包含 `build-desktop.mjs`、`check-security.py` 等构建与安全检查工具 |
| `docs/` | 文档与设计决策 | **精简发布** | 保留核心架构设计、用户指南、API 文档；内部演进草稿规整 |
| `experiments/` | 历史实验与本地备份 | **必须排除（.gitignore）** | 包含本地开发调试临时备份，绝对不能提交到 GitHub |
| `references/` | 外部借鉴参考仓 clone | **必须排除（.gitignore）** | 外部参考仓库本地 clone，属于独立 Git 库，禁止作为嵌套文件推送到公开仓库 |
| `.venv/`, `node_modules/` | 本地依赖环境 | **必须排除（.gitignore）** | 虚拟环境与依赖包 |
| `*.db`, `*.log`, `.pytest-tmp/` | 运行时数据与缓存 | **必须排除（.gitignore）** | 运行时 SQLite 数据库、日志与测试临时文件 |

---

## 二、敏感信息与安全扫描（结果：全部通过）

经全面排查与静态正则扫描：
1. **API Keys / Tokens**：
   - 扫描 `sk-`、`Bearer ` 等模式：所有测试用例均使用已批准的脱敏测试前缀 `«redacted:sk-…»`；无任何明文真实私钥或 API 密钥。
2. **个人隐私与系统路径**：
   - 核心发布源码中无个人路径，无私有用户名硬编码；
   - 外部网络访问严格遵循回环检验（`127.0.0.1` / `::1`）与白名单 Origin 校验。
3. **配置文件与凭据加载**：
   - 严格通过系统安全作用域、环境变量或本地未跟踪的 `credentials.json` 动态加载，不随代码发布。

---

## 三、代码借鉴与参考项目致谢（Attribution & Credits）

本项目在架构演进过程中深度借鉴并融合了以下开源项目与 Hermes 生态组件的优秀设计，必须在 GitHub `README.md` 与文档中明确致谢与标注来源：

1. **[DeepSeek-Balance-Whale-Widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget)** (by @MeteorNOX):
   - **借鉴核心**：
     - 双轨制（Dual-Track）记账模型设计：API 余额实际观测下降（消费）与上升（充值/赠金）的差分记账法，以及定点数精度计算规则。
     - 气泡排版与消息轮换引擎理念（多模块、加权出泡、连击吐槽等趣味交互模式）。
   - **许可协议**：遵循上游开源规范，在 README 中给予显著致谢与声明。

2. **[hermes-ai-usage-tracker](https://github.com/lvabarajithan/hermes-ai-usage-tracker)** (by @lvabarajithan):
   - **借鉴核心**：
     - Hermes 桌面端三域集成规范（`ROUTES_AREA` + `SIDEBAR_NAV_AREA` + `STATUSBAR_AREAS.right`）。
     - 多 Provider 配额窗口抽象（`_window(label, used_percent, remaining_percent, reset_at, detail)`）。
     - Profile 作用域隔离与进程内轻量 TTL 缓存设计。
   - **许可协议**：MIT License 致谢。

3. **Hermes Agent 原生架构 (`agent.account_usage`)** (by Nous Research):
   - **集成核心**：
     - 直连 Hermes 原生认证链与 OpenAI Codex / Anthropic 的配额解析与 Banked Resets 状态感知。

---

## 四、申请加入 Hermes 官方插件广场可行性分析

### 1. 规范对齐要求（参考 `D:/hermes/hermes-agent/plugin-catalog/*.yaml`）
官方插件广场收录门槛：
- [x] **开源透明**：必须有公开可访问的 GitHub 仓库地址。
- [x] **精确提交锁定（Exact-SHA Pin）**：提供明确的 Release 标签及 40 位 hex SHA。
- [x] **统一插件包（Unified Package）**：单插件同时包含 Agent 能力与桌面 UI，无需分拆。
- [x] **安全沙箱与零后门**：
  - 前端桌面脚本在沙箱中运行，无未授权的外部代码下载或自动更新；
  - 后端严格限制回环访问（Loopback Only），不向未经许可的外部第三方泄露凭据；
  - 通过 Hermes 官方 import 白名单与安全扫描。
- [x] **提供标准化 Catalog 元数据清单**（`catalog/pet-wallet.yaml`）。

### 2. 申请提交流程
1. 代码推送到用户的 GitHub 仓库并打出 Release 标签（例如 `v0.1.0`）；
2. 获取发布 Commit 的 40 位 SHA-1 校验和；
3. 向 Hermes Agent 官方仓库（`NousResearch/hermes-agent`）提交 Pull Request，在 `plugin-catalog/pet-wallet.yaml` 添加条目。
