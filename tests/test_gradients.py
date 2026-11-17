"""渐变文字的单元测试。

PowerPoint 能给文字本身填渐变（``a:rPr/a:gradFill``）—— 封面标题
「深耕·笃行致远」就是一半橙黄渐变、一半纯黑。矢量模式下必须把它画出来，
否则那四个字会变成黑色（HTML 模式一直是对的，矢量模式漏了）。
"""

from __future__ import annotations

import unittest

from ppt2web.model import (
    Color,
    Gradient,
    GradientStop,
    Paragraph,
    Run,
    Shape,
    TextFrame,
    Theme,
)
from ppt2web.render.gradients import GradientRegistry
from ppt2web.render.glyphs import GlyphProvider
from ppt2web.render.vectortext import render_vector_text

THEME = Theme(colors={"dk1": "000000", "lt1": "FFFFFF"})


def gradient_shape() -> Shape:
    run = Run(
        text="渐变字",
        font="思源宋体 CN",
        east_asian_font="思源宋体 CN",
        size_pt=24.0,
        fill=None,
    )
    run.fill = _gradient_fill()
    shape = Shape(
        shape_id="7",
        name="标题",
        kind="textbox",
        width=400000.0,
        height=100000.0,
        text=TextFrame(paragraphs=[Paragraph(runs=[run])]),
    )
    return shape


def _gradient_fill():
    from ppt2web.model import Fill

    grad = Gradient(
        kind="linear",
        angle=30.0,
        stops=[
            GradientStop(position=0.0, color=Color(rgb="E53815")),
            GradientStop(position=1.0, color=Color(rgb="F8A31A")),
        ],
    )
    return Fill(kind="gradient", gradient=grad)


class TestGradientText(unittest.TestCase):
    def test_渐变文字会生成linearGradient(self):
        shape = gradient_shape()
        html = render_vector_text(shape, THEME, GlyphProvider())
        assert html is not None
        self.assertIn("<linearGradient", html)
        self.assertIn('fill="url(#', html)
        self.assertIn('stop-color="#E53815"', html)
        self.assertIn('stop-color="#F8A31A"', html)

    def test_渐变id一页之内不能重复(self):
        """两个形状各有一个渐变 → id 必须不同，否则浏览器只认第一个。"""
        provider = GlyphProvider()
        ids = []
        for index in (1, 2):
            shape = gradient_shape()
            shape.shape_id = str(index)
            html = render_vector_text(shape, THEME, provider)
            assert html is not None
            marker = 'id="'
            start = html.index("<linearGradient")
            ident = html[html.index('id="', start) + 4 :]
            ids.append(ident.split('"')[0])
        self.assertNotEqual(ids[0], ids[1])
        self.assertIn(str(1), ids[0])
        self.assertIn(str(2), ids[1])

    def test_纯色文字不生成渐变定义(self):
        shape = gradient_shape()
        shape.text.paragraphs[0].runs[0].fill = None
        shape.text.paragraphs[0].runs[0].color = Color(rgb="112233")
        html = render_vector_text(shape, THEME, GlyphProvider())
        assert html is not None
        self.assertNotIn("<linearGradient", html)
        self.assertIn('fill="#112233"', html)


class TestGradientRegistry(unittest.TestCase):
    def test_角度决定渐变方向(self):
        registry = GradientRegistry(prefix="g")
        grad = Gradient(
            kind="linear",
            angle=0.0,
            stops=[GradientStop(position=0.0, color=Color(rgb="000000"))],
        )
        registry.register(grad, THEME)
        # 0° = 从左到右 → x1 < x2，y 不变
        self.assertIn('x1="0.0000"', registry.defs[0])
        self.assertIn('x2="1.0000"', registry.defs[0])

    def test_没有色标就不给id(self):
        registry = GradientRegistry()
        self.assertIsNone(registry.register(Gradient(stops=[]), THEME))
        self.assertEqual(registry.defs, [])


if __name__ == "__main__":
    unittest.main()
