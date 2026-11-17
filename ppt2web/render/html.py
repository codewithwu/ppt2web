"""幻灯片 HTML 渲染。"""

from __future__ import annotations

import html
from typing import Optional

from ..fontmap import split_by_script
from ..model import Deck, Fill, Picture, Shape, Slide, Theme
from .fontplan import FontPlan
from .gradients import GradientRegistry
from .svg import BOTH, FILL, STROKE, geom_paths

EMU_PER_PX = 9525.0


def emu(v: float) -> float:
    return v / EMU_PER_PX


def pt(v: float) -> float:
    return v


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def render_slide(
    slide: Slide,
    deck: Deck,
    theme: Theme,
    plan: FontPlan,
    provider=None,
    text_mode: str = "html",
    stats: Optional[dict] = None,
    mirror_text: bool = False,
) -> str:
    parts = [
        f'<div class="stage" style="width:{emu(deck.slide_width_emu):.2f}px;'
        f'height:{emu(deck.slide_height_emu):.2f}px">'
    ]
    for shape in slide.shapes:
        parts.append(
            _render_shape(
                shape, theme, plan, provider, text_mode, stats,
                (False, False), mirror_text,
            )
        )
    parts.append("</div>")
    return "\n".join(parts)


def _render_shape(
    shape: Shape,
    theme: Theme,
    plan: FontPlan,
    provider=None,
    text_mode: str = "html",
    stats: Optional[dict] = None,
    flip: tuple[bool, bool] = (False, False),
    mirror_text: bool = False,
) -> str:
    style = [
        "position:absolute",
        "left:0",
        "top:0",
        f"width:{emu(shape.width):.2f}px",
        f"height:{emu(shape.height):.2f}px",
        "transform-origin:0 0",
    ]
    matrix = shape.local_transform or shape.transform
    if matrix and not matrix.is_identity:
        style.append(f"transform:{matrix.to_css_px()}")
    if shape.opacity < 1:
        style.append(f"opacity:{shape.opacity:.4f}")

    classes = ["shell", f"k-{shape.kind}"]
    inner = ""

    # 翻转的奇偶性（祖先组 + 自身）：用来决定文字要不要跟着镜像
    own_flip = (bool(shape.flip_h), bool(shape.flip_v))
    net_flip = (flip[0] != own_flip[0], flip[1] != own_flip[1])

    if shape.kind == "group":
        # 分组保留成嵌套结构：PowerPoint 可以直接给"组"加动画
        inner = "".join(
            _render_shape(
                child, theme, plan, provider, text_mode, stats, net_flip, mirror_text
            )
            for child in shape.children
        )
    elif shape.picture is not None:
        inner = _render_picture(shape)
    elif shape.kind == "chart" and shape.chart is not None:
        from .charts import chart_a11y_text, render_chart

        mirror = (False, False) if mirror_text else net_flip
        rendered = None
        if not shape.chart.unsupported:
            rendered = render_chart(shape, theme, provider, mirror)
        if rendered is not None:
            inner = rendered
            if stats is not None:
                stats["charts"] = stats.get("charts", 0) + 1
        else:
            # 渲染不了也**不能把文字弄丢**：占位框照旧，文字进无障碍层
            inner = _render_placeholder(shape)
            text = chart_a11y_text(shape.chart)
            if text:
                inner += f'<div class="tx-a11y">{text}</div>'
    elif shape.kind == "table" and shape.table is not None:
        from .tables import render_table, table_a11y_html

        mirror = (False, False) if mirror_text else net_flip
        rendered = None
        if not shape.table.unsupported:
            rendered = render_table(shape, theme, provider, mirror)
        if rendered is not None:
            inner = rendered
            if stats is not None:
                stats["tables"] = stats.get("tables", 0) + 1
        else:
            inner = _render_placeholder(shape) + table_a11y_html(shape.table)
    elif shape.kind in ("graphicframe", "chart", "diagram", "table"):
        inner = _render_placeholder(shape)
    else:
        inner = _render_geometry(shape, theme)
        if shape.text and any(p.runs for p in shape.text.paragraphs):
            vector = None
            if text_mode == "vector" and provider is not None:
                from .vectortext import render_vector_text

                vector = render_vector_text(
                    shape,
                    theme,
                    provider,
                    mirror=(False, False) if mirror_text else net_flip,
                )
            # 矢量模式下缺字形 → 这个形状退回 HTML 文字（宁可丑也不能丢字）
            if vector is not None:
                inner += vector
                if stats is not None:
                    stats["vector"] = stats.get("vector", 0) + 1
            else:
                inner += _render_text(
                    shape,
                    theme,
                    plan,
                    mirror=(False, False) if mirror_text else net_flip,
                )
                if stats is not None:
                    stats["html"] = stats.get("html", 0) + 1

    if not inner:
        # 没有可见内容，但仍然保留元素：它可能是动画目标，丢了动画就断链
        inner = ""
    return (
        f'<div class="{" ".join(classes)}" data-shape-id="{_esc(shape.shape_id)}" '
        f'style="{";".join(style)}">'
        f'<div class="anim">'
        f"{inner}"
        f"</div></div>"
    )


