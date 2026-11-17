"""效果覆盖报告：逐页逐动画标注 native / approx / dropped。

判定规则：
- native —— 行为能被完整表达，参数与 PPT 一致
- approx —— 有降级维度（近似实现或参数丢失）
- dropped —— 无法表达：元素在动画开始前直接呈现，绝不静默消失

除了动画，报告还覆盖**页面转场**、**音频**、**几何降级**、**图表/表格占位框**
—— 凡是"源里有、产物里没有"的东西都必须在这里出现。

页面底部有一段机器可读的 JSON 摘要（``ppt2web-report-summary``），
``ppt2web verify`` 直接读它做门禁，不用去抠 HTML。
"""

from __future__ import annotations

import html
import json
from typing import Any

from ..model import Deck
from .effects import judge_filter
from .svg import SUPPORTED as SUPPORTED_GEOMS

#: 运行时**原生**实现的页面转场。
#: 与 ``runtime.js`` 里的 ``NATIVE_TRANSITIONS`` 一一对应 —— verify 会交叉检查：
#: 源文件用了表里没有的转场 → 硬失败（不然转场就是静默丢失）。
IMPLEMENTED_TRANSITIONS: set[str] = {
    "fade",
    "wipe",
    "push",
    "cover",
    "split",
    "cut",
    "dissolve",
    "zoom",
}

#: **近似**实现的转场（3D 转场降级成 2D 效果）。
#: 不算失败，但必须在报告里写清楚降级成了什么。
APPROX_TRANSITIONS: dict[str, str] = {
    "flythrough": "3D 镜头运动降级成「推近 + 淡入」",
}

# 行为类型 → (判定, 说明)
_BEHAVIOR_JUDGEMENT: dict[str, tuple[str, str]] = {
    "set": ("native", "可见性/属性直接设置"),
    "anim": ("native", "transform 通道插值"),
    "animRot": ("native", "旋转插值"),
    "animScale": ("native", "缩放插值"),
    "animClr": ("native", "颜色插值"),
    "animMotion": ("approx", "动作路径用 offset-path 近似"),
    "animEffect": ("approx", "入场效果按位移近似"),
    "cmd": ("dropped", "命令型动画无法表达，元素直接呈现"),
}


def _judge_cmd(b) -> tuple[str, str]:
    """命令型行为：能播媒体的就是实现了的。

    ``cmd="playFrom(0.0)"`` + 目标形状上挂着 ``a:audioFile`` → 播它。
    认不出媒体的就只能"元素直接呈现"（降级）。
    """
    if getattr(b, "media", None):
        return "native", f"播放媒体 {b.media.rsplit('/', 1)[-1]}"
    if getattr(b, "command", None):
        return "dropped", f"命令 {b.command} 无法表达，元素直接呈现"
    return "dropped", "命令型动画无法表达，元素直接呈现"


def _judge_behavior(b) -> tuple[str, str]:
    kind = b.type
    if kind == "animEffect":
        # 有 filter 的入场效果是精确描述 → 照着做就是原生
        return judge_filter(getattr(b, "filter_name", None))
    if kind == "cmd":
        return _judge_cmd(b)
    if kind in _BEHAVIOR_JUDGEMENT:
        verdict, note = _BEHAVIOR_JUDGEMENT[kind]
        if kind == "anim":
            if b.attr_name not in (
                "ppt_x",
                "ppt_y",
                "ppt_w",
                "ppt_h",
                "r",
                "style.opacity",
            ):
                return "approx", f"未知属性 {b.attr_name}，按 transform 近似"
            # 源里写了相对量（``#ppt_y+.1``），算出来却和起点一样
            # → 相对位移被抹平了，动作没表达出来。
            # 注意别误判：``#ppt_x`` → ``#ppt_x`` 是源文件**故意**让它不动
            # （"浮入"效果里 x 不变、只有 y 变），那是原样还原，不算降级。
            values = [kf.get("v") for kf in (b.keyframes or [])]
            if not values:
                return "approx", f"{b.attr_name} 没有关键帧（动作没有表达出来）"
            if len({str(v) for v in values}) == 1 and _has_relative_formula(b):
                return "approx", f"{b.attr_name} 的相对位移被抹平了（动作没有表达出来）"
        return verdict, note
    return "dropped", f"未知行为类型 {kind}"


def _has_relative_formula(b) -> bool:
    """行为里有没有"相对量"公式（解析层记在 notes 里）。"""
    return any(note.startswith("公式 #") for note in (getattr(b, "notes", None) or []))


