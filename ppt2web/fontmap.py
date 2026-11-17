"""字体名解析：把 PPT 里的 typeface 映射成「替代字体 + 字重」。

三件事在这里解决：

1. **变体字重** —— PPT 的字体名经常自带字重后缀：
   ``思源宋体 CN Light`` / ``思源宋体 CN Heavy`` / ``思源宋体 CN SemiBold`` /
   ``阿里巴巴普惠体 2.0 45 Light``。字重藏在名字里，得拆出来，
   否则 Light 和 Heavy 会用同一个字重渲染。

2. **同族不同名** —— ``思源宋体 CN`` 就是开源的 Noto Serif SC（同一套字形），
   ``思源黑体 CN`` 就是 Noto Sans SC；``Calibri`` 用度量兼容的 Carlito，
   ``Arial`` 用 Arimo。

3. **真身优先** —— 用户把商用字体（阿里巴巴普惠体、演示夏行楷……）放进
   ``ppt2web/fonts/local/`` 时，转换器优先用真身画轮廓，自动从
   「替代字体」升级成「原字体」。

注意 latin / ea 两个槽是分开解析的：中文走 ``a:ea``、西文走 ``a:latin``，
两者经常不是同一个字体（``+mn-lt`` 与 ``+mn-ea`` 在不同主题里指向不同族）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# --------------------------------------------------------------------------
# 变体字重
# --------------------------------------------------------------------------

#: 字体名里的字重后缀 → CSS 字重数值
VARIANT_WEIGHTS: dict[str, int] = {
    "thin": 100,
    "hairline": 100,
    "extralight": 200,
    "ultralight": 200,
    "light": 300,
    "regular": 400,
    "book": 400,
    "normal": 400,
    "medium": 500,
    "semibold": 600,
    "demibold": 600,
    "bold": 700,
    "extrabold": 800,
    "ultrabold": 800,
    "black": 900,
    "heavy": 900,
}

#: 数字后缀也算版本号（阿里巴巴普惠体 2.0 45 Light），不是字重
_VERSION_TOKEN = re.compile(r"^[0-9.]+$")


def split_variant(name: str) -> tuple[str, Optional[int]]:
    """把 ``思源宋体 CN Heavy`` 拆成 ``("思源宋体 cn", 900)``。

    拆不掉就原样返回（字重 None，交给调用方用默认字重）。
    """
    tokens = name.strip().split()
    base = list(tokens)
    weight: Optional[int] = None
    while base:
        last = base[-1].lower()
        if last in VARIANT_WEIGHTS:
            weight = VARIANT_WEIGHTS[last]
            base.pop()
            continue
        if _VERSION_TOKEN.match(last) or last in ("of", "the"):
            base.pop()
            continue
        break
    if weight is None:
        return name.strip(), None
    return " ".join(base), weight


# --------------------------------------------------------------------------
# 替代字体表
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FontSpec:
    """一种可嵌入的字体（来自 npm fontsource 包）。

    package/css_files/src_family 是构建期取文件的依据；
    family 是产物里 @font-face 声明的名字。
    """

    key: str  # 规格标识（= family）
    package: str
    css_files: tuple[str, ...]
    family: str
    src_family: str
    weight_default: int = 400
    #: True = 与源字体同源（思源宋体 CN ≡ Noto Serif SC），字形一致
    same_origin: bool = False


_CARLITO = FontSpec(
    key="Carlito",
    package="@fontsource/carlito",
    css_files=("400.css", "700.css", "400-italic.css", "700-italic.css"),
    family="Carlito",
    src_family="Carlito",
)
_ARIMO = FontSpec(
    key="Arimo",
    package="@fontsource/arimo",
    css_files=("400.css", "700.css", "400-italic.css", "700-italic.css"),
    family="Arimo",
    src_family="Arimo",
)
_NOTO_SANS_SC = FontSpec(
    key="Noto Sans SC",
    package="@fontsource-variable/noto-sans-sc",
    css_files=("wght.css",),
    family="Noto Sans SC",
    src_family="Noto Sans SC Variable",
    # 思源黑体 CN 的开源同源版本 —— 字形完全一致
    same_origin=True,
)
_NOTO_SERIF_SC = FontSpec(
    key="Noto Serif SC",
    package="@fontsource-variable/noto-serif-sc",
    css_files=("wght.css",),
    family="Noto Serif SC",
    src_family="Noto Serif SC Variable",
    # 思源宋体 CN 的开源同源版本 —— 字形完全一致
    same_origin=True,
)
_MONOTON = FontSpec(
    key="Monoton",
    package="@fontsource/monoton",
    css_files=("400.css",),
    family="Monoton",
    src_family="Monoton",
)

#: 源字体名（小写）→ 替代规格
SPECS: dict[str, FontSpec] = {}

#: 源字体名（小写）→ 替代是否与源字体同源。
#:
#: **同一个替代规格可能既服务同源字体、又服务非同源字体** ——
#: 思源黑体 CN ≡ Noto Sans SC 是同源的（字形完全一致），
#: 而阿里巴巴普惠体 → Noto Sans SC 只是"能显示"（字形、字宽、标点宽度
#: 全都不一样）。所以这个标记必须按**源字体名**记，不能挂在规格上。
SAME_ORIGIN_OVERRIDES: dict[str, bool] = {}


def _reg(
    names: tuple[str, ...], spec: FontSpec, same_origin: Optional[bool] = None
) -> None:
    for n in names:
        key = n.lower()
        SPECS[key] = spec
        if same_origin is not None:
            SAME_ORIGIN_OVERRIDES[key] = same_origin


_reg(("calibri", "calibri light", "calibri thin"), _CARLITO)
_reg(("arial", "arial narrow", "helvetica", "helvetica neue"), _ARIMO)
_reg(("monoton",), _MONOTON)
_reg(
    (
        # 这些**都不是** Noto Sans SC 的同源字体，只是"能显示中文"而已：
        # 微软雅黑、阿里巴巴普惠体和 Noto Sans SC 的字形/字宽都不一样，
        # 替代之后断行和行高都会漂。
        "微软雅黑",
        "microsoft yahei",
        "microsoft yahei ui",
        "等线",
        "等线 light",
        "dengxian",
        "dengxian light",
        "黑体",
        "simhei",
        "方正黑体",
        # 阿里巴巴普惠体（阿里免费商用字体）—— 无开源同源品，用 Noto Sans SC 兜
        "阿里巴巴普惠体",
        "alibaba puhuiti",
        "alibaba puhuiti 2.0",
    ),
    _NOTO_SANS_SC,
    same_origin=False,
)
_reg(
    (
        # 思源黑体 CN 的开源同源版本 —— 字形完全一致
        "思源黑体 cn",
        "source han sans cn",
        "思源黑体",
        "noto sans sc",
        "noto sans cjk sc",
    ),
    _NOTO_SANS_SC,
)
_reg(
    (
        # 思源宋体 CN 的开源同源版本 —— 字形完全一致
        "思源宋体 cn",
        "source han serif cn",
        "思源宋体",
        "noto serif sc",
        "noto serif cjk sc",
    ),
    _NOTO_SERIF_SC,
)
_reg(
    (
        # 宋体/楷体/仿宋 与 Noto Serif SC **不同源**（宋体的笔画风格完全不一样）
        "宋体",
        "simsun",
        "新宋体",
        "nsimsun",
        "仿宋",
        "fangsong",
        "楷体",
        "kaiti",
        "宋体 cn",
    ),
    _NOTO_SERIF_SC,
    same_origin=False,
)


@dataclass
class ResolvedFont:
    """一个源字体名的解析结果。"""

    name: str  # 原始 typeface
    base: str  # 去掉字重后缀的族名（小写）
    weight: int  # 建议字重
    spec: Optional[FontSpec]  # 命中的替代规格（None = 没有替代）
    #: 真身字体文件路径（用户在 fonts/local/ 放了原字体时才有）
    local_file: Optional[str] = None

    @property
    def family(self) -> Optional[str]:
        if self.local_file:
            return None  # 真身：由文件决定 family
        return self.spec.family if self.spec else None

    @property
    def exact(self) -> bool:
        """是否用真身（字形与原稿一致）。"""
        return self.local_file is not None

    @property
    def same_origin(self) -> bool:
        """替代字体和源字体是否同源（字形、字宽完全一致）。

        同源的替代（思源宋体 CN ≡ Noto Serif SC）排版结果和原稿一致；
        不同源的（阿里巴巴普惠体 → Noto Sans SC）字宽不同，断行和行高都会漂。
        """
        override = SAME_ORIGIN_OVERRIDES.get(self.base)
        if override is not None:
            return override
        return bool(self.spec and self.spec.same_origin)


def resolve(name: Optional[str], default_weight: int = 400) -> Optional[ResolvedFont]:
    """把一个 typeface 名字解析成替代规格 + 字重。

    名字里带的字重优先（``Heavy`` → 900），否则用规格的默认字重。
    """
    if not name:
        return None
    base, weight = split_variant(name)
    spec = SPECS.get(base.lower())
    if spec is None:
        # 退一步：名字整体（未拆变体）再试一次
        spec = SPECS.get(name.strip().lower())
    if weight is None:
        weight = spec.weight_default if spec else default_weight
    return ResolvedFont(
        name=name,
        base=base.lower(),
        weight=weight,
        spec=spec,
    )


# --------------------------------------------------------------------------
# 字符归属：中文走 ea 槽，西文走 latin 槽
# --------------------------------------------------------------------------

_EA_RANGES = (
    (0x2E80, 0x2EFF),  # 中日韩部首
    (0x3000, 0x303F),  # 中日韩符号和标点（，。！？…）
    (0x3040, 0x30FF),  # 假名
    (0x3100, 0x312F),  # 注音符号
    (0x3190, 0x319F),  # 康熙部首
    (0x31C0, 0x31EF),  # 中日韩笔画
    (0x3200, 0x32FF),  # 带圈中日韩字母
    (0x3400, 0x4DBF),  # 扩展 A
    (0x4E00, 0x9FFF),  # 基本区
    (0xF900, 0xFAFF),  # 兼容汉字
    (0xFE30, 0xFE4F),  # 中日韩兼容形式
    (0xFF00, 0xFF60),  # 全角形式
    (0xFFE0, 0xFFE6),  # 全角符号
    (0x1F200, 0x1F2FF),  # 带圈汉字（🈁…）
    (0x20000, 0x2FA1F),  # 扩展 B–F + 兼容补充
)


def is_east_asian(ch: str) -> bool:
    """这个字符在 PowerPoint 里走 ``a:ea``（中文字体）还是 ``a:latin``（西文字体）。

    PowerPoint 是**按字符**选字体的：一个 run 里中文用 ea 槽、西文用 latin 槽，
    两者常常不是同一个字体。所以渲染时必须逐字符判断，不能整个 run 用一个字体。
    """
    code = ord(ch)
    for lo, hi in _EA_RANGES:
        if lo <= code <= hi:
            return True
    return False


def split_by_script(text: str) -> list[tuple[str, bool]]:
    """把文本切成 ``[(片段, 是否东亚字符), ...]``，连续同类合并。"""
    if not text:
        return []
    segments: list[tuple[str, bool]] = []
    current = text[0]
    current_ea = is_east_asian(text[0])
    for ch in text[1:]:
        ea = is_east_asian(ch)
        if ea == current_ea:
            current += ch
        else:
            segments.append((current, current_ea))
            current = ch
            current_ea = ea
    segments.append((current, current_ea))
    return segments
