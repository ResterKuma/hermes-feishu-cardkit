<!-- DREAMFIELD_README_HEADER_START -->
<p align="center">
<a href="https://www.dreamfield.top">
<img src="https://www.dreamfield.top/dream-field/contest-readme/assets/dreamseed-readme-banner.png" alt="DreamSeed 种梦计划参赛作品" width="100%" />
</a>
</p>
<!-- DREAMFIELD_README_HEADER_END -->

---

# 🃏 feishu-cardkit

> [Hermes Agent](https://github.com/NousResearch/hermes-agent) 飞书 CardKit 流式卡片扩展库

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 💡 这是什么？

Hermes 是一个开源 AI Agent 框架，原生支持 Telegram、Discord、Slack 等平台，但**飞书的 CardKit 流式卡片功能并不在官方 Hermes 中**。

本库将 Hermes 飞书平台的 CardKit 流式卡片功能独立提取为标准 Python 包，方便：

- 🔧 **Hermes 用户**：直接 `pip install` 替代内置模块，无需改动业务代码
- 🌍 **非 Hermes 用户**：独立使用流式卡片控制器，接入自己的飞书机器人

## ✨ 特性

- 🔄 **流式卡片** — AI 回复打字机效果，实时增量更新
- 🏗️ **完整状态机** — `idle → creating → streaming → completed/aborted/terminated`
- 🛠️ **工具调用折叠面板** — 30+ 工具的 emoji/标题/参数映射，按 Turn 分组展示
- 💭 **Reasoning 过滤** — `<think_phase>` 标签自动剥离 + 折叠显示
- ⚡ **节流 & 批量刷新** — FlushController 风格的 throttle + deferred flush + reflush
- 📊 **Markdown 表格** — 自动转为 `column_set` 多列布局，完美适配移动端
- 🛡️ **消息不可用检测** — 30 分钟 TTL 缓存，跳过已撤回/删除的消息
- 🔀 **多轮回复检测** — 文本长度回缩自动识别为新一轮
- 🪂 **静态降级回退** — CardKit 创建失败时自动回退到 `im.message.create` + `im.message.patch`
- 🔒 **并发安全** — `scoped_lock` 保护的 finalize/abort 操作

## 📦 安装

```bash
pip install feishu-cardkit
```

依赖：`lark-oapi>=1.4.0`

## 🚀 快速开始

### 在 Hermes 中使用（替代内置模块）

只需改一行 import：

```python
# 旧（Hermes 内置模块）
from gateway.platforms.feishu_cardkit import StreamingCardController

# 新（使用本库）
from feishu_cardkit import StreamingCardController
```

其余代码（finalize/abort/build_complete_card/fallback/工具映射等）无需任何改动。

### 独立使用

```python
import asyncio
import lark_oapi as lark
from feishu_cardkit import StreamingCardController

async def main():
    client = lark.Client.builder() \
        .app_id("cli_xxx") \
        .app_secret("xxx") \
        .build()

    # 创建流式卡片
    controller = StreamingCardController(
        cfg={},
        chat_id="oc_xxx",
        client=client,
        show_tool_use=True,
    )

    # 创建并发送卡片
    await controller.ensure_card_created()

    # 流式更新内容（打字机效果）
    await controller.update_content("你好，", is_partial=True)
    await controller.update_content("你好，世界！", is_partial=True)

    # 完成卡片（自动渲染工具面板 + footer + 最终内容）
    await controller.finalize(text="你好，世界！")

asyncio.run(main())
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
│   ├── __init__.py              # 公共 API 导出
│   └── hermes_controller.py     # 核心模块（流式卡片控制器，完整状态机）
├── docs/                        # 飞书卡片中文文档（Card JSON 2.0 / 组件 / 流式 / 回调）
├── examples/                    # 示例代码
└── tests/                       # 单元测试
```

> 核心代码集中在单个模块 `hermes_controller.py`（~2500行），包含完整流式卡片生命周期：
> API 调用、Markdown 优化、表格渲染、工具映射、节流控制、消息检测、降级回退。

## 🔧 依赖自动适配

`hermes_controller.py` 中的并发锁采用 `try/except` 自动降级：

```python
# Hermes 环境下自动启用 gateway.status 并发锁
try:
    from gateway.status import acquire_scoped_lock, release_scoped_lock
except ImportError:
    # 独立使用时降级为 no-op（无锁模式）
    ...
```

## 📖 飞书卡片文档

完整飞书卡片文档见 [`docs/`](./docs/) 目录：

| 文档 | 说明 |
|------|------|
| [00-overview.md](./docs/00-overview.md) | 飞书卡片总览 |
| [02-json-structure.md](./docs/02-json-structure.md) | Card JSON 2.0 结构详解 |
| [06-cardkit-components.md](./docs/06-cardkit-components.md) | 组件文档 |
| [07-streaming-updates.md](./docs/07-streaming-updates.md) | 流式更新 |
| [11-card-callback.md](./docs/11-card-callback.md) | 卡片回调通信 |

## 🧪 开发

```bash
git clone https://github.com/ResterKuma/hermes-feishu-cardkit.git
cd hermes-feishu-cardkit
pip install -e ".[dev]"
pytest
```

## 📄 License

MIT License © 2026 ResterKuma (YuZiXuan)
