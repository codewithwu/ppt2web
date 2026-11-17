"""命令行入口。

    ppt2web convert 样本.pptx -o out/     转换成网页包
    ppt2web inspect 样本.pptx             结构探针：先摸清一个 PPT 里有什么
    ppt2web verify  out/                 跑结构化断言（硬门禁）
    ppt2web export-pdf out/ -o deck.pdf   导出 PDF
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ppt2web", description="把 PPTX 转成可在浏览器里放映的自包含网页"
    )
    parser.add_argument("--version", action="version", version=f"ppt2web {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_convert = sub.add_parser("convert", help="转换成静态网页包")
    p_convert.add_argument("pptx")
    p_convert.add_argument("-o", "--out", default="out", help="输出目录（默认 out/）")
    p_convert.add_argument("-q", "--quiet", action="store_true")
    p_convert.add_argument(
        "--pdf", metavar="FILE", help="转换后顺便用 Chrome 导出一份 PDF"
    )
    p_convert.add_argument(
        "--text",
        choices=["vector", "html"],
        default="vector",
        help=(
            "文字渲染方式：vector=转成字形轮廓（不依赖字体、版式自算，默认）；"
            "html=保留 HTML 文字（可选中，依赖内嵌字体）"
        ),
    )
    p_convert.add_argument(
        "--wipe-direction",
        choices=["motion", "side"],
        default="motion",
        help=(
            "擦除（wipe）方向约定：motion=名字指擦除边缘的移动方向（默认）；"
            "side=名字指显现的起始边。真实文件里 filter 与 presetSubtype 可能矛盾，"
            "两种都实现了，用这个开关切换。"
        ),
    )
    p_convert.add_argument(
        "--mirror-text",
        action="store_true",
        help=(
            "翻转（flipH/flipV）的形状，文字也跟着镜像。"
            "默认不镜像：PowerPoint 翻转形状不会把文字镜像掉，"
            "文字保持正立、只在形状内部左右换位。"
        ),
    )

    p_inspect = sub.add_parser("inspect", help="结构探针")
    p_inspect.add_argument("pptx")

    p_verify = sub.add_parser("verify", help="结构化断言")
    p_verify.add_argument("out")
    p_verify.add_argument(
        "--pptx",
        metavar="FILE",
        help="同时回读源 .pptx 做端到端比对（逐字符文字、动画行为数）",
    )

    p_pdf = sub.add_parser("export-pdf", help="导出 PDF")
    p_pdf.add_argument("out")
    p_pdf.add_argument("-o", "--pdf", default="deck.pdf")

    p_visual = sub.add_parser(
        "visual-diff",
        help="像素级视觉比对（探索工具，不做门禁）",
    )
    p_visual.add_argument("out")
    p_visual.add_argument("--pptx", required=True, metavar="FILE", help="源 .pptx")
    p_visual.add_argument(
        "--report",
        metavar="DIR",
        help="报告输出目录（默认 out/visual-diff/）",
    )
    p_visual.add_argument(
        "--dpi", type=int, default=96, help="栅格化分辨率（默认 96）"
    )

    args = parser.parse_args(argv)

    if args.command == "convert":
        from .render.site import convert

        convert(
            args.pptx,
            args.out,
            quiet=args.quiet,
            wipe_direction=args.wipe_direction,
            text_mode=args.text,
            mirror_text=args.mirror_text,
        )
        if args.pdf:
            from .export import export_pdf

            export_pdf(args.out, args.pdf)
        return 0

    if args.command == "inspect":
        from .inspect import inspect

        inspect(args.pptx)
        return 0

    if args.command == "verify":
        from .verify import verify

        ok = verify(args.out, pptx_path=args.pptx)
        return 0 if ok else 1

    if args.command == "export-pdf":
        from .export import export_pdf

        export_pdf(args.out, args.pdf)
        return 0

    if args.command == "visual-diff":
        from .visual import visual_diff

        summary = visual_diff(args.out, args.pptx, args.report, args.dpi)
        if summary.get("error"):
            print(f"✗ {summary['error']}")
            return 1
        worst = summary.get("worstWithoutKnownReasons")
        print(f"✓ 视觉比对完成：{summary['total']} 页 → 报告在 {args.report or 'out/visual-diff'}")
        print(
            f"  {summary['withKnownReasons']} 页有已知差异（字体缺失 / c15 扩展 / wrap=none），"
            f"{summary['withoutKnownReasons']} 页没有"
        )
        if worst:
            print(
                f"  值得查：第 {worst['slide']} 页差异 {worst['diffPercent']:.2f}%"
                f"（没有已知差异能解释它）"
            )
        return 0

    parser.error(f"未知命令 {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
