# 宠物 Wallet 优化实施方案（改名 + 订阅额度体系升级）

## 一、方案概览

根据用户明确指示：
1. **改名字**：由 `Whale Wallet` 改为 **宠物 Wallet**。
2. **订阅额度升级**：不局限于 DeepSeek 余额，参考 Hermes 原生 `agent.account_usage` 及 `ai-usage-tracker` 插件，引入对主流大模型（特别是 OpenAI Codex 5小时与1周配额、Claude、Copilot 等）的订阅窗口额度查询与展示。

---

## 二、详细任务拆解

### 任务 1：名称与文案全面升级（改名「宠物 Wallet」）
- **UI 页面与组件**：
  - `desktop/src/ui/dashboard.js`：
    - 页面路由标题：`Whale Wallet` → `宠物 Wallet`
    - 导航栏标签：`Whale Wallet` → `宠物 Wallet`
    - 页面 Header：`🐋 Whale Wallet 用量` → `🐾 宠物 Wallet 用量`
    - 描述与提示文案：统一更新为「宠物 Wallet」
  - `desktop/src/main.js`：
    - 浮动管家面板标题：`Whale Wallet 管家` → `宠物 Wallet 管家`
    - 状态栏芯片与 Toast：更新为「宠物 Wallet」相关提示文案
  - `desktop/src/ui/whale-pane.js`：
    - 标题行文案优化为宠物管家风格。
  - **元数据与文档**：
    - `README.md`、`plugin.yaml`、`package.json` 中的展示文案同步更新。
- **兼容策略**：
  - 底层插件 ID（`whale-widget`）与内部通信通道保持兼容，确保现有各 Profile 的配置项、数据库 `whale.db` 及 Junction 链接平滑继承，无需重新建库。

---

## 三、任务 2：订阅额度系统升级（多 Provider 与时间窗口配额）

### 1. 后端架构重构（`whale_core.providers`）
- **通用 Provider 契约设计**：
  在 `providers/base.py` 中抽象出统一返回规范：
  - **`kind: "balance"`（现金/点数余额）**：
    - `observed_balance_units`: 整数（1e8 定点数）
    - `currency`: 货币代码（如 CNY, USD）
  - **`kind: "quota"`（时间窗口订阅配额）**：
    - `windows`: 列表，每个窗口包含：
      - `label`: 窗口名称（如 `Session (5h)`、`Weekly (7d)`、`Completions`）
      - `used_percent`: 已用百分比（0.0 ~ 100.0）
      - `remaining_percent`: 剩余百分比（0.0 ~ 100.0）
      - `reset_at`: ISO 8601 或时间戳重置时刻
      - `detail`: 补充说明（如 `8 resets banked`、`$15 of $20 left`）
    - `plan`: 订阅类型（如 Plus, Pro, Team）
- **新增主流 Provider 支持**：
  1. **OpenAI Codex (`openai-codex`)**：
     - 直接对齐 Hermes 原生 `_fetch_codex_account_usage`。
     - 捕获 `primary_window`（5小时 Session）和 `secondary_window`（7天 Weekly）。
     - 支持读取 Banked reset 次数与 Credits 余额。
  2. **Anthropic Claude (`anthropic`)**：
     - 捕获 5小时会话窗口与 7天周窗口，以及 Sonnet/Opus 独立额度。
  3. **GitHub Copilot (`copilot`)**：
     - 捕获 Premium 请求剩余数、月度重置时刻。
  4. **DeepSeek (`deepseek`)**：
     - 保留原有的多币种差分现金余额能力。
  5. **其他国内平台（可选接入）**：
     - Z.AI (GLM) 5小时与周配额、Kimi 编码周配额、MiniMax 剩余配额等。
- **凭据与安全性**：
  - 复用 Hermes 原生凭据与运行时环境（`resolve_codex_runtime_credentials`、环境变量 `OPENAI_API_KEY` / `CODEX_*` 等），严禁明文外泄。

### 2. 前端展示升级（`desktop/src/ui/dashboard.js`）
- **卡片自适应渲染**：
  - 如果 Provider 是 `kind: "quota"`（如 Codex）：
    - 渲染双进度条：**5小时额度（Session）** 和 **周额度（Weekly）**；
    - 展示剩余百分比、重置倒计时（如 `2小时45分后重置`）；
    - 若有 Banked reset 则显示重置胶囊徽标。
  - 如果 Provider 是 `kind: "balance"`（如 DeepSeek）：
    - 保持现有的清晰大字余额与五状态指示灯。
- **桌面宠物泡泡（Pet Layer）联动**：
  - 支持泡泡轮询播报活跃模型额度（如 `Codex: 5h 剩余 75% | 周 剩余 90%`）。

---

## 四、遗漏风险点与防范对策

| 风险点 | 影响范围 | 应对对策 |
|---|---|---|
| **改名导致现有配置找不到插件** | Hermes 桌面端无法加载 | 仅变更前端 Display Name 与页面标题；底层插件 ID 与路由路径保持原有别名兼容，防止配置断裂。 |
| **Codex 401 探针失败** | 用户未登录或 Token 过期 | 状态诚实降级为「未配置」或「需重新登录」，带引导提示，绝不捏造假数据或导致后台崩溃。 |
| **并发查询拖慢后台或打满速率** | 弱性能服务器资源消耗大 | 引入 60 秒轻量内存缓存（TTL Cache）；仅在用户打开页面或主动点击刷新时探查，无网络无头空转。 |
| **测试断言冲突** | 原有 244 个 JS / 198 个 Python 测试报错 | 同步更新测试用例中硬编码的旧名字文案及单 Provider 断言，确保测试全绿。 |

---

## 五、验收标准

1. 桌面端左侧导航、页面顶部标题、悬浮管家卡片统一显示为 **宠物 Wallet**。
2. 在「订阅额度」面板中，不仅能看 DeepSeek 余额，还能清晰查看 Codex 的 **5小时会话配额** 和 **一周订阅配额**（包含百分比进度与重置时间）。
3. 单元测试全部通过（JS 244+，Python 198+），安全自检 100% 通过。
4. 部署至实际环境（`D:\hermes`）后各 Profile 无报错。
