"""入场效果滤镜（p:animEffect）的判定表。

PowerPoint 把入场效果写成 ``filter="wipe(left)"`` 这种精确描述，
presetID 只是 UI 标签。照着 filter 翻译成 clip-path / opacity 才是
逐帧一致的原生实现。

这里的判定表与 ``runtime/slide.js`` 里的 ``FILTERS`` 表一一对应
（verify 会交叉检查：稿子里用到的每个 filter 都必须在 JS 表里）。
"""

from __future__ import annotations

#: filter → (判定, 说明)
FILTER_JUDGEMENT: dict[str, tuple[str, str]] = {
    "fade": ("native", "透明度渐显"),
    "wipe(up)": ("native", "clip-path 自下而上擦除"),
    "wipe(down)": ("native", "clip-path 自上而下擦除"),
    "wipe(left)": ("native", "clip-path 自右向左擦除"),
    "wipe(right)": ("native", "clip-path 自左向右擦除"),
    "circle(in)": ("native", "clip-path 圆形由内向外扩张"),
    "circle(out)": ("native", "clip-path 圆形由外向内收缩"),
    "barn(inVertical)": ("native", "clip-path 多边形竖向对开"),
    "barn(inHorizontal)": ("native", "clip-path 多边形横向对开"),
    "dissolve": ("approx", "像素级溶解用透明度近似"),
    "randombar(horizontal)": ("approx", "随机条顺序用固定错位近似"),
    "randombar(vertical)": ("approx", "随机条顺序用固定错位近似"),
}


def judge_filter(name: str | None) -> tuple[str, str]:
    if not name:
        return "approx", "未指定滤镜，按位移近似"
    if name in FILTER_JUDGEMENT:
        return FILTER_JUDGEMENT[name]
    return "approx", f"未实现的滤镜 {name}，按位移近似"
