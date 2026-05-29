<!-- DREAMFIELD_README_HEADER_START -->
<p align="center">
<a href="https://www.dreamfield.top">
<img src="https://www.dreamfield.top/dream-field/contest-readme/assets/dreamseed-readme-banner.png" alt="DreamSeed 种梦计划参赛作品" width="100%" />
</a>
</p>
<!-- DREAMFIELD_README_HEADER_END -->

<br>

<h1 align="center">🃏 feishu-cardkit v2</h1>

<p align="center">
  <strong>🚀 Hermes Agent × 飞书 CardKit · 流式卡片终解方案</strong>
  <br>
  <em>让飞书机器人的 AI 回复拥有 Telegram 级别的实时打字机体验</em>
</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python" alt="Python 3.10+"></a>
  <a href="#"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="MIT License"></a>
  <a href="#"><img src="https://img.shields.io/badge/Hermes-Ready-ff69b4?style=flat-square" alt="Hermes Ready"></a>
  <a href="#"><img src="https://img.shields.io/badge/Feishu-CardKit%20v2.0-success?style=flat-square" alt="Feishu CardKit"></a>
</p>

<p align="center">
  <i>English version below · <a href="#english">↓ Jump to English</a></i>
</p>

<br>

---

<h2 align="center">✨ 中 文 版 ✨</h2>

<br>

## 💫 一句话介绍

**feishu-cardkit** 是 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 飞书平台的专属插件，基于飞书 CardKit API 构建，为飞书机器人带来 **原生级流式交互体验**。

> 不在官方 Hermes 中没有的，我们补上了。🃏

> ⚠️ **定位说明**：本项目为 Hermes Agent 专用插件，不做通用适配。

<br>

## 🎯 解决的问题

**官方飞书消息 API** 只支持「一次性发送」，AI 回复只能干等：

- ❌ 用户等 10 秒才看到回复，体验极差
- ❌ 无法展示 AI 思考过程
- ❌ 看不到工具调用进度，以为卡死了
- ❌ 表格在手机上完全不能看

**feishu-cardkit 利用 CardKit API，实现了接近 Telegram 级别的流式体验** ✅

<br>

## ✨ 核心特性

> 🔥 **流式卡片** — 基于飞书 CardKit API 增量更新，边想边输出，用户零等待
> 
> 🛠️ **工具调用面板** — 30+ 工具 emoji + 中文映射，按 Agent 回复轮次分组，实时展示
> 
> 💭 **思考折叠** — 自动过滤 `<think_phase>` 等标签，折叠展示思考过程
> 
> 📊 **表格渲染引擎** — Markdown 表格自动转 CardKit column_set 布局，移动端完美适配
> 
> 🛡️ **完整状态机** — `idle → creating → streaming → completed/aborted/terminated`，并发安全
> 
> ⚡ **智能节流** — 0.5s 间隔批量卡片更新，工具事件触发即时刷新，原子提交 finalize
> 
> 🪂 **优雅降级** — CardKit 不可用时自动回退普通消息，永不崩溃
> 
> 🔒 **并发安全** — scoped_lock 保护 finalize/abort 操作，支持多线程安全

<br>

## 🚀 一分钟安装

```bash
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash
```

配置 `~/.hermes/config.yaml`：

```yaml
platforms:
  feishu:
    cardkit_streaming_enabled: true    # 🔥 开启流式卡片
    cardkit_streaming_for_ai: true     # AI 对话流式输出
    cardkit_streaming_for_tasks: true  # 任务进度流式通知
```

重启 Gateway：

```bash
hermes gateway restart
```

卸载：

```bash
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash -s -- --uninstall
```

<br>

## 📦 安装了什么？

| 文件 | 目标位置 | 行数 | 说明 |
| :--- | :--- | :--- | :--- |
| `feishu_cardkit.py` | `gateway/platforms/` | 2,542 | 🔥 流式卡片核心控制器（状态机 + 渲染 + API） |
| `cardkit_stream_consumer.py` | `gateway/` | 847 | 🔗 流式 consumer（连接受理器与卡片） |

<br>

## 📋 完整功能清单

