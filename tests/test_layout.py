"""排版引擎的单元测试（用假的字体，不依赖 fontTools）。"""

from __future__ import annotations

import unittest

from ppt2web.model import Paragraph, Run
from ppt2web.render.textlayout import EMU_PER_PT, TextLayout


class StubFace:
    def __init__(self, advance: float = 500.0, upem: int = 1000):
        self.upem = upem
        self.ascent = 800.0
        self.descent = 200.0
        self._advance = advance

    def glyph_name(self, ch: str) -> str:
        return "g%d" % ord(ch)

    def advance(self, glyph_name: str) -> float:
        return self._advance


class StubFamily:
    def __init__(self, advance: float = 500.0):
        self.face = StubFace(advance)
        self.faces = [self.face]
        self.pairs: list = []

    def face_for(self, ch: str) -> StubFace:
        return self.face

    def primary_face(self) -> StubFace:
        return self.face

    def metrics(self) -> tuple[float, float]:
        return (self.face.ascent, self.face.descent)


class StubProvider:
    def __init__(self, advance: float = 500.0, with_font: bool = True):
        self.advance = advance
        self.with_font = with_font

    def family(self, name):
        if not self.with_font:
            return None
        return StubFamily(self.advance)


def char_width(size_pt: float = 10.0, advance: float = 500.0, upem: int = 1000) -> float:
    return advance / upem * size_pt * EMU_PER_PT


class TestLineBreaking(unittest.TestCase):
    def setUp(self):
        self.layout = TextLayout(StubProvider())
        self.w = char_width()  # 每个字符的宽度

    def _para(self, text: str, size_pt: float = 10.0) -> Paragraph:
        return Paragraph(runs=[Run(text=text, size_pt=size_pt)])

    def test_西文按空格断行(self):
        para = self._para("AAA BBB")
        out = self.layout.layout_paragraph(para, self.w * 4, 0, first=True)
        self.assertEqual(len(out.lines), 2)
        self.assertEqual("".join(g.ch for g in out.lines[0].glyphs), "AAA ")
        self.assertEqual("".join(g.ch for g in out.lines[1].glyphs), "BBB")

    def test_西文单词不切断(self):
        # 宽度只够 2 个字符，"ABC" 不能被拆开
        para = self._para("ABC DEF")
        out = self.layout.layout_paragraph(para, self.w * 2, 0, first=True)
        first = "".join(g.ch for g in out.lines[0].glyphs)
        # 词比整行还宽 → 溢出但不切断
        self.assertTrue(first.startswith("ABC"), first)
        joined = "".join("".join(g.ch for g in ln.glyphs) for ln in out.lines)
        self.assertIn("ABC", joined)

    def test_汉字逐字断行(self):
        para = self._para("一二三四五")
        out = self.layout.layout_paragraph(para, self.w * 3, 0, first=True)
        self.assertEqual(len(out.lines), 2)
        self.assertEqual("".join(g.ch for g in out.lines[0].glyphs), "一二三")
        self.assertEqual("".join(g.ch for g in out.lines[1].glyphs), "四五")

    def test_行首禁则(self):
        # 宽度只够 3 个字："。" 不能出现在行首，要挤回上一行
        para = self._para("一二三。四五")
        out = self.layout.layout_paragraph(para, self.w * 3, 0, first=True)
        first = "".join(g.ch for g in out.lines[0].glyphs)
        self.assertFalse(first.startswith("。"))
        self.assertIn("。", first)

    def test_没有字体时按兜底宽度(self):
        layout = TextLayout(StubProvider(with_font=False))
        para = Paragraph(runs=[Run(text="深", size_pt=10.0)])
        out = layout.layout_paragraph(para, 100000, 0, first=True)
        self.assertEqual(len(out.lines), 1)
        self.assertEqual(out.lines[0].glyphs[0].width, 10.0 * EMU_PER_PT)


class TestLineHeight(unittest.TestCase):
    def setUp(self):
        self.layout = TextLayout(StubProvider())

    def test_默认行高用字体度量(self):
        para = Paragraph(runs=[Run(text="A", size_pt=10.0)])
        out = self.layout.layout_paragraph(para, 100000, 0, first=True)
        # ascent(800) - descent(200) = 600 → 6pt
        self.assertAlmostEqual(out.lines[0].height, 6.0 * EMU_PER_PT, places=0)

    def test_倍数行距(self):
        para = Paragraph(runs=[Run(text="A", size_pt=10.0)], line_spacing=1.5)
        out = self.layout.layout_paragraph(para, 100000, 0, first=True)
        self.assertAlmostEqual(out.lines[0].height, 9.0 * EMU_PER_PT, places=0)

    def test_固定行距(self):
        para = Paragraph(runs=[Run(text="A", size_pt=10.0)], line_spacing_pt=12.0)
        out = self.layout.layout_paragraph(para, 100000, 0, first=True)
        self.assertAlmostEqual(out.lines[0].height, 12.0 * EMU_PER_PT, places=0)

    def test_段前段后(self):
        para = Paragraph(
            runs=[Run(text="A", size_pt=10.0)], space_before_pt=3.0, space_after_pt=2.0
        )
        out = self.layout.layout_paragraph(para, 100000, 0, first=True)
        line_h = 6.0 * EMU_PER_PT
        self.assertAlmostEqual(out.height, line_h + 5.0 * EMU_PER_PT, places=0)


