"""
Feishu CardKit streaming card implementation.

Provides streaming card support for Feishu/Lark using the CardKit API,
enabling typewriter-style updates for AI responses and task progress notifications.

Reference: @larksuite/openclaw-lark/src/card/streaming-card-controller.js
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Callable

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
        ReplyMessageRequest,
        ReplyMessageRequestBody,
    )
    from lark_oapi.api.cardkit.v1.model import (
        CreateCardRequest,
        CreateCardRequestBody,
        ContentCardElementRequest,
        ContentCardElementRequestBody,
        PatchCardElementRequest,
        PatchCardElementRequestBody,
        UpdateCardRequest,
        UpdateCardRequestBody,
        SettingsCardRequest,
        SettingsCardRequestBody,
    )
    from lark_oapi.core import AccessTokenType, HttpMethod
    from lark_oapi.core.model import BaseRequest
    LARK_AVAILABLE = True
except ImportError:
    LARK_AVAILABLE = False
    lark = None

# 兼容 Hermes gateway.status 锁，独立使用时自动降级为 no-op
try:
    from gateway.status import acquire_scoped_lock, release_scoped_lock
except ImportError:
    def acquire_scoped_lock(name: str, timeout: float = 5.0):
        class _DummyLock:
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return _DummyLock()
    def release_scoped_lock(name: str): pass

logger = logging.getLogger(__name__)

# Element ID for streaming content in CardKit cards
STREAMING_ELEMENT_ID = "streaming_content"

# Feishu card element limit: tables beyond this trigger 230099/11310
FEISHU_CARD_TABLE_LIMIT = 3

# CardKit API error codes
CARD_ERROR_RATE_LIMITED = 230020
CARD_ERROR_CONTENT_FAILED = 230099
CARD_ERROR_ELEMENT_LIMIT = 11310


# ---------------------------------------------------------------------------
# Module-level helpers used by _optimize_markdown
# ---------------------------------------------------------------------------

def _table_after_spacing(m: re.Match) -> str:
    """re.sub callback: append <br> after table block unless next line is
    a heading, bold text, or end-of-string."""
    table_block = m.group(1)
    end_pos = m.end()
    # Peek at the full text via m.string
    remainder = m.string[end_pos:].lstrip('\n')
    if not remainder:
        return table_block
    # Skip <br> before heading or bold
    if remainder.startswith('####') or remainder.startswith('**'):
        return table_block
    return table_block + '<br>\n'


# ---------------------------------------------------------------------------
# Tool use display — structured step rendering
# ---------------------------------------------------------------------------

# Maps tool names to display metadata: (emoji, title, param_keys_for_summary)
# Reference: openclaw-lark/src/card/tool-use-display.js TOOL_DESCRIPTORS
_TOOL_DISPLAY: Dict[str, Dict[str, Any]] = {
    # File operations
    "read":          {"emoji": "📄", "title": "Read",       "params": ["file_path", "path"]},
    "open":          {"emoji": "📄", "title": "Read",       "params": ["file_path", "path"]},
    "write":         {"emoji": "✏️",  "title": "Write",      "params": ["file_path", "path"]},
    "edit":          {"emoji": "✏️",  "title": "Edit",       "params": ["file_path", "path"]},
    "patch":         {"emoji": "✏️",  "title": "Edit",       "params": ["old_string", "new_string", "path"]},
    "search_files":  {"emoji": "🔍", "title": "Search",     "params": ["pattern", "path"]},
    "search":        {"emoji": "🔍", "title": "Search",     "params": ["pattern", "query"]},
    # Web
    "web_search":    {"emoji": "🌐", "title": "Search web", "params": ["query", "q"]},
    "web_fetch":     {"emoji": "🌐", "title": "Fetch",      "params": ["url"]},
    "web_extract":   {"emoji": "🌐", "title": "Extract",    "params": ["url"]},
    "browser":       {"emoji": "🌐", "title": "Browse",     "params": ["url"]},
    "browser_navigate": {"emoji": "🌐", "title": "Navigate",  "params": ["url"]},
    "browser_click":    {"emoji": "🌐", "title": "Click",     "params": ["ref"]},
    "browser_snapshot": {"emoji": "🌐", "title": "Snapshot",  "params": []},
    "browser_type":     {"emoji": "🌐", "title": "Type",      "params": ["text"]},
    # Terminal
    "shell":         {"emoji": "💻", "title": "Shell",      "params": ["command", "cmd"]},
    "terminal":      {"emoji": "💻", "title": "Terminal",    "params": ["command"]},
    "execute_code":  {"emoji": "💻", "title": "Code",       "params": ["code"]},
    "bash":          {"emoji": "💻", "title": "Bash",       "params": ["command"]},
    # System
    "list":          {"emoji": "📁", "title": "List",       "params": ["path", "directory"]},
    "ls":            {"emoji": "📁", "title": "List",       "params": ["path"]},
    "mkdir":         {"emoji": "📁", "title": "Mkdir",      "params": ["path"]},
    "skill":         {"emoji": "📚", "title": "Load skill", "params": ["skill", "name"]},
    "skill_view":    {"emoji": "📚", "title": "View skill", "params": ["name"]},
    "skills_list":   {"emoji": "📚", "title": "List skills","params": []},
    # Memory & search
    "memory":        {"emoji": "🧠", "title": "Memory",     "params": ["action", "content"]},
    "session_search": {"emoji": "🔎", "title": "Recall",    "params": ["query"]},
    "delegate_task":  {"emoji": "🤝", "title": "Delegate",   "params": ["goal"]},
    "send_message":   {"emoji": "💬", "title": "Send",       "params": ["message", "target"]},
    "todo":           {"emoji": "📋", "title": "Todo",       "params": []},
    "cronjob":        {"emoji": "⏰", "title": "Cron",       "params": ["action"]},
    "clarify":        {"emoji": "❓", "title": "Ask",        "params": ["question"], "hidden": True},
    "vision_analyze": {"emoji": "👁️", "title": "Analyze",   "params": ["image_url"]},
    "browser_vision": {"emoji": "👁️", "title": "Screenshot","params": ["question"]},
    "text_to_speech": {"emoji": "🔊", "title": "TTS",       "params": ["text"]},
    # Default fallback
    "_default":      {"emoji": "🛠️", "title": "Tool",       "params": []},
}


def _normalize_tool_step(step: Any) -> Dict[str, Any]:
    """Convert a raw tool step into a normalized display dict.

    Input step can be:
    - dict with "title" key (current hermes format)
    - dict with "name" + optional "params" (structured format)
    - string (plain text title)

    Returns: {"name": str, "title": str, "summary": str, "emoji": str, "status": str}
    """
    if isinstance(step, str):
        return {"name": "unknown", "title": step, "summary": "", "emoji": "🛠️", "status": "completed"}

    if not isinstance(step, dict):
        return {"name": "unknown", "title": str(step), "summary": "", "emoji": "🛠️", "status": "completed"}

    name = step.get("name", step.get("title", "unknown")).lower()
    title = step.get("title", "")
    status = step.get("status", "completed")  # running, completed, error

    # Look up display info — try exact name, then fuzzy match
    display = _TOOL_DISPLAY.get(name)
    if not display:
        for variant in (name.rstrip("0123456789"), name.split("_")[0]):
            if variant in _TOOL_DISPLAY:
                display = _TOOL_DISPLAY[variant]
                break
    if not display:
        display = _TOOL_DISPLAY["_default"]

    # Extract summary — priority: explicit summary > params > title (preview) > regex > common keys
    summary = step.get("summary", "")
    params = step.get("params", step.get("arguments", step.get("input", {})))
    if isinstance(params, dict):
        for pk in display.get("params", []):
            val = params.get(pk)
            if val:
                s = str(val)
                summary = s[:150] + ("..." if len(s) > 150 else "")
                break

    # Fallback: use step["title"] as summary when it differs from the display title
    # This is the common case: on_tool_use(tool_name, preview) stores preview in "title"
    if not summary and title and title != display["title"]:
        summary = title

    # Another fallback: try to extract from title via regex
    if not summary and title:
        for pat in [
            r'(?:read|open|write|edit|patch)\s+(?:file\s+)?[`"]?([^`"\n]+)',
            r'(?:search|grep|find)\s+(?:for\s+)?[`"]?([^`"\n]+)',
            r'(?:run|execute|exec)\s+[`"]?([^`"\n]+)',
        ]:
            m = re.search(pat, title, re.IGNORECASE)
            if m:
                summary = m.group(1).strip()[:150]
                break

    # If we still have no summary but have params with common keys
    if not summary and isinstance(params, dict):
        for k in ("query", "command", "path", "file_path", "url", "pattern", "code"):
            val = params.get(k)
            if val:
                s = str(val)
                summary = s[:150] + ("..." if len(s) > 150 else "")
                break

    return {
        "name": name,
        "title": display["title"],
        "summary": summary,
        "emoji": display["emoji"],
        "status": status,
        "hidden": display.get("hidden", False),
    }


def _format_tool_summary_line(step: Dict[str, Any], index: int) -> str:
    """Format a single tool step as a markdown line for card display."""
    normalized = _normalize_tool_step(step)
    emoji = normalized["emoji"]
    title = normalized["title"]
    summary = normalized["summary"]
    status = normalized["status"]

    # Status indicator
    if status == "running":
        status_icon = " ⏳"
    elif status == "error":
        status_icon = " ❌"
    else:
        status_icon = " ✓"

    if summary:
        line = f"{emoji} **{title}** `{_truncate(summary, 150)}`{status_icon}"
    else:
        line = f"{emoji} **{title}**{status_icon}"

    # Truncate to max 2 lines: keep first and last line, cut the middle
    return _truncate_to_two_lines(line)


def _truncate_to_two_lines(text: str) -> str:
    """Truncate text to at most 2 lines by cutting the middle part."""
    lines = text.split('\n')
    if len(lines) <= 2:
        return text
    return lines[0] + '\n...\n' + lines[-1]


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


# ---------------------------------------------------------------------------
# Unavailable message guard
# ---------------------------------------------------------------------------

# Feishu API codes indicating the message no longer exists (deleted/recalled).
# All further API calls for this message_id should be skipped.
_MESSAGE_TERMINAL_CODES = frozenset({230011, 231003})

# Module-level cache: message_id -> (api_code, timestamp)
# TTL = 30 minutes, auto-pruned when exceeding 512 entries.
_UNAVAILABLE_CACHE: Dict[str, tuple] = {}
_UNAVAILABLE_TTL = 30 * 60  # seconds
_UNAVAILABLE_MAX = 512


def mark_message_unavailable(message_id: str, api_code: int, operation: str = "") -> None:
    """Mark a message_id as unavailable (deleted/recalled)."""
    if not message_id:
        return
    if len(_UNAVAILABLE_CACHE) >= _UNAVAILABLE_MAX:
        _prune_unavailable_cache()
    _UNAVAILABLE_CACHE[message_id] = (api_code, time.time(), operation)
    logger.warning("[CardKit] Message %s marked unavailable (code=%d, op=%s)", message_id, api_code, operation)


def is_message_unavailable(message_id: str) -> bool:
    """Check if a message_id is known to be unavailable."""
    if not message_id:
        return False
    entry = _UNAVAILABLE_CACHE.get(message_id)
    if not entry:
        return False
    if time.time() - entry[1] > _UNAVAILABLE_TTL:
        del _UNAVAILABLE_CACHE[message_id]
        return False
    return True


def check_api_error_unavailable(message_id: str, error: Any, operation: str = "") -> bool:
    """Check if an API error indicates the message is unavailable.

    Returns True if the error is a terminal message error (230011/231003)
    and marks the message as unavailable.
    """
    code = _extract_lark_api_code(error)
    if code and code in _MESSAGE_TERMINAL_CODES:
        mark_message_unavailable(message_id, code, operation)
        return True
    return False


def _extract_lark_api_code(error: Any) -> Optional[int]:
    """Try to extract a Lark API error code from various error shapes."""
    if isinstance(error, dict):
        code = error.get("code") or error.get("Code")
        if isinstance(code, int):
            return code
        try:
            return int(code)
        except (TypeError, ValueError):
            pass
    if hasattr(error, "code"):
        try:
            return int(error.code)
        except (TypeError, ValueError):
            pass
    # lark_oapi SDK wraps errors in response.data
    if hasattr(error, "data") and hasattr(error.data, "code"):
        try:
            return int(error.data.code)
        except (TypeError, ValueError):
            pass
    return None


def _prune_unavailable_cache() -> None:
    """Remove expired entries from the unavailable message cache."""
    now = time.time()
    expired = [k for k, v in _UNAVAILABLE_CACHE.items() if now - v[1] > _UNAVAILABLE_TTL]
    for k in expired:
        del _UNAVAILABLE_CACHE[k]


class CardPhase(str, Enum):
    """Streaming card lifecycle phases."""
    IDLE = "idle"
    CREATING = "creating"
    STREAMING = "streaming"
    COMPLETED = "completed"
    ABORTED = "aborted"
    TERMINATED = "terminated"
    CREATION_FAILED = "creation_failed"


# Valid phase transitions
PHASE_TRANSITIONS: Dict[CardPhase, set] = {
    CardPhase.IDLE: {CardPhase.CREATING},
    CardPhase.CREATING: {CardPhase.STREAMING, CardPhase.CREATION_FAILED},
    CardPhase.STREAMING: {CardPhase.COMPLETED, CardPhase.ABORTED, CardPhase.TERMINATED},
    CardPhase.COMPLETED: set(),
    CardPhase.ABORTED: set(),
    CardPhase.TERMINATED: set(),
    CardPhase.CREATION_FAILED: set(),
}

TERMINAL_PHASES = {CardPhase.COMPLETED, CardPhase.ABORTED, CardPhase.TERMINATED, CardPhase.CREATION_FAILED}

# Throttle constants (ms) — aligned with openclaw-lark flush-controller.js
THROTTLE_CARDKIT_MS = 200        # CardKit cardElement.content() — print frequency delegated to client via streaming_config
THROTTLE_PATCH_MS = 1000         # im.message.patch — strict rate limits (code 230020) (was 1500)
LONG_GAP_THRESHOLD_MS = 200     # After this idle gap, batch the first flush (was 2000→1000→500)
BATCH_AFTER_GAP_MS = 30         # Batching window after a long gap (was 300→100→50)


@dataclass
class CardKitState:
    """CardKit-specific state."""
    card_id: Optional[str] = None  # CardKit card ID
    original_card_id: Optional[str] = None  # Original card ID before any fallbacks
    sequence: int = 0
    message_id: Optional[str] = None  # IM message ID


@dataclass
class TurnStep:
    """A single tool-call step within a Turn."""
    name: str = ""
    title: str = ""       # preview / summary text
    summary: str = ""     # short param summary
    status: str = "completed"  # running | completed | error
    hidden: bool = False

@dataclass
class Turn:
    """A group of tool-call steps belonging to one agent reply round."""
    turn_number: int = 1
    title: str = ""       # e.g. "搜索 Cut 文字压缩功能代码"
    steps: List[TurnStep] = field(default_factory=list)
    status: str = "completed"  # running | completed
    reasoning_text: str = ""   # Per-turn reasoning/thinking content

@dataclass
class TextState:
    """Text accumulation state."""
    accumulated_text: str = ""
    completed_text: str = ""
    streaming_prefix: str = ""
    last_partial_text: str = ""
    last_flushed_text: str = ""
    tool_use_text: str = ""
    tool_use_list: List = field(default_factory=list)  # Flat list (legacy compat)
    turns: List[Turn] = field(default_factory=list)     # Grouped by turn


@dataclass
class ReasoningState:
    """Reasoning/thinking state."""
    accumulated_text: str = ""
    start_time: Optional[float] = None
    elapsed_ms: int = 0
    is_phase: bool = False


@dataclass
class StreamingCardController:
    """
    Manages the lifecycle of a streaming CardKit card.

    State machine: idle -> creating -> streaming -> completed/aborted/terminated

    Supports:
    - AI response streaming (typewriter effect)
    - Task progress notifications
    - Tool use status updates
    """

    cfg: Dict[str, Any]
    chat_id: str
    client: Any  # lark_oapi client

    # Callbacks
    on_card_created: Optional[Callable] = None
    on_card_updated: Optional[Callable] = None
    on_card_finalized: Optional[Callable] = None

    # Configuration
    show_tool_use: bool = True
    reply_to_message_id: Optional[str] = None
    reply_in_thread: bool = False
    account_id: Optional[str] = None
    user_question: str = ""

    # Internal state
    _phase: CardPhase = CardPhase.IDLE
    _card_kit: CardKitState = field(default_factory=CardKitState)
    _text: TextState = field(default_factory=TextState)
    _reasoning: ReasoningState = field(default_factory=ReasoningState)
    _dispatch_start_time: float = field(default_factory=time.time)
    _first_content_time: Optional[float] = None  # Timestamp of first content/reasoning delta
    _terminal_reason: Optional[str] = None
    _flush_in_progress: bool = False
    _needs_reflush: bool = False
    _last_flush_time: float = 0
    _last_flushed_tool_count: int = 0   # Track tool count to detect changes
    _last_flushed_reasoning_len: int = 0  # Track reasoning length to detect changes
    _panel_update_pending: bool = False   # Whether a background panel update is in flight
    _pending_flush_task: Optional[asyncio.Task] = None
    _thinking_status_text: str = ""       # Current thinking status text on card
    _thinking_face_idx: int = 0           # Rotating index for kawaii faces
    _thinking_verb_idx: int = 0           # Rotating index for Chinese thinking verbs
    _iteration_count: Optional[int] = None  # Current iteration count for quota display
    _first_token_ms: Optional[int] = None   # First token timing for status bar

    @property
    def phase(self) -> CardPhase:
        return self._phase

    @property
    def is_terminal(self) -> bool:
        return self._phase in TERMINAL_PHASES

    @property
    def card_message_id(self) -> Optional[str]:
        return self._card_kit.message_id

    @property
    def terminal_reason(self) -> Optional[str]:
        return self._terminal_reason

    def should_proceed(self, source: str) -> bool:
        """Check if the pipeline should proceed for the given source.

        Returns False if:
        - The card is in a terminal phase (completed/aborted/terminated)
        - The reply-to message is known to be unavailable (deleted/recalled)
        """
        if self.is_terminal:
            return False
        if is_message_unavailable(self.reply_to_message_id):
            logger.info("[CardKit] should_proceed(%s): reply-to message unavailable, terminating", source)
            self.transition(CardPhase.TERMINATED, source, "message_unavailable")
            return False
        if self._card_kit.message_id and is_message_unavailable(self._card_kit.message_id):
            logger.info("[CardKit] should_proceed(%s): card message unavailable, terminating", source)
            self.transition(CardPhase.TERMINATED, source, "message_unavailable")
            return False
        return True

    def transition(self, to: CardPhase, source: str, reason: Optional[str] = None) -> bool:
        """Attempt to transition to a new phase."""
        from_state = self._phase
        if from_state == to:
            return False
        if to not in PHASE_TRANSITIONS.get(from_state, set()):
            logger.warning("[CardKit] phase transition rejected: %s -> %s (from %s)", from_state, to, source)
            return False
        self._phase = to
        logger.info("[CardKit] phase transition: %s -> %s (source=%s, reason=%s)", from_state, to, source, reason)
        if self.is_terminal:
            self._terminal_reason = reason
        return True

    def compute_elapsed_ms(self) -> int:
        """Compute elapsed time since dispatch start."""
        return int((time.time() - self._dispatch_start_time) * 1000)

    def _build_quote_section(self) -> Dict[str, Any]:
        """Build the user message quote section.
        
        Uses ReplyMessage official mechanism for the quote bar;
        just displays the user's question as a blockquote.
        """
        if not self.user_question:
            return {"tag": "markdown", "content": " "}
        return {
            "tag": "markdown",
            "content": f"> {self.user_question}"
        }

    # Kawaii thinking faces (from display.py KawaiiSpinner.KAWAII_THINKING)
    _THINKING_FACES = [
        "(*￣︶￣)", "╰(*°▽°*)╯", "ヾ(◍°∇°◍)ﾉ", "(๑•̀ㅂ•́)و✧",
        "(◍•ᴗ•◍)✧", "(*╹▽╹*)", "(•̀ᴗ•́)و", "(๑˃̵ᴗ˂̵)و",
        "(๑¯◡¯๑)", "ヾ(✿❛▽❛)ノ",
    ]

    # Chinese thinking verbs
    _THINKING_VERBS_CN = [
        "思考中…", "分析中…", "计算中…", "推理中…", "处理中…",
        "酝酿中…", "筹划中…", "检索中…", "琢磨中…", "探索中…",
    ]

    # Tool name → (icon, chinese_verb)
    _TOOL_ACTION_MAP = {
        "search_files": ("🔍", "搜索"),
        "search": ("🔍", "搜索"),
        "smart_search": ("🔎", "智能搜索"),
        "read_file": ("📖", "阅读"),
        "write_file": ("✏️", "写入"),
        "edit": ("✏️", "编辑"),
        "patch": ("🔧", "修补"),
        "web_search": ("🌐", "搜索"),
        "web_extract": ("🌐", "提取"),
        "browser": ("🌐", "浏览"),
        "terminal": ("⚡", "执行"),
        "session_search": ("🔎", "检索记忆"),
        "session": ("🔎", "检索"),
        "skill_view": ("📚", "查阅"),
        "skills_list": ("📚", "扫描"),
        "skill_manage": ("📚", "管理"),
        "todo": ("✅", "检查任务"),
        "clarify": ("💬", "询问"),
        "send_message": ("📤", "发送消息"),
        "notify": ("📤", "通知"),
        "mcp": ("🔌", "调用"),
        "list_dir": ("📁", "列出目录"),
        "check_submission": ("📋", "检查缺交"),
        "locate": ("📍", "定位"),
        "tree": ("🌳", "查看结构"),
        "stats": ("📊", "统计"),
    }

    @staticmethod
    def _match_tool_action(tool_name: str) -> tuple:
        """Match a tool name to (icon, verb)."""
        # Try exact match first
        if tool_name in StreamingCardController._TOOL_ACTION_MAP:
            return StreamingCardController._TOOL_ACTION_MAP[tool_name]
        # Try suffix match (e.g. mcp_xxx → mcp)
        for key, val in StreamingCardController._TOOL_ACTION_MAP.items():
            if tool_name.startswith(key) or key.startswith(tool_name):
                return val
        return ("🛠️", "执行")

    def _build_thinking_text(self) -> str:
        """Build the thinking status text shown during streaming.
        
        Rotates through kawaii faces and Chinese verbs on each call.
        When tools are present, shows the current tool action with context.
        Always appends quota line at the bottom.
        """
        lines = []
        
        # Rotate face + verb
        faces = self._THINKING_FACES
        verbs = self._THINKING_VERBS_CN
        face = faces[self._thinking_face_idx % len(faces)]
        verb = verbs[self._thinking_verb_idx % len(verbs)]
        self._thinking_face_idx += 1
        self._thinking_verb_idx += 1
        
        lines.append(f"🧠 {face} {verb}")
        
        # Tool action line — one line max, truncated if too long
        if self._text.tool_use_list:
            # Get the latest tool
            latest = self._text.tool_use_list[-1]
            tool_name = latest.get("name", "") if isinstance(latest, dict) else str(latest)
            icon, action_verb = self._match_tool_action(tool_name)
            # Extract a brief summary from args
            summary = latest.get("summary", "") if isinstance(latest, dict) else ""
            if not summary:
                args = latest.get("args", {}) if isinstance(latest, dict) else {}
                if args:
                    # For patch: show old_string → new_string trunc
                    if "old_string" in args and "new_string" in args:
                        old_s = str(args.get("old_string", ""))
                        new_s = str(args.get("new_string", ""))
                        o = old_s[:150] + ("..." if len(old_s) > 150 else "")
                        n = new_s[:150] + ("..." if len(new_s) > 150 else "")
                        summary = f"「{o}」→「{n}」"
                    else:
                        # Try known meaningful keys; skip mode/action keys
                        for k in ("path", "file_path", "command", "cmd", "query",
                                   "code", "url", "pattern", "message", "content",
                                   "keyword", "old_string", "new_string",
                                   "file_type", "question", "goal"):
                            v = args.get(k)
                            if v and isinstance(v, str):
                                s = v[:150] + ("..." if len(v) > 150 else "")
                                summary = s
                                break
            if summary:
                tool_line = f"{icon} {action_verb}「{summary}」"
            else:
                tool_line = f"{icon} {action_verb}中…"
            # Truncate to fit status line
            if len(tool_line) > 150:
                tool_line = tool_line[:147] + "…"
            lines.append(tool_line)
        
        # Quota line
        elapsed = self.compute_elapsed_ms()
        elapsed_str = self._format_elapsed(elapsed) if elapsed else ""
        iter_count = self._iteration_count
        quota_parts = []
        if iter_count is not None:
            quota_parts.append(f"Iter {iter_count}")
        if elapsed_str:
            quota_parts.append(f"耗时 {elapsed_str}")
        if quota_parts:
            lines.append(f"💳 {' · '.join(quota_parts)}")
        
        return "\n".join(lines)

    def _build_thinking_section(self, status_text: str = "") -> Dict[str, Any]:
        """Build the thinking status section — shown during processing."""
        if not status_text:
            status_text = "🧠 (◉_◉) pondering..."
        return {
            "tag": "markdown",
            "content": status_text,
            "element_id": "thinking_status"
        }

    def build_streaming_card(self, show_tool_use: bool = True) -> Dict[str, Any]:
        """Build the initial streaming card payload (CardKit 2.0 format).

        Layout (new design):
          ┌─ 💬 你说 ────────────────────┐  ← 引用用户消息
          │   > 用户问题...              │
          ├─ [Streaming Content] ─────┤  ← 流式正文
          ├─ 🧠 (◉_◉) pondering... ──┤  ← 思考中状态 (含工具信息)
          └──────────────────────────────┘
        """
        elements = []

        # ① Quote section — user's original message
        elements.append(self._build_quote_section())

        # Separator
        elements.append({"tag": "hr", "element_id": "divider_qt_cont"})

        # ② Streaming content element — starts with a thinking placeholder
        elements.append({
            "tag": "markdown",
            "content": " ",
            "text_align": "left",
            "text_size": "normal_v2",
            "margin": "0px 0px 0px 0px",
            "element_id": STREAMING_ELEMENT_ID
        })

        # ③ Thinking status section — shows KawaiiSpinner-style status
        elements.append({
            "tag": "hr",
            "element_id": "divider_thinking"
        })
        elements.append(self._build_thinking_section(
            self._build_thinking_text()
        ))

        return {
            "schema": "2.0",
            "config": {
                "streaming_mode": True,
                "streaming_config": {
                    "print_frequency_ms": {"default": 30},
                    "print_step": {"default": 2},
                    "print_strategy": "fast"
                },
                "update_multi": True,
                "enable_forward": True,
                "width_mode": "fill",
                "locales": ["zh_cn", "en_us"],
                "summary": {
                    "content": "处理中...",
                    "i18n_content": {"zh_cn": "处理中...", "en_us": "Processing..."}
                }
            },
            # No header (matches official bot style)
            "body": {
                "direction": "vertical",
                "padding": "12px",
                "vertical_spacing": "8px",
                "horizontal_align": "left",
                "elements": elements
            }
        }

    def build_complete_card(
        self,
        text: str,
        tool_use_steps: Optional[List] = None,
        tool_use_elapsed_ms: Optional[int] = None,
        show_tool_use: bool = True,
        is_error: bool = False,
        is_aborted: bool = False,
        elapsed_ms: Optional[int] = None,
        first_token_ms: Optional[int] = None,
        model_name: Optional[str] = None,
        token_usage: Optional[Dict[str, int]] = None,
        context_usage: Optional[Dict[str, Any]] = None,
        iteration_count: Optional[int] = None,
        max_iterations: Optional[int] = None,
        hourly_usage: Optional[Dict[str, int]] = None,
        balance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build the final/complete card payload.

        Layout:
          ① 💬 你说 (引用用户消息)
          ② 🛠️ N步 (工具调用折叠面板)
          ③ 正文 markdown + 表格
          ④ status bar (精简)
        """
        elements = []

        # ── ① Quote section ──
        elements.append(self._build_quote_section())
        elements.append({"tag": "hr", "element_id": "divider_quote_tool"})

        # ── ② Combined collapsible panel: turns with tool calls ──
        has_turns_with_content = False
        panel_inner_elements = []
        total_tool_count = 0

        if show_tool_use and self._text.turns:
            for turn in self._text.turns:
                visible_steps = [s for s in turn.steps if not s.hidden]

                if not visible_steps:
                    continue

                has_turns_with_content = True
                turn_elements = []

                # Per-turn tool calls (direct display)
                for i, step in enumerate(visible_steps):
                    total_tool_count += 1
                    normalized = _normalize_tool_step({
                        "name": step.name,
                        "title": step.title,
                        "summary": step.summary,
                        "status": step.status,
                    })
                    line = _format_tool_summary_line(normalized, i)
                    turn_elements.append({
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": line
                        }
                    })

                if turn_elements:
                    panel_inner_elements.append({
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**Turn {turn.turn_number}:**"
                        }
                    })
                    panel_inner_elements.extend(turn_elements)

        elif show_tool_use and tool_use_steps:
            # Legacy fallback: no turns, flat step list
            has_turns_with_content = True
            total_tool_count = len(tool_use_steps)
            panel_inner_elements.extend(self._build_tool_use_elements(tool_use_steps))

        if has_turns_with_content:
            # Build panel title — tool steps only, no reasoning count
            title_parts_zh = []
            if total_tool_count > 0:
                title_parts_zh.append(f"{total_tool_count} 步")
            elapsed_str = self._format_elapsed(tool_use_elapsed_ms) if tool_use_elapsed_ms else None
            if elapsed_str:
                title_parts_zh.append(f"({elapsed_str})")
            title_zh = "🛠️ " + " · ".join(title_parts_zh) if title_parts_zh else "🛠️ 工具执行"

            elements.append({
                "tag": "collapsible_panel",
                "expanded": False,
                "header": {
                    "title": {
                        "tag": "markdown",
                        "content": title_zh,
                    },
                    "vertical_align": "center",
                },
                "border": {"color": "grey", "corner_radius": "5px"},
                "vertical_spacing": "4px",
                "padding": "8px 8px 8px 8px",
                "elements": panel_inner_elements,
                "element_id": "tool_use_panel"
            })

        # Divider between tool panel and main content
        if has_turns_with_content:
            elements.append({
                "tag": "hr",
                "element_id": "divider_tool_content"
            })

        # ── ④ Main content ──
        content_elements: List[Dict[str, Any]] = []

        # Body text + tables
        segments = self._split_text_and_tables(text)

        # Estimate element count: pre-count all fixed elements, then decide
        # whether tables can use column_set layout or must fallback to markdown.
        # column_set table: (num_rows + 1) rows × (1 column_set + num_cols columns + num_cols markdowns)
        # markdown table: 1 element per table
        fixed_count = len(content_elements)  # reasoning panel + hr already added
        # Quote section: 2 elements (quote + hr) — already in `elements`, not content_elements
        # Tool panel + hr (if present): not in content_elements
        table_cols_count = 0
        table_segments = []
        text_segments = []
        for seg in segments:
            if seg["type"] == "text":
                text_segments.append(seg)
                fixed_count += 1  # 1 markdown tag
            else:
                table_segments.append(seg)
                if seg.get("headers"):
                    nc = max(len(seg["headers"]), max((len(r) for r in seg.get("rows", [])), default=0))
                else:
                    nc = 0
                table_cols_count += nc

        # Estimate column_set table element count:
        # Each row = (1 column_set + num_cols columns + num_cols markdowns)
        total_est = fixed_count
        for seg in table_segments:
            nc = max(len(seg.get("headers", [])),
                     max((len(r) for r in seg.get("rows", [])), default=0))
            num_rows = len(seg.get("rows", [])) + 1  # +1 for header row
            total_est += num_rows * (1 + nc + nc)  # column_set + columns + markdowns

        use_column_set_for_tables = total_est <= 200

        for seg in segments:
            if seg["type"] == "text":
                optimized = self._optimize_markdown(seg["content"])
                content_elements.append({
                    "tag": "markdown",
                    "content": optimized
                })
            elif seg["type"] in ("table",):
                table_elements = self._parse_markdown_table(
                    seg["headers"], seg["rows"],
                    use_column_set=use_column_set_for_tables
                )
                if table_elements:
                    content_elements.extend(table_elements)

        # Wrap content in outer column_set to avoid mixing markdown + column_set
        # at body.elements top level, which causes finalize update_card to fail.
        if content_elements:
            elements.append({
                "tag": "column_set",
                "flex_mode": "none",
                "background_style": "default",
                "horizontal_spacing": "default",
                "element_id": "body_content",
                "columns": [{
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "vertical_align": "top",
                    "elements": content_elements
                }]
            })

        # ── ⑤ Thinking completed footnote ──
        if is_error:
            done_text = "❌ **出错**"
        elif is_aborted:
            done_text = "⏹ **已停止**"
        else:
            done_text = "✨ **已完成**"

        elements.append({
            "tag": "hr",
            "element_id": "divider_footer_done"
        })
        elements.append({
            "tag": "markdown",
            "content": done_text,
            "element_id": "thinking_status"
        })

        # ── ⑥ Footer: two-row markdown status bar ──
        elapsed_str = self._format_elapsed(elapsed_ms) if elapsed_ms else None
        if elapsed_str:
            # Top row: model · iter · tokens
            top_parts_en = []
            top_parts_zh = []
            if model_name:
                short_model = model_name.rsplit("/", 1)[-1] if "/" in model_name else model_name
                top_parts_en.append(short_model)
                top_parts_zh.append(short_model)
            if iteration_count is not None:
                if max_iterations and max_iterations > 0:
                    iter_label = f"iter {iteration_count}/{max_iterations}"
                else:
                    iter_label = f"iter {iteration_count}"
                top_parts_en.append(iter_label)
                top_parts_zh.append(iter_label)
            if token_usage:
                total = token_usage.get("total", 0)
                if total > 0:
                    token_str = f"{self._compact_number(total)} tokens"
                    top_parts_en.append(token_str)
                    top_parts_zh.append(f"{self._compact_number(total)} tokens")
            if balance:
                top_parts_en.append(balance)
                top_parts_zh.append(balance)
            if hourly_usage and hourly_usage.get("limit", 0) > 0:
                hour_used = hourly_usage.get("used", 0)
                hour_limit = hourly_usage.get("limit", 0)
                hour_label = f"hour {hour_used}/{hour_limit}"
                top_parts_en.append(hour_label)
                top_parts_zh.append(hour_label)

            top_en = " · ".join(top_parts_en)
            top_zh = " · ".join(top_parts_zh)

            # Bottom row: context · elapsed · first_token
            bottom_parts_en = []
            bottom_parts_zh = []
            if context_usage:
                ctx_used = context_usage.get("used", 0)
                ctx_total = context_usage.get("total", 0)
                if ctx_used > 0 and ctx_total > 0:
                    ctx_percent = min(100, round((ctx_used / ctx_total) * 100))
                    ctx_label = f"{self._format_token_k(ctx_used)}/{self._format_token_k(ctx_total)} {ctx_percent}%"
                    bottom_parts_en.append(ctx_label)
                    bottom_parts_zh.append(ctx_label)
            bottom_parts_en.append(f"Elapsed {elapsed_str}")
            bottom_parts_zh.append(f"耗时 {elapsed_str}")
            first_token_str = self._format_elapsed(first_token_ms) if first_token_ms else None
            if first_token_str:
                bottom_parts_en.append(f"First token {first_token_str}")
                bottom_parts_zh.append(f"首响应 {first_token_str}")

            bottom_en = " · ".join(bottom_parts_en)
            bottom_zh = " · ".join(bottom_parts_zh)

            left_color = "red" if is_error else "grey"
            top_content_en = f"<font color='{left_color}'>{top_en}</font>"
            top_content_zh = f"<font color='{left_color}'>{top_zh}</font>"
            bottom_content_en = f"<font color='grey'>{bottom_en}</font>"
            bottom_content_zh = f"<font color='grey'>{bottom_zh}</font>"

            elements.append({
                "tag": "markdown",
                "content": top_content_en,
                "i18n_content": {"zh_cn": top_content_zh, "en_us": top_content_en},
                "text_size": "notation",
                "element_id": "footer_status"
            })
            elements.append({
                "tag": "markdown",
                "content": bottom_content_en,
                "i18n_content": {"zh_cn": bottom_content_zh, "en_us": bottom_content_en},
                "text_size": "notation",
                "element_id": "footer_stats"
            })

            # Overflow menu: V2 places overflow directly in body.elements (no "action" wrapper)
            elements.append({
                "tag": "overflow",
                "element_id": "overflow_menu",
                "options": [
                    {
                        "text": {"tag": "plain_text", "content": "📄 导出为TXT"},
                        "value": "export_txt",
                    },
                ],
            })

        # Summary
        summary_text = text.replace(r"[*_`#>\[\]()~]", "").strip()[:120]

        return {
            "schema": "2.0",
            "config": {
                "wide_screen_mode": True,
                "update_multi": True,
                "enable_forward": True,
                "width_mode": "fill",
                "locales": ["zh_cn", "en_us"],
                "summary": {"content": summary_text} if summary_text else None
            },
            # No header (matches official bot style)
            "body": {
                "direction": "vertical",
                "padding": "12px",
                "vertical_spacing": "8px",
                "horizontal_align": "left",
                "elements": elements
            }
        }

    @staticmethod
    def _parse_markdown_table(headers: List[str], rows: List[List[str]],
                              use_column_set: bool = True) -> Optional[List[Dict[str, Any]]]:
        """Parse a markdown table into CardKit elements.

        When use_column_set=True: one column_set per row, one column per cell.
        True aligned table on all clients, but uses more elements.

        When use_column_set=False: single markdown element with standard
        markdown table syntax.  Uses only 1 element per table.

        Returns None if parsing fails.
        """
        num_cols = max(len(headers), max((len(r) for r in rows), default=0))
        if num_cols == 0:
            return None

        # ── Fallback: pure markdown table (1 element) ──
        if not use_column_set:
            lines = []
            lines.append("| " + " | ".join(h if h else " " for h in headers) + " |")
            lines.append("| " + " | ".join("---" for _ in range(num_cols)) + " |")
            for row in rows:
                vals = [row[ci] if ci < len(row) else " " for ci in range(num_cols)]
                lines.append("| " + " | ".join(vals) + " |")
            table_md = "\n".join(lines)
            return [{"tag": "markdown", "content": table_md, "text_size": "notation"}]

        # ── column_set mode (n elements) ──
        col_weight = 1
        result: List[Dict[str, Any]] = []

        # Header row (grey background)
        header_cols: List[Dict] = []
        for ci in range(num_cols):
            header_cols.append({
                "tag": "column",
                "width": "weighted",
                "weight": col_weight,
                "vertical_align": "top",
                "elements": [{
                    "tag": "markdown",
                    "content": f"**{headers[ci]}**" if headers[ci] else " ",
                    "text_size": "notation"
                }]
            })

        result.append({
            "tag": "column_set",
            "flex_mode": "none",
            "background_style": "grey",
            "horizontal_spacing": "default",
            "element_id": f"th{id(headers) % 10000}",
            "columns": header_cols
        })

        # Data rows
        for ri, row in enumerate(rows):
            data_cols: List[Dict] = []
            for ci in range(num_cols):
                cell_val = row[ci] if ci < len(row) else ""
                data_cols.append({
                    "tag": "column",
                    "width": "weighted",
                    "weight": col_weight,
                    "vertical_align": "top",
                    "elements": [{
                        "tag": "markdown",
                        "content": cell_val if cell_val else " ",
                        "text_size": "notation"
                    }]
                })

            result.append({
                "tag": "column_set",
                "flex_mode": "none",
                "background_style": "default",
                "horizontal_spacing": "default",
                "element_id": f"tr{id(headers) % 10000}_{ri}",
                "columns": data_cols
            })

        return result

    @staticmethod
    def _split_text_and_tables(text: str) -> List[Dict[str, Any]]:
        """Split content into text segments and table segments.

        Returns list of dicts:
          {"type": "text", "content": str}
          {"type": "table", "headers": [str], "rows": [[str]]}

        Must be called BEFORE _optimize_markdown to avoid <br> spacers
        interfering with table detection.
        """
        segments = []
        last_end = 0

        # Split into code blocks and non-code blocks
        blocks = text.split("```")
        table_re = re.compile(
            r"^[ \t]*\|(.+)\|[ \t]*\n"
            r"[ \t]*\|([-:| ]+)\|[ \t]*\n"
            r"((?:[ \t]*\|.*\|[ \t]*\n)*)",
            re.MULTILINE
        )

        # Build sorted list of table positions
        tables_info: List[tuple[int, int, List[str], List[List[str]]]] = []
        for i, block in enumerate(blocks):
            if i % 2 == 1:
                continue  # inside code block
            prefix_len = sum(len(blocks[j]) for j in range(i))
            prefix_len += len("```") * i  # account for code fence markers
            for match in table_re.finditer(block):
                abs_start = prefix_len + match.start()
                abs_end = abs_start + len(match.group(0))
                header_cells = [c.strip() for c in match.group(1).split("|")]
                body_raw = match.group(3).strip()
                body_rows: List[List[str]] = []
                if body_raw:
                    for line in body_raw.split("\n"):
                        line = line.strip()
                        if line.startswith("|") and line.endswith("|"):
                            cells = [c.strip() for c in line[1:-1].split("|")]
                            body_rows.append(cells)
                tables_info.append((abs_start, abs_end, header_cells, body_rows))

        tables_info.sort(key=lambda x: x[0])

        for start, end, headers, rows in tables_info:
            if start > last_end:
                chunk = text[last_end:start].strip()
                if chunk:
                    segments.append({"type": "text", "content": chunk})
            segments.append({"type": "table", "headers": headers, "rows": rows})
            last_end = end

        if last_end < len(text):
            remaining = text[last_end:].strip()
            if remaining:
                segments.append({"type": "text", "content": remaining})

        if not segments:
            segments.append({"type": "text", "content": text})

        return segments

    def build_progress_card(
        self,
        title: str,
        progress_text: str,
        progress_percent: Optional[int] = None,
        status: str = "Processing"
    ) -> Dict[str, Any]:
        """Build a progress notification card."""
        elements = []

        # Progress bar if percentage provided
        if progress_percent is not None:
            bar_length = 20
            filled = int(bar_length * progress_percent / 100)
            bar = "█" * filled + "░" * (bar_length - filled)
            elements.append({
                "tag": "markdown",
                "content": f"**Progress:** [{bar}] {progress_percent}%"
            })
        else:
            elements.append({
                "tag": "markdown",
                "content": f"**Status:** {status}"
            })

        # Progress details
        elements.append({
            "tag": "markdown",
            "content": progress_text
        })

        return {
            "schema": "2.0",
            "config": {
                "update_multi": True,
                "enable_forward": True,
                "width_mode": "fill",
            },
            "header": {
                "title": {"content": title, "tag": "plain_text"},
                "template": "blue"
            },
            "body": {
                "direction": "vertical",
                "padding": "12px",
                "vertical_spacing": "8px",
                "elements": elements
            }
        }

    @staticmethod
    def build_img_element(img_key: str, alt: str = "", title: str = "",
                          img_size: str = "auto",
                          element_id: Optional[str] = None) -> Dict[str, Any]:
        """Build a JSON V2 image (img) component element.

        Args:
            img_key: Image key obtained from the Feishu upload image API.
            alt: Alternative text for accessibility.
            title: Image title/caption.
            img_size: Image size mode. Options: "auto", "stretch".
            element_id: Optional unique element ID for streaming updates.
        """
        el: Dict[str, Any] = {
            "tag": "img",
            "img_key": img_key,
            "alt": {"tag": "plain_text", "content": alt or "image"},
            "mode": img_size,
        }
        if title:
            el["title"] = {"tag": "plain_text", "content": title}
        if element_id:
            el["element_id"] = element_id
        return el

    def _format_elapsed(self, ms: Optional[int]) -> Optional[str]:
        """Format milliseconds into human-readable duration."""
        if ms is None:
            return None
        seconds = ms / 1000
        if seconds < 60:
            return f"{seconds:.1f}s"
        return f"{int(seconds // 60)}m {round(seconds % 60)}s"

    @staticmethod
    def _filter_reasoning(text: str) -> str:
        """
        Extract Chinese process descriptions from reasoning text.

        Shows the last Chinese paragraph (up to 200 chars) so the user
        can see what the agent is currently doing — e.g. "让我看看日志…",
        "找到原因了，是 xxx 导致的".

        Falls back to the full reasoning text if no Chinese found (so the
        reasoning panel always shows up when reasoning exists).
        """
        if not text:
            return ""

        # Find all Chinese segments (sequences containing Chinese chars)
        segments = re.findall(r'[\u4e00-\u9fff][^\n]{0,200}', text)
        if not segments:
            return text  # Fallback to full reasoning, no Chinese content

        # Take the last segment — it reflects current activity
        result = segments[-1].strip()
        if len(result) > 200:
            result = result[:197] + "…"
        return result

    @staticmethod
    def _compact_number(n: int) -> str:
        """Format large numbers compactly: 1.2K, 3.5M, etc."""
        if n < 1000:
            return str(n)
        if n < 1_000_000:
            return f"{n / 1000:.1f}K"
        return f"{n / 1_000_000:.1f}M"

    @staticmethod
    def _format_token_k(tokens: int) -> str:
        """Format token count like CLI: 128000 -> '128K', 45000 -> '45K'."""
        if tokens >= 1_000_000:
            val = tokens / 1_000_000
            rounded = round(val)
            if abs(val - rounded) < 0.05:
                return f"{rounded}M"
            return f"{val:.1f}M"
        if tokens >= 1_000:
            val = tokens / 1_000
            rounded = round(val)
            if abs(val - rounded) < 0.05:
                return f"{rounded}K"
            return f"{val:.1f}K"
        return str(tokens)

    # ===================================================================
    # Markdown table limit handling
    # ===================================================================

    @staticmethod
    def _find_markdown_tables_outside_code_blocks(text: str) -> List[Dict]:
        """Find markdown tables that are NOT inside code blocks.

        Returns list of {index, length, raw} dicts, sorted by position.
        """
        # First, identify code block ranges
        code_ranges: List[tuple] = []
        cb_pat = re.compile(r'(`{3,})[^\n]*\n[\s\S]*?\n\1', re.MULTILINE)
        for m in cb_pat.finditer(text):
            code_ranges.append((m.start(), m.end()))

        def _in_code(pos: int) -> bool:
            return any(s <= pos < e for s, e in code_ranges)

        table_pat = re.compile(
            r'\|.+\|[\r\n]+\|[-:| ]+\|[\s\S]*?(?=\n\n|\n(?!\|)|$)'
        )
        results = []
        for m in table_pat.finditer(text):
            if not _in_code(m.start()):
                results.append({
                    "index": m.start(),
                    "length": len(m.group(0)),
                    "raw": m.group(0),
                })
        return results

    @classmethod
    def sanitize_text_for_card(
        cls, text: str, table_limit: int = FEISHU_CARD_TABLE_LIMIT
    ) -> str:
        """Wrap markdown tables beyond *table_limit* in code blocks.

        Feishu cards reject messages with >3 markdown tables (error
        230099 / 11310).  This keeps the first *table_limit* tables as
        native card tables and wraps the rest in fenced code blocks so
        they render as plain text instead of crashing the card.
        """
        tables = cls._find_markdown_tables_outside_code_blocks(text)
        if len(tables) <= table_limit:
            return text

        # Back-to-front replacement to keep indices stable
        result = text
        for t in reversed(tables[table_limit:]):
            replacement = f"```\n{t['raw']}\n```"
            result = result[:t["index"]] + replacement + result[t["index"] + t["length"]:]
        return result

    @classmethod
    def sanitize_text_segments_for_card(
        cls, segments: List[str], table_limit: int = FEISHU_CARD_TABLE_LIMIT
    ) -> List[str]:
        """Share a table budget across multiple text segments (e.g. reasoning + body)."""
        budget = table_limit
        result = []
        for seg in segments:
            tables = cls._find_markdown_tables_outside_code_blocks(seg)
            if len(tables) <= budget:
                budget -= len(tables)
                result.append(seg)
            else:
                result.append(cls._sanitize_segment_tables(seg, tables, max(budget, 0)))
                budget = 0
        return result

    @classmethod
    def _sanitize_segment_tables(cls, text: str, tables: List[Dict], keep: int) -> str:
        """Internal: wrap tables beyond *keep* in code blocks."""
        if len(tables) <= keep:
            return text
        result = text
        for t in reversed(tables[keep:]):
            replacement = f"```\n{t['raw']}\n```"
            result = result[:t["index"]] + replacement + result[t["index"] + t["length"]:]
        return result

    @staticmethod
    def _strip_invalid_image_keys(text: str) -> str:
        """Remove ![alt](value) where value is not a valid Feishu img_xxx key.

        Prevents CardKit error 200570.  HTTP URLs that haven't been
        resolved by ImageResolver are also stripped as a safety net.
        """
        if '![' not in text:
            return text
        def _replacer(m):
            value = m.group(2)
            if value.startswith('img_'):
                return m.group(0)
            return ''
        return re.sub(r'!\[([^\]]*)\]\(([^)\s]+)\)', _replacer, text)

    @classmethod
    def _optimize_markdown(cls, text: str) -> str:
        """Optimize markdown for Feishu CardKit 2.0 rendering.

        Applies:
        1. Code block extraction & protection
        2. Heading demotion (H1->H4, H2-H6->H5)
        3. Paragraph spacing around tables
        4. Compress excessive blank lines
        5. Strip invalid image keys (non img_xxx)
        6. Table sanitization (wrap excess tables in code blocks)

        Reference: openclaw-lark/src/card/markdown-style.js
        """
        try:
            return cls._do_optimize_markdown(text)
        except Exception:
            return text

    @classmethod
    def _do_optimize_markdown(cls, text: str) -> str:
        if not text or not text.strip():
            return text

        # 1. Extract code blocks, replace with placeholders
        MARK = '___CB_'
        code_blocks: List[str] = []
        code_pattern = re.compile(
            r'(?:^|\n)(`{3,})([^\n]*)\n[\s\S]*?\n\1(?:\n|$)', re.MULTILINE
        )

        def _extract_code(m):
            block = m.group(0)
            idx = len(code_blocks)
            code_blocks.append(block)
            return f'\n{MARK}{idx}___\n'

        r = code_pattern.sub(_extract_code, text)

        # 2. Heading demotion (only when H1-H3 present)
        has_h1_to_h3 = bool(re.search(r'^#{1,3} ', r, re.MULTILINE))
        if has_h1_to_h3:
            r = re.sub(r'^#{2,6} (.+)$', r'##### \1', r, flags=re.MULTILINE)
            r = re.sub(r'^# (.+)$', r'#### \1', r, flags=re.MULTILINE)

        # 3. Add spacing around tables
        # 3a. Non-table line directly followed by table row -> insert blank line
        r = re.sub(
            r'^([^|\n].*)\n(\|.+\|)',
            r'\1\n\n\2',
            r,
            flags=re.MULTILINE,
        )
        # 3b. Before table block: insert <br> spacer
        r = re.sub(
            r'\n\n((?:\|.+\|[^\S\n]*\n?)+)',
            '\n\n<br>\n\n\\1',
            r,
        )
        # 3c. After table block: append <br> (skip before heading/bold/EOF)
        r = re.sub(
            r'((?:^\|.+\|[^\S\n]*\n?)+)',
            _table_after_spacing,
            r,
            flags=re.MULTILINE,
        )

        # 4. Restore code blocks with <br> spacers
        for i, block in enumerate(code_blocks):
            r = r.replace(f'{MARK}{i}___', f'\n<br>\n{block}\n<br>\n')

        # 5. Compress 3+ consecutive newlines -> 2
        r = re.sub(r'\n{3,}', '\n\n', r)

        # 6. Strip invalid image keys
        r = cls._strip_invalid_image_keys(r)

        # 7. Sanitize tables (wrap excess in code blocks)
        r = cls.sanitize_text_for_card(r)

        return r.strip()

    def _build_tool_use_elements(self, steps: List) -> List[Dict]:
        """Build structured tool use step elements with icons and summaries.

        Each step is rendered as a markdown line with:
        - Emoji icon based on tool type
        - Bold tool title (Read, Write, Search, etc.)
        - Parameter summary in inline code (file path, query, command)
        - Status indicator (✓ completed, ⏳ running, ❌ error)

        Steps marked as "hidden" (e.g. clarify) are filtered out.
        """
        elements = []
        for i, step in enumerate(steps):
            normalized = _normalize_tool_step(step)
            if normalized.get("hidden"):
                continue
            line = _format_tool_summary_line(normalized, i)
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": line
                }
            })
        return elements

    def _build_streaming_card_with_tool_use(self) -> Dict[str, Any]:
        """
        Build a streaming card — no tool use panel in streaming phase.
        Tool info is shown via thinking_status line (颜文字行).
        """
        elements = []

        # ── Streaming content element ──
        streaming_text = self._text.accumulated_text or ""
        elements.append({
            "tag": "markdown",
            "content": streaming_text,
            "text_align": "left",
            "text_size": "normal_v2",
            "margin": "0px 0px 0px 0px",
            "element_id": STREAMING_ELEMENT_ID
        })

        # Loading indicator
        elements.append({
            "tag": "markdown",
            "content": " ",
            "text_align": "left",
            "text_size": "normal_v2"
        })

        return {
            "schema": "2.0",
            "config": {
                "streaming_mode": True,
                "streaming_config": {
                    "print_frequency_ms": {"default": 30},
                    "print_step": {"default": 2},
                    "print_strategy": "fast"
                },
                "locales": ["zh_cn", "en_us"]
            },
            "body": {
                "elements": elements
            }
        }

    def _build_simple_streaming_card(self) -> Dict[str, Any]:
        """Build a simple streaming card without tool use panel.

        Used when all tool steps are hidden (e.g. clarify only).
        Shows streaming text only (no reasoning display).
        """
        elements = []

        # Streaming content
        elements.append({
            "tag": "markdown",
            "content": self._text.accumulated_text or "",
            "text_align": "left",
            "text_size": "normal_v2",
            "margin": "0px 0px 0px 0px",
            "element_id": STREAMING_ELEMENT_ID
        })

        # Loading indicator
        elements.append({
            "tag": "markdown",
            "content": " ",
            "text_align": "left",
            "text_size": "normal_v2"
        })

        return {
            "schema": "2.0",
            "config": {
                "streaming_mode": True,
                "streaming_config": {
                    "print_frequency_ms": {"default": 30},
                    "print_step": {"default": 2},
                    "print_strategy": "fast"
                },
                "locales": ["zh_cn", "en_us"]
            },
            "body": {
                "elements": elements
            }
        }

    # =======================================================================
    # CardKit API Operations
    # =======================================================================

    async def create_card_entity(self, card: Dict[str, Any]) -> Optional[str]:
        """
        Create a CardKit card entity via the CardKit API.

        Returns the card_id on success, None on failure.
        """
        if not LARK_AVAILABLE:
            logger.error("[CardKit] lark_oapi not available")
            return None

        try:
            request = (
                CreateCardRequest.builder()
                .request_body(
                    CreateCardRequestBody.builder()
                    .type("card_json")
                    .data(json.dumps(card))
                    .build()
                )
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(self.client.cardkit.v1.card.create, request),
                timeout=10.0
            )

            if response.code == 0:
                card_id = response.data.card_id if hasattr(response, 'data') and response.data else None
                if card_id:
                    logger.info("[CardKit] created card entity: %s", card_id)
                    return card_id
            else:
                logger.warning("[CardKit] create_card_entity failed: code=%s, msg=%s", response.code, response.msg)

        except asyncio.TimeoutError:
            logger.warning("[CardKit] create_card_entity timed out after 10s")
        except Exception as e:
            logger.error("[CardKit] create_card_entity exception: %s", e)

        return None

    async def send_card_message(self, card_id: str, to: str) -> Optional[Dict[str, str]]:
        """
        Send an interactive card message referencing a CardKit card_id.

        Returns {'message_id': ..., 'chat_id': ...} on success.
        """
        if not LARK_AVAILABLE:
            return None

        # Guard: skip if reply-to message was already recalled/deleted
        if self.reply_to_message_id and is_message_unavailable(self.reply_to_message_id):
            logger.info("[CardKit] send_card_message: reply-to %s is unavailable, skipping", self.reply_to_message_id)
            return None

        try:
            content_payload = json.dumps({
                "type": "card",
                "data": {"card_id": card_id}
            })

            if self.reply_to_message_id:
                logger.info("[CardKit] send_card_message replying to message_id=%s", self.reply_to_message_id)
                # 使用 ReplyMessage REST API 实现引用条效果
                # POST /open-apis/im/v1/messages/{message_id}/reply
                # reply_to_message_id 天然实现"引用回复"UI
                request = (
                    BaseRequest.builder()
                    .http_method(HttpMethod.POST)
                    .uri(f"/open-apis/im/v1/messages/{self.reply_to_message_id}/reply")
                    .body({
                        "content": content_payload,
                        "msg_type": "interactive",
                    })
                    .token_types({AccessTokenType.TENANT})
                    .build()
                )
                response = await asyncio.wait_for(
                    asyncio.to_thread(self.client.request, request),
                    timeout=10.0
                )
            else:
                request = (
                    CreateMessageRequest.builder()
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(to)
                        .content(content_payload)
                        .msg_type("interactive")
                        .build()
                    )
                    .receive_id_type("chat_id")
                    .build()
                )
                response = await asyncio.wait_for(
                    asyncio.to_thread(self.client.im.v1.message.create, request),
                    timeout=10.0
                )

            # 兼容两种 response 格式：
            # SDK 方法 (CreateMessage/ReplyMessage) → response.data.message_id
            # BaseRequest (REST API)               → response.raw.content (JSON)
            raw_content = getattr(getattr(response, "raw", None), "content", None)
            if raw_content:
                # BaseRequest 路径：从 raw.content JSON 解析
                payload = json.loads(raw_content)
                if payload.get("code") == 0:
                    msg_info = payload.get("data", {})
                    result = {
                        'message_id': msg_info.get('message_id', ''),
                        'chat_id': msg_info.get('chat_id', ''),
                    }
                    logger.info("[CardKit] sent card message (REST): %s", result['message_id'])
                    return result
                else:
                    logger.warning("[CardKit] send_card_message REST failed: code=%s, msg=%s",
                                   payload.get("code"), payload.get("msg"))
                    check_api_error_unavailable(self.reply_to_message_id, payload, "send_card_message")
            elif hasattr(response, 'data') and response.data:
                # SDK 路径
                result = {
                    'message_id': getattr(response.data, 'message_id', ''),
                    'chat_id': getattr(response.data, 'chat_id', '')
                }
                logger.info("[CardKit] sent card message (SDK): %s", result['message_id'])
                return result

        except asyncio.TimeoutError:
            logger.warning("[CardKit] send_card_message timed out after 10s")
        except Exception as e:
            logger.error("[CardKit] send_card_message exception: %s", e)
            check_api_error_unavailable(self.reply_to_message_id, e, "send_card_message")

        return None

    async def stream_content(self, card_id: str, element_id: str, content: str, sequence: int) -> bool:
        """
        Stream text content to a specific card element.

        The card automatically diffs the new content and renders with typewriter effect.
        """
        if not LARK_AVAILABLE:
            return False

        try:
            request = (
                ContentCardElementRequest.builder()
                .card_id(card_id)
                .element_id(element_id)
                .request_body(
                    ContentCardElementRequestBody.builder()
                    .content(content)
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(self.client.cardkit.v1.card_element.content, request),
                timeout=10.0
            )

            if response.code == 0:
                return True
            else:
                logger.warning("[CardKit] stream_content failed: code=%s, msg=%s", response.code, response.msg)
                check_api_error_unavailable(self._card_kit.message_id, response, "stream_content")

        except asyncio.TimeoutError:
            logger.warning("[CardKit] stream_content timed out after 10s")
        except Exception as e:
            logger.error("[CardKit] stream_content exception: %s", e)
            check_api_error_unavailable(self._card_kit.message_id, e, "stream_content")

        return False

    async def update_card(self, card_id: str, card: Dict[str, Any], sequence: int) -> bool:
        """
        Fully update/replace a CardKit card.

        Used for final state updates after streaming completes.
        """
        if not LARK_AVAILABLE:
            return False

        try:
            request = (
                UpdateCardRequest.builder()
                .card_id(card_id)
                .request_body(
                    UpdateCardRequestBody.builder()
                    .card({
                        "type": "card_json",
                        "data": json.dumps(card)
                    })
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(self.client.cardkit.v1.card.update, request),
                timeout=10.0
            )

            if response.code == 0:
                return True
            else:
                logger.warning("[CardKit] update_card failed: code=%s, msg=%s", response.code, response.msg)
                check_api_error_unavailable(self._card_kit.message_id, response, "update_card")

        except asyncio.TimeoutError:
            logger.warning("[CardKit] update_card timed out after 10s")
        except Exception as e:
            logger.error("[CardKit] update_card exception: %s", e)
            check_api_error_unavailable(self._card_kit.message_id, e, "update_card")

        return False

    async def patch_card_element(self, card_id: str, element_id: str,
                                  partial_element: Dict[str, Any],
                                  sequence: int) -> bool:
        """
        Patch (partial update) a single element in a CardKit card.

        Uses PatchCardElement API to update only the changed parts of an
        element, avoiding the cost of rebuilding and replacing the entire
        card JSON.  Much lighter than update_card for streaming panel updates.
        """
        if not LARK_AVAILABLE:
            return False

        try:
            request = (
                PatchCardElementRequest.builder()
                .card_id(card_id)
                .element_id(element_id)
                .request_body(
                    PatchCardElementRequestBody.builder()
                    .partial_element(json.dumps(partial_element))
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(self.client.cardkit.v1.card_element.patch, request),
                timeout=10.0
            )

            if response.code == 0:
                return True
            else:
                logger.warning("[CardKit] patch_card_element failed: code=%s, msg=%s", response.code, response.msg)
                check_api_error_unavailable(self._card_kit.message_id, response, "patch_card_element")

        except asyncio.TimeoutError:
            logger.warning("[CardKit] patch_card_element timed out after 10s")
        except Exception as e:
            logger.error("[CardKit] patch_card_element exception: %s", e)
            check_api_error_unavailable(self._card_kit.message_id, e, "patch_card_element")

        return False

    async def set_streaming_mode(self, card_id: str, enabled: bool, sequence: int) -> bool:
        """
        Enable or disable streaming mode on a CardKit card.

        Must be called after streaming completes to restore normal card behavior.
        """
        if not LARK_AVAILABLE:
            return False

        try:
            request = (
                SettingsCardRequest.builder()
                .card_id(card_id)
                .request_body(
                    SettingsCardRequestBody.builder()
                    .settings(json.dumps({"streaming_mode": enabled}))
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(self.client.cardkit.v1.card.settings, request),
                timeout=10.0
            )

            if response.code == 0:
                logger.info("[CardKit] set streaming_mode=%s for card %s", enabled, card_id)
                return True
            else:
                logger.warning("[CardKit] set_streaming_mode failed: code=%s, msg=%s", response.code, response.msg)
                check_api_error_unavailable(self._card_kit.message_id, response, "set_streaming_mode")

        except asyncio.TimeoutError:
            logger.warning("[CardKit] set_streaming_mode timed out after 10s")
        except Exception as e:
            logger.error("[CardKit] set_streaming_mode exception: %s", e)
            check_api_error_unavailable(self._card_kit.message_id, e, "set_streaming_mode")

        return False

    # =======================================================================
    # Streaming Controller Interface
    # =======================================================================

    async def ensure_card_created(self) -> bool:
        """
        Ensure the streaming card is created and sent.

        This is called when the first content arrives and we need to show the card.
        """
        if self._card_kit.message_id or self._phase == CardPhase.CREATION_FAILED:
            return True

        if not self.transition(CardPhase.CREATING, "ensure_card_created"):
            return False

        # Build initial streaming card
        card = self.build_streaming_card(show_tool_use=self.show_tool_use)

        # Create CardKit entity
        card_id = await self.create_card_entity(card)
        if not card_id:
            logger.warning("[CardKit] card creation failed, falling back to static card")
            self.transition(CardPhase.CREATION_FAILED, "create_card_entity", "creation_failed")
            return False

        self._card_kit.card_id = card_id
        self._card_kit.original_card_id = card_id
        self._card_kit.sequence = 1

        # Send IM message
        result = await self.send_card_message(card_id, self.chat_id)
        if not result or not result.get('message_id'):
            logger.error("[CardKit] failed to send card message")
            self.transition(CardPhase.CREATION_FAILED, "send_card_message", "creation_failed")
            return False

        self._card_kit.message_id = result['message_id']
        self.transition(CardPhase.STREAMING, "ensure_card_created", "streaming")

        if self.on_card_created:
            await self.on_card_created(self._card_kit.message_id)

        return True

    async def update_content(
        self,
        text: str,
        reasoning_text: Optional[str] = None,
        tool_use_text: Optional[str] = None,
        is_partial: bool = False
    ) -> bool:
        """
        Update streaming content on the card.

        Args:
            text: The content text to display
            reasoning_text: Optional reasoning/thinking content
            tool_use_text: Optional tool use/progress text
            is_partial: If True, this is a partial update (typewriter effect)
        """
        if not self.should_proceed("update_content"):
            return False

        if not self._card_kit.card_id:
            await self.ensure_card_created()

        if not self._card_kit.card_id:
            return False

        # Accumulate text
        if reasoning_text:
            self._reasoning.accumulated_text = reasoning_text
            self._reasoning.is_phase = True
            if not self._reasoning.start_time:
                self._reasoning.start_time = time.time()
            if not self._first_content_time:
                self._first_content_time = time.time()

        # Accumulate text with reply boundary detection.
        # When text length shrinks compared to the last partial, it means
        # a new reply round started (e.g. after tool calls).  Move the
        # previous round's text into streaming_prefix so accumulated_text
        # captures the full multi-round output.
        # Reference: openclaw onPartialReply boundary detection
        if text:
            if self._text.last_partial_text and len(text) < len(self._text.last_partial_text):
                self._text.streaming_prefix += (
                    ("\n\n" + self._text.last_partial_text)
                    if self._text.streaming_prefix
                    else self._text.last_partial_text
                )
                logger.info(
                    "[CardKit] Reply boundary detected: text shrunk (%d -> %d), prefix_len=%d",
                    len(self._text.last_partial_text), len(text), len(self._text.streaming_prefix),
                )
            self._text.last_partial_text = text
            self._text.accumulated_text = (
                self._text.streaming_prefix + "\n\n" + text
                if self._text.streaming_prefix
                else text
            )
            if not self._first_content_time:
                self._first_content_time = time.time()

        if tool_use_text is not None:
            self._text.tool_use_text = tool_use_text

        # Check throttle — throttled update with deferred flush support
        throttle_ms = THROTTLE_CARDKIT_MS if self._card_kit.card_id else THROTTLE_PATCH_MS
        await self._throttled_update(throttle_ms)

        return True

    async def _throttled_update(self, throttle_ms: int) -> None:
        """Throttled update with deferred flush, mutex, and reflush support.

        Mirrors openclaw-lark FlushController.throttledUpdate():
        1. If enough time elapsed: flush immediately (or batch after long gap)
        2. If inside throttle window: schedule a deferred flush for the remaining time
        3. If a flush is in progress: mark needs_reflush for follow-up after current completes
        """
        now = time.time()
        elapsed_ms = (now - self._last_flush_time) * 1000

        if elapsed_ms >= throttle_ms:
            # Cancel any pending deferred flush
            self._cancel_pending_flush()

            if elapsed_ms > LONG_GAP_THRESHOLD_MS:
                # After a long idle gap (e.g. tool call finished), batch briefly
                # so the first visible update contains meaningful text rather
                # than just 1-2 characters.
                self._schedule_deferred_flush(BATCH_AFTER_GAP_MS / 1000)
            else:
                await self._flush_update()
        elif not self._pending_flush_task:
            # Inside throttle window — schedule a deferred flush
            delay = (throttle_ms - elapsed_ms) / 1000
            self._schedule_deferred_flush(delay)

    def _cancel_pending_flush(self) -> None:
        """Cancel any pending deferred flush timer."""
        if self._pending_flush_task is not None:
            self._pending_flush_task.cancel()
            self._pending_flush_task = None

    def _schedule_deferred_flush(self, delay: float) -> None:
        """Schedule a flush after `delay` seconds."""
        if self._pending_flush_task is not None:
            return  # Already scheduled

        async def _deferred():
            await asyncio.sleep(delay)
            self._pending_flush_task = None
            await self._flush_update()

        self._pending_flush_task = asyncio.ensure_future(_deferred())

    async def _flush_update(self) -> None:
        """Flush pending content update to the card.

        Mutex-guarded: if a flush is already in progress, marks _needs_reflush
        so a follow-up flush fires immediately after the current one completes.
        """
        if not self._card_kit.card_id:
            return

        # Mutex guard — if flush is already running, request a reflush
        if self._flush_in_progress:
            self._needs_reflush = True
            return

        if self.is_terminal:
            return

        self._flush_in_progress = True
        try:
            await self._do_flush()

            # After flush completes, check if another flush was requested
            # while we were running (reflush-on-conflict)
            if self._needs_reflush and not self.is_terminal:
                self._needs_reflush = False
                await self._do_flush()
        finally:
            self._flush_in_progress = False

    def _build_panel_partial(self) -> Optional[Dict[str, Any]]:
        """Build the partial element data for patching the tool_use_panel.

        Returns the collapsible_panel fields to patch (header title + inner
        elements), or None if there's nothing visible.
        """
        turns = self._text.turns
        steps = self._text.tool_use_list

        visible_flat = self._build_tool_use_elements(steps) if steps else []
        has_visible_turns = False

        if turns:
            for t in turns:
                if any(not s.hidden for s in t.steps):
                    has_visible_turns = True
                    break

        if not has_visible_turns and len(visible_flat) == 0:
            return None

        panel_inner_elements = []
        total_tool_count = 0

        if has_visible_turns:
            for turn in turns:
                visible_steps = [s for s in turn.steps if not s.hidden]

                if not visible_steps:
                    continue

                turn_elements = []

                for idx, step in enumerate(visible_steps):
                    total_tool_count += 1
                    line = _format_tool_summary_line(_normalize_tool_step({
                        "name": step.name, "title": step.title,
                        "summary": step.summary, "status": step.status,
                        "hidden": step.hidden
                    }), idx)
                    turn_elements.append({
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": line}
                    })

                if turn_elements:
                    turn_title = turn.title or f"Turn {turn.turn_number}"
                    panel_inner_elements.append({
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**Turn {turn.turn_number}:** {turn_title}"
                        }
                    })
                    panel_inner_elements.extend(turn_elements)
        else:
            total_tool_count = len(visible_flat)
            panel_inner_elements.extend(visible_flat)

        # Build panel title
        title_parts_zh = []
        if total_tool_count > 0:
            title_parts_zh.append(f"{total_tool_count} 步")
        title_zh = "🛠️ 执行中 · " + " · ".join(title_parts_zh) if title_parts_zh else "🛠️ 执行中"
        title_en_parts = []
        if total_tool_count > 0:
            title_en_parts.append(f"{total_tool_count} step{'s' if total_tool_count > 1 else ''}")
        title_en = "🛠️ Executing · " + " · ".join(title_en_parts) if title_en_parts else "🛠️ Executing"

        # Return partial element: only patch header title + inner elements
        return {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title_en,
                    "i18n_content": {"zh_cn": title_zh, "en_us": title_en},
                    "text_color": "grey",
                    "text_size": "notation"
                },
            },
            "elements": panel_inner_elements,
        }

    async def _do_flush(self) -> None:
        """Actual flush logic — called by _flush_update under mutex.

        Strategy: text streaming and panel updates are serialized via the
        shared sequence counter.

        - Text streams via lightweight stream_content (typewriter effect).
        - Panel updates use patch_card_element to only update the
          tool_use_panel element's header and inner content, instead of
          rebuilding the entire card JSON via update_card.
        """
        self._last_flush_time = time.time()

        display_text = self._text.accumulated_text or ""

        # --- 1. Lightweight text streaming (always, via cardElement.content) ---
        if display_text and display_text != self._text.last_flushed_text:
            self._card_kit.sequence += 1
            text_success = await self.stream_content(
                self._card_kit.card_id,
                STREAMING_ELEMENT_ID,
                display_text,
                self._card_kit.sequence
            )
            if text_success:
                self._text.last_flushed_text = display_text
            logger.info("[CardKit] _do_flush: stream_content, text_len=%d, success=%s",
                        len(display_text), text_success)

        # --- 2. Panel update via patch_card_element (only after finalize) ---
        # Streaming phase has no tool panel; tool info is shown in thinking_status line.
        if self.phase == CardPhase.COMPLETED:
            current_tool_count = len(self._text.tool_use_list) if self._text.tool_use_list else 0
            tool_count_changed = current_tool_count != self._last_flushed_tool_count

            current_reasoning_len = len(self._reasoning.accumulated_text) if self._reasoning.accumulated_text else 0
            reasoning_changed = current_reasoning_len != self._last_flushed_reasoning_len

            if (tool_count_changed or reasoning_changed) and self.show_tool_use:
                partial = self._build_panel_partial()
                if partial:
                    self._card_kit.sequence += 1
                    patch_success = await self.patch_card_element(
                        self._card_kit.card_id,
                        "tool_use_panel",
                        partial,
                        self._card_kit.sequence
                    )
                    if patch_success:
                        self._last_flushed_tool_count = current_tool_count
                        self._last_flushed_reasoning_len = current_reasoning_len
                    else:
                        # Fallback: if patch fails (e.g. element_id not recognized),
                        # try full update_card as before
                        logger.warning("[CardKit] _do_flush: patch_card_element failed, falling back to update_card")
                        self._card_kit.sequence += 1
                        card = self._build_streaming_card_with_tool_use()
                        card_success = await self.update_card(
                            self._card_kit.card_id,
                            card,
                            self._card_kit.sequence
                        )
                        if card_success:
                            self._text.last_flushed_text = display_text
                            self._last_flushed_tool_count = current_tool_count
                            self._last_flushed_reasoning_len = current_reasoning_len
                    logger.info("[CardKit] _do_flush: panel update, tools=%d, reasoning=%d",
                                current_tool_count, current_reasoning_len)

        # --- 3. Thinking status update (streaming phase) ---
        new_thinking = self._build_thinking_text()
        if new_thinking != self._thinking_status_text:
            self._card_kit.sequence += 1
            thinking_success = await self.patch_card_element(
                self._card_kit.card_id,
                "thinking_status",
                {"content": new_thinking},
                self._card_kit.sequence
            )
            if thinking_success:
                self._thinking_status_text = new_thinking

    async def _do_panel_update(self, display_text: str) -> None:
        """Legacy panel update — no longer used.

        Panel updates are now done inline in _do_flush via patch_card_element.
        """
        pass

    async def finalize(
        self,
        completed_text: str,
        reasoning_text: Optional[str] = None,
        reasoning_elapsed_ms: Optional[int] = None,
        tool_use_steps: Optional[List] = None,
        tool_use_elapsed_ms: Optional[int] = None,
        is_error: bool = False,
        is_aborted: bool = False,
        model_name: Optional[str] = None,
        token_usage: Optional[Dict[str, int]] = None,
        context_usage: Optional[Dict[str, Any]] = None,
        iteration_count: Optional[int] = None,
        hourly_usage: Optional[Dict[str, int]] = None,
        balance: Optional[str] = None,
        force: bool = False,
    ) -> None:
        """
        Finalize the streaming card with the completed response.

        This closes streaming mode and sends the final card content.
        If force=True, re-finalize even if already terminal (used during
        shutdown to re-send complete card content after streaming_mode reset).
        """
        if self.is_terminal and not force:
            return
        if self.is_terminal and force:
            # Re-finalize: skip phase transition but re-send card content
            logger.info("[CardKit] finalize(force=True): re-finalizing terminal card")
        else:
            self.transition(CardPhase.COMPLETED, "finalize", "normal")

        # Cancel any pending deferred flush and wait for in-progress flush
        self._cancel_pending_flush()
        self._needs_reflush = False
        # Wait for any in-progress flush to finish (spin briefly)
        for _ in range(20):
            if not self._flush_in_progress:
                break
            await asyncio.sleep(0.05)

        elapsed_ms = self.compute_elapsed_ms()
        first_token_ms = int((self._first_content_time - self._dispatch_start_time) * 1000) if self._first_content_time else None

        # Close streaming mode if we have a CardKit card
        if self._card_kit.card_id:
            streaming_off_ok = await self.set_streaming_mode(self._card_kit.card_id, False, self._card_kit.sequence + 1)
            logger.info("[CardKit] finalize: set_streaming_mode(False) -> %s", streaming_off_ok)
            self._card_kit.sequence += 2

            # Build final card
            # Priority: explicit tool_use_steps > _tool_use_list > single tool_use_text
            _tool_use_steps = tool_use_steps
            if not _tool_use_steps and self._text.tool_use_list:
                _tool_use_steps = list(self._text.tool_use_list)
            elif not _tool_use_steps and self._text.tool_use_text:
                _tool_use_steps = [{"title": self._text.tool_use_text}]

            # Filter out hidden steps (e.g. clarify) from final card
            if _tool_use_steps:
                _tool_use_steps = [
                    s for s in _tool_use_steps
                    if not _normalize_tool_step(s).get("hidden", False)
                ]

            # Resolve final text: use accumulated streaming content
            _final_text = self._text.accumulated_text or ""

            final_card = self.build_complete_card(
                text=_final_text,
                tool_use_steps=_tool_use_steps,
                tool_use_elapsed_ms=tool_use_elapsed_ms,
                show_tool_use=self.show_tool_use,
                is_error=is_error,
                is_aborted=is_aborted,
                elapsed_ms=elapsed_ms,
                first_token_ms=first_token_ms,
                model_name=model_name,
                token_usage=token_usage,
                context_usage=context_usage,
                iteration_count=iteration_count,
                hourly_usage=hourly_usage,
                balance=balance,
            )

            update_ok = await self.update_card(self._card_kit.card_id, final_card, self._card_kit.sequence)
            logger.info("[CardKit] finalize: update_card -> %s", update_ok)

            if not update_ok:
                # Fallback: update_card failed (e.g. code=300305 element exceeds limit).
                # Card already has stream_content element from streaming phase.
                # Just patch its text content to final text so card shows complete answer.
                _fallback_text = _final_text
                if not is_error and not is_aborted:
                    _fallback_text += "\n\n---\n✨ **已完成**"
                logger.info("[CardKit] finalize: update_card failed, fallback to patch_card_element")
                self._card_kit.sequence += 1
                await self.patch_card_element(
                    self._card_kit.card_id,
                    STREAMING_ELEMENT_ID,
                    {"content": _fallback_text},
                    self._card_kit.sequence
                )

        if self.on_card_finalized:
            await self.on_card_finalized(self._card_kit.message_id, self._card_kit.card_id)

        logger.info("[CardKit] card finalized (elapsed_ms=%s)", elapsed_ms)

    async def abort(self, abort_text: str = "Aborted.") -> None:
        """Abort the streaming card."""
        if self.is_terminal:
            return

        self.transition(CardPhase.ABORTED, "abort", "abort")

        # Cancel any pending deferred flush
        self._cancel_pending_flush()
        self._needs_reflush = False

        elapsed_ms = self.compute_elapsed_ms()

        if self._card_kit.card_id:
            await self.set_streaming_mode(self._card_kit.card_id, False, self._card_kit.sequence + 1)
            self._card_kit.sequence += 2

            abort_card = self.build_complete_card(
                text=abort_text,
                reasoning_text=self._reasoning.accumulated_text,
                reasoning_elapsed_ms=int((time.time() - self._reasoning.start_time) * 1000) if self._reasoning.start_time else None,
                show_tool_use=False,
                is_aborted=True,
                elapsed_ms=elapsed_ms
            )

            await self.update_card(self._card_kit.card_id, abort_card, self._card_kit.sequence)

        if self.on_card_finalized:
            await self.on_card_finalized(self._card_kit.message_id, self._card_kit.card_id)

        logger.info("[CardKit] card aborted")


# =============================================================================
# Convenience Functions
# =============================================================================

async def create_streaming_card(
    client: Any,
    cfg: Dict[str, Any],
    chat_id: str,
    show_tool_use: bool = True,
    reply_to_message_id: Optional[str] = None,
    reply_in_thread: bool = False,
    user_question: str = "",
) -> StreamingCardController:
    """
    Create and initialize a streaming card.

    Returns the controller after the initial card is sent.
    """
    controller = StreamingCardController(
        cfg=cfg,
        chat_id=chat_id,
        client=client,
        show_tool_use=show_tool_use,
        reply_to_message_id=reply_to_message_id,
        reply_in_thread=reply_in_thread,
        user_question=user_question,
    )

    await controller.ensure_card_created()
    return controller


async def send_progress_card(
    client: Any,
    chat_id: str,
    title: str,
    progress_text: str,
    progress_percent: Optional[int] = None,
    status: str = "Processing"
) -> Optional[str]:
    """
    Send a simple progress notification card (non-streaming).

    Returns the message_id on success.
    """
    if not LARK_AVAILABLE:
        return None

    try:
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"content": title, "tag": "plain_text"},
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**Status:** {status}"
                },
                {
                    "tag": "markdown",
                    "content": progress_text
                }
            ]
        }

        if progress_percent is not None:
            bar_length = 20
            filled = int(bar_length * progress_percent / 100)
            bar = "█" * filled + "░" * (bar_length - filled)
            card["elements"].insert(1, {
                "tag": "markdown",
                "content": f"**Progress:** [{bar}] {progress_percent}%"
            })

        content_payload = json.dumps(card, ensure_ascii=False)

        request = (
            CreateMessageRequest.builder()
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .content(content_payload)
                .msg_type("interactive")
                .build()
            )
            .receive_id_type("chat_id")
            .build()
        )

        response = await asyncio.to_thread(client.im.v1.message.create, request)

        if hasattr(response, 'data') and response.data:
            return getattr(response.data, 'message_id', None)

    except Exception as e:
        logger.error("[CardKit] send_progress_card exception: %s", e)

    return None
