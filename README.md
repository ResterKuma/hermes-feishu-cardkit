<!-- DREAMFIELD_README_HEADER_START -->
<p align="center">
<a href="https://www.dreamfield.top">
<img src="https://www.dreamfield.top/dream-field/contest-readme/assets/dreamseed-readme-banner.png" alt="DreamSeed 种梦计划参赛作品" width="100%" />
</a>
</p>
<!-- DREAMFIELD_README_HEADER_END -->

---

# 🃏 feishu-cardkit

> 飞书 CardKit Python SDK — 流式卡片、JSON 2.0 构建、Markdown 表格渲染，一站式搞定

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ 特性

- 🔄 **流式卡片** — 打字机效果，实时增量更新 AI 回复内容
- 🏗️ **JSON 2.0 构建器** — 声明式 API，轻松构建飞书 CardKit 卡片
- 📊 **Markdown 表格渲染** — 自动将 Markdown 表格转为 `column_set` 多列布局，**完美适配移动端**
- 🧩 **组件工厂** — `column_set`、`collapsible_panel`、`overflow` 等常用组件一键创建
- 🛠️ **工具调用展示** — 折叠面板呈现工具使用步骤
- ⚡ **节流 & 批量刷新** — 内置 throttle + deferred flush，防止 API 限流
- 🧹 **Markdown 优化** — 标题降级、代码块保护、表格间距自动处理

## 📦 安装

```bash
pip install feishu-cardkit
```

## 🚀 快速开始

### 发送一张流式卡片

```python
import asyncio
import lark_oapi as lark
from feishu_cardkit import StreamingCardController

async def main():
    # 初始化飞书客户端
    client = lark.Client.builder() \
        .app_id("cli_xxx") \
        .app_secret("xxx") \
        .build()

    # 创建流式卡片控制器
    controller = StreamingCardController(
        client=client,
        chat_id="oc_xxx",
    )

    # 创建并发送卡片
    await controller.ensure_card_created()

    # 流式更新内容（打字机效果）
    await controller.update_content("你好，", is_partial=True)
    await controller.update_content("你好，世界！", is_partial=True)

    # 完成卡片
    await controller.finalize(text="你好，世界！")

asyncio.run(main())
```

### 用构建器创建卡片 JSON

```python
from feishu_cardkit import CardBuilder

card = (
    CardBuilder()
    .header("项目进度", template="blue", subtitle="本周更新")
    .markdown("**任务完成率：85%**\n\n一切顺利 ✅")
    .table_from_markdown("| 名称 | 状态 | 负责人 |\n|------|------|--------|\n| 前端 | ✅ | 小明 |\n| 后端 | 🔄 | 小红 |")
    .collapsible_panel("🛠️ 详情", ["步骤1: 初始化 ✓", "步骤2: 执行 ✓"])
    .build()
)
```

### 进度通知卡片

```python
from feishu_cardkit import send_progress_card

message_id = await send_progress_card(
    client=client,
    chat_id="oc_xxx",
    title="数据处理中",
    progress_text="正在处理第 3/10 批数据...",
    progress_percent=30,
    status="Running",
)
```

## 🏗️ 项目结构

```
feishu-cardkit/
├── src/feishu_cardkit/
│   ├── __init__.py            # 公共 API 导出
│   ├── builder.py             # Card JSON 2.0 声明式构建器
│   ├── controller.py          # StreamingCardController（简化独立版）
│   ├── hermes_controller.py   # 🤝 Hermes 完整版控制器（2491行）
│   ├── markdown.py            # Markdown 优化 & 表格解析
│   ├── components.py          # 组件工厂（column_set, collapsible_panel 等）
│   └── api.py                 # CardKit API 封装（创建/更新/流式/组件级CRUD）
├── docs/                      # 飞书卡片完整中文文档
├── examples/                  # 示例代码
└── tests/                     # 单元测试
```

## 📖 文档

完整文档见 [`docs/`](./docs/) 目录：

| 文档 | 说明 |
|------|------|
| [00-overview.md](./docs/00-overview.md) | 飞书卡片总览 |
| [02-json-structure.md](./docs/02-json-structure.md) | Card JSON 2.0 结构详解 |
| [06-cardkit-components.md](./docs/06-cardkit-components.md) | 组件文档 |
| [07-streaming-updates.md](./docs/07-streaming-updates.md) | 流式更新 |
| [11-card-callback.md](./docs/11-card-callback.md) | 卡片回调通信 |

## 🧪 开发

```bash
# 克隆项目
git clone https://github.com/ResterKuma/hermes-feishu-cardkit.git
cd hermes-feishu-cardkit

# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest
```

## 🤝 Hermes Agent 适配

本项目提供 **完整版 Hermes 控制器**，可直接替代 Hermes Agent 内置的 `feishu_cardkit.py` 模块，无需修改任何业务逻辑。

### 什么是 Hermes？

[Hermes](https://github.com/nousresearch/hermes) 是一个开源 AI Agent 框架，本 SDK 的 `hermes_controller.py` 从 Hermes 的 `gateway/platforms/feishu_cardkit.py` 完整提取而来，保留了全部功能。

### 迁移方式

只需改一行 import：

```python
# 旧（Hermes 内置模块）
from gateway.platforms.feishu_cardkit import StreamingCardController

# 新（使用本 SDK）
from feishu_cardkit.hermes_controller import StreamingCardController
```

### Hermes 完整版包含（独立 SDK 版不具备的）

- **完整状态机**：`idle → creating → streaming → completed/aborted/terminated/creation_failed`
- **finalize/abort**：带 `scoped_lock` 并发安全的卡片终结
- **build_complete_card**：最终卡片渲染（工具折叠面板 + reasoning + 双语 footer + overflow 菜单）
- **工具映射表**：`_TOOL_DISPLAY` 内置 30+ 工具的 emoji/标题/参数映射
- **节流 & 批量刷新**：`FlushController` 风格的 `_throttled_update` + deferred flush + reflush
- **消息不可用检测**：`mark_message_unavailable` + 30 分钟 TTL 缓存，跳过已撤回/删除的消息
- **Reasoning 过滤**：`<think_phase>` 标签自动剥离 + 折叠显示
- **多轮回复检测**：文本长度回缩自动识别为新一轮，`streaming_prefix` 累积
- **静态降级回退**：CardKit 创建失败时自动回退到 `im.message.create` + `im.message.patch`

### 依赖自动适配

`hermes_controller.py` 中的 `gateway.status` 锁采用 `try/except` 自动降级：

```python
# Hermes 环境下自动启用并发锁
try:
    from gateway.status import acquire_scoped_lock, release_scoped_lock
except ImportError:
    # 独立使用时降级为 no-op
    ...
```

## 📄 License

MIT License © 2026 ResterKuma (YuZiXuan)