def _render_geometry(shape: Shape, theme: Theme) -> str:
    fill = shape.fill

    stroke_attr = "none"
    stroke_w = 0.0
    if shape.line is not None and shape.line.color is not None:
        stroke_attr = shape.line.color.to_css(theme)
        # 线宽的单位必须和 viewBox 一致（**EMU**）—— SVG 的 user unit 就是
        # viewBox 的单位，转成像素的话线会细 9525 倍，8pt 的线只剩 0.001px，
        # 等于没画（第 20 页那 4 个弧就是这么消失的）。
        stroke_w = float(shape.line.width_emu or 12700)

    # 一个预置形状可能有多条路径，填充/描边各走各的（arc：填充是扇形、描边只有弧线）
    geom = list(
        geom_paths(shape.geom, shape.adj, shape.width, shape.height, shape.geom_path)
    )
    fill_paths = [m for m, role in geom if role in (BOTH, FILL)]
    stroke_paths = [m for m, role in geom if role in (BOTH, STROKE)]

    defs: list[str] = []
    body: list[str] = []

    if fill.kind == "blip" and fill.blip is not None:
        # 形状被图片填充（源文件里第 9/17/21 页的照片就是这么放的）
        image = _blip_image(shape, fill.blip)
        if image is not None and fill_paths:
            markup, extra_defs = image
            shape_clip = f"shapeclip{shape.shape_id}"
            defs.append(f'<clipPath id="{shape_clip}">{"".join(fill_paths)}</clipPath>')
            defs.extend(extra_defs)
            body.append(markup.replace("__SHAPE_CLIP__", f"url(#{shape_clip})"))
    else:
        fill_attr = "none"
        if fill.kind == "solid" and fill.color is not None:
            fill_attr = fill.color.to_css(theme)
        elif fill.kind == "gradient" and fill.gradient is not None:
            # SVG 的 fill 属性**不接受 CSS 渐变函数** —— 写进去浏览器会忽略，
            # 形状就变成默认的黑色（第 5 页那个橙红渐变的圆徽章就是这么黑的）。
            # 正确做法：注册成 <defs> 里的 <linearGradient>，再用 url(#id) 引用。
            registry = GradientRegistry(prefix=f"geo{shape.shape_id}-")
            painted = registry.register(fill.gradient, theme)
            if painted:
                fill_attr = painted
                defs = registry.defs
        if fill_attr != "none" and fill_paths:
            body.append(f'<g fill="{fill_attr}">{"".join(fill_paths)}</g>')

    if stroke_paths and stroke_attr != "none":
        body.append(
            f'<g fill="none" stroke="{stroke_attr}" stroke-width="{stroke_w:.2f}">'
            f'{"".join(stroke_paths)}</g>'
        )

    if not body:
        return ""

    defs_markup = f'<defs>{"".join(defs)}</defs>' if defs else ""
    return (
        f'<svg class="geo" viewBox="0 0 {shape.width:.0f} {shape.height:.0f}" '
        f'preserveAspectRatio="none" style="overflow:visible">'
        f"{defs_markup}"
        f'{"".join(body)}</svg>'
    )