- ✅ **流式内容更新** — 边生成边推送，用户零延迟感
- ✅ **工具调用面板** — emoji + 中文标题 + 实时摘要，按 Turn 分组
- ✅ **Reasoning 过滤** — 自动剥离思考标签，折叠展示
- ✅ **Markdown → 表格** — column_set 布局，移动端完美适配
- ✅ **超限保护** — 元素超 200 个自动降级纯文本
- ✅ **多轮回复检测** — 文本回缩自动识别新一轮
- ✅ **消息不可用缓存** — 30 分钟 TTL，跳过已撤回消息
- ✅ **优雅降级** — CardKit 失败自动回退普通消息
- ✅ **并发安全** — scoped_lock 保护 finalize/abort
- ✅ **进度通知卡片** — `send_progress_card()` 智能进度条
- ✅ **对话引用回复** — 原生 `reply_to_message_id` 支持
- ✅ **中断内容续传** — 上次中断的进度自动拼接前缀
- ✅ **Footer 信息条** — Model 名 / Token 用量 / 上下文率 / 迭代数 / 余额

<br>

## 🏗️ 项目结构

```
feishu-cardkit/
├── src/feishu_cardkit/
│   ├── __init__.py                 # 📦 公共 API 导出 (v2.0.0)
│   ├── feishu_cardkit.py           # 🃏 卡片核心控制器 (2,542 行)
│   └── cardkit_stream_consumer.py  # 🔗 流式 consumer (847 行)
├── install.sh                      # 🚀 一键安装脚本
├── docs/                           # 📖 飞书卡片文档
├── examples/                       # 🧪 示例代码
├── tests/                          # ✅ 单元测试
├── README.md                       # 📝 使用说明
└── pyproject.toml                  # 🐍 项目配置
```

<br>

## 🧪 本地开发

```bash
git clone https://github.com/ResterKuma/hermes-feishu-cardkit.git
cd hermes-feishu-cardkit
pip install -e ".[dev]"
pytest
```

<br>

## 🔧 手动配置联动代码

如果安装脚本提示联动代码缺失，请手动添加：

<details>
<summary><b>📄 gateway/run.py</b></summary>

在 `_run_agent` 方法的 CardKit 判断逻辑前添加：

```python
from gateway.cardkit_stream_consumer import CardKitStreamConsumer, CardKitStreamConsumerConfig
```

</details>

<details>
<summary><b>📄 gateway/platforms/feishu.py</b></summary>

文件头部添加 lazy import：

```python
try:
    from gateway.platforms.feishu_cardkit import (
        StreamingCardController,
        create_streaming_card,
        send_progress_card,
        STREAMING_ELEMENT_ID,
    )
    CARDKIT_AVAILABLE = True
except ImportError:
    CARDKIT_AVAILABLE = False
```

配置类 `FeishuAdapterSettings` 中添加：

```python
cardkit_streaming_enabled: bool = False   # 开启流式卡片功能
cardkit_streaming_for_ai: bool = True     # AI 对话流式输出
cardkit_streaming_for_tasks: bool = True  # 任务进度流式通知
```

</details>

<br>

---

<a name="english"></a>

<h2 align="center">🇬🇧 ENGLISH VERSION</h2>

<br>

<p align="center">
  <i>Chinese version above 👆</i>
</p>

<br>

<h1 align="center">🃏 feishu-cardkit v2</h1>

<p align="center">
  <strong>🚀 Hermes Agent × Feishu CardKit — The Ultimate Streaming Card Solution</strong>
  <br>
  <em>Bring Telegram-grade real-time typewriter experience to your Feishu AI bot</em>
</p>

<br>

## 💫 Introduction

**feishu-cardkit** is a dedicated plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent) on the Feishu (Lark) platform. It leverages the Feishu CardKit API to bring **native streaming interaction** to your Feishu AI bot.

> What Hermes doesn't ship — we ship. 🃏

> ⚠️ **Note**: This is a Hermes Agent exclusive plugin. No universal SDK.

<br>

## 🎯 Problem Solved

