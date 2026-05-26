"""
StreamingCardController — 流式卡片状态机。

管理 CardKit 卡片的全生命周期：
  idle → creating → streaming → completed / aborted / terminated

支持：
- AI 回复流式渲染（打字机效果）
- 任务进度通知
- 工具调用状态展示
- Reasoning/思考过程展示
- 节流 & 批量刷新
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .api import CardKitAPI
from .builder import CardBuilder
from .markdown import optimize_markdown, sanitize_text_for_card, split_text_and_tables

logger = logging.getLogger("feishu_cardkit.controller")

# ── 节流常量（毫秒）──
THROTTLE_STREAM_MS = 300
THROTTLE_PATCH_MS = 1000


# ===================================================================
# 枚举 & 数据类
# ===================================================================

class CardPhase(str, Enum):
    """卡片生命周期阶段。"""
    IDLE = "idle"
    CREATING = "creating"
    STREAMING = "streaming"
    COMPLETED = "completed"
    ABORTED = "aborted"
    TERMINATED = "terminated"
    CREATION_FAILED = "creation_failed"


# 合法状态转换
_VALID_TRANSITIONS: Dict[CardPhase, set] = {
    CardPhase.IDLE: {CardPhase.CREATING},
    CardPhase.CREATING: {CardPhase.STREAMING, CardPhase.CREATION_FAILED},
    CardPhase.STREAMING: {CardPhase.COMPLETED, CardPhase.ABORTED},
    CardPhase.COMPLETED: set(),
    CardPhase.ABORTED: {CardPhase.TERMINATED},
    CardPhase.TERMINATED: set(),
    CardPhase.CREATION_FAILED: set(),
}

TERMINAL_PHASES = {CardPhase.COMPLETED, CardPhase.ABORTED, CardPhase.TERMINATED, CardPhase.CREATION_FAILED}


@dataclass
class TurnStep:
    """单个工具调用步骤。"""
    name: str = ""
    title: str = ""        # 预览/摘要文本
    summary: str = ""       # 详细说明
    status: str = "pending" # pending / running / completed / failed


@dataclass
class Turn:
    """一轮对话（可含多个工具步骤）。"""
    steps: List[TurnStep] = field(default_factory=list)
    current_step_idx: int = -1


@dataclass
class TextState:
    """文本累积状态。"""
    accumulated_text: str = ""
    completed_text: str = ""
    streaming_prefix: str = ""
    last_partial_text: str = ""
    last_flushed_text: str = ""


@dataclass
class ReasoningState:
    """思考过程状态。"""
    accumulated_text: str = ""
    start_time: Optional[float] = None
    elapsed_ms: int = 0
    is_active: bool = False


# ===================================================================
# StreamingCardController
# ===================================================================

@dataclass
class StreamingCardController:
    """管理 CardKit 流式卡片的全生命周期。

    状态机：idle → creating → streaming → completed/aborted/terminated

    用法::

        ctrl = StreamingCardController(client=client, chat_id="oc_xxx")
        await ctrl.ensure_card_created()
        await ctrl.update_content("你好", is_partial=True)
        await ctrl.finalize(text="你好世界！")

    Args:
        client: ``lark_oapi.Client`` 实例。
        chat_id: 目标聊天 ID。
        reply_to: 回复的消息 ID（可选）。
        header_title: 卡片头部标题。
        header_template: 头部颜色模板。
    """

    # ── 必填参数 ──
    client: Any = None
    chat_id: str = ""

    # ── 可选参数 ──
    reply_to: Optional[str] = None
    header_title: str = ""
    header_template: str = "default"

    # ── 内部状态（不要手动修改）──
    phase: CardPhase = CardPhase.IDLE
    card_id: Optional[str] = None
    message_id: Optional[str] = None
    sequence: int = 0

    _text: TextState = field(default_factory=TextState)
    _reasoning: ReasoningState = field(default_factory=ReasoningState)
    _turn: Turn = field(default_factory=Turn)
    _api: Optional[CardKitAPI] = None

    # 节流
    _last_stream_ms: float = 0.0
    _last_patch_ms: float = 0.0
    _pending_flush: Optional[asyncio.TimerHandle] = None
    _flush_scheduled: bool = False

    # 回调
    on_phase_change: Optional[Callable[[CardPhase, CardPhase], None]] = None

    def __post_init__(self):
        if self.client is not None:
            self._api = CardKitAPI(self.client)

    # ===================================================================
    # 状态机
    # ===================================================================

    def _transition(self, new_phase: CardPhase) -> bool:
        """尝试状态转换。"""
        allowed = _VALID_TRANSITIONS.get(self.phase, set())
        if new_phase not in allowed:
            logger.warning("非法状态转换: %s → %s", self.phase.value, new_phase.value)
            return False
        old = self.phase
        self.phase = new_phase
        if self.on_phase_change:
            self.on_phase_change(old, new_phase)
        logger.debug("状态转换: %s → %s", old.value, new_phase.value)
        return True

    @property
    def is_terminal(self) -> bool:
        """是否处于终态。"""
        return self.phase in TERMINAL_PHASES

    # ===================================================================
    # 创建卡片
    # ===================================================================

    async def ensure_card_created(self) -> bool:
        """确保卡片已创建并发送到聊天。

        Returns:
            成功返回 True。
        """
        if self.card_id and self.phase != CardPhase.IDLE:
            return True

        if not self._api:
            logger.error("未设置 client，无法创建卡片")
            return False

        self._transition(CardPhase.CREATING)

        # 构建初始卡片
        card = self._build_initial_card()
        card_id = await self._api.create_card(card)

        if not card_id:
            self._transition(CardPhase.CREATION_FAILED)
            logger.error("卡片创建失败")
            return False

        self.card_id = card_id

        # 发送到聊天
        result = await self._api.send_card_message(
            card_id,
            self.chat_id,
            reply_to=self.reply_to,
        )

        if result:
            self.message_id = result.get("message_id")
            # 开启流式模式
            self._next_seq()
            await self._api.set_streaming_mode(card_id, True, self.sequence)

        self._transition(CardPhase.STREAMING)
        return True

    def _build_initial_card(self) -> Dict[str, Any]:
        """构建初始卡片 JSON。"""
        builder = CardBuilder()

        if self.header_title:
            builder.header(self.header_title, template=self.header_template)
        else:
            builder.header("💭 思考中…", template="default")

        # 思考占位
        builder.markdown(
            "\u200b",
            text_size="normal_v2",
            element_id="streaming_text",
        )

        builder.streaming_config()
        return builder.build()

    # ===================================================================
    # 内容更新
    # ===================================================================

    async def update_content(
        self,
        text: str,
        *,
        is_partial: bool = True,
        force_flush: bool = False,
    ) -> None:
        """更新流式文本内容。

        Args:
            text: 当前文本（partial=True 时为累积文本，否则为增量）。
            is_partial: text 是否为累积文本（True）或增量（False）。
            force_flush: 强制立即刷新到 API。
        """
        if self.is_terminal or not self.card_id:
            return

        # 累积文本
        if is_partial:
            self._text.accumulated_text = text
        else:
            self._text.accumulated_text += text

        # 检查是否有新内容需要刷新
        if self._text.accumulated_text == self._text.last_flushed_text and not force_flush:
            return

        # 节流检查
        now = time.monotonic() * 1000
        if not force_flush and (now - self._last_stream_ms) < THROTTLE_STREAM_MS:
            # 延迟刷新
            if not self._flush_scheduled:
                self._schedule_flush()
            return

        await self._flush_stream()

    async def _flush_stream(self) -> None:
        """将累积文本刷写到 API。"""
        if not self.card_id or self.is_terminal:
            return

        text = self._text.accumulated_text
        self._next_seq()

        # 优化 markdown
        optimized = optimize_markdown(text) if text else ""

        ok = await self._api.stream_content(
            self.card_id, "streaming_text", optimized, self.sequence
        )

        if ok:
            self._text.last_flushed_text = text
            self._last_stream_ms = time.monotonic() * 1000
            self._flush_scheduled = False

    def _schedule_flush(self) -> None:
        """调度延迟刷新。"""
        self._flush_scheduled = True
        try:
            loop = asyncio.get_running_loop()
            self._pending_flush = loop.call_later(
                THROTTLE_STREAM_MS / 1000,
                lambda: asyncio.ensure_future(self._flush_stream()),
            )
        except RuntimeError:
            self._flush_scheduled = False

    # ===================================================================
    # Reasoning（思考过程）
    # ===================================================================

    async def update_reasoning(self, text: str, *, is_partial: bool = True) -> None:
        """更新思考过程文本。

        Args:
            text: 思考内容。
            is_partial: 是否为累积文本。
        """
        if self.is_terminal:
            return

        if is_partial:
            self._reasoning.accumulated_text = text
        else:
            self._reasoning.accumulated_text += text

        if not self._reasoning.start_time:
            self._reasoning.start_time = time.monotonic()
            self._reasoning.is_active = True

    # ===================================================================
    # 工具调用步骤
    # ===================================================================

    async def add_tool_step(
        self,
        name: str,
        *,
        title: str = "",
        summary: str = "",
        status: str = "running",
    ) -> None:
        """添加一个工具调用步骤。

        Args:
            name: 工具名称。
            title: 预览/摘要文本。
            summary: 详细说明。
            status: 步骤状态。
        """
        if self.is_terminal:
            return

        step = TurnStep(name=name, title=title, summary=summary, status=status)
        self._turn.steps.append(step)
        self._turn.current_step_idx = len(self._turn.steps) - 1

        await self._flush_tool_panel()

    async def update_tool_step(self, index: int, *, status: str = "", summary: str = "") -> None:
        """更新指定步骤的状态。

        Args:
            index: 步骤索引。
            status: 新状态。
            summary: 新摘要。
        """
        if self.is_terminal or index >= len(self._turn.steps):
            return

        step = self._turn.steps[index]
        if status:
            step.status = status
        if summary:
            step.summary = summary

        await self._flush_tool_panel()

    async def _flush_tool_panel(self) -> None:
        """刷新工具面板到卡片。"""
        if not self.card_id or self.is_terminal:
            return

        now = time.monotonic() * 1000
        if (now - self._last_patch_ms) < THROTTLE_PATCH_MS:
            return

        # 构建工具面板内容
        panel_content = self._build_tool_panel_content()
        if not panel_content:
            return

        self._next_seq()
        ok = await self._api.patch_element(
            self.card_id, "tool_use_panel", panel_content, self.sequence
        )
        if ok:
            self._last_patch_ms = time.monotonic() * 1000

    def _build_tool_panel_content(self) -> Optional[Dict[str, Any]]:
        """构建工具面板的 partial_element。"""
        steps = self._turn.steps
        if not steps:
            return None

        # 统计完成数
        completed = sum(1 for s in steps if s.status in ("completed", "failed"))
        total = len(steps)
        panel_title = f"🛠️ {total} 步"

        lines = []
        for i, step in enumerate(steps):
            icon = _status_icon(step.status)
            line = f"{icon} **{step.name}**"
            if step.title:
                line = f"{icon} {step.title}"
            if step.summary:
                line += f"\n  <font color='grey'>{step.summary}</font>"
            lines.append(line)

        content = "\n".join(lines)

        return {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": panel_title,
                    "text_color": "grey",
                    "text_size": "notation",
                },
            },
            "elements": [
                {"tag": "markdown", "content": content, "text_size": "notation"}
            ],
        }


def _status_icon(status: str) -> str:
    """获取步骤状态图标。"""
    return {
        "pending": "⏳",
        "running": "🔄",
        "completed": "✅",
        "failed": "❌",
    }.get(status, "•")


# ===================================================================
# 便捷函数
# ===================================================================

async def create_streaming_card(
    client: Any,
    chat_id: str,
    *,
    header_title: str = "",
    header_template: str = "default",
    reply_to: Optional[str] = None,
) -> StreamingCardController:
    """创建并发送一张流式卡片。

    Args:
        client: ``lark_oapi.Client`` 实例。
        chat_id: 目标聊天 ID。
        header_title: 卡片标题。
        header_template: 标题颜色模板。
        reply_to: 回复的消息 ID。

    Returns:
        已初始化的 :class:`StreamingCardController` 实例。
    """
    ctrl = StreamingCardController(
        client=client,
        chat_id=chat_id,
        header_title=header_title,
        header_template=header_template,
        reply_to=reply_to,
    )
    await ctrl.ensure_card_created()
    return ctrl


async def send_progress_card(
    client: Any,
    chat_id: str,
    *,
    title: str = "处理中",
    progress_text: str = "",
    progress_percent: int = 0,
    status: str = "Running",
    header_template: str = "orange",
) -> Optional[str]:
    """发送一张进度通知卡片。

    Args:
        client: ``lark_oapi.Client`` 实例。
        chat_id: 目标聊天 ID。
        title: 卡片标题。
        progress_text: 进度说明文本。
        progress_percent: 进度百分比（0-100）。
        status: 状态文本。
        header_template: 头部颜色模板。

    Returns:
        成功返回 message_id，失败返回 None。
    """
    api = CardKitAPI(client)

    # 进度条
    filled = int(20 * progress_percent / 100)
    bar = "█" * filled + "░" * (20 - filled)
    bar_text = f"[{bar}] {progress_percent}%"

    builder = (
        CardBuilder()
        .header(title, template=header_template)
        .markdown(f"**{bar_text}**")
    )

    if progress_text:
        builder.markdown(progress_text)

    builder.note(f"状态: {status}")

    card = builder.build()
    card_id = await api.create_card(card)
    if not card_id:
        return None

    result = await api.send_card_message(card_id, chat_id)
    if result:
        return result.get("message_id")
    return None
