"""产物文字提取（verify 的核心断言）的单元测试。"""

from __future__ import annotations

import unittest

from ppt2web.verify import extract_text


class TestExtractText(unittest.TestCase):
    def test_取出正文文字(self):
        html = '<div class="tx"><p><span>深耕</span><span>笃行</span></p></div>'
        self.assertEqual(extract_text(html), "深耕笃行")

    def test_跳过脚本与样式(self):
        html = """
        <style>.tx{color:red}</style>
        <script>var x = "不该被算进来";</script>
        <div class="tx"><p>正文</p></div>
        """
        self.assertEqual(extract_text(html), "正文")

    def test_跳过页面标题(self):
        html = "<title>slide</title><div class='tx'><p>正文</p></div>"
        self.assertEqual(extract_text(html), "正文")

    def test_跳过占位框(self):
        html = (
            '<div class="gp-placeholder" data-kind="chart">'
            "<span>chart</span><small>graphicData uri=...</small></div>"
            '<div class="tx"><p>正文</p></div>'
        )
        self.assertEqual(extract_text(html), "正文")

    def test_跳过项目符号(self):
        html = '<p><span class="bul">•</span><span>正文</span></p>'
        self.assertEqual(extract_text(html), "正文")

    def test_空白被归一化(self):
        html = "<div class='tx'><p>深 耕\n笃行</p></div>"
        self.assertEqual(extract_text(html), "深耕笃行")

    def test_无障碍文本层也会被读到(self):
        """矢量模式：文字在 .tx-a11y 里，必须能被抽出来做逐字符比对。"""
        html = '<div class="tx-a11y">深耕笃行</div><svg class="tx-svg"></svg>'
        self.assertEqual(extract_text(html), "深耕笃行")


if __name__ == "__main__":
    unittest.main()


class TestChartTableGate(unittest.TestCase):
    """分级门禁：已支持的图表/表格必须真的渲染出来。

    硬失败的是"我们声称支持的类型却留了占位框"；
    明确不支持的类型才允许留占位框（并且要记进报告）。
    """

    def _shape(self, kind, chart=None, table=None):
        from ppt2web.model import Shape

        return Shape(shape_id="1", name="x", kind=kind, chart=chart, table=table)

    def test_支持的图表不该留占位框(self):
        from ppt2web.model import Chart
        from ppt2web.verify import _expected_placeholders

        slide = _Slide([self._shape("chart", chart=Chart(kind="doughnut"))])
        count, reasons = _expected_placeholders(slide)
        self.assertEqual(count, 0)
        self.assertEqual(reasons, [])

    def test_不支持的图表允许留占位框但要记原因(self):
        from ppt2web.model import Chart
        from ppt2web.verify import _expected_placeholders

        chart = Chart(kind="line", unsupported=["图表类型 line"])
        slide = _Slide([self._shape("chart", chart=chart)])
        count, reasons = _expected_placeholders(slide)
        self.assertEqual(count, 1)
        self.assertIn("图表类型 line", reasons[0])

    def test_带合并单元格的表格算不支持(self):
        from ppt2web.model import Table
        from ppt2web.verify import _expected_placeholders

        table = Table(unsupported=["合并单元格（竖向）"])
        slide = _Slide([self._shape("table", table=table)])
        count, reasons = _expected_placeholders(slide)
        self.assertEqual(count, 1)
        self.assertIn("合并单元格", reasons[0])

    def test_占位框正则只认图表和表格(self):
        from ppt2web.verify import _PLACEHOLDER_RE

        self.assertEqual(
            len(_PLACEHOLDER_RE.findall(
                '<div class="gp-placeholder" data-kind="chart">'
                '<div class="gp-placeholder" data-kind="table">'
            )),
            2,
        )
        self.assertEqual(
            len(_PLACEHOLDER_RE.findall(
                '<div class="gp-placeholder" data-kind="diagram">'
            )),
            0,
        )


class _Slide:
    """最小化的 slide 替身（只需要 shapes）。"""

    def __init__(self, shapes):
        self.shapes = shapes
