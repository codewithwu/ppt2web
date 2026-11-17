"""排版引擎：自己算换行、行高、字距，把文字摆成精确坐标。

为什么要自己排：浏览器排版和 PowerPoint 一定有偏差（字体不同、行高规则
不同、标点禁则不同），第 2 页那种"文字溢出压住下一行标题"就是这么来的。
自己排版才能做到"和原稿一样"。

坐标系：EMU（和形状的 viewBox 一致，px↔EMU 换算交给 SVG）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..fontmap import is_east_asian
from ..model import Gradient, Paragraph, Run, TextFrame
from .glyphs import EMU_PER_PT, Family, GlyphProvider

#: 行首禁则：这些字符不能出现在行首（要挤回上一行）
NO_LINE_START = set("，。、！？：；）〕］｝〉》」』】…‰′″℃%·—～")
#: 行尾禁则：这些字符不能出现在行尾
NO_LINE_END = set("（〔［｛〈《「『【‘“")

#: 没有字体时的兜底宽度（相对字号）
_FALLBACK_CJK = 1.0
_FALLBACK_LATIN = 0.5


@dataclass
class PlacedGlyph:
    """一个已定位的字形。"""

    ch: str
    face: object  # Face
    glyph_name: str
    x: float  # EMU
    width: float  # EMU
    size_pt: float = 18.0
    color: Optional[str] = None
    #: 文字本身的渐变填充（``a:rPr/a:gradFill``）—— 封面标题那种描边渐变
    gradient: Optional[Gradient] = None


@dataclass
class StyledRun:
    """一个 run 的排版样式。"""

    run: Run
    size_pt: float
    color: Optional[str] = None
    family_latin: Optional[Family] = None
    family_ea: Optional[Family] = None
    letter_spacing_emu: float = 0.0
    gradient: Optional[Gradient] = None


@dataclass
class Line:
    """一行。"""

    glyphs: list[PlacedGlyph] = field(default_factory=list)
    x: float = 0.0  # 行首 x（EMU，相对文本框）
    width: float = 0.0
    baseline: float = 0.0  # 基线 y（EMU，相对文本框）
    height: float = 0.0


@dataclass
class ParagraphLayout:
    lines: list[Line] = field(default_factory=list)
    height: float = 0.0
    bullet: Optional[str] = None
    bullet_x: float = 0.0
    bullet_width: float = 0.0


class TextLayout:
    """把一个 TextFrame 排成若干行（坐标相对文本框左上角，EMU）。"""

    def __init__(self, provider: GlyphProvider, theme=None):
        self.provider = provider
        self.theme = theme

    # -- 字符宽度 --------------------------------------------------------
    def _char_width(self, ch: str, styled: StyledRun) -> tuple[float, object, Optional[str]]:
        """返回 (宽度 EMU, Face, 字形名)。"""
        family = styled.family_ea if is_east_asian(ch) else styled.family_latin
        if family is None:
            size = styled.size_pt or 18.0
            ratio = _FALLBACK_CJK if is_east_asian(ch) else _FALLBACK_LATIN
            return size * EMU_PER_PT * ratio, None, None
        face = family.face_for(ch)
        if face is None:
            size = styled.size_pt or 18.0
            ratio = _FALLBACK_CJK if is_east_asian(ch) else _FALLBACK_LATIN
            return size * EMU_PER_PT * ratio, None, None
        glyph_name = face.glyph_name(ch)
        advance = face.advance(glyph_name)
        size = styled.size_pt or 18.0
        width = advance / face.upem * size * EMU_PER_PT
        return width, face, glyph_name

    # -- 段落排版 --------------------------------------------------------
    def layout_paragraph(
        self,
        para: Paragraph,
        box_width: float,
        left_inset: float,
        first: bool,
        wrap: bool = True,
    ) -> ParagraphLayout:
        out = ParagraphLayout()
        styled_runs: list[StyledRun] = []
        for run in para.runs:
            if not run.text:
                continue
            styled = StyledRun(
                run=run,
                size_pt=run.size_pt or 18.0,
                family_latin=self.provider.family(run.font),
                family_ea=self.provider.family(run.east_asian_font),
                letter_spacing_emu=(run.spacing_pt or 0.0) * EMU_PER_PT,
            )
            if run.color is not None and self.theme is not None:
                styled.color = run.color.to_css(self.theme)
            if run.fill is not None and run.fill.kind == "gradient":
                styled.gradient = run.fill.gradient
            styled_runs.append(styled)

        # 字符序列
        chars: list[tuple[str, StyledRun, float, object, Optional[str]]] = []
        for styled in styled_runs:
            for ch in styled.run.text:
                if ch == "\n":
                    chars.append(("\n", styled, 0.0, None, None))
                    continue
                width, face, gname = self._char_width(ch, styled)
                chars.append((ch, styled, width, face, gname))

        # 可用宽度与首行缩进
        # （坐标一律用形状坐标系：左内边距要算进去，不然整段文字偏左）
        margin_left = para.margin_left_emu or 0
        indent = para.indent_emu or 0
        left_edge = left_inset + margin_left  # 文字区左边界
        right_edge = left_inset + box_width  # 文字区右边界
        first_indent = left_edge + indent  # indent 只作用于本段的首行（OOXML 语义）
        # 首行（挂悬挂缩进时）可用宽度和其余行不同
        usable_first = max(right_edge - first_indent, 1.0)
        usable_rest = max(right_edge - left_edge, 1.0)

        # 断行
        segments = self._break_lines(chars, usable_first, usable_rest, wrap)

        # 行高
        line_height = self._line_height(para, styled_runs)
        size_pt = max((s.size_pt for s in styled_runs), default=18.0)
        ascent, descent = self._font_metrics(styled_runs, size_pt)
        baseline_offset = self._baseline_in_line(
            line_height, ascent, descent, exact=bool(para.line_spacing_pt)
        )

        y = 0.0
        if para.space_before_pt:
            y += para.space_before_pt * EMU_PER_PT

        for index, segment in enumerate(segments):
            is_first = index == 0
            start_x = first_indent if is_first else margin_left
            x = start_x
            line = Line(x=start_x, height=line_height)
            for ch, styled, width, face, gname in segment:
                if ch == "\n":
                    continue
                line.glyphs.append(
                    PlacedGlyph(
                        ch=ch,
                        face=face,
                        glyph_name=gname or "",
                        x=x,
                        width=width + styled.letter_spacing_emu,
                        size_pt=styled.size_pt,
                        color=styled.color,
                        gradient=styled.gradient,
                    )
                )
                x += width + styled.letter_spacing_emu
            line.width = x - start_x

            # 水平对齐：PowerPoint 的 algn（l / ctr / r / just / dist）
            align = para.align or "l"
            if align == "ctr":
                line.x = left_edge + (right_edge - left_edge - line.width) / 2
            elif align == "r":
                line.x = right_edge - line.width
            else:
                line.x = start_x
            if line.x != start_x:
                dx = line.x - start_x
                for glyph in line.glyphs:
                    glyph.x += dx

            line.baseline = y + baseline_offset
            out.lines.append(line)
            y += line_height

        if para.space_after_pt:
            y += para.space_after_pt * EMU_PER_PT
        out.height = y
        return out

    def _break_lines(
        self, chars, usable_first: float, usable_rest: float, wrap: bool = True
    ):
        """按宽度断行。

        先切"断行单元"：西文按词（词尾空格跟词一起）、汉字逐字、换行符独立。
        再贪心填行：装不下就换行；一个词本身比整行还宽时让它溢出（不切断单词）。
        最后套中文标点禁则。

        首行可用宽度和其余行可能不同（悬挂缩进），所以两个宽度都传进来。
        ``wrap=False``（PowerPoint 的 ``bodyPr wrap="none"``）时不自动换行，
        整段排成一行，让它横向溢出文本框。
        """
        if not chars:
            return [[]]
        segments = self._segments(chars)
        lines: list[list] = []
        current: list = []
        current_width = 0.0
        for segment in segments:
            if segment[0][0] == "\n":
                lines.append(current)
                current = []
                current_width = 0.0
                continue
            usable = usable_first if not lines else usable_rest
            seg_width = sum(item[2] for item in segment)
            if wrap and current and current_width + seg_width > usable:
                lines.append(current)
                current = []
                current_width = 0.0
            current.extend(segment)
            current_width += seg_width
        if current:
            lines.append(current)
        return self._apply_kinsoku(lines)

    @staticmethod
    def _segments(chars) -> list[list]:
        """切断行单元：西文按词，汉字逐字。"""
        segments: list[list] = []
        buffer: list = []
        for item in chars:
            ch = item[0]
            if ch == "\n":
                if buffer:
                    segments.append(buffer)
                    buffer = []
                segments.append([item])
                continue
            buffer.append(item)
            if ch == " " or is_east_asian(ch):
                # 空格之后 / 每个汉字，都是断行单元的边界
                segments.append(buffer)
                buffer = []
        if buffer:
            segments.append(buffer)
        return segments

    @staticmethod
    def _is_break_point(prev: str, ch: str) -> bool:
        """prev 和 ch 之间能不能断行。"""
        if not prev or not ch:
            return False
        if prev == " ":
            return True
        if is_east_asian(prev) and is_east_asian(ch):
            return True
        return False

    @staticmethod
    def _apply_kinsoku(lines: list[list]) -> list[list]:
        """中文标点禁则。

        * 行首禁则：行首不能是收尾标点 → 把这个标点**挂回上一行末尾**
          （中文排版的"标点悬挂"，上一行因此略微超宽）
        * 行尾禁则：行尾不能是开头标点 → 挪到下一行开头
        """
        result = [list(line) for line in lines]
        for i in range(len(result)):
            line = result[i]
            # 行尾禁则：末尾是开头标点 → 挪到下一行开头
            guard = 0
            while (
                line
                and line[-1][0] in NO_LINE_END
                and i + 1 < len(result)
                and guard < 8
            ):
                guard += 1
                moved = line.pop()
                result[i + 1].insert(0, moved)
            # 行首禁则：开头是收尾标点 → 挂回上一行末尾
            guard = 0
            while line and line[0][0] in NO_LINE_START and i > 0 and guard < 8:
                guard += 1
                moved = line.pop(0)
                result[i - 1].append(moved)
        # 去掉因禁则处理而变空的行
        return [line for line in result if line] or [[]]

    # -- 行高 ------------------------------------------------------------
    def _line_height(self, para: Paragraph, styled_runs: list[StyledRun]) -> float:
        """行高（EMU）。"""
        size_pt = max((s.size_pt for s in styled_runs), default=18.0)
        if para.line_spacing_pt:
            return para.line_spacing_pt * EMU_PER_PT
        single = self._single_line_height(styled_runs, size_pt)
        if para.line_spacing:
            return single * para.line_spacing
        return single

    def _font_metrics(self, styled_runs: list[StyledRun], size_pt: float) -> tuple[float, float]:
        """段落的字体度量：(ascent EMU, descent EMU)。

        descent 沿用字体自己的符号约定（hhea 是负数），
        所以"内容区高度 = ascent - descent"、"基线在 ascent 处"。

        取段落里第一个能用的字体（PowerPoint 也是按段落的基准字体排行）。
        """
        for styled in styled_runs:
            family = styled.family_ea or styled.family_latin
            if family is None:
                continue
            ascent, descent = family.metrics()
            face = family.primary_face()
            if face is None:
                continue
            scale = size_pt * EMU_PER_PT / face.upem
            return ascent * scale, descent * scale
        return size_pt * EMU_PER_PT * 0.8, size_pt * EMU_PER_PT * -0.2

    def _single_line_height(self, styled_runs: list[StyledRun], size_pt: float) -> float:
        """单倍行高：用字体的 ascent - descent（PowerPoint 的行距基准）。"""
        ascent, descent = self._font_metrics(styled_runs, size_pt)
        return ascent - descent

    def _baseline_in_line(
        self,
        line_height: float,
        ascent: float,
        descent: float,
        exact: bool,
    ) -> float:
        """基线在行盒里的位置（EMU，从行盒顶算）。

        这是 CSS 的"半行距"模型：行盒比字体的内容区高出来的部分，
        一半放在基线之上、一半放在之下。基线因此落在 ``ascent + 半行距``，
        而不是"行高 × ascent 比例"——后者会把行距重复算一遍，
        整段文字会整体下沉约半个行距，压到下一行/下一段上。

        固定行距（``spcPts``）没有半行距可言：PowerPoint 把文字的底部
        对齐到行盒底，基线 = 行高 + descent（descent 是负数）。
        """
        if exact:
            return max(line_height - abs(descent), 0.0)
        half_leading = (line_height - (ascent - descent)) / 2.0
        return half_leading + ascent
