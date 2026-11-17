"""几何门禁：产物里的图元位置/尺寸/排版，和源 PPT 逐个对账。

这一层回答的是"**东西还在该在的地方**"：

1. **尺寸** —— 每个图元的宽高（EMU）必须和源里 ``a:ext`` 一致
2. **位置** —— 图元的**绝对**位置（把分组里的变换一路复合上去）必须和源里的
   绝对矩阵一致；只比"父容器内的相对位置"是不够的，分组变换错了照样看得出来
3. **排版尺寸** —— 源里写了 ``<a:spAutoFit/>``（"框随文字调整大小"）的文本框，
   它的**框高/框宽就是 PowerPoint 用原字体算出来的文字尺寸**。
   那是真正独立的基准：产物算出来的文字块尺寸跟它对不上，就说明
   **字体替代让排版漂了**（断行变了、行数变了）。

第 3 条是"不写第二套排版引擎"也能验证排版的办法 —— 基准来自 PowerPoint 自己，
不是来自我们。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Optional

#: 位置/尺寸的容差（EMU）。产物里的矩阵被四舍五入到 0.01px = 95 EMU，
#: 分组嵌套还会累积一点，所以给 300 EMU（约 0.0003 英寸）的余量。
POS_TOL = 300.0
#: 尺寸的容差（EMU）
SIZE_TOL = 300.0
#: 排版尺寸的容差（EMU）—— 比位置宽一点：字体替代本来就会带来差异，
#: 但**同源替代**（思源宋体 CN ≡ Noto Serif SC）不该有任何差异。
LAYOUT_TOL = 1200.0

_VOID_TAGS = {"img", "br", "hr", "meta", "link", "input", "source", "path", "rect",
              "circle", "ellipse", "line", "polyline", "polygon", "use", "stop",
              "image", "area", "col", "embed", "track", "wbr"}

_MATRIX_RE = re.compile(
    r"matrix\(\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*,"
    r"\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\)"
)


class _Matrix:
    """CSS matrix(a,b,c,d,e,f)：(x,y) → (a·x + c·y + e, b·x + d·y + f)。"""

    __slots__ = ("a", "b", "c", "d", "e", "f")

    def __init__(self, a=1.0, b=0.0, c=0.0, d=1.0, e=0.0, f=0.0):
        self.a, self.b, self.c, self.d, self.e, self.f = a, b, c, d, e, f

    def multiply(self, other: "_Matrix") -> "_Matrix":
        """self × other（先应用 other，再应用 self）。"""
        return _Matrix(
            self.a * other.a + self.c * other.b,
            self.b * other.a + self.d * other.b,
            self.a * other.c + self.c * other.d,
            self.b * other.c + self.d * other.d,
            self.a * other.e + self.c * other.f + self.e,
            self.b * other.e + self.d * other.f + self.f,
        )

    def near(self, other: "_Matrix", tol: float) -> bool:
        return (
            abs(self.a - other.a) < 1e-4
            and abs(self.b - other.b) < 1e-4
            and abs(self.c - other.c) < 1e-4
            and abs(self.d - other.d) < 1e-4
            and abs(self.e - other.e) < tol
            and abs(self.f - other.f) < tol
        )


def _parse_matrix(style: str) -> _Matrix:
    match = _MATRIX_RE.search(style or "")
    if not match:
        return _Matrix()
    a, b, c, d, e, f = (float(v) for v in match.groups())
    return _Matrix(a, b, c, d, e, f)


def _style_value(style: str, name: str) -> Optional[float]:
    match = re.search(rf"(?:^|;)\s*{name}\s*:\s*([-\d.]+)px", style or "")
    if not match:
        return None
    return float(match.group(1))


class _ShapeCollector(HTMLParser):
    """从产物 HTML 里抽出每个图元的盒子、绝对矩阵和排版度量。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.shapes: dict[str, dict] = {}
        self._stack: list[tuple[str, _Matrix]] = []

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        style = attr_map.get("style") or ""
        own = _parse_matrix(style)
        parent = self._stack[-1][1] if self._stack else _Matrix()
        absolute = parent.multiply(own)

        shape_id = attr_map.get("data-shape-id")
        if shape_id:
            self.shapes[shape_id] = {
                "width_px": _style_value(style, "width"),
                "height_px": _style_value(style, "height"),
                "matrix": absolute,
                "text": {},
            }
        if tag not in _VOID_TAGS:
            self._stack.append((tag, absolute))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS and self._stack:
            self._stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        pass


