"""几何渲染（预设几何 + custGeom）与主题字体槽的单元测试。"""

from __future__ import annotations

import unittest

from ppt2web.model import Theme
from ppt2web.parse.theme import resolve_font_token
from ppt2web.render.svg import custgeom_svg, geom_paths, geom_svg


class TestGeomSvg(unittest.TestCase):
    def test_矩形(self):
        markup = geom_svg("rect", {}, 1000.0, 500.0)
        self.assertIn("<path", markup)
        self.assertIn("1000", markup)

    def test_未覆盖的几何退回矩形(self):
        markup = geom_svg("完全没见过的形状", {}, 1000.0, 500.0)
        self.assertIn("<rect", markup)

    def test_custgeom_按自身坐标系缩放(self):
        # custGeom 的路径空间是 100x50，形状是 200x100 → 缩放 2 倍
        path = "100x50|M 0 0 L 50 0 L 50 50 L 0 50 Z"
        markup = custgeom_svg(path, 200.0, 100.0)
        self.assertIn("scale(2.000000,2.000000)", markup)
        self.assertIn('d="M 0 0 L 50 0', markup)

    def test_custgeom_空路径(self):
        self.assertEqual(custgeom_svg("", 200.0, 100.0), "")
        self.assertEqual(custgeom_svg(None, 200.0, 100.0), "")
        self.assertEqual(custgeom_svg("坏数据|xxx", 200.0, 100.0), "")

    def test_custgeom_通过_geom_svg_渲染(self):
        path = "100x50|M 0 0 L 50 0 L 50 50 L 0 50 Z"
        markup = geom_svg("custom", {}, 200.0, 100.0, path)
        self.assertIn("<path", markup)
        self.assertIn("scale(", markup)


class TestThemeTokens(unittest.TestCase):
    def setUp(self):
        self.theme = Theme(
            major_latin="Major Latin",
            major_ea="Major EA",
            minor_latin="Minor Latin",
            minor_ea="Minor EA",
        )

    def test_主题槽解析(self):
        self.assertEqual(resolve_font_token(self.theme, "+mj-lt"), "Major Latin")
        self.assertEqual(resolve_font_token(self.theme, "+mj-ea"), "Major EA")
        self.assertEqual(resolve_font_token(self.theme, "+mn-lt"), "Minor Latin")
        self.assertEqual(resolve_font_token(self.theme, "+mn-ea"), "Minor EA")

    def test_按token自身的槽解析(self):
        """真实文件里有 <a:latin typeface="+mj-ea"/> 这种写法。"""
        self.assertEqual(resolve_font_token(self.theme, "+mj-ea"), "Major EA")

    def test_普通字体名原样返回(self):
        self.assertEqual(resolve_font_token(self.theme, "思源宋体 CN"), "思源宋体 CN")

    def test_空值(self):
        self.assertIsNone(resolve_font_token(self.theme, None))
        self.assertIsNone(resolve_font_token(self.theme, ""))


if __name__ == "__main__":
    unittest.main()


class TestPresetGeometry(unittest.TestCase):
    """teardrop / arc —— 和 ECMA-376 的预置定义逐点比对。

    期望值来自 npm 包 ``@pptx-studio/geometry``（完整的 ECMA-376 预置几何
    引擎）算出来的路径，用来当标准答案。
    """

    @staticmethod
    def _numbers(markup: str) -> list[float]:
        import re

        return [
            float(x)
            for x in re.findall(r"-?\d+(?:\.\d+)?", re.sub(r"[A-Za-z]", " ", markup))
        ]

    def test_teardrop的路径(self):
        markup = geom_svg("teardrop", {}, 1000.0, 1000.0)
        expected = [
            0, 500, 500, 500, 0, 0, 1, 500, 0, 750, 0, 1000, 0,
            1000, 250, 1000, 500, 500, 500, 0, 0, 1, 500, 1000,
            500, 500, 0, 0, 1, 0, 500,
        ]
        self.assertEqual(self._numbers(markup), [float(x) for x in expected])

    def test_teardrop的尖随调整值伸长(self):
        # adj=0 → 尖缩回圆心；adj=200000 → 伸到角外一倍
        short = self._numbers(geom_svg("teardrop", {"adj": 0}, 1000.0, 1000.0))
        long = self._numbers(geom_svg("teardrop", {"adj": 200000}, 1000.0, 1000.0))
        self.assertEqual(short[9:12], [500.0, 0.0, 500.0])   # 控制点 (500,0) → (500,500)
        self.assertEqual(long[9:12], [1000.0, 0.0, 1500.0])  # → (1000,0) → (1500,-500)

    def test_arc是两条路径_填充扇形描边只有弧(self):
        paths = geom_paths("arc", {"adj1": 5759947, "adj2": 805288}, 1453964.0, 1453964.0)
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0][1], "fill")
        self.assertEqual(paths[1][1], "stroke")
        # 弧线端点（ECMA 的角度映射：tanφ = tanθ·(wd2/hd2)）
        numbers = self._numbers(paths[1][0])
        self.assertAlmostEqual(numbers[0], 651002.835, places=1)
        self.assertAlmostEqual(numbers[1], 1449982.688, places=1)
        self.assertAlmostEqual(numbers[-2], 1434109.382, places=0)

    def test_arc起止角相同是整圆(self):
        markup = geom_paths("arc", {"adj1": 0, "adj2": 0}, 1000.0, 1000.0)[1][0]
        # SVG 一条弧画不出 360° → 拆成两条 180° 的
        self.assertEqual(markup.count("A"), 2)

    def test_arc默认是四分之一弧(self):
        markup = geom_paths("arc", {}, 1000.0, 1000.0)[1][0]
        self.assertEqual(markup.count("A"), 1)
        self.assertIn("M 500.0 0.0", markup)   # 起点在 12 点方向
        self.assertIn("1000.0 500.0", markup)  # 终点在 3 点方向
