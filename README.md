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
│   ├── controller.py          # StreamingCardController 状态机
│   ├── markdown.py            # Markdown 优化 & 表格解析
│   ├── components.py          # 组件工厂（column_set, collapsible_panel 等）
│   └── api.py                 # CardKit API 封装（创建/更新/流式/补丁）
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
git clone https://github.com/ResterJ/feishu-cardkit.git
cd feishu-cardkit

# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest
```

## 📄 License

MIT License © 2026 Rester (YuZiXuan)
