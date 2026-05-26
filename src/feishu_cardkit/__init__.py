"""
feishu-cardkit — 飞书 CardKit Python SDK

流式卡片、JSON 2.0 构建、Markdown 表格渲染，一站式搞定。
"""

from .builder import CardBuilder
from .controller import (
    CardPhase,
    StreamingCardController,
    TurnStep,
    Turn,
    TextState,
    ReasoningState,
    create_streaming_card,
    send_progress_card,
)
from .markdown import (
    parse_markdown_table,
    split_text_and_tables,
    optimize_markdown,
    sanitize_text_for_card,
)
from .components import (
    column_set,
    collapsible_panel,
    markdown_element,
    hr_element,
    img_element,
    overflow_menu,
)
from .api import CardKitAPI

__version__ = "0.1.0"
__all__ = [
    # 构建器
    "CardBuilder",
    # 流式控制器
    "CardPhase",
    "StreamingCardController",
    "create_streaming_card",
    "send_progress_card",
    # Markdown 工具
    "parse_markdown_table",
    "split_text_and_tables",
    "optimize_markdown",
    "sanitize_text_for_card",
    # 组件工厂
    "column_set",
    "collapsible_panel",
    "markdown_element",
    "hr_element",
    "img_element",
    "overflow_menu",
    # API 封装
    "CardKitAPI",
]
