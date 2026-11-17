"""像素级视觉比对（**探索工具，不做门禁**）。

    ppt2web visual-diff out/ --pptx 某文件.pptx

做法：
1. 用 LibreOffice 把源 ``.pptx`` 渲成 PDF（"原稿"基准）
2. 用本机 Chrome 打印产物的 ``print.html``（"产物"）
3. 两边都栅格化成 PNG，逐页做像素 diff
4. 输出 diff 图 + 差异率，并**标注这一页有没有"已知差异"**

为什么要标"已知差异"：

LibreOffice 不是 PowerPoint，它在**至少三类**差异上是错的，而 ppt2web 是对的：

* **本机缺字体** —— 源文件里的商业字体（阿里巴巴普惠体等）本机没装，
  LibreOffice 换成系统字体，ppt2web 用真身或度量兼容的替代
* **``c15`` 扩展** —— WPS 把图表的类别名/系列名放在 ``c15:filteredCategoryTitle``，
  LibreOffice 不认，图表上就没有标签
* **``wrap="none"``** —— 源文件里"不自动换行"的文本框，PowerPoint 保持一行，
  LibreOffice 导入成按框宽换行

这些页面的 diff 天然很大，**不能当成 bug**。所以每一页都会带上
"这一页有没有已知差异"的标注 —— 没有标注还差异很大的页面，才是真正该查的。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

#: 判定"这一页有已知差异"的类别
KNOWN_REASONS = {
    "font": "本机缺商业字体，LibreOffice 替换了字体",
    "c15": "图表类别名/系列名在 c15 扩展里，LibreOffice 不支持",
    "wrap_none": "源文件里 wrap=\"none\" 的文本框，LibreOffice 导入成按宽换行",
    "fillrect": "图片填充用了 a:fillRect（出血/裁剪），LibreOffice 直接忽略它",
}


def find_soffice() -> Optional[str]:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _fontconfig_aliases(deck) -> list[tuple[str, str]]:
    """为"系统里没有"的字体找出可用的替代，写成 fontconfig 别名。

    LibreOffice 用的是**系统字体库**，不是 ``ppt2web/fonts/`` 里那份 ——
    源文件里的商业字体本机没装的话，LibreOffice 会换成 DejaVu Sans 兜底，
    比对出来的差异全是"字体不一样"，没有诊断价值。

    所以给 soffice 喂一份**临时**的 fontconfig 配置（``FONTCONFIG_FILE``），
    把这些字体指向系统里同源的替代 —— 只是这次调用生效，不改系统配置。
    """
    from .fontfiles import SYSTEM_ALIASES, normalize_font_name
    from .fontmap import resolve as resolve_font

    pairs: list[tuple[str, str]] = []
    names: set[str] = set()
    for slide in deck.slides:
        def walk(shapes):
            for shape in shapes:
                yield shape
                yield from walk(shape.children)

        for shape in walk(slide.shapes):
            if shape.text is None:
                continue
            for para in shape.text.paragraphs:
                for run in para.runs:
                    for name in (run.font, run.east_asian_font):
                        if name:
                            names.add(name)

    for name in sorted(names):
        if _system_has_font(name):
            continue
        resolved = resolve_font(name)
        if resolved is None or resolved.spec is None:
            continue
        family = resolved.spec.family
        system_family = SYSTEM_ALIASES.get(family, family)
        if _system_has_font(system_family):
            pairs.append((name, system_family))
    return pairs


def _write_fontconfig(workdir: Path, pairs: list[tuple[str, str]]) -> Optional[Path]:
    """写一份临时 fontconfig（包含系统配置 + 我们的别名）。"""
    if not pairs:
        return None
    rules = []
    for name, family in pairs:
        rules.append(
            "  <match target=\"pattern\">\n"
            f"    <test name=\"family\"><string>{name}</string></test>\n"
            f"    <edit name=\"family\" mode=\"prepend\" binding=\"strong\">"
            f"<string>{family}</string></edit>\n"
            "  </match>"
        )
    path = workdir / "ppt2web-fonts.conf"
    path.write_text(
        '<?xml version="1.0"?>\n'
        "<!DOCTYPE fontconfig SYSTEM \"fonts.dtd\">\n"
        "<fontconfig>\n"
        "  <include ignore_missing=\"yes\">/etc/fonts/fonts.conf</include>\n"
        + "\n".join(rules)
        + "\n</fontconfig>\n",
        encoding="utf-8",
    )
    return path


def _render_source_pdf(
    pptx_path: str, workdir: Path, fontconfig: Optional[Path] = None
) -> Optional[Path]:
    """LibreOffice 把源 pptx 渲成 PDF。"""
    soffice = find_soffice()
    if soffice is None:
        return None
    cmd = [
        soffice,
        "--headless",
        "--norestore",
        "--convert-to",
        "pdf",
        "--outdir",
        str(workdir),
        str(Path(pptx_path).resolve()),
    ]
    env = os.environ.copy()
    if fontconfig is not None:
        env["FONTCONFIG_FILE"] = str(fontconfig)
    try:
        subprocess.run(
            cmd, capture_output=True, text=True, timeout=900, env=env
        )
    except subprocess.TimeoutExpired:
        return None
    pdf = workdir / (Path(pptx_path).stem + ".pdf")
    return pdf if pdf.exists() else None


def _render_product_pdf(out_dir: Path, workdir: Path) -> Optional[Path]:
    """Chrome 打印产物的 print.html。"""
    from .export import export_pdf

    pdf = workdir / "product.pdf"
    try:
        export_pdf(str(out_dir), str(pdf))
    except SystemExit:
        return None
    return pdf if pdf.exists() else None


def _rasterize(pdf: Path, workdir: Path, prefix: str, dpi: int = 96) -> list[Path]:
    """PDF → PNG（每页一张）。"""
    try:
        import pymupdf
    except ImportError:
        return []
    zoom = dpi / 72.0
    out: list[Path] = []
    with pymupdf.open(str(pdf)) as doc:
        for index, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            path = workdir / f"{prefix}-{index:03d}.png"
            pix.save(str(path))
            out.append(path)
    return out


def _system_font(name: str) -> Optional[str]:
    """系统字体库里这个字体叫什么（fontconfig）。

    LibreOffice 用的是**系统字体**，不是 ppt2web/fonts/ 里那份 ——
    所以"转换器能还原"和"LibreOffice 能还原"是两件事。
    """
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{family}", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _system_has_font(name: str) -> bool:
    """系统里有没有这个字体（没有的话 LibreOffice 会替换 → 已知差异）。"""
    from .fontfiles import normalize_font_name

    matched = _system_font(name)
    if matched is None:
        return True  # 查不了就别乱标
    wanted = normalize_font_name(name)
    for part in matched.split(","):
        if normalize_font_name(part) == wanted:
            return True
    return False


def _page_reasons(slide, aliased: set[str]) -> list[str]:
    """这一页有哪些"已知差异"（会让 LibreOffice 渲错）。

    ``aliased`` 是已经用临时 fontconfig 指向了同源替代的字体 ——
    这些 LibreOffice 能用同一套字形渲染，**不算**已知差异。
    """
    reasons: list[str] = []
    fonts: set[str] = set()

    def walk(shapes):
        for shape in shapes:
            yield shape
            yield from walk(shape.children)

    for shape in walk(slide.shapes):
        if shape.text is not None:
            if shape.text.wrap == "none":
                reasons.append("wrap_none")
            for para in shape.text.paragraphs:
                for run in para.runs:
                    for name in (run.font, run.east_asian_font):
                        if not name or name in fonts or name in aliased:
                            continue
                        # 系统字体库里没有、也没别名 → LibreOffice 会换成别的字体
                        if not _system_has_font(name):
                            fonts.add(name)
        if shape.chart is not None:
            for note in shape.chart.notes:
                if "c15" in note:
                    reasons.append("c15")
                    break
        if shape.fill is not None and shape.fill.kind == "blip":
            # 图片填充：``a:fillRect`` 的负内缩表示图片比形状大（出血），
            # LibreOffice 不认这个元素，会用居中裁剪 —— 已知差异
            rect = shape.fill.blip_rect or (0.0, 0.0, 0.0, 0.0)
            if any(abs(v) > 1e-6 for v in rect):
                reasons.append("fillrect")
    if fonts:
        reasons.append("font")
    return sorted(set(reasons))


def _diff_page(a_path: Path, b_path: Path, diff_path: Path) -> tuple[float, float, float]:
    """返回 (可见差异像素比例, 边缘差异比例, 平均通道差)。

    "非零像素"这个指标没用：渲染引擎之间 1 像素的亚��素偏移就会让
    整页边缘都算成"差异"（背景图的缩放、字形的舍入）。
    所以这里给两个数：

    * **可见差异** —— 任一通道差 > 32，才算"人眼看得出来的差异"
    * **边缘差异** —— 任一通道差 > 0，只说明两张图不是逐像素相同
    """
    from PIL import Image, ImageChops

    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB")
    if a.size != b.size:
        b = b.resize(a.size)
    diff = ImageChops.difference(a, b)
    pixels = list(diff.getdata())
    total = len(pixels)
    edge = sum(1 for p in pixels if p != (0, 0, 0))
    visible = sum(1 for p in pixels if max(p) > 32)
    mean = sum(sum(p) for p in pixels) / (total * 3)
    diff.point(lambda v: min(255, v * 4)).save(str(diff_path))
    return visible / total * 100, edge / total * 100, mean


def visual_diff(
    out_dir: str,
    pptx_path: str,
    report_dir: Optional[str] = None,
    dpi: int = 96,
) -> dict:
    """跑一遍像素比对，返回报告数据。"""
    from .parse.deck import parse_deck

    out = Path(out_dir)
    target = Path(report_dir) if report_dir else out / "visual-diff"
    target.mkdir(parents=True, exist_ok=True)

    deck = parse_deck(pptx_path)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        aliases = _fontconfig_aliases(deck)
        fontconfig = _write_fontconfig(work, aliases)
        src_pdf = _render_source_pdf(pptx_path, work, fontconfig)
        prod_pdf = _render_product_pdf(out, work)
        if src_pdf is None:
            return {"error": "LibreOffice 渲染源文件失败（没装 soffice？）"}
        if prod_pdf is None:
            return {"error": "Chrome 打印产物失败"}
        src_png = _rasterize(src_pdf, work, "src", dpi)
        prod_png = _rasterize(prod_pdf, work, "prod", dpi)
        if not src_png or not prod_png:
            return {"error": "PDF 栅格化失败（缺 pymupdf？）"}

        pages = []
        for index in range(min(len(src_png), len(prod_png))):
            slide = deck.slides[index] if index < len(deck.slides) else None
            reasons = (
                _page_reasons(slide, {name for name, _ in aliases})
                if slide is not None
                else []
            )
            diff_file = target / f"diff-{index + 1:03d}.png"
            visible, edge, mean = _diff_page(
                src_png[index], prod_png[index], diff_file
            )
            pages.append(
                {
                    "slide": index + 1,
                    "diffPercent": round(visible, 2),
                    "edgeDiffPercent": round(edge, 2),
                    "meanChannelDiff": round(mean, 2),
                    "knownReasons": reasons,
                    "diffImage": diff_file.name,
                }
            )

    unknown = [p for p in pages if not p["knownReasons"]]
    unknown.sort(key=lambda p: -p["diffPercent"])
    summary = {
        "pages": pages,
        "total": len(pages),
        "withKnownReasons": len(pages) - len(unknown),
        "withoutKnownReasons": len(unknown),
        "worstWithoutKnownReasons": unknown[0] if unknown else None,
    }
    (target / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_html(target / "index.html", summary)
    return summary


def _write_html(path: Path, summary: dict) -> None:
    rows = []
    for page in summary["pages"]:
        reasons = "、".join(
            KNOWN_REASONS.get(r, r) for r in page["knownReasons"]
        )
        rows.append(
            "<tr>"
            f"<td>{page['slide']}</td>"
            f"<td>{page['diffPercent']:.2f}%</td>"
            f"<td>{page.get('edgeDiffPercent', 0):.2f}%</td>"
            f"<td>{page['meanChannelDiff']:.2f}</td>"
            f"<td>{reasons or '<b>无已知差异 — 值得查</b>'}</td>"
            f'<td><img src="{page["diffImage"]}" style="max-width:420px"></td>'
            "</tr>"
        )
    worst = summary.get("worstWithoutKnownReasons")
    headline = (
        f"差异最大且**没有已知差异**的页：第 {worst['slide']} 页（{worst['diffPercent']:.2f}%）"
        if worst
        else "所有有差异的页都能用已知差异解释"
    )
    path.write_text(
        f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>ppt2web 视觉比对</title>
<style>
body{{font-family:"Noto Sans CJK SC","Noto Sans",sans-serif;margin:32px;color:#222}}
table{{border-collapse:collapse;font-size:13px}}
th,td{{border:1px solid #ddd;padding:6px 10px;text-align:left;vertical-align:top}}
th{{background:#f4f4f6}}
</style></head><body>
<h1>ppt2web 视觉比对（探索工具，不是门禁）</h1>
<p>共 {summary['total']} 页：{summary['withKnownReasons']} 页有已知差异，
{summary['withoutKnownReasons']} 页没有 —— {headline}</p>
<p>已知差异类别：{'<br>'.join(f'· {k}：{v}' for k, v in KNOWN_REASONS.items())}</p>
<table>
<tr><th>页</th><th>可见差异</th><th>边缘差异</th><th>平均通道差</th><th>已知差异</th><th>diff 图</th></tr>
{"".join(rows)}
</table>
</body></html>
""",
        encoding="utf-8",
    )
