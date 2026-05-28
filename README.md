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
- 📊 **表格 column_set 渲染** — Markdown 表格自动转为多列横排布局，完美适配移动端
- 🧠 **智能工具摘要** — 按 key 名精准匹配参数摘要（patch 显示 `old → new`），截断 150 字符
- 💭 **Reasoning 过滤** — `<think_phase>` 标签自动剥离 + 折叠显示
- ⚡ **节流 & 批量刷新** — FlushController 风格的 throttle + deferred flush + reflush
- 🛡️ **消息不可用检测** — 30 分钟 TTL 缓存，跳过已撤回/删除的消息
- 🔀 **多轮回复检测** — 文本长度回缩自动识别为新一轮
- 🪂 **update_card fallback** — `update_card` 失败时自动走 `patch_card_element`
- 🔒 **元素安全保护** — 自动估算卡片元素数，超 200 上限时回退纯 markdown 表格
- 🔐 **并发安全** — `scoped_lock` 保护的 finalize/abort 操作

## 📦 安装

### 方式一：一键安装到 Hermes（推荐）

```bash
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash
```

安装脚本会自动完成：
1. 🔍 查找 Hermes Agent 安装路径
2. 📥 下载最新 `feishu_cardkit.py` 到 `gateway/platforms/`
3. 📦 备份旧版本（`*.bak.%Y%m%d%H%M%S`）
4. 🩹 打集成补丁（`gateway/run.py` + `run_agent.py`）

安装后直接在 Hermes 中使用：
```python
from gateway.platforms.feishu_cardkit import StreamingCardController
```

卸载：
```bash
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash -s -- --uninstall
```

手动指定路径：
```bash
bash install.sh --path /your/hermes-agent
```

### 方式二：pip 安装（独立使用）

```bash
pip install feishu-cardkit
```

依赖：`lark-oapi>=1.4.0`

## 🚀 快速开始

### Hermes 中使用

一键安装后，直接 import 即可：

```python
from gateway.platforms.feishu_cardkit import StreamingCardController

controller = StreamingCardController(
    cfg={}, chat_id="oc_xxx", client=client, show_tool_use=True
)
await controller.ensure_card_created()
await controller.update_content("你好世界！", is_partial=True)
await controller.finalize(text="你好世界！")
```

### 独立使用（pip 安装）

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
│   └── hermes_controller.py     # 核心引擎（流式卡片控制器，完整状态机）
├── patches/                     # Hermes Agent 集成补丁
│   ├── run.py.patch             # gateway/run.py 卡片联动补丁
│   └── run_agent.py.patch       # run_agent.py 引导语修正
├── docs/                        # 飞书卡片中文文档（Card JSON 2.0 / 组件 / 流式 / 回调）
├── examples/                    # 示例代码
├── tests/                       # 单元测试
└── install.sh                   # 一键安装脚本（安装核心 + 打补丁）
```

> 核心代码集中在单个模块 `hermes_controller.py`（~2500行），包含完整流式卡片生命周期：  
> API 调用、Markdown 优化、表格 column_set 渲染、工具摘要映射、节流控制、元素安全、降级回退。  
> 集成补丁见 `patches/` 目录，`install.sh` 自动应用。

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

MIT License © 2026 ResterKuma
