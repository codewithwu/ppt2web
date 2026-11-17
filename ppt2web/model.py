"""中间数据模型。

解析器把 .pptx 的 OOXML 折叠成这些结构，渲染器只认这些结构。
凡是"继承"（slide → layout → master → theme）在解析阶段就压平，
渲染器不需要知道 OOXML 的继承链。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .affine import Affine


@dataclass
class Color:
    """颜色。rgb 为 None 时用 theme（主题色槽名）+ tint/shade/alpha 描述。"""

    rgb: Optional[str] = None
    theme: Optional[str] = None
    tint: Optional[float] = None
    shade: Optional[float] = None
    alpha: Optional[float] = None
    lum_mod: Optional[float] = None
    lum_off: Optional[float] = None

    def to_css(self, theme: "Theme") -> str:
        base = self.rgb
        if base is None and self.theme:
            base = theme.color(self.theme)
        if base is None:
            return "transparent"
        r, g, b = _hex_to_rgb(base)
        if self.tint:
            r, g, b = _apply_tint(r, g, b, self.tint)
        if self.shade:
            r, g, b = _apply_shade(r, g, b, self.shade)
        if self.lum_mod is not None or self.lum_off is not None:
            r, g, b = _apply_lum(r, g, b, self.lum_mod, self.lum_off)
        alpha = 1.0 if self.alpha is None else self.alpha
        if alpha >= 1.0:
            return f"#{r:02X}{g:02X}{b:02X}"
        return f"rgba({r},{g},{b},{alpha:.4f})"


@dataclass
class GradientStop:
    position: float = 0.0
    color: Color = field(default_factory=Color)


@dataclass
class Gradient:
    kind: str = "linear"  # linear | radial | path
    angle: float = 90.0  # 线性渐变角度（度，0 = 从左到右）
    center: tuple[float, float] = (0.5, 0.5)  # 径向渐变焦点（占形状比例）
    stops: list[GradientStop] = field(default_factory=list)
    rotate_with_shape: bool = True


@dataclass
class Fill:
    kind: str = "none"  # none | solid | gradient | pattern | blip | group
    color: Optional[Color] = None
    gradient: Optional[Gradient] = None
    pattern: Optional[dict[str, Any]] = None
    blip: Optional["Picture"] = None
    alpha: Optional[float] = None
    #: 图片填充时，图片覆盖的区域相对形状的比例内缩/外扩
    #: （``a:fillRect`` 的 l/t/r/b，1/100000 → 比例；负值 = 出血）
    blip_rect: Optional[tuple[float, float, float, float]] = None


@dataclass
class Line:
    color: Optional[Color] = None
    width_emu: int = 0
    dash: Optional[str] = None
    cap: Optional[str] = None
    join: Optional[str] = None


@dataclass
class Picture:
    """图片资源。blob 为原始字节，产物里字节级原样落盘。"""

    part_name: str
    ext: str
    blob: bytes
    sha256: str
    crop: Optional[dict[str, float]] = None  # {"l":..,"t":..,"r":..,"b":..} 比例
    src_rect_emu: Optional[tuple[int, int, int, int]] = None


@dataclass
class Run:
    text: str
    font: Optional[str] = None  # latin typeface
    east_asian_font: Optional[str] = None
    size_pt: Optional[float] = None
    bold: bool = False
    italic: bool = False
    underline: Optional[str] = None  # sng | dbl | none
    strike: Optional[str] = None
    color: Optional[Color] = None
    fill: Optional[Fill] = None  # run 级渐变/图案文字填充
    baseline: Optional[int] = None  # 上下标：30000=上标 -25000=下标
    spacing_pt: Optional[float] = None
    caps: Optional[str] = None


@dataclass
class Paragraph:
    runs: list[Run] = field(default_factory=list)
    level: int = 0
    align: Optional[str] = None  # l | ctr | r | just | dist
    line_spacing: Optional[float] = None  # 倍数
    line_spacing_pt: Optional[float] = None
    space_before_pt: Optional[float] = None
    space_after_pt: Optional[float] = None
    bullet: Optional[str] = None  # 字符本身
    bullet_type: Optional[str] = None  # char | autoNum | none | picture
    bullet_color: Optional[Color] = None
    bullet_size_pct: Optional[float] = None
    indent_emu: Optional[int] = None
    margin_left_emu: Optional[int] = None
    hanging_emu: Optional[int] = None
    default_run_props: dict[str, Any] = field(default_factory=dict)


@dataclass
class TextFrame:
    paragraphs: list[Paragraph] = field(default_factory=list)
    anchor: Optional[str] = None  # t | ctr | b | just
    wrap: Optional[str] = None  # square | none
    autofit: Optional[str] = None  # none | norm | shape
    autofit_font_scale: Optional[float] = None
    autofit_line_spacing_reduction: Optional[float] = None
    margins_emu: tuple[int, int, int, int] = (91440, 91440, 91440, 91440)  # l,t,r,b
    vertical: Optional[str] = None  # horz | vert | vert270
    columns: int = 1


@dataclass
class ChartPoint:
    """一个数据点的单独格式（``c:dPt``）。"""

    idx: int
    fill: Optional[Fill] = None
    line: Optional[Line] = None


@dataclass
class ChartSeries:
    """一个系列（``c:ser``）。"""

    name: Optional[str] = None
    values: list[float] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    fill: Optional[Fill] = None
    line: Optional[Line] = None
    points: list[ChartPoint] = field(default_factory=list)


@dataclass
class ChartAxis:
    """一根坐标轴（``c:catAx`` / ``c:valAx``）。"""

    kind: str = "cat"  # cat | val
    position: str = "b"  # b | l | r | t
    deleted: bool = False
    num_fmt: str = "General"
    major_unit: Optional[float] = None
    label_rotation: float = 0.0  # 度（DrawingML 角度，顺时针为正）
    label_size_pt: Optional[float] = None
    label_color: Optional[Color] = None
    label_font: Optional[str] = None
    label_ea_font: Optional[str] = None
    gridlines: Optional[Line] = None
    line: Optional[Line] = None
    major_tick_mark: str = "none"
    tick_label_pos: str = "nextTo"


@dataclass
class ChartLabels:
    """数据标签（``c:dLbls``）。"""

    show_value: bool = False
    show_category: bool = False
    show_series: bool = False
    show_percent: bool = False
    size_pt: Optional[float] = None
    color: Optional[Color] = None
    font: Optional[str] = None
    ea_font: Optional[str] = None
    leader_line: Optional[Line] = None


@dataclass
class Chart:
    """一张图表（``ppt/charts/chartN.xml``）。

    只覆盖这份稿子用到的类型；遇到不认识的就记进 ``unsupported``，
    由 verify 降级成警告，而不是画个错的。
    """

    kind: str = "bar"  # bar | doughnut | pie
    bar_dir: str = "col"  # col | bar
    grouping: str = "clustered"
    hole_size: int = 50  # 甜甜圈的内径百分比
    first_slice_angle: float = 0.0  # 起始角（度，12 点方向为 0，顺时针）
    vary_colors: bool = False
    gap_width: int = 150
    overlap: Optional[int] = None
    categories: list[str] = field(default_factory=list)
    series: list[ChartSeries] = field(default_factory=list)
    axes: list[ChartAxis] = field(default_factory=list)
    labels: Optional[ChartLabels] = None
    #: 解析过程中的说明（"类别名来自 c15 扩展"之类）
    notes: list[str] = field(default_factory=list)
    #: 绘图区手工布局 (x, y, w, h)，比例 0~1；没有就是自动
    layout: Optional[tuple[float, float, float, float]] = None
    legend: bool = False
    title: Optional[str] = None
    #: 图表自己的主题（``c:themeOverride``）—— 甜甜圈的配色靠它
    theme: Optional["Theme"] = None
    #: 主题配色循环（``ppt/charts/colorsN.xml``）的色槽名
    color_cycle: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


@dataclass
class TableCell:
    """一个单元格。"""

    text: Optional[TextFrame] = None
    fill: Optional[Fill] = None
    margin_left_emu: int = 91440
    margin_right_emu: int = 91440
    margin_top_emu: int = 45720
    margin_bottom_emu: int = 45720
    anchor: str = "t"
    grid_span: int = 1
    v_merge: Optional[str] = None


@dataclass
class TableRow:
    height_emu: int = 0
    cells: list[TableCell] = field(default_factory=list)


@dataclass
class TableStyle:
    """表格样式（``ppt/tableStyles.xml`` 里的一个 ``a:tblStyle``）。

    边框往往**不在 cell 上**而在样式里 —— 不读它，表格就没有内线。
    """

    name: Optional[str] = None
    #: wholeTbl 的边框：left/right/top/bottom/insideH/insideV
    borders: dict[str, Optional[Line]] = field(default_factory=dict)
    #: wholeTbl 的填充（cell 自己的填充会覆盖它）
    fill: Optional[Fill] = None
    #: firstRow 的额外边框（键同 wholeTbl）
    first_row_borders: dict[str, Optional[Line]] = field(default_factory=dict)
    #: firstRow 的文字色（None = 不改）
    first_row_color: Optional[Color] = None
    first_row_bold: bool = False
    first_row_fill: Optional[Fill] = None
    #: 隔行底色（band1H）
    band_fill: Optional[Fill] = None


@dataclass
class Table:
    """一张表格（``a:tbl``）。"""

    columns: list[int] = field(default_factory=list)  # 每列宽 EMU
    rows: list[TableRow] = field(default_factory=list)
    first_row: bool = False
    band_row: bool = False
    style: Optional[TableStyle] = None
    unsupported: list[str] = field(default_factory=list)


@dataclass
class Shape:
    """一个可渲染的图元。

    transform 是折叠到幻灯片绝对坐标的矩阵（便于校验）；
    local_transform 是相对父容器（分组的 div 局部空间）的矩阵（渲染时用）。
    分组保留成嵌套结构 —— 因为 PowerPoint 允许直接给"组"加动画，
    展平会让动画目标消失。
    """

    shape_id: str
    name: str
    kind: str  # shape | picture | textbox | table | chart | group | connector | media
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    transform: Optional[Affine] = None  # 绝对（幻灯片坐标）
    local_transform: Optional[Affine] = None  # 相对父容器
    geom: Optional[str] = None  # prstGeom 的 prst 值
    geom_path: Optional[str] = None  # custGeom 的 path d
    adj: dict[str, Any] = field(default_factory=dict)
    fill: Fill = field(default_factory=Fill)
    line: Optional[Line] = None
    text: Optional[TextFrame] = None
    picture: Optional[Picture] = None
    chart: Optional[Chart] = None
    table: Optional[Table] = None
    rotation: float = 0.0
    flip_h: bool = False
    flip_v: bool = False
    opacity: float = 1.0
    shadow: Optional[dict[str, Any]] = None
    #: 形状上挂着的音频/视频（包内路径）—— ``a:audioFile`` / ``a:videoFile``
    audio_part: Optional[str] = None
    placeholder: Optional[dict[str, Any]] = None
    z: int = 0
    notes: list[str] = field(default_factory=list)
    children: list["Shape"] = field(default_factory=list)
    ch_off: tuple[float, float] = (0.0, 0.0)  # 分组的子坐标空间原点


@dataclass
class Behavior:
    """一个动画行为（OOXML p:anim 家族的一个节点）。"""

    type: str  # anim | animRot | animScale | animClr | animMotion | set | cmd
    attr_name: str
    target_id: Optional[str]
    duration_ms: int = 0
    delay_ms: int = 0
    keyframes: list[dict[str, Any]] = field(default_factory=list)
    formula: Optional[str] = None
    preset_id: Optional[str] = None
    preset_class: Optional[str] = None
    calc_mode: str = "lin"
    #: animEffect 的滤镜名（wipe(left) / circle(in) / fade …）—— 渲染效果的真正依据
    filter_name: Optional[str] = None
    #: animEffect 的方向（in / out）
    transition: Optional[str] = None
    #: 命令型行为（``p:cmd``）的命令，如 ``playFrom(0.0)``
    command: Optional[str] = None
    #: 命令型行为要播放的媒体（包内路径）
    media: Optional[str] = None
    notes: list[str] = field(default_factory=list)


@dataclass
class AnimationGroup:
    """一次点击/自动推进的单元。"""

    trigger: str = "auto"  # auto | click | interactive
    start_delay_ms: int = 0
    behaviors: list[Behavior] = field(default_factory=list)
    target_ids: list[str] = field(default_factory=list)


@dataclass
class Timeline:
    groups: list[AnimationGroup] = field(default_factory=list)
    has_timing: bool = False
    main_seq_duration: Optional[int] = None


@dataclass
class Transition:
    kind: Optional[str] = None  # fade | wipe | push | cover | cut | morph ...
    duration_ms: int = 0
    speed: Optional[str] = None
    advance_on_click: bool = True
    #: 方向（wipe/push/cover 的 dir，flythrough 的方向）
    direction: Optional[str] = None
    #: 自动翻页时间（``advTm``，毫秒）—— 0 = 不自动翻
    advance_ms: int = 0
    #: 老版本的退化转场（``mc:Fallback`` 里的那个）—— p14 的 3D 转场
    #: 在不支持 p14 的阅读器里就退化成它
    fallback_kind: Optional[str] = None


@dataclass
class Slide:
    index: int
    layout_name: str = ""
    shapes: list[Shape] = field(default_factory=list)
    timeline: Timeline = field(default_factory=Timeline)
    transition: Transition = field(default_factory=Transition)
    notes_text: str = ""
    #: 这一页挂着的音频/视频素材
    audio: list["AudioClip"] = field(default_factory=list)
    background_fill: Optional[Fill] = None
    follow_master_background: bool = True
    theme: Optional["Theme"] = None


@dataclass
class Theme:
    name: str = ""
    colors: dict[str, str] = field(default_factory=dict)
    major_latin: Optional[str] = None
    major_ea: Optional[str] = None
    minor_latin: Optional[str] = None
    minor_ea: Optional[str] = None

    def color(self, slot: str) -> Optional[str]:
        return self.colors.get(slot)

    def font_for(self, name: Optional[str], is_heading: bool) -> Optional[str]:
        """把主题字体槽（major/minor）解析成具体字体名。"""
        if not name:
            return None
        if name in ("+mj-lt", "+mj-ea", "+mj-cs"):
            return self.major_ea if name.endswith("ea") else self.major_latin
        if name in ("+mn-lt", "+mn-ea", "+mn-cs"):
            return self.minor_ea if name.endswith("ea") else self.minor_latin
        return name


@dataclass
class AudioClip:
    """音频/视频素材（``p:audio`` / ``a:audioFile``）。

    目前只解析、不播放 —— 但**必须解析**：不解析的话这份媒体在产物里
    就彻底消失了，而且没有任何地方会提醒（``verify`` 只校验"产物里有的
    媒体"，源里多出来的媒体对它是隐形的）。
    """

    part_name: str = ""
    ext: str = ""
    blob: bytes = b""
    sha256: str = ""
    target_id: str = ""  # 挂在哪个形状上
    volume: int = 100000  # 0~100000
    loop: bool = False
    kind: str = "audio"  # audio | video


@dataclass
class Deck:
    slide_width_emu: int = 9144000
    slide_height_emu: int = 6858000
    slides: list[Slide] = field(default_factory=list)
    themes: dict[str, Theme] = field(default_factory=dict)
    fonts_used: list[str] = field(default_factory=list)
    media: list[Picture] = field(default_factory=list)
    audio: list[AudioClip] = field(default_factory=list)
    title: str = ""
    author: str = ""

    @property
    def slide_width_px(self) -> float:
        return self.slide_width_emu / 9525.0

    @property
    def slide_height_px(self) -> float:
        return self.slide_height_emu / 9525.0


# --------------------------------------------------------------------------
# 颜色工具
# --------------------------------------------------------------------------


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return f"{int(round(r)):02X}{int(round(g)):02X}{int(round(b)):02X}"


def _apply_tint(r: int, g: int, b: int, tint: float) -> tuple[int, int, int]:
    """ECMA-376 tint：向白色插值。tint=1 全白，tint=0 不变。"""
    r = r + (255 - r) * tint
    g = g + (255 - g) * tint
    b = b + (255 - b) * tint
    return int(round(r)), int(round(g)), int(round(b))


def _apply_shade(r: int, g: int, b: int, shade: float) -> tuple[int, int, int]:
    """shade=1 不变，shade=0 全黑。"""
    return int(round(r * shade)), int(round(g * shade)), int(round(b * shade))


def _apply_lum(
    r: int, g: int, b: int, lum_mod: Optional[float], lum_off: Optional[float]
) -> tuple[int, int, int]:
    """亮度调制（HSL 空间）。"""
    h, l, s = _rgb_to_hsl(r, g, b)
    if lum_mod is not None:
        l *= lum_mod
    if lum_off is not None:
        l += lum_off
    l = max(0.0, min(1.0, l))
    r, g, b = _hsl_to_rgb(h, l, s)
    return int(round(r)), int(round(g)), int(round(b))


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    rf, gf, bf = r / 255, g / 255, b / 255
    mx, mn = max(rf, gf, bf), min(rf, gf, bf)
    l = (mx + mn) / 2
    if mx == mn:
        return 0.0, l, 0.0
    d = mx - mn
    s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == rf:
        h = ((gf - bf) / d) % 6
    elif mx == gf:
        h = (bf - rf) / d + 2
    else:
        h = (rf - gf) / d + 4
    return h / 6, l, s


def _hsl_to_rgb(h: float, l: float, s: float) -> tuple[float, float, float]:
    if s == 0:
        return l * 255, l * 255, l * 255
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    hk = h * 6
    return (
        _hue_to_rgb(p, q, hk % 6) * 255,
        _hue_to_rgb(p, q, (hk - 1) % 6) * 255,
        _hue_to_rgb(p, q, (hk - 2) % 6) * 255,
    )


def _hue_to_rgb(p: float, q: float, t: float) -> float:
    if t < 1:
        return p + (q - p) * t
    if t < 2:
        return q
    if t < 3:
        return p + (q - p) * (3 - t)
    if t < 4:
        return p
    if t < 5:
        return p + (q - p) * (t - 4)
    return q
