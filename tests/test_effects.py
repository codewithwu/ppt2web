"""动效滤镜的判定与运行时实现的一致性测试。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from ppt2web.render.effects import FILTER_JUDGEMENT, judge_filter

RUNTIME = Path(__file__).resolve().parent.parent / "ppt2web" / "runtime" / "slide.js"


def _runtime_filters() -> set[str]:
    """从 runtime/slide.js 的 FILTERS 表里抠出滤镜名。"""
    text = RUNTIME.read_text(encoding="utf-8")
    block = re.search(r"var FILTERS = \{(.*?)\n  \};", text, re.S)
    assert block, "runtime/slide.js 里找不到 FILTERS 表"
    quoted = set(re.findall(r'"([^"]+)":\s*\{', block.group(1)))
    bare = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*):\s*\{", block.group(1)))
    return quoted | bare


class TestFilterJudgement(unittest.TestCase):
    def test_已知滤镜判原生(self):
        for name in ("fade", "wipe(left)", "wipe(down)", "circle(in)", "barn(inVertical)"):
            verdict, note = judge_filter(name)
            self.assertEqual(verdict, "native", f"{name}: {note}")

    def test_近似滤镜说明原因(self):
        for name in ("dissolve", "randombar(horizontal)"):
            verdict, note = judge_filter(name)
            self.assertEqual(verdict, "approx", name)
            self.assertTrue(note)

    def test_未知滤镜不谎报(self):
        verdict, note = judge_filter("wipe(sideways)")
        self.assertEqual(verdict, "approx")
        self.assertIn("wipe(sideways)", note)

    def test_没有滤镜(self):
        verdict, _ = judge_filter(None)
        self.assertEqual(verdict, "approx")


class TestRuntimeParity(unittest.TestCase):
    """Python 的判定表和运行时的实现表必须一致 —— 否则报告会撒谎。"""

    def test_判定表里的滤镜运行时都实现了(self):
        runtime_filters = _runtime_filters()
        for name in FILTER_JUDGEMENT:
            self.assertIn(name, runtime_filters, f"运行时缺 {name}")

    def test_运行时没有多出未登记的滤镜(self):
        judgement = set(FILTER_JUDGEMENT)
        runtime_filters = _runtime_filters()
        extra = runtime_filters - judgement
        self.assertEqual(extra, set(), f"运行时多出未登记的滤镜：{extra}")


if __name__ == "__main__":
    unittest.main()
