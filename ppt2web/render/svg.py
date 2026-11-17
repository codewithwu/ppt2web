"""预设几何（a:prstGeom）→ SVG。

OOXML 有 ~190 种预设几何，这里先覆盖高频的一批；
未覆盖的退回矩形，并在覆盖报告里标注（M1 补全）。
"""

from __future__ import annotations

import math
from typing import Callable, Optional

#: 路径角色：
#: * ``both``   —— 既填充又描边（绝大多数形状）
#: * ``fill``   —— 只填充（ECMA 里 fill="norm" stroke="false" 的那条）
#: * ``stroke`` —— 只描边（ECMA 里 fill="none" stroke="true" 的那条）
BOTH = "both"
FILL = "fill"
STROKE = "stroke"


def geom_paths(
    prst: Optional[str],
    adj: dict,
    width: float,
    height: float,
    geom_path: Optional[str] = None,
) -> list[tuple[str, str]]:
    """返回 ``[(path d, 角色)]``。

    一个预置形状可能有多条路径，各自有不同的填充/描边约定 ——
    ``arc`` 就是这样：填充是扇形，描边只有那圈弧线。
    """
    w = max(width, 1.0)
    h = max(height, 1.0)
    if prst == "custom":
        # a:custGeom：自定义路径，坐标在它自己的 w×h 空间里
        markup = custgeom_svg(geom_path, width, height)
        if markup:
            return [(markup, BOTH)]
        return [(f'<rect x="0" y="0" width="{w}" height="{h}"/>', BOTH)]
    if prst in (None, "none"):
        return [(f'<rect x="0" y="0" width="{w}" height="{h}"/>', BOTH)]

    if prst == "arc":
        return _arc_paths(w, h, adj)

    fn = _PATHS.get(prst)
    if fn is None:
        return [(f'<rect x="0" y="0" width="{w}" height="{h}"/>', BOTH)]
    d = fn(w, h, adj)
    if not d:
        return [(f'<rect x="0" y="0" width="{w}" height="{h}"/>', BOTH)]
    return [(f'<path d="{d}"/>', BOTH)]


def geom_svg(
    prst: Optional[str],
    adj: dict,
    width: float,
    height: float,
    geom_path: Optional[str] = None,
) -> str:
    """返回 <svg> 内部内容；viewBox 用形状自身的 EMU 尺寸。"""
    return "".join(
        markup for markup, _role in geom_paths(prst, adj, width, height, geom_path)
    )


def custgeom_svg(geom_path: Optional[str], width: float, height: float) -> str:
    """``a:custGeom`` 的路径 → SVG path。

    路径坐标在 custGeom 自己的 ``w×h`` 空间里，要缩放到形状尺寸；
    用 ``transform=scale()`` 一步搞定，viewBox 仍是 EMU。
    """
    if not geom_path:
        return ""
    head, sep, body = geom_path.partition("|")
    if not sep:
        return ""
    try:
        path_w, path_h = (int(v) for v in head.split("x", 1))
    except ValueError:
        return ""
    if not path_w or not path_h:
        return ""
    d = body.strip()
    if not d:
        return ""
    sx = width / path_w
    sy = height / path_h
    return f'<path d="{d}" transform="scale({sx:.6f},{sy:.6f})"/>'


def _r(x: float) -> str:
    return f"{round(x, 2)}"


# --------------------------------------------------------------------------
# 路径生成器：参数 (w, h, adj) → SVG path d
# --------------------------------------------------------------------------


def _rect(w: float, h: float, adj) -> str:
    return f"M 0 0 L {_r(w)} 0 L {_r(w)} {_r(h)} L 0 {_r(h)} Z"


def _round_rect(w: float, h: float, adj) -> str:
    adj_val = adj.get("adj", 16667) / 100000 if isinstance(adj.get("adj"), int) else 0.16667
    radius = min(w, h) * adj_val
    return (
        f"M {_r(radius)} 0 L {_r(w - radius)} 0 "
        f"A {_r(radius)} {_r(radius)} 0 0 1 {_r(w)} {_r(radius)} "
        f"L {_r(w)} {_r(h - radius)} "
        f"A {_r(radius)} {_r(radius)} 0 0 1 {_r(w - radius)} {_r(h)} "
        f"L {_r(radius)} {_r(h)} "
        f"A {_r(radius)} {_r(radius)} 0 0 1 0 {_r(h - radius)} "
        f"L 0 {_r(radius)} "
        f"A {_r(radius)} {_r(radius)} 0 0 1 {_r(radius)} 0 Z"
    )


