"""2D 仿射变换。

OOXML 里一个形状从"自身局部坐标"到"幻灯片坐标"的映射由 xfrm 决定，
分组还要叠加父级的 chOff/chExt 映射。渲染时统一折叠成一个 CSS matrix()。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EMU_PER_PX = 9525.0


@dataclass(frozen=True)
class Affine:
    """[[a c e], [b d f], [0 0 1]] —— 与 SVG/CSS matrix(a,b,c,d,e,f) 同序。"""

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def multiply(self, other: "Affine") -> "Affine":
        """self ∘ other —— 先应用 other，再应用 self。"""
        return Affine(
            a=self.a * other.a + self.c * other.b,
            b=self.b * other.a + self.d * other.b,
            c=self.a * other.c + self.c * other.d,
            d=self.b * other.c + self.d * other.d,
            e=self.a * other.e + self.c * other.f + self.e,
            f=self.b * other.e + self.d * other.f + self.f,
        )

    def translate(self, tx: float, ty: float) -> "Affine":
        return Affine(self.a, self.b, self.c, self.d, self.e + tx, self.f + ty)

    def scale(self, sx: float, sy: float) -> "Affine":
        return Affine(self.a * sx, self.b * sx, self.c * sy, self.d * sy, self.e, self.f)

    def rotate(self, degrees: float) -> "Affine":
        rad = math.radians(degrees)
        cos, sin = math.cos(rad), math.sin(rad)
        return Affine(
            a=self.a * cos + self.c * sin,
            b=self.b * cos + self.d * sin,
            c=self.a * -sin + self.c * cos,
            d=self.b * -sin + self.d * cos,
            e=self.e,
            f=self.f,
        )

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def to_css(self) -> str:
        return f"matrix({self.a:.6f},{self.b:.6f},{self.c:.6f},{self.d:.6f},{self.e:.2f},{self.f:.2f})"

    def to_css_px(self, emu_per_px: float = EMU_PER_PX) -> str:
        """CSS matrix：线性部分无量纲，平移量从 EMU 换算成 px。"""
        return (
            f"matrix({self.a:.6f},{self.b:.6f},{self.c:.6f},{self.d:.6f},"
            f"{self.e / emu_per_px:.2f},{self.f / emu_per_px:.2f})"
        )

    @property
    def is_identity(self) -> bool:
        return (
            abs(self.a - 1) < 1e-9
            and abs(self.b) < 1e-9
            and abs(self.c) < 1e-9
            and abs(self.d - 1) < 1e-9
            and abs(self.e) < 1e-9
            and abs(self.f) < 1e-9
        )


def emu_to_px(emu: float) -> float:
    return emu / EMU_PER_PX


def px_to_emu(px: float) -> int:
    return int(round(px * EMU_PER_PX))
