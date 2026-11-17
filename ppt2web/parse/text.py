"""文本解析：段落、run、项目符号、自动缩放、文本框边距。"""

from __future__ import annotations

from typing import Any, Optional

from ..model import Color, Paragraph, Run, TextFrame
from .xmlutil import find, findall, read_color, read_text_fill

DEFAULT_MARGINS = (91440, 45720, 91440, 45720)  # l, t, r, b（EMU，默认 PowerPoint 0.1"/0.05"）


def parse_text_body(tx_body, level_defaults: Optional[list[dict[str, Any]]] = None) -> TextFrame:
    """解析 a:txBody / p:txBody。"""
    tf = TextFrame()
    if tx_body is None:
        return tf

    body_pr = find(tx_body, "a:bodyPr")
    if body_pr is not None:
        tf.anchor = body_pr.get("anchor")
        tf.wrap = body_pr.get("wrap")
        tf.vertical = body_pr.get("vert")
        tf.margins_emu = (
            int(body_pr.get("lIns", DEFAULT_MARGINS[0])),
            int(body_pr.get("tIns", DEFAULT_MARGINS[1])),
            int(body_pr.get("rIns", DEFAULT_MARGINS[2])),
            int(body_pr.get("bIns", DEFAULT_MARGINS[3])),
        )
        norm = find(body_pr, "a:normAutofit")
        if norm is not None:
            tf.autofit = "norm"
            if norm.get("fontScale"):
                tf.autofit_font_scale = int(norm.get("fontScale")) / 100000
            if norm.get("lnSpcReduction"):
                tf.autofit_line_spacing_reduction = int(norm.get("lnSpcReduction")) / 100000
        elif find(body_pr, "a:spAutoFit") is not None:
            tf.autofit = "shape"
        elif find(body_pr, "a:noAutofit") is not None:
            tf.autofit = "none"
        cols = find(body_pr, "a:normAutofit")
        if cols is not None:
            tf.columns = int(cols.get("numCol", 1))

    lst_defaults = _read_lst_style(tx_body)

    for p_el in findall(tx_body, "a:p"):
        tf.paragraphs.append(_parse_paragraph(p_el, level_defaults, lst_defaults))
    return tf


def _read_lst_style(tx_body) -> dict[int, dict[str, Any]]:
    """读形状级 ``a:lstStyle`` 里的各级默认文字属性。

    很多 PPT 把字体写在形状自己的 lstStyle 里（而不是每个 run 上）——
    漏掉这层，这些字就会掉回主题字体。
    """
    result: dict[int, dict[str, Any]] = {}
    lst = find(tx_body, "a:lstStyle")
    if lst is None:
        return result
    for child in lst:
        tag = child.tag.split("}")[-1]
        if not (tag.startswith("lvl") and tag.endswith("pPr")):
            continue
        try:
            level = int(tag[3:-3]) - 1  # lvl1pPr → 0
        except ValueError:
            continue
        def_rpr = find(child, "a:defRPr")
        if def_rpr is not None:
            result[level] = _read_rpr(def_rpr)
    return result


def _parse_paragraph(p_el, level_defaults, lst_defaults=None) -> Paragraph:
    para = Paragraph()
    p_pr = find(p_el, "a:pPr")
    defaults: dict[str, Any] = {}
    lst_defaults = lst_defaults or {}

    if p_pr is not None:
        para.level = int(p_pr.get("lvl") or 0)
        para.align = p_pr.get("algn")
        if p_pr.get("marL") is not None:
            para.margin_left_emu = int(p_pr.get("marL"))
        if p_pr.get("indent") is not None:
            para.indent_emu = int(p_pr.get("indent"))
        if p_pr.get("hanging") is not None:
            para.hanging_emu = int(p_pr.get("hanging"))

        ln_spc = find(p_pr, "a:lnSpc")
        if ln_spc is not None:
            pct = find(ln_spc, "a:spcPct")
            pts = find(ln_spc, "a:spcPts")
            if pct is not None:
                para.line_spacing = int(pct.get("val")) / 100000
            elif pts is not None:
                para.line_spacing_pt = int(pts.get("val")) / 100

        spc_bef = find(p_pr, "a:spcBef")
        if spc_bef is not None:
            pts = find(spc_bef, "a:spcPts")
            if pts is not None:
                para.space_before_pt = int(pts.get("val")) / 100
        spc_aft = find(p_pr, "a:spcAft")
        if spc_aft is not None:
            pts = find(spc_aft, "a:spcPts")
            if pts is not None:
                para.space_after_pt = int(pts.get("val")) / 100

        bu_char = find(p_pr, "a:buChar")
        bu_auto = find(p_pr, "a:buAutoNum")
        bu_none = find(p_pr, "a:buNone")
        bu_sz = find(p_pr, "a:buSzPct")
        if bu_char is not None:
            para.bullet_type = "char"
            para.bullet = bu_char.get("char")
        elif bu_auto is not None:
            para.bullet_type = "autoNum"
            para.bullet = bu_auto.get("type")
        elif bu_none is not None:
            para.bullet_type = "none"
        elif bu_sz is not None:
            para.bullet_size_pct = int(bu_sz.get("val")) / 1000
        para.bullet_color = read_color(find(p_pr, "a:buClr"))

        def_rpr = find(p_pr, "a:defRPr")
        if def_rpr is not None:
            defaults = _read_rpr(def_rpr)
    # 继承顺序：形状 lstStyle → 段落 defRPr（后者覆盖前者）
    merged: dict[str, Any] = {}
    merged.update(lst_defaults.get(para.level, {}))
    merged.update(defaults)
    defaults = merged
    para.default_run_props = defaults

    # 段落级默认（来自母版 bodyStyle）兜底项目符号
    if para.bullet_type is None and level_defaults:
        lvl_default = level_defaults[min(para.level, len(level_defaults) - 1)]
        if lvl_default.get("bullet"):
            para.bullet_type = lvl_default.get("bullet_type", "char")
            para.bullet = lvl_default["bullet"]
        if para.margin_left_emu is None and lvl_default.get("marL") is not None:
            para.margin_left_emu = lvl_default["marL"]
        if para.indent_emu is None and lvl_default.get("indent") is not None:
            para.indent_emu = lvl_default["indent"]

    for child in p_el:
        tag = child.tag.split("}")[-1]
        if tag == "r":
            para.runs.append(_parse_run(child, defaults))
        elif tag == "br":
            para.runs.append(Run(text="\n"))
        elif tag == "fld":
            # 域（如幻灯片编号）：取缓存文本
            t = find(child, "a:t")
            if t is not None and t.text:
                para.runs.append(Run(text=t.text))
    return para