class TestIndent(unittest.TestCase):
    def test_首行缩进(self):
        layout = TextLayout(StubProvider())
        w = char_width()
        para = Paragraph(runs=[Run(text="AAA", size_pt=10.0)], margin_left_emu=1000)
        out = layout.layout_paragraph(para, w * 10, 0, first=True)
        self.assertAlmostEqual(out.lines[0].x, 1000.0, places=0)

    def test_悬挂缩进只作用于本段首行(self):
        layout = TextLayout(StubProvider())
        w = char_width()
        para = Paragraph(
            runs=[Run(text="AA BB", size_pt=10.0)], margin_left_emu=1000, indent_emu=-400
        )
        out = layout.layout_paragraph(para, w * 3, 0, first=True)
        self.assertAlmostEqual(out.lines[0].x, 600.0, places=0)
        self.assertAlmostEqual(out.lines[1].x, 1000.0, places=0)

    def test_左内边距算进坐标(self):
        layout = TextLayout(StubProvider())
        w = char_width()
        para = Paragraph(runs=[Run(text="AA", size_pt=10.0)])
        out = layout.layout_paragraph(para, w * 10, 5000, first=True)
        self.assertAlmostEqual(out.lines[0].x, 5000.0, places=0)


class TestBaseline(unittest.TestCase):
    """基线位置：行盒比内容区高出来的部分，一半在基线上、一半在下。"""

    def setUp(self):
        self.layout = TextLayout(StubProvider())

    def test_单倍行距基线落在ascent(self):
        para = Paragraph(runs=[Run(text="A", size_pt=10.0)])
        out = self.layout.layout_paragraph(para, 100000, 0, first=True)
        # stub 字体 ascent=800 descent=200 → 行高 6pt、基线在 8pt 处
        self.assertAlmostEqual(out.lines[0].baseline, 8.0 * EMU_PER_PT, places=0)

    def test_倍数行距多出来的行距分摊两边(self):
        para = Paragraph(runs=[Run(text="A", size_pt=10.0)], line_spacing=1.5)
        out = self.layout.layout_paragraph(para, 100000, 0, first=True)
        # 行高 9pt、内容区 6pt → 半行距 1.5pt → 基线 8 + 1.5 = 9.5pt
        self.assertAlmostEqual(out.lines[0].baseline, 9.5 * EMU_PER_PT, places=0)

    def test_固定行距底部对齐(self):
        para = Paragraph(runs=[Run(text="A", size_pt=10.0)], line_spacing_pt=12.0)
        out = self.layout.layout_paragraph(para, 100000, 0, first=True)
        # 固定行距没有半行距：基线 = 行高 − descent = 12 − 2 = 10pt
        self.assertAlmostEqual(out.lines[0].baseline, 10.0 * EMU_PER_PT, places=0)


class TestAlignment(unittest.TestCase):
    def setUp(self):
        self.layout = TextLayout(StubProvider())
        self.w = char_width()

    def test_居中(self):
        para = Paragraph(runs=[Run(text="AA", size_pt=10.0)], align="ctr")
        out = self.layout.layout_paragraph(para, self.w * 10, 0, first=True)
        # 文字宽 2 字，文字区宽 10 字 → 左边留 4 字
        self.assertAlmostEqual(out.lines[0].x, self.w * 4, places=0)

    def test_右对齐(self):
        para = Paragraph(runs=[Run(text="AA", size_pt=10.0)], align="r")
        out = self.layout.layout_paragraph(para, self.w * 10, 0, first=True)
        self.assertAlmostEqual(out.lines[0].x, self.w * 8, places=0)

    def test_左对齐是默认(self):
        para = Paragraph(runs=[Run(text="AA", size_pt=10.0)])
        out = self.layout.layout_paragraph(para, self.w * 10, 0, first=True)
        self.assertAlmostEqual(out.lines[0].x, 0.0, places=0)


class TestWrap(unittest.TestCase):
    def setUp(self):
        self.layout = TextLayout(StubProvider())
        self.w = char_width()

    def test_不换行时整段排成一行(self):
        para = Paragraph(runs=[Run(text="AA BB CC", size_pt=10.0)])
        out = self.layout.layout_paragraph(para, self.w * 2, 0, first=True, wrap=False)
        self.assertEqual(len(out.lines), 1)
        self.assertEqual(len(out.lines[0].glyphs), 8)

    def test_默认会换行(self):
        para = Paragraph(runs=[Run(text="AA BB CC", size_pt=10.0)])
        out = self.layout.layout_paragraph(para, self.w * 2, 0, first=True)
        self.assertGreater(len(out.lines), 1)


if __name__ == "__main__":
    unittest.main()
