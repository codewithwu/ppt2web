"""OOXML 底层读取工具（标准库实现）。

这里直接啃原始 XML —— python-pptx 的高层 API 覆盖不到渐变、
custGeom、项目符号、阴影、动画行为树这些东西。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Optional

from ..model import Color, Fill, Gradient, GradientStop, Line
from ..ooxml import find, findall, qn
from .theme import resolve_slot


def read_color(parent: Optional[ET.Element]) -> Optional[Color]:
    """从一个父元素里读颜色（solidFill / rPr / pPr 都能用）。"""
    if parent is None:
        return None
    fill = find(parent, "a:solidFill")
    if fill is None:
        return None
    return _color_from_fill(fill)


def _color_from_fill(fill: ET.Element) -> Optional[Color]:
    color = Color()
    srgb = find(fill, "a:srgbClr")
    scheme = find(fill, "a:schemeClr")
    sysc = find(fill, "a:sysClr")
    if srgb is not None:
        color.rgb = srgb.get("val")
    elif scheme is not None:
        # 主题色槽的别名（tx1 / bg1 / tx2 / bg2）要映射到真正的槽名，
        # 否则去主题里查不到 → 颜色变成 transparent
        color.theme = resolve_slot(scheme.get("val"))
        _apply_color_modifiers(scheme, color)
    elif sysc is not None:
        color.rgb = sysc.get("lastClr") or "000000"
    else:
        return None
    return color


def _apply_color_modifiers(scheme: ET.Element, color: Color) -> None:
    for child in scheme:
        tag = child.tag.split("}")[-1]
        value = child.get("val")
        if value is None:
            continue
        if tag == "tint":
            color.tint = int(value) / 100000
        elif tag == "shade":
            color.shade = int(value) / 100000
        elif tag == "alpha":
            color.alpha = int(value) / 100000
        elif tag == "lumMod":
            color.lum_mod = int(value) / 100000
        elif tag == "lumOff":
            color.lum_off = int(value) / 100000


def read_fill(sp_pr: Optional[ET.Element]) -> Fill:
    """读 a:spPr / a:grpSpPr 下的填充。"""
    if sp_pr is None:
        return Fill(kind="none")
    if find(sp_pr, "a:noFill") is not None:
        return Fill(kind="none")
    if find(sp_pr, "a:blipFill") is not None:
        return _read_blip_fill(find(sp_pr, "a:blipFill"))
    grad = find(sp_pr, "a:gradFill")
    if grad is not None:
        return Fill(kind="gradient", gradient=_read_gradient(grad))
    patt = find(sp_pr, "a:pattFill")
    if patt is not None:
        return Fill(kind="pattern", pattern={"prst": patt.get("prst")})
    solid = find(sp_pr, "a:solidFill")
    if solid is not None:
        color = _color_from_fill(solid)
        alpha = color.alpha if (color and color.alpha is not None) else None
        return Fill(kind="solid", color=color, alpha=alpha)
    if find(sp_pr, "a:grpFill") is not None:
        return Fill(kind="group")
    return Fill(kind="none")


def _read_blip_fill(blip_fill: ET.Element) -> Fill:
    """读图片填充（``a:blipFill``）。

    这是"形状被一张图填充"，和 ``<p:pic>`` 是两回事 —— 源文件里第 9/17/21 页
    的照片就是这么放的（``<p:sp>`` + ``a:blipFill``），不是图片图元。
    以前这里只返回 ``kind="blip"``，内容全丢，图就整个消失了。

    ``a:fillRect`` 描述图片覆盖形状内哪一块：l/t/r/b 是比例（1/100000），
    **负值表示图片比形状大**（出血）。这里只记比例，图片本体由解析层补。
    """
    fill = Fill(kind="blip")
    # ``a:fillRect`` 在 ``a:stretch`` / ``a:tile`` **里面**，
    # 不是 a:blipFill 的直接子节点 —— 只找直接子节点会漏掉它。
    rect = find(blip_fill, "a:stretch/a:fillRect")
    if rect is None:
        rect = find(blip_fill, "a:tile/a:fillRect")
    if rect is not None:
        def val(name: str) -> float:
            raw = rect.get(name)
            return int(raw) / 100000 if raw is not None else 0.0

        fill.blip_rect = (val("l"), val("t"), val("r"), val("b"))
    return fill


def read_text_fill(r_pr: Optional[ET.Element]) -> Optional[Fill]:
    """读 run 级文字填充（渐变文字）。

    PowerPoint 可以给文字本身填渐变（``a:rPr/a:gradFill``）——这份稿子的
    章节标题全是橙黄渐变，不读它就会渲染成黑色。
    只返回"非纯色"的填充：纯色走 :func:`read_color` 的 color 通道。
    """
    if r_pr is None:
        return None
    grad = find(r_pr, "a:gradFill")
    if grad is not None:
        return Fill(kind="gradient", gradient=_read_gradient(grad))
    patt = find(r_pr, "a:pattFill")
    if patt is not None:
        return Fill(kind="pattern", pattern={"prst": patt.get("prst")})
    return None


def _read_gradient(grad: ET.Element) -> Gradient:
    g = Gradient()
    lin = find(grad, "a:lin")
    path = find(grad, "a:path")
    if lin is not None:
        g.kind = "linear"
        g.angle = int(lin.get("ang", 0)) / 60000
        g.rotate_with_shape = lin.get("rotWithShape") != "0"
    elif path is not None:
        g.kind = "path"
        fill_rect = find(path, "a:fillToRect")
        if fill_rect is not None:
            g.center = (
                int(fill_rect.get("l", 50000)) / 100000,
                int(fill_rect.get("t", 50000)) / 100000,
            )
    else:
        g.kind = "linear"
    gs_lst = find(grad, "a:gsLst")
    for gs in findall(gs_lst, "a:gs"):
        pos = int(gs.get("pos", 0)) / 100000
        color = None
        srgb = find(gs, "a:srgbClr")
        scheme = find(gs, "a:schemeClr")
        if srgb is not None:
            color = Color(rgb=srgb.get("val"))
        elif scheme is not None:
            color = Color(theme=scheme.get("val"))
            _apply_color_modifiers(scheme, color)
        g.stops.append(GradientStop(position=pos, color=color or Color()))
    return g


def read_line(sp_pr: Optional[ET.Element]) -> Optional[Line]:
    """读 a:ln。返回 None 表示没有描边。"""
    if sp_pr is None:
        return None
    ln = find(sp_pr, "a:ln")
    if ln is None:
        return None
    if find(ln, "a:noFill") is not None:
        return None
    line = Line()
    line.width_emu = int(ln.get("w") or 0)
    if ln.get("cap"):
        line.cap = ln.get("cap")
    if ln.get("cmpd"):
        line.join = ln.get("cmpd")
    solid = find(ln, "a:solidFill")
    if solid is not None:
        line.color = _color_from_fill(solid)
    prst_dash = find(ln, "a:prstDash")
    if prst_dash is not None:
        line.dash = prst_dash.get("val")
    return line


def read_xfrm(el: Optional[ET.Element]) -> Optional[dict[str, Any]]:
    """读 xfrm，返回 off/ext/chOff/chExt/rot/flip。"""
    if el is None:
        return None
    off = find(el, "a:off")
    ext = find(el, "a:ext")
    if off is None or ext is None:
        return None
    data: dict[str, Any] = {
        "x": int(off.get("x", 0)),
        "y": int(off.get("y", 0)),
        "cx": int(ext.get("cx", 0)),
        "cy": int(ext.get("cy", 0)),
        "rot": int(el.get("rot") or 0) / 60000,
        "flip_h": el.get("flipH") == "1",
        "flip_v": el.get("flipV") == "1",
    }
    ch_off = find(el, "a:chOff")
    ch_ext = find(el, "a:chExt")
    if ch_off is not None and ch_ext is not None:
        data["chx"] = int(ch_off.get("x", 0))
        data["chy"] = int(ch_off.get("y", 0))
        data["chcx"] = int(ch_ext.get("cx", 0)) or 1
        data["chcy"] = int(ch_ext.get("cy", 0)) or 1
    return data


def read_shadow(sp_pr: Optional[ET.Element]) -> Optional[dict[str, Any]]:
    """读外阴影 a:outerShdw。"""
    if sp_pr is None:
        return None
    shdw = find(sp_pr, "a:effectLst/a:outerShdw")
    if shdw is None:
        return None
    color = None
    srgb = find(shdw, "a:srgbClr")
    scheme = find(shdw, "a:schemeClr")
    if srgb is not None:
        color = Color(rgb=srgb.get("val"))
    elif scheme is not None:
        color = Color(theme=scheme.get("val"))
    alpha = color.alpha if (color and color.alpha is not None) else 1.0
    return {
        "blur_emu": int(shdw.get("blurRad") or 0),
        "dist_emu": int(shdw.get("dist") or 0),
        "dir_deg": int(shdw.get("dir") or 0) / 60000,
        "sx": int(shdw.get("sx") or 100000) / 100000,
        "sy": int(shdw.get("sy") or 100000) / 100000,
        "color": color,
        "alpha": alpha,
    }


def read_crop(shape_el: ET.Element) -> Optional[dict[str, float]]:
    """读 a:srcRect 裁剪（比例 0~1）。"""
    src_rect = find(shape_el, "p:blipFill/a:srcRect")
    if src_rect is None:
        return None

    def val(name: str) -> float:
        raw = src_rect.get(name)
        return int(raw) / 100000 if raw is not None else 0.0

    crop = {"l": val("l"), "t": val("t"), "r": val("r"), "b": val("b")}
    if not any(crop.values()):
        return None
    return crop
