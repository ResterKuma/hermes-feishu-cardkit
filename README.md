<!-- DREAMFIELD_README_HEADER_START -->
<p align="center">
<a href="https://www.dreamfield.top">
<img src="https://www.dreamfield.top/dream-field/contest-readme/assets/dreamseed-readme-banner.png" alt="DreamSeed 种梦计划参赛作品" width="100%" />
</a>
</p>
<!-- DREAMFIELD_README_HEADER_END -->

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

<div align="center">
  <table>
    <tr>
      <td align="center">🔥 打字机实时流式输出</td>
      <td align="center">🛠️ 工具调用面板实时追踪</td>
      <td align="center">💭 思考过程优雅折叠</td>
    </tr>
    <tr>
      <td align="center">📊 Markdown 表格移动端优化</td>
      <td align="center">🛡️ 并发安全状态机</td>
      <td align="center">⚡ 智能节流批量刷新</td>
    </tr>
  </table>
</div>

<br>

---

## 💫 简介

**feishu-cardkit** 是 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 飞书平台的专属插件，基于飞书 CardKit API 构建，为飞书机器人带来**原生级流式交互体验**。

不在官方 Hermes 中没有的，我们补上了。🃏

> ⚠️ **定位说明**：本项目为 Hermes Agent 专用插件，不做通用适配，不开源独立 SDK。

<br>

## 🎯 为什么要用这个？

飞书官方消息 API 只支持「发送 → 编辑」两次更新，AI 回复只能一次性吐出：
- ❌ 用户等 10 秒才看到回复，体验极其糟糕
- ❌ 无法展示 AI 思考过程
- ❌ 看不到工具调用进度，用户以为卡死了
- ❌ 表格在手机上完全不能看

**feishu-cardkit 利用飞书 CardKit API，实现了接近 Telegram 级别的流式体验：**

- ✅ **打字机效果** — 边想边输出，用户零等待
- ✅ **工具面板** — 每次工具调用实时展现在卡片上
- ✅ **思考折叠** — Model 思考过程优雅折起，不干扰正文
- ✅ **表格适配** — 自动转 column_set 布局，移动端完美显示
- ✅ **超限保护** — 卡片元素超 200 个自动兜底，绝不崩溃

<br>

## ✨ 核心特性

<table>
<tr>
<td width="50%">

### 🔄 流式卡片
- 基于飞书 CardKit API 增量更新
- 智能节流控制（0.5s 间隔批量刷新）
- 多轮回复自动分 Turn 展示
- 静态降级：CardKit 不可用时自动回退普通消息

</td>
<td width="50%">

### 🛠️ 工具调用面板
- 30+ 工具 emoji + 中文标题映射
- 按 Agent 回复轮次（Turn）分组
- 实时展示工具摘要
- 面板可折叠，不占正文字段

</td>
</tr>
<tr>
<td width="50%">

### 💭 Reasoning 折叠
- 自动过滤 `<think_phase>` / `<reasoning>` 等标签
- 思考过程存入独立字段
- 最终卡片折叠显示，不干扰回复

</td>
<td width="50%">

### 📊 表格渲染引擎
- Markdown 表格 → CardKit column_set 多列布局
- 自动设置行间距 2px，紧凑美观
- 超 3 个表格自动降级为纯文本
- 移动端阅读体验大幅提升

</td>
</tr>
<tr>
<td width="50%">

### 🛡️ 完整状态机
```
idle → creating → streaming → completed
                          ↘ aborted
                          ↘ terminated
```
- 并发锁保护 finalize/abort 操作
- 30 分钟 TTL 消息不可用缓存
- 优雅处理消息撤回/删除场景

</td>
<td width="50%">

### ⚡ 智能节流
- FlushController 模式：按键/节流/排队
- 0.5s 间隔批量卡片更新
- 工具事件触发即时刷新
- 最终内容原子提交 finalize

</td>
</tr>
</table>

<br>

## 🚀 一分钟安装

```bash
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash
```

然后在 `~/.hermes/config.yaml` 开启：

```yaml
platforms:
  feishu:
    cardkit_streaming_enabled: true    # 🔥 开启流式卡片
    cardkit_streaming_for_ai: true     # AI 对话流式输出
    cardkit_streaming_for_tasks: true  # 任务进度流式通知
```

重启生效：

```bash
hermes gateway restart
```

### 📦 安装了什么？

| 文件 | 目标位置 | 行数 | 说明 |
|:------|:----------|:-----|:------|
| `feishu_cardkit.py` | `gateway/platforms/` | 2,542 | 🔥 流式卡片核心控制器（状态机+渲染+API） |
| `cardkit_stream_consumer.py` | `gateway/` | 847 | 🔗 流式 consumer（连接受理器与卡片） |

### 🗑️ 卸载

```bash
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash -s -- --uninstall
```

<br>

## 📋 完整功能清单

- [x] **流式内容更新** — 边生成边推送，用户零延迟感
- [x] **工具调用面板** — emoji + 中文标题 + 实时摘要，按 Turn 分组
- [x] **Reasoning 过滤** — 自动剥离思考标签，折叠展示
- [x] **Markdown → 表格** — column_set 布局，移动端完美适配
- [x] **超限保护** — 元素超过阈值自动兜底
- [x] **多轮回复检测** — 文本回缩自动识别新一轮
- [x] **消息不可用缓存** — 30 分钟 TTL，跳过已撤回消息
- [x] **静态降级** — CardKit 失败自动回退普通消息
- [x] **并发安全** — scoped_lock 保护 finalize/abort
- [x] **进度通知卡片** — send_progress_card() 智能进度条
- [x] **对话��用回复** — 原生 reply_to_message_id 支持
- [x] **中断内容续传** — 上次中断的进度自动拼接前缀
- [x] **Footer 信息条** — Model 名/Token 用量/上下文率/迭代数/余额

