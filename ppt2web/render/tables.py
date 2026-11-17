"""表格渲染：把 :class:`Table` 画成 SVG（外加一层屏幕阅读器专用的真表格）。

可见层是 SVG —— 和图表、几何、文字同一套坐标系，不依赖观看者装字体。
边框来自**表格样式**（``ppt/tableStyles.xml``）而不是单元格：
``a:tcPr`` 里通常一条线都没有，全在样式里。

无障碍层是一张真的 ``<table>``（带 ``th``/``td`` 和行列关联），
屏幕阅读器能按行列导航 —— 光有一坨扁平文本的话，读屏器只会念一长串。
"""

from __future__ import annotations

import html
from dataclasses import replace
from typing import Optional

from ..model import Fill, Line, Shape, Table, TableCell, Theme
from .glyphs import GlyphProvider
from .gradients import GradientRegistry
from .vectortext import render_text_frame


def render_table(
    shape: Shape,
    theme: Theme,
    provider: GlyphProvider,
    mirror: tuple[bool, bool] = (False, False),
) -> Optional[str]:
    """返回表格的 HTML（SVG + 无障碍表格）。

    ``mirror``：形状被翻转过时，几何照翻、文字不翻（PowerPoint 的行为）。
    """
    table = shape.table
    if table is None:
        return None

    width = max(shape.width, 1.0)
    height = max(shape.height, 1.0)
    col_x = _column_offsets(table, width)
    row_y = _row_offsets(table, height)

    gradients = GradientRegistry(prefix=f"tbl{shape.shape_id}-")
    parts: list[str] = []
    parts.extend(_fills(table, col_x, row_y, theme))
    parts.extend(_borders(table, col_x, row_y, width, height, theme))
    texts = _texts(table, col_x, row_y, theme, provider, gradients)
    if gradients.defs:
        parts.insert(0, f'<defs>{"".join(gradients.defs)}</defs>')

    if texts:
        text_body = "".join(texts)
        if mirror[0] or mirror[1]:
            sx = -1 if mirror[0] else 1
            sy = -1 if mirror[1] else 1
            tx = width if mirror[0] else 0
            ty = height if mirror[1] else 0
            text_body = f'<g transform="matrix({sx},0,0,{sy},{tx:.0f},{ty:.0f})">{text_body}</g>'
        parts.append(text_body)

    svg = (
        f'<svg class="table-svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'preserveAspectRatio="none" style="position:absolute;inset:0;width:100%;height:100%">'
        f'{"".join(parts)}</svg>'
    )
    return svg + table_a11y_html(table)


# --------------------------------------------------------------------------
# 网格
# --------------------------------------------------------------------------


def _column_offsets(table: Table, width: float) -> list[tuple[float, float]]:
    """每列的 (x, 宽)。列宽之和可能和图形框对不上，按比例缩放。"""
    raw = [float(c) for c in table.columns] or [width]
    total = sum(raw) or 1.0
    scale = width / total
    offsets: list[tuple[float, float]] = []
    x = 0.0
    for col in raw:
        w = col * scale
        offsets.append((x, w))
        x += w
    return offsets


def _row_offsets(table: Table, height: float) -> list[tuple[float, float]]:
    raw = [float(r.height_emu) for r in table.rows] or [height]
    total = sum(raw) or 1.0
    scale = height / total
    offsets: list[tuple[float, float]] = []
    y = 0.0
    for row in raw:
        h = row * scale
        offsets.append((y, h))
        y += h
    return offsets


# --------------------------------------------------------------------------
# 填充
# --------------------------------------------------------------------------


def _cell_fill(
    table: Table, row_index: int, cell: TableCell
) -> Optional[Fill]:
    """单元格的填充色：单元格里写的 > 样式首行 > 样式隔行 > 样式整表。"""
    if cell.fill is not None and cell.fill.kind != "none":
        return cell.fill
    style = table.style
    if style is None:
        return None
    if table.first_row and row_index == 0 and style.first_row_fill is not None:
        return style.first_row_fill
    if table.band_row and row_index % 2 == 1 and style.band_fill is not None:
        return style.band_fill
    return style.fill


def _fills(
    table: Table,
    col_x: list[tuple[float, float]],
    row_y: list[tuple[float, float]],
    theme: Theme,
) -> list[str]:
    parts: list[str] = []
    for r, row in enumerate(table.rows):
        if r >= len(row_y):
            break
        y, h = row_y[r]
        for c, cell in enumerate(row.cells):
            if c >= len(col_x):
                break
            x, w = col_x[c]
            fill = _cell_fill(table, r, cell)
            if fill is None or fill.kind != "solid" or fill.color is None:
                continue
            color = fill.color.to_css(theme)
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
                f'fill="{color}"/>'
            )
    return parts