def _blip_image(
    shape: Shape, pic: Picture
) -> Optional[tuple[str, list[str]]]:
    """形状的图片填充 → ``<image>``（最后由形状轮廓裁剪）。

    ``a:stretch`` 的字面语义是"把图拉伸铺满填充矩形"，``a:fillRect`` 描述
    填充矩形相对形状的内缩/外扩（**负值 = 图片比形状大，出血**），
    形状轮廓负责把多出来的部分裁掉。

    这里刻意**不保比例**：PowerPoint 的形状填充只有"拉伸/平铺/居中"，
    没有"裁剪填充"那种保比��的选项。

    也不用 CSS ``clip-path`` —— 它吃不了任意 SVG path（预置几何/自定义几何
    在 ``svg.py:geom_paths`` 里都是 path 数据），所以改用 SVG 的
    ``<clipPath>``，图片直接被形状轮廓裁掉。
    """
    src = f"../assets/{pic.part_name.rsplit('/', 1)[-1]}"
    width = shape.width
    height = shape.height
    if width <= 0 or height <= 0:
        return None

    l, t, r, b = shape.fill.blip_rect or (0.0, 0.0, 0.0, 0.0)
    x = l * width
    y = t * height
    iw = (1 - l - r) * width
    ih = (1 - t - b) * height
    if iw <= 0 or ih <= 0:
        return None

    markup = (
        f'<image href="{_esc(src)}" xlink:href="{_esc(src)}" '
        f'x="{x:.2f}" y="{y:.2f}" width="{iw:.2f}" height="{ih:.2f}" '
        f'preserveAspectRatio="none" clip-path="__SHAPE_CLIP__"/>'
    )

    extra_defs: list[str] = []
    crop = pic.crop or {}
    cl = crop.get("l", 0.0)
    ct = crop.get("t", 0.0)
    cr = crop.get("r", 0.0)
    cb = crop.get("b", 0.0)
    if any((cl, ct, cr, cb)):
        # a:srcRect：先把原图裁一块，再拉伸到填充矩形
        vw = max(1e-6, 1 - cl - cr)
        vh = max(1e-6, 1 - ct - cb)
        crop_clip = f"cropclip{shape.shape_id}"
        extra_defs.append(
            f'<clipPath id="{crop_clip}">'
            f'<rect x="{x + cl * iw:.2f}" y="{y + ct * ih:.2f}" '
            f'width="{vw * iw:.2f}" height="{vh * ih:.2f}"/></clipPath>'
        )
        markup = (
            f'<g clip-path="url(#{crop_clip})">{markup}</g>'
        )
    return markup, extra_defs


def _gradient_css(fill: Fill, theme: Theme) -> str:
    grad = fill.gradient
    if grad is None or not grad.stops:
        return "none"
    stops = []
    for stop in grad.stops:
        color = stop.color.to_css(theme) if stop.color else "transparent"
        stops.append(f"{color} {stop.position * 100:.1f}%")
    if grad.kind == "linear":
        # OOXML ang: 0 = 从左到右，顺时针
        return f"linear-gradient({grad.angle:.2f}deg, {', '.join(stops)})"
    cx, cy = grad.center
    return f"radial-gradient(circle at {cx * 100:.1f}% {cy * 100:.1f}%, {', '.join(stops)})"


def _render_picture(shape: Shape) -> str:
    pic = shape.picture
    assert pic is not None
    src = f"../assets/{pic.part_name.rsplit('/', 1)[-1]}"
    crop = pic.crop or {}
    left = crop.get("l", 0.0)
    top = crop.get("t", 0.0)
    right = crop.get("r", 0.0)
    bottom = crop.get("b", 0.0)
    visible_w = max(1e-6, 1 - left - right)
    visible_h = max(1e-6, 1 - top - bottom)
    if not (left or top or right or bottom):
        return (
            f'<img class="pic" src="{_esc(src)}" alt="" '
            f'style="width:100%;height:100%;object-fit:fill;display:block">'
        )
    style = ";".join(
        [
            "position:absolute",
            f"width:{100 / visible_w:.4f}%",
            f"height:{100 / visible_h:.4f}%",
            f"left:{-left / visible_w * 100:.4f}%",
            f"top:{-top / visible_h * 100:.4f}%",
        ]
    )
    return (
        f'<div class="picwrap">'
        f'<img class="pic" src="{_esc(src)}" alt="" style="{style}">'
        f"</div>"
    )


def _render_placeholder(shape: Shape) -> str:
    label = shape.kind
    note = " ".join(shape.notes)
    if len(note) > 40:
        note = note[:37] + "…"
    return (
        f'<div class="gp-placeholder" data-kind="{_esc(label)}">'
        f"<span>{_esc(label)}</span><small>{_esc(note)}</small></div>"
    )


