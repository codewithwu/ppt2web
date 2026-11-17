#!/usr/bin/env python3
"""把 npm fontsource 包里的字体导入项目内置字体目录。

    # 一次性准备（联网）
    npm install --prefix ~/.cache/ppt2web/fonts \\
        @fontsource-variable/noto-serif-sc @fontsource-variable/noto-sans-sc \\
        @fontsource/carlito @fontsource/arimo @fontsource/monoton

    # 导入到项目（离线，只拷文件）
    python tools/import_fonts.py --prefix ~/.cache/ppt2web/fonts

导入后转换器就不再需要 npm 了：``ppt2web/fonts/`` 里是字体文件 + manifest，
转换期完全离线。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ppt2web.fontfiles import FONTS_DIR, parse_font_css, sha256_file  # noqa: E402
from ppt2web.fontmap import SPECS  # noqa: E402

EXT_BY_FMT = {"woff2": ".woff2", "woff": ".woff"}


def import_family(spec, prefix: Path, out_dir: Path) -> dict:
    package_dir = prefix / "node_modules" / spec.package
    if not package_dir.is_dir():
        return {"status": "missing", "package": spec.package}

    faces: list[dict] = []
    seen: set[str] = set()
    for css_name in spec.css_files:
        css_path = package_dir / css_name
        if not css_path.exists():
            continue
        for desc in parse_font_css(css_path.read_text(encoding="utf-8")):
            src_path = package_dir / "files" / Path(desc.src).name
            if not src_path.exists():
                # 有些包的 files 在根目录
                alt = package_dir / Path(desc.src).name
                src_path = alt if alt.exists() else src_path
            if not src_path.exists() or desc.src in seen:
                continue
            seen.add(desc.src)
            out_name = Path(desc.src).name
            target = out_dir / out_name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.stat().st_size != src_path.stat().st_size:
                shutil.copyfile(src_path, target)
            faces.append(
                {
                    "family": spec.family,
                    "src_family": desc.family,
                    "style": desc.style,
                    "weight": desc.weight,
                    "file": out_name,
                    "unicode_range": desc.unicode_range,
                    "fmt": desc.fmt,
                }
            )

    if not faces:
        return {"status": "empty", "package": spec.package}

    (out_dir / "manifest.json").write_text(
        json.dumps({"key": spec.key, "faces": faces}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    pkg_json = package_dir / "package.json"
    version = ""
    license_ = ""
    if pkg_json.exists():
        meta = json.loads(pkg_json.read_text(encoding="utf-8"))
        version = meta.get("version", "")
        license_ = meta.get("license", "")
        # 把 LICENSE 也带进来（OFL 要求随字体分发）
        for lic in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
            src = package_dir / lic
            if src.exists():
                shutil.copyfile(src, out_dir / f"LICENSE-{spec.key}")
                break

    return {
        "status": "ok",
        "package": spec.package,
        "version": version,
        "license": license_,
        "faces": len(faces),
        "bytes": sum((out_dir / f["file"]).stat().st_size for f in faces),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="导入字体到项目内置目录")
    parser.add_argument("--prefix", default=str(Path.home() / ".cache/ppt2web/fonts"))
    parser.add_argument("--out", default=str(FONTS_DIR))
    args = parser.parse_args()

    prefix = Path(args.prefix)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    seen_specs: dict[str, object] = {}
    for spec in SPECS.values():
        seen_specs[spec.key] = spec

    lock: dict = {"families": {}}
    total = 0
    for key, spec in seen_specs.items():
        result = import_family(spec, prefix, out / key)
        lock["families"][key] = {
            "package": spec.package,
            "sameOrigin": spec.same_origin,
            **result,
        }
        if result.get("status") == "ok":
            total += result.get("bytes", 0)
            print(f"  ✓ {key}: {result['faces']} 个分片，{result['bytes'] / 1e6:.1f}MB")
        else:
            print(f"  ✗ {key}: {result.get('status')}（{spec.package}）")

    lock["totalBytes"] = total
    (out / "fonts.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n字体已导入 {out}（合计 {total / 1e6:.1f}MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
