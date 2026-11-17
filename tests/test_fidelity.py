"""保真相关的单元测试：动画时序、图片填充、渐变、报告、门禁。

这些是"转出来的东西和原稿一样吗"的核心断言 —— 每一条都对应一个
已经踩过的坑，改坏了要立刻红。
"""

from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET

from ppt2web.model import Color, Fill, Gradient, GradientStop, Shape, Theme
from ppt2web.ooxml import NS
from ppt2web.parse.animation import _self_value, _trigger_of
from ppt2web.parse.xmlutil import read_fill
from ppt2web.render.html import _render_geometry
from ppt2web.render.report import _judge_behavior

THEME = Theme(colors={"accent2": "ED7D31", "lt1": "FFFFFF"})

A = NS["a"]
P = NS["p"]
R = NS["r"]
#: 测试 XML 的命名空间声明
DECL = f'xmlns:a="{A}" xmlns:p="{P}" xmlns:r="{R}"'


def _el(xml: str) -> ET.Element:
    return ET.fromstring(xml)


class TestAnimationTiming(unittest.TestCase):
    def test_onBegin条件判自动触发(self):
        """``evt="onBegin"`` 的组是"随页自动播"，不是"等点击"。

        源文件里这两种条件是**并列**的：
        ``<p:cond delay="indefinite"/><p:cond evt="onBegin" delay="0"/>``
        只看第一个 cond 会把自动播的组全判成点击组。
        """
        c_tn = _el(
            f'<p:cTn {DECL} id="3">'
            "<p:stCondLst>"
            '<p:cond delay="indefinite"/>'
            '<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond>'
            "</p:stCondLst>"
            "</p:cTn>"
        )
        trigger, delay = _trigger_of(c_tn, "2")
        self.assertEqual(trigger, "auto")
        self.assertEqual(delay, 0)

    def test_indefinite判点击触发(self):
        c_tn = _el(
            f'<p:cTn {DECL} id="7">'
            "<p:stCondLst><p:cond delay=\"indefinite\"/></p:stCondLst>"
            "</p:cTn>"
        )
        trigger, delay = _trigger_of(c_tn, "2")
        self.assertEqual(trigger, "click")
        self.assertEqual(delay, 0)

    def test_onBegin指向组内节点不算自动(self):
        """``onBegin`` 指向组内更早的节点 = "上一个效果结束后"。"""
        c_tn = _el(
            f'<p:cTn {DECL} id="3">'
            "<p:stCondLst>"
            '<p:cond delay="indefinite"/>'
            '<p:cond evt="onBegin" delay="0"><p:tn val="9"/></p:cond>'
            "</p:stCondLst>"
            "</p:cTn>"
        )
        trigger, _ = _trigger_of(c_tn, "2")
        self.assertEqual(trigger, "click")


class TestRelativeOffset(unittest.TestCase):
    def test_相对位移换算成EMU(self):
        """``#ppt_y+.1`` = 往下偏移整页高度的 10%。

        以前只认精确的名字，``ppt_y+.1`` 落到兜底分支变成 0.0 ——
        "浮入"效果的位移被静默抹平，报告还判它 native。
        """
        value = _self_value("ppt_y+.1", "ppt_y", 12192000, 6858000)
        self.assertAlmostEqual(value, 685800.0)
        value = _self_value("ppt_y-.1", "ppt_y", 12192000, 6858000)
        self.assertAlmostEqual(value, -685800.0)
        value = _self_value("ppt_x+.05", "ppt_x", 12192000, 6858000)
        self.assertAlmostEqual(value, 609600.0)

    def test_没有相对量就是原位(self):
        self.assertEqual(_self_value("ppt_y", "ppt_y", 12192000, 6858000), 0.0)
        self.assertEqual(_self_value("ppt_x", "ppt_x", 12192000, 6858000), 0.0)

    def test_尺寸类的当前值是满尺寸(self):
        self.assertEqual(_self_value("ppt_w", "ppt_w", 0, 0), 1.0)


