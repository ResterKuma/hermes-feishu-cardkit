# 🚀 CardKit v2 — 飞书卡片全面升级

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
Markdown 原生表格在移动端（窄屏）被截断，内容显示不全。

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
- **备份保护** — `feishu_cardkit.py.bak*` 自动生成，方便回滚

---

## 📁 文件变更汇总

| 文件 | 变更量 | 说明 |
|------|--------|------|
| `gateway/platforms/feishu_cardkit.py` | ±660 | 核心改动 |
| `gateway/run.py` | ±173 | 卡片联动逻辑 |
| `run_agent.py` | ±10 | 引导语优化 |

### gateway/run.py 改动详情

**1. 卡片元数据构建（L13126-L13144）**
- 新增 `_cardkit_meta` 字典，统一构建 metadata
- 加入 `reply_to_message_id` 以支持飞书原生引用回复
- 移除 API 调用时多余的 `user_question` 参数

**2. 最终清理路径安全增强（L14560-L14681）**
- 新增 `_ensure_controller` 延迟创建逻辑：当 agent 在卡片创建完成前就返回纯文本回复时，可回追创建 controller
- Empty State 判断从单一 `is not None` 改为分段校验：先检查 controller 是否存在，不存在则尝试创建，仍不存在才跳过
- 其余逻辑（`finalize` 调用、卡片文本缓存、streaming 注销、日志）保持不变

### run_agent.py 改动详情
- 引导语/提示词中 `paralell` 拼写修正为 `parallel`

---

## Git 历史

**Squash 记录：** 从 `ac5cb5c32` 到 `96fc2c531` 共 40 个 commits 合并为 1 个 commit。

**分支：** `cardkit-v2`（基于 detached HEAD 创建，与 `main` 分支的工作流独立）

```bash
69292353e feat(card): 飞书卡片全面升级 — column_set 表格 + 元素安全 + 工具摘要
```
