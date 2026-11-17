"""OOXML 命名空间与元素查找工具（标准库实现，零依赖）。

ppt2web 刻意不使用 python-pptx / lxml：转换器要能在任何机器上
`python -m ppt2web` 直接跑，不该逼用户先 pip install。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Iterator, Optional

NS: dict[str, str] = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    #: 微软的图表扩展命名空间（c14=样式、c15=筛选后的标题、c16=唯一 id）
    "c14": "http://schemas.microsoft.com/office/drawing/2007/8/2/chart",
    "c15": "http://schemas.microsoft.com/office/drawing/2012/chart",
    "c16": "http://schemas.microsoft.com/office/drawing/2014/chart",
    "cs": "http://schemas.microsoft.com/office/drawing/2012/chartStyle",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "asvg": "http://schemas.microsoft.com/office/drawing/2016/SVG/main",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
    "p159": "http://schemas.microsoft.com/office/powerpoint/2015/09/main",
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}

# 关系类型（只列用得到的）
REL_SLIDE = "slide"
REL_SLIDE_LAYOUT = "slideLayout"
REL_SLIDE_MASTER = "slideMaster"
REL_THEME = "theme"
REL_NOTES_SLIDE = "notesSlide"
REL_IMAGE = "image"
REL_OLE_OBJECT = "oleObject"
REL_PACKAGE = "package"


def qn(name: str) -> str:
    """'a:off' → '{namespace}off'；也支持 'p:spPr/a:xfrm' 这种多段路径。"""
    parts = []
    for seg in name.split("/"):
        if ":" in seg:
            prefix, local = seg.split(":", 1)
            parts.append(f"{{{NS[prefix]}}}{local}")
        else:
            parts.append(seg)
    return "/".join(parts)


def local_name(el: ET.Element) -> str:
    tag = el.tag
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.split("}", 1)[1]
    return str(tag)


def find(el: Optional[ET.Element], path: str) -> Optional[ET.Element]:
    if el is None:
        return None
    try:
        return el.find(qn(path))
    except (KeyError, SyntaxError):
        return None


def findall(el: Optional[ET.Element], path: str) -> list[ET.Element]:
    if el is None:
        return []
    try:
        return list(el.findall(qn(path)))
    except (KeyError, SyntaxError):
        return []


def find_deep(el: Optional[ET.Element], path: str) -> Optional[ET.Element]:
    if el is None:
        return None
    try:
        return el.find(f".//{qn(path)}")
    except (KeyError, SyntaxError):
        return None


def iter_descendants(el: ET.Element, tag: str) -> Iterator[ET.Element]:
    wanted = qn(tag)
    for node in el.iter():
        if node.tag == wanted:
            yield node


def attr(el: Optional[ET.Element], name: str, default: Any = None) -> Any:
    if el is None:
        return default
    value = el.get(qn(name))
    return default if value is None else value
