"""图表解析与渲染的单元测试（用最小化的 OOXML 夹具，不依赖真实文件）。"""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from ppt2web.model import Theme
from ppt2web.package import Package
from ppt2web.parse.chart import parse_chart
from ppt2web.render.charts import render_chart

CHART_HEAD = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:c15="http://schemas.microsoft.com/office/drawing/2012/chart" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
)
CHART_TAIL = "</c:chartSpace>"


def make_package(parts: dict[str, str]) -> Package:
    """把几个 XML 部件打成一个临时 zip，交给 Package 读。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fake.pptx"
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in parts.items():
                zf.writestr(name, data)
        return Package(str(path))


def doughnut(values: str, cats: str = "") -> str:
    """一段甜甜圈 chart XML。``values``/``cats`` 是现成的 ``c:pt`` 片段。"""
    return (
        CHART_HEAD
        + "<c:chart><c:plotArea><c:doughnutChart>"
        '<c:varyColors val="1"/>'
        "<c:ser><c:idx val=\"0\"/><c:order val=\"0\"/>"
        "<c:tx><c:strRef><c:f>Sheet1!$B$1</c:f>"
        '<c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>销售额</c:v></c:pt></c:strCache>'
        "</c:strRef></c:tx>"
        '<c:spPr><a:solidFill><a:srgbClr val="ED7D31"/></a:solidFill></c:spPr>'
        + cats
        + "<c:val><c:numRef><c:f>Sheet1!$B$2:$B$3</c:f><c:numCache>"
        '<c:formatCode>General</c:formatCode><c:ptCount val="4"/>'
        + values
        + "</c:numCache></c:numRef></c:val>"
        "</c:ser>"
        '<c:firstSliceAng val="0"/><c:holeSize val="78"/>'
        "</c:doughnutChart></c:plotArea></c:chart>" + CHART_TAIL
    )


class TestParseChart(unittest.TestCase):
    def _parse(self, chart_xml: str, extra: dict[str, str] | None = None):
        parts = {"ppt/charts/chart1.xml": chart_xml}
        parts.update(extra or {})
        return parse_chart(make_package(parts), "ppt/charts/chart1.xml", Theme())

    def test_甜甜圈的基本参数(self):
        chart = self._parse(
            doughnut(
                '<c:pt idx="0"><c:v>6.2</c:v></c:pt><c:pt idx="1"><c:v>3.8</c:v></c:pt>'
            )
        )
        assert chart is not None
        self.assertEqual(chart.kind, "doughnut")
        self.assertEqual(chart.hole_size, 78)
        self.assertEqual(chart.series[0].name, "销售额")
        self.assertEqual(chart.series[0].values, [6.2, 3.8])
        self.assertEqual(chart.unsupported, [])

    def test_ptCount会撒谎_只按实际存在的点画(self):
        """numCache 声明 4 个点却只给 2 个 —— 按声明画会多出两个空扇区。"""
        chart = self._parse(
            doughnut(
                '<c:pt idx="0"><c:v>40</c:v></c:pt><c:pt idx="1"><c:v>60</c:v></c:pt>'
            )
        )
        assert chart is not None
        self.assertEqual(chart.series[0].values, [40.0, 60.0])

    def test_类别名优先读c15扩展(self):
        """WPS 生成的图表把类别名/系列名放在 c15:filtered*Title 里。"""
        cats = (
            "<c:cat/>"
            "<c:extLst><c:ext>"
            '<c15:filteredCategoryTitle><c15:cat><c:strRef><c:strCache>'
            '<c:ptCount val="4"/>'
            '<c:pt idx="0"><c:v>类别1</c:v></c:pt>'
            '<c:pt idx="1"><c:v>类别2</c:v></c:pt>'
            '<c:pt idx="2"><c:v>类别3</c:v></c:pt>'
            '<c:pt idx="3"><c:v>类别4</c:v></c:pt>'
            "</c:strCache></c:strRef></c15:cat></c15:filteredCategoryTitle>"
            "</c:ext></c:extLst>"
        )
        chart = self._parse(
            doughnut('<c:pt idx="0"><c:v>1</c:v></c:pt>', cats)
        )
        assert chart is not None
        self.assertEqual(chart.categories, ["类别1", "类别2", "类别3", "类别4"])

    def test_不认识的图表类型会被记成不支持(self):
        xml = (
            CHART_HEAD
            + "<c:chart><c:plotArea><c:lineChart><c:ser/></c:lineChart>"
            "</c:plotArea></c:chart>" + CHART_TAIL
        )
        chart = self._parse(xml)
        assert chart is not None
        self.assertTrue(chart.unsupported)

    def test_主题覆盖决定配色(self):
        """图表自带 themeOverride 时，配色按覆盖主题算，不是幻灯片主题。"""
        override = (
            '<a:themeOverride xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:clrScheme name="X"><a:accent1><a:srgbClr val="5B9BD5"/></a:accent1>'
            '<a:accent2><a:srgbClr val="ED7D31"/></a:accent2></a:clrScheme></a:themeOverride>'
        )
        rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/themeOverride"'
            ' Target="../theme/themeOverride1.xml"/></Relationships>'
        )
        slide_theme = Theme(colors={"accent1": "4472C4", "accent2": "ED7D31"})
        parts = {
            "ppt/charts/chart1.xml": doughnut('<c:pt idx="0"><c:v>1</c:v></c:pt>'),
            "ppt/charts/_rels/chart1.xml.rels": rels,
            "ppt/theme/themeOverride1.xml": override,
        }
        chart = parse_chart(make_package(parts), "ppt/charts/chart1.xml", slide_theme)
        assert chart is not None
        assert chart.theme is not None
        self.assertEqual(chart.theme.colors.get("accent1"), "5B9BD5")


class TestRenderChart(unittest.TestCase):
    def _shape(self, chart):
        from ppt2web.model import Shape

        return Shape(shape_id="10", name="图表", kind="chart", width=1000.0, height=800.0, chart=chart)

    def test_甜甜圈画出两段弧(self):
        parts = {"ppt/charts/chart1.xml": doughnut(
            '<c:pt idx="0"><c:v>6.2</c:v></c:pt><c:pt idx="1"><c:v>3.8</c:v></c:pt>'
        )}
        chart = parse_chart(make_package(parts), "ppt/charts/chart1.xml", Theme())
        assert chart is not None
        html = render_chart(self._shape(chart), Theme(), provider=None)
        assert html is not None
        self.assertIn('class="chart-svg"', html)
        self.assertIn("<path", html)
        # 无障碍层带系列名（verify 靠它逐字符比对）
        self.assertIn("销售额", html)

    def test_不支持的类型不渲染(self):
        xml = (
            CHART_HEAD
            + "<c:chart><c:plotArea><c:lineChart><c:ser/></c:lineChart>"
            "</c:plotArea></c:chart>" + CHART_TAIL
        )
        chart = parse_chart(make_package({"ppt/charts/chart1.xml": xml}), "ppt/charts/chart1.xml", Theme())
        assert chart is not None
        self.assertIsNone(render_chart(self._shape(chart), Theme(), provider=None))


if __name__ == "__main__":
    unittest.main()
