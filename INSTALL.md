# hermes-whale-widget 安装指南

> 适用版本：插件 v0.1.0（`plugin.yaml` / `dashboard/manifest.json` / desktop 产物三处一致）。
> 适用 Hermes：**v0.21.5+**（验证基线：v0.21.5+6188.g0ff4c74，Windows x64）。
>
> **部署红线（AGENTS.md §0）**：本项目不自动部署。一切写入 `D:\hermes`（HERMES_HOME）的动作——
> 复制插件目录、修改 `config.yaml`、重启 App——**必须由用户手动执行**，本项目的 agent 不代写。
>
> 用户使用流程级检查清单（每条流程的环节/预期/验证方式）见
> [`docs/plans/USER_FLOW_CHECKLIST.md`](docs/plans/USER_FLOW_CHECKLIST.md)；
> 未完成项总账见 [`docs/plans/REMAINING_WORK.md`](docs/plans/REMAINING_WORK.md)。

---

## 1. 前置条件

| 项 | 要求 | 说明 |
|---|---|---|
| Hermes Desktop | v0.21.5+ | 统一包插件机制、`/api/plugins/<id>/` 挂载、floating pane SDK 均依赖该版本面 |
| Node.js | ≥ 20 | **仅构建机需要**（esbuild 打包 + 测试）；最终用户运行时不需要 |
| Python | 无需用户安装 | dashboard（Python）半体运行在 Hermes 的 `hermes serve` 进程内（importlib 挂载 `plugin_api.py`），不拉起独立 Python 进程、不建 venv |
| 磁盘 | 插件目录约几百 KB | 运行数据（whale.db / 日志）在数据目录随用量增长，与代码目录分离 |

## 2. 插件形态（安装前 30 秒了解）

Unified Package 三半体：

- **desktop 半体** `desktop/plugin.js`：单文件 ESM（构建产物），由 Hermes Electron（runtime-loader）加载，负责管家面板（floating pane）、状态栏芯片、泡泡、事件转发；角色形象由 Hermes 内置宠物承载（可选，见 §12）；
- **dashboard 半体** `dashboard/plugin_api.py`（+ `whale_core/`）：FastAPI router，挂载在 `/api/plugins/whale-widget/`，负责账本（SQLite）、计价、余额轮询、提醒规则、REST；
- **agent 半体** `__init__.py`（+ `whale_agent/approval_hook.py`）：注册 `pre_approval_request` / `post_approval_response` observer hook，把审批挂起状态写入数据目录。

