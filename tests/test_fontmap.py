"""字体名解析的单元测试（标准库 unittest，零依赖）。

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from ppt2web.fontmap import (
    VARIANT_WEIGHTS,
    is_east_asian,
    resolve,
    split_by_script,
    split_variant,
)


class TestSplitVariant(unittest.TestCase):
    def test_英文后缀(self):
        self.assertEqual(split_variant("思源宋体 CN Heavy"), ("思源宋体 CN", 900))
        self.assertEqual(split_variant("思源宋体 CN Light"), ("思源宋体 CN", 300))
        self.assertEqual(split_variant("思源宋体 CN SemiBold"), ("思源宋体 CN", 600))
        self.assertEqual(split_variant("Noto Sans SC Bold"), ("Noto Sans SC", 700))

    def test_版本号后缀(self):
        base, weight = split_variant("阿里巴巴普惠体 2.0 45 Light")
        self.assertEqual(base, "阿里巴巴普惠体")
        self.assertEqual(weight, 300)

    def test_没有后缀(self):
        base, weight = split_variant("微软雅黑")
        self.assertEqual(base, "微软雅黑")
        self.assertIsNone(weight)

    def test_字重表(self):
        self.assertEqual(VARIANT_WEIGHTS["heavy"], 900)
        self.assertEqual(VARIANT_WEIGHTS["light"], 300)
        self.assertEqual(VARIANT_WEIGHTS["semibold"], 600)


class TestResolve(unittest.TestCase):
    def test_思源宋体映射到衬线(self):
        info = resolve("思源宋体 CN Light")
        assert info is not None
        self.assertEqual(info.spec.family, "Noto Serif SC")
        self.assertEqual(info.weight, 300)

    def test_思源黑体映射到无衬线(self):
        info = resolve("思源黑体 CN Normal")
        assert info is not None
        self.assertEqual(info.spec.family, "Noto Sans SC")
        self.assertEqual(info.weight, 400)

    def test_微软雅黑与等线(self):
        for name in ("微软雅黑", "等线", "等线 Light", "黑体"):
            info = resolve(name)
            assert info is not None, name
            self.assertEqual(info.spec.family, "Noto Sans SC", name)

    def test_宋体族(self):
        info = resolve("宋体")
        assert info is not None
        self.assertEqual(info.spec.family, "Noto Serif SC")

    def test_度量兼容字体(self):
        self.assertEqual(resolve("Calibri").spec.family, "Carlito")
        self.assertEqual(resolve("Arial").spec.family, "Arimo")

    def test_没有替代的字体(self):
        info = resolve("演示夏行楷")
        assert info is not None
        self.assertIsNone(info.spec)

    def test_空名字(self):
        self.assertIsNone(resolve(None))
        self.assertIsNone(resolve(""))


class TestScript(unittest.TestCase):
    def test_汉字算东亚(self):
        for ch in "深耕，。！？（":
            self.assertTrue(is_east_asian(ch), ch)

    def test_西文不算东亚(self):
        for ch in "Aa1 ,.()":
            self.assertFalse(is_east_asian(ch), ch)

    def test_全角数字算东亚(self):
        self.assertTrue(is_east_asian("１"))
        self.assertFalse(is_east_asian("1"))

    def test_按字符分段(self):
        self.assertEqual(
            split_by_script("深A耕"),
            [("深", True), ("A", False), ("耕", True)],
        )

    def test_同类合并(self):
        self.assertEqual(split_by_script("深耕笃行"), [("深耕笃行", True)])
        self.assertEqual(split_by_script(""), [])


if __name__ == "__main__":
    unittest.main()
