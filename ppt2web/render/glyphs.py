"""字形轮廓与度量（fontTools）。

矢量模式的核心：把 PPT 里的文字变成字形轮廓，顺便拿到排版需要的度量：

* 字形轮廓 → SVG path（fontTools 的 SVGPathPen）
* advance width → 自己算换行和字距（浏览器排版永远和 PowerPoint 有偏差）
* 变量字体实例化 → ``思源宋体 CN Heavy`` 取 wght=900 的那一份字形

fontsource 的中文可变字体是按 unicode-range 切片的，所以"某个字符用哪份
字体文件"要靠分片的 unicode-range 找 —— 和 HTML 模式的子集化是同一套逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..fontfiles import FontDescriptor, FontLibrary, system_font
from ..fontmap import FontSpec, ResolvedFont, resolve

#: 1pt = 12700 EMU
EMU_PER_PT = 12700.0


class FontToolsMissing(RuntimeError):
    """fontTools 没装。"""


def _require_fonttools():
    try:
        import fontTools  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 环境问题
        raise FontToolsMissing(
            "矢量模式需要 fontTools：pip install fonttools（产品物本身仍然零依赖）"
        ) from exc
    return fontTools


@dataclass
class Glyph:
    """一个字形在文本行里的位置与轮廓来源。"""

    char: str
    face: "Face"
    glyph_name: str
    advance: float  # 字体单位


class Face:
    """一个已加载的字体文件（变量字体已按字重实例化）。"""

    def __init__(self, path: Path, weight: Optional[int] = None, font_number: int = 0):
        _require_fonttools()
        from fontTools.ttLib import TTFont

        self.path = path
        self.weight = weight
        self.font = TTFont(str(path), fontNumber=font_number, lazy=True)
        if weight is not None and "fvar" in self.font:
            from fontTools.varLib import instancer

            self.font = instancer.instantiateVariableFont(
                self.font, {"wght": weight}, inplace=True
            )
        self.upem = int(self.font["head"].unitsPerEm)
        self.cmap = self.font.getBestCmap() or {}
        self.glyph_set = self.font.getGlyphSet()
        self.hmtx = self.font["hmtx"] if "hmtx" in self.font else None
        self.ascent, self.descent = self._vertical_metrics()

    def _vertical_metrics(self) -> tuple[float, float]:
        try:
            hhea = self.font["hhea"]
            return float(hhea.ascent), float(hhea.descent)
        except (KeyError, AttributeError):
            return float(self.upem) * 0.8, float(self.upem) * 0.2

    def glyph_name(self, ch: str) -> Optional[str]:
        return self.cmap.get(ord(ch))

    def advance(self, glyph_name: str) -> float:
        if self.hmtx is None:
            return float(self.upem) * 0.5
        try:
            return float(self.hmtx[glyph_name][0])
        except KeyError:
            return float(self.upem) * 0.5

    def draw(self, glyph_name: str, pen) -> None:
        """把字形画到 pen（调用方负责变换）。"""
        glyph = self.glyph_set[glyph_name]
        glyph.draw(pen)

    def close(self) -> None:
        try:
            self.font.close()
        except Exception:  # pragma: no cover
            pass


class Family:
    """一个源字体名对应的字体集合。

    * 真身（用户放在 fonts/local/ 的字体）：单个 Face，覆盖所有字符
    * 替代字体（fontsource 分片）：(分片描述, Face) 列表，按 unicode-range 挑

    真身常常缺西文或符号字形。这时**逐字符**回落到 ``fallback``（替代字体）
    —— 而不是让整个形状退回 HTML 文字（那样版式就变了，16 页的正文会集体塌）。
    """

    def __init__(
        self,
        source_name: str,
        pairs: Optional[list[tuple[FontDescriptor, object]]] = None,
        faces: Optional[list[Face]] = None,
        fallback: Optional["Family"] = None,
        loader=None,
    ):
        self.source_name = source_name
        #: (分片描述, 字体文件) —— **文件是懒加载的**：
        #: 一个中文字体有上百个分片，全加载要十几秒，而一份稿子只会用到一两个。
        self.pairs = pairs or []
        self.faces = faces or []
        #: 真身缺字形时的兜底族
        self.fallback = fallback
        self._loader = loader
        self._loaded: dict[int, object] = {}

    def _face_at(self, index: int) -> Optional[Face]:
        """取第 index 个分片的字体文件（懒加载）。"""
        source = self.pairs[index][1]
        if isinstance(source, Face):
            return source
        if index in self._loaded:
            return self._loaded[index]
        if self._loader is None:
            return None
        face = self._loader(source)
        self._loaded[index] = face
        return face

    def primary_face(self) -> Optional[Face]:
        """度量用的主字体文件。"""
        if self.faces:
            return self.faces[0]
        if self.pairs:
            return self._face_at(0)
        return None

    def face_for(self, ch: str) -> Optional[Face]:
        """找能画出这个字符的字体（先按分片的 unicode-range，再兜底）。"""
        code = ord(ch)
        for index, (desc, _source) in enumerate(self.pairs):
            if not desc.covers(code):
                continue
            face = self._face_at(index)
            if face is not None and face.glyph_name(ch):
                return face
        for face in self.faces:
            if face.glyph_name(ch):
                return face
        if self.fallback is not None:
            return self.fallback.face_for(ch)
        return None

    def metrics(self) -> tuple[float, float]:
        """(ascent, descent)，单位是字体单位。"""
        face = self.primary_face()
        if face is not None:
            return face.ascent, face.descent
        return 800.0, 200.0


def _fallback_spec() -> FontSpec:
    """没有替代字体时的兜底族（Noto Sans SC）。"""
    from ..fontmap import SPECS

    for spec in SPECS.values():
        if spec.key == "Noto Sans SC":
            return spec
    raise RuntimeError("兜底字体缺失")


class GlyphProvider:
    """按源字体名提供 :class:`Family`（带缓存）。"""
    def __init__(self, library: Optional[FontLibrary] = None):
        self.library = library or FontLibrary()
        self._cache: dict[tuple[str, int], Family] = {}
        self._loaded: dict[tuple[str, str], Face] = {}

    def family(self, source_name: Optional[str]) -> Optional[Family]:
        if not source_name:
            return None
        info: ResolvedFont = resolve(source_name)
        cache_key = (source_name, info.weight)
        if cache_key in self._cache:
            return self._cache[cache_key]

        family = self._build(source_name, info)
        self._cache[cache_key] = family
        return family

    def _build(self, source_name: str, info: ResolvedFont) -> Family:
        # 1. 真身优先
        local = self.library.local_font(source_name)
        if local is not None:
            face = self._load_face(local, info.weight)
            # 真身缺字形时逐字符回落到替代字体（见 Family.fallback）
            fallback = self._build_substitute(source_name, info)
            return Family(source_name, faces=[face], fallback=fallback)

        return self._build_substitute(source_name, info)

    def _build_substitute(self, source_name: str, info: ResolvedFont) -> Family:
        """替代字体：项目内置的分片 → 系统同族字体 → 兜底族。"""
        spec = info.spec
        if spec is None:
            # 没有替代字体（演示夏行楷这类商用字体）→ 用兜底族渲染，
            # 宁可用替代字形，也不要让这块文字退回 HTML（版式会变）。
            spec = _fallback_spec()
            info.spec = spec

        pairs: list[tuple[FontDescriptor, object]] = []
        for desc in self.library.family(spec.key):
            path = self.library.file_path(spec.key, desc)
            if not path.exists():
                continue
            pairs.append((desc, path))
        if pairs:
            return Family(
                source_name,
                pairs=pairs,
                loader=lambda p: self._load_face(p, info.weight, spec.key),
            )

        # 2. 项目里没有这个族 → 找系统里的同族字体
        system = system_font(spec.family)
        if system is not None:
            path, index = system
            face = self._load_face(path, info.weight, index=index)
            return Family(source_name, faces=[face])
        return Family(source_name)

    def _load_face(
        self,
        path: Path,
        weight: Optional[int],
        key: str = "",
        index: int = 0,
    ) -> Face:
        cache_key = (str(path), f"{key}:{index}:{weight}")
        if cache_key not in self._loaded:
            self._loaded[cache_key] = Face(path, weight=weight, font_number=index)
        return self._loaded[cache_key]

    def close(self) -> None:
        for face in self._loaded.values():
            face.close()