def _ellipse(w: float, h: float, adj) -> str:
    rx, ry = w / 2, h / 2
    return (
        f"M 0 {_r(ry)} A {_r(rx)} {_r(ry)} 0 1 1 {_r(w)} {_r(ry)} "
        f"A {_r(rx)} {_r(ry)} 0 1 1 0 {_r(ry)} Z"
    )


def _triangle(w: float, h: float, adj) -> str:
    return f"M {_r(w / 2)} 0 L {_r(w)} {_r(h)} L 0 {_r(h)} Z"


def _triangle_up(w: float, h: float, adj) -> str:
    return f"M {_r(w / 2)} 0 L {_r(w)} {_r(h)} L 0 {_r(h)} Z"


def _diamond(w: float, h: float, adj) -> str:
    return f"M {_r(w / 2)} 0 L {_r(w)} {_r(h / 2)} L {_r(w / 2)} {_r(h)} L 0 {_r(h / 2)} Z"


def _parallelogram(w: float, h: float, adj) -> str:
    off = w * 0.25
    return f"M {_r(off)} 0 L {_r(w)} 0 L {_r(w - off)} {_r(h)} L 0 {_r(h)} Z"


def _trapezoid(w: float, h: float, adj) -> str:
    off = w * 0.25
    return f"M {_r(off)} 0 L {_r(w - off)} 0 L {_r(w)} {_r(h)} L 0 {_r(h)} Z"


def _line(w: float, h: float, adj) -> str:
    return f"M 0 {_r(h)} L {_r(w)} 0"


def _arrow_right(w: float, h: float, adj) -> str:
    tail = h * 0.5
    head = w * 0.5
    return (
        f"M 0 {_r(tail / 2)} L {_r(head)} {_r(tail / 2)} "
        f"L {_r(head)} 0 L {_r(w)} {_r(h / 2)} "
        f"L {_r(head)} {_r(h)} L {_r(head)} {_r(h - tail / 2)} L 0 {_r(h - tail / 2)} Z"
    )


def _arrow_left(w: float, h: float, adj) -> str:
    tail = h * 0.5
    head = w * 0.5
    return (
        f"M {_r(w)} {_r(tail / 2)} L {_r(w - head)} {_r(tail / 2)} "
        f"L {_r(w - head)} 0 L 0 {_r(h / 2)} "
        f"L {_r(w - head)} {_r(h)} L {_r(w - head)} {_r(h - tail / 2)} L {_r(w)} {_r(h - tail / 2)} Z"
    )


def _arrow_up(w: float, h: float, adj) -> str:
    tail = w * 0.5
    head = h * 0.5
    return (
        f"M {_r(tail / 2)} {_r(h)} L {_r(tail / 2)} {_r(head)} "
        f"L 0 {_r(head)} L {_r(w / 2)} 0 L {_r(w)} {_r(head)} "
        f"L {_r(w - tail / 2)} {_r(head)} L {_r(w - tail / 2)} {_r(h)} Z"
    )


def _arrow_down(w: float, h: float, adj) -> str:
    tail = w * 0.5
    head = h * 0.5
    return (
        f"M {_r(tail / 2)} 0 L {_r(tail / 2)} {_r(h - head)} "
        f"L 0 {_r(h - head)} L {_r(w / 2)} {_r(h)} L {_r(w)} {_r(h - head)} "
        f"L {_r(w - tail / 2)} {_r(h - head)} L {_r(w - tail / 2)} 0 Z"
    )


def _home_plate(w: float, h: float, adj) -> str:
    off = w * 0.25
    return f"M 0 0 L {_r(w - off)} 0 L {_r(w)} {_r(h / 2)} L {_r(w - off)} {_r(h)} L 0 {_r(h)} Z"


def _chevron(w: float, h: float, adj) -> str:
    off = w * 0.25
    return (
        f"M 0 0 L {_r(w - off)} 0 L {_r(w)} {_r(h / 2)} L {_r(w - off)} {_r(h)} L 0 {_r(h)} "
        f"L {_r(off)} {_r(h / 2)} Z"
    )


