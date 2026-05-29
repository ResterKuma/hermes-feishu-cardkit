"""
CardKit streaming consumer for Feishu.

Provides streaming card support via the CardKit API, enabling
typewriter-style updates for AI responses.

This is an alternative to the standard StreamConsumer when
CardKit streaming is enabled.
"""

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
    )
    from lark_oapi.api.cardkit.v1.model import (
        CreateCardRequest,
        CreateCardRequestBody,
        ContentCardElementRequest,
        ContentCardElementRequestBody,
        UpdateCardRequest,
        UpdateCardRequestBody,
        SettingsCardRequest,
        SettingsCardRequestBody,
    )
    LARK_AVAILABLE = True
except ImportError:
    LARK_AVAILABLE = False
    lark = None

from gateway.platforms.feishu_cardkit import (
    StreamingCardController,
    STREAMING_ELEMENT_ID,
)

logger = logging.getLogger("gateway.cardkit_stream_consumer")


def _is_cjk_char(ch: str) -> bool:
    """Check if a single character is CJK (Chinese/Japanese/Korean)."""
    if not ch:
        return False
    cp = ord(ch[0])
    return (
        0x4E00 <= cp <= 0x9FFF or   # CJK Unified Ideographs
        0x3400 <= cp <= 0x4DBF or   # CJK Extension A
        0x20000 <= cp <= 0x2A6DF or # CJK Extension B
        0xF900 <= cp <= 0xFAFF or   # CJK Compatibility Ideographs
        0x3000 <= cp <= 0x303F or   # CJK Symbols and Punctuation
        0x3040 <= cp <= 0x309F or   # Hiragana
        0x30A0 <= cp <= 0x30FF or   # Katakana
        0xAC00 <= cp <= 0xD7AF or   # Hangul Syllables
        0xFF01 <= cp <= 0xFF60      # Fullwidth punctuation
    )


def _smart_append_reasoning(existing: str, new_text: str) -> str:
    """Append new_text to existing, adding space only between non-CJK tokens.

    CJK characters are concatenated directly (no space between Chinese chars).
    English/Latin tokens still get spaces as before.
    """
    if not existing:
        return new_text
    if not new_text:
        return existing
    last_ch = existing[-1]
    first_ch = new_text[0]
    # If either boundary char is CJK, concatenate without space
    if _is_cjk_char(last_ch) or _is_cjk_char(first_ch):
        return existing + new_text
    # If either side already has whitespace, concatenate directly
    if last_ch.isspace() or first_ch.isspace():
        return existing + new_text
    # Otherwise add a space (for English/Latin tokens)
    return existing + " " + new_text


@dataclass
class CardKitStreamConsumerConfig:
    """Configuration for CardKit streaming."""
    cursor: str = " ▉"
    buffer_threshold: int = 10  # Chars before forcing an update
    show_tool_use: bool = True


