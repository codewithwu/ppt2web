"""顶层解析入口：包 → Deck。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional

from ..affine import Affine
from ..model import Deck, Picture, Slide, Transition
from ..ooxml import find
from ..package import Package
from .animation import parse_timing
from .audio import parse_audio
from .shapes import ShapeCollector
from .text import master_body_style
from .theme import parse_theme, resolve_font_token


def parse_deck(path: str) -> Deck:
    pkg = Package(path)
    pres = pkg.xml("ppt/presentation.xml")
    deck = Deck()
    if pres is not None:
        sld_sz = find(pres, "p:sldSz")
        if sld_sz is not None:
            deck.slide_width_emu = int(sld_sz.get("cx", 9144000))
            deck.slide_height_emu = int(sld_sz.get("cy", 6858000))

    props = pkg.core_properties()
    deck.title = props.get("title", "")
    deck.author = props.get("author", "")

    media: dict[str, Picture] = {}

    for index, partname in enumerate(pkg.slide_partnames(), start=1):
        model = Slide(index=index)
        slide_el = pkg.xml(partname)
        if slide_el is None:
            deck.slides.append(model)
            continue

        layout_part = pkg.related(partname, "slideLayout")
        master_part = pkg.related(layout_part, "slideMaster") if layout_part else None
        theme_part = pkg.related(master_part, "theme") if master_part else None

        # 母版/版式可以带 themeOverride，它会顶掉母版的主题（字体/配色都可能变）
        for override_owner in (partname, layout_part):
            if not override_owner:
                continue
            override = pkg.related(override_owner, "themeOverride")
            if override:
                theme_part = override
                break

        theme = parse_theme(pkg.xml(theme_part) if theme_part else None)
        model.theme = theme

        master_el = pkg.xml(master_part) if master_part else None
        level_defaults = master_body_style(master_el)

        if layout_part:
            layout_el = pkg.xml(layout_part)
            if layout_el is not None:
                c_sld = find(layout_el, "p:cSld")
                model.layout_name = (c_sld.get("name") if c_sld is not None else "") or ""

        collector = ShapeCollector(pkg, partname, media, theme)
        shapes: list = []
        sp_tree = find(slide_el, "p:cSld/p:spTree")
        if sp_tree is not None:
            collector.collect(sp_tree, Affine(), (0.0, 0.0), shapes, level_defaults)
        model.shapes = shapes

        _resolve_fonts(model, theme)

        model.timeline = parse_timing(
            slide_el, deck.slide_width_emu, deck.slide_height_emu
        )
        model.transition = _parse_transition(slide_el)
        model.notes_text = _parse_notes(pkg, partname)
        deck.slides.append(model)

        # 音频/视频：素材本体挂在形状上（a:audioFile），播放由命令型动画触发
        clips = parse_audio(pkg, partname, slide_el)
        model.audio = clips
        deck.audio.extend(clips)
        _bind_media_commands(model, clips)

    deck.media = list(media.values())
    deck.fonts_used = sorted(_collect_fonts(deck))
    return deck


def _bind_media_commands(slide: Slide, clips: list) -> None:
    """把命令型行为（``cmd="playFrom(...)"``）和它要播的媒体对上。

    媒体挂在**目标形状**上（``a:audioFile``），命令的行为树里只写了
    形状 id —— 这一步把两者连起来，运行时才知道该播哪个文件。
    """
    if not clips:
        return
    by_target: dict[str, str] = {}
    for clip in clips:
        if clip.target_id:
            by_target[clip.target_id] = clip.part_name

    def walk(shapes):
        for shape in shapes:
            yield shape
            yield from walk(shape.children)

    part_by_shape = {
        shape.shape_id: shape.audio_part
        for shape in walk(slide.shapes)
        if shape.audio_part
    }
    for group in slide.timeline.groups:
        for behavior in group.behaviors:
            if behavior.type != "cmd":
                continue
            target = behavior.target_id
            part = part_by_shape.get(target or "")
            if part is None:
                part = by_target.get(target or "")
            if part:
                behavior.media = part


def _parse_transition(slide_el: ET.Element) -> Transition:
    """读页面转场。

    3D 转场（``p14:flythrough`` 之类）包在 ``mc:AlternateContent`` 里：

    .. code-block:: xml

        <mc:AlternateContent>
          <mc:Choice Requires="p14"><p:transition p14:dur="800"><p14:flythrough/></p:transition></mc:Choice>
          <mc:Fallback><p:transition><p:fade/></p:transition></mc:Fallback>
        </mc:AlternateContent>

    取 ``mc:Choice`` 里的那个（它是"真正"的转场），同时把 ``mc:Fallback``
    里的退化转场也记下来 —— 万一以后只实现得了退化版，可以用它。
    """
    trans = Transition()
    node = find(slide_el, "p:transition")
    if node is None:
        node = find(slide_el, "mc:AlternateContent/mc:Choice/p:transition")
    if node is None:
        return trans
    fallback = find(slide_el, "mc:AlternateContent/mc:Fallback/p:transition")
    if fallback is not None:
        for child in fallback:
            trans.fallback_kind = child.tag.split("}")[-1]
            break
    trans.speed = node.get("spd")
    dur = node.get("{http://schemas.microsoft.com/office/powerpoint/2010/main}dur")
    if dur:
        trans.duration_ms = int(dur)
    else:
        trans.duration_ms = {"fast": 500, "med": 750, "slow": 1000}.get(trans.speed or "", 0)
    adv = node.get("advTm")
    if adv and adv.isdigit():
        trans.advance_ms = int(adv)
    for child in node:
        trans.kind = child.tag.split("}")[-1]
        trans.direction = child.get("dir")
        break
    return trans


def _parse_notes(pkg: Package, partname: str) -> str:
    notes_part = pkg.related(partname, "notesSlide")
    if not notes_part:
        return ""
    root = pkg.xml(notes_part)
    if root is None:
        return ""
    # 备注正文在 notesSlide 的 body 占位符里
    for sp in root.iter():
        if sp.tag.split("}")[-1] != "sp":
            continue
        ph = find(sp, "p:nvSpPr/p:nvPr/p:ph")
        if ph is None:
            continue
        if ph.get("type") != "body":
            continue
        chunks = []
        for t in sp.iter():
            if t.tag.split("}")[-1] == "t" and t.text:
                chunks.append(t.text)
        return "".join(chunks)
    return ""


def _collect_fonts(deck: Deck) -> set[str]:
    fonts: set[str] = set()
    for slide in deck.slides:
        # 必须下钻组合：第 1 页的封面标题就在"组合 53"里，
        # 只遍历 slide.shapes 会把它漏掉 —— 清单少一款字体，
        # 后面"缺真身要不要补字体"的判断就全错了。
        for shape in _walk_shapes(slide.shapes):
            if not shape.text:
                continue
            for para in shape.text.paragraphs:
                for run in para.runs:
                    if run.font:
                        fonts.add(run.font)
                    if run.east_asian_font:
                        fonts.add(run.east_asian_font)
    return fonts


#: 标题类占位符继承 major 字体，其余继承 minor
_TITLE_PLACEHOLDERS = {"title", "ctrTitle", "subTitle"}


def _resolve_fonts(slide: Slide, theme: Theme) -> None:
    """把 run 上的字体槽解析成具体字体名。

    两件事：

    * **主题槽**：``+mn-ea`` / ``+mj-lt`` 这类 token 换成主题里真正的字体名
      （``Theme.font_for`` 之前定义了但没人用，字体名就这么丢了）。
    * **继承**：run / 段落都没指定 ``a:ea`` 时，PowerPoint 会沿
      「形状 lstStyle → 版式占位符 → 母版 txStyles → 主题 minorFont」
      往下找；我们只实现了最后一环，用主题 minor/major 兜底。

    解析后每个 run 同时有 latin 槽（西文用）和 ea 槽（中文用），
    两者**经常不是同一个字体**，渲染时要按字符分开取。
    """
    for shape in _walk_shapes(slide.shapes):
        if not shape.text:
            continue
        ph_type = (shape.placeholder or {}).get("type") or ""
        if ph_type in _TITLE_PLACEHOLDERS:
            inh_latin, inh_ea = theme.major_latin, theme.major_ea
        else:
            inh_latin, inh_ea = theme.minor_latin, theme.minor_ea
        for para in shape.text.paragraphs:
            for run in para.runs:
                run.font = resolve_font_token(theme, run.font) or inh_latin
                run.east_asian_font = resolve_font_token(theme, run.east_asian_font) or inh_ea


def _walk_shapes(shapes):
    for shape in shapes:
        yield shape
        if shape.children:
            yield from _walk_shapes(shape.children)