def _plus(w: float, h: float, adj) -> str:
    t = min(w, h) * 0.3
    return (
        f"M {_r((w - t) / 2)} 0 L {_r((w + t) / 2)} 0 L {_r((w + t) / 2)} {_r((h - t) / 2)} "
        f"L {_r(w)} {_r((h - t) / 2)} L {_r(w)} {_r((h + t) / 2)} L {_r((w + t) / 2)} {_r((h + t) / 2)} "
        f"L {_r((w + t) / 2)} {_r(h)} L {_r((w - t) / 2)} {_r(h)} L {_r((w - t) / 2)} {_r((h + t) / 2)} "
        f"L 0 {_r((h + t) / 2)} L 0 {_r((h - t) / 2)} L {_r((w - t) / 2)} {_r((h - t) / 2)} Z"
    )


def _star5(w: float, h: float, adj) -> str:
    import math

    cx, cy = w / 2, h / 2
    rx, ry = w / 2, h / 2
    pts = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        radius = 1.0 if i % 2 == 0 else 0.382
        pts.append(f"{_r(cx + rx * radius * math.cos(angle))} {_r(cy + ry * radius * math.sin(angle))}")
    return "M " + " L ".join(pts) + " Z"


def _donut(w: float, h: float, adj) -> str:
    thickness = adj.get("adj", 25000) / 100000 if isinstance(adj.get("adj"), int) else 0.25
    t = min(w, h) * thickness
    return (
        f"M 0 {_r(h / 2)} A {_r(w / 2)} {_r(h / 2)} 0 1 1 {_r(w)} {_r(h / 2)} "
        f"A {_r(w / 2)} {_r(h / 2)} 0 1 1 0 {_r(h / 2)} Z "
        f"M {_r(t)} {_r(h / 2)} A {_r(w / 2 - t)} {_r(h / 2 - t)} 0 1 0 {_r(w - t)} {_r(h / 2)} "
        f"A {_r(w / 2 - t)} {_r(h / 2 - t)} 0 1 0 {_r(t)} {_r(h / 2)} Z"
    )


def _flow_process(w: float, h: float, adj) -> str:
    return _rect(w, h, adj)


def _flow_decision(w: float, h: float, adj) -> str:
    return _diamond(w, h, adj)


def _flow_terminator(w: float, h: float, adj) -> str:
    return _round_rect(w, h, adj)


def _flow_connector(w: float, h: float, adj) -> str:
    return _ellipse(w, h, adj)


def _flow_data(w: float, h: float, adj) -> str:
    return _parallelogram(w, h, adj)


def _bevel(w: float, h: float, adj) -> str:
    return _rect(w, h, adj)


def _adj_int(adj: dict, name: str, default: int) -> int:
    """读一个调整值。非整数（公式形式）就用默认值。"""
    value = adj.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return default
    return value


def _teardrop(w: float, h: float, adj) -> str:
    """``teardrop``：一个圆，右上角被拉成一个尖。

    ``adj``（默认 100000）决定尖伸多远：0 = 缩回圆心，100000 = 正好到角上，
    200000 = 再多伸出一倍（会出框）。

    公式照 ECMA-376 的 teardrop 预置定义（``x1 = hc + adj/100000·wd2``…）。
    """
    value = _adj_int(adj, "adj", 100000)
    a = max(0.0, min(2.0, value / 100000.0))
    wd2, hd2 = w / 2, h / 2
    x1 = wd2 + a * wd2
    y1 = hd2 - a * hd2
    x2 = (wd2 + x1) / 2
    y2 = (hd2 + y1) / 2
    return (
        f"M 0 {_r(hd2)} "
        f"A {_r(wd2)} {_r(hd2)} 0 0 1 {_r(wd2)} 0 "
        f"Q {_r(x2)} 0 {_r(x1)} {_r(y1)} "
        f"Q {_r(w)} {_r(y2)} {_r(w)} {_r(hd2)} "
        f"A {_r(wd2)} {_r(hd2)} 0 0 1 {_r(wd2)} {_r(h)} "
        f"A {_r(wd2)} {_r(hd2)} 0 0 1 0 {_r(hd2)} Z"
    )