def _render_text(
    shape: Shape,
    theme: Theme,
    plan: FontPlan,
    mirror: tuple[bool, bool] = (False, False),
) -> str:
    tf = shape.text
    assert tf is not None
    l_ins, t_ins, r_ins, b_ins = tf.margins_emu
    style = [
        "position:absolute",
        "left:0",
        "top:0",
        "width:100%",
        "height:100%",
        f"padding:{emu(t_ins):.2f}px {emu(r_ins):.2f}px {emu(b_ins):.2f}px {emu(l_ins):.2f}px",
        "display:flex",
        "flex-direction:column",
        "box-sizing:border-box",
    ]
    if mirror[0] or mirror[1]:
        # 形状翻转了，但文字不跟着镜像（PowerPoint 的行为）
        sx = -1 if mirror[0] else 1
        sy = -1 if mirror[1] else 1
        style.append(f"transform:scale({sx},{sy})")
    anchor = {"t": "flex-start", "ctr": "center", "b": "flex-end"}.get(tf.anchor or "t", "flex-start")
    style.append(f"justify-content:{anchor}")
    if tf.wrap == "none":
        style.append("white-space:nowrap")
    if tf.autofit == "norm" and tf.autofit_font_scale:
        style.append(f"font-size:{tf.autofit_font_scale * 100:.2f}%")

    body = []
    for para in tf.paragraphs:
        body.append(_render_paragraph(para, theme, plan))

    return f'<div class="tx" style="{";".join(style)}">{"".join(body)}</div>'


def _render_paragraph(para, theme: Theme, plan: FontPlan) -> str:
    style = ["margin:0", "padding:0"]
    align = {"l": "left", "ctr": "center", "r": "right", "just": "justify"}.get(
        para.align or "", "left"
    )
    style.append(f"text-align:{align}")
    if para.line_spacing:
        style.append(f"line-height:{para.line_spacing:.4f}")
    elif para.line_spacing_pt:
        style.append(f"line-height:{para.line_spacing_pt:.3f}pt")
    if para.space_before_pt:
        style.append(f"margin-top:{para.space_before_pt:.3f}pt")
    if para.space_after_pt:
        style.append(f"margin-bottom:{para.space_after_pt:.3f}pt")
    if para.margin_left_emu:
        style.append(f"margin-left:{emu(para.margin_left_emu):.2f}px")
    if para.indent_emu:
        style.append(f"text-indent:{emu(para.indent_emu):.2f}px")

    bullet = ""
    if para.bullet_type == "char" and para.bullet:
        color = para.bullet_color.to_css(theme) if para.bullet_color else "currentColor"
        bullet = (
            f'<span class="bul" style="color:{color}">{_esc(para.bullet)}</span>'
        )

    runs = []
    for run in para.runs:
        runs.append(_render_run(run, theme, plan))

    return f'<p style="{";".join(style)}">{bullet}{"".join(runs)}</p>'


def _render_run(run, theme: Theme, plan: FontPlan) -> str:
    if run.text == "\n":
        return "<br>"

    base: list[str] = []
    if run.size_pt:
        base.append(f"font-size:{run.size_pt:.3f}pt")
    if run.bold:
        base.append("font-weight:700")
    if run.italic:
        base.append("font-style:italic")
    if run.underline and run.underline != "none":
        base.append("text-decoration:underline")
    if run.strike and run.strike not in ("noStrike", "none"):
        base.append("text-decoration:line-through")
    if run.baseline:
        if run.baseline > 0:
            base.append("vertical-align:super")
            base.append(f"font-size:{run.size_pt * 0.65:.3f}pt" if run.size_pt else "")
        else:
            base.append("vertical-align:sub")
    if run.spacing_pt:
        base.append(f"letter-spacing:{run.spacing_pt:.3f}pt")
    if run.caps == "all":
        base.append("text-transform:uppercase")

    # 渐变文字：background-clip:text（Chrome/Firefox/Safari 都支持）
    gradient_style: list[str] = []
    if run.fill is not None and run.fill.kind == "gradient":
        gradient_style = [
            f"background-image:{_gradient_css(run.fill, theme)}",
            "background-clip:text",
            "-webkit-background-clip:text",
            "color:transparent",
            "-webkit-text-fill-color:transparent",
        ]
    elif run.color is not None:
        base.append(f"color:{run.color.to_css(theme)}")

    # PowerPoint 按**字符**选字体：中文走 ea 槽、西文走 latin 槽，
    # 两个槽经常不是同一个字体 —— 所以这里按字符分段。
    parts: list[str] = []
    for text, is_ea in split_by_script(run.text):
        font_name = run.east_asian_font if is_ea else run.font
        style = list(base)
        if font_name:
            style.append(f"font-family:{plan.stack_for(font_name)}")
            weight = plan.weight_for(font_name)
            if weight and not run.bold:
                style.append(f"font-weight:{weight}")
        style.extend(gradient_style)
        joined = ";".join(s for s in style if s)
        parts.append(f'<span style="{joined}">{_esc(text)}</span>' if joined else _esc(text))

    return "".join(parts)
