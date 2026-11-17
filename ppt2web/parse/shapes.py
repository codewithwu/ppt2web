"""图元遍历：把幻灯片的形状树展平成带绝对变换的 Shape 列表。"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from typing import Any, Optional

from ..affine import Affine
from ..model import Fill, Picture, Shape
from ..ooxml import find, findall, local_name, qn
from ..package import Package
from .text import parse_text_body
from .xmlutil import read_crop, read_fill, read_line, read_shadow, read_xfrm

GRAPHIC_TABLE = "http://schemas.openxmlformats.org/drawingml/2006/table"
GRAPHIC_CHART = "http://schemas.openxmlformats.org/drawingml/2006/chart"
GRAPHIC_DIAGRAM = "http://schemas.openxmlformats.org/drawingml/2006/diagram"

LEAF_TAGS = {"sp", "pic", "graphicFrame", "cxnSp"}

# 各图元的"非可视属性"容器路径
_CNVPR_PATHS = (
    "p:nvSpPr/p:cNvPr",
    "p:nvPicPr/p:cNvPr",
    "p:nvGraphicFramePr/p:cNvPr",
    "p:nvCxnSpPr/p:cNvPr",
    "p:nvGrpSpPr/p:cNvPr",
)


class ShapeCollector:
    """遍历形状树并累积媒体资源。"""

    def __init__(
        self,
        package: Package,
        partname: str,
        media_registry: dict[str, Picture],
        theme=None,
    ):
        self.package = package
        self.partname = partname
        self.media = media_registry
        #: 幻灯片的主题 —— 图表配色要用（图表自己也可以带主题覆盖）
        self.theme = theme
        self.z = 0

    def collect(
        self,
        container: ET.Element,
        child_space_to_abs: Affine,
        container_ch_off: tuple[float, float],
        out: list[Shape],
        level_defaults,
    ) -> None:
        """child_space_to_abs：容器子坐标空间 → 幻灯片坐标。

        container_ch_off：容器自身 div 局部空间相对其子坐标空间的原点偏移
        （分组用 chOff，幻灯片根用 (0,0)）。
        """
        for el in container:
            tag = local_name(el)
            if tag == "grpSp":
                self._collect_group(el, child_space_to_abs, container_ch_off, out, level_defaults)
            elif tag in LEAF_TAGS:
                self._collect_leaf(el, child_space_to_abs, container_ch_off, out, level_defaults)

    # ------------------------------------------------------------------
    def _collect_group(self, el, child_space_to_abs, container_ch_off, out, level_defaults) -> None:
        xfrm = read_xfrm(find(el, "p:grpSpPr/a:xfrm"))
        if xfrm is None:
            return
        cx, cy = xfrm["cx"], xfrm["cy"]
        chx, chy = xfrm.get("chx", 0), xfrm.get("chy", 0)
        chcx = xfrm.get("chcx", 1) or 1
        chcy = xfrm.get("chcy", 1) or 1
        sx, sy = cx / chcx, cy / chcy

        # 组的 div 局部空间（0..chExt）→ 容器子坐标空间
        center_x = xfrm["x"] + cx / 2
        center_y = xfrm["y"] + cy / 2
        to_parent = Affine().translate(center_x, center_y)
        if xfrm["rot"]:
            to_parent = to_parent.multiply(Affine().rotate(xfrm["rot"]))
        if xfrm["flip_h"] or xfrm["flip_v"]:
            to_parent = to_parent.multiply(
                Affine().scale(-1 if xfrm["flip_h"] else 1, -1 if xfrm["flip_v"] else 1)
            )
        to_parent = to_parent.translate(-center_x, -center_y)
        to_parent = to_parent.translate(xfrm["x"], xfrm["y"])
        to_parent = to_parent.scale(sx, sy)

        group = Shape(
            shape_id=str(self._cnvpr_id(el) or ""),
            name=self._cnvpr_name(el),
            kind="group",
            x=float(xfrm["x"]),
            y=float(xfrm["y"]),
            width=float(chcx),
            height=float(chcy),
            transform=child_space_to_abs.multiply(to_parent),
            local_transform=Affine()
            .translate(-container_ch_off[0], -container_ch_off[1])
            .multiply(to_parent),
            rotation=xfrm["rot"],
            flip_h=xfrm["flip_h"],
            flip_v=xfrm["flip_v"],
            z=self.z,
            ch_off=(float(chx), float(chy)),
        )
        self.z += 1

        # 组的子坐标空间 → 幻灯片
        child_space_to_abs_inner = child_space_to_abs.multiply(to_parent).multiply(
            Affine().translate(-chx, -chy)
        )
        self.collect(el, child_space_to_abs_inner, (chx, chy), group.children, level_defaults)
        out.append(group)

    # ------------------------------------------------------------------
    def _collect_leaf(self, el, child_space_to_abs, container_ch_off, out, level_defaults) -> None:
        tag = local_name(el)
        xfrm = self._read_any_xfrm(el)
        if xfrm is None:
            return
        own = self._own_matrix(xfrm)
        matrix = child_space_to_abs.multiply(own)

        c_nv_pr = None
        for path in _CNVPR_PATHS:
            c_nv_pr = find(el, path)
            if c_nv_pr is not None:
                break

        model = Shape(
            shape_id=str(c_nv_pr.get("id")) if c_nv_pr is not None else "",
            name=(c_nv_pr.get("name") if c_nv_pr is not None else "") or "",
            kind=self._kind_of(el, tag),
            x=float(xfrm["x"]),
            y=float(xfrm["y"]),
            width=float(xfrm["cx"]),
            height=float(xfrm["cy"]),
            transform=matrix,
            local_transform=Affine()
            .translate(-container_ch_off[0], -container_ch_off[1])
            .multiply(own),
            rotation=xfrm["rot"],
            flip_h=xfrm["flip_h"],
            flip_v=xfrm["flip_v"],
            z=self.z,
        )
        self.z += 1

        sp_pr = find(el, "p:spPr")
        if sp_pr is None:
            sp_pr = find(el, "p:grpSpPr")
        model.fill = read_fill(sp_pr)
        model.line = read_line(sp_pr)
        model.shadow = read_shadow(sp_pr)
        if model.fill.kind == "blip":
            self._fill_blip_fill(sp_pr, model)

        ph = find(el, "p:nvSpPr/p:nvPr/p:ph")
        if ph is None:
            ph = find(el, "p:nvPicPr/p:nvPr/p:ph")
        if ph is not None:
            model.placeholder = {
                "type": ph.get("type") or "body",
                "idx": ph.get("idx"),
                "orient": ph.get("orient"),
            }

        if tag == "pic":
            self._fill_picture(el, model)
            self._fill_audio_ref(el, model)
        elif tag == "graphicFrame":
            self._fill_graphic_frame(el, model)
        else:
            geom = find(sp_pr, "a:prstGeom")
            if geom is not None:
                model.geom = geom.get("prst")
                model.adj = _read_adj(geom)
            cust = find(sp_pr, "a:custGeom")
            if cust is not None:
                model.geom = "custom"
                model.geom_path = _read_custgeom_path(cust)

        tx_body = find(el, "p:txBody")
        if tx_body is not None:
            model.text = parse_text_body(tx_body, level_defaults)
            if model.kind == "shape" and any(p.runs for p in model.text.paragraphs):
                model.kind = "textbox"
        out.append(model)

    @staticmethod
    def _cnvpr(el: ET.Element) -> Optional[ET.Element]:
        for path in _CNVPR_PATHS:
            node = find(el, path)
            if node is not None:
                return node
        return None

    @classmethod
    def _cnvpr_id(cls, el: ET.Element) -> Optional[str]:
        node = cls._cnvpr(el)
        return node.get("id") if node is not None else None

    @classmethod
    def _cnvpr_name(cls, el: ET.Element) -> str:
        node = cls._cnvpr(el)
        return (node.get("name") if node is not None else "") or ""

    @staticmethod
    def _read_any_xfrm(el: ET.Element) -> Optional[dict[str, Any]]:
        for path in ("p:spPr/a:xfrm", "p:grpSpPr/a:xfrm", "p:xfrm"):
            data = read_xfrm(find(el, path))
            if data:
                return data
        return None

    @staticmethod
    def _own_matrix(xfrm: dict[str, Any]) -> Affine:
        """形状自身 xfrm → 局部盒(0,0,w,h) 到父坐标空间的映射。

        旋转/翻转都绕形状**自身中心**，所以顺序必须是：
        先把局部盒的中心移到原点 → 旋转/翻转 → 再把原点放回父空间里形状的中心。

        （顺序错了就变成绕左上角转/翻：形状会被甩出去，形状框也不再待在原位。）
        """
        cx, cy = xfrm["cx"], xfrm["cy"]
        center_x = xfrm["x"] + cx / 2
        center_y = xfrm["y"] + cy / 2
        m = Affine().translate(-cx / 2, -cy / 2)
        if xfrm["flip_h"] or xfrm["flip_v"]:
            m = Affine().scale(
                -1 if xfrm["flip_h"] else 1, -1 if xfrm["flip_v"] else 1
            ).multiply(m)
        if xfrm["rot"]:
            m = Affine().rotate(xfrm["rot"]).multiply(m)
        return Affine().translate(center_x, center_y).multiply(m)

    @staticmethod
    def _kind_of(el: ET.Element, tag: str) -> str:
        if tag == "pic":
            return "picture"
        if tag == "cxnSp":
            return "connector"
        if tag == "graphicFrame":
            graphic_data = find(el, "a:graphic/a:graphicData")
            uri = graphic_data.get("uri") if graphic_data is not None else ""
            if uri == GRAPHIC_TABLE:
                return "table"
            if uri == GRAPHIC_CHART:
                return "chart"
            if uri == GRAPHIC_DIAGRAM:
                return "diagram"
            return "graphicframe"
        return "shape"

    # ------------------------------------------------------------------
    def _fill_picture(self, el: ET.Element, model: Shape) -> None:
        blip = find(el, "p:blipFill/a:blip")
        if blip is None:
            return

        # 矢量优先：PowerPoint 2016+ 会把 SVG 放在 blip 的扩展里
        # （asvg:svgBlip）。有的文件 a:blip 上根本没有 r:embed，
        # 只有扩展里的 SVG —— 只认 r:embed 会让这个图元整个丢光。
        target = self._svg_blip_target(blip)
        if not target:
            r_embed = blip.get(qn("r:embed"))
            if not r_embed:
                return
            target = self.package.rel_target_for(self.partname, r_embed)
        if not target:
            return
        try:
            blob = self.package.read(target)
        except KeyError:
            return
        ext = self.package.extension(target)
        sha = hashlib.sha256(blob).hexdigest()
        pic = Picture(part_name=target, ext=ext, blob=blob, sha256=sha)
        pic.crop = read_crop(el)
        model.picture = pic
        self.media.setdefault(target, pic)

    def _fill_blip_fill(self, sp_pr: ET.Element, model: Shape) -> None:
        """把"形状被图片填充"里的图片接进来。

        和 ``<p:pic>`` 的图片图元是两条路：这里图片是形状的**填充**，
        要按形状轮廓裁剪（第 9 页的照片就放在圆角矩形里）。
        """
        blip_fill = find(sp_pr, "a:blipFill")
        if blip_fill is None:
            return
        blip = find(blip_fill, "a:blip")
        if blip is None:
            return
        target = self._svg_blip_target(blip)
        if not target:
            r_embed = blip.get(qn("r:embed"))
            if not r_embed:
                return
            target = self.package.rel_target_for(self.partname, r_embed)
        if not target:
            return
        try:
            blob = self.package.read(target)
        except KeyError:
            return
        ext = self.package.extension(target)
        sha = hashlib.sha256(blob).hexdigest()
        pic = Picture(part_name=target, ext=ext, blob=blob, sha256=sha)
        src_rect = find(blip_fill, "a:srcRect")
        if src_rect is not None:
            def val(name: str) -> float:
                raw = src_rect.get(name)
                return int(raw) / 100000 if raw is not None else 0.0

            crop = {"l": val("l"), "t": val("t"), "r": val("r"), "b": val("b")}
            if any(crop.values()):
                pic.crop = crop
        model.fill.blip = pic
        self.media.setdefault(target, pic)

    def _fill_audio_ref(self, el: ET.Element, model: Shape) -> None:
        """形状上挂着的音频/视频（``a:audioFile`` / ``a:videoFile``）。

        素材本体是幻灯片的关系（``r:link``），这里只记下包内路径 ——
        命令型动画（``cmd="playFrom(...)"``）靠它找到该播哪个文件。
        """
        for path in (
            "p:nvPicPr/p:nvPr/a:audioFile",
            "p:nvSpPr/p:nvPr/a:audioFile",
            "p:nvPicPr/p:nvPr/a:videoFile",
            "p:nvSpPr/p:nvPr/a:videoFile",
        ):
            node = find(el, path)
            if node is None:
                continue
            r_id = node.get(qn("r:link")) or node.get(qn("r:embed"))
            if not r_id:
                continue
            target = self.package.rel_target_for(self.partname, r_id)
            if target:
                model.audio_part = target
            return

    def _svg_blip_target(self, blip: ET.Element) -> Optional[str]:
        """从 blip 的扩展里找 SVG（asvg:svgBlip）。"""
        svg_blip = find(blip, "a:extLst/a:ext/asvg:svgBlip")
        if svg_blip is None:
            return None
        r_embed = svg_blip.get(qn("r:embed"))
        if not r_embed:
            return None
        return self.package.rel_target_for(self.partname, r_embed)

    def _fill_graphic_frame(self, el: ET.Element, model: Shape) -> None:
        graphic_data = find(el, "a:graphic/a:graphicData")
        uri = graphic_data.get("uri") if graphic_data is not None else ""
        model.notes.append(f"graphicData uri={uri}")

        if uri == GRAPHIC_CHART:
            self._fill_chart(el, model)
        elif uri == GRAPHIC_TABLE:
            self._fill_table(el, model)

    def _fill_chart(self, el: ET.Element, model: Shape) -> None:
        from .chart import parse_chart

        chart_el = find(el, "a:graphic/a:graphicData/c:chart")
        r_id = chart_el.get(qn("r:id")) if chart_el is not None else None
        target = self.package.rel_target_for(self.partname, r_id) if r_id else None
        if not target:
            model.notes.append("图表部件找不到")
            return
        chart = parse_chart(self.package, target, self.theme)
        if chart is None:
            model.notes.append("图表部件解析失败")
            return
        model.chart = chart
        model.notes.append(f"chart {chart.kind} · {len(chart.series)} 系列")

    def _fill_table(self, el: ET.Element, model: Shape) -> None:
        from .table import parse_table

        table = parse_table(self.package, el)
        if table is None:
            model.notes.append("表格解析失败")
            return
        model.table = table
        model.notes.append(f"table {len(table.rows)} 行 × {len(table.columns)} 列")


def _read_adj(geom: ET.Element) -> dict[str, Any]:
    adj: dict[str, Any] = {}
    for gd in findall(find(geom, "a:avLst"), "a:gd"):
        name = gd.get("name")
        fmla = gd.get("fmla") or ""
        if name and fmla.startswith("val "):
            try:
                adj[name] = int(fmla[4:])
            except ValueError:
                adj[name] = fmla[4:]
    return adj


def _read_custgeom_path(cust: ET.Element) -> Optional[str]:
    path_el = find(cust, "a:pathLst/a:path")
    if path_el is None:
        return None
    w = int(path_el.get("w") or 0)
    h = int(path_el.get("h") or 0)
    parts = []
    supported = {"moveTo", "lnTo", "cubicBezTo", "quadBezTo", "close"}
    for child in path_el:
        tag = local_name(child)
        if tag not in supported:
            # 不支持的路径命令（arcTo 等）：宁可退回矩形，也不要画错形状
            return None
        if tag == "moveTo":
            pt = find(child, "a:pt")
            if pt is not None:
                parts.append(f"M {pt.get('x')} {pt.get('y')}")
        elif tag == "lnTo":
            pt = find(child, "a:pt")
            if pt is not None:
                parts.append(f"L {pt.get('x')} {pt.get('y')}")
        elif tag == "cubicBezTo":
            pts = findall(child, "a:pt")
            if len(pts) == 3:
                parts.append(
                    f"C {pts[0].get('x')} {pts[0].get('y')} {pts[1].get('x')} {pts[1].get('y')} "
                    f"{pts[2].get('x')} {pts[2].get('y')}"
                )
        elif tag == "quadBezTo":
            pts = findall(child, "a:pt")
            if len(pts) == 2:
                parts.append(
                    f"Q {pts[0].get('x')} {pts[0].get('y')} {pts[1].get('x')} {pts[1].get('y')}"
                )
        elif tag == "close":
            parts.append("Z")
    if not parts:
        return None
    return f"{w}x{h}|" + " ".join(parts)