| Before (Official API) | After (feishu-cardkit) |
| :--- | :--- |
| ❌ Users wait 10+ seconds for a reply | ✅ Typewriter effect — outputs while thinking |
| ❌ Cannot show AI thinking process | ✅ Reasoning fold — collapsible thinking panel |
| ❌ No tool call progress visibility | ✅ Tool panel — real-time tool call tracking |
| ❌ Tables unreadable on mobile | ✅ Table engine — auto column_set layout |

<br>

## ✨ Core Features

> 🔥 **Streaming Cards** — Incremental updates via CardKit API, zero-latency delivery
> 
> 🛠️ **Tool Use Panel** — 30+ tool emoji + labels, grouped by turns, real-time summaries
> 
> 💭 **Reasoning Fold** — Auto-filters think tags, collapsible thinking panel
> 
> 📊 **Table Rendering Engine** — Markdown → CardKit column_set layout, mobile-friendly
> 
> 🛡️ **State Machine** — `idle → creating → streaming → completed/aborted/terminated`, concurrency-safe
> 
> ⚡ **Smart Throttle** — 0.5s batch updates, flush on tool events, atomic finalize
> 
> 🪂 **Graceful Fallback** — Auto-fallback to plain messages when CardKit unavailable
> 
> 🔒 **Concurrency Safe** — scoped_lock protected finalize/abort operations

<br>

## 🚀 One-Minute Install

```bash
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash
```

Configure `~/.hermes/config.yaml`:

```yaml
platforms:
  feishu:
    cardkit_streaming_enabled: true    # 🔥 Enable streaming cards
    cardkit_streaming_for_ai: true     # AI dialogue streaming output
    cardkit_streaming_for_tasks: true  # Task progress streaming notifications
```

Restart Gateway:

```bash
hermes gateway restart
```

Uninstall:

```bash
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash -s -- --uninstall
```

<br>

## 📦 Installed Files

| File | Destination | Lines | Purpose |
| :--- | :--- | :--- | :--- |
| `feishu_cardkit.py` | `gateway/platforms/` | 2,542 | 🔥 Core controller (state machine + rendering + API) |
| `cardkit_stream_consumer.py` | `gateway/` | 847 | 🔗 Stream consumer (bridges runner and card controller) |

<br>

## 📋 Feature Checklist

- ✅ **Streaming content updates** — zero-latency delivery
- ✅ **Tool use panel** — emoji + labels + live summaries, grouped by turns
- ✅ **Reasoning filtering** — auto strip think tags, collapsible display
- ✅ **Markdown → table rendering** — column_set layout, mobile-friendly
- ✅ **Element limit protection** — graceful degradation beyond 200 elements
- ✅ **Multi-turn detection** — text length rollback triggers new turn
- ✅ **Message unavailability cache** — 30-min TTL, skip recalled messages
- ✅ **Fallback to static cards** — auto when CardKit fails
- ✅ **Concurrency safety** — scoped_lock for finalize/abort
- ✅ **Progress notification cards** — `send_progress_card()` with smart progress bar
- ✅ **Reply-to support** — native `reply_to_message_id`
- ✅ **Interrupt continuation** — auto-prefix interrupted progress
- ✅ **Footer info bar** — model name / token usage / context rate / iterations / balance

<br>

## 🏗️ Project Structure

```
feishu-cardkit/
├── src/feishu_cardkit/
│   ├── __init__.py                 # 📦 Public API exports (v2.0.0)
│   ├── feishu_cardkit.py           # 🃏 Core card controller (2,542 lines)
│   └── cardkit_stream_consumer.py  # 🔗 Stream consumer (847 lines)
├── install.sh                      # 🚀 One-click installer
├── docs/                           # 📖 Feishu card documentation
├── examples/                       # 🧪 Example code
├── tests/                          # ✅ Unit tests
├── README.md                       # 📝 Documentation
└── pyproject.toml                  # 🐍 Project config
```

<br>

## 🧪 Development

```bash
git clone https://github.com/ResterKuma/hermes-feishu-cardkit.git
cd hermes-feishu-cardkit
pip install -e ".[dev]"
pytest
```

<br>

## 📄 License

MIT License © 2026 ResterKuma