运行数据全部在 **`<HERMES_HOME>/whale-widget/`**（本机默认即 `D:\hermes\whale-widget\`；多 profile 时随 profile 作用域分账），绝不写入插件代码目录：

```
<HERMES_HOME>/whale-widget/
├── whale.db (+ -wal / -shm)   # SQLite WAL 账本（全部记账数据）
├── config.json                # 无密钥配置（阈值/泡泡/轮询/音效开关）
├── credentials.json           # 兜底凭据（仅用户手工创建，插件只读不写）
├── approval-state.json        # 审批挂起状态（agent 半体原子写）
└── logs/whale-widget.log      # 轮转 5×1MB，自动脱敏（sk-/Bearer/Authorization）
```

## 3. 构建（项目内执行）

在项目根目录 `E:\hermes_plugin\hermes-whale-widget\`（或解压后的源码包）执行：

```text
node tools/build-desktop.mjs                        # 产出 desktop/plugin.js（单文件 ESM）
node --check plugin-src/hermes-whale-widget/desktop/plugin.js   # 产物语法检查
node tools/check-security.mjs                       # 产物级安全自检（必须通过）
.venv/Scripts/python.exe tools/check-security.py    # 全源码安全自检（必须通过）
```

- 仓库内 `desktop/plugin.js` 已是构建产物；若拿到的是 release zip（构建时已剔除 tests/preview），可跳过本节直接安装。
- 桌面半体产物即 `desktop/plugin.js`；Python 侧无需构建。

## 4. 安装（手动复制 —— 由用户执行）

> 复制到 `D:\hermes` 的每一步都需用户自己执行——本项目约束（AGENTS.md §0）禁止 agent 代写外部目录。

1. 复制整个 `plugin-src/hermes-whale-widget/` 目录到 `D:\hermes\plugins\whale-widget\`
   （目标目录不存在则新建；升级安装时覆盖前建议记下旧版本号便于回滚，见 §9）。
   复制后的结构：

   ```
   D:\hermes\plugins\whale-widget\
   ├── plugin.yaml            # agent 半体清单（provides_hooks 声明）
   ├── __init__.py            # agent 半体入口
   ├── whale_agent\           # 审批观察 hook
   ├── dashboard\             # Python 半体（plugin_api.py + whale_core/）
   ├── desktop\               # 桌面半体（plugin.js = 构建产物）
   └── catalog\               # catalog PR sidecar（占位，见 §11）
   ```

2. 使用发布 zip 安装时解压出同样的结构即可。
3. `.hermes-package.json` 由 Electron 在物化桌面半体到 `desktop-plugins\` 时自动生成，**无需手写、无需手工放置**。

## 5. 启用

1. 编辑 `D:\hermes\config.yaml`，在 `plugins.enabled` 列表中加入 `whale-widget`
   （保留列表中其它既有插件名，不要删除用户已有条目）：

   ```yaml
   plugins:
     enabled:
       - whale-widget
   ```

2. **重启 Hermes App**。dashboard / agent 半体在 serve 进程内，启用必须重启一次才生效（desktop 半体本身支持热载，但首次统一包安装共用这一次重启）。
3. 重启后在 Settings → **Plugins 页**找到 **Whale Widget**，**启用桌面半体**——desktop 半体默认关闭（opt-in），此开关实时生效、无需再重启。

## 6. 验证

| 检查点 | 方式 | 预期 |
|---|---|---|
| `/health` | App 运行中请求 `GET /api/plugins/whale-widget/health`（serve 端口由 App 动态分配，可从日志获取；或经 `node tools/dev-preview.mjs` 预览面间接核对） | `{"ok":true,"plugin":"whale-widget","schema_version":1,...}`；账本损坏时 `ok:false` + `ledger_error`（fail-closed） |
| 运行日志 | 查看 `<HERMES_HOME>/whale-widget/logs/whale-widget.log` | 首次请求后出现 `whale-widget runtime started: data_dir=... schema_version=...` |
| 状态栏芯片 | 看 Hermes 底部状态栏右侧 | 出现 whale-widget 芯片：`●` ok（后端与账本可用）/ `◐` 账本降级 / `○` 后端不可达 / `◌` 探测中 |
| 管家面板 | Plugins 页启用桌面半体后 | floating pane 出现管家面板（泡泡/数据卡），可拖拽、点击、按压；角色形象由内置宠物承载（§12，可选） |
| 数据目录 | 查看 `<HERMES_HOME>/whale-widget/` | 自动生成 `whale.db` / `config.json` / `logs\` |

未配置凭据时余额显示 **`—`（不是 0）**——这是预期语义（「未配置 ≠ 余额为零」，AGENTS.md §8 红线），配好凭据后自动进入余额轮询。

## 7. 凭据配置（DeepSeek；三种方式，按解析优先级排列）

解析顺序（`whale_core/providers/gateway.py`，先命中先用）：

1. **Hermes profile secret scope** —— `agent.secret_scope.get_secret("DEEPSEEK_API_KEY")`；
2. **进程环境变量** —— 同名 `DEEPSEEK_API_KEY`（1、2 在 REST 上均显示为 `source:"hermes_secret"`）；
3. **插件数据目录 `credentials.json`**（兜底，`source:"credentials_file"`）。

密钥本体只在 Python 半体进程内解析；REST 响应、日志、前端能看到的只有
`{provider_id, configured, source, credential_id, fingerprint}`（fingerprint = sha256 前 24 位）。
携带凭据的出站请求只允许发往模板钉死的 provider 端点（自定义 host 需显式确认，云元数据地址一律拒绝）。

### 方式 A（推荐）：Hermes secret_sources

按 Hermes 官方机制（Bitwarden / 1Password / Command 源）在所用 profile 的 secret scope 中配置
env 名 **`DEEPSEEK_API_KEY`**。优点：密钥不落插件可见的明文文件，且随 profile 作用域隔离。

### 方式 B：进程环境变量

在启动 Hermes App 的用户环境中设置 `DEEPSEEK_API_KEY=<你的密钥>`
（Windows：系统属性 → 环境变量 → 用户变量），**重启 App 生效**。适合单 profile 部署。

### 方式 C（兜底）：credentials.json

手工创建 `<HERMES_HOME>/whale-widget/credentials.json`（本机默认 `D:\hermes\whale-widget\credentials.json`）：

```json
{"providers": {"deepseek": "<你的密钥>"}}
```

也接受扁平 `{"deepseek": "<你的密钥>"}` 与嵌套 `{"providers": {"deepseek": {"api_key": "<你的密钥>"}}}`。

### 安全说明与风险标注（必读）

- **credentials.json 是明文文件**：Windows 下仅依赖用户目录 ACL 保护，DPAPI 等加密方案未验证。
  仅当方式 A/B 均不可用时使用；注意文件权限，不要把它同步/备份到不可信位置。插件只读该文件，**绝不代写**。
- **绝不把 key 写进 config.json**：config.json 是无密钥配置文件，写接口对 credential 类字段名
  （secret/token/password/api_key/credential）一律拒绝；即使手改进去也不生效，徒增泄露面。
- 换 key（指纹变化）→ 余额轨②按新指纹开新记账 scope，旧账不混算。
- 提交/分享任何文件前用 `git diff` 自查不得出现 `sk-`、`Bearer ` 模式（AGENTS.md §7）。

## 8. 配置项（config.json 全部键与默认值）

来源：`whale_core/config.py` 的 `DEFAULTS`（全集，无遗漏）。文件位置
`<HERMES_HOME>/whale-widget/config.json`；读取时与默认值深合并（缺键回默认、损坏文件自动隔离），
写入经白名单校验（未知节拒绝、credential 类字段名拒绝）。设置 UI 属 M12（未实现），
当前可直接编辑该文件，或经 `PUT /api/plugins/whale-widget/config`。

| 键 | 默认 | 含义 |
|---|---|---|
| `balance_poll_seconds` | `60` | 余额轮询间隔（秒）。Python 半体轮询每周期重读（钳制 5–3600）；desktop 展示层轮询同用此值 |
| `usage_summary_poll_seconds` | `30` | 今日消费汇总（`/usage/summary`）轮询间隔（秒） |
| `reminders.balance_low_enabled` | `true` | 余额不足提醒开关 |
| `reminders.budget_enabled` | `true` | 今日预算提醒开关 |
| `reminders.turn_cost_enabled` | `true` | 单轮消费提醒开关 |
| `thresholds.balance_low` | `null` | 余额预警阈值，**货币值**（与余额 API 返回币种一致，直接比较不折算）；`null` = 规则关 |
| `thresholds.daily_budget` | `null` | 今日消费预算，**货币值**（与 usage 轨当日估算合计比较，逐币种分列、不跨币种求和）；`null` = 规则关 |
| `thresholds.turn_cost_min` | `null` | 单轮消费提醒下限，**货币值**（已计价轮 ≥ 下限才提醒；未计价轮诚实跳过）；`null` = 不设下限 |
| `bubbles.enabled` | `true` | 泡泡系统总开关 |
| `bubbles.turn_cost_ttl_ms` | `5000` | 单轮消费泡泡自动关闭时长（毫秒） |
| `sound.enabled` | `false` | 音效总开关（**默认关**） |
| `sound.muted` | `false` | 静音开关（运行时即时生效） |
| `sound.volume_global` | `100` | 全局音量，**0–100**；每事件音量未单独设置时跟随全局 |

注意：

- 三个阈值为 `null` 时对应提醒规则**整体关闭**——这是「null ≠ 0」语义，未配置绝不当作 0。
- 阈值为货币值，直接与该币种金额比较（不做汇率折算，DR-12）；请填与你的 DeepSeek 账户结算币种一致的数值。
- 提醒去重是持久的（DR-14）：余额预警同日只响一次、预算按日去重，重启 App 不重响；余额回升 ≥ 阈值后未过期预警自动消除。

## 9. 卸载与回滚

### 卸载

1. Settings → Plugins 页**禁用** Whale Widget 桌面半体（desktop 半体实时卸载：定时器/订阅/浮窗全量清理）。
2. 从 `D:\hermes\config.yaml` 的 `plugins.enabled` 移除 `whale-widget`，**重启 App**（dashboard / agent 半体随之不再挂载）。
3. 删除插件目录 `D:\hermes\plugins\whale-widget\`；若 Electron 物化过 `D:\hermes\desktop-plugins\whale-widget\`，一并删除。
4. 数据目录 `<HERMES_HOME>\whale-widget\` **默认保留**（含 whale.db 全部账本、config.json）。
   - 重装或升级后账目自动延续；
   - 确认彻底不再使用且已导出需要的数据后，可手动删除整个目录；
   - 删除前先检查 `credentials.json`（如有）中是否有需要保留的 key。

### 回滚

- **插件版本回滚**：在项目仓库 `git checkout <tag 或 commit>` → 重新构建（§3）→ 用户重新复制覆盖
  `D:\hermes\plugins\whale-widget\`（步骤同 §4–§5，重启生效）。
- **schema 回滚**：migrations 在每次升级迁移前自动备份 `whale.db.bak-<version>`；需要时先退出 App，
  用备份文件覆盖 `whale.db`。
- **仅临时停用**（不回滚版本）：执行卸载步骤 1–2 即可，随时可重新启用，账本无损。

## 10. 已知限制

- **估算 vs 真实严格分列**：单轮/今日消费为估算值（三级计价：hermes_estimate > 价目表 > token_only），
  UI 一律带「估算」角标；真实观测（余额差分）单列展示。未计价轮显示 `—`，绝不按 0 计。
- **素材**：管家面板已去角色化（DR-15），角色形象由 Hermes 内置宠物承载（§12）；音效**不发货默认素材**——
  `sound.enabled` 开启后，在素材就位前也天然无声。
- **未完成里程碑**：M11 多 Provider（现仅 DeepSeek 余额）、M12 设置 UI（现走 config.json）、
  M13 打包发布（catalog `repo`/`sha` 为占位）——未完成项总账见
  [`docs/plans/REMAINING_WORK.md`](docs/plans/REMAINING_WORK.md)。
- **真机端到端未验证**：所有流程的自动化覆盖与待真机清单见
  [`docs/plans/USER_FLOW_CHECKLIST.md`](docs/plans/USER_FLOW_CHECKLIST.md)
  （原因：`D:\hermes` 只读约束，需用户手动部署后执行）。
- **生命周期**：dashboard / agent 半体的启用与禁用需重启 App；desktop 半体热载、实时生效。

## 11. 关于 catalog（catalog/whale-widget.yaml）

该 sidecar 面向**未来**的 catalog PR 分发路径（GitHub repo + SHA pin + 评审准入），其中 `repo`/`sha`
当前为占位，M13 打包定稿。**手动部署（§4–§5）完全不依赖此文件**——复制目录 + `plugins.enabled`
白名单即可。

## 12. 宠物皮肤（可选，推荐）

> 背景（DR-15，2026-10-04）：宿主角色 = **Hermes 内置宠物**穿鲸鱼皮肤包；whale 管家面板已去角色化
> （无自建形象，只承载泡泡/数据/提醒/音效）。系统调研与 file:line 证据见
> [`docs/research/HERMES_PET_SYSTEM.md`](docs/research/HERMES_PET_SYSTEM.md)；
> 架构定性见 `docs/design/ARCHITECTURE_DECISION.md` §11。

### 12.1 什么是 Hermes 内置宠物系统

Hermes 桌面自带桌宠子系统（v0.21.5+）：皮肤包放在 `<HERMES_HOME>/pets/<slug>/`（**自动发现，
无需注册**），每个皮肤包 = `pet.json`（id/displayName/description/spritesheetPath）+ Codex 规格
spritesheet（**8 列 × 9 行 = 1536×1872 px**，帧 192×208，每态 6 帧；行序
idle / running-right / running-left / waving / jumping / failed / waiting / running / review）。
宠物姿态由会话状态自动派生（busy→run、awaiting→waiting），可弹出为**独立透明置顶窗口**
（Alt+滚轮缩放），在宠物图库（petdex）中切换皮肤。

宠物**不是**本插件的组件：插件不注入、不控制它（`@hermes/plugin-sdk` 对宠物零导出，泡泡文字为
core 硬编码）。本插件与它的关系 = 「皮肤包 + 并列摆位」（DR-15）。

### 12.2 安装鲸鱼皮肤包（步骤 2–4 由用户执行）

1. **构建**（项目内执行；纯 stdlib，无第三方依赖）：

   ```text
   .venv/Scripts/python.exe tools/build-whale-pet-pack.py
   ```

   产物为 `assets/whale-pet-pack/`（pet.json + spritesheet.png，9 姿态 × 6 帧像素鲸鱼）。

2. **复制**（用户手动执行——AGENTS.md §0 禁止 agent 代写 `D:\hermes`）：
   把 `assets\whale-pet-pack\` 目录复制到 `D:\hermes\pets\` 下并重命名为 `whale`
   （或把目录内容复制进已新建的 `D:\hermes\pets\whale\`），结果结构：

   ```text
   D:\hermes\pets\whale\
   ├── pet.json
   └── spritesheet.png
   ```

3. **选择**：Hermes 设置的宠物图库（petdex）中选择 **whale**（鲸鱼）。
   注意：未显式选择时宠物取字母序第一个皮肤包，建议在图库中明确点选。

4. **确认**：桌面角落出现像素鲸鱼；可弹出为独立透明置顶窗口，Alt+滚轮缩放调整大小。

5. **摆位**：把 whale 管家面板（floating pane，可拖拽）拖到宠物旁——
   即得「宠物（角色）+ 随身账本（泡泡/数据/提醒/音效）」组合。

### 12.3 替代方式：/pet-generate 自生成

Hermes 内置 AI 皮肤生成：会话内执行 `/pet-generate`，示例提示词 **"cute pixel whale"**，
产物同格式自动入库、图库同样可见可选。与 §12.2 的皮肤包**二选一**即可；
生成器产物为确定性输出（纯 stdlib），便于复检与再分发。

### 12.4 回退

删除 `D:\hermes\pets\whale\` 目录即恢复默认宠物（皮肤包自动发现机制，无需反注册）；
whale 管家面板与记账功能**完全不受影响**——插件运行时不读取皮肤包，皮肤包缺失只是外观回退。

### 12.5 与管家面板的配合

- **姿态语义天然对齐**：会话 busy→宠物 run、awaiting→waiting 是官方自有行为，与本项目的忙碌/等待
  提醒语义一致，无需注入（DR-15）。
- **泡泡分工**：记账/余额/预算/等待提醒泡泡在**管家面板**内呈现；宠物泡泡文字为 core 硬编码短语
  （不可注入）。若希望插件文案直接出现在宠物泡泡上，需等 upstream 采纳 Hermes Pet API
  （见 [`docs/design/FEASIBILITY_REPORT.md`](docs/design/FEASIBILITY_REPORT.md) §3.1），
  当前以「管家面板 + 宠物」并列摆位呈现——把面板拖到宠物旁即可。
