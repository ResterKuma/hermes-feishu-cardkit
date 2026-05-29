"""feishu-cardkit v2 — Hermes Agent 专用飞书 CardKit 流式卡片插件

基于飞书 CardKit API 的流式卡片控制器，提供 AI 回复打字机效果、
工具调用折叠面板、进度通知等完整功能。

直接替代 Hermes Agent 的 gateway/platforms/feishu_cardkit.py + gateway/cardkit_stream_consumer.py。
"""

from .feishu_cardkit import (
    # 核心控制器
    StreamingCardController,
    # 状态 & 数据类
    CardPhase,
    CardKitState,
    TurnStep,
    Turn,
    TextState,
    ReasoningState,
    # 便捷函数
    create_streaming_card,
    send_progress_card,
    # 消息不可用检测
    mark_message_unavailable,
    is_message_unavailable,
    check_api_error_unavailable,
    # 常量
    STREAMING_ELEMENT_ID,
    FEISHU_CARD_TABLE_LIMIT,
    CARD_ERROR_RATE_LIMITED,
    CARD_ERROR_CONTENT_FAILED,
    CARD_ERROR_ELEMENT_LIMIT,
)

from .cardkit_stream_consumer import CardKitStreamConsumer, CardKitStreamConsumerConfig

__version__ = "2.0.0"
__all__ = [
    "StreamingCardController",
    "CardKitStreamConsumer",
    "CardKitStreamConsumerConfig",
    "create_streaming_card",
    "send_progress_card",
    "CardPhase",
    "CardKitState",
    "TurnStep",
    "Turn",
    "TextState",
    "ReasoningState",
    "mark_message_unavailable",
    "is_message_unavailable",
    "check_api_error_unavailable",
    "STREAMING_ELEMENT_ID",
    "FEISHU_CARD_TABLE_LIMIT",
    "CARD_ERROR_RATE_LIMITED",
    "CARD_ERROR_CONTENT_FAILED",
    "CARD_ERROR_ELEMENT_LIMIT",
]
