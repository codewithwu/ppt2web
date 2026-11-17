"""字体文件层：读项目里内置的字体（不依赖 npm，转换期完全离线）。

目录结构（由 ``tools/import_fonts.py`` 从 npm fontsource 包导入一次）::

    ppt2web/fonts/
      fonts.lock.json          # 来源、版本、sha256（可审计）
      noto-serif-sc/
        manifest.json          # 每个分片的 unicode-range / 字重 / 文件名
        noto-serif-sc-4-wght-normal.woff2
        ...
      local/                   # 用户自放的商用字体（真身优先）

fontsource 的中文可变字体按 unicode-range 切成了上百个分片，每个分片
自带 wght 轴（一份文件覆盖 100–900 全部字重）。所以"某个字符用哪份字体"
要靠分片的 unicode-range 来找 —— 这也是字体子集化的等效实现：只把用到的
分片拷进产物。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

#: 项目内置字体目录（可用 PPT2WEB_FONTS_DIR 覆盖，方便指向别处的字体库）
FONTS_DIR = Path(
    os.environ.get("PPT2WEB_FONTS_DIR")
    or (Path(__file__).resolve().parent / "fonts")
)
#: 用户自放字体目录（真身优先）
LOCAL_DIR = FONTS_DIR / "local"

_FACE_RE = re.compile(r"@font-face\s*\{([^}]*)\}", re.S)
_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")


@dataclass
class FontDescriptor:
    """一个 @font-face 分片。"""

    family: str  # 源 CSS 里的 family 名
    style: str
    weight: str  # 字重或字重区间（"400" / "100 900"）
    src: str  # 相对字体目录的文件名
    unicode_range: str
    fmt: str

    @property
    def weight_value(self) -> int:
        """字重区间的下限（用于匹配"这个 run 要哪个字重"）。"""
        head = self.weight.strip().split()
        try:
            return int(head[0])
        except (ValueError, IndexError):
            return 400

    def covers(self, code: int) -> bool:
        for lo, hi in parse_unicode_range(self.unicode_range):
            if lo <= code <= hi:
                return True
        return False


def parse_unicode_range(value: str) -> list[tuple[int, int]]:
    """解析 CSS unicode-range → [(lo, hi), ...]。"""
    ranges: list[tuple[int, int]] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if part.lower().startswith("u+"):
            part = part[2:]
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            try:
                ranges.append((int(lo_s, 16), int(hi_s, 16)))
            except ValueError:
                continue
        else:
            try:
                code = int(part, 16)
                ranges.append((code, code))
            except ValueError:
                continue
    return ranges


def parse_font_css(text: str) -> list[FontDescriptor]:
    """从 fontsource 的 CSS 里抽出 @font-face 描述。"""
    descriptors: list[FontDescriptor] = []
    for block in _FACE_RE.findall(text):
        family = _attr(block, "font-family")
        if not family:
            continue
        src_block = _attr(block, "src") or ""
        urls = _URL_RE.findall(src_block)
        woff2 = next((u for u in urls if u.endswith(".woff2")), None)
        if not woff2:
            continue
        descriptors.append(
            FontDescriptor(
                family=family.strip("'\" "),
                style=_attr(block, "font-style") or "normal",
                weight=_attr(block, "font-weight") or "400",
                src=woff2.lstrip("./"),
                unicode_range=_attr(block, "unicode-range") or "",
                fmt="woff2-variations" if "woff2-variations" in src_block else "woff2",
            )
        )
    return descriptors


def _attr(block: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}\s*:\s*([^;]+)", block)
    return match.group(1).strip() if match else ""


# --------------------------------------------------------------------------
# 读取项目内置字体
# --------------------------------------------------------------------------


class FontLibrary:
    """项目内置字体 + 用户自放字体的统一入口。"""

    def __init__(self, fonts_dir: Path | None = None):
        self.dir = Path(fonts_dir) if fonts_dir else FONTS_DIR
        self.local_dir = self.dir / "local"
        self._families: dict[str, list[FontDescriptor]] = {}
        self._local: dict[str, Path] = {}
        self._load()

    def _load(self) -> None:
        if not self.dir.is_dir():
            return
        for family_dir in sorted(self.dir.iterdir()):
            if not family_dir.is_dir() or family_dir.name == "local":
                continue
            manifest = family_dir / "manifest.json"
            if not manifest.exists():
                continue
            data = json.loads(manifest.read_text(encoding="utf-8"))
            descriptors = [
                FontDescriptor(
                    family=item["family"],
                    style=item.get("style", "normal"),
                    weight=str(item.get("weight", "400")),
                    src=item["file"],
                    unicode_range=item.get("unicode_range", ""),
                    fmt=item.get("fmt", "woff2"),
                )
                for item in data.get("faces", [])
            ]
            self._families[family_dir.name] = descriptors
        self._load_local()

    def _load_local(self) -> None:
        """扫描 local/：文件名（含字体名）→ 字体文件。

        文件名可以带版本号和字重后缀（``阿里巴巴普惠体-3.0 55 Regular.ttf``、
        ``思源宋体 CN Heavy.ttf``）—— 匹配时按"规范化后**以**字体名开头"来找，
        不是要求文件名和字体名完全一样（那样太容易踩坑）。

        除了文件名，还索引**字体文件内部声明的 family 名**（nameID 1）——
        商用字体经常"文件名一套、内部名另一套"（``演示夏行楷.ttf`` 内部叫
        "楷体"），只按文件名索引的话 ``local_font("楷体")`` 就找不到真身。
        """
        if not self.local_dir.is_dir():
            return
        for path in sorted(self.local_dir.iterdir()):
            if path.suffix.lower() not in (".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2"):
                continue
            stem = path.stem
            self._local[normalize_font_name(stem)] = path
            for internal in font_family_names(path):
                key = normalize_font_name(internal)
                if key and key not in self._local:
                    self._local[key] = path

    # -- 查询 ------------------------------------------------------------
    def family(self, key: str) -> list[FontDescriptor]:
        return self._families.get(key, [])

    def has_family(self, key: str) -> bool:
        return bool(self._families.get(key))

    def local_font(self, source_name: str) -> Optional[Path]:
        """按源字体名找用户自放的真身。

        匹配顺序：
        1. 规范化后**完全相等**（``阿里巴巴普惠体.ttf``）
        2. 去掉字重后缀再比一次（``思源宋体 CN Heavy`` → ``思源宋体 CN``）
        3. **前缀匹配**：文件名以字体名开头（``阿里巴巴普惠体-3.0 55 Regular.ttf``）
           —— 商用字体几乎都带版本号，这一步才是真正管用的
        """
        from .fontmap import split_variant

        key = normalize_font_name(source_name)
        if key in self._local:
            return self._local[key]

        base, weight = split_variant(source_name)
        base_key = normalize_font_name(base)
        if base_key in self._local:
            return self._local[base_key]

        candidates = [k for k in self._local if k.startswith(base_key)]
        if not candidates:
            return None
        if len(candidates) == 1:
            return self._local[candidates[0]]

        # 有多个候选（Light / Heavy 都在），挑字重最接近的
        def candidate_weight(name: str) -> int:
            _, w = split_variant(name)
            return w if w is not None else 400

        target = weight if weight is not None else 400
        best = min(
            candidates,
            key=lambda k: (abs(candidate_weight(k) - target), len(k)),
        )
        return self._local[best]

    def file_path(self, key: str, descriptor: FontDescriptor) -> Path:
        return self.dir / key / descriptor.src

    def lock(self) -> dict:
        path = self.dir / "fonts.lock.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}


def normalize_font_name(name: str) -> str:
    """规范化字体名用于匹配：去掉空格、连字符、下划线并小写。"""
    return re.sub(r"[\s\-_]+", "", name.strip().lower())


def font_family_names(path: Path) -> list[str]:
    """读字体文件内部声明的所有 family 名（nameID 1 / 16 / 4）。

    商用字体经常"文件名一套、内部名另一套" —— ``演示夏行楷.ttf`` 内部的
    nameID 1 是 "KaiTi"（中文版是 "楷体"）。取文件名当 family 会让
    @font-face 声明的名字和字体本身对不上，浏览器按内部名匹配就落空了。

    读不出来（没装 fontTools / 文件损坏）就返回空列表，调用方退回文件名。
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return []
    out: list[str] = []
    try:
        with TTFont(str(path), lazy=True) as font:
            for record in font["name"].names:
                if record.nameID not in (1, 16, 4):
                    continue
                try:
                    value = record.toUnicode()
                except Exception:
                    continue
                value = value.strip()
                if value and value not in out:
                    out.append(value)
    except Exception:  # 字体损坏/格式怪 —— 不该让整次转换挂掉
        return []
    return out