<br>

## 🏗️ 项目结构

```
feishu-cardkit/
├── src/feishu_cardkit/
│   ├── __init__.py                    # 📦 公共 API 导出 (v2.0.0)
│   ├── feishu_cardkit.py             # 🃏 卡片核心控制器 (2,542行)
│   └── cardkit_stream_consumer.py    # 🔗 流式 consumer (847行)
├── install.sh                        # 🚀 一键安装脚本
├── docs/                             # 📖 飞书卡片文档
├── examples/                         # 🧪 示例代码
├── tests/                            # ✅ 单元测试
├── README.md                         # 📝 使用说明
└── pyproject.toml                    # 🐍 项目配置
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

## 🔧 手动配置联动代��

如果安装脚本提示 `run.py` 或 `feishu.py` 缺少联动代码，请手动添加：

<details>
<summary><b>📄 gateway/run.py — 添加 import</b></summary>

在 `_run_agent` 方法的 CardKit 判断逻辑前添加：

```python
from gateway.cardkit_stream_consumer import CardKitStreamConsumer, CardKitStreamConsumerConfig
```

</details>

<details>
<summary><b>📄 gateway/platforms/feishu.py — 添加配置项和 import</b></summary>

文件头部：

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

配置类中添加：

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
  <i>Scroll down for the Chinese version above 👆</i>
</p>

<br>

<h1 align="center">🃏 feishu-cardkit v2</h1>

<p align="center">
  <strong>🚀 Hermes Agent × Feishu CardKit — The Ultimate Streaming Card Solution</strong>
  <br>
  <em>Bring Telegram-grade real-time typewriter experience to your Feishu AI bot</em>
</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python" alt="Python 3.10+"></a>
  <a href="#"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="MIT License"></a>
  <a href="#"><img src="https://img.shields.io/badge/Hermes-Ready-ff69b4?style=flat-square" alt="Hermes Ready"></a>
</p>

<br>

## 💫 Introduction

**feishu-cardkit** is a dedicated plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent) on the Feishu (Lark) platform. It leverages the Feishu CardKit API to bring **native streaming interaction** to your Feishu AI bot.

What Hermes doesn't ship — we ship. 🃏

> ⚠️ **Note**: This is a Hermes Agent exclusive plugin. No universal SDK, no standalone packaging.

<br>

## ✨ Features

| Feature | Description |
|:--------|:------------|
| 🔄 **Streaming Cards** | Real-time typewriter effect via CardKit API incremental updates |
| 🛠️ **Tool Use Panel** | Live tracking of tool calls with emoji + Chinese labels, grouped by agent turns |
| 💭 **Reasoning Fold** | Auto-filter think tags, collapsible reasoning panel |
| 📊 **Table Engine** | Markdown → column_set layout, mobile-optimized |
| 🛡️ **State Machine** | `idle → creating → streaming → completed/aborted/terminated`, concurrency-safe |
| ⚡ **Smart Throttle** | 0.5s batch updates, flush on tool events, atomic finalize |
| 🪂 **Graceful Fallback** | Auto-fallback to plain messages when CardKit is unavailable |
| 🔒 **Concurrency Safe** | scoped_lock protected finalize/abort operations |

<br>

## 🚀 One-Minute Install

```bash
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash
```

Enable in `~/.hermes/config.yaml`:

```yaml
platforms:
  feishu:
    cardkit_streaming_enabled: true
    cardkit_streaming_for_ai: true
    cardkit_streaming_for_tasks: true
```

Restart:

```bash
hermes gateway restart
```

### What's Installed?

| File | Destination | Lines | Purpose |
|:-----|:------------|:------|:--------|
| `feishu_cardkit.py` | `gateway/platforms/` | 2,542 | 🔥 Streaming card core controller (state machine + rendering + API) |
| `cardkit_stream_consumer.py` | `gateway/` | 847 | 🔗 Stream consumer (bridges runner and card controller) |

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash -s -- --uninstall
```

<br>

## 📋 Feature Checklist

- [x] Streaming content updates — zero-latency delivery
- [x] Tool use panel — emoji + labels + live summaries, grouped by turns
- [x] Reasoning filtering — auto strip think tags, collapsible display
- [x] Markdown → table rendering — column_set layout, mobile-friendly
- [x] Element limit protection — graceful degradation beyond threshold
- [x] Multi-turn detection — text length rollback triggers new turn
- [x] Message unavailability cache — 30-min TTL, skip recalled messages
- [x] Fallback to static cards — auto when CardKit fails
- [x] Concurrency safety — scoped_lock for finalize/abort
- [x] Progress notification cards — send_progress_card()
- [x] Reply-to support — native reply_to_message_id
- [x] Interrupt continuation — auto-prefix interrupted progress
- [x] Footer info bar — model name / token usage / context rate / iterations / balance

<br>

## 🏗️ Project Structure

```
feishu-cardkit/
├── src/feishu_cardkit/
│   ├── __init__.py                    # 📦 Public API exports (v2.0.0)
│   ├── feishu_cardkit.py             # 🃏 Core card controller (2,542 lines)
│   └─�� cardkit_stream_consumer.py    # 🔗 Stream consumer (847 lines)
├── install.sh                        # 🚀 One-click installer
├── docs/                             # 📖 Feishu card documentation
├── examples/                         # 🧪 Example code
├── tests/                            # ✅ Unit tests
├── README.md                         # 📝 This file
└── pyproject.toml                    # 🐍 Project config
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
