"""表格解析：``a:tbl`` + ``ppt/tableStyles.xml`` → :class:`Table`。

最容易漏的一处：**边框不在 cell 上**。``a:tcPr`` 里通常什么都没有，
所有线条都写在表格样式（``ppt/tableStyles.xml``）里 —— 不读样式，
表格就只剩一格格没有线的方块。

样式同时还管**文字**：``firstRow`` 的 ``a:tcTxStyle`` 指定了白色粗体，
即使 cell 自己写了橙色填充，这两件事也照样生效（填充覆盖样式的填充，
但文字色和粗体不被覆盖）。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional

from ..model import (
    Color,
    Fill,
    Line,
    Table,
    TableCell,
    TableRow,
    TableStyle,
)
from ..ooxml import find, findall
from ..package import Package
from .text import parse_text_body
from .xmlutil import read_fill, read_line

#: 表格样式的边框位置
_BORDER_KEYS = ("left", "right", "top", "bottom", "insideH", "insideV")


def parse_table(package: Package, graphic_frame: ET.Element) -> Optional[Table]:
    """解析 graphicFrame 里的 ``a:tbl``。"""
    tbl = find(graphic_frame, "a:graphic/a:graphicData/a:tbl")
    if tbl is None:
        return None

    table = Table()

    tbl_pr = find(tbl, "a:tblPr")
    style_id = None
    if tbl_pr is not None:
        table.first_row = tbl_pr.get("firstRow") == "1"
        table.band_row = tbl_pr.get("bandRow") == "1"
        style_id = tbl_pr.get("tableStyleId")
    table.style = _load_style(package, style_id)

    for col in findall(find(tbl, "a:tblGrid"), "a:gridCol"):
        table.columns.append(int(col.get("w") or 0))

    for tr_el in findall(tbl, "a:tr"):
        row = TableRow(height_emu=int(tr_el.get("h") or 0))
        for tc_el in findall(tr_el, "a:tc"):
            row.cells.append(_parse_cell(tc_el))
        table.rows.append(row)

    _collect_unsupported(table)
    return table


def _parse_cell(tc_el: ET.Element) -> TableCell:
    cell = TableCell()
    cell.text = parse_text_body(find(tc_el, "a:txBody"))
    tc_pr = find(tc_el, "a:tcPr")
    if tc_pr is not None:
        cell.margin_left_emu = int(tc_pr.get("marL") or 91440)
        cell.margin_right_emu = int(tc_pr.get("marR") or 91440)
        cell.margin_top_emu = int(tc_pr.get("marT") or 45720)
        cell.margin_bottom_emu = int(tc_pr.get("marB") or 45720)
        cell.anchor = tc_pr.get("anchor") or "t"
        if tc_pr.get("gridSpan"):
            cell.grid_span = int(tc_pr.get("gridSpan"))
        v_merge = find(tc_pr, "a:vMerge")
        if v_merge is not None:
            cell.v_merge = v_merge.get("val") or "continue"
        cell.fill = read_fill(tc_pr)
    return cell


# --------------------------------------------------------------------------
# 表格样式
# --------------------------------------------------------------------------


def _load_style(package: Package, style_id: Optional[str]) -> Optional[TableStyle]:
    """从 ``ppt/tableStyles.xml`` 里取一个表格样式。"""
    root = package.xml("ppt/tableStyles.xml")
    if root is None:
        return None
    target = style_id
    if not target:
        target = root.get("def")
    if not target:
        return None

    for style_el in findall(root, "a:tblStyle"):
        if (style_el.get("styleId") or "").lower() != target.lower():
            continue
        return _parse_style(style_el)
    return None


def _parse_style(style_el: ET.Element) -> TableStyle:
    style = TableStyle(name=style_el.get("styleName"))

    whole = find(style_el, "a:wholeTbl")
    if whole is not None:
        style.borders = _read_borders(find(whole, "a:tcStyle/a:tcBdr"))
        style.fill = read_fill(find(whole, "a:tcStyle"))

    first_row = find(style_el, "a:firstRow")
    if first_row is not None:
        style.first_row_borders = _read_borders(find(first_row, "a:tcStyle/a:tcBdr"))
        style.first_row_color = _tx_style_color(first_row)
        style.first_row_bold = _tx_style_bold(first_row)
        style.first_row_fill = read_fill(find(first_row, "a:tcStyle"))

    band = find(style_el, "a:band1H")
    if band is not None:
        style.band_fill = read_fill(find(band, "a:tcStyle"))

    return style


def _read_borders(tc_bdr: Optional[ET.Element]) -> dict[str, Optional[Line]]:
    borders: dict[str, Optional[Line]] = {}
    if tc_bdr is None:
        return borders
    for key in _BORDER_KEYS:
        borders[key] = read_line(find(tc_bdr, f"a:{key}"))
    return borders


def _tx_style_color(style_el: ET.Element) -> Optional[Color]:
    """``a:tcTxStyle`` 里的文字颜色（``a:schemeClr`` / ``a:srgbClr``）。"""
    tx_style = find(style_el, "a:tcTxStyle")
    if tx_style is None:
        return None
    scheme = find(tx_style, "a:schemeClr")
    if scheme is not None:
        color = Color(theme=scheme.get("val"))
        from .xmlutil import _apply_color_modifiers

        _apply_color_modifiers(scheme, color)
        return color
    srgb = find(tx_style, "a:srgbClr")
    if srgb is not None:
        return Color(rgb=srgb.get("val"))
    return None


def _tx_style_bold(style_el: ET.Element) -> bool:
    tx_style = find(style_el, "a:tcTxStyle")
    if tx_style is None:
        return False
    return tx_style.get("b") in ("1", "on", "true")


def _collect_unsupported(table: Table) -> None:
    for row in table.rows:
        for cell in row.cells:
            if cell.v_merge:
                table.unsupported.append("合并单元格（竖向）")
            if cell.grid_span > 1:
                table.unsupported.append("合并单元格（横向）")
