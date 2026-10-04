# HERMES_PET_SYSTEM — Hermes 内置宠物系统调研（2026-10-04）

> 事实来源：本机 `D:\hermes\hermes-agent`（v0.21.5）源码，只读核查，全部结论附 file:line。
> 背景决策：用户要求**不再自建宠物角色**，以 Hermes 内置宠物系统为宿主承载 whale widget 功能。

## 1. 系统组成

| 部分 | 位置 | 说明 |
|---|---|---|
| Python 侧 | `agent/pet/`（constants/manifest/render/state/store/generate） | 皮肤包存储、petdex 在线目录、终端渲染、AI 生成管线 |
| 桌面侧 | `apps/desktop/src/store/{pet,pet-overlay,pet-gallery}.ts` + `components/pet/` | 姿态状态机、弹出式透明 overlay、图库 |
| 命令面 | `tui_gateway/server.py:180` | RPC：pet.cells/gallery/generate/hatch/info/select/thumb（全部核心内部） |
| 宠物泡泡 | `components/pet/pet-bubble.tsx` | popped-out overlay 里的语音泡泡 + 状态徽标 |

## 2. 皮肤包格式（= 我们的集成接口）

- **位置**：`<HERMES_HOME>/pets/<slug>/`（store.py:20-24），自动发现——`installed_pets()` 枚举所有含可用 spritesheet 的目录（store.py:117-120），**无需注册**。
- **pet.json**：`{id, displayName, description, spritesheetPath, createdBy?}`。
- **spritesheet**（constants.py）：Codex 格式 **8 列 × 9 行 = 1536×1872 px**，帧 192×208，每态 6 帧，循环 1100ms；行序（CODEX_STATE_ROWS）：
  `idle, running-right, running-left, waving, jumping, failed, waiting, running, review`
- **渲染状态**（PetState）：`idle/wave/run/failed/review/jump/waiting`（7 态），桌面端由会话状态派生（pet.ts:107 derivePetState；busy→run、attention→waiting、toolRunning/reasoning 细分）。
- **激活**：配置键 `display.pet.slug`；未配置时取字母序第一个（store.py:127-131）。
- 宠物可弹出为**独立透明置顶窗口**（pet-overlay：popOutPet/restorePetOverlay，pet-overlay.ts:197-242），支持 Alt+滚轮缩放、提交输入、未读徽标（$petUnread）、反应动画（forwardPetReaction('vibe')，唯一 kind，硬编码于 vibe-hearts.tsx:74）。
- `agent/pet/generate/`：内置 AI 皮肤生成（`/pet-generate`，示例提示词含 "pixel dragon" 等），产物同格式入库。

## 3. 插件扩展面结论（关键）

- **`@hermes/plugin-sdk` 对宠物零导出**（sdk/index.ts 全文 grep 无 pet）。
- 宠物泡泡文字**纯派生**自 `$petState/$petActivity`，短语硬编码（pet-bubble.tsx:33-67 SPECS），无注入点。
- 宠物姿态、反应、overlay 窗口均为核心内部 atom/store，插件（渲染进程 blob ESM，import 白名单）不可触达。
- **结论：宠物行为/泡泡/姿态对插件 = 无官方扩展面**；唯一合法接口是**皮肤包文件**（§2）。

## 4. 集成方案（架构修订 DR-15）

**宿主角色 = Hermes 内置宠物（穿鲸鱼皮肤包）+ whale 管家面板（原 floating pane 去角色化）**

1. **鲸鱼皮肤包**（`assets/whale-pet-pack/`）：pet.json + Codex 规格 spritesheet.png（9 pose × 6 帧像素鲸鱼，`tools/build-whale-pet-pack.py` 纯 stdlib 生成）。用户手动复制到 `D:\hermes\pets\whale\`（遵守 AGENTS.md §0——由用户执行），图库中选择即变成鲸鱼。
2. **管家面板**：移除自建 SVG 鲸鱼（不再"单独创建宠物"），保留泡泡引擎（单轮消费/预算/余额/等待）+ 数据卡 + 音效；情绪状态机改为驱动泡泡与面板强调色。用户将面板拖到宠物旁即成"宠物 + 随身账本"组合。
3. **姿态语义天然对齐**：会话 busy→宠物 run、awaiting→waiting（官方行为，use-pet-bridge.ts），与我们的提醒语义一致，无需注入。
4. **Upstream 提案**（记录于 FEASIBILITY_REPORT §upstream）：`host.pet.say(lines)`、`host.pet.react(kind)`、`host.pet.setActivity(patch)`——让插件能驱动官方宠物的泡泡与姿态；这是"宠物原生承载记账提醒"的正解，当前版本缺失。