def font_family_name(path: Path) -> Optional[str]:
    """字体内部声明的 family 名（取第一个，通常是拉丁名）。"""
    names = font_family_names(path)
    return names[0] if names else None


#: 项目内置族名 → 系统里的等价族名
SYSTEM_ALIASES: dict[str, str] = {
    "Noto Sans SC": "Noto Sans CJK SC",
    "Noto Serif SC": "Noto Serif CJK SC",
}


def system_font(family: str) -> Optional[tuple[Path, int]]:
    """找系统里的同族字体，返回 (文件, 字体索引)。

    项目里没内置某个族时，系统里往往有等价物（本机的 Noto Serif CJK SC
    就是思源宋体 CN 的开源同源版本）。用 fontconfig 找，找不到就返回 None ——
    宁可没有，也不要悄悄换成不相干的字体。
    """
    import shutil
    import subprocess

    fc_match = shutil.which("fc-match")
    if not fc_match:
        return None
    wanted = SYSTEM_ALIASES.get(family, family)
    try:
        result = subprocess.run(
            [fc_match, "-f", "%{file}|%{index}|%{family}\n", wanted],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = (result.stdout or "").strip()
    if not line or "|" not in line:
        return None
    file_part, index_part, family_part = line.split("|", 2)
    path = Path(file_part)
    if not path.exists():
        return None
    matched = family_part.split(",")[0].strip().lower()
    if matched != wanted.lower():
        # fontconfig 回落到了别的字体（说明系统里没有这个族）→ 不用
        return None
    try:
        index = int(index_part)
    except ValueError:
        index = 0
    return path, index


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_local_fonts(local_dir: Path | None = None) -> Iterable[Path]:
    local = Path(local_dir) if local_dir else LOCAL_DIR
    if not local.is_dir():
        return []
    return sorted(
        p
        for p in local.iterdir()
        if p.suffix.lower() in (".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2")
    )
