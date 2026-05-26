"""
Markdown 处理工具。

提供 Markdown 优化、表格解析（转为 column_set）、表格超限保护等功能。
"""

import re
from typing import Any, Dict, List, Optional

# 飞书卡片元素限制：超过此数的表格触发 230099/11310 错误
TABLE_LIMIT = 3


# ---------------------------------------------------------------------------
# 表格解析：Markdown → column_set 元素
# ---------------------------------------------------------------------------

def parse_markdown_table(table_md: str) -> Optional[List[Dict[str, Any]]]:
    """将 Markdown 表格文本解析为 CardKit column_set 元素列表。

    每行变成一个 ``column_set``，表头带灰色背景，数据行普通背景。
    移动端自动折行，解决原生 markdown 表格截断问题。

    Args:
        table_md: Markdown 表格文本。

    Returns:
        column_set 元素列表，解析失败返回 None。

    示例::

        elements = parse_markdown_table(
            "| 名称 | 状态 |\\n|------|------|\\n| 前端 | ✅ |"
        )
    """
    lines = table_md.strip().split("\\n")
    # 如果只有一行，说明可能是真正的换行符
    if len(lines) <= 1:
        lines = table_md.strip().split("\n")

    # 过滤空行
    lines = [l for l in lines if l.strip()]
    if len(lines) < 2:
        return None

    # 解析表头
    header_line = lines[0]
    if not header_line.startswith("|"):
        return None
    headers = [c.strip() for c in header_line.strip("|").split("|")]

    # 跳过分隔行（|---|---|）
    data_start = 1
    if data_start < len(lines):
        sep = lines[data_start].strip()
        if re.match(r'^[\|\s\-:]+$', sep):
            data_start += 1

    # 解析数据行
    rows: List[List[str]] = []
    for line in lines[data_start:]:
        line = line.strip()
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line[1:-1].split("|")]
            rows.append(cells)
        elif "|" in line:
            cells = [c.strip() for c in line.split("|")]
            rows.append(cells)

    if not headers:
        return None

    return _build_column_set_table(headers, rows)


def _build_column_set_table(
    headers: List[str], rows: List[List[str]]
) -> List[Dict[str, Any]]:
    """根据表头和数据行构建 column_set 元素列表。"""
    num_cols = max(len(headers), max((len(r) for r in rows), default=0))
    if num_cols == 0:
        return []

    result: List[Dict[str, Any]] = []

    # 表头行（灰色背景）
    header_cols = []
    for ci in range(num_cols):
        header_cols.append({
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "vertical_align": "top",
            "elements": [{
                "tag": "markdown",
                "content": f"**{headers[ci]}**" if ci < len(headers) and headers[ci] else " ",
                "text_size": "notation",
            }],
        })
    result.append({
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "grey",
        "horizontal_spacing": "default",
        "vertical_spacing": "2px",
        "columns": header_cols,
    })

    # 数据行
    for row in rows:
        data_cols = []
        for ci in range(num_cols):
            cell_val = row[ci] if ci < len(row) else ""
            data_cols.append({
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "vertical_align": "top",
                "elements": [{
                    "tag": "markdown",
                    "content": cell_val if cell_val else " ",
                    "text_size": "notation",
                }],
            })
        result.append({
            "tag": "column_set",
            "flex_mode": "none",
            "background_style": "default",
            "horizontal_spacing": "default",
            "vertical_spacing": "2px",
            "columns": data_cols,
        })

    return result


def _parse_table_segments_to_elements(
    headers: List[str], rows: List[List[str]]
) -> Optional[List[Dict[str, Any]]]:
    """供 builder.py 调用的桥接函数。"""
    return _build_column_set_table(headers, rows)


# ---------------------------------------------------------------------------
# 文本拆分：表格 / 非表格
# ---------------------------------------------------------------------------

