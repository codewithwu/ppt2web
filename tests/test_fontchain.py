"""真身字体链路的单元测试：命名匹配、逐字符回落。

「真身」= 用户把商用字体放进 ``ppt2web/fonts/local/``。这条路上有两个坑：

1. **命名匹配太死** —— 文件名必须和 PPT 里的字体名完全一致才认得，
   而商用字体几乎都带版本号（``阿里巴巴普惠体-3.0 55 Regular.ttf``）。
2. **真身缺字形 → 整个形状退回 HTML 文字** —— 中文字体常常没有西文字形，
   一旦缺字形，16 页正文会集体从矢量掉回 HTML（版式就变了）。
   正确做法是**逐字符**回落到替代字体。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ppt2web.fontfiles import FontLibrary, normalize_font_name
from ppt2web.render.glyphs import Family


def _library(files: dict[str, bytes]) -> FontLibrary:
    """建一个只含 local/ 的字体库。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "local").mkdir()
        for name, data in files.items():
            (root / "local" / name).write_bytes(data)
        return FontLibrary(root)


class TestLocalFontMatching(unittest.TestCase):
    def test_文件名完全一致(self):
        lib = _library({"阿里巴巴普惠体.ttf": b"x"})
        self.assertIsNotNone(lib.local_font("阿里巴巴普惠体"))

    def test_文件名带版本号也认得(self):
        """商用字体几乎都带版本号 —— 匹配太死是最大的坑。"""
        lib = _library({"阿里巴巴普惠体-3.0 55 Regular.ttf": b"x"})
        found = lib.local_font("阿里巴巴普惠体")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.name, "阿里巴巴普惠体-3.0 55 Regular.ttf")

    def test_英文名和大小写不敏感(self):
        lib = _library({"AlibabaPuHuiTi.ttf": b"x"})
        self.assertIsNotNone(lib.local_font("alibaba puhuiti"))

    def test_多个候选时挑字重最接近的(self):
        lib = _library(
            {
                "思源宋体CNLight.ttf": b"x",
                "思源宋体CNHeavy.ttf": b"x",
            }
        )
        heavy = lib.local_font("思源宋体 CN Heavy")
        light = lib.local_font("思源宋体 CN Light")
        assert heavy is not None and light is not None
        self.assertEqual(heavy.name, "思源宋体CNHeavy.ttf")
        self.assertEqual(light.name, "思源宋体CNLight.ttf")

    def test_认不出来就是没有(self):
        lib = _library({"别的字体.ttf": b"x"})
        self.assertIsNone(lib.local_font("阿里巴巴普惠体"))

    def test_规范化规则(self):
        self.assertEqual(normalize_font_name("Alibaba PuHuiTi"), "alibabapuhuiti")
        self.assertEqual(normalize_font_name("思源宋体 CN Heavy"), "思源宋体cnheavy")


class StubFace:
    """只实现 face_for 需要的那个方法。"""

    def __init__(self, chars: str):
        self.chars = set(chars)
        self.upem = 1000
        self.ascent = 800.0
        self.descent = 200.0

    def glyph_name(self, ch: str):
        return "g" if ch in self.chars else None


class TestPerCharacterFallback(unittest.TestCase):
    def test_真身有的字用真身(self):
        family = Family("真身", faces=[StubFace("汉字")])
        self.assertIsNotNone(family.face_for("汉"))

    def test_真身缺的字回落到替代字体(self):
        """逐字符回落 —— 不是整个形状退回 HTML。"""
        fallback = Family("替代", faces=[StubFace("A汉")])
        family = Family("真身", faces=[StubFace("汉")], fallback=fallback)
        self.assertIsNotNone(family.face_for("A"))
        # 替代字体也没有 → 才是真的没有
        self.assertIsNone(family.face_for("Z"))

    def test_没有兜底就是没有(self):
        family = Family("真身", faces=[StubFace("汉")])
        self.assertIsNone(family.face_for("A"))


if __name__ == "__main__":
    unittest.main()