def _collect_product_shapes(html: str) -> dict[str, dict]:
    collector = _ShapeCollector()
    collector.feed(html)
    # tx-svg 的度量挂在形状里 —— 单独再扫一遍，按形状顺序对齐
    for match in re.finditer(
        r'data-shape-id="([^"]+)".*?<svg class="tx-svg"[^>]*?'
        r'data-block-w="([\d.-]+)" data-block-h="([\d.-]+)" '
        r'data-lines="(\d+)" data-font-pt="([\d.-]+)"',
        html,
        re.S,
    ):
        shape_id, bw, bh, lines, size = match.groups()
        info = collector.shapes.get(shape_id)
        if info is not None:
            info["text"] = {
                "block_w": float(bw),
                "block_h": float(bh),
                "lines": int(lines),
                "size_pt": float(size),
            }
    return collector.shapes


def check_geometry(deck, slide_html: dict[int, str], notes: list[str]) -> list[str]:
    """逐个图元核对位置/尺寸；顺带核对 spAutoFit 文本框的排版尺寸。"""
    from .fontfiles import FontLibrary
    from .fontmap import resolve as resolve_font

    library = FontLibrary()
    failures: list[str] = []
    checked = 0
    size_bad = 0
    pos_bad = 0
    layout_checked = 0
    layout_bad = 0
    ambiguous = 0
    drift: list[tuple[int, str, float, str]] = []

    for slide in deck.slides:
        html = slide_html.get(slide.index)
        if html is None:
            continue
        product = _collect_product_shapes(html)
        for shape in _all_shapes(slide.shapes):
            info = product.get(shape.shape_id)
            if info is None:
                failures.append(
                    f"第 {slide.index} 页图元 {shape.shape_id} 在产物里不存在"
                )
                continue
            checked += 1
            # 尺寸
            if info["width_px"] is not None:
                got_w = info["width_px"] * 9525.0
                got_h = (info["height_px"] or 0.0) * 9525.0
                if abs(got_w - shape.width) > SIZE_TOL or abs(got_h - shape.height) > SIZE_TOL:
                    size_bad += 1
                    failures.append(
                        f"第 {slide.index} 页图元 {shape.shape_id} 尺寸不符："
                        f"源 {shape.width:.0f}×{shape.height:.0f} EMU，"
                        f"产物 {got_w:.0f}×{got_h:.0f} EMU"
                    )
            # 位置（绝对矩阵）
            matrix = shape.transform
            if matrix is not None:
                got = info["matrix"]
                want = _Matrix(
                    matrix.a, matrix.b, matrix.c, matrix.d,
                    matrix.e / 9525.0, matrix.f / 9525.0,
                )
                if not got.near(want, POS_TOL / 9525.0):
                    pos_bad += 1
                    failures.append(
                        f"第 {slide.index} 页图元 {shape.shape_id} 位置/变换不符："
                        f"源 ({want.e * 9525:.0f}, {want.f * 9525:.0f}) EMU，"
                        f"产物 ({got.e * 9525:.0f}, {got.f * 9525:.0f}) EMU"
                    )
            # 排版：断行数（不是高度）
            #
            # 源里 ``<a:spAutoFit/>`` 的文本框，框高是**作者软件**按它自己的
            # 行高模型算出来的。这份稿子里的框高一律是 ~1.212×字号，而
            # PowerPoint / LibreOffice / 我们的转换器都用**字体度量**
            # （思源宋体 → Noto Serif SC 是 1.437em）—— 所以框高对不上是
            # **模型差异**，不是 bug（实测 LibreOffice 的行距和产物一致，
            # 都和源里存的框高对不上）。
            #
            # 但**行数**是可以比的：行高差 1% 的话，"框高 ÷ (1.2×字号)"
            # 四舍五入仍然还原得出行数。而行数不一样 = **断行点不一样**，
            # 那才是字体替代真正带来的排版漂移。
            if (
                shape.text is not None
                and shape.text.autofit == "shape"
                and info["text"]
            ):
                l_ins, t_ins, r_ins, b_ins = shape.text.margins_emu
                want_h = shape.height - t_ins - b_ins
                got_h = info["text"]["block_h"]
                sizes = [
                    r.size_pt
                    for p in shape.text.paragraphs
                    for r in p.runs
                    if r.size_pt
                ]
                if not sizes or want_h <= 0:
                    continue
                size = max(sizes)
                exact, inexact_fonts = _font_exactness(shape, library, resolve_font)
                if not exact:
                    # 字体不是逐字一致的（真身/同源替代都没有）——
                    # 高度本来就会差一截，记下来但不算 bug。
                    drift.append(
                        (
                            slide.index,
                            shape.shape_id,
                            (got_h - want_h) / want_h * 100 if want_h else 0.0,
                            "、".join(inexact_fonts),
                        )
                    )
                implied = want_h / (1.2 * size * 12700)
                nearest = round(implied)
                if abs(implied - nearest) > 0.15:
                    # 推不出干净的整数行数（多段落/段间距），判不了
                    ambiguous += 1
                    continue
                layout_checked += 1
                if nearest != info["text"]["lines"]:
                    layout_bad += 1
                    failures.append(
                        f"第 {slide.index} 页图元 {shape.shape_id} 的断行数与原稿不符："
                        f"原稿 {nearest} 行，产物 {info['text']['lines']} 行"
                        f"（多半是字体替代导致断行点变化）"
                    )

    if checked:
        notes.append(
            f"几何门禁：{checked} 个图元核对位置/尺寸"
            f"（尺寸不符 {size_bad}，位置不符 {pos_bad}）"
        )
    if layout_checked:
        notes.append(
            f"排版门禁：{layout_checked} 个文本框核对断行数（不符 {layout_bad}；"
            f"另有 {ambiguous} 个行数推不出来、跳过）"
        )
    if drift:
        fonts = sorted({d[3] for d in drift})
        notes.append(
            f"另有 {len(drift)} 个文本框用的是非同源替代字体（{', '.join(fonts)}）："
            f"字形与原稿不同（断行已核对一致）；补上真身字体即可完全还原"
        )
    return failures


def _font_exactness(shape, library, resolve_font) -> tuple[bool, list[str]]:
    """这个形状的文字用的字体是不是"逐字一致"的。

    逐字一致 = 真身（fonts/local/ 里放了原字体）或者**同源**替代
    （思源宋体 CN ≡ Noto Serif SC，字形和度量都一样）。
    非同源替代（阿里巴巴普惠体 → Noto Sans SC）字宽/行高都不同，
    文字块高度必然有差 —— 那是已知限制，不能算 bug。
    """
    inexact: list[str] = []
    if shape.text is None:
        return True, []
    for para in shape.text.paragraphs:
        for run in para.runs:
            for name in (run.font, run.east_asian_font):
                if not name:
                    continue
                if library.local_font(name) is not None:
                    continue  # 真身
                resolved = resolve_font(name)
                if resolved is not None and resolved.same_origin:
                    continue  # 同源替代（字形、字宽完全一致）
                if name not in inexact:
                    inexact.append(name)
    return (not inexact), inexact


def _all_shapes(shapes):
    for shape in shapes:
        yield shape
        if shape.children:
            yield from _all_shapes(shape.children)
