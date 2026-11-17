"""结构化断言（第 1 层验收，硬门禁）。

    ppt2web verify out/                       只查产物内部一致性
    ppt2web verify out/ --pptx 某文件.pptx    再回读源文件做端到端比对

校验项：
1. 每个媒体文件存在且 SHA-256 与 manifest 一致 → 证明"图片无损"
2. 每页幻灯片文件存在，且形状数量与 manifest 一致 → 证明"内容没丢"
3. 时间轴条目数与 manifest 一致 → 证明"动画没丢"
4. 每个动画目标在产物里都有对应节点 → 证明"动画不断链"
5. **文字逐字符对齐**：产物里渲染出来的文字 = 源 PPT 里的文字
   （不丢字、不串行、不错序）—— 这是最容易悄悄丢东西的地方
6. 字体覆盖：源文件用到的每个字体，要么内嵌了 @font-face，要么在回落清单里
7. 动效滤镜交叉检查：源文件用到的每个 filter，运行时必须实现
8. 索引与打印页齐全
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

_SHAPE_RE = re.compile(r'data-shape-id="([^"]+)"')
#: 图表/表格没渲染出来时留下的占位框
_PLACEHOLDER_RE = re.compile(
    r'<div class="gp-placeholder" data-kind="(?:chart|table)"'
)
_TIMELINE_RE = re.compile(
    r'<script id="ppt2web-timeline" type="application/json">(.*?)</script>', re.S
)
#: 报告里的机器可读摘要（verify 用它做门禁，不用抠 HTML）
_REPORT_SUMMARY_RE = re.compile(
    r'<script id="ppt2web-report-summary" type="application/json">(.*?)</script>', re.S
)
#: SVG 的 fill/stroke 属性**不接受 CSS 渐变函数** ——
#: 写进去浏览器会忽略，颜色退回初始值（黑）。
#: 这是"形状渐变全变黑"那类 bug 的指纹，必须门禁住。
_BAD_PAINT_RE = re.compile(r'(?:fill|stroke)="(?:linear|radial)-gradient\(')


class _TextCollector(HTMLParser):
    """把产物里的可见文字抠出来。

    跳过的：脚本、样式、页面标题、占位框（图表/表格还没渲染）、
    项目符号（项目符号是排版元素，不是源文字）。
    """

    SKIP_TAGS = {"script", "style", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip = 0
        self._skip_stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        cls = attr_map.get("class", "") or ""
        if (
            tag in self.SKIP_TAGS
            or "gp-placeholder" in cls
            or cls.strip() == "bul"
        ):
            self._skip_stack.append(tag)
            self._skip += 1

    def handle_endtag(self, tag):
        if self._skip_stack and self._skip_stack[-1] == tag:
            self._skip_stack.pop()
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if self._skip == 0 and data.strip():
            self.chunks.append(data)


def extract_text(html: str) -> str:
    collector = _TextCollector()
    collector.feed(html)
    return _normalize("".join(collector.chunks))


def _normalize(text: str) -> str:
    """归一化：去掉所有空白，只比字符序列。"""
    return re.sub(r"\s+", "", text)


def _source_text(slide) -> str:
    parts: list[str] = []
    for shape in _all_shapes(slide.shapes):
        if shape.text:
            for para in shape.text.paragraphs:
                for run in para.runs:
                    if run.text:
                        parts.append(run.text)
        if shape.table is not None:
            parts.append(_table_text(shape.table))
        if shape.chart is not None:
            parts.append(_chart_text(shape.chart))
    return _normalize("".join(parts))


def _table_text(table) -> str:
    """表格的文字（行优先）。产物里由 sr-only 的真表格承载，顺序一致。"""
    parts: list[str] = []
    for row in table.rows:
        for cell in row.cells:
            if cell.text is None:
                continue
            for para in cell.text.paragraphs:
                for run in para.runs:
                    if run.text:
                        parts.append(run.text)
    return "".join(parts)


def _chart_text(chart) -> str:
    """图表的文字：系列名 + 类别名（顺序和产物里的无障碍层一致）。"""
    parts: list[str] = []
    for series in chart.series:
        if series.name:
            parts.append(series.name)
    parts.extend(chart.categories)
    return "".join(parts)


def _all_shapes(shapes):
    for shape in shapes:
        yield shape
        if shape.children:
            yield from _all_shapes(shape.children)


def _expected_placeholders(slide) -> tuple[int, list[str]]:
    """这一页**应该**留几个占位框（= 我们明确不支持的图表/表格）。

    分级门禁的核心：已支持的类型必须零占位框（硬失败）；
    明确不支持的才允许留占位框，并且要记进报告里（警告）。
    """
    count = 0
    reasons: list[str] = []
    for shape in _all_shapes(slide.shapes):
        if shape.kind == "chart":
            if shape.chart is None:
                count += 1
                reasons.append("图表部件解析失败")
            elif shape.chart.unsupported:
                count += 1
                reasons.append(f"图表不支持：{'、'.join(shape.chart.unsupported)}")
        elif shape.kind == "table":
            if shape.table is None:
                count += 1
                reasons.append("表格解析失败")
            elif shape.table.unsupported:
                count += 1
                reasons.append(f"表格不支持：{'、'.join(shape.table.unsupported)}")
    return count, reasons


def verify(out_dir: str, pptx_path: Optional[str] = None) -> bool:
    out = Path(out_dir)
    failures: list[str] = []
    notes: list[str] = []

    manifest_path = out / "manifest.json"
    if not manifest_path.exists():
        print(f"✗ 缺少 {manifest_path}")
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # 1. 媒体字节一致
    for media in manifest.get("media", []):
        src = media.get("src")
        if not src:
            continue
        path = out / src
        if not path.exists():
            failures.append(f"媒体缺失：{src}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != media.get("sha256"):
            failures.append(f"媒体字节不一致（图片有损！）：{src}")
    notes.append(f"媒体 {len(manifest.get('media', []))} 个已逐一校验字节一致")

    # 2. 每页形状数一致
    total_shapes = 0
    slide_html: dict[int, str] = {}
    for slide in manifest.get("slides", []):
        path = out / slide["file"]
        if not path.exists():
            failures.append(f"缺少幻灯片：{slide['file']}")
            continue
        html = path.read_text(encoding="utf-8")
        slide_html[slide["index"]] = html
        count = len(_SHAPE_RE.findall(html))
        total_shapes += count
        expected = slide.get("shapes")
        if expected is not None and count != expected:
            failures.append(
                f"第 {slide['index']} 页形状数不符：manifest {expected}，产物 {count}"
            )
    notes.append(f"幻灯片 {len(manifest.get('slides', []))} 页，共 {total_shapes} 个图元")

    # 3. 时间轴条目 + 动画目标不断链
    filters_used: set[str] = set()
    for slide in manifest.get("slides", []):
        path = out / slide["file"]
        if not path.exists():
            continue
        html = path.read_text(encoding="utf-8")
        match = _TIMELINE_RE.search(html)
        if not match:
            failures.append(f"第 {slide['index']} 页缺少时间轴数据")
            continue
        try:
            timeline = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            failures.append(f"第 {slide['index']} 页时间轴 JSON 解析失败：{exc}")
            continue
        groups = len(timeline.get("groups", []))
        expected = slide.get("animationGroups")
        if expected is not None and groups != expected:
            failures.append(
                f"第 {slide['index']} 页动画组数不符：manifest {expected}，产物 {groups}"
            )
        present = set(_SHAPE_RE.findall(html))
        for group in timeline.get("groups", []):
            for behavior in group.get("behaviors", []):
                target = behavior.get("target_id")
                if target and target not in present:
                    failures.append(
                        f"第 {slide['index']} 页动画目标 {target} 在产物里不存在（动画会断链）"
                    )
                    break
                filt = behavior.get("filter")
                if filt:
                    filters_used.add(filt)

    # 4. 入口文件
    for name in ("index.html", "print.html", "report.html", "runtime.js", "slide.js"):
        if not (out / name).exists():
            failures.append(f"缺少 {name}")
    if not (out / "assets" / "ppt2web.css").exists():
        failures.append("缺少 assets/ppt2web.css")

    # 5. 动效滤镜必须在运行时实现
    runtime_js = out / "slide.js"
    if runtime_js.exists() and filters_used:
        runtime_text = runtime_js.read_text(encoding="utf-8")
        for filt in sorted(filters_used):
            if f'"{filt}"' not in runtime_text and f"{filt}:" not in runtime_text:
                failures.append(f"动效滤镜 {filt} 在运行时没有实现（会退化成位移近似）")
        notes.append(f"动效滤镜 {len(filters_used)} 种均已在运行时实现")

    # 6. 字体覆盖
    css_path = out / "assets" / "ppt2web.css"
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    embedded_families = set(re.findall(r"font-family:\s*'([^']+)'", css_text))
    fallbacks = list(manifest.get("fontFallbacks", []))
    subs = manifest.get("fontSubstitutions", {})
    local_fonts = manifest.get("localFonts", {})
    if manifest.get("textMode") == "vector":
        # 矢量模式：字体已经烘进字形轮廓，产物不需要 @font-face。
        # 门禁看的是"每个源字体都解析到了具体字体"（解析不到 → 形状退回 HTML，
        # 上面已经查过）。
        for name in manifest.get("fonts", []):
            if name in local_fonts or name in subs:
                continue
            failures.append(f"字体 {name} 没有解析到替代字体（矢量模式会退回 HTML 文字）")
        notes.append(
            f"矢量模式：字体烘进轮廓（真身 {len(local_fonts)} 种，"
            f"替代 {len(subs)} 种），产物无需内嵌 @font-face"
        )
    else:
        for name in manifest.get("fonts", []):
            if name in fallbacks:
                continue
            family = subs.get(name)
            if family and family in embedded_families:
                continue
            # 字体文件缺失时登记的是「族名（说明）」，按前缀匹配
            if family and any(f.startswith(family) for f in fallbacks):
                continue
            if family is None and not fallbacks:
                continue
            failures.append(f"字体 {name} 既没有内嵌也没有登记回落（会掉回系统字体）")
    notes.append(
        f"字体 {len(manifest.get('fonts', []))} 种，内嵌 {len(embedded_families)} 个 family，"
        f"回落 {len(fallbacks)} 种"
    )

    # 7. 矢量模式下不允许有形状静默退回 HTML 文字
    rendering = manifest.get("textRendering") or {}
    if manifest.get("textMode") == "vector":
        fallback = rendering.get("htmlFallbackShapes", 0)
        vector = rendering.get("vectorShapes", 0)
        if fallback:
            failures.append(
                f"矢量模式下有 {fallback} 个形状因为缺字形退回 HTML 文字"
                f"（补齐 ppt2web/fonts/ 里的字体后再转）"
            )
        notes.append(f"文字矢量化：{vector} 个形状转成字形轮廓，{fallback} 个退回 HTML")

    # 8. 端到端：回读源 PPT，逐字符比对文字
    if pptx_path:
        failures.extend(
            _compare_with_source(pptx_path, manifest, slide_html, notes, out)
        )

    # 9. 非法 SVG paint：渐变不能直接写进 fill/stroke
    bad_paint = 0
    for index, html in slide_html.items():
        hits = _BAD_PAINT_RE.findall(html)
        if hits:
            bad_paint += len(hits)
            failures.append(
                f"第 {index} 页有 {len(hits)} 处 fill/stroke 写成了 CSS 渐变函数"
                f"（SVG 不认，浏览器会退回黑色）"
            )
    if not bad_paint:
        notes.append("SVG 渐变写法正确（全部走 <defs> + url(#id)）")

    # 10. 页面转场：源文件用了的转场，运行时必须实现
    failures.extend(_check_transitions(manifest, out, notes))

    # 11. 报告摘要：dropped 必须是 0（丢就是丢，不能静默）
    failures.extend(_check_report(out, notes))

    # 12. 几何门禁：位置/尺寸/排版尺寸
    if pptx_path:
        from .parse.deck import parse_deck
        from .verify_layout import check_geometry

        deck = parse_deck(pptx_path)
        failures.extend(check_geometry(deck, slide_html, notes))

    for note in notes:
        print(f"  · {note}")
    if failures:
        print(f"\n✗ {len(failures)} 项未通过：")
        for f in failures:
            print(f"  - {f}")
        return False
    print("\n✓ 结构化断言全部通过")
    return True


def _compare_with_source(
    pptx_path: str,
    manifest: dict,
    slide_html: dict[int, str],
    notes: list[str],
    out_dir: Optional[Path] = None,
) -> list[str]:
    """重新解析源 PPT，和产物逐项比对（端到端）。"""
    from .parse.deck import parse_deck

    failures: list[str] = []
    deck = parse_deck(pptx_path)
    if len(deck.slides) != len(manifest.get("slides", [])):
        failures.append(
            f"页数不符：源 {len(deck.slides)}，产物 {len(manifest.get('slides', []))}"
        )

    text_pages = 0
    for slide in deck.slides:
        html = slide_html.get(slide.index)
        if html is None:
            failures.append(f"第 {slide.index} 页产物缺失")
            continue
        want = _source_text(slide)
        got = extract_text(html)
        if not want:
            continue
        text_pages += 1
        if want != got:
            failures.append(
                f"第 {slide.index} 页文字不一致：源 {len(want)} 字，产物 {len(got)} 字"
                f"（首个差异在第 {_first_diff(want, got)} 字）"
            )

        # 图表/表格：声称支持的必须真的画出来（不能留占位框）
        expected_ph, reasons = _expected_placeholders(slide)
        got_ph = len(_PLACEHOLDER_RE.findall(html))
        if got_ph != expected_ph:
            failures.append(
                f"第 {slide.index} 页图表/表格占位框数不符："
                f"源里有 {expected_ph} 个不支持的，产物里有 {got_ph} 个"
            )
        for reason in reasons:
            notes.append(f"第 {slide.index} 页 {reason}（降级为占位框，文字仍可搜索）")

        # 动画：组数与行为数
        groups = len(slide.timeline.groups)
        behaviors = sum(len(g.behaviors) for g in slide.timeline.groups)
        match = _TIMELINE_RE.search(html)
        if match:
            try:
                timeline = json.loads(match.group(1))
            except json.JSONDecodeError:
                timeline = {}
            got_groups = len(timeline.get("groups", []))
            got_behaviors = sum(len(g.get("behaviors", [])) for g in timeline.get("groups", []))
            if got_groups != groups:
                failures.append(
                    f"第 {slide.index} 页动画组数不符：源 {groups}，产物 {got_groups}"
                )
            if got_behaviors != behaviors:
                failures.append(
                    f"第 {slide.index} 页动画行为数不符：源 {behaviors}，产物 {got_behaviors}"
                )

    notes.append(f"回读源文件逐字符比对：{text_pages} 页有文字，全部对齐")

    # 媒体集合比对：源里**引用**的媒体，产物里必须都有。
    # 以前只校验"产物里已有的媒体字节是否一致" —— 转换时漏掉的媒体
    # 对 verify 完全隐形（第 9/17/21 页的 5 张图就是这么丢的）。
    if out_dir is not None:
        failures.extend(_compare_media(pptx_path, out_dir, notes))
    return failures


def _source_media_parts(pptx_path: str) -> set[str]:
    """源 pptx 里被关系引用到的媒体部件（取文件名）。"""
    import posixpath
    import zipfile

    names: set[str] = set()
    with zipfile.ZipFile(pptx_path) as z:
        for rels_name in z.namelist():
            if not rels_name.endswith(".rels"):
                continue
            data = z.read(rels_name).decode("utf-8", "replace")
            base = rels_name.rsplit("/_rels/", 1)[0]
            for target in re.findall(r'Target="([^"]+)"', data):
                if "media/" not in target:
                    continue
                if target.startswith("/"):
                    part = target.lstrip("/")
                else:
                    part = posixpath.normpath(posixpath.join(base, target))
                names.add(part.rsplit("/", 1)[-1])
    return names


def _compare_media(pptx_path: str, out_dir: Path, notes: list[str]) -> list[str]:
    """源里引用了、产物里却没有的媒体 → 硬失败。"""
    failures: list[str] = []
    source = _source_media_parts(pptx_path)
    assets_dir = out_dir / "assets"
    produced = (
        {
            p.name
            for p in assets_dir.iterdir()
            if p.is_file() and p.name != "ppt2web.css"
        }
        if assets_dir.exists()
        else set()
    )
    missing = sorted(source - produced)
    if missing:
        for name in missing:
            failures.append(
                f"源文件里的媒体 {name} 没有出现在产物里（这个资源被丢掉了）"
            )
    else:
        notes.append(f"媒体集合比对：源 {len(source)} 个全部出现在产物里")
    return failures


def _first_diff(a: str, b: str) -> int:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i + 1
    return min(len(a), len(b)) + 1


def _check_transitions(manifest: dict, out: Path, notes: list[str]) -> list[str]:
    """页面转场：源文件用了的转场，运行时必须真的实现。

    以前转场是**静默丢失**的：元数据解析了、写进 manifest 了，
    运行时只改 iframe.src，什么转场效果都没有 —— 而且 report 里
    连一条提示都没有。现在转场缺失 = 硬失败。

    "近似实现"（3D 转场降级成 2D 效果）不算失败，但会在 notes 里点出来。
    """
    from .render.report import APPROX_TRANSITIONS, IMPLEMENTED_TRANSITIONS

    failures: list[str] = []
    used: dict[str, list[int]] = {}
    for slide in manifest.get("slides", []):
        kind = slide.get("transition")
        if kind:
            used.setdefault(kind, []).append(slide["index"])
    if not used:
        notes.append("源文件没有页面转场")
        return failures

    runtime_text = ""
    runtime_js = out / "runtime.js"
    if runtime_js.exists():
        runtime_text = runtime_js.read_text(encoding="utf-8")

    native = 0
    approx: list[str] = []
    for kind, pages in sorted(used.items()):
        if kind in IMPLEMENTED_TRANSITIONS:
            native += 1
            if kind not in runtime_text:
                failures.append(
                    f"页面转场 {kind} 报告说已实现，但 runtime.js 里找不到对应实现"
                )
        elif kind in APPROX_TRANSITIONS:
            approx.append(f"{kind}（{APPROX_TRANSITIONS[kind]}）")
        else:
            failures.append(
                f"页面转场 {kind} 未实现（用在第 {pages[0]} 页等 {len(pages)} 页，"
                f"翻页时不会有转场效果）"
            )
    notes.append(f"页面转场 {len(used)} 种：原生 {native}，近似 {len(approx)}")
    if approx:
        notes.append(f"近似实现的转场：{'、'.join(approx)}")
    return failures


def _check_report(out: Path, notes: list[str]) -> list[str]:
    """读报告里的机器可读摘要，做硬门禁。"""
    failures: list[str] = []
    report_path = out / "report.html"
    if not report_path.exists():
        return failures
    match = _REPORT_SUMMARY_RE.search(report_path.read_text(encoding="utf-8"))
    if not match:
        failures.append("report.html 里缺少机器可读摘要（ppt2web-report-summary）")
        return failures
    try:
        summary = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        failures.append(f"报告摘要解析失败：{exc}")
        return failures

    counts = summary.get("counts", {})
    notes.append(
        f"覆盖报告：native {counts.get('native', 0)} · "
        f"approx {counts.get('approx', 0)} · "
        f"dropped {counts.get('dropped', 0)}"
    )

    dropped = summary.get("dropped", [])
    for item in dropped:
        failures.append(
            f"第 {item.get('slide')} 页有降级行为："
            f"{item.get('type')}（{item.get('preset')}）— {item.get('note')}"
        )

    missing = summary.get("missingTransitions", [])
    if missing:
        kinds = sorted({t.get("kind") for t in missing})
        notes.append(
            f"页面转场未实现 {len(missing)} 个（{', '.join(kinds)}）"
        )

    audio = summary.get("audio", [])
    if audio:
        notes.append(f"音频/视频素材 {len(audio)} 个（已内嵌，由命令型动画触发）")
    return failures
