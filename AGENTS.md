# AGENTS.md — hermes-whale-widget 操作规范

本文件是所有后续 coding agent 的长期操作规范。任何代码修改前必须先读完本文件。

## 0. 最高约束（用户明确要求，违反即事故）

1. **只允许修改工作区内代码**：即 `E:\hermes_plugin\hermes-whale-widget\` 内的一切。
2. **禁止修改 Hermes 及其它任何外部位置的代码/配置**，包括但不限于：
   - `D:\hermes\`（HERMES_HOME，含 `hermes-agent` 源码、`desktop-plugins`、`plugins`、`state.db`、`config.yaml`）——**一律只读**；
   - 用户全局配置、`~/.hermes`、系统注册表、其它项目目录；
   - 除非用户明确、逐次授权。
3. 调研时可以对 `D:\hermes` 做只读操作（读源码、读数据库 schema、跑只读查询），但不得写入、不得重命名、不得删除。
4. 插件部署/安装测试仅当用户要求时进行；本项目的 dev 流程必须能在不写 `D:\hermes` 的情况下静态验证。

## 1. 项目架构边界

- 本项目是 **Hermes Desktop Plugin（挂件 + 记账 UI）**，目标形态与最终架构见
  `docs/design/ARCHITECTURE_DECISION.md`（调查后确定，见该文档的决策记录）。
- SDK：`@hermes/plugin-sdk`（React + host API，参考本机 `D:\hermes\desktop-plugins\prompt-snippets\plugin.js` 的真实用法）。
- 本项目**不是** Hermes Core 的一部分；**禁止修改 Hermes Core**（见 §0）。
  若调查发现 SDK 缺关键能力，记录到 `docs/design/FEASIBILITY_REPORT.md` 并提出 upstream API 建议，不得自行 patch。

## 2. 目录约定

```text
plugin-src/      插件源码（desktop plugin）
docs/            全部设计与调研文档（结构见 README）
references/      参考项目 clone（gitignore，可随时删除重建）
experiments/     实验/一次性脚本（每个脚本头注释 Purpose/Input/Output/Can delete）
tools/           可复用开发脚本
```

- 禁止在仓库根目录产生 `test2.py`、`final_final2.py` 之类无解释文件。
- `references/` 与 `experiments/` 不进入发布产物。

## 3. 事实来源优先级

```text
本地 D:\hermes\hermes-agent 源码（v0.21.5+6188.g0ff4c74）
  > 本机 Hermes 文档
  > NousResearch/hermes-agent (GitHub)
  > Hermes 官方 example plugins
  > 成熟社区插件（ai-usage-tracker / hermes-pet / avatar_pet）
  > 其它第三方项目
  > README 推测
```

不要因为某社区插件这么写就认为这是 Hermes 唯一方式。

## 4. 文档更新规则

- 修改架构 → 必须同步更新 `docs/design/ARCHITECTURE_DECISION.md`。
- 每个 Milestone 完成 → 更新 `docs/progress/WORKLOG.md`（完成了什么/改了哪些文件/设计变化/测试结果/未解决问题/下一阶段）。
- 实现与计划不一致 → 必须同时改 `docs/plans/IMPLEMENTATION_PLAN.md`，不得让计划与代码脱节。
- 功能变化 → 更新 `README.md` 的已实现/未实现/已知限制三节。

## 5. 命令

（Milestone 0 建立 dev/test 脚手架后回填；在此之前以 `node --check` / 手动 bundle 验证为准。）

```text
# build:    待定（plugin.js 为打包产物）
# test:     待定
# lint:     待定
```

## 6. Windows 特殊注意事项

- 开发机：Windows 10/11 x64，Git Bash 环境；Python 在 `F:\anaconda3\python.exe`。
- 透明窗口/置顶/拖拽涉及 WebView2，行为与 macOS/Linux 不同，一切以 Windows 实测为准。
- 路径统一用正斜杠或 `path` API 处理，防止反斜杠转义事故。

## 7. 安全规则（API Key 等）

- 禁止把 API Key / Token / Cookie 写入 git、日志、README、测试 fixture、SQLite 明文字段。
- 前端/UI 只允许知道 credential 的 id/name，不允许拿到密钥本身。
- 优先使用 Hermes 官方凭据机制（调查结论见 `docs/design/ARCHITECTURE_DECISION.md` §安全边界）。
- 日志禁止输出 Authorization header、完整 provider response 中的敏感字段。
- 提交前检查：`git diff` 中不得出现 `sk-`、`Bearer ` 等模式。

## 8. 记账正确性红线

- 区分：`observed_balance`（API 真实余额）/ `observed_spend`（余额差分）/ `local_usage_cost`（本地估算）/
  `provider_reported_usage` / `manual_adjustment`。禁止混在一个字段，禁止把估算值伪装成真实账单。
- 账本写入必须幂等（event_id 去重；restart/reload/reconnect 不得重复扣费）。
- 余额 API 失败 ≠ 余额为 0；必须区分 unknown / zero / error / stale。
- usage 采集：aggregate → turn end → persist，禁止逐 token 落盘，禁止重复轮询 timer。

## 9. 生命周期红线

- Hermes 退出 → 挂件进程必须退出；禁止 orphan process。
- 处理 plugin disable / reload / Hermes crash / gateway restart。
- 实验/子进程必须由插件统一管理，带清理逻辑。

## 10. 禁止事项（浓缩版）

复制 DSH 插件进 Hermes；monkey patch Hermes 内部对象；DOM scraping 判断 agent state；
明文存 key；把余额 API 失败当余额 0；重复统计 usage；留孤儿进程；删除/覆盖用户已有插件与配置；
绕开 Hermes Plugin SDK；未记录理由新增长期依赖。
