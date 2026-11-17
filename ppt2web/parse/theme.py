"""主题（theme）解析：配色方案 + 字体方案。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional

from ..model import Theme
from ..ooxml import find

# 主题色槽 → clrScheme 里的元素名
_SLOT_TO_SCHEME = {
    "dk1": "dk1",
    "lt1": "lt1",
    "dk2": "dk2",
    "lt2": "lt2",
    "accent1": "accent1",
    "accent2": "accent2",
    "accent3": "accent3",
    "accent4": "accent4",
    "accent5": "accent5",
    "accent6": "accent6",
    "hlink": "hlink",
    "folHlink": "folHlink",
}

# 绘图时可能出现的别名（tx1/bg1 之类）
_ALIAS = {
    "tx1": "dk1",
    "tx2": "dk2",
    "bg1": "lt1",
    "bg2": "lt2",
    "phClr": "accent1",
}


def parse_theme(root: Optional[ET.Element]) -> Theme:
    theme = Theme()
    if root is None:
        return theme
    theme.name = root.get("name") or ""

    # 完整主题是 <a:theme><a:themeElements><a:clrScheme>…，
    # 而**主题覆盖**（themeOverride，图表/版式专用）少一层 themeElements：
    #     <a:themeOverride><a:clrScheme …>
    # 两种都得认，否则图表的配色整个查不到（颜色全变成 transparent）。
    scheme = find(root, "a:themeElements/a:clrScheme") or find(root, "a:clrScheme")
    if scheme is not None:
        theme.name = scheme.get("name") or theme.name
        for slot, elem_name in _SLOT_TO_SCHEME.items():
            node = find(scheme, f"a:{elem_name}")
            if node is None:
                continue
            srgb = find(node, "a:srgbClr")
            sys_clr = find(node, "a:sysClr")
            if srgb is not None:
                theme.colors[slot] = srgb.get("val")
            elif sys_clr is not None:
                theme.colors[slot] = sys_clr.get("lastClr") or "000000"

    font_scheme = find(root, "a:themeElements/a:fontScheme") or find(root, "a:fontScheme")
    if font_scheme is not None:
        major = find(font_scheme, "a:majorFont")
        minor = find(font_scheme, "a:minorFont")
        if major is not None:
            theme.major_latin = _font_name(major, "a:latin")
            theme.major_ea = _font_name(major, "a:ea")
        if minor is not None:
            theme.minor_latin = _font_name(minor, "a:latin")
            theme.minor_ea = _font_name(minor, "a:ea")
    return theme


def _font_name(font_el: ET.Element, path: str) -> Optional[str]:
    node = find(font_el, path)
    if node is None:
        return None
    return node.get("typeface")


def resolve_slot(slot: Optional[str]) -> Optional[str]:
    if not slot:
        return None
    return _ALIAS.get(slot, slot)


#: 主题字体槽 token → (major/minor, latin/ea/cs)
_THEME_TOKENS = {
    "+mj-lt": ("major", "latin"),
    "+mj-ea": ("major", "ea"),
    "+mj-cs": ("major", "cs"),
    "+mn-lt": ("minor", "latin"),
    "+mn-ea": ("minor", "ea"),
    "+mn-cs": ("minor", "cs"),
}


def resolve_font_token(theme: Theme, token: Optional[str]) -> Optional[str]:
    """把 ``+mn-ea`` 这类主题字体槽解析成主题里真正的字体名。

    按 token **自身的**槽位解析，而不是按它出现在哪个属性里 ——
    真实文件里存在 ``<a:latin typeface="+mj-ea"/>`` 这种"槽写错属性"
    的情况（PowerPoint 自己也会这么写），此时中文仍然该用 major ea。
    """
    if not token:
        return None
    key = token.strip()
    if key not in _THEME_TOKENS:
        return token
    group, slot = _THEME_TOKENS[key]
    if slot == "latin":
        return getattr(theme, f"{group}_latin", None)
    if slot == "ea":
        return getattr(theme, f"{group}_ea", None)
    # cs（复杂文种）主题里通常为空，回落到同组的 latin
    return getattr(theme, f"{group}_latin", None) or getattr(theme, f"{group}_ea", None)