def split_text_and_tables(text: str) -> List[Dict[str, Any]]:
    """将文本拆分为表格段和非表格段。

    Returns:
        字典列表，每项为 ``{"type": "text", "content": str}`` 或
        ``{"type": "table", "headers": [...], "rows": [[...]]}``。

    注意:
        应在 :func:`optimize_markdown` **之前**调用，避免 ``<br>`` 干扰表格检测。
    """
    segments: List[Dict[str, Any]] = []
    last_end = 0

    blocks = text.split("```")
    table_re = re.compile(
        r"^[ \t]*\|(.+)\|[ \t]*\n"
        r"[ \t]*\|([-:| ]+)\|[ \t]*\n"
        r"((?:[ \t]*\|.*\|[ \t]*\n)*)",
        re.MULTILINE,
    )

    tables_info: List[tuple] = []
    for i, block in enumerate(blocks):
        if i % 2 == 1:
            continue  # 代码块内
        prefix_len = sum(len(blocks[j]) for j in range(i))
        prefix_len += len("```") * i
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


# ---------------------------------------------------------------------------
# 表格超限保护
# ---------------------------------------------------------------------------

def _find_markdown_tables_outside_code_blocks(text: str) -> List[Dict]:
    """查找不在代码块内的 Markdown 表格。"""
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


def sanitize_text_for_card(text: str, table_limit: int = TABLE_LIMIT) -> str:
    """将超过限制的 Markdown 表格包裹为代码块。

    飞书卡片拒绝包含超过 3 个表格的消息（错误 230099 / 11310）。
    此函数保留前 *table_limit* 个表格，多余的包裹为代码块。

    Args:
        text: Markdown 文本。
        table_limit: 允许的最大表格数（默认 3）。
    """
    tables = _find_markdown_tables_outside_code_blocks(text)
    if len(tables) <= table_limit:
        return text

    result = text
    for t in reversed(tables[table_limit:]):
        replacement = f"```\n{t['raw']}\n```"
        result = result[:t["index"]] + replacement + result[t["index"] + t["length"]:]
    return result


# ---------------------------------------------------------------------------
# Markdown 优化
# ---------------------------------------------------------------------------

def optimize_markdown(text: str) -> str:
    """优化 Markdown 以适配飞书 CardKit 2.0 渲染。

    处理内容：
    1. 代码块提取 & 保护
    2. 标题降级（H1→H4, H2-H6→H5）
    3. 表格间距调整
    4. 压缩多余空行
    5. 过滤无效图片引用
    """
    try:
        return _do_optimize_markdown(text)
    except Exception:
        return text


def _do_optimize_markdown(text: str) -> str:
    """Markdown 优化的实际实现。"""
    if not text or not text.strip():
        return text

    # 1. 提取并保护代码块
    code_blocks: List[str] = []
    def _extract_code(m: re.Match) -> str:
        code_blocks.append(m.group(0))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    text = re.sub(r'(`{3,})[^\n]*\n[\s\S]*?\n\1', _extract_code, text)

    # 2. 标题降级
    text = re.sub(r'^#{1}\s+', '#### ', text, flags=re.MULTILINE)
    text = re.sub(r'^#{2,6}\s+', '##### ', text, flags=re.MULTILINE)

    # 3. 表格间距
    def _table_after_spacing(m: re.Match) -> str:
        table_block = m.group(1)
        end_pos = m.end()
        remainder = m.string[end_pos:].lstrip('\n')
        if not remainder:
            return table_block
        if remainder.startswith('####') or remainder.startswith('**'):
            return table_block
        return table_block + '<br>\n'

    text = re.sub(
        r'(\|.+\|[\r\n]+\|[-:| ]+\|[\s\S]*?(?:\n\n|\n(?!\|)|$))',
        _table_after_spacing,
        text,
    )

    # 4. 压缩空行
    text = re.sub(r'\n{4,}', '\n\n\n', text)

    # 5. 过滤无效图片引用
    if '![' in text:
        def _replacer(m: re.Match) -> str:
            value = m.group(2)
            if value.startswith('img_'):
                return m.group(0)
            return ''
        text = re.sub(r'!\[([^\]]*)\]\(([^)\s]+)\)', _replacer, text)

    # 恢复代码块
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{i}\x00", block)

    return text
