# 宠物 Wallet（pet-wallet）插件更名与部署验收报告（2026-10-08）

## 一、更名与重构执行总结

根据用户决议（Q1=A, Q2=B, Q3=A, Q4=B）：
1. **插件系统标识变更为 `pet-wallet`**：
   - `plugin.yaml` 与 `manifest.json` 全面统一声明为 `pet-wallet`。
   - API 挂载路径对齐为 `/api/plugins/pet-wallet`。
   - 桌面内部路由彻底变更为 `/pet-wallet`。
2. **数据目录无损重命名继承**：
   - 数据目录切换为 `D:\hermes\pet-wallet` 及 `profiles\code\pet-wallet`。
   - SQLite 数据库完整就地继承为 `pet-wallet.db`（含 WAL/SHM 与备份，历史记账数据零丢失）。
3. **物理目录与系统配置全局更新**：
   - 插件目录正式部署于 `D:\hermes\plugins\pet-wallet`、`profiles\code\plugins\pet-wallet` 及 `desktop-plugins\pet-wallet`。
   - 旧 `whale-widget` 物理插件目录已全量移除。
   - `D:\hermes\config.yaml` 与 `profiles\code\config.yaml` 中的 `plugins.enabled` 已同步替换为 `pet-wallet`。

---

## 二、测试与实机验收

1. **测试全绿验证**：
   - **JavaScript 测试**：**248 / 248 项通过**。
   - **Python 测试**：**199 / 199 项通过**。
   - **安全自检**：产物与源码扫描 100% 通过。
2. **真实环境实机加载验证**：
   - 使用 Hermes 真实 Python 环境直接探测 `D:\hermes\plugins\pet-wallet` 运行态：
     - 数据目录：`D:\hermes\pet-wallet`
     - Schema 版本：`v2`
     - 账本状态：`Ledger error: None`（健康）
     - Provider 探测：`openai-codex` 正常读取（当前 Session 5h 剩余 49%，Weekly 剩余 64%）。
