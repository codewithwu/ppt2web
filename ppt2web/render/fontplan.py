"""字体子集化计划（HTML 文字模式用；矢量模式不需要 @font-face）。

fontsource 的可变字体已经按 unicode-range 切成了上百个分片，每个分片自带
wght 轴（一份文件覆盖 100–900 全部字重）。所以子集化不用 fontTools：
**扫描产物里实际用到的字符，反查落在哪几个分片，只把这几个 woff2 拷进产物**
—— 等效于精确子集化，且零额外依赖。

字体名 → 替代规格的映射在 :mod:`ppt2web.fontmap`，文件读取在
:mod:`ppt2web.fontfiles`。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..fontfiles import FontDescriptor, FontLibrary, font_family_name
from ..fontmap import FontSpec, ResolvedFont, resolve
from .fonts import to_css


@dataclass
class FontPlan:
    css: str = ""
    files: list[tuple[Path, str]] = field(default_factory=list)
    #: 源字体名 → 命中的替代规格
    families: dict[str, FontSpec] = field(default_factory=dict)
    #: 源字体名 → 解析结果（含字重）
    resolved: dict[str, ResolvedFont] = field(default_factory=dict)
    #: 源字体名 → 用户自放的真身字体文件
    local: dict[str, Path] = field(default_factory=dict)
    #: 没有替代方案的字体
    missing: set[str] = field(default_factory=set)

    def spec_for(self, source_name: Optional[str]) -> Optional[FontSpec]:
        if not source_name:
            return None
        info = self.resolved.get(source_name)
        return info.spec if info else None

    def weight_for(self, source_name: Optional[str]) -> Optional[int]:
        if not source_name:
            return None
        info = self.resolved.get(source_name)
        return info.weight if info else None

    def stack_for(self, source_name: Optional[str]) -> str:
        """源字体名 → CSS font-family 值。

        内嵌的 family 必须排第一，否则浏览器会去用系统里的同名/近名字体，
        内嵌的 @font-face 永远不生效。

        真身（``fonts/local/``）要用**字体文件内部声明的 family 名** ——
        和 :func:`materialize` 生成的 @font-face 对得上
        （``演示夏行楷.ttf`` 内部叫 "KaiTi"）。以前这里一律回落到替代规格的
        族名，真身字体等于白嵌。
        """
        if not source_name:
            return to_css("Noto Sans SC")
        info = self.resolved.get(source_name)
        if info is None:
            info = resolve(source_name)
        local = self.local.get(source_name)
        if local is not None:
            family = font_family_name(local) or local.stem
            return to_css(family)
        if info.spec is not None:
            return to_css(info.spec.family)
        return to_css("Noto Sans SC")


def _face_css(family: str, desc: FontDescriptor, file_name: str) -> str:
    return (
        "@font-face {\n"
        f"  font-family: '{family}';\n"
        f"  font-style: {desc.style};\n"
        f"  font-weight: {desc.weight};\n"
        "  font-display: swap;\n"
        f"  src: url(fonts/{file_name}) format('{desc.fmt}');\n"
        f"  unicode-range: {desc.unicode_range};\n"
        "}"
    )


def build_plan(
    font_usage: dict[str, set[str]], library: Optional[FontLibrary] = None
) -> FontPlan:
    """font_usage: {源字体名 → 该字体下用到的字符集合}。"""
    lib = library or FontLibrary()
    plan = FontPlan()
    css_blocks: list[str] = []
    used_files: set[str] = set()

    # 替代规格 → 需要覆盖的字符
    need: dict[str, set[int]] = {}

    for source_name, chars in font_usage.items():
        info = resolve(source_name)
        plan.resolved[source_name] = info
        local = lib.local_font(source_name)
        if local is not None:
            # 真身：直接把字体文件带进产物（HTML 模式下当作一个 @font-face）
            plan.local[source_name] = local
            continue
        if info.spec is None:
            if source_name:
                plan.missing.add(source_name)
            spec = _fallback_spec()
        else:
            spec = info.spec
        plan.families[source_name] = spec
        bucket = need.setdefault(spec.key, set())
        for ch in chars:
            bucket.add(ord(ch))

    for key, codes in need.items():
        spec = _spec_by_key(key)
        if spec is None:
            continue
        descriptors = lib.family(key)
        if not descriptors:
            plan.missing.add(f"{spec.family}（字体文件缺失）")
            continue
        for desc in descriptors:
            if desc.style not in ("normal", "italic"):
                continue
            if not any(desc.covers(code) for code in codes):
                continue
            out_name = Path(desc.src).name
            if out_name in used_files:
                continue
            src_path = lib.file_path(key, desc)
            if not src_path.exists():
                continue
            used_files.add(out_name)
            plan.files.append((src_path, out_name))
            css_blocks.append(_face_css(spec.family, desc, out_name))

    # 真身字体（用户自放）：直接作为 @font-face 带进产物
    for source_name, local_path in plan.local.items():
        info = plan.resolved.get(source_name)
        weight = info.weight if info else 400
        # family 用**字体文件内部声明的名字**（nameID 1），不是文件名 ——
        # 商用字体经常"文件名一套、内部名另一套"（演示夏行楷.ttf 内部叫"楷体"），
        # 声明成文件名的话浏览器按内部名匹配会落空。
        family = (
            info.spec.family
            if info and info.spec
            else (font_family_name(local_path) or local_path.stem)
        )
        fmt = {
            ".ttf": "truetype",
            ".otf": "opentype",
            ".ttc": "truetype",
            ".woff": "woff",
            ".woff2": "woff2",
        }.get(local_path.suffix.lower(), "truetype")
        out_name = local_path.name
        if out_name in used_files:
            continue
        used_files.add(out_name)
        plan.files.append((local_path, out_name))
        css_blocks.append(
            "@font-face {\n"
            f"  font-family: '{family}';\n"
            "  font-style: normal;\n"
            f"  font-weight: {weight};\n"
            "  font-display: swap;\n"
            f"  src: url(fonts/{out_name}) format('{fmt}');\n"
            "}"
        )

    plan.css = "\n\n".join(css_blocks)
    return plan


_FALLBACK_KEY = "Noto Sans SC"


def _fallback_spec() -> FontSpec:
    spec = _spec_by_key(_FALLBACK_KEY)
    assert spec is not None
    return spec


def _spec_by_key(key: str) -> Optional[FontSpec]:
    from ..fontmap import SPECS

    for spec in SPECS.values():
        if spec.key == key:
            return spec
    return None


def materialize(plan: FontPlan, assets_dir: Path) -> list[str]:
    """把选中的字体文件拷进产物目录，返回拷贝的文件名。"""
    fonts_dir = assets_dir / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for src_path, name in plan.files:
        target = fonts_dir / name
        if not src_path.exists():
            continue
        shutil.copyfile(src_path, target)
        copied.append(name)
    return copied
