"""字体回退栈。

本机（以及很多观看者的机器）没有 Calibri / 微软雅黑 / 等线这些商业字体，
`fc-match` 会把它们统统回落到没有汉字覆盖的 DejaVu。所以每个替代字体
都要配一条"同度量或有汉字覆盖"的回退栈。

具体字体到替代方案的映射见 fontplan.py。
"""

from __future__ import annotations

# 通用回退
DEFAULT_STACK = ["Noto Sans", "DejaVu Sans", "sans-serif"]
# 有汉字覆盖的回退
CJK_STACK = ["Noto Sans CJK SC", "Noto Sans", "DejaVu Sans", "sans-serif"]

# 各替代方案对应的系统回退栈（产物里内嵌的 family 排在最前）
STACKS: dict[str, list[str]] = {
    "Carlito": ["Calibri", "Carlito", "Noto Sans", "sans-serif"],
    "Arimo": ["Arial", "Arimo", "Noto Sans", "sans-serif"],
    "Noto Sans SC": ["Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", "sans-serif"],
    "Noto Serif SC": ["Noto Serif CJK SC", "SimSun", "Songti SC", "serif"],
}


def stack_for(family: str) -> list[str]:
    return STACKS.get(family, CJK_STACK)


def to_css(family: str) -> str:
    """把内嵌 family + 系统回退拼成 CSS font-family 值。

    内嵌的 family 必须排第一，否则浏览器会去用系统里的同名/近名字体，
    内嵌的 @font-face 永远不生效。
    """
    parts = [family] + [p for p in stack_for(family) if p != family]
    return ", ".join(f'"{p}"' if " " in p else p for p in parts)
