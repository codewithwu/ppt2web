"""图表渲染：把 :class:`Chart` 画成 SVG。

产物是**静态 SVG**（不引任何 JS 库），坐标是形状自己的 EMU 空间，
和同一页的其他图元共用一套坐标系 —— 所以能和原稿严丝合缝地对上。

覆盖的类型（这份稿子用到的）：

* **甜甜圈 / 饼图**：两段圆环弧。角度从 12 点方向开始、顺时针；
  配色优先用每个数据点的显式填充（``c:dPt``），没有才走主题配色循环。
* **簇状柱状图**：绘图区按 ``c:manualLayout`` 手工定位，
  网格线、坐标轴标签（可带旋转）、柱顶数据标签都画。

不支持的特性（次坐标轴、堆积、图例、3D……）会记进 ``chart.unsupported``，
由 verify 降级成警告，而不是画个像但不对的图。
"""

from __future__ import annotations

import math
from typing import Optional

from ..model import Chart, Color, Fill, Shape, Theme
from .glyphs import EMU_PER_PT, GlyphProvider
from .gradients import GradientRegistry
from .vectortext import VectorText, vector_text

#: 绘图区边缘到坐标轴标签的留白（EMU）
_AXIS_GAP = int(0.03 * 914400)


def render_chart(
    shape: Shape,
    theme: Theme,
    provider: GlyphProvider,
    mirror: tuple[bool, bool] = (False, False),
) -> Optional[str]:
    """返回图表的 HTML（SVG + 无障碍文本层）。渲染不了就返回 None。

    ``mirror``：形状被翻转过时，**几何照翻、文字不翻** —— 和 PowerPoint 一致。
    """
    chart = shape.chart
    if chart is None or chart.unsupported:
        # 不支持的类型宁可画占位框，也不要画个"像但不对"的图
        return None

    ctheme = chart.theme or theme
    width = max(shape.width, 1.0)
    height = max(shape.height, 1.0)

    gradients = GradientRegistry(prefix=f"chart{shape.shape_id}-")
    geo: list[str] = []
    txt: list[str] = []
    if chart.kind in ("doughnut", "pie"):
        geo, txt = _render_doughnut(chart, width, height, ctheme, gradients)
    elif chart.kind == "bar":
        geo, txt = _render_bar(
            chart, shape, width, height, ctheme, theme, provider, gradients
        )
    else:
        return None

    body = "".join(geo)
    if txt:
        text_body = "".join(txt)
        if mirror[0] or mirror[1]:
            # 抵消外层翻转对文字的影响（PowerPoint 翻转形状不翻转文字）
            sx = -1 if mirror[0] else 1
            sy = -1 if mirror[1] else 1
            tx = width if mirror[0] else 0
            ty = height if mirror[1] else 0
            text_body = f'<g transform="matrix({sx},0,0,{sy},{tx:.0f},{ty:.0f})">{text_body}</g>'
        body += text_body
    if gradients.defs:
        body = f'<defs>{"".join(gradients.defs)}</defs>' + body
    svg = (
        f'<svg class="chart-svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'preserveAspectRatio="none" style="position:absolute;inset:0;width:100%;height:100%">'
        f"{body}</svg>"
    )
    a11y = _a11y_text(chart)
    return svg + a11y


def chart_a11y_text(chart: Chart) -> str:
    """图表的无障碍文本（纯文本）。

    顺序是固定的：**系列名 → 类别名**。源文件侧用同一个顺序，
    verify 才能逐字符比对（"图表里的文字不丢" 这条门禁）。
    """
    parts: list[str] = []
    for series in chart.series:
        if series.name:
            parts.append(series.name)
    parts.extend(chart.categories)
    return "".join(parts)


def _a11y_text(chart: Chart) -> str:
    text = chart_a11y_text(chart)
    return f'<div class="tx-a11y">{text}</div>' if text else ""


# --------------------------------------------------------------------------
# 甜甜圈 / 饼图
# --------------------------------------------------------------------------


def _render_doughnut(
    chart: Chart,
    width: float,
    height: float,
    theme: Theme,
    gradients: GradientRegistry,
) -> tuple[list[str], list[str]]:
    series = chart.series[0] if chart.series else None
    if series is None or not series.values:
        return [], []

    plot = _plot_rect(chart, width, height)
    cx = plot[0] + plot[2] / 2
    cy = plot[1] + plot[3] / 2
    outer = min(plot[2], plot[3]) / 2
    inner = outer * (chart.hole_size / 100.0) if chart.kind == "doughnut" else 0.0

    values = [v for v in series.values if v is not None]
    total = sum(values)
    if total <= 0:
        return [], []

    parts: list[str] = []
    angle = chart.first_slice_angle
    for idx, value in enumerate(values):
        sweep = 360.0 * (value / total)
        color = _point_color(chart, series, idx, theme, gradients)
        if color is None:
            continue
        path = _annular_sector(cx, cy, outer, inner, angle, angle + sweep)
        if not path:
            continue
        title = _point_title(chart, series, idx, value, total)
        parts.append(f'<path d="{path}" fill="{color}"><title>{title}</title></path>')
        angle += sweep
    return parts, []


