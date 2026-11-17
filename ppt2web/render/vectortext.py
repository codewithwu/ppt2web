"""矢量文字渲染：把排好版的文字变成 SVG 字形轮廓。

产物形如::

    <svg class="tx-svg" viewBox="0 0 宽 高">
      <path d="M ..." fill="#E53815"/>     ← 一行（一个字体一种颜色）一条 path
      ...
    </svg>
    <div class="tx-a11y">深耕 · 笃行致远</div>   ← 无障碍/可搜索/可复制的真实文本

坐标全部是 EMU（和形状的 viewBox 一致），px↔EMU 换算交给 SVG 自己。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..model import Color, Paragraph, Run, Shape, TextFrame, Theme
from .glyphs import EMU_PER_PT, GlyphProvider
from .gradients import GradientRegistry
from .textlayout import PlacedGlyph, TextLayout


@dataclass
class VectorText:
    """一行已经画好的矢量文字。

    ``path`` 是 SVG path 片段（可以有多条，每条自带 fill），
    ``width`` / ``ascent`` / ``descent`` 是 EMU，调用方拿它们定位。
    """

    path: str
    fill: str
    width: float
    ascent: float
    descent: float


def vector_text(
    text: str,
    provider: GlyphProvider,
    theme: Theme,
    *,
    font: Optional[str] = None,
    ea_font: Optional[str] = None,
    size_pt: float = 18.0,
    color: Optional[Color] = None,
) -> Optional[VectorText]:
    """把一行文字画成 SVG path（坐标原点在文字基线左端，单位 EMU）。

    给图表的坐标轴标签、数据标签用 —— 它们不在文本框里，
    但同样要是矢量轮廓（不然就得依赖观看者装字体）。

    缺字形时返回 None。
    """
    if not text:
        return VectorText(path="", fill="#000000", width=0.0, ascent=0.0, descent=0.0)

    run = Run(
        text=text,
        font=font,
        east_asian_font=ea_font,
        size_pt=size_pt,
        color=color,
    )
    para = Paragraph(runs=[run])
    layout = TextLayout(provider, theme)
    out = layout.layout_paragraph(para, 1e9, 0, first=True, wrap=False)
    if not out.lines:
        return None
    line = out.lines[0]
    if not line.glyphs:
        return None

    parts: list[str] = []
    fill = "#000000"
    for group in _group_by_face(line.glyphs):
        path_d, group_fill = _draw_group(group, line.baseline)
        if path_d:
            parts.append(f'<path d="{path_d}" fill="{group_fill}"/>')
            fill = group_fill

    ascent, descent = _metrics(line.glyphs, size_pt)
    return VectorText(
        path="".join(parts),
        fill=fill,
        width=line.width,
        ascent=ascent,
        descent=descent,
    )


def _metrics(glyphs: list[PlacedGlyph], size_pt: float) -> tuple[float, float]:
    """(ascent EMU, descent EMU)。descent 沿用字体的符号约定（负数）。"""
    face = glyphs[0].face
    if face is None:
        return size_pt * EMU_PER_PT * 0.8, size_pt * EMU_PER_PT * -0.2
    scale = size_pt * EMU_PER_PT / face.upem
    return face.ascent * scale, face.descent * scale


def render_vector_text(
    shape: Shape,
    theme: Theme,
    provider: GlyphProvider,
    mirror: tuple[bool, bool] = (False, False),
) -> Optional[str]:
    """返回矢量文字的 HTML（SVG + 无障碍文本层）。

    缺字形时返回 None —— 调用方退回 HTML 文字渲染。
    宁可字形不完美，也不能让文字凭空消失。

    ``mirror``：形状（及其祖先）被水平/垂直翻转过时，文字要不要跟着镜像。
    PowerPoint 翻转形状不会把文字镜像掉，所以默认 False —— 形状的几何照翻，
    文字保持正立。
    """
    tf = shape.text
    assert tf is not None
    # 渐变 id 要在一页之内唯一 → 用形状 id 做前缀
    gradients = GradientRegistry(prefix=f"tx{shape.shape_id}-")
    result = render_text_frame(
        tf, shape.width, shape.height, provider, theme, mirror, gradients
    )
    if result is None:
        return None
    body, a11y_text, metrics = result

    # 排版度量写进 data-* —— 产物自报排版结果，verify 拿它和源文件比对
    svg = (
        f'<svg class="tx-svg" viewBox="0 0 {shape.width:.0f} {shape.height:.0f}" '
        f'preserveAspectRatio="none" style="position:absolute;inset:0;width:100%;height:100%" '
        f'data-block-w="{metrics["block_w"]:.0f}" data-block-h="{metrics["block_h"]:.0f}" '
        f'data-lines="{metrics["lines"]}" data-font-pt="{metrics["size_pt"]:.2f}">'
        f"{body}</svg>"
    )
    a11y = f'<div class="tx-a11y">{a11y_text}</div>' if a11y_text else ""
    return svg + a11y


def render_text_frame(
    tf: TextFrame,
    width: float,
    height: float,
    provider: GlyphProvider,
    theme: Theme,
    mirror: tuple[bool, bool] = (False, False),
    gradients: Optional[GradientRegistry] = None,
) -> Optional[tuple[str, str]]:
    """把一个文本框排成 SVG。

    返回 ``(SVG 片段, 无障碍文本)``；片段的坐标是**文本框自己的** 0..宽/0..高，
    调用方自己决定往哪儿摆（表格的单元格就是靠这个嵌进表格坐标系）。

    缺字形时返回 None。
    """
    if not _has_all_glyphs(tf, provider):
        return None
    if gradients is None:
        gradients = GradientRegistry()
    l_ins, t_ins, r_ins, b_ins = tf.margins_emu
    box_w = max(width - l_ins - r_ins, 1.0)
    box_h = max(height - t_ins - b_ins, 1.0)

    layout = TextLayout(provider, theme)
    wrap = tf.wrap != "none"  # bodyPr wrap="none" → 整段不自动换行
    paragraphs = []
    for index, para in enumerate(tf.paragraphs):
        paragraphs.append(
            layout.layout_paragraph(
                para, box_w, l_ins, first=(index == 0), wrap=wrap
            )
        )

    total = sum(p.height for p in paragraphs)
    anchor = tf.anchor or "t"
    if anchor == "ctr":
        y0 = t_ins + (box_h - total) / 2
    elif anchor == "b":
        y0 = t_ins + (box_h - total)
    else:
        y0 = t_ins

    paths: list[str] = []
    a11y_parts: list[str] = []
    cursor = y0

    for para, para_layout in zip(tf.paragraphs, paragraphs):
        a11y_parts.append(_paragraph_text(para))
        for line in para_layout.lines:
            baseline = line.baseline + cursor
            for group in _group_by_face(line.glyphs):
                path_d, fill = _draw_group(group, baseline, gradients, theme)
                if path_d:
                    paths.append(
                        f'<path d="{path_d}" fill="{fill}"/>'
                    )
        cursor += para_layout.height

    body = "".join(paths)
    if gradients.defs:
        body = f'<defs>{"".join(gradients.defs)}</defs>' + body
    if mirror[0] or mirror[1]:
        # 抵消外层翻转对文字的影响：绕形状自身中心反镜像一次，字就正了
        sx = -1 if mirror[0] else 1
        sy = -1 if mirror[1] else 1
        tx = width if mirror[0] else 0
        ty = height if mirror[1] else 0
        body = f'<g transform="matrix({sx},0,0,{sy},{tx:.0f},{ty:.0f})">{body}</g>'

    metrics = _text_metrics(paragraphs)
    return body, "".join(a11y_parts), metrics


def _text_metrics(paragraphs) -> dict[str, float]:
    """排版结果的度量（EMU）。

    写进产物的 ``data-*`` 属性，让**产物自报排版结果** ——
    ``verify`` 拿它和源文件里 PowerPoint 自己算出来的尺寸比对，
    不需要在 verify 里再写一套排版引擎（那会变成"自己验自己"）。

    源文件里 ``<a:spAutoFit/>`` 的文本框，框高/框宽就是 PowerPoint
    用**原字体**算出来的文字尺寸 —— 那才是真正的独立基准。
    """
    total_h = sum(p.height for p in paragraphs)
    block_w = 0.0
    lines = 0
    size_pt = 0.0
    for para in paragraphs:
        lines += len(para.lines)
        for line in para.lines:
            if not line.glyphs:
                continue
            left = min(g.x for g in line.glyphs)
            right = max(g.x + g.width for g in line.glyphs)
            block_w = max(block_w, right - left)
            for g in line.glyphs:
                size_pt = max(size_pt, g.size_pt or 0.0)
    return {
        "block_h": total_h,
        "block_w": block_w,
        "lines": lines,
        "size_pt": size_pt,
    }


def _paragraph_text(para) -> str:
    return "".join(run.text for run in para.runs)


def _has_all_glyphs(tf: TextFrame, provider: GlyphProvider) -> bool:
    """这个文本框的文字是不是每个字都有轮廓可用。"""
    for para in tf.paragraphs:
        for run in para.runs:
            if not run.text:
                continue
            latin = provider.family(run.font)
            ea = provider.family(run.east_asian_font)
            for ch in run.text:
                if ch in " \n\t":
                    continue
                family = ea if _is_ea(ch) else latin
                if family is None:
                    return False
                if family.face_for(ch) is None:
                    return False
    return True


def _is_ea(ch: str) -> bool:
    from ..fontmap import is_east_asian

    return is_east_asian(ch)


def _group_by_face(glyphs: list[PlacedGlyph]):
    """把连续的同字体同颜色的字形分组（一组一条 path）。"""
    groups = []
    current_key = None
    current: list[PlacedGlyph] = []
    for glyph in glyphs:
        key = (id(glyph.face), glyph.color, glyph.size_pt, id(glyph.gradient))
        if key != current_key:
            if current:
                groups.append(current)
            current = []
            current_key = key
        current.append(glyph)
    if current:
        groups.append(current)
    return groups


def _draw_group(
    group: list[PlacedGlyph],
    baseline: float,
    gradients: Optional[GradientRegistry] = None,
    theme: Optional[Theme] = None,
) -> tuple[str, str]:
    """把一组字形画成一条 path。返回 (path d, fill)。"""
    face = group[0].face
    if face is None or not group[0].glyph_name:
        return "", "#000000"
    try:
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.pens.transformPen import TransformPen
    except ImportError:  # pragma: no cover - 环境问题
        return "", "#000000"

    size_pt = group[0].size_pt or 18.0
    scale = size_pt * EMU_PER_PT / face.upem
    pen = SVGPathPen(face.glyph_set)
    for glyph in group:
        if not glyph.glyph_name:
            continue
        transform = TransformPen(
            pen, (scale, 0.0, 0.0, -scale, glyph.x, baseline)
        )
        try:
            face.draw(glyph.glyph_name, transform)
        except Exception:  # pragma: no cover - 单个字形坏掉不该毁掉整页
            continue
    fill = group[0].color or "#000000"
    gradient = group[0].gradient
    if gradient is not None and gradients is not None and theme is not None:
        # 渐变文字（封面标题那种）：SVG 里用 linearGradient
        fill = gradients.register(gradient, theme) or fill
    return _compact_path(pen.getCommands()), fill


#: path 里的浮点数（SVGPathPen 输出全精度）
_FLOAT_RE = re.compile(r"-?\d+\.\d+")


def _compact_path(d: str) -> str:
    """把 path 坐标压到整数 EMU。

    1 EMU = 1/9525 像素，整数精度远远小于一个像素，肉眼看不出区别，
    但体积能小三分之一。
    """
    return _FLOAT_RE.sub(lambda m: str(int(round(float(m.group(0))))), d)