class CardKitStreamConsumer:
    """
    CardKit-based streaming consumer for Feishu.

    Provides the same interface as GatewayStreamConsumer but uses
    CardKit streaming cards instead of progressive edits.

    Key differences from standard StreamConsumer:
    - Creates a CardKit card entity, sends it, then streams content updates
    - Finalizes with the complete card content
    - Falls back to standard send if CardKit fails
    """

    _OPEN_THINK_TAGS = (
        "<REASONING_SCRATCHPAD>", "<reasoning>",
        "<think>", "</think>", "<thought>", "</thought>",
        "<Think>", "</Think>", "<THINKING>", "</THINKING>",
        "<ANT THINKING>", "</ANT THINKING>",
    )
    _CLOSE_THINK_TAGS = (
        "</REASONING_SCRATCHPAD>", "</reasoning>",
        "</think>", "</think>", "</thought>", "</thought>",
        "</Think>", "</Think>", "</THINKING>", "</THINKING>",
        "</ANT THINKING>", "</ANT THINKING>",
    )

    def __init__(
        self,
        adapter: Any,
        chat_id: str,
        config: Optional[CardKitStreamConsumerConfig] = None,
        metadata: Optional[dict] = None,
        interrupt_prefix: Optional[str] = None,
        user_question: str = "",
    ):
        self.adapter = adapter
        self.chat_id = chat_id
        self.cfg = config or CardKitStreamConsumerConfig()
        self.metadata = metadata or {}
        self.user_question = user_question
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._finished = False

        # CardKit controller (created when first delta arrives)
        self._controller: Optional[StreamingCardController] = None
        self._controller_ready = asyncio.Event()
        self._controller_loop: Optional[asyncio.AbstractEventLoop] = None

        # Interrupt prefix: content from previous interrupted card to show at top
        self._interrupt_prefix = interrupt_prefix

        # Text accumulation
        self._accumulated = ""
        self._streaming_prefix = ""  # Text from previous reply rounds (boundary detection)
        self._in_think_block = False
        self._think_buffer = ""
        self._last_partial = ""
        self._tool_use_text = ""
        self._tool_use_list = []  # Accumulated tool use steps for collapsible panel
        self._reasoning_text = ""

        # Turn tracking
        self._current_turn_number = 0    # Incremented on each new agent reply round
        self._current_turn_tools = []    # Tool steps for the current turn
        self._current_turn_reasoning = ""  # Reasoning text for the current turn
        self._turns_list = []            # List of completed turns (dicts)
        self._last_tool_turn = 0         # Turn number when last tool was added
        self._between_tool_calls = False # True when on_delta received text between tool calls

        # Tracking
        self._message_id: Optional[str] = None
        self._card_id: Optional[str] = None
        self._already_sent = False
        self._pending_final_text: Optional[str] = None
        self._final_response_sent = False  # Initially False; set to False again when consumer returns control to gateway

    @property
    def already_sent(self) -> bool:
        """Whether a message has been sent."""
        return self._already_sent

    def final_response_sent(self) -> bool:
        """Whether the final response has been sent."""
        return self._final_response_sent

    def on_segment_break(self) -> None:
        """Handle a segment break (tool call boundary)."""
        pass

    def on_tool_use(self, tool_name: str, preview: str = None) -> None:
        """
        Handle tool use/progress notification.

        Called synchronously from the agent's worker thread.
        Ignores _finished flag - tool_use should always be shown if available.

        Turn boundary: a new Turn starts each time on_tool_use is called
        and the previous turn already had tool calls in it AND the agent
        had time to produce text between tool calls (indicated by
        _between_tool_calls flag set by on_delta).
        """
        logger.info("[CardKit] on_tool_use called: tool=%s preview=%s", tool_name, preview)

        tool_text = preview or tool_name

        # Always save to instance variable (used by _ensure_controller)
        self._tool_use_text = tool_text

        # Turn boundary logic:
        # If we already have tools in current turn AND the agent produced
        # text between tool calls (on_delta set _between_tool_calls=True),
        # then this is a new agent round -> start a new turn.
        if self._current_turn_tools and self._between_tool_calls:
            self._start_new_turn()
        elif self._current_turn_number == 0:
            # First tool call ever
            self._current_turn_number = 1
            self._current_turn_tools = []

        self._last_tool_turn = self._current_turn_number
        self._between_tool_calls = False  # Reset flag

        # Append this step to current turn
        step_entry = {
            "name": tool_name,
            "title": tool_text,
            "summary": tool_text if tool_text != tool_name else "",
            "status": "completed",
        }
        self._tool_use_list.append(step_entry)
        self._current_turn_tools.append(step_entry)
        logger.info("[CardKit] on_tool_use: turn %d, step #%d: %s",
                     self._current_turn_number, len(self._current_turn_tools), tool_text)

        # Sync to controller's TextState (both flat list + turns)
        if self._controller:
            try:
                if self._controller._text:
                    self._controller._text.tool_use_text = tool_text
                    self._controller._text.tool_use_list = list(self._tool_use_list)
                    # Sync turns
                    self._sync_turns_to_controller()
                    logger.info("[CardKit] on_tool_use: synced %d steps, %d turns to controller",
                                len(self._tool_use_list), len(self._turns_list))
            except Exception as e:
                logger.warning("[CardKit] on_tool_use failed to update controller: %s", e)

        # Always put in queue for processing - queue ensures ordering
        logger.info("[CardKit] on_tool_use: putting [TOOL_USE]%s[/TOOL_USE] into queue", tool_text)
        self._queue.put(f"[TOOL_USE]{tool_text}[/TOOL_USE]")

    def _finalize_current_turn(self) -> None:
        """Finalize the current turn and add it to turns_list."""
        if self._current_turn_number > 0 and self._current_turn_tools:
            turn = {
                "turn_number": self._current_turn_number,
                "title": self._current_turn_tools[0].get("title", ""),
                "steps": list(self._current_turn_tools),
                "status": "completed",
                "reasoning_text": self._current_turn_reasoning,
            }
            self._turns_list.append(turn)
            logger.info("[CardKit] Finalized turn %d with %d steps, reasoning=%d chars",
                        self._current_turn_number, len(self._current_turn_tools),
                        len(self._current_turn_reasoning))
            self._current_turn_tools = []
            self._current_turn_reasoning = ""
            # Clear controller's reasoning so next turn starts fresh
            if self._controller and self._controller._reasoning:
                self._controller._reasoning.accumulated_text = ""

    def _start_new_turn(self) -> None:
        """Start a new turn (called on reply boundary detection)."""
        # Finalize current turn first
        if self._current_turn_tools:
            self._finalize_current_turn()
        self._current_turn_number += 1
        self._current_turn_tools = []
        logger.info("[CardKit] Started new turn %d", self._current_turn_number)

    def _sync_turns_to_controller(self) -> None:
        """Sync consumer turn state to controller's TextState.turns."""
        if not self._controller or not self._controller._text:
            return
        from gateway.platforms.feishu_cardkit import Turn, TurnStep
        # Build turns from turns_list + current in-progress turn
        all_turns = []
        for t in self._turns_list:
            steps = [TurnStep(name=s.get("name",""), title=s.get("title",""),
                              summary=s.get("summary",""),
                              status=s.get("status","completed")) for s in t["steps"]]
            all_turns.append(Turn(turn_number=t["turn_number"], title=t.get("title",""),
                                  steps=steps, status=t.get("status","completed"),
                                  reasoning_text=t.get("reasoning_text", "")))
        # Add current in-progress turn
        if self._current_turn_tools:
            steps = [TurnStep(name=s.get("name",""), title=s.get("title",""),
                              summary=s.get("summary",""),
                              status=s.get("status","completed")) for s in self._current_turn_tools]
            all_turns.append(Turn(turn_number=self._current_turn_number,
                                  title=self._current_turn_tools[0].get("title",""),
                                  steps=steps, status="running",
                                  reasoning_text=self._current_turn_reasoning))
        self._controller._text.turns = all_turns

    _REASONING_FLUSH_CHARS = 50  # Batch card updates every N chars

    def on_reasoning(self, reasoning_text: str) -> None:
        """Handle reasoning/thinking content from the agent.

        Accumulates reasoning across tokens and displays it as the main
        card text. Updates the card every _REASONING_FLUSH_CHARS characters
        to avoid per-token card update overhead.
        """
        if self._finished or not reasoning_text:
            return

        logger.debug("[CardKit] on_reasoning: len=%d, preview=%s",
                     len(reasoning_text), reasoning_text[:80])

        # Accumulate reasoning for this turn (reasoning_text is incremental)
        prev_len = len(self._current_turn_reasoning or "")
        self._current_turn_reasoning = (self._current_turn_reasoning or "") + reasoning_text
        new_len = len(self._current_turn_reasoning)

        # Sync to controller state on every token (cheap, no API call)
        if self._controller:
            try:
                self._controller._reasoning.accumulated_text = self._current_turn_reasoning
                self._controller._reasoning.is_phase = True
                if not self._controller._reasoning.start_time:
                    self._controller._reasoning.start_time = time.time()
                self._sync_turns_to_controller()
            except Exception as e:
                logger.warning("[CardKit] on_reasoning controller sync failed: %s", e)

        # Only trigger card update when we've accumulated enough new chars
        flush_threshold = self._REASONING_FLUSH_CHARS
        if (new_len - prev_len < flush_threshold and new_len >= prev_len + 1
                and new_len % flush_threshold >= (new_len - prev_len)):
            # Haven't crossed a flush boundary yet — skip card update
            return

        # Flush: push reasoning into queue for consumer loop to handle.
        # The consumer run loop throttles card updates to ~0.5s intervals,
        # providing smooth incremental rendering. Do NOT call update_content
        # directly here — that would bypass throttling and cause full-card
        # re-renders on every 50-char flush.
        self._queue.put(f"[REASONING]{reasoning_text}[/REASONING]")

    def _capture_reasoning(self, think_text: str) -> None:
        """Internal: store reasoning text captured from think blocks."""
        if not think_text:
            return
        self._current_turn_reasoning = think_text

    def on_delta(self, text: str) -> None:
        """
        Handle a stream delta from the agent.

        This is called synchronously from the agent's worker thread.
        NOTE: The agent fires stream_delta_callback(None) before each tool
        execution to flush the display.  We must NOT pass None into the
        queue — the consumer loop treats None as a sentinel (end-of-stream).
        Only finish() should produce the sentinel.
        """
        if self._finished:
            return
        if text is None:
            # Agent's inter-turn flush signal — ignore it.
            # Only finish() may send the true sentinel.
            return
        self._between_tool_calls = True  # Mark that text arrived between tool calls
        self._queue.put(text)

    def finish(self) -> None:
        """Signal that streaming is complete."""
        self._finished = True
        self._queue.put(None)  # Sentinel

    def wait_for_done(self, timeout: float = 30.0) -> bool:
        """Wait for the consumer thread to finish."""
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        return True

    def get_pending_final_text(self) -> Optional[str]:
        """Get any pending text for the final message."""
        return self._pending_final_text if self._finished else None

    def _process_text(self, text: str) -> None:
        """Process incoming text, extracting tool_use markers only.

        Reasoning/think blocks are silently discarded (no display).
        Only [TOOL_USE] markers and plain text are preserved.
        """
        logger.info("[CardKit] _process_text input: len=%d, repr=%s", len(text), repr(text[:80]))
        buf = self._think_buffer + text
        self._think_buffer = ""

        # Tag patterns for tool_use markers only
        tool_open = "[TOOL_USE]"
        tool_close = "[/TOOL_USE]"

        while buf:
            # Handle think blocks — skip content silently
            if self._in_think_block:
                best_idx = -1
                best_len = 0
                for tag in self._CLOSE_THINK_TAGS:
                    idx = buf.find(tag)
                    if idx != -1 and (best_idx == -1 or idx < best_idx):
                        best_idx = idx
                        best_len = len(tag)

                if best_len:
                    self._in_think_block = False
                    # Discard think block content
                    buf = buf[best_idx + best_len:]
                else:
                    max_tag = max(len(t) for t in self._CLOSE_THINK_TAGS)
                    self._think_buffer = buf[-max_tag:] if len(buf) > max_tag else buf
                    break

            # Handle [TOOL_USE] markers
            tool_idx = buf.find(tool_open)
            if tool_idx != -1:
                tool_end = buf.find(tool_close, tool_idx)
                if tool_end != -1:
                    tool_content = buf[tool_idx + len(tool_open):tool_end]
                    logger.info("[CardKit] _process_text: extracted tool_use_text=%s", tool_content)
                    self._tool_use_text = tool_content
                    if self._controller and self._controller._text:
                        self._controller._text.tool_use_text = tool_content
                    buf = buf[tool_end + len(tool_close):]
                    continue
                else:
                    tool_content = buf[tool_idx + len(tool_open):]
                    self._tool_use_text = tool_content
                    if self._controller and self._controller._text:
                        self._controller._text.tool_use_text = tool_content
                    buf = ""
                    continue

            # Skip [REASONING] markers entirely
            reason_open = "[REASONING]"
            reason_close = "[/REASONING]"
            reason_idx = buf.find(reason_open)
            if reason_idx != -1:
                reason_end = buf.find(reason_close, reason_idx)
                if reason_end != -1:
                    buf = buf[reason_end + len(reason_close):]
                    continue
                else:
                    buf = ""
                    continue

            # Handle think open tags — enter think block mode (discard content)
            best_idx = -1
            best_len = 0
            for tag in self._OPEN_THINK_TAGS:
                idx = buf.find(tag)
                if idx != -1 and (best_idx == -1 or idx < best_idx):
                    best_idx = idx
                    best_len = len(tag)

            if best_len:
                # Output text before the tag
                if best_idx > 0:
                    self._accumulated += buf[:best_idx]
                self._in_think_block = True
                buf = buf[best_idx + best_len:]
            else:
                # No more tags, output everything
                self._accumulated += buf
                break

    async def _ensure_controller(self) -> bool:
        """Ensure the CardKit card is created and ready."""
        if self._controller is not None:
            return True

        if not LARK_AVAILABLE:
            logger.warning("[CardKit] lark_oapi not available")
            return False

        try:
            # Create streaming card
            from gateway.platforms.feishu_cardkit import create_streaming_card

            cfg = {
                "app_id": self.adapter._app_id,
                "app_secret": self.adapter._app_secret,
            }

            controller = await create_streaming_card(
                client=self.adapter._client,
                cfg=cfg,
                chat_id=self.chat_id,
                show_tool_use=self.cfg.show_tool_use,
                reply_to_message_id=self.metadata.get("reply_to_message_id"),
                reply_in_thread=self.metadata.get("reply_in_thread", False),
                user_question=self.user_question,
            )

            if controller and controller.card_message_id:
                self._controller = controller
                self._message_id = controller.card_message_id
                self._card_id = controller._card_kit.card_id if controller._card_kit else None
                self._already_sent = True

                # Apply pending tool_use_text and reasoning_text to the new controller
                if self._tool_use_text and controller._text:
                    controller._text.tool_use_text = self._tool_use_text
                    controller._text.tool_use_list = list(self._tool_use_list)
                    logger.info("[CardKit] Card created: applied pending tool_use_text=%s, steps=%d",
                                self._tool_use_text, len(self._tool_use_list))
                if self._reasoning_text and controller._reasoning:
                    controller._reasoning.accumulated_text = self._reasoning_text
                    controller._reasoning.is_phase = True
                    logger.info("[CardKit] Card created: applied pending reasoning_text=%s", self._reasoning_text)

                logger.info("[CardKit] Card created: message_id=%s", self._message_id)

                # Inject interrupt prefix if present (content from previous interrupted card)
                if self._interrupt_prefix and self._controller and self._controller._text:
                    try:
                        prefix_md = (
                            "📋 **上次任务进度：**\n"
                            + self._interrupt_prefix.strip()
                            + "\n\n---\n"
                        )
                        # Pre-populate accumulated text so streaming starts after the prefix
                        self._accumulated = prefix_md
                        self._controller._text.accumulated_text = prefix_md
                        await self._controller._flush_update()
                        logger.info("[CardKit] Injected interrupt prefix (%d chars)", len(prefix_md))
                    except Exception as _pe:
                        logger.debug("[CardKit] Failed to inject interrupt prefix: %s", _pe)

                # Register card as actively streaming (for orphan cleanup on restart)
                if self._card_id and hasattr(self.adapter, 'register_streaming_card'):
                    self.adapter.register_streaming_card(self._card_id)
                # Register controller reference for graceful shutdown finalize
                if self._card_id and self._controller and hasattr(self.adapter, 'register_streaming_controller'):
                    self.adapter.register_streaming_controller(self._card_id, self._controller)

                return True

        except Exception as e:
            logger.error("[CardKit] Failed to create card: %s", e)

        return False

    async def _stream_update(self, text: str) -> bool:
        """Send a streaming content update with optional reasoning hint."""
        logger.info("[CardKit] _stream_update called: text_len=%d, controller=%s, card_id=%s",
                    len(text), self._controller is not None,
                    self._controller._card_kit.card_id if self._controller and self._controller._card_kit else None)
        if not self._controller or not self._controller._card_kit.card_id:
            logger.warning("[CardKit] _stream_update: no controller or card_id")
            return False

        try:
            # Display text: when formal text arrives it replaces reasoning
            display = text or ""

            # Get tool_use_text from controller's state
            tool_use_text = self._controller._text.tool_use_text if self._controller._text else ""
            success = await self._controller.update_content(
                text=display,
                tool_use_text=tool_use_text,
            )
            logger.info("[CardKit] _stream_update: update_content returned %s", success)
            return success
        except Exception as e:
            logger.error("[CardKit] stream update failed: %s", e)
            return False

    async def _direct_update_tool_use(self) -> bool:
        """Directly update the card with current tool_use_text (bypasses queue)."""
        if not self._controller or not self._controller._card_kit.card_id:
            return False
        try:
            tool_use_text = self._controller._text.tool_use_text if self._controller._text else ""
            reasoning_text = self._controller._reasoning.accumulated_text if self._controller._reasoning else ""
            text_to_show = self._accumulated or ""
            # Build display text similar to _flush_update
            parts = []
            if tool_use_text:
                parts.append(f"🛠️ **{tool_use_text}**")
            if text_to_show:
                parts.append(text_to_show)
            if reasoning_text:
                parts.append(f"💭 **{reasoning_text}**")
            display_text = "\n\n".join(parts)
            if display_text:
                await self._controller.update_content(text=text_to_show)
            return True
        except Exception as e:
            logger.warning("[CardKit] _direct_update_tool_use failed: %s", e)
            return False

    async def _finalize(self, final_text: str) -> bool:
        """Finalize the card with complete content."""
        logger.info("[CardKit] _finalize CALLED: controller=%s, card_id=%s, text_len=%d",
            self._controller is not None,
            self._controller._card_kit.card_id if self._controller and self._controller._card_kit else None,
            len(final_text)
        )
        if not self._controller:
            return False

        try:
            await self._controller.finalize(
                completed_text=final_text,
                reasoning_text=None,
            )
            logger.info("[CardKit] Card finalized")
            return True
        except Exception as e:
            logger.error("[CardKit] finalize failed: %s", e)
            return False

    async def run(self) -> None:
        """
        Run the consumer loop.

        This processes deltas from the queue and sends streaming updates.
        Should be called as an async task.
        """
        self._running = True
        self._controller_loop = asyncio.get_event_loop()
        logger.info("[CardKit] Consumer run started")

        # Eagerly create a placeholder card so the user sees immediate feedback
        # ("思考中…") instead of waiting 10-20s for the LLM's first token.
        if not self._controller:
            logger.info("[CardKit] Consumer: creating eager placeholder card")
            await self._ensure_controller()

        # Track last activity time for timeout
        last_activity = time.time()
        BASE_IDLE_TIMEOUT = 120.0       # base idle timeout (seconds)
        TOOL_ACTIVE_TIMEOUT = 600.0     # extended timeout while tool is executing
        _first_ping_delay = 3.0         # first "still working" ping after 3s
        _ping_interval = 10.0           # subsequent pings every 10s
        _last_ping = time.time()
        _pinged_once = False
        _tool_active = False            # True when tool execution is in progress
        _last_reasoning_flush = 0.0     # throttle reasoning-only card updates

        while self._running:
            try:
                # Non-blocking queue check — never block the event loop!
                try:
                    text = self._queue.get_nowait()
                    last_activity = time.time()
                    _last_ping = time.time()   # reset ping timer on activity
                    _pinged_once = False       # reset for next idle period
                    # Detect tool activity from queue markers
                    if "[TOOL_USE]" in (text or ""):
                        _tool_active = True
                except queue.Empty:
                    effective_timeout = TOOL_ACTIVE_TIMEOUT if _tool_active else BASE_IDLE_TIMEOUT
                    idle_secs = time.time() - last_activity
                    if idle_secs > effective_timeout:
                        logger.info("[CardKit] Consumer idle timeout (%.1fs, tool_active=%s), calling finish",
                                    idle_secs, _tool_active)
                        self.finish()
                    else:
                        # Ping card to show it's still working
                        ping_delay = _first_ping_delay if not _pinged_once else _ping_interval
                        since_ping = time.time() - _last_ping
                        if since_ping >= ping_delay:
                            _last_ping = time.time()
                            _pinged_once = True
                            if self._controller and self._controller._card_kit.card_id:
                                try:
                                    # Flush panel updates (tool steps, reasoning)
                                    # without modifying text content
                                    await self._controller._flush_update()
                                except Exception:
                                    pass
                    await asyncio.sleep(0.05)  # Yield to event loop
                    continue

                if text is None:
                    # Sentinel - streaming complete
                    # Finalize any in-progress turn
                    if self._current_turn_tools:
                        self._finalize_current_turn()
                        self._sync_turns_to_controller()
                    # First, drain ALL remaining items without processing (they may contain [TOOL_USE] markers)
                    remaining_items = []
                    logger.info("[CardKit] Consumer received sentinel (None), draining remaining queue items")
                    while True:
                        try:
                            remaining = self._queue.get_nowait()
                            if remaining is None:
                                break
                            logger.info("[CardKit] Consumer draining: len=%d", len(remaining))
                            remaining_items.append(remaining)
                        except queue.Empty:
                            break
                    logger.info("[CardKit] Consumer drain complete, collected %d items", len(remaining_items))

                    # Process remaining items to extract tool_use/reasoning
                    for item in remaining_items:
                        self._process_text(item)

                    # Now check what we have
                    # Note: _process_text stores tool_use_text in self._tool_use_text and reasoning_text in self._reasoning_text
                    tool_use_text = self._controller._text.tool_use_text if self._controller and self._controller._text else self._tool_use_text
                    reasoning_text = self._controller._reasoning.accumulated_text if self._controller and self._controller._reasoning else self._reasoning_text

                    if (self._accumulated or tool_use_text or reasoning_text):
                        if not self._controller:
                            # No controller yet - create one now since we have tool_use/reasoning to show
                            logger.info("[CardKit] Consumer: need card for tool_use/reasoning, creating now")
                            if not await self._ensure_controller():
                                logger.warning("[CardKit] Failed to create card for tool_use")
                                break
                        if self._controller:
                            logger.info("[CardKit] Consumer: sending final update after drain, accumulated_len=%d, tool_use_len=%d", len(self._accumulated), len(tool_use_text))
                            await self._stream_update(self._accumulated)

                    # Wait for a period to capture any late-arriving tool_use events
                    # (subagent callbacks may arrive after main stream completes)
                    # Keep waiting until queue is empty for up to 30 seconds
                    logger.info("[CardKit] Consumer: waiting for late tool_use events (up to 30s)...")
                    wait_start = asyncio.get_event_loop().time()
                    consecutive_empty = 0
                    while asyncio.get_event_loop().time() - wait_start < 30.0:
                        try:
                            remaining = self._queue.get_nowait()
                            if remaining is None:
                                # Another sentinel - stop waiting
                                break
                            consecutive_empty = 0
                            logger.info("[CardKit] Consumer: got late event, processing: len=%d", len(remaining))
                            self._process_text(remaining)
                            # Get tool_use_text and reasoning_text from either controller or instance variables
                            tool_use_text = self._controller._text.tool_use_text if self._controller and self._controller._text else self._tool_use_text
                            reasoning_text = self._controller._reasoning.accumulated_text if self._controller and self._controller._reasoning else self._reasoning_text
                            # If we have content but no controller, create one now
                            if (tool_use_text or reasoning_text) and not self._controller:
                                logger.info("[CardKit] Consumer: creating controller for late event")
                                if not await self._ensure_controller():
                                    logger.warning("[CardKit] Failed to create controller for late event")
                                    continue
                            # Update card with new tool_use/reasoning directly via _flush_update
                            # (update_content may refuse if in terminal state)
                            if self._controller and self._controller._card_kit.card_id:
                                if tool_use_text or reasoning_text:
                                    # Controller's _flush_update has its own mutex + throttle,
                                    # so safe to call directly here for late-arriving events
                                    logger.info("[CardKit] Late event: calling _flush_update directly")
                                    await self._controller._flush_update()
                        except queue.Empty:
                            consecutive_empty += 1
                            # If queue empty for 3 consecutive checks (3s), we're likely done
                            if consecutive_empty >= 3:
                                break
                            await asyncio.sleep(1.0)  # Yield to event loop while waiting
                            continue
                    logger.info("[CardKit] Consumer: late wait period complete")
                    # Save pending text and return control to gateway
                    # Do NOT self-finalize - let gateway decide when to finalize
                    self._pending_final_text = self._accumulated or ""
                    self._final_response_sent = False
                    self._running = False
                    logger.info("[CardKit] Consumer finished (returning control to gateway)")
                    return

                logger.info("[CardKit] Consumer got text: len=%d, accumulated_len=%d", len(text), len(self._accumulated))

                # Non-tool text arrived — tool execution likely finished
                _tool_active = False

                # Quick check: pure reasoning tokens
                _is_pure_reasoning = text.startswith("[REASONING]") and text.endswith("[/REASONING]")

                # Process text (filter think blocks)
                self._process_text(text)

                # For pure reasoning tokens, still update the card so the
                # reasoning hint is visible.  Throttle to avoid excessive
                # API calls — only update every ~0.5s worth of reasoning.
                if _is_pure_reasoning:
                    now = time.time()
                    if now - _last_reasoning_flush >= 0.5:
                        _last_reasoning_flush = now
                        if self._controller and self._controller._card_kit.card_id:
                            reasoning_text = self._controller._reasoning.accumulated_text if self._controller._reasoning else ""
                            tool_use_text = self._controller._text.tool_use_text if self._controller._text else ""
                            if reasoning_text or tool_use_text:
                                await self._controller._flush_update()
                    continue

                # Check if we need to create card
                if not self._controller and self._accumulated:
                    logger.info("[CardKit] Consumer: need card, accumulated_len=%d", len(self._accumulated))
                    if not await self._ensure_controller():
                        logger.warning("[CardKit] Failed to create card, falling back")
                        break

                # Send streaming update if card is ready
                # Check if we have content to display (text OR tool_use OR reasoning)
                tool_use_text = self._controller._text.tool_use_text if self._controller and self._controller._text else ""
                reasoning_text = self._controller._reasoning.accumulated_text if self._controller and self._controller._reasoning else ""
                has_display_content = self._accumulated or tool_use_text or reasoning_text

                logger.info("[CardKit] Consumer: check stream_update - controller=%s, accumulated_len=%d, tool_use=%s, reasoning=%s, threshold=%d",
                           self._controller is not None, len(self._accumulated), len(tool_use_text), len(reasoning_text),
                           self.cfg.buffer_threshold)
                if self._controller and has_display_content:
                    # Throttle updates unless we have tool_use or reasoning content
                    if len(self._accumulated) >= self.cfg.buffer_threshold or tool_use_text or reasoning_text:
                        logger.info("[CardKit] Consumer: calling _stream_update, accumulated_len=%d", len(self._accumulated))
                        await self._stream_update(self._accumulated)
                    else:
                        logger.info("[CardKit] Consumer: skipping _stream_update, accumulated_len=%d < threshold=%d", len(self._accumulated), self.cfg.buffer_threshold)

            except Exception as e:
                logger.error("[CardKit] Consumer error: %s", e)
                break

        self._running = False
        logger.info("[CardKit] Consumer finished")


def create_cardkit_consumer(
    adapter: Any,
    chat_id: str,
    config: Optional[CardKitStreamConsumerConfig] = None,
    metadata: Optional[dict] = None,
) -> CardKitStreamConsumer:
    """
    Factory function to create a CardKit streaming consumer.

    Returns a consumer that provides the same interface as GatewayStreamConsumer
    but uses CardKit for streaming.
    """
    return CardKitStreamConsumer(
        adapter=adapter,
        chat_id=chat_id,
        config=config,
        metadata=metadata,
    )