def _annular_sector(
    cx: float, cy: float, outer: float, inner: float, start: float, end: float
) -> str:
    """圆环扇形（角度以 12 点方向为 0，顺时针，单位度）。"""
    sweep = end - start
    if sweep <= 0:
        return ""
    if sweep >= 359.999:
        # 整圆：外圈正圆 + 内圈反向挖洞
        outer_d = (
            f"M {cx - outer:.2f} {cy:.2f} "
            f"A {outer:.2f} {outer:.2f} 0 1 1 {cx + outer:.2f} {cy:.2f} "
            f"A {outer:.2f} {outer:.2f} 0 1 1 {cx - outer:.2f} {cy:.2f} Z"
        )
        if inner <= 0:
            return outer_d
        return (
            f"{outer_d} M {cx - inner:.2f} {cy:.2f} "
            f"A {inner:.2f} {inner:.2f} 0 1 0 {cx + inner:.2f} {cy:.2f} "
            f"A {inner:.2f} {inner:.2f} 0 1 0 {cx - inner:.2f} {cy:.2f} Z"
        )

    large = 1 if sweep > 180 else 0
    x0, y0 = _polar(cx, cy, outer, start)
    x1, y1 = _polar(cx, cy, outer, end)
    if inner <= 0:
        return (
            f"M {cx:.2f} {cy:.2f} L {x0:.2f} {y0:.2f} "
            f"A {outer:.2f} {outer:.2f} 0 {large} 1 {x1:.2f} {y1:.2f} Z"
        )
    x2, y2 = _polar(cx, cy, inner, end)
    x3, y3 = _polar(cx, cy, inner, start)
    return (
        f"M {x0:.2f} {y0:.2f} A {outer:.2f} {outer:.2f} 0 {large} 1 {x1:.2f} {y1:.2f} "
        f"L {x2:.2f} {y2:.2f} A {inner:.2f} {inner:.2f} 0 {large} 0 {x3:.2f} {y3:.2f} Z"
    )


def _polar(cx: float, cy: float, radius: float, angle_deg: float) -> tuple[float, float]:
    """极坐标 → 直角坐标（12 点方向为 0，顺时针；屏幕 y 向下）。"""
    rad = math.radians(angle_deg)
    return cx + radius * math.sin(rad), cy - radius * math.cos(rad)


# --------------------------------------------------------------------------
# 柱状图
# --------------------------------------------------------------------------


