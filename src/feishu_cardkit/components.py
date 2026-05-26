"""
组件工厂函数。

提供常用 CardKit 组件的快捷创建函数，生成标准 JSON 元素字典。
"""

from typing import Any, Dict, List, Optional


def markdown_element(
    content: str,
    *,
    text_size: str = "normal_v2",
    text_align: str = "left",
    element_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建 Markdown 渲染元素。

    Args:
        content: Markdown 文本。
        text_size: 字号。
        text_align: 对齐方式。
        element_id: 元素 ID（流式更新用）。
    """
    el: Dict[str, Any] = {
        "tag": "markdown",
        "content": content,
        "text_size": text_size,
        "text_align": text_align,
    }
    if element_id:
        el["element_id"] = element_id
    return el


def hr_element(element_id: Optional[str] = None) -> Dict[str, Any]:
    """创建分割线元素。"""
    el: Dict[str, Any] = {"tag": "hr"}
    if element_id:
        el["element_id"] = element_id
    return el


def img_element(
    img_key: str,
    *,
    alt: str = "image",
    title: Optional[str] = None,
    mode: str = "auto",
    element_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建图片元素。

    Args:
        img_key: 飞书图片 key。
        alt: 替代文本。
        title: 图片标题。
        mode: 显示模式。
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
    return el


def column_set(
    columns: List[Dict[str, Any]],
    *,
    flex_mode: str = "none",
    background_style: str = "default",
    horizontal_spacing: str = "default",
    vertical_spacing: str = "4px",
    element_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建多列布局元素。

    Args:
        columns: 列列表，每列格式::

            {
                "width": "weighted",
                "weight": 1,
                "vertical_align": "top",
                "elements": [{"tag": "markdown", "content": "..."}],
            }
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
    return cs


def collapsible_panel(
    title: str,
    elements: List[Dict[str, Any]],
    *,
    expanded: bool = False,
    text_color: str = "grey",
    border_color: str = "grey",
    element_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建可折叠面板。

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
                "text_color": text_color,
                "text_size": "notation",
            },
            "vertical_align": "center",
        },
        "border": {"color": border_color, "corner_radius": "5px"},
        "padding": "8px",
        "vertical_spacing": "4px",
        "elements": elements,
    }
    if element_id:
        panel["element_id"] = element_id
    return panel


def overflow_menu(
    options: List[Dict[str, str]],
    *,
    element_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建溢出菜单（更多操作）。

    Args:
        options: 选项列表，格式::

            [{"text": "导出 TXT", "value": "export"}]
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
    return el


def progress_bar(percent: int, bar_length: int = 20) -> Dict[str, Any]:
    """创建进度条元素。

    Args:
        percent: 进度百分比（0-100）。
        bar_length: 进度条长度（字符数）。
    """
    filled = int(bar_length * percent / 100)
    bar = "█" * filled + "░" * (bar_length - filled)
    return markdown_element(f"**Progress:** [{bar}] {percent}%")


def button(
    text: str,
    *,
    value: Optional[str] = None,
    url: Optional[str] = None,
    button_type: str = "primary",
    element_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建按钮元素。

    Args:
        text: 按钮文本。
        value: 回调值（点击时传回）。
        url: 跳转链接（与 value 二选一）。
        button_type: 按钮样式：``primary``, ``default``, ``danger``。
    """
    el: Dict[str, Any] = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": button_type,
    }
    if value:
        el["value"] = {"action": value}
    if url:
        el["url"] = url
    if element_id:
        el["element_id"] = element_id
    return el
