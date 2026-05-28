# 🚀 CardKit v2 — 飞书卡片全面升级

## 这是什么

**feishu-cardkit** 是一个飞书流式卡片 SDK + Hermes Agent 集成方案，包含：

- `src/feishu_cardkit/` — 核心 Python 包（卡片构建、streaming、渲染引擎）
- `install.sh` — 一键安装脚本（安装核心包 + 给 Hermes Agent 打集成补丁）
- `gateway/run.py` / `run_agent.py` 补丁 — Hermes Agent 调用 CardKit 所需的适配代码

---

## 💬 新版卡片设计

布局大幅精简，更清爽清晰：

```
旧版                             新版
─────                            ─────
💬 你说                          💬 你说（引用消息）
🛠️ N步（工具面板）                🛠️ N步（工具面板）
💭 思考过程（折叠面板）             正文 ⬇️
  ├─ 正文 markdown                   • 纯文本
  ├─ 表格（column_set）              • 表格（column_set）
  └─ status bar                      • 状态栏
```

**关键变化：**
- **移除 reasoning 面板** — 思考过程不再嵌入主卡片，UI 更精简
- **正文和表格同级** — 不再用外层 column_set 包裹，修复 element nesting 300305 错误
- **状态栏更紧凑** — 精简显示耗时 + token 信息

---

## 📊 表格：column_set 横排布局 + 智能 fallback

### 旧问题
Markdown 原生表格在飞书移动端（窄屏）被截断，内容显示不全。

### 新方案：column_set 横排布局

每行一个 `column_set`，每个单元格一个 `column`，等宽对齐不截断：

```
┌──────────────────────────────────────────┐
│ **损伤类型**  │ **症状**  │ **应急处理**  │  ← 表头行 (grey 背景)
├──────────────────────────────────────────┤
│ 扭伤          │ 肿胀      │ 冰敷加压      │  ← 每行一个 column_set
│ 肌肉拉伤      │ 刺痛      │ 冷敷15分钟    │
│ 擦伤          │ 渗血      │ 碘伏消毒后包扎│     每单元格一个 column
│ 骨折          │ 剧痛      │ 固定转运      │
└──────────────────────────────────────────┘
```

- 等宽对齐，内容自动换行不截断
- 表头灰色背景，表头/数据行视觉分离

### 智能元素安全（200 上限保护）

飞书卡片限制最多 **200 个元素**。系统自动估算表内容量：

```
估算公式：total = 固定元素 + Σ(每表行数 × (1 + 列数 + 列数))

tables 元素 ≤ 200 → column_set 横排布局 ✅
tables 元素 > 200 → 纯 markdown 表格回退（1 元素/表）⚠️
```

对常见场景的测试：
| 场景 | 3表(每表6列×6行) | 5表(3列×4行) |
|------|:-:|:-:|
| column_set 元素 | ≈170 | ≈120 |
| 是否超限 | ✅ 不超 | ✅ 不超 |
| 安全裕量 | ~30 | ~80 |

**配置变更：** `FEISHU_CARD_TABLE_LIMIT: 0 → 3` —— 防止 fallback 时纯 markdown 表格触发 API 错误 230099。

---

## 🛠️ 工具调用摘要：一看就知道在干什么

### 之前的问题
- `patch` 只显示路径 `/home/resteryu/...`，不知道改了啥
- 所有工具都取 `args` 第一个值（通常是 mode 等无关参数）：`🛠️ 修补「replace」`
- thinking 态只有 28 字符超短截断

### 现在

| 工具 | 旧 | 新 |
|------|----|----|
| **patch** | `🔧 修补 /home/resteryu/...` | `✏️ Edit「委托书从白名单移除」→「增加白名单验证」` |
| **search_files** | `🔍 搜索「search」` (取到 mode) | `🔍 搜索「FEISHU_CARD_TABLE_LIMIT|table...」` |
| **terminal** | `💻 执行「background」` (取到布尔值) | `💻 执行「git log --oneline -20 — gateway...」` |
| **thinking 态** | `🔍 搜索中…` (<40 字符跳过) | `🔍 正在搜索「FEISHU_CARD_TABLE_LIMIT|table.*limit...` |

**改进点：**
- `patch` 的 params 优先取 `old_string`/`new_string`，显示替换内容概览
- 按 key 名精准匹配摘要字段：`path` > `command` > `query` > `pattern` > `url` > ...
- summary 截断从 50/80 → **150 字符**
- 新增 `_truncate_to_two_lines()` 保留首尾行
- thinking 态状态栏截断从 28 → **150 字符**

---

## 🔧 稳定性提升

- **update_card fallback** — `update_card` 失败时自动走 `patch_card_element` 作为保障，兼容 element nesting 300305 错误
- **外层 column_set 包裹逻辑** — 内容 ≤20 个元素时自动包裹，避免混排导致渲染异常
- **备份保护** — 安装时自动备份旧版本

---

## 📦 安装

```bash
# 一键安装到 Hermes Agent
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash

# 或指定 Hermes 路径
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash -s -- --path /path/to/hermes-agent
```

**install.sh 会完成：**
1. 自动查找 Hermes Agent 安装路径（通过 which / 常见路径 / pip）
2. 下载最新版 `feishu_cardkit.py` 到 `gateway/platforms/`
3. 备份旧版本（`*.bak.%Y%m%d%H%M%S`）
4. 打集成补丁（`gateway/run.py` + `run_agent.py`）

### 卸载

```bash
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash -s -- --uninstall
```

---

## 📁 文件清单

| 路径 | 说明 |
|------|------|
| `src/feishu_cardkit/__init__.py` | 包入口 |
| `src/feishu_cardkit/hermes_controller.py` | **核心引擎** — StreamingCardController |
| `install.sh` | 一键安装脚本（安装 + 打补丁） |
| `docs/` | API 文档 |

### hermes_controller.py 核心模块

| 模块 | 行数 | 说明 |
|------|------|------|
| CardKit 构建器 | ~300 | Card JSON 2.0 构建、列表面板、column_set 表格 |
| Streaming 状态机 | ~200 | CardPhase 四态管理、flushing 调度 |
| 工具摘要渲染 | ~200 | 颜文字、summary 智能提取、截断控制 |
| update / patch | ~100 | update_card + patch_card_element 双路径 |
| build_complete_card | ~150 | finalize 卡片构建 |

### 集成补丁

| 文件 | 变更量 | 说明 |
|------|--------|------|
| `gateway/run.py` | ±173 | 卡片元数据传递 + `_ensure_controller` 延迟创建 |
| `run_agent.py` | ±10 | 引导语 `paralell` → `parallel` 修正 |

---

## ⚙️ install.sh 集成补丁详情

**gateway/run.py 补丁（L13126-L13144）：**
- 新增 `_cardkit_meta` 字典构建，包含 `reply_to_message_id`（飞书原生引用回复支持）
- 移除多余的 `user_question` 参数

**gateway/run.py 补丁（L14560-L14681）：**
- 新增 `_ensure_controller` 延迟创建：agent 在卡片创建完成前返回纯文本时，可回追创建 controller
- 分段校验（先查 controller 是否存在 → 不存在则创建 → 仍不存在才跳过）
- 最终清理路径保护（finalize 调用、卡片文本缓存、streaming 注销）

---

## 📜 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v2.0 (cardkit-v2) | 2026-05-28 | column_set 表格、工具摘要增强、元素安全、集成补丁标准化 |
| v0.1.0 | - | 初版（`main` 分支） |