def _render_bar(
    chart: Chart,
    shape: Shape,
    width: float,
    height: float,
    theme: Theme,
    slide_theme: Theme,
    provider: GlyphProvider,
    gradients: GradientRegistry,
) -> tuple[list[str], list[str]]:
    cat_axis = next((a for a in chart.axes if a.kind == "cat"), None)
    val_axis = next((a for a in chart.axes if a.kind == "val"), None)
    if not chart.series:
        return [], []

    plot = _plot_rect(chart, width, height)
    px, py, pw, ph = plot

    values = [v for series in chart.series for v in series.values]
    if not values:
        return [], []
    unit = val_axis.major_unit if val_axis and val_axis.major_unit else 1.0
    vmin = 0.0
    vmax = max(values)
    vmax = math.ceil(vmax / unit) * unit if unit > 0 else vmax
    if vmax <= vmin:
        vmax = vmin + unit

    categories = chart.categories
    n_cat = max(len(categories), max((len(s.values) for s in chart.series), default=0))
    if n_cat == 0:
        return [], []

    parts: list[str] = []
    texts: list[str] = []
    parts.extend(_gridlines(val_axis, px, py, pw, ph, vmin, vmax, unit, theme))

    # 类别轴的线（画在柱子下面）
    if cat_axis is not None and cat_axis.line is not None:
        stroke = cat_axis.line.color.to_css(theme) if cat_axis.line.color else "none"
        width = cat_axis.line.width_emu or 12700
        parts.append(
            f'<line x1="{px:.2f}" y1="{py + ph:.2f}" x2="{px + pw:.2f}" y2="{py + ph:.2f}" '
            f'stroke="{stroke}" stroke-width="{width:.2f}"/>'
        )

    # 柱子
    n_series = len(chart.series)
    overlap = (chart.overlap or 0) / 100.0
    gap = chart.gap_width / 100.0
    denom = n_cat * (n_series - (n_series - 1) * overlap) + max(n_cat - 1, 0) * gap
    bar_w = pw / denom if denom > 0 else pw / max(n_cat, 1)
    cluster_w = n_series * bar_w - (n_series - 1) * overlap * bar_w

    for s_index, series in enumerate(chart.series):
        for i, value in enumerate(series.values):
            if value is None:
                continue
            bar_h = ph * (value - vmin) / (vmax - vmin)
            x = px + i * (cluster_w + gap * bar_w) + s_index * (bar_w - overlap * bar_w)
            y = py + ph - bar_h
            fill = _point_color(chart, series, i, theme, gradients)
            if fill is None:
                continue
            title = _point_title(chart, series, i, value, vmax)
            parts.append(
                f'<path d="M {x:.2f} {y:.2f} L {x + bar_w:.2f} {y:.2f} '
                f'L {x + bar_w:.2f} {py + ph:.2f} L {x:.2f} {py + ph:.2f} Z" '
                f'fill="{fill}"><title>{title}</title></path>'
            )
            # 柱顶数据标签
            if chart.labels is not None and chart.labels.show_value:
                label = _format_number(value)
                texts.extend(
                    _label_markup(
                        label,
                        provider,
                        theme,
                        slide_theme,
                        x=x + bar_w / 2,
                        baseline=y - 2 * EMU_PER_PT,
                        anchor="middle",
                        size_pt=chart.labels.size_pt or 10.0,
                        color=chart.labels.color,
                        font=chart.labels.font,
                        ea_font=chart.labels.ea_font,
                    )
                )

    texts.extend(_cat_labels(chart, cat_axis, px, py, pw, ph, n_cat, cluster_w, gap, bar_w,
                             theme, slide_theme, provider))
    texts.extend(_val_labels(val_axis, px, py, pw, ph, vmin, vmax, unit, theme, slide_theme, provider))
    return parts, texts


def _gridlines(
    val_axis,
    px: float,
    py: float,
    pw: float,
    ph: float,
    vmin: float,
    vmax: float,
    unit: float,
    theme: Theme,
) -> list[str]:
    if val_axis is None or val_axis.gridlines is None:
        return []
    line = val_axis.gridlines
    stroke = line.color.to_css(theme) if line.color else "none"
    width = line.width_emu or 12700
    parts: list[str] = []
    value = vmin
    while value <= vmax + 1e-9:
        y = py + ph * (1 - (value - vmin) / (vmax - vmin))
        parts.append(
            f'<line x1="{px:.2f}" y1="{y:.2f}" x2="{px + pw:.2f}" y2="{y:.2f}" '
            f'stroke="{stroke}" stroke-width="{width:.2f}"/>'
        )
        value += unit
    return parts


def _cat_labels(
    chart: Chart,
    axis,
    px: float,
    py: float,
    pw: float,
    ph: float,
    n_cat: int,
    cluster_w: float,
    gap: float,
    bar_w: float,
    theme: Theme,
    slide_theme: Theme,
    provider: GlyphProvider,
) -> list[str]:
    if axis is None or axis.deleted or not chart.categories:
        return []
    parts: list[str] = []
    rotation = axis.label_rotation
    for i, name in enumerate(chart.categories[:n_cat]):
        center = px + i * (cluster_w + gap * bar_w) + cluster_w / 2
        parts.extend(
            _label_markup(
                name,
                provider,
                theme,
                slide_theme,
                x=center,
                baseline=py + ph + _AXIS_GAP,
                anchor="end",
                size_pt=axis.label_size_pt or 10.0,
                color=axis.label_color,
                font=axis.label_font,
                ea_font=axis.label_ea_font,
                rotation=rotation,
            )
        )
    return parts


def _val_labels(
    axis,
    px: float,
    py: float,
    pw: float,
    ph: float,
    vmin: float,
    vmax: float,
    unit: float,
    theme: Theme,
    slide_theme: Theme,
    provider: GlyphProvider,
) -> list[str]:
    if axis is None or axis.deleted:
        return []
    parts: list[str] = []
    value = vmin
    while value <= vmax + 1e-9:
        y = py + ph * (1 - (value - vmin) / (vmax - vmin))
        parts.extend(
            _label_markup(
                _format_number(value),
                provider,
                theme,
                slide_theme,
                x=px - _AXIS_GAP / 2,
                baseline=y,
                anchor="end",
                valign="middle",
                size_pt=axis.label_size_pt or 10.0,
                color=axis.label_color,
                font=axis.label_font,
                ea_font=axis.label_ea_font,
            )
        )
        value += unit
    return parts


