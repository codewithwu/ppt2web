"""产物生成：中间模型 → 静态站点。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..model import Deck, Slide, Theme
from ..parse.deck import parse_deck
from .css import BASE_CSS, PLAYER_CSS, PRINT_CSS
from .fontplan import build_plan, materialize
from .html import render_slide
from .report import render_report

RUNTIME_DIR = Path(__file__).resolve().parent.parent / "runtime"


def convert(
    pptx_path: str,
    out_dir: str,
    quiet: bool = False,
    wipe_direction: str = "motion",
    text_mode: str = "vector",
    mirror_text: bool = False,
) -> dict[str, Any]:
    deck = parse_deck(pptx_path)
    out = Path(out_dir)
    (out / "slides").mkdir(parents=True, exist_ok=True)
    (out / "assets").mkdir(parents=True, exist_ok=True)

    # 媒体：字节级原样落盘（"图片无损"的硬指标）
    media_files: dict[str, str] = {}
    for pic in deck.media:
        name = pic.part_name.rsplit("/", 1)[-1]
        (out / "assets" / name).write_bytes(pic.blob)
        media_files[pic.part_name] = f"assets/{name}"

    # 音频/视频素材：也原样落盘（命令型动画要播它们）
    audio_files: dict[str, str] = {}
    for clip in deck.audio:
        if not clip.blob:
            continue
        name = clip.part_name.rsplit("/", 1)[-1]
        (out / "assets" / name).write_bytes(clip.blob)
        audio_files[clip.part_name] = f"assets/{name}"

    # 字体：按实际用到的字符挑分片，等效精确子集化
    plan = build_plan(_collect_font_usage(deck))
    font_files = []
    css = BASE_CSS
    if text_mode == "html":
        # HTML 文字模式才需要内嵌字体（矢量模式文字是路径，不依赖字体）
        font_files = materialize(plan, out / "assets")
        if plan.css:
            css += "\n\n/* ---- 内嵌字体（按用到的字符子集化） ---- */\n" + plan.css
    (out / "assets" / "ppt2web.css").write_text(css, encoding="utf-8")
    shutil.copyfile(RUNTIME_DIR / "runtime.js", out / "runtime.js")
    shutil.copyfile(RUNTIME_DIR / "slide.js", out / "slide.js")

    provider = None
    if text_mode == "vector":
        from .glyphs import GlyphProvider

        provider = GlyphProvider()

    slide_entries = []
    text_stats: dict[str, int] = {}
    for slide in deck.slides:
        theme = slide.theme or Theme()
        body = render_slide(
            slide, deck, theme, plan, provider, text_mode, text_stats,
            mirror_text=mirror_text,
        )
        timeline = _timeline_json(slide, wipe_direction)
        media_html = _media_html(slide, audio_files)
        name = f"{slide.index:03d}.html"
        (out / "slides" / name).write_text(
            _slide_html(body, timeline, deck, media_html), encoding="utf-8"
        )
        slide_entries.append(
            {
                "index": slide.index,
                "file": f"slides/{name}",
                "layout": slide.layout_name,
                "shapes": _count_shapes(slide.shapes),
                "animationGroups": len(slide.timeline.groups),
                "transition": slide.transition.kind,
                "transitionMs": slide.transition.duration_ms,
                "transitionDir": slide.transition.direction,
                "transitionFallback": slide.transition.fallback_kind,
                "advanceMs": slide.transition.advance_ms,
            }
        )

    manifest = {
        "title": deck.title,
        "author": deck.author,
        "slideWidth": deck.slide_width_emu / 9525.0,
        "slideHeight": deck.slide_height_emu / 9525.0,
        "slideWidthEmu": deck.slide_width_emu,
        "slideHeightEmu": deck.slide_height_emu,
        "slides": slide_entries,
        "textMode": text_mode,
        "textRendering": {
            "vectorShapes": text_stats.get("vector", 0),
            "htmlFallbackShapes": text_stats.get("html", 0),
        },
        "graphics": {
            "charts": text_stats.get("charts", 0),
            "tables": text_stats.get("tables", 0),
        },
        "fonts": deck.fonts_used,
        "embeddedFonts": font_files,
        "fontSubstitutions": {
            name: sub.family for name, sub in plan.families.items()
        },
        "fontWeights": {
            name: info.weight
            for name, info in plan.resolved.items()
            if info.spec is not None
        },
        "localFonts": {name: path.name for name, path in plan.local.items()},
        "fontFallbacks": sorted(plan.missing),
        "media": [
            {
                "src": media_files.get(p.part_name, ""),
                "sha256": p.sha256,
                "bytes": len(p.blob),
            }
            for p in deck.media
        ],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (out / "index.html").write_text(_index_html(deck, slide_entries), encoding="utf-8")
    (out / "print.html").write_text(_print_html(deck, slide_entries), encoding="utf-8")
    (out / "report.html").write_text(render_report(deck), encoding="utf-8")

    if not quiet:
        print(f"✓ {pptx_path} → {out}")
        print(f"  幻灯片 {len(deck.slides)} 页 · 媒体 {len(deck.media)} 个 · 字体 {len(deck.fonts_used)} 种")
    return manifest


def _count_shapes(shapes) -> int:
    """递归计数（含分组的子元素与分组本身）。"""
    total = 0
    for shape in shapes:
        total += 1
        if shape.children:
            total += _count_shapes(shape.children)
    return total


def _collect_font_usage(deck: Deck) -> dict[str, set[str]]:
    """每个源字体下用到了哪些字符 —— 决定要内嵌哪些 unicode-range 分片。

    一个 run 的字符可能分别落在 latin 槽和 ea 槽（中文走 ea、西文走 latin），
    所以两个槽都要统计。
    """
    usage: dict[str, set[str]] = {}
    for slide in deck.slides:
        for shape in _all_shapes(slide.shapes):
            if not shape.text:
                continue
            for para in shape.text.paragraphs:
                for run in para.runs:
                    for name in (run.font, run.east_asian_font):
                        if not name:
                            continue
                        chars = usage.setdefault(name, set())
                        chars.update(run.text)
    return usage


def _all_shapes(shapes):
    for shape in shapes:
        yield shape
        if shape.children:
            yield from _all_shapes(shape.children)


def _timeline_json(slide: Slide, wipe_direction: str = "motion") -> dict[str, Any]:
    groups = []
    for group in slide.timeline.groups:
        behaviors = []
        for b in group.behaviors:
            behaviors.append(
                {
                    "type": b.type,
                    "attr_name": b.attr_name,
                    "target_id": b.target_id,
                    "duration_ms": b.duration_ms,
                    "delay_ms": b.delay_ms,
                    "keyframes": b.keyframes,
                    "preset_id": b.preset_id,
                    "preset_class": b.preset_class,
                    "filter": b.filter_name,
                    "transition": b.transition,
                    "command": b.command,
                    "media": b.media.rsplit("/", 1)[-1] if b.media else None,
                }
            )
        groups.append(
            {
                "trigger": group.trigger,
                "startDelay": group.start_delay_ms,
                "behaviors": behaviors,
                "targets": group.target_ids,
            }
        )
    return {"groups": groups, "options": {"wipeDirection": wipe_direction}}


def _media_html(slide: Slide, audio_files: dict[str, str]) -> str:
    """这一页的音频/视频元素（命令型动画会播它们）。

    ``<audio>`` 用**同目录**的相对路径 —— ``file://`` 下也能播，
    不需要 fetch（浏览器的 file:// 限制）。
    """
    parts = []
    for clip in slide.audio:
        src = audio_files.get(clip.part_name)
        if not src:
            continue
        name = clip.part_name.rsplit("/", 1)[-1]
        attrs = [
            f'id="ppt2web-media-{html_escape(name)}"',
            f'src="../{src}"',
            'preload="auto"',
        ]
        if clip.loop:
            attrs.append("loop")
        parts.append(f"<audio {' '.join(attrs)}></audio>")
    if not parts:
        return ""
    return (
        '<div class="ppt2web-media" hidden>'
        + "".join(parts)
        + "</div>"
    )


def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _slide_html(body: str, timeline: dict, deck: Deck, media_html: str = "") -> str:
    data = json.dumps(timeline, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>slide</title>
<link rel="stylesheet" href="../assets/ppt2web.css">
<style>html,body{{background:#fff;overflow:hidden;}}</style>
</head>
<body>
{body}
{media_html}
<script id="ppt2web-timeline" type="application/json">{data}</script>
<script>window.PPT2WEB_TIMELINE = JSON.parse(document.getElementById("ppt2web-timeline").textContent);</script>
<script src="../slide.js"></script>
</body>
</html>
"""