# --------------------------------------------------------------------------
# 边框
# --------------------------------------------------------------------------


def _borders(
    table: Table,
    col_x: list[tuple[float, float]],
    row_y: list[tuple[float, float]],
    width: float,
    height: float,
    theme: Theme,
) -> list[str]:
    style = table.style
    if style is None:
        return []
    parts: list[str] = []
    borders = style.borders

    # 整表的外框
    parts.append(_line(0.0, 0.0, width, 0.0, borders.get("top"), theme))
    parts.append(_line(0.0, height, width, height, borders.get("bottom"), theme))
    parts.append(_line(0.0, 0.0, 0.0, height, borders.get("left"), theme))
    parts.append(_line(width, 0.0, width, height, borders.get("right"), theme))

    # 行分隔线
    for index in range(1, len(row_y)):
        y = row_y[index][0]
        parts.append(_line(0.0, y, width, y, borders.get("insideH"), theme))

    # 列分隔线
    for index in range(1, len(col_x)):
        x = col_x[index][0]
        parts.append(_line(x, 0.0, x, height, borders.get("insideV"), theme))

    # 首行底下那条粗线
    if table.first_row and style.first_row_borders:
        bottom = style.first_row_borders.get("bottom")
        if bottom is not None and row_y:
            y = row_y[0][0] + row_y[0][1]
            parts.append(_line(0.0, y, width, y, bottom, theme))

    return [p for p in parts if p]


def _line(
    x1: float, y1: float, x2: float, y2: float, line: Optional[Line], theme: Theme
) -> str:
    if line is None or line.color is None:
        return ""
    stroke = line.color.to_css(theme)
    width = line.width_emu or 12700
    return (
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="{stroke}" stroke-width="{width:.2f}"/>'
    )


# --------------------------------------------------------------------------
# 文字
# --------------------------------------------------------------------------


def _texts(
    table: Table,
    col_x: list[tuple[float, float]],
    row_y: list[tuple[float, float]],
    theme: Theme,
    provider: GlyphProvider,
    gradients: Optional[GradientRegistry] = None,
) -> list[str]:
    if provider is None:
        return []
    parts: list[str] = []
    for r, row in enumerate(table.rows):
        if r >= len(row_y):
            break
        y, h = row_y[r]
        for c, cell in enumerate(row.cells):
            if c >= len(col_x):
                break
            x, w = col_x[c]
            text_frame = _cell_text(table, r, cell)
            if text_frame is None:
                continue
            rendered = render_text_frame(
                text_frame, w, h, provider, theme, gradients=gradients
            )
            if rendered is None:
                continue
            body, _a11y, _metrics = rendered
            if not body:
                continue
            parts.append(f'<g transform="translate({x:.2f},{y:.2f})">{body}</g>')
    return parts


def _cell_text(table: Table, row_index: int, cell: TableCell):
    """单元格里的文本（带上单元格自己的边距和首行样式）。"""
    tf = cell.text
    if tf is None:
        return None
    margins = (
        cell.margin_left_emu,
        cell.margin_top_emu,
        cell.margin_right_emu,
        cell.margin_bottom_emu,
    )
    style = table.style
    use_first_row = table.first_row and row_index == 0 and style is not None
    if not use_first_row:
        return replace(tf, margins_emu=margins, anchor=cell.anchor)

    # 首行的文字色和粗体来自表格样式（单元格里的填充覆盖不了它们）
    paragraphs = []
    for para in tf.paragraphs:
        runs = []
        for run in para.runs:
            new_run = replace(run)
            if style.first_row_color is not None and run.color is None:
                new_run.color = style.first_row_color
            if style.first_row_bold and not run.bold:
                new_run.bold = True
            runs.append(new_run)
        paragraphs.append(replace(para, runs=runs))
    return replace(tf, paragraphs=paragraphs, margins_emu=margins, anchor=cell.anchor)


# --------------------------------------------------------------------------
# 无障碍表格
# --------------------------------------------------------------------------


def table_a11y_html(table: Table) -> str:
    """屏幕阅读器专用的真表格。"""
    rows: list[str] = []
    for r, row in enumerate(table.rows):
        cells = []
        for c, cell in enumerate(row.cells):
            text = ""
            if cell.text is not None:
                text = "".join(
                    run.text
                    for para in cell.text.paragraphs
                    for run in para.runs
                )
            tag = "th" if (r == 0 and table.first_row) else "td"
            scope = ' scope="col"' if tag == "th" else ""
            cells.append(f"<{tag}{scope}>{html.escape(text)}</{tag}>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    if not rows:
        return ""
    return f'<table class="tbl-a11y">{"".join(rows)}</table>'
