# 宠物交互与智能泡泡系统升级实施方案（DR-17）

## 一、需求背景
用户确认实施方案，将「宠物 Wallet」与 Hermes 内置宠物的交互深度升级：
1. **自动闲时冒泡**：任务完成及时反馈消耗后最新额度；空闲期（默认约 6~8 分钟）低频周期性随机冒泡问候或播报当前会话活跃供应商的额度。
2. **多态连击交互**：点击宠物不停切换不同话术（加权随机池 + 阶梯连击体验）：
   - 1~3 连击：日常问候、活跃供应商配额（如 Codex 5h/周进度）、今日花费钱包信息；
   - 4~7 连击：调皮/吐槽互动台词；
   - 8+ 连击：高阶彩蛋与连击达成；
3. **泡泡可交互**：单击泡泡切下一句，双击可直接唤起「宠物 Wallet」大面板。

---

## 二、架构设计与关键改动

### 1. 泡泡数据源与当前会话供应商感知
- **数据流**：
  - `main.js` 监听会话元数据（`session.info` 中的 `provider` 和 `model`），记录 `currentSessionProvider`。
  - `providers/status` 获取到的各家供应商状态注入 `controller.setProviders(rows)`。
  - `providerBalanceText(row)` 支持 Quota 型（如 `Codex 5h剩75% · 周剩68%`）与 Balance 型（如 `deepseek ¥1.10`）。
  - 若当前会话使用 Codex，优先播报 Codex 额度；若使用 DeepSeek，优先播报 DeepSeek 余额；若无匹配，则汇报已配置订阅概况或今日消费。

### 2. 多阶段话术库（`bubble/defaults.js`）
- 扩充丰富的话术池：
  - **问候与日常（GREETING_LINES）**：6+ 种不同管家问候，随机抽取不重样。
  - **额度与钱包（QUOTA_REPORT / WALLET_LINES）**：动态绑定当前供应商额度与今日开销。
  - **连续点击吐槽（COMBO_TEASING_LINES）**：连击 4~7 下触发吐槽。
  - **高阶彩蛋（EASTER_EGG_LINES）**：连击 8+ 下触发彩蛋。

### 3. 主动闲时与任务后冒泡调度器（Idle & Task Quota Scheduler）
- **Task Complete 触发**：任务完成 3 秒后，自动冒泡汇报“任务搞定！当前 Codex 5h剩XX% / 今日已花费XX元”。
- **Idle 定时器**：每 6~8 分钟在用户空闲时静默触发一次问候或额度提示，TTL 8 秒自动淡出。

### 4. 泡泡自身点击体验（`pet-layer.js`）
- 泡泡 DOM 增加指针事件监听：
  - 单击泡泡：切换下一页/下一个泡泡（`advance`）。
  - 双击泡泡：触发回调打开 `/whale` 路由大面板。
