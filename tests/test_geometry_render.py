"""形状几何渲染（填充/描边/坐标）的单元测试。"""

from __future__ import annotations

import unittest

from ppt2web.model import Color, Fill, Line, Shape, Theme
from ppt2web.render.html import _render_geometry

THEME = Theme(colors={"accent2": "ED7D31", "lt1": "FFFFFF"})


def _shape(**kw) -> Shape:
    shape = Shape(shape_id="1", name="x", kind="shape", width=1453964.0, height=1453964.0)
    shape.fill = kw.get("fill", Fill(kind="solid", color=Color(rgb="ED7D31")))
    shape.line = kw.get("line")
    shape.geom = kw.get("geom", "ellipse")
    return shape


class TestRenderGeometry(unittest.TestCase):
    def test_线宽的单位是EMU不是像素(self):
        """SVG 的 user unit = viewBox 的单位（EMU）。

        转成像素的话线会细 9525 倍 —— 8pt 的线只剩 0.001px，等于没画
        （第 20 页那 4 个弧就是这么消失的）。
        """
        shape = _shape(line=Line(color=Color(rgb="ED7D31"), width_emu=101600))
        html = _render_geometry(shape, THEME)
        self.assertIn('stroke-width="101600.00"', html)
        self.assertNotIn('stroke-width="10.67"', html)

    def test_没设线宽时用1pt(self):
        shape = _shape(line=Line(color=Color(rgb="ED7D31"), width_emu=0))
        html = _render_geometry(shape, THEME)
        self.assertIn('stroke-width="12700.00"', html)

    def test_没有填充也没有描边就不画(self):
        shape = _shape(fill=Fill(kind="none"))
        self.assertEqual(_render_geometry(shape, THEME), "")

    def test_圆角矩形的路径(self):
        shape = _shape(geom="roundRect")
        html = _render_geometry(shape, THEME)
        self.assertIn("<path", html)
        self.assertIn("A ", html)   # 圆角是弧


if __name__ == "__main__":
    unittest.main()
