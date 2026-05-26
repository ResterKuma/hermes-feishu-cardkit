"""
Card JSON 2.0 声明式构建器。

提供链式调用 API，轻松构建飞书 CardKit 卡片。

示例::

    card = (
        CardBuilder()
        .header("标题", template="blue")
        .markdown("**粗体文本**")
        .table_from_markdown("| A | B |\\n|---|---|\\n| 1 | 2 |")
        .build()
    )
"""

from typing import Any, Dict, List, Optional

from .markdown import parse_markdown_table, split_text_and_tables


class CardBuilder:
    """飞书 Card JSON 2.0 声明式构建器。

    支持链式调用，按需添加组件，最终调用 :meth:`build` 生成完整的
    Card JSON 2.0 字典，可直接用于 CardKit API。
    """

    def __init__(self) -> None:
        self._header: Optional[Dict[str, Any]] = None
        self._elements: List[Dict[str, Any]] = []
        self._config: Dict[str, Any] = {
            "update_multi": True,
            "enable_forward": True,
            "width_mode": "fill",
        }
        self._card_link: Optional[Dict[str, str]] = None

    # ── Header ───────────────────────────────────────────────

    def header(
        self,
        title: str,
        *,
        subtitle: Optional[str] = None,
        template: str = "default",
        icon_key: Optional[str] = None,
    ) -> "CardBuilder":
        """设置卡片头部。

        Args:
            title: 卡片标题。
            subtitle: 卡片副标题（可选）。
            template: 头部颜色模板，可选值：
                ``blue``, ``green``, ``red``, ``orange``, ``purple``,
                ``wathet``, ``turquoise``, ``grey``, ``default``。
            icon_key: 自定义图标 img_key（可选）。
        """
        h: Dict[str, Any] = {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        }
        if subtitle:
            h["subtitle"] = {"tag": "plain_text", "content": subtitle}
        if icon_key:
            h["ud_icon"] = {
                "tag": "custom_icon",
                "img_key": icon_key,
                "size": "16px 16px",
            }
        self._header = h
        return self

    # ── 基础组件 ─────────────────────────────────────────────

    def markdown(
        self,
        content: str,
        *,
        text_size: str = "normal_v2",
        text_align: str = "left",
        element_id: Optional[str] = None,
    ) -> "CardBuilder":
        """添加 Markdown 渲染组件。

        Args:
            content: Markdown 文本内容。
            text_size: 字号，可选值：``normal_v2``, ``heading``,
                ``notation`` 等。
            text_align: 对齐方式：``left``, ``center``, ``right``。
            element_id: 元素 ID（用于流式更新）。
        """
        el: Dict[str, Any] = {
            "tag": "markdown",
            "content": content,
            "text_size": text_size,
            "text_align": text_align,
        }
        if element_id:
            el["element_id"] = element_id
        self._elements.append(el)
        return self

    def hr(self, element_id: Optional[str] = None) -> "CardBuilder":
        """添加分割线。"""
        el: Dict[str, Any] = {"tag": "hr"}
        if element_id:
            el["element_id"] = element_id
        self._elements.append(el)
        return self

    def image(
        self,
        img_key: str,
        *,
        alt: str = "image",
        title: Optional[str] = None,
        mode: str = "auto",
        element_id: Optional[str] = None,
    ) -> "CardBuilder":
        """添加图片组件。

        Args:
            img_key: 飞书图片 key（通过上传接口获取）。
            alt: 替代文本。
            title: 图片标题。
            mode: 显示模式：``auto``, ``stretch``。
        """
        el: Dict[str, Any] = {
            "tag": "img",
            "img_key": img_key,
            "alt": {"tag": "plain_text", "content": alt},
            "mode": mode,
        }
        if title:
            el["title"] = {"tag": "plain_text", "content": title}
        if element_id:
            el["element_id"] = element_id
        self._elements.append(el)
        return self

    def note(self, text: str) -> "CardBuilder":
        """添加备注文本（小号灰色文字）。"""
        self._elements.append({
            "tag": "markdown",
            "content": f"<font color='grey'>{text}</font>",
            "text_size": "notation",
        })
        return self

    # ── 容器组件 ─────────────────────────────────────────────

    def column_set(
        self,
        columns: List[Dict[str, Any]],
        *,
        flex_mode: str = "none",
        background_style: str = "default",
        horizontal_spacing: str = "default",
        vertical_spacing: str = "4px",
        element_id: Optional[str] = None,
    ) -> "CardBuilder":
        """添加多列布局。

        Args:
            columns: 列定义列表，每列为 ``{"weight": 1, "elements": [...]}``。
            flex_mode: 布局模式：``none``, ``bisect``, ``trifecta`` 等。
            background_style: 背景样式：``default``, ``grey``。
        """
        cs: Dict[str, Any] = {
            "tag": "column_set",
            "flex_mode": flex_mode,
            "background_style": background_style,
            "horizontal_spacing": horizontal_spacing,
            "vertical_spacing": vertical_spacing,
            "columns": columns,
        }
        if element_id:
            cs["element_id"] = element_id
        self._elements.append(cs)
        return self

    def collapsible_panel(
        self,
        title: str,
        elements: List[Dict[str, Any]],
        *,
        expanded: bool = False,
        element_id: Optional[str] = None,
    ) -> "CardBuilder":
        """添加可折叠面板。

        Args:
            title: 面板标题。
            elements: 面板内部元素列表。
            expanded: 是否默认展开。
        """
        panel: Dict[str, Any] = {
            "tag": "collapsible_panel",
            "expanded": expanded,
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title,
                    "text_color": "grey",
                    "text_size": "notation",
                },
                "vertical_align": "center",
            },
            "border": {"color": "grey", "corner_radius": "5px"},
            "padding": "8px",
            "vertical_spacing": "4px",
            "elements": elements,
        }
        if element_id:
            panel["element_id"] = element_id
        self._elements.append(panel)
        return self

    def overflow_menu(
        self,
        options: List[Dict[str, str]],
        *,
        element_id: Optional[str] = None,
    ) -> "CardBuilder":
        """添加溢出菜单（更多操作）。

        Args:
            options: 选项列表，格式：``[{"text": "导出", "value": "export"}]``。
        """
        el: Dict[str, Any] = {
            "tag": "overflow",
            "options": [
                {
                    "text": {"tag": "plain_text", "content": opt["text"]},
                    "value": opt["value"],
                }
                for opt in options
            ],
        }
        if element_id:
            el["element_id"] = element_id
        self._elements.append(el)
        return self

    # ── Markdown 表格 → column_set ────────────────────────────

    def table_from_markdown(self, table_md: str) -> "CardBuilder":
        """将 Markdown 表格转为 column_set 多列布局（移动端友好）。

        Args:
            table_md: Markdown 表格文本，如
                ``| A | B |\\n|---|---|\\n| 1 | 2 |``。
        """
        elements = parse_markdown_table(table_md)
        if elements:
            self._elements.extend(elements)
        else:
            # 解析失败，回退为普通 markdown
            self._elements.append({"tag": "markdown", "content": table_md})
        return self

    def text_with_tables(self, text: str) -> "CardBuilder":
        """将包含 Markdown 表格的文本拆分渲染。

        表格转为 column_set，其余保持 markdown 渲染。
        调用前会自动进行 markdown 优化和表格超限处理。

        Args:
            text: 包含 Markdown 表格的混合文本。
        """
        from .markdown import optimize_markdown, sanitize_text_for_card

        text = sanitize_text_for_card(text)
        text = optimize_markdown(text)
        segments = split_text_and_tables(text)

        for seg in segments:
            if seg["type"] == "text":
                self._elements.append({
                    "tag": "markdown",
                    "content": seg["content"],
                    "text_size": "normal_v2",
                })
            elif seg["type"] == "table":
                from .markdown import _parse_table_segments_to_elements
                elements = _parse_table_segments_to_elements(seg["headers"], seg["rows"])
                if elements:
                    self._elements.extend(elements)
                else:
                    # 回退：表格转为代码块
                    import re
                    header_line = "| " + " | ".join(seg["headers"]) + " |"
                    rows_lines = [
                        "| " + " | ".join(row) + " |"
                        for row in seg["rows"]
                    ]
                    fallback = "```\n" + header_line + "\n" + "\n".join(rows_lines) + "\n```"
                    self._elements.append({"tag": "markdown", "content": fallback})

        return self

    # ── Config ───────────────────────────────────────────────

    def streaming_config(
        self,
        *,
        print_frequency_ms: int = 30,
        print_step: int = 2,
        print_strategy: str = "fast",
    ) -> "CardBuilder":
        """启用流式模式配置。"""
        self._config["streaming_mode"] = True
        self._config["streaming_config"] = {
            "print_frequency_ms": {"default": print_frequency_ms},
            "print_step": {"default": print_step},
            "print_strategy": print_strategy,
        }
        return self

    def config(self, **kwargs: Any) -> "CardBuilder":
        """设置额外 config 参数。"""
        self._config.update(kwargs)
        return self

    def card_link(self, url: str, **platform_urls: str) -> "CardBuilder":
        """设置卡片跳转链接。"""
        self._card_link = {"url": url, **platform_urls}
        return self

    # ── Build ────────────────────────────────────────────────

    def build(self) -> Dict[str, Any]:
        """构建完整的 Card JSON 2.0 字典。"""
        card: Dict[str, Any] = {
            "schema": "2.0",
            "config": self._config,
        }
        if self._header:
            card["header"] = self._header
        if self._card_link:
            card["card_link"] = self._card_link
        card["body"] = {
            "direction": "vertical",
            "padding": "12px",
            "vertical_spacing": "8px",
            "horizontal_align": "left",
            "elements": self._elements,
        }
        return card
