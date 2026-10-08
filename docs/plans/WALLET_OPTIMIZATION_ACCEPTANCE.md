# 宠物 Wallet 优化实施验收报告（2026-10-08）

## 一、需求执行结果

### 1. 改名落地（Whale Wallet → 宠物 Wallet）
- **左侧导航栏**：注册显示为「宠物 Wallet」（`ROUTE_TITLE = '宠物 Wallet'`）。
- **页面 Header**：更新为「🐾 宠物 Wallet 用量 · {profile}」。
- **悬浮面板**：标题更新为「宠物 Wallet 管家」，面板顶栏更新为「🐾 宠物管家」。
- **状态栏与 Toast**：更新为「宠物 Wallet」系列提示，提示加载状态清晰。
- **兼容性保障**：底层保留插件 ID `whale-widget` 和路由 `/whale` 内部映射，未破坏任何已存在的 profile 绑定与数据库。

### 2. 订阅额度与配额体系优化（Codex 等多 Provider 接入）
- **后端架构升级**：
  - 新增 `whale_core.providers.codex.CodexProvider`，挂载至 `registry.py`。
  - 标准化双模支持：资金余额型（`kind="balance"`，如 DeepSeek）与时间窗口配额型（`kind="quota"`，如 Codex）。
  - 直连 Hermes 原生认证链，零额外常驻开销，带 60s 轻量内存缓存（TTL）。
- **前端卡片自适应渲染**：
  - `desktop/src/ui/dashboard.js` 的 `BalanceCard` 自适应支持 Quota 模式：
    - 展示多窗口进度条：**Session 5小时额度**与 **Weekly 一周额度**；
    - 呈现剩余百分比（如 `剩 75%`）、色彩动态健康指示（绿色充足 / 橙色告警 / 红色用尽）；
    - 呈现具体重置时间（如 `重置时间：10月8日 16:32`）；
    - 呈现附加权益提示（如 `💡 You have 3 resets banked - use /usage reset to activate`）。

---

## 二、测试与安全验收

1. **JavaScript 单元测试**：
   - 245 / 245 测试全部通过（`node --test "plugin-src/hermes-whale-widget/desktop/tests/*.test.mjs"`）。
2. **Python 单元测试**：
   - 199 / 199 测试全部通过（`pytest plugin-src/hermes-whale-widget/dashboard/tests`）。
3. **安全扫描**：
   - 产物安全自检：通过（`node tools/check-security.mjs`，无敏感 pattern 与未白名单导入）。
   - 源码安全扫描：通过（`.venv/Scripts/python.exe tools/check-security.py`，109 个文件全绿）。
4. **真实运行时环境验证**：
   - 真实连接当前 Hermes 核心，成功读取出 Codex Plus 订阅：
     - Session (5h): 已用 25%，剩余 75%
     - Weekly (7d): 已用 32%，剩余 68%
     - Banked resets: 3 次可用
   - 实际 `D:\hermes` 部署目标（default profile、code profile、desktop-plugins）已同步更新完毕。
