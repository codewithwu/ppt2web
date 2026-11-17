"""最小 OOXML 包读取器（标准库实现）。

.pptx 就是个 zip：
    [Content_Types].xml
    ppt/presentation.xml           ← 幻灯片顺序在这里
    ppt/_rels/presentation.xml.rels
    ppt/slides/slide1.xml
    ppt/slides/_rels/slide1.xml.rels
    ...

只要能读 zip + 解析 XML + 顺着 rels 找部件，就够用了。
"""

from __future__ import annotations

import posixpath
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from typing import Optional

from .ooxml import NS, find, findall, qn

CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
OVERRIDE = "{%s}Override" % CONTENT_TYPES
DEFAULT = "{%s}Default" % CONTENT_TYPES
REL_TAG = "{%s}Relationship" % NS["rel"]

# 内容类型 → 文件扩展名
EXT_BY_CT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/tiff": "tif",
    "image/x-emf": "emf",
    "image/x-wmf": "wmf",
    "image/svg+xml": "svg",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
}


@dataclass
class Rel:
    r_id: str
    rel_type: str
    target: str
    mode: str = "Internal"

    @property
    def type_suffix(self) -> str:
        """关系类型的最后一段，如 '.../image' → 'image'。"""
        return self.rel_type.rsplit("/", 1)[-1]


class Package:
    """一个 .pptx（.docx/.xlsx 同理）包。"""

    def __init__(self, path: str):
        self.path = path
        self.zip = zipfile.ZipFile(path)
        self._xml: dict[str, ET.Element] = {}
        self._rels: dict[str, dict[str, Rel]] = {}
        self._content_types: dict[str, str] = {}
        self._load_content_types()

    # ------------------------------------------------------------------
    def _load_content_types(self) -> None:
        try:
            root = ET.fromstring(self.zip.read("[Content_Types].xml"))
        except KeyError:
            return
        for node in root:
            tag = node.tag
            if tag == OVERRIDE:
                self._content_types[node.get("PartName", "").lstrip("/")] = node.get(
                    "ContentType", ""
                )
            elif tag == DEFAULT:
                self._content_types["*." + node.get("Extension", "").lower()] = node.get(
                    "ContentType", ""
                )

    def content_type(self, partname: str) -> str:
        if partname in self._content_types:
            return self._content_types[partname]
        ext = partname.rsplit(".", 1)[-1].lower() if "." in partname else ""
        return self._content_types.get("*." + ext, "")

    def extension(self, partname: str) -> str:
        ct = self.content_type(partname)
        if ct in EXT_BY_CT:
            return EXT_BY_CT[ct]
        if "." in partname:
            return partname.rsplit(".", 1)[-1].lower()
        return "bin"

    # ------------------------------------------------------------------
    def names(self) -> list[str]:
        return self.zip.namelist()

    def read(self, partname: str) -> bytes:
        return self.zip.read(partname.lstrip("/"))

    def xml(self, partname: str) -> Optional[ET.Element]:
        partname = partname.lstrip("/")
        if partname in self._xml:
            return self._xml[partname]
        try:
            root = ET.fromstring(self.zip.read(partname))
        except (KeyError, ET.ParseError):
            return None
        self._xml[partname] = root
        return root

    # ------------------------------------------------------------------
    def rels(self, partname: str) -> dict[str, Rel]:
        """读取某个部件的 .rels，返回 {rId: Rel}。"""
        partname = partname.lstrip("/")
        if partname in self._rels:
            return self._rels[partname]
        directory, _, filename = partname.rpartition("/")
        rels_path = f"{directory}/_rels/{filename}.rels" if directory else f"_rels/{filename}.rels"
        result: dict[str, Rel] = {}
        try:
            root = ET.fromstring(self.zip.read(rels_path))
        except (KeyError, ET.ParseError):
            self._rels[partname] = result
            return result
        for node in root.findall(REL_TAG):
            rel = Rel(
                r_id=node.get("Id", ""),
                rel_type=node.get("Type", ""),
                target=node.get("Target", ""),
                mode=node.get("TargetMode", "Internal"),
            )
            result[rel.r_id] = rel
        self._rels[partname] = result
        return result

    def resolve(self, partname: str, rel: Rel) -> str:
        """把 rel 的 Target 解析成包内的绝对部件名。"""
        if rel.mode == "External":
            return rel.target
        base = posixpath.dirname(partname.lstrip("/"))
        return posixpath.normpath(posixpath.join(base, rel.target)).lstrip("/")

    def related(self, partname: str, type_suffix: str) -> Optional[str]:
        """按关系类型找目标部件名。"""
        for rel in self.rels(partname).values():
            if rel.type_suffix == type_suffix:
                return self.resolve(partname, rel)
        return None

    def related_all(self, partname: str, type_suffix: str) -> list[str]:
        out = []
        for rel in self.rels(partname).values():
            if rel.type_suffix == type_suffix:
                out.append(self.resolve(partname, rel))
        return out

    def rel_target_for(self, partname: str, r_id: str) -> Optional[str]:
        rel = self.rels(partname).get(r_id)
        if rel is None:
            return None
        return self.resolve(partname, rel)

    # ------------------------------------------------------------------
    def slide_partnames(self) -> list[str]:
        """按 presentation.xml 里的顺序返回幻灯片部件名。"""
        pres = self.xml("ppt/presentation.xml")
        if pres is None:
            return []
        lst = find(pres, "p:sldIdLst")
        rels = self.rels("ppt/presentation.xml")
        out: list[str] = []
        for sld_id in findall(lst, "p:sldId"):
            r_id = sld_id.get(qn("r:id"))
            rel = rels.get(r_id or "")
            if rel is None:
                continue
            out.append(self.resolve("ppt/presentation.xml", rel))
        return out

    def core_properties(self) -> dict[str, str]:
        root = self.xml("docProps/core.xml")
        if root is None:
            return {}
        props: dict[str, str] = {}
        for key, tag in (
            ("title", "dc:title"),
            ("author", "dc:creator"),
            ("subject", "dc:subject"),
            ("description", "dc:description"),
        ):
            node = find(root, tag)
            if node is not None and node.text:
                props[key] = node.text
        return props