class TestBlipFill(unittest.TestCase):
    def test_填充矩形在stretch里面(self):
        """``a:fillRect`` 是 ``a:stretch`` 的子节点，不是 blipFill 的直接子节点。"""
        sp_pr = _el(
            f'<a:spPr {DECL}>'
            "<a:blipFill>"
            '<a:blip r:embed="rId3"/>'
            '<a:stretch><a:fillRect t="-96726" b="-77032"/></a:stretch>'
            "</a:blipFill>"
            "</a:spPr>"
        )
        fill = read_fill(sp_pr)
        self.assertEqual(fill.kind, "blip")
        self.assertIsNotNone(fill.blip_rect)
        l, t, r, b = fill.blip_rect
        self.assertAlmostEqual(t, -0.96726, places=5)
        self.assertAlmostEqual(b, -0.77032, places=5)
        self.assertEqual(l, 0.0)
        self.assertEqual(r, 0.0)

    def test_没有fillRect时是整块(self):
        sp_pr = _el(
            f'<a:spPr {DECL}><a:blipFill><a:blip r:embed="rId3"/></a:blipFill></a:spPr>'
        )
        fill = read_fill(sp_pr)
        self.assertEqual(fill.kind, "blip")
        self.assertIsNone(fill.blip_rect)


class TestGradientRendering(unittest.TestCase):
    def test_形状渐变走defs而不是CSS串(self):
        """SVG 的 fill **不接受** CSS 渐变函数 —— 写进去浏览器会忽略，颜色变黑。"""
        shape = Shape(shape_id="3", name="badge", kind="shape", width=1000.0, height=1000.0)
        shape.geom = "ellipse"
        shape.fill = Fill(
            kind="gradient",
            gradient=Gradient(
                kind="linear",
                angle=0.0,
                stops=[
                    GradientStop(position=0.23, color=Color(rgb="E53815")),
                    GradientStop(position=1.0, color=Color(rgb="FEA92C")),
                ],
            ),
        )
        html = _render_geometry(shape, THEME)
        self.assertNotIn("linear-gradient(", html)
        self.assertIn("<defs>", html)
        self.assertIn("<linearGradient", html)
        self.assertIn('fill="url(#geo3-1)"', html)

    def test_径向渐变也走defs(self):
        shape = Shape(shape_id="4", name="x", kind="shape", width=1000.0, height=1000.0)
        shape.geom = "ellipse"
        shape.fill = Fill(
            kind="gradient",
            gradient=Gradient(
                kind="path",
                center=(0.3, 0.7),
                stops=[GradientStop(position=0.0, color=Color(rgb="000000"))],
            ),
        )
        html = _render_geometry(shape, THEME)
        self.assertIn("<radialGradient", html)
        self.assertNotIn("radial-gradient(", html)


class TestReportJudgement(unittest.TestCase):
    def test_关键帧全等判近似(self):
        """源里写了相对量、算出来却不动 —— 必须判 approx，不能判 native。"""

        class _B:
            type = "anim"
            attr_name = "ppt_y"
            keyframes = [{"t": 0.0, "v": 0.0}, {"t": 1.0, "v": 0.0}]
            notes = ["公式 #ppt_y+.1"]

        verdict, note = _judge_behavior(_B())
        self.assertEqual(verdict, "approx")
        self.assertIn("相对位移", note)

    def test_源文件本来就不动算原生(self):
        """``#ppt_x`` → ``#ppt_x`` 是源文件**故意**让它不动，不算降级。"""

        class _B:
            type = "anim"
            attr_name = "ppt_x"
            keyframes = [{"t": 0.0, "v": 0.0}, {"t": 1.0, "v": 0.0}]
            notes = []

        verdict, _ = _judge_behavior(_B())
        self.assertEqual(verdict, "native")


class TestFontSubstitution(unittest.TestCase):
    def test_非同源替代不能算逐字一致(self):
        """阿里巴巴普惠体 → Noto Sans SC 只是"能显示"，字形/字宽都不一样。"""
        from ppt2web.fontmap import resolve

        self.assertFalse(resolve("阿里巴巴普惠体").same_origin)
        self.assertFalse(resolve("微软雅黑").same_origin)
        self.assertFalse(resolve("宋体").same_origin)
        self.assertTrue(resolve("思源宋体 CN").same_origin)
        self.assertTrue(resolve("思源黑体 CN").same_origin)


