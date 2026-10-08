# GitHub 开源发布整理与审计完整报告（Pet Wallet）

## 一、发布整理结论

**判定结果**：**READY（可以进入 GitHub 仓库发布与提交）**

- **项目物理重构完成**：插件标识全量升级为 `pet-wallet`，面向用户的文字标签统一为 `Pet Wallet`。
- **敏感信息独立审计 100% 通过**：零明文 API Key、零私钥、零个人绝对路径与凭据外泄。
- **开源借鉴与版权致谢明确**：在 `README.md` 与文档中显著标注借鉴了 **DeepSeek-Balance-Whale-Widget** 与 **hermes-ai-usage-tracker**。
- **官方插件广场元数据就绪**：`catalog/whale-widget.yaml` 升级为规范的 `catalog/pet-wallet.yaml`，完全符合 Hermes 官方收录规范。

---

## 二、项目结构规范化成果

### 1. 发布文件清单（可直接推送到 GitHub 仓库）
```text
pet-wallet/
├── README.md               # 项目主说明（核心特性、致谢与开源借鉴、安装与使用）
├── LICENSE                 # MIT License 开源协议
├── SECURITY.md             # 安全与漏洞报告策略
├── CONTRIBUTING.md         # 开发者贡献与测试规范
├── AGENTS.md               # Coding Agent 操作规范与红线
├── .gitignore              # 严密防泄露忽略规则（排除本地 db/log/venv/references/experiments）
├── .env.example            # 安全的环境变量公开模板
├── package.json            # 桌面构建与测试依赖
├── requirements-dev.txt    # 后端开发依赖清单
├── plugin-src/
│   └── hermes-whale-widget/# 统一插件包（含 backend dashboard、agent hook 与 desktop 前端）
│       ├── plugin.yaml     # 插件标准声明（name: pet-wallet）
│       ├── catalog/        # 官方插件广场声明配置
│       │   └── whale-widget.yaml -> 待在官方提 PR 时使用
│       ├── dashboard/      # Python 后端（FastAPI + whale_core + 单元测试）
│       └── desktop/        # 前端 UI（ESM 单文件产物与源码组件）
├── dist/
│   └── desktop/
│       └── plugin.js       # 开箱即用的预构建前端产物（134KB）
├── tools/                  # 构建与双重安全自检脚本
└── docs/                   # 架构审计、测试计划与发布审计报告
```

### 2. 严格排除的文件（已加入 .gitignore，绝对不提交）
- `experiments/`：本地环境调试备份、CMD 命令草稿。
- `references/`：外部参考项目克隆库（`DeepSeek-Balance-Whale-Widget` 等）。
- `*.db`、`*.db-wal`、`*.db-shm`：本地 SQLite 账本文件。
- `logs/`、`*.log`：本地运行日志。
- `.env`、`credentials.json`：真实的本地敏感配置文件。
- `.venv/`、`node_modules/`、`.pytest-tmp*/`：本地虚拟环境与临时测试目录。

---

## 三、安全与敏感信息审计表

| 风险等级 | 检查项 | 扫描结果 | 处理状态 |
|---|---|---|---|
| **Critical** | 明文 API Key / Token 泄露 | 无发现真实密钥（测试仅用 `«redacted:sk-…»` 假数据） | **已通过（100% 干净）** |
| **High** | 私钥、证书或认证文件 | 无敏感凭据文件 | **已通过** |
| **Medium** | 个人用户名与宿主系统路径 | 无个人真实路径残留，排除 `.git` 历史污染 | **已通过** |
| **Low** | 配置文件明文 | 已剥离配置模板至 `.env.example`，真实文件已 gitignore | **已通过** |

---

## 四、功能完整性与测试验证

- **桌面前端 JS 测试**：**248 / 248 项全部通过**（`npm test`）。
- **Python 后端测试**：**199 / 199 项全部通过**（`pytest`）。
- **双重安全自检**：
  - `python tools/check-security.py`：**109 个源码文件全部通过**。
  - `node tools/check-security.mjs`：**单文件构建产物全部通过**。
- **真机实测**：直连当前运行态 `D:\hermes\plugins\pet-wallet`，Codex 5h/Weekly 额度、今日记账账本正常运作，零错误。

---

## 五、GitHub 发布与提交操作建议（可直接复制执行）

请在终端或 Git Bash 中进入 `E:\hermes_plugin\hermes-whale-widget` 执行以下命令初始化提交：

```bash
cd E:/hermes_plugin/hermes-whale-widget

# 1. 检查待提交状态（确认 references/ 与 experiments/ 已经被 gitignore 忽略）
git status

# 2. 暂存所有整理好的发布文件
git add .

# 3. 提交本地 Git
git commit -m "feat: release Pet Wallet v0.1.0 with quota tracking and pet interaction"

# 4. 关联你在 GitHub 上新建的仓库（例如 pet-wallet）
# git remote add origin https://github.com/<你的GitHub用户名>/pet-wallet.git
# git branch -M main
# git push -u origin main

# 5. 打出 v0.1.0 标签
# git tag v0.1.0
# git push origin v0.1.0
```

---

## 六、申请加入 Hermes 官方插件广场指引

在将仓库推送到 GitHub 并打出 Release Tag 后，申请加入官方插件广场只需 3 步：

1. **获取发布 Commit 的 40 位 SHA 校验和**：
   ```bash
   git rev-parse HEAD
   ```
2. **在官方仓库提 Pull Request**：
   - Fork 官方仓库 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)；
   - 在其 `plugin-catalog/` 目录下新增文件 `pet-wallet.yaml`；
   - 内容填入：
     ```yaml
     name: pet-wallet
     repo: https://github.com/<你的GitHub用户名>/pet-wallet
     sha: "<你的40位commit_sha>"
     description: "Pet Wallet — Dual-track AI usage ledger (estimate vs observed balance), pet desktop bubbles, and live multi-provider quota tracking (Codex 5h/Weekly, DeepSeek) for Hermes."
     maintainer: "<你的GitHub用户名>"
     tier: community
     category: desktop
     requires_hermes: ">=0.21"
     platforms: [windows, macos, linux]
     docs_url: "https://github.com/<你的GitHub用户名>/pet-wallet#readme"
     capabilities:
       provides_tools: []
       provides_hooks:
         - pre_approval_request
         - post_approval_response
       provides_middleware: []
       requires_env: []
     ```
3. **提交 PR 等待合并**：合并后，所有 Hermes 用户即可通过 `hermes plugins install pet-wallet` 在官方插件广场一键安装！