def _parse_run(r_el, defaults: dict[str, Any]) -> Run:
    r_pr = find(r_el, "a:rPr")
    props = dict(defaults)
    if r_pr is not None:
        props.update(_read_rpr(r_pr))
    t = find(r_el, "a:t")
    text = t.text if t is not None and t.text else ""
    return Run(
        text=text,
        font=props.get("latin"),
        east_asian_font=props.get("ea"),
        size_pt=props.get("sz"),
        bold=bool(props.get("b")),
        italic=bool(props.get("i")),
        underline=props.get("u"),
        strike=props.get("strike"),
        color=props.get("color"),
        fill=props.get("fill"),
        baseline=props.get("baseline"),
        spacing_pt=props.get("spc"),
        caps=props.get("cap"),
    )


def _read_rpr(r_pr) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if r_pr.get("sz"):
        out["sz"] = int(r_pr.get("sz")) / 100
    if r_pr.get("b") is not None:
        out["b"] = r_pr.get("b") in ("1", "true")
    if r_pr.get("i") is not None:
        out["i"] = r_pr.get("i") in ("1", "true")
    if r_pr.get("u"):
        out["u"] = r_pr.get("u")
    if r_pr.get("strike"):
        out["strike"] = r_pr.get("strike")
    if r_pr.get("baseline"):
        out["baseline"] = int(r_pr.get("baseline"))
    if r_pr.get("spc"):
        out["spc"] = int(r_pr.get("spc")) / 100
    if r_pr.get("cap"):
        out["cap"] = r_pr.get("cap")
    latin = find(r_pr, "a:latin")
    if latin is not None:
        out["latin"] = latin.get("typeface")
    ea = find(r_pr, "a:ea")
    if ea is not None:
        out["ea"] = ea.get("typeface")
    color = read_color(r_pr)
    if color is not None:
        out["color"] = color
    text_fill = read_text_fill(r_pr)
    if text_fill is not None:
        out["fill"] = text_fill
    return out


def master_body_style(master_el) -> list[dict[str, Any]]:
    """从母版的 bodyStyle 读每级的默认项目符号与缩进。"""
    result: list[dict[str, Any]] = []
    if master_el is None:
        return result
    tx_styles = find(master_el, "p:txStyles")
    if tx_styles is None:
        return result
    body = find(tx_styles, "p:bodyStyle")
    if body is None:
        return result
    for lvl in range(1, 10):
        p_pr = find(body, f"p:lvl{lvl}pPr")
        entry: dict[str, Any] = {}
        if p_pr is not None:
            if p_pr.get("marL") is not None:
                entry["marL"] = int(p_pr.get("marL"))
            if p_pr.get("indent") is not None:
                entry["indent"] = int(p_pr.get("indent"))
            bu_char = find(p_pr, "a:buChar")
            bu_auto = find(p_pr, "a:buAutoNum")
            if bu_char is not None:
                entry["bullet"] = bu_char.get("char")
                entry["bullet_type"] = "char"
            elif bu_auto is not None:
                entry["bullet"] = bu_auto.get("type")
                entry["bullet_type"] = "autoNum"
        result.append(entry)
    return result
