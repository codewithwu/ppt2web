"""导出 PDF：用本机 Chrome headless 打印 print.html。

    ppt2web export-pdf out/ -o deck.pdf
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

CHROME_CANDIDATES = [
    Path.home() / ".cache/hyperframes/chrome",
    Path("/usr/bin"),
]


def find_chrome() -> str | None:
    """找 chrome-headless-shell 或 chrome。"""
    for base in CHROME_CANDIDATES:
        if not base.exists():
            continue
        for path in base.rglob("chrome-headless-shell"):
            if path.is_file():
                return str(path)
        for path in base.rglob("chrome"):
            if path.is_file():
                return str(path)
    for name in ("google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def export_pdf(out_dir: str, pdf_path: str) -> None:
    out = Path(out_dir)
    chrome = find_chrome()
    if chrome is None:
        raise SystemExit("找不到 Chrome/Chrome headless，无法导出 PDF")
    print_html = out / "print.html"
    if not print_html.exists():
        raise SystemExit(f"缺少 {print_html}")

    cmd = [
        chrome,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={Path(pdf_path).resolve()}",
        print_html.resolve().as_uri(),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise SystemExit(f"导出失败：{result.stderr[-2000:]}")
    size = Path(pdf_path).stat().st_size if Path(pdf_path).exists() else 0
    print(f"✓ {pdf_path}（{size} bytes）")
