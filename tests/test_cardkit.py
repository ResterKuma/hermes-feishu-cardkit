"""
feishu-cardkit 单元测试骨架。
"""

import pytest
from feishu_cardkit import CardBuilder
from feishu_cardkit.markdown import (
    optimize_markdown,
    parse_markdown_table,
    sanitize_text_for_card,
    split_text_and_tables,
)
from feishu_cardkit.components import (
    collapsible_panel,
    column_set,
    markdown_element,
    progress_bar,
    button,
)
from feishu_cardkit.controller import (
    CardPhase,
    StreamingCardController,
    _status_icon,
)


# ── CardBuilder 测试 ────────────────────────────────────────

class TestCardBuilder:
    def test_empty_card(self):
        card = CardBuilder().build()
        assert card["schema"] == "2.0"
        assert "body" in card
        assert card["body"]["elements"] == []

    def test_header(self):
        card = CardBuilder().header("标题", template="blue").build()
        assert card["header"]["title"]["content"] == "标题"
        assert card["header"]["template"] == "blue"

    def test_header_with_subtitle(self):
        card = CardBuilder().header("标题", subtitle="副标题").build()
        assert card["header"]["subtitle"]["content"] == "副标题"

    def test_markdown(self):
        card = CardBuilder().markdown("**粗体**").build()
        el = card["body"]["elements"][0]
        assert el["tag"] == "markdown"
        assert el["content"] == "**粗体**"

    def test_markdown_with_id(self):
        card = CardBuilder().markdown("内容", element_id="md1").build()
        el = card["body"]["elements"][0]
        assert el["element_id"] == "md1"

    def test_hr(self):
        card = CardBuilder().hr().build()
        assert card["body"]["elements"][0]["tag"] == "hr"

    def test_note(self):
        card = CardBuilder().note("备注").build()
        el = card["body"]["elements"][0]
        assert "grey" in el["content"]
        assert el["text_size"] == "notation"

    def test_streaming_config(self):
        card = CardBuilder().streaming_config().build()
        assert card["config"]["streaming_mode"] is True
        assert "streaming_config" in card["config"]

    def test_chaining(self):
        card = (
            CardBuilder()
            .header("H", template="green")
            .markdown("A")
            .hr()
            .markdown("B")
            .build()
        )
        assert len(card["body"]["elements"]) == 3  # hr + 2 markdown


# ── Markdown 测试 ───────────────────────────────────────────

class TestMarkdown:
    def test_parse_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = parse_markdown_table(md)
        assert result is not None
        # 应有表头行 + 1 数据行 = 2 个 column_set
        assert len(result) == 2
        assert result[0]["background_style"] == "grey"  # 表头灰底

    def test_parse_table_empty(self):
        assert parse_markdown_table("") is None
        assert parse_markdown_table("无表格") is None

    def test_optimize_h1_downgrade(self):
        text = "# 标题\n内容"
        result = optimize_markdown(text)
        assert "#### 标题" in result

    def test_optimize_code_block_protection(self):
        text = "# 不降级\n```\n# 代码里的标题\n```\n# 降级"
        result = optimize_markdown(text)
        assert "```" in result  # 代码块保留
        assert "#### 不降级" in result
        assert "#### 降级" in result

    def test_sanitize_table_limit(self):
        tables = ""
        for i in range(5):
            tables += f"| A{i} | B{i} |\n|---|---|\n| {i} | {i} |\n\n"
        result = sanitize_text_for_card(tables, table_limit=3)
        # 超过 3 个的表格应被包裹为代码块
        assert result.count("```") >= 2  # 至少 1 个被包裹

    def test_split_text_and_tables(self):
        text = "前面文本\n| A | B |\n|---|---|\n| 1 | 2 |\n后面文本"
        segments = split_text_and_tables(text)
        types = [s["type"] for s in segments]
        assert "text" in types
        assert "table" in types


# ── 组件工厂测试 ────────────────────────────────────────────

class TestComponents:
    def test_markdown_element(self):
        el = markdown_element("内容")
        assert el["tag"] == "markdown"
        assert el["content"] == "内容"

    def test_progress_bar(self):
        el = progress_bar(50, bar_length=10)
        assert el["tag"] == "markdown"
        assert "50%" in el["content"]
        assert "█" in el["content"]

    def test_button_with_url(self):
        el = button("打开", url="https://example.com")
        assert el["tag"] == "button"
        assert el["url"] == "https://example.com"

    def test_column_set(self):
        cols = [{"weight": 1, "elements": []}]
        el = column_set(cols)
        assert el["tag"] == "column_set"
        assert len(el["columns"]) == 1


# ── Controller 测试 ────────────────────────────────────────

class TestController:
    def test_initial_state(self):
        ctrl = StreamingCardController()
        assert ctrl.phase == CardPhase.IDLE
        assert ctrl.card_id is None
        assert ctrl.is_terminal is False

    def test_transition_idle_to_creating(self):
        ctrl = StreamingCardController()
        assert ctrl._transition(CardPhase.CREATING) is True
        assert ctrl.phase == CardPhase.CREATING

    def test_invalid_transition(self):
        ctrl = StreamingCardController()
        assert ctrl._transition(CardPhase.COMPLETED) is False
        assert ctrl.phase == CardPhase.IDLE

    def test_status_icon(self):
        assert _status_icon("completed") == "✅"
        assert _status_icon("running") == "🔄"
        assert _status_icon("failed") == "❌"
        assert _status_icon("pending") == "⏳"
