"""结构探针：拿到任意 PPT 先摸清里面有什么，再决定工作量。

    ppt2web inspect 某文件.pptx
"""

from __future__ import annotations

import collections
from typing import Any

from .fontfiles import FontLibrary
from .fontmap import resolve as resolve_font
from .parse.deck import parse_deck, _walk_shapes
from .render.svg import SUPPORTED as SUPPORTED_GEOMS


def inspect(path: str) -> dict[str, Any]:
    deck = parse_deck(path)

    print(f"文件：{path}")
    print(f"标题：{deck.title or '(无)'}    作者：{deck.author or '(无)'}")
    print(
        f"尺寸：{deck.slide_width_emu} × {deck.slide_height_emu} EMU "
        f"({deck.slide_width_emu / 914400:.3f}in × {deck.slide_height_emu / 914400:.3f}in，"
        f"{deck.slide_width_emu / deck.slide_height_emu:.3f}:1)"
    )
    print(f"页数：{len(deck.slides)}")

    kind_count: collections.Counter = collections.Counter()
    geom_count: collections.Counter = collections.Counter()
    font_count: collections.Counter = collections.Counter()
    behavior_count: collections.Counter = collections.Counter()
    attr_count: collections.Counter = collections.Counter()
    preset_count: collections.Counter = collections.Counter()
    transition_count: collections.Counter = collections.Counter()
    unsupported: set[str] = set()

    for slide in deck.slides:
        # 下钻组合：形状/字体统计必须包含组合里的图元，
        # 否则清单会漏掉一大块（第 1 页封面标题就在组合里）。
        for shape in _walk_shapes(slide.shapes):
            kind_count[shape.kind] += 1
            if shape.geom:
                geom_count[shape.geom] += 1
                if shape.geom not in SUPPORTED_GEOMS and shape.geom != "custom":
                    unsupported.add(shape.geom)
            if shape.text:
                for para in shape.text.paragraphs:
                    for run in para.runs:
                        if run.font:
                            font_count[run.font] += 1
                        if run.east_asian_font:
                            font_count[run.east_asian_font] += 1
        for group in slide.timeline.groups:
            for b in group.behaviors:
                behavior_count[b.type] += 1
                attr_count[b.attr_name] += 1
                if b.preset_id:
                    preset_count[f"{b.preset_class}/{b.preset_id}"] += 1
        if slide.transition.kind:
            transition_count[slide.transition.kind] += 1

    def dump(title: str, counter: collections.Counter, limit: int = 40) -> None:
        if not counter:
            print(f"\n{title}：无")
            return
        print(f"\n{title}：")
        for name, n in counter.most_common(limit):
            print(f"  {n:6d}  {name}")

    print("\n—— 形状类型 ——")
    dump("图元种类", kind_count)
    dump("预设几何", geom_count)
    dump("字体", font_count)

    print("\n—— 动画 ——")
    total_groups = sum(len(s.timeline.groups) for s in deck.slides)
    print(f"时间轴组：{total_groups}")
    for slide in deck.slides:
        triggers = collections.Counter(g.trigger for g in slide.timeline.groups)
        n_beh = sum(len(g.behaviors) for g in slide.timeline.groups)
        print(
            f"  第 {slide.index} 页：{len(slide.timeline.groups)} 组 / {n_beh} 条行为 "
            f"触发={dict(triggers)}"
        )
    dump("行为类型", behavior_count)
    dump("动画属性", attr_count)
    dump("预设", preset_count)

    print("\n—— 其它 ——")
    dump("页面转场", transition_count)
    print(f"\n媒体文件：{len(deck.media)}")
    for pic in deck.media:
        print(f"  {pic.part_name}  {len(pic.blob):>9d} bytes  {pic.ext}")

    if unsupported:
        print(f"\n⚠ 未覆盖的预设几何（当前用矩形替代）：{', '.join(sorted(unsupported))}")

    risks = _risks(deck, unsupported)
    if risks:
        print("\n⚠ 风险提示：")
        for r in risks:
            print(f"  - {r}")

    return {
        "slides": len(deck.slides),
        "kinds": dict(kind_count),
        "fonts": dict(font_count),
        "behaviors": dict(behavior_count),
        "unsupportedGeoms": sorted(unsupported),
    }


def _risks(deck, unsupported: set[str]) -> list[str]:
    risks: list[str] = []
    if unsupported:
        risks.append(f"{len(unsupported)} 种预设几何尚未实现，当前退化为矩形")
    kinds = {
        shape.kind
        for slide in deck.slides
        for shape in _walk_shapes(slide.shapes)
    }
    shapes = [
        shape
        for slide in deck.slides
        for shape in _walk_shapes(slide.shapes)
    ]
    charts = [s.chart for s in shapes if s.chart is not None]
    bad_charts = [c for c in charts if c.unsupported]
    if charts:
        if bad_charts:
            reasons = sorted({r for c in bad_charts for r in c.unsupported})
            risks.append(
                f"{len(bad_charts)}/{len(charts)} 个图表是暂不支持的类型，会降级成占位框："
                f"{'；'.join(reasons)}"
            )
        else:
            risks.append(f"包含 {len(charts)} 个图表（柱状/饼图/甜甜圈会真的画出来）")
    tables = [s.table for s in shapes if s.table is not None]
    bad_tables = [t for t in tables if t.unsupported]
    if tables:
        if bad_tables:
            risks.append(f"{len(bad_tables)}/{len(tables)} 个表格含合并单元格，会降级成占位框")
        else:
            risks.append(f"包含 {len(tables)} 个表格（会真的画出来）")
    if "diagram" in kinds:
        risks.append("包含 SmartArt：目前只渲染占位框")
    if "media" in kinds:
        risks.append("包含嵌入媒体：目前只渲染占位框")

    # 字体：分清三种情况
    #   ① fonts/local/ 里有真身 —— 转换期用真字形，只是**看这份稿的机器**没装
    #   ② 只有开源替代 —— 字形和原稿不同，排版可能漂移（断行、行数、段高）
    #   ③ 连替代都没有 —— 退到兜底字体，偏差更大
    library = FontLibrary()
    local_only: list[str] = []
    substituted: list[str] = []
    no_true_font: list[str] = []
    for name in sorted(deck.fonts_used):
        if library.local_font(name) is not None:
            local_only.append(name)
            continue
        resolved = resolve_font(name)
        if resolved is not None and resolved.spec is not None:
            substituted.append(f"{name}→{resolved.spec.family}")
        else:
            no_true_font.append(name)
    if local_only:
        risks.append(
            f"用到了 fonts/local/ 里有真身的字体（转换期用真身，看稿的机器没装会替换）："
            f"{', '.join(local_only)}"
        )
    if substituted:
        risks.append(
            f"这些字体没有真身，将用开源替代（字形/字宽不同，排版可能有偏差）："
            f"{', '.join(substituted)}"
        )
    if no_true_font:
        risks.append(
            f"这些字体既没有真身也没有开源替代（将退到兜底字体，版式偏差更大）："
            f"{', '.join(no_true_font)}"
        )
    return risks
