"""表格解析与渲染的单元测试（最小化 OOXML 夹具）。"""

from __future__ import annotations

import unittest

from ppt2web.model import Shape, Theme
from ppt2web.package import Package
from ppt2web.parse.table import parse_table
from ppt2web.render.tables import render_table
from tests.test_chart import make_package

TABLE_XML = (
    '<p:graphicFrame xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    "<p:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"1000\" cy=\"500\"/></p:xfrm>"
    "<a:graphic><a:graphicData>"
    '<a:tbl><a:tblPr firstRow="1" bandRow="1">'
    "<a:tableStyleId>{GUID}</a:tableStyleId></a:tblPr>"
    '<a:tblGrid><a:gridCol w="500"/><a:gridCol w="500"/></a:tblGrid>'
    '<a:tr h="250"><a:tc><a:txBody><a:bodyPr/><a:lstStyle/>'
    '<a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="zh-CN" sz="1600"/><a:t>表头</a:t></a:r></a:p>'
    "</a:txBody>"
    '<a:tcPr marL="117299" marR="117299" marT="58650" marB="58650">'
    '<a:solidFill><a:schemeClr val="accent2"/></a:solidFill></a:tcPr></a:tc>'
    '<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>'
    '<a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="zh-CN" sz="1400"/><a:t>值</a:t></a:r></a:p>'
    "</a:txBody><a:tcPr/></a:tc></a:tr>"
    '<a:tr h="250"><a:tc><a:txBody><a:bodyPr/><a:lstStyle/>'
    '<a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="zh-CN" sz="1400"/><a:t>正文</a:t></a:r></a:p>'
    "</a:txBody><a:tcPr/></a:tc>"
    '<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>'
    '<a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="zh-CN" sz="1400"/><a:t>另一格</a:t></a:r></a:p>'
    "</a:txBody><a:tcPr/></a:tc></a:tr>"
    "</a:tbl></a:graphicData></a:graphic></p:graphicFrame>"
)

TABLE_STYLES = (
    '<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'def="{GUID}">'
    '<a:tblStyle styleId="{GUID}" styleName="中度样式 2 - 强调 1">'
    "<a:wholeTbl><a:tcStyle><a:tcBdr>"
    '<a:left><a:ln w="12700"><a:solidFill><a:schemeClr val="lt1"/></a:solidFill></a:ln></a:left>'
    '<a:insideH><a:ln w="12700"><a:solidFill><a:schemeClr val="lt1"/></a:solidFill></a:ln></a:insideH>'
    "</a:tcBdr></a:tcStyle></a:wholeTbl>"
    "<a:firstRow><a:tcTxStyle b=\"on\"><a:schemeClr val=\"lt1\"/></a:tcTxStyle>"
    "<a:tcStyle><a:tcBdr>"
    '<a:bottom><a:ln w="38100"><a:solidFill><a:schemeClr val="lt1"/></a:solidFill></a:ln></a:bottom>'
    "</a:tcBdr></a:tcStyle></a:firstRow>"
    "</a:tblStyle></a:tblStyleLst>"
)


def _package() -> Package:
    return make_package(
        {
            "ppt/slides/slide1.xml": TABLE_XML.replace("{GUID}", "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"),
            "ppt/tableStyles.xml": TABLE_STYLES.replace("{GUID}", "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"),
        }
    )


#: 夹具用得到的主题色
THEME = Theme(colors={"accent2": "ED7D31", "lt1": "FFFFFF", "bg1": "FFFFFF"})


def _parse():
    import xml.etree.ElementTree as ET

    package = _package()
    root = package.xml("ppt/slides/slide1.xml")
    return parse_table(package, root)


class TestParseTable(unittest.TestCase):
    def test_行列与单元格文字(self):
        table = _parse()
        assert table is not None
        self.assertEqual(len(table.rows), 2)
        self.assertEqual(len(table.columns), 2)
        self.assertEqual(table.columns, [500, 500])
        texts = [
            "".join(r.text for p in c.text.paragraphs for r in p.runs)
            for c in table.rows[0].cells
        ]
        self.assertEqual(texts, ["表头", "值"])

    def test_边框来自表格样式而不是单元格(self):
        """a:tcPr 里通常一条线都没有，全在 ppt/tableStyles.xml 里。"""
        table = _parse()
        assert table is not None and table.style is not None
        self.assertEqual(table.style.name, "中度样式 2 - 强调 1")
        self.assertIsNotNone(table.style.borders.get("left"))
        self.assertEqual(table.style.borders["left"].width_emu, 12700)
        # 首行：3pt 粗底线 + 白字粗体
        self.assertEqual(table.style.first_row_borders["bottom"].width_emu, 38100)
        self.assertTrue(table.style.first_row_bold)
        self.assertEqual(table.style.first_row_color.theme, "lt1")

    def test_单元格的填充和边距(self):
        table = _parse()
        assert table is not None
        cell = table.rows[0].cells[0]
        self.assertEqual(cell.fill.kind, "solid")
        self.assertEqual(cell.margin_left_emu, 117299)
        self.assertEqual(cell.margin_top_emu, 58650)

    def test_合并单元格会被记成不支持(self):
        xml = TABLE_XML.replace(
            "<a:tcPr/>", '<a:tcPr><a:vMerge val="restart"/></a:tcPr>'
        )
        package = make_package(
            {
                "ppt/slides/slide1.xml": xml.replace("{GUID}", "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"),
                "ppt/tableStyles.xml": TABLE_STYLES.replace("{GUID}", "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"),
            }
        )
        table = parse_table(package, package.xml("ppt/slides/slide1.xml"))
        assert table is not None
        self.assertTrue(table.unsupported)


class TestRenderTable(unittest.TestCase):
    def _shape(self, table):
        return Shape(
            shape_id="4", name="表格 2", kind="table",
            width=1000.0, height=250.0, table=table,
        )

    def test_渲染出填充边框和无障碍表格(self):
        table = _parse()
        assert table is not None
        html = render_table(self._shape(table), THEME, provider=None)
        assert html is not None
        self.assertIn('class="table-svg"', html)
        self.assertIn("<rect", html)      # 单元格填充
        self.assertIn("<line", html)      # 边框
        self.assertIn('class="tbl-a11y"', html)
        self.assertIn("表头", html)

    def test_无障碍表格有行列结构(self):
        table = _parse()
        assert table is not None
        html = render_table(self._shape(table), THEME, provider=None)
        assert html is not None
        self.assertIn("<th", html)
        self.assertIn("<td", html)


if __name__ == "__main__":
    unittest.main()