class TestFontCollection(unittest.TestCase):
    def test_字体普查要下钻组合(self):
        """封面标题在组合里 —— 只遍历 slide.shapes 会把它漏掉。"""
        from ppt2web.parse.deck import _collect_fonts
        from ppt2web.model import Deck, Run, Slide, TextFrame

        inner = Shape(shape_id="2", name="in", kind="textbox")
        inner.text = TextFrame(
            paragraphs=[
                type("P", (), {"runs": [Run(text="深", font="演示夏行楷")]})()
            ]
        )
        group = Shape(shape_id="1", name="grp", kind="group", children=[inner])
        slide = Slide(index=1, shapes=[group])
        deck = Deck(slides=[slide])
        self.assertIn("演示夏行楷", _collect_fonts(deck))


class TestTransitions(unittest.TestCase):
    def test_报告的转场表要和运行时一致(self):
        """报告说"原生实现"的转场，runtime.js 里必须真有。"""
        import re
        from pathlib import Path

        from ppt2web.render.report import IMPLEMENTED_TRANSITIONS

        runtime = (
            Path(__file__).resolve().parent.parent
            / "ppt2web"
            / "runtime"
            / "runtime.js"
        ).read_text(encoding="utf-8")
        block = re.search(r"var NATIVE_TRANSITIONS = \{(.*?)\};", runtime, re.S)
        self.assertIsNotNone(block, "runtime.js 里找不到 NATIVE_TRANSITIONS")
        runtime_kinds = set(re.findall(r"(\w+):\s*1", block.group(1)))
        self.assertEqual(
            runtime_kinds,
            IMPLEMENTED_TRANSITIONS,
            "报告里的 IMPLEMENTED_TRANSITIONS 和运行时的 NATIVE_TRANSITIONS 不一致",
        )

    def test_近似转场不算失败但要标注(self):
        from ppt2web.render.report import APPROX_TRANSITIONS

        self.assertIn("flythrough", APPROX_TRANSITIONS)
        self.assertTrue(APPROX_TRANSITIONS["flythrough"])


class TestAudio(unittest.TestCase):
    def test_音频解析出素材和播放设置(self):
        """``p:audio`` 的音量/循环/目标 + ``a:audioFile`` 的素材本体。"""
        from ppt2web.parse.audio import parse_audio

        class _FakePackage:
            def rel_target_for(self, partname, r_id):
                return "ppt/media/media1.mp3"

            def read(self, target):
                return b"ID3fake"

            def extension(self, target):
                return "mp3"

        slide = _el(
            f"<p:sld {DECL}>"
            "<p:timing><p:tnLst><p:par><p:cTn><p:childTnLst>"
            '<p:audio><p:cMediaNode vol="80000">'
            '<p:cTn repeatCount="indefinite"/>'
            '<p:tgtEl><p:spTgt spid="50"/></p:tgtEl>'
            "</p:cMediaNode></p:audio>"
            "</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>"
            "</p:sld>"
        )
        clips = parse_audio(_FakePackage(), "ppt/slides/slide1.xml", slide)
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0].volume, 80000)
        self.assertTrue(clips[0].loop)
        self.assertEqual(clips[0].target_id, "50")


class TestTrueFontFamily(unittest.TestCase):
    def test_真身字体的引用名和font_face要一致(self):
        """@font-face 声明的 family 和 CSS 里引用的必须一致 —— 对不上就白嵌。

        商用字体经常"文件名一套、内部名另一套"（演示夏行楷.ttf 内部叫 "KaiTi"）。
        """
        import tempfile
        from pathlib import Path

        from ppt2web.fontfiles import FontLibrary, font_family_name
        from ppt2web.render.fontplan import build_plan, materialize

        local = FontLibrary()
        path = local.local_font("演示夏行楷")
        if path is None:
            self.skipTest("本地没有演示夏行楷真身")
        family = font_family_name(path)
        self.assertTrue(family, "读不出字体内部的 family 名")

        plan = build_plan({"演示夏行楷": set("深耕笃行")})
        with tempfile.TemporaryDirectory() as tmp:
            materialize(plan, Path(tmp))
            css = plan.css or ""
        self.assertIn(f"font-family: '{family}'", css, "@font-face 没声明真身的 family")
        stack = plan.stack_for("演示夏行楷")
        self.assertIn(family, stack, f"CSS 里没引用真身的 family（{family}）")


if __name__ == "__main__":
    unittest.main()