def _index_html(deck: Deck, slides: list[dict]) -> str:
    data = json.dumps(
        {
            "slideWidth": deck.slide_width_emu / 9525.0,
            "slideHeight": deck.slide_height_emu / 9525.0,
            "slides": slides,
        },
        ensure_ascii=False,
    )
    title = deck.title or "ppt2web"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="assets/ppt2web.css">
<style>{PLAYER_CSS}</style>
</head>
<body class="deck-body">
<div class="deck">
  <div class="deck-frame" id="deck-frame">
    <iframe id="deck-iframe" title="slide" allowfullscreen></iframe>
    <iframe id="deck-iframe-back" title="slide" allowfullscreen hidden></iframe>
  </div>
</div>
<div class="deck-bar" id="deck-bar">
  <button id="deck-prev">← 上一页</button>
  <button id="deck-next">下一页 →</button>
  <span class="pos" id="deck-pos"></span>
  <span class="spacer"></span>
  <span class="hint">← → 翻页 · 空格 推进动画 · F 全屏 · O 控件栏</span>
</div>
<script>window.PPT2WEB = {data};</script>
<script src="runtime.js"></script>
</body>
</html>
"""


def _print_html(deck: Deck, slides: list[dict]) -> str:
    width_in = deck.slide_width_emu / 914400
    height_in = deck.slide_height_emu / 914400
    pages = "\n".join(
        f'<div class="print-page"><iframe src="{s["file"]}"></iframe></div>' for s in slides
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>print</title>
<style>
{PRINT_CSS}
@page {{ size: {width_in:.4f}in {height_in:.4f}in; margin: 0; }}
.print-page {{ width: {width_in:.4f}in; height: {height_in:.4f}in; }}
</style>
</head>
<body>
{pages}
</body>
</html>
"""
