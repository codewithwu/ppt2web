"""图表解析：``ppt/charts/chartN.xml`` → :class:`Chart`。

数据来自 chart XML 里的缓存（``c:numCache`` / ``c:strCache``），
**不读 embedded xlsx** —— 缓存里已经有全部数值，读 xlsx 只会多一个依赖。

三个坑（这份稿子上全踩到了）：

1. **类别名/系列名可能不在 ``c:cat`` / ``c:tx`` 里**。WPS 生成的图表把它们
   放进了 ``c15:filteredCategoryTitle`` / ``c15:filteredSeriesTitle`` 扩展，
   不解析就只能画出没有标签的柱子。
2. **``ptCount`` 会撒谎**。有的图表声明 4 个点却只给 2 个 ``c:pt``，
   按 ``ptCount`` 画会多出两个空扇区 —— 一律按**实际存在的点**画。
3. **图表可以自带主题**（``c:themeOverride``）。甜甜圈那几块的配色
   来自覆盖主题而不是幻灯片主题，用错主题颜色就全错。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional

from ..model import (
    Chart,
    ChartAxis,
    ChartLabels,
    ChartPoint,
    ChartSeries,
    Color,
    Fill,
    Line,
    Theme,
)
from ..ooxml import find, findall
from ..package import Package
from .theme import parse_theme
from .xmlutil import read_fill, read_line

#: 图表组标签 → 图表类型
_GROUPS = (
    ("c:barChart", "bar"),
    ("c:doughnutChart", "doughnut"),
    ("c:pieChart", "pie"),
)


def _has_c15_extension(root) -> bool:
    """chart XML 里有没有 c15 扩展（类别名/系列名被挪进去了）。"""
    for tag in ("c15:filteredCategoryTitle", "c15:filteredSeriesTitle"):
        if find(root, tag) is not None:
            return True
        for node in root.iter():
            if node.tag.split("}")[-1] in (
                "filteredCategoryTitle",
                "filteredSeriesTitle",
            ):
                return True
    return False


def parse_chart(
    package: Package,
    partname: str,
    slide_theme: Optional[Theme] = None,
) -> Optional[Chart]:
    """解析一个 chart part。返回 None 表示这个部件不是图表。"""
    root = package.xml(partname)
    if root is None:
        return None
    chart_el = find(root, "c:chart")
    if chart_el is None:
        return None

    chart = Chart()
    chart.theme = _chart_theme(package, partname, slide_theme)
    chart.color_cycle = _color_cycle(package, partname)
    # WPS 把类别名/系列名放进了 c15 扩展（chart XML 里没有 c:cat）。
    # LibreOffice 不支持 c15，渲染出来就没有标签 —— 记一笔，
    # 视觉比对时好把它当成"已知差异"而不是 bug。
    if _has_c15_extension(root):
        chart.notes.append("类别名/系列名来自 c15 扩展")

    plot_area = find(chart_el, "c:plotArea")
    if plot_area is None:
        chart.unsupported.append("没有 plotArea")
        return chart

    _parse_group(chart, plot_area)
    _parse_axes(chart, plot_area)
    _parse_layout(chart, plot_area)
    _parse_labels(chart, plot_area)
    chart.legend = find(chart_el, "c:legend") is not None
    chart.title = _title_text(find(chart_el, "c:title"))

    # 类别名：优先取第一个有类别的系列（不同系列的类别是一样的）
    for series in chart.series:
        if series.categories:
            chart.categories = list(series.categories)
            break

    _collect_unsupported(chart)
    return chart


# --------------------------------------------------------------------------
# 图表组（柱状图 / 甜甜圈 / 饼图）
# --------------------------------------------------------------------------


def _parse_group(chart: Chart, plot_area: ET.Element) -> None:
    for tag, kind in _GROUPS:
        group = find(plot_area, tag)
        if group is None:
            continue
        chart.kind = kind
        _read_group_common(chart, group)
        if kind == "bar":
            chart.bar_dir = _val(group, "c:barDir", "col")
            chart.grouping = _val(group, "c:grouping", "clustered")
        else:
            chart.hole_size = int(_val(group, "c:holeSize", "50") or 50)
            chart.first_slice_angle = float(_val(group, "c:firstSliceAng", "0") or 0)
        for ser_el in findall(group, "c:ser"):
            chart.series.append(_parse_series(ser_el))
        return
    # 一个都没认出来 → 类型是"未知"，不能当成柱状图瞎画
    chart.kind = "unknown"
    chart.unsupported.append("未知的图表类型")


def _read_group_common(chart: Chart, group: ET.Element) -> None:
    chart.vary_colors = _val(group, "c:varyColors", "0") == "1"
    chart.gap_width = int(_val(group, "c:gapWidth", "150") or 150)
    overlap = _val(group, "c:overlap", None)
    if overlap is not None:
        chart.overlap = int(overlap)


def _parse_series(ser_el: ET.Element) -> ChartSeries:
    series = ChartSeries()

    tx = find(ser_el, "c:tx")
    if tx is not None:
        series.name = _first_cached_string(tx)
    if not series.name:
        # WPS 把系列名挪进了 c15 扩展
        cached = _c15_filtered(ser_el, "c15:filteredSeriesTitle")
        series.name = cached[0] if cached else None

    cat = find(ser_el, "c:cat")
    if cat is not None:
        series.categories = _category_strings(cat)
    if not series.categories:
        series.categories = _c15_filtered(ser_el, "c15:filteredCategoryTitle")

    val = find(ser_el, "c:val")
    if val is not None:
        series.values = _cached_numbers(find(val, "c:numRef"))

    sp_pr = find(ser_el, "c:spPr")
    series.fill = read_fill(sp_pr)
    series.line = read_line(sp_pr)

    for dpt in findall(ser_el, "c:dPt"):
        idx_el = find(dpt, "c:idx")
        if idx_el is None:
            continue
        dpt_sp = find(dpt, "c:spPr")
        series.points.append(
            ChartPoint(
                idx=int(idx_el.get("val") or 0),
                fill=read_fill(dpt_sp),
                line=read_line(dpt_sp),
            )
        )
    return series


# --------------------------------------------------------------------------
# 坐标轴
# --------------------------------------------------------------------------


def _parse_axes(chart: Chart, plot_area: ET.Element) -> None:
    for tag, kind in (("c:catAx", "cat"), ("c:valAx", "val")):
        for ax_el in findall(plot_area, tag):
            chart.axes.append(_parse_axis(ax_el, kind))


def _parse_axis(ax_el: ET.Element, kind: str) -> ChartAxis:
    axis = ChartAxis(kind=kind)
    axis.position = _val(ax_el, "c:axPos", "b")
    axis.deleted = _val(ax_el, "c:delete", "0") == "1"
    num_fmt = find(ax_el, "c:numFmt")
    if num_fmt is not None:
        axis.num_fmt = num_fmt.get("formatCode") or "General"
    axis.major_tick_mark = _val(ax_el, "c:majorTickMark", "none")
    axis.tick_label_pos = _val(ax_el, "c:tickLblPos", "nextTo")
    unit = _val(ax_el, "c:majorUnit", None)
    if unit is not None:
        axis.major_unit = float(unit)

    axis.line = read_line(find(ax_el, "c:spPr"))
    gridlines = find(ax_el, "c:majorGridlines")
    if gridlines is not None:
        axis.gridlines = read_line(find(gridlines, "c:spPr"))

    tx_pr = find(ax_el, "c:txPr")
    if tx_pr is not None:
        body_pr = find(tx_pr, "a:bodyPr")
        if body_pr is not None and body_pr.get("rot") is not None:
            axis.label_rotation = _normalize_angle(int(body_pr.get("rot")))
        def_rpr = find(tx_pr, "a:p/a:pPr/a:defRPr")
        if def_rpr is not None:
            if def_rpr.get("sz"):
                axis.label_size_pt = int(def_rpr.get("sz")) / 100
            color = _solid_color(find(def_rpr, "a:solidFill"))
            if color is not None:
                axis.label_color = color
            latin = find(def_rpr, "a:latin")
            if latin is not None:
                axis.label_font = latin.get("typeface")
            ea = find(def_rpr, "a:ea")
            if ea is not None:
                axis.label_ea_font = ea.get("typeface")
    return axis


def _normalize_angle(raw: int) -> float:
    """``a:bodyPr@rot`` → 度。

    OOXML 规定单位是 1/60000 度。但有些生成器（WPS）写的是 **1/1000000 度**：
    ``rot="-60000000"`` 按规范算是 -1000°（荒谬），按 1e-6 度算是 **-60°**（合理）。

    怎么分辨？**看超出范围**：规范单位下 ±180° 只需要 ±10800000，
    更大的值只能是单位不对，按 1e-6 度解释。
    （另外这条稿子的绘图区下方留白 25.8pt，正好等于 3 个 10pt 汉字按 -60°
    斜排的高度 30×sin60°=26.0pt —— 交叉验证了 -60° 才是作者要的。）
    """
    deg = raw / 60000.0
    if abs(deg) > 180:
        deg = raw / 1000000.0
    return ((deg + 180) % 360) - 180


# --------------------------------------------------------------------------
# 绘图区布局 / 数据标签 / 标题
# --------------------------------------------------------------------------


def _parse_layout(chart: Chart, plot_area: ET.Element) -> None:
    manual = find(plot_area, "c:layout/c:manualLayout")
    if manual is None:
        return
    values = []
    for tag in ("c:x", "c:y", "c:w", "c:h"):
        node = find(manual, tag)
        if node is None:
            return
        try:
            values.append(float(node.get("val")))
        except (TypeError, ValueError):
            return
    chart.layout = (values[0], values[1], values[2], values[3])


def _parse_labels(chart: Chart, plot_area: ET.Element) -> None:
    """数据标签：系列级优先，其次图表组级。"""
    group = None
    for tag, _kind in _GROUPS:
        group = find(plot_area, tag)
        if group is not None:
            break
    if group is None:
        return
    labels_el = None
    for ser_el in findall(group, "c:ser"):
        candidate = find(ser_el, "c:dLbls")
        if candidate is not None:
            labels_el = candidate
            break
    if labels_el is None:
        labels_el = find(group, "c:dLbls")
    if labels_el is None:
        return

    labels = ChartLabels()
    labels.show_value = _val(labels_el, "c:showVal", "0") == "1"
    labels.show_category = _val(labels_el, "c:showCatName", "0") == "1"
    labels.show_series = _val(labels_el, "c:showSerName", "0") == "1"
    labels.show_percent = _val(labels_el, "c:showPercent", "0") == "1"

    tx_pr = find(labels_el, "c:txPr")
    if tx_pr is not None:
        def_rpr = find(tx_pr, "a:p/a:pPr/a:defRPr")
        if def_rpr is not None:
            if def_rpr.get("sz"):
                labels.size_pt = int(def_rpr.get("sz")) / 100
            color = _solid_color(find(def_rpr, "a:solidFill"))
            if color is not None:
                labels.color = color
            latin = find(def_rpr, "a:latin")
            if latin is not None:
                labels.font = latin.get("typeface")
            ea = find(def_rpr, "a:ea")
            if ea is not None:
                labels.ea_font = ea.get("typeface")

    # c15:leaderLines —— 标签的引线样式
    for ext in findall(find(labels_el, "c:extLst"), "c:ext"):
        leader = find(ext, "c15:leaderLines")
        if leader is not None:
            labels.leader_line = read_line(find(leader, "c:spPr"))
            break
    chart.labels = labels


def _title_text(title_el: Optional[ET.Element]) -> Optional[str]:
    if title_el is None:
        return None
    parts = []
    for rich in findall(title_el, "c:tx/c:rich"):
        for pt in findall(rich, "a:p"):
            for t in findall(pt, "a:r"):
                node = find(t, "a:t")
                if node is not None and node.text:
                    parts.append(node.text)
    return "".join(parts) or None


# --------------------------------------------------------------------------
# 主题与配色
# --------------------------------------------------------------------------


def _chart_theme(
    package: Package, partname: str, slide_theme: Optional[Theme]
) -> Optional[Theme]:
    """图表自带的主题覆盖（``c:themeOverride``），没有就用幻灯片的。"""
    override = package.related(partname, "themeOverride")
    if override:
        root = package.xml(override)
        if root is not None:
            return parse_theme(root)
    return slide_theme


def _color_cycle(package: Package, partname: str) -> list[str]:
    """``ppt/charts/colorsN.xml`` 里的配色循环（色槽名顺序）。"""
    colors_part = package.related(partname, "chartColorStyle")
    if not colors_part:
        return []
    root = package.xml(colors_part)
    if root is None:
        return []
    cycle: list[str] = []
    for child in root:
        if child.tag.endswith("}schemeClr"):
            cycle.append(child.get("val") or "")
    return cycle


# --------------------------------------------------------------------------
# 缓存读取
# --------------------------------------------------------------------------


def _val(el: ET.Element, path: str, default):
    node = find(el, path)
    if node is None:
        return default
    value = node.get("val")
    return default if value is None else value


def _cached_numbers(ref: Optional[ET.Element]) -> list[float]:
    """``c:numCache`` 里的数值。

    **按实际存在的 ``c:pt`` 读，不信 ``ptCount``** —— 有的文件声明 4 个点
    却只给 2 个（数据被筛掉了），按声明画会多出两个空扇区。
    """
    if ref is None:
        return []
    cache = find(ref, "c:numCache")
    if cache is None:
        return []
    values: dict[int, float] = {}
    for pt in findall(cache, "c:pt"):
        idx = int(pt.get("idx") or 0)
        node = find(pt, "c:v")
        if node is None or node.text is None:
            continue
        try:
            values[idx] = float(node.text)
        except ValueError:
            continue
    return [values[i] for i in sorted(values)]


def _cached_strings(ref: Optional[ET.Element]) -> list[str]:
    """``c:strCache`` 里的字符串。"""
    if ref is None:
        return []
    cache = find(ref, "c:strCache")
    if cache is None:
        return []
    values: dict[int, str] = {}
    for pt in findall(cache, "c:pt"):
        idx = int(pt.get("idx") or 0)
        node = find(pt, "c:v")
        values[idx] = node.text if node is not None and node.text else ""
    return [values[i] for i in sorted(values)]


def _first_cached_string(tx_el: ET.Element) -> Optional[str]:
    ref = find(tx_el, "c:strRef")
    values = _cached_strings(ref)
    return values[0] if values else None


def _category_strings(cat_el: ET.Element) -> list[str]:
    """类别名。``c:multiLvlStrRef`` 可能只有公式没有缓存（那就真的没有）。"""
    ref = find(cat_el, "c:strRef")
    if ref is not None:
        return _cached_strings(ref)
    multi = find(cat_el, "c:multiLvlStrRef")
    if multi is not None:
        cache = find(multi, "c:multiLvlStrCache")
        if cache is None:
            return []
        level = find(cache, "c:lvl")
        if level is None:
            return []
        values: dict[int, str] = {}
        for pt in findall(level, "c:pt"):
            idx = int(pt.get("idx") or 0)
            node = find(pt, "c:v")
            values[idx] = node.text if node is not None and node.text else ""
        return [values[i] for i in sorted(values)]
    return []


def _c15_filtered(ser_el: ET.Element, tag: str) -> list[str]:
    """读 ``c15:filteredSeriesTitle`` / ``c15:filteredCategoryTitle``。

    这两个扩展里的结构和 ``c:tx`` / ``c:cat`` 一模一样，只是套了一层 c15。
    """
    for ext in findall(find(ser_el, "c:extLst"), "c:ext"):
        node = find(ext, tag)
        if node is None:
            continue
        for inner_tag in ("c15:tx", "c15:cat"):
            inner = find(node, inner_tag)
            if inner is None:
                continue
            values = _cached_strings(find(inner, "c:strRef"))
            if values:
                return values
    return []


def _solid_color(fill_el: Optional[ET.Element]) -> Optional[Color]:
    if fill_el is None:
        return None
    from .xmlutil import _color_from_fill

    return _color_from_fill(fill_el)


def _collect_unsupported(chart: Chart) -> None:
    """记下这份渲染器画不出来的特性 —— verify 会把它们降级成警告。"""
    kinds = {group.kind for group in []}
    if chart.kind not in ("bar", "doughnut", "pie"):
        chart.unsupported.append(f"图表类型 {chart.kind}")
    if chart.kind == "bar":
        if chart.grouping not in ("clustered", "standard"):
            chart.unsupported.append(f"柱状图分组 {chart.grouping}")
        if chart.bar_dir not in ("col", "bar"):
            chart.unsupported.append(f"柱状图方向 {chart.bar_dir}")
        kinds = {axis.kind for axis in chart.axes}
        if len(kinds) > 2:
            chart.unsupported.append("多坐标轴")
    if chart.legend:
        chart.unsupported.append("图例")
    if chart.title:
        chart.unsupported.append("图表标题")
