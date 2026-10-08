# 宠物 Wallet（原 Whale Wallet）改名与多 Provider 订阅额度优化调研

**日期**：2026-10-08  
**目标**：
1. 插件名称升级：由「Whale Wallet / Whale Widget」更名为「宠物 Wallet」（保留底层 ID 兼容）。
2. 订阅额度能力优化：从仅支持 DeepSeek 现金余额，扩展支持多模型时间窗口订阅额度（如 OpenAI Codex 5小时与1周配额、Claude、Copilot、Z.AI 等）。

---

## 一、现有源码与架构调研结论

### 1. 现状盘点
- **插件源码**：`E:\hermes_plugin\hermes-whale-widget`。
- **运行与部署位置**：`D:\hermes\plugins\whale-widget`（含各 Profile 挂载）及 `D:\hermes\desktop-plugins\whale-widget`。
- **当前 Provider 实现**：`dashboard/whale_core/providers/deepseek.py` + `registry.py`。
  - 仅注册了 `deepseek`。
  - 数据模型假定为纯资金余额（`observed_balance_units`, `currency`），不支持时间周期配额（Windows / Quota）。
- **当前前端展示**：
  - 路由标题：`Whale Wallet`（`desktop/src/ui/dashboard.js`）。
  - 管家面板：`Whale Wallet 管家`（`desktop/src/main.js`）。
  - 卡片语义：仅展示 5 状态金额（`正常`、`零余额`、`未刷新`、`获取失败`、`未配置`）。

---

## 二、Hermes 生态成熟参考案例检索

### 1. 参考案例 A：Hermes 原生 `account_usage.py`（权威基准）
- **源码位置**：`D:\hermes\hermes-agent\agent\account_usage.py`。
- **能力定义**：
  - `openai-codex`：
    - 主窗口（`primary_window`，18000s = 5小时）：`Session` 会话额度百分比 `used_percent` 及重置时间 `reset_at`。
    - 次窗口（`secondary_window`，604800s = 7天）：`Weekly` 周额度百分比 `used_percent` 及重置时间 `reset_at`。
    - Banked reset credits 计数及消耗机制。
    - Credits 账户现金/点数余额。
  - `anthropic`：
    - `five_hour`（5小时会话窗口利用率 `utilization` 及 `resets_at`）。
    - `seven_day`（7天周窗口利用率）。
    - `seven_day_opus` / `seven_day_sonnet`（模型专属周窗口）。
  - `openrouter`：API Key 额度上限与已用金额、日/周/月用量汇总。
  - `nous`：Portal 月度订阅 Credits 余额与充值额度。
- **核心优势**：直接复用 Hermes 进程内的 OAuth/Token 解析逻辑（`resolve_codex_runtime_credentials`、`resolve_anthropic_token`），无需外部重复维护握手流程，安全且低开销。

### 2. 参考案例 B：本机已安装插件 `ai-usage-tracker`
- **源码位置**：`D:\hermes\plugins\ai-usage-tracker\dashboard\plugin_api.py`。
- **扩展能力**：
  - 在 `account_usage` 基础上，封装了统一的 `_window(label, used_percent, remaining_percent, reset_at, detail)` 窗口抽象。
  - 补充实现了 `copilot`（GitHub Copilot Chat/Completions/Premium 交互配额）、`opencode-go`（5h/周/月配额）、`zai`（Z.AI / GLM 5h/周配额）、`kimi-coding`（Kimi 周配额）、`minimax`（Coding Plan 剩余用量）。

---

## 三、改造要点与风险控制

1. **改名兼容性（防止断崖破坏）**：
   - **对外显示**：全量变更显示名称为「宠物 Wallet」（侧边栏 Nav、页面 Header、管家浮窗 Pane、状态栏 Chip、提示 Toast）。
   - **底层 ID**：保留插件 ID `whale-widget` 和路由 `/whale` 别名/映射，确保现有 `config.yaml`、SQLite 数据库文件、NTFS Junction 以及已有 Profile 账本数据无缝延续。
2. **低资源与轻量开销保障**：
   - 遵循用户小型服务器性能约束，不启动重型常驻组件。
   - 探针复用原生 `agent.account_usage` 与异步/轻量客户端，增加 60 秒本地 TTL 内存缓存，避免频繁打满上游速率限制。
3. **数据模型扩展（统一双模）**：
   - 兼容现金余额型（`kind="balance"`，如 DeepSeek）与窗口配额型（`kind="quota"`，如 Codex、Anthropic、Copilot）。