def render_report(deck: Deck) -> str:
    rows: list[str] = []
    counts = {"native": 0, "approx": 0, "dropped": 0}
    dropped_items: list[dict[str, Any]] = []
    unsupported_geoms: set[str] = set()
    placeholders: dict[int, dict[str, int]] = {}
    rendered: dict[int, dict[str, int]] = {}
    unsupported_notes: list[str] = []
    custgeom = 0

    for slide in deck.slides:
        for group in slide.timeline.groups:
            for b in group.behaviors:
                verdict, note = _judge_behavior(b)
                counts[verdict] += 1
                if verdict == "dropped":
                    dropped_items.append(
                        {
                            "slide": slide.index,
                            "type": b.type,
                            "preset": f"{b.preset_class or '-'}/{b.preset_id or '-'}",
                            "target": b.target_id or "-",
                            "note": note,
                        }
                    )
                rows.append(
                    "<tr>"
                    f"<td>{slide.index}</td>"
                    f"<td>{html.escape(str(b.preset_id or '-'))}</td>"
                    f"<td>{html.escape(str(b.preset_class or '-'))}</td>"
                    f"<td>{html.escape(b.type)}</td>"
                    f"<td>{html.escape(b.attr_name)}</td>"
                    f"<td>{html.escape(str(getattr(b, 'filter_name', None) or '-'))}</td>"
                    f"<td>{html.escape(str(b.target_id or '-'))}</td>"
                    f"<td>{b.delay_ms}</td>"
                    f"<td>{b.duration_ms}</td>"
                    f'<td class="v-{verdict}">{verdict}</td>'
                    f"<td>{html.escape(note)}</td>"
                    "</tr>"
                )
        for shape in _all_shapes(slide.shapes):
            if shape.geom and shape.geom not in SUPPORTED_GEOMS and shape.geom != "custom":
                unsupported_geoms.add(shape.geom)
            if shape.geom == "custom":
                custgeom += 1
            if shape.kind == "chart":
                if shape.chart is not None and not shape.chart.unsupported:
                    bucket = rendered.setdefault(slide.index, {})
                    bucket["chart"] = bucket.get("chart", 0) + 1
                else:
                    bucket = placeholders.setdefault(slide.index, {})
                    bucket["chart"] = bucket.get("chart", 0) + 1
                    reason = (
                        "、".join(shape.chart.unsupported)
                        if shape.chart is not None
                        else "部件解析失败"
                    )
                    unsupported_notes.append(f"第 {slide.index} 页 图表：{reason}")
            elif shape.kind == "table":
                if shape.table is not None and not shape.table.unsupported:
                    bucket = rendered.setdefault(slide.index, {})
                    bucket["table"] = bucket.get("table", 0) + 1
                else:
                    bucket = placeholders.setdefault(slide.index, {})
                    bucket["table"] = bucket.get("table", 0) + 1
                    reason = (
                        "、".join(shape.table.unsupported)
                        if shape.table is not None
                        else "解析失败"
                    )
                    unsupported_notes.append(f"第 {slide.index} 页 表格：{reason}")
            elif shape.kind in ("diagram", "graphicframe"):
                bucket = placeholders.setdefault(slide.index, {})
                bucket[shape.kind] = bucket.get(shape.kind, 0) + 1

    # --- 页面转场 -------------------------------------------------------
    transitions: list[dict[str, Any]] = []
    for slide in deck.slides:
        if not slide.transition.kind:
            continue
        kind = slide.transition.kind
        native = kind in IMPLEMENTED_TRANSITIONS
        approx = APPROX_TRANSITIONS.get(kind)
        transitions.append(
            {
                "slide": slide.index,
                "kind": kind,
                "duration_ms": slide.transition.duration_ms,
                "direction": slide.transition.direction,
                "fallback": slide.transition.fallback_kind,
                "advance_ms": slide.transition.advance_ms,
                "implemented": native,
                "verdict": "native" if native else ("approx" if approx else "missing"),
                "note": approx or "",
            }
        )
    missing_transitions = [t for t in transitions if t["verdict"] == "missing"]
    approx_transitions = [t for t in transitions if t["verdict"] == "approx"]

    transition_html = ""
    if transitions:
        def _mark(t):
            if t["verdict"] == "native":
                return "— 原生实现"
            if t["verdict"] == "approx":
                return f"— <b>近似：{html.escape(t['note'])}</b>"
            return "— <b>未实现</b>"

        items = "".join(
            f"<li>第 {t['slide']} 页：{html.escape(str(t['kind']))}"
            f"（{t['duration_ms']}ms"
            + (f"，方向 {html.escape(str(t['direction']))}" if t["direction"] else "")
            + "）"
            f"{_mark(t)}</li>"
            for t in transitions
        )
        transition_html = (
            f"<h2>页面转场（共 {len(transitions)} 个，"
            f"原生 {len(transitions) - len(missing_transitions) - len(approx_transitions)}，"
            f"近似 {len(approx_transitions)}，"
            f"未实现 {len(missing_transitions)}）</h2><ul>{items}</ul>"
        )

    # --- 音频 -----------------------------------------------------------
    audio_clips = [
        {
            "part": clip.part_name,
            "bytes": len(clip.blob),
            "target": clip.target_id,
            "volume": clip.volume,
            "loop": clip.loop,
        }
        for clip in deck.audio
    ]
    audio_html = ""
    if audio_clips:
        items = "".join(
            f"<li>{html.escape(str(a['part']))}（{a['bytes']} 字节）"
            f"{'循环' if a['loop'] else '不循环'}，音量 {a['volume'] / 1000:.0f}%"
            f" — 已内嵌，由命令型动画触发播放"
            f"（浏览器的自动播放策略可能拦掉无手势的播放）</li>"
            for a in audio_clips
        )
        audio_html = f"<h2>音频 / 视频素材（共 {len(audio_clips)} 个）</h2><ul>{items}</ul>"

    geom_html = ""
    if unsupported_geoms:
        items = "".join(f"<li>{html.escape(g)}</li>" for g in sorted(unsupported_geoms))
        geom_html = f"<h2>未覆盖的预设几何（暂用矩形替代）</h2><ul>{items}</ul>"

    placeholder_html = ""
    if placeholders:
        items = "".join(
            f"<li>第 {page} 页：{kind} × {count}</li>"
            for page, kinds in sorted(placeholders.items())
            for kind, count in sorted(kinds.items())
        )
        placeholder_html = (
            "<h2>仍是占位框的元素</h2><ul>" + items + "</ul>"
        )
        if unsupported_notes:
            details = "".join(
                f"<li>{html.escape(n)}</li>" for n in unsupported_notes
            )
            placeholder_html += f"<ul>{details}</ul>"

    rendered_html = ""
    if rendered:
        total_charts = sum(k.get("chart", 0) for k in rendered.values())
        total_tables = sum(k.get("table", 0) for k in rendered.values())
        items = "".join(
            f"<li>第 {page} 页：{kind} × {count}</li>"
            for page, kinds in sorted(rendered.items())
            for kind, count in sorted(kinds.items())
        )
        rendered_html = (
            f"<h2>已渲染的图表与表格（共 {total_charts} 图 / {total_tables} 表）</h2>"
            f"<ul>{items}</ul>"
        )

    fonts = "".join(f"<li>{html.escape(f)}</li>" for f in deck.fonts_used)

    summary = {
        "counts": counts,
        "dropped": dropped_items,
        "transitions": transitions,
        "missingTransitions": missing_transitions,
        "approxTransitions": approx_transitions,
        "audio": audio_clips,
        "placeholders": [
            {"slide": page, **kinds} for page, kinds in sorted(placeholders.items())
        ],
        "unsupportedGeoms": sorted(unsupported_geoms),
        "fonts": list(deck.fonts_used),
    }
    summary_json = json.dumps(summary, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>ppt2web 覆盖报告</title>
<style>
body{{font-family:"Noto Sans CJK SC","Noto Sans",sans-serif;margin:32px;color:#222}}
table{{border-collapse:collapse;font-size:13px;width:100%}}
th,td{{border:1px solid #ddd;padding:5px 8px;text-align:left}}
th{{background:#f4f4f6}}
.v-native{{color:#0a7a3d;font-weight:600}}
.v-approx{{color:#a06000;font-weight:600}}
.v-dropped{{color:#b00020;font-weight:600}}
.counts{{font-size:15px;margin:12px 0}}
</style></head><body>
<h1>ppt2web 效果覆盖报告</h1>
<p class="counts">
native（原生）{counts['native']} ·
approx（近似）{counts['approx']} ·
dropped（降级）{counts['dropped']}
</p>
{transition_html}
{audio_html}
{geom_html}
{rendered_html}
{placeholder_html}
<h2>用到的字体</h2><ul>{fonts}</ul>
<p>（自定义几何 a:custGeom 已渲染：{custgeom} 个）</p>
<h2>逐条动画</h2>
<table>
<tr><th>页</th><th>presetID</th><th>类别</th><th>类型</th><th>属性</th><th>滤镜</th><th>目标</th>
<th>延时ms</th><th>时长ms</th><th>判定</th><th>说明</th></tr>
{"".join(rows)}
</table>
<script id="ppt2web-report-summary" type="application/json">{summary_json}</script>
</body></html>
"""


def _all_shapes(shapes):
    for shape in shapes:
        yield shape
        if shape.children:
            yield from _all_shapes(shape.children)