# --------------------------------------------------------------------------
# 标签
# --------------------------------------------------------------------------


def _label_markup(
    text: str,
    provider: GlyphProvider,
    theme: Theme,
    slide_theme: Theme,
    *,
    x: float,
    baseline: float,
    anchor: str = "start",
    valign: str = "baseline",
    size_pt: float = 10.0,
    color: Optional[Color] = None,
    font: Optional[str] = None,
    ea_font: Optional[str] = None,
    rotation: float = 0.0,
) -> list[str]:
    """画一行标签（矢量轮廓，和其他文字一样不依赖观看者的字体）。

    ``rotation`` 不为 0 时按 Excel 的规矩摆：**文字末端钉在 (x, y) 上，
    整体朝斜下方展开**（底轴的斜标签就该这样，否则会压进绘图区）。
    """
    if not text or provider is None:
        return []
    vt = vector_text(
        text,
        provider,
        theme,
        font=_resolve_font(font, theme, slide_theme, latin=True),
        ea_font=_resolve_font(ea_font, theme, slide_theme, latin=False),
        size_pt=size_pt,
        color=color,
    )
    if vt is None:
        return []

    if rotation:
        base_x = {"start": x + vt.width, "middle": x + vt.width / 2, "end": x}.get(
            anchor, x
        )
        inner = (
            f'<g transform="translate({base_x:.2f},{baseline:.2f}) '
            f'rotate({rotation:.4f}) translate({-vt.width:.2f},{-vt.ascent:.2f})">'
            f"{vt.path}</g>"
        )
        return [inner]

    dx = {"start": 0.0, "middle": -vt.width / 2, "end": -vt.width}.get(anchor, 0.0)
    if valign == "middle":
        dy = (vt.ascent - vt.descent) / 2 - vt.ascent
    else:
        dy = -vt.ascent
    inner = f'<g transform="translate({x + dx:.2f},{baseline + dy:.2f})">{vt.path}</g>'
    return [inner]


def _resolve_font(
    token: Optional[str], theme: Theme, slide_theme: Theme, latin: bool
) -> Optional[str]:
    """主题字体槽（``+mn-lt`` / ``+mn-ea``）→ 具体字体名。"""
    if not token:
        return None
    if token.startswith("+"):
        resolved = theme.font_for(token, is_heading=token.startswith("+mj"))
        if resolved:
            return resolved
        return slide_theme.font_for(token, is_heading=token.startswith("+mj"))
    return token


def _format_number(value: float) -> str:
    """按 Excel 的 General 格式输出一个数（去掉多余的尾零）。"""
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    return text


def _point_title(
    chart: Chart, series, idx: int, value: float, total: float
) -> str:
    """数据点的 tooltip 文本。"""
    parts: list[str] = []
    if series.name:
        parts.append(series.name)
    if idx < len(chart.categories):
        parts.append(chart.categories[idx])
    parts.append(_format_number(value))
    if chart.kind in ("pie", "doughnut") and total:
        parts.append(f"{value / total * 100:.1f}%")
    return " · ".join(p for p in parts if p)


# --------------------------------------------------------------------------
# 颜色
# --------------------------------------------------------------------------


def _plot_rect(chart: Chart, width: float, height: float) -> tuple[float, float, float, float]:
    """绘图区（手工布局优先，否则用整个形状）。"""
    if chart.layout:
        x, y, w, h = chart.layout
        return x * width, y * height, w * width, h * height
    return 0.0, 0.0, width, height


def _point_color(
    chart: Chart, series, idx: int, theme: Theme, gradients: GradientRegistry
) -> Optional[str]:
    """数据点的颜色：显式 dPt > 系列填充 > 主题配色循环。"""
    for point in series.points:
        if point.idx != idx:
            continue
        if point.fill is not None and point.fill.kind != "none":
            return _fill_css(point.fill, theme, gradients)
    if series.fill is not None and series.fill.kind != "none":
        return _fill_css(series.fill, theme, gradients)
    if chart.vary_colors and chart.color_cycle:
        slot = chart.color_cycle[idx % len(chart.color_cycle)]
        color = theme.color(slot)
        if color:
            return f"#{color.lstrip('#').upper()}"
    return None


def _fill_css(
    fill: Fill, theme: Theme, gradients: GradientRegistry
) -> Optional[str]:
    if fill.kind == "solid" and fill.color is not None:
        return fill.color.to_css(theme)
    if fill.kind == "gradient" and fill.gradient is not None:
        return gradients.register(fill.gradient, theme)
    return None

