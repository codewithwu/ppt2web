"""渐变 → SVG ``<linearGradient>`` 定义。

DrawingML 的 ``a:gradFill`` 在 SVG 里没有一一对应的写法，要自己把色标和
角度翻译成 ``<linearGradient>`` 的坐标：

* ``a:lin@ang`` 单位是 1/60000 度，0 = 从左到右，顺时针为正
* SVG 的渐变方向用 ``(x1,y1)→(x2,y2)`` 表示，y 向下（和 DrawingML 一致）
* ``a:path``（径向/焦点矩形）在 SVG 里没有对应写法，用以焦点为中心的
  ``<radialGradient>`` 近似

渐变 id 必须**一页之内唯一** —— 所以注册时带上形状 id 做前缀，
否则一页里两个形状的渐变会共用同一个 id，浏览器只认第一个。
"""

from __future__ import annotations

import math
from typing import Optional

from ..model import Gradient, Theme


class GradientRegistry:
    """收集渐变定义，返回 ``fill="url(#id)"``。"""

    def __init__(self, prefix: str = "g"):
        self.defs: list[str] = []
        self.prefix = prefix
        self._counter = 0

    def register(self, gradient: Gradient, theme: Theme) -> Optional[str]:
        if not gradient.stops:
            return None
        stops = []
        for stop in gradient.stops:
            color = stop.color.to_css(theme) if stop.color else "transparent"
            stops.append(f'<stop offset="{stop.position:.4f}" stop-color="{color}"/>')
        self._counter += 1
        gid = f"{self.prefix}{self._counter}"
        if gradient.kind in ("radial", "path"):
            # 径向/路径渐变：DrawingML 的 ``a:path`` 用 fillToRect 描述焦点矩形，
            # SVG 没有对应写法 —— 用以焦点为中心的径向渐变近似。
            cx, cy = gradient.center
            self.defs.append(
                f'<radialGradient id="{gid}" cx="{cx:.4f}" cy="{cy:.4f}" r="0.5" '
                f'fx="{cx:.4f}" fy="{cy:.4f}">{"".join(stops)}</radialGradient>'
            )
            return f"url(#{gid})"
        rad = math.radians(gradient.angle)
        dx = 0.5 * math.cos(rad)
        dy = 0.5 * math.sin(rad)
        self.defs.append(
            f'<linearGradient id="{gid}" x1="{0.5 - dx:.4f}" y1="{0.5 - dy:.4f}" '
            f'x2="{0.5 + dx:.4f}" y2="{0.5 + dy:.4f}">{"".join(stops)}</linearGradient>'
        )
        return f"url(#{gid})"