def _arc_point(wd2: float, hd2: float, angle: int) -> tuple[float, float]:
    """``arc`` 弧线上的一个点（角度单位 1/60000 度，0 = 3 点方向，顺时针）。

    注意**不是**简单的 ``(wd2·cosθ, hd2·sinθ)``：那样算出来的是"圆上的角度"，
    在椭圆上会偏。OOXML 的映射是 ``tanφ = tanθ · (wd2/hd2)``（保持象限），
    再取椭圆上的点 —— 正方形时 wd2=hd2，退化成普通圆，正好对上。
    """
    rad = math.radians(angle / 60000.0)
    c, s = math.cos(rad), math.sin(rad)
    k = (wd2 / hd2) if hd2 else 1.0
    den = math.sqrt(c * c + k * k * s * s) or 1.0
    return wd2 + wd2 * c / den, hd2 + wd2 * s / den


def _arc_paths(w: float, h: float, adj) -> list[tuple[str, str]]:
    """``arc``：一条细圆弧（ECMA 里 ``arc`` 是"弧线"，不是"粗弧带"）。

    两条路径：填充是**扇形**（从圆心到弧），描边**只有弧线本身** ——
    所以有填充色时是扇形，没填充色时就是一道弧（PowerPoint 里那个形状）。
    """
    adj1 = _adj_int(adj, "adj1", 16200000)
    adj2 = _adj_int(adj, "adj2", 0)
    wd2, hd2 = w / 2, h / 2
    x1, y1 = _arc_point(wd2, hd2, adj1)
    x2, y2 = _arc_point(wd2, hd2, adj2)

    sweep = (adj2 - adj1) / 60000.0
    # ECMA 的 swAng 是 ?: sw11 sw11 sw12 —— sw11 为 0 时取 sw12（+360°），
    # 所以"起止角相同"画出来是**整圆**，不是零长度的弧。
    if sweep <= 0:
        sweep += 360.0
    if sweep >= 359.999:
        # 整圆：SVG 一条弧画不出 360°，拆成两条 180° 的
        mid_x, mid_y = 2 * wd2 - x1, 2 * hd2 - y1
        arc = (
            f"A {_r(wd2)} {_r(hd2)} 0 0 1 {_r(mid_x)} {_r(mid_y)} "
            f"A {_r(wd2)} {_r(hd2)} 0 0 1 {_r(x2)} {_r(y2)}"
        )
    else:
        large = 1 if sweep > 180.0 else 0
        arc = f"A {_r(wd2)} {_r(hd2)} 0 {large} 1 {_r(x2)} {_r(y2)}"
    wedge = f"M {_r(x1)} {_r(y1)} {arc} L {_r(wd2)} {_r(hd2)} Z"
    stroke = f"M {_r(x1)} {_r(y1)} {arc}"
    return [(f'<path d="{wedge}"/>', FILL), (f'<path d="{stroke}"/>', STROKE)]


_PATHS: dict[str, Callable[[float, float, dict], str]] = {
    "rect": _rect,
    "roundRect": _round_rect,
    "round1Rect": _round_rect,
    "round2SameRect": _round_rect,
    "snip1Rect": _rect,
    "ellipse": _ellipse,
    "circle": _ellipse,
    "triangle": _triangle,
    "rtTriangle": _triangle,
    "diamond": _diamond,
    "parallelogram": _parallelogram,
    "trapezoid": _trapezoid,
    "line": _line,
    "straightConnector1": _line,
    "bentConnector1": _line,
    "rightArrow": _arrow_right,
    "leftArrow": _arrow_left,
    "upArrow": _arrow_up,
    "downArrow": _arrow_down,
    "homePlate": _home_plate,
    "chevron": _chevron,
    "plus": _plus,
    "star5": _star5,
    "donut": _donut,
    "teardrop": _teardrop,
    "flowChartProcess": _flow_process,
    "flowChartDecision": _flow_decision,
    "flowChartTerminator": _flow_terminator,
    "flowChartConnector": _flow_connector,
    "flowChartData": _flow_data,
    "bevel": _bevel,
}

#: 所有"真的画得出来"的预置几何（arc 单独处理 —— 它有两条路径，
#: 填充是扇形、描边只有弧线，不能和普通形状一个画法）
SUPPORTED = set(_PATHS) | {"arc", "custom"}
