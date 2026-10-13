#!/usr/bin/env python3
"""Convert an SVG source asset to a PNG without changing the source file."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class ConversionError(RuntimeError):
    """Raised when no supported SVG renderer can produce the target PNG."""


def svg_dimensions(source: Path) -> tuple[int, int]:
    """Read explicit SVG dimensions for a headless-browser screenshot."""
    text = source.read_text(encoding="utf-8")
    width = re.search(r'\bwidth="(\d+)(?:px)?"', text)
    height = re.search(r'\bheight="(\d+)(?:px)?"', text)
    if not width or not height:
        raise ConversionError(f"SVG 必须声明整数 width 和 height：{source}")
    return int(width.group(1)), int(height.group(1))


def windows_browser() -> Path | None:
    """Return a locally installed Chrome/Edge executable, without downloading one."""
    for value in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ):
        candidate = Path(value)
        if candidate.is_file():
            return candidate
    return None


def renderer_command(source: Path, target: Path, browser_profile: Path | None = None) -> list[str]:
    """Return a platform-appropriate SVG conversion command.

    macOS ships ``sips``. Linux users can install ``librsvg`` for
    ``rsvg-convert``. ImageMagick is an additional fallback.
    """
    if shutil.which("sips"):
        return ["sips", "-s", "format", "png", str(source), "--out", str(target)]
    if shutil.which("rsvg-convert"):
        return ["rsvg-convert", str(source), "--output", str(target)]
    if shutil.which("magick"):
        return ["magick", str(source), str(target)]
    browser = windows_browser()
    if browser:
        width, height = svg_dimensions(source)
        profile_args = [f"--user-data-dir={browser_profile}", "--no-first-run"] if browser_profile else []
        return [str(browser), "--headless=new", "--disable-gpu", "--disable-software-rasterizer", "--hide-scrollbars",
                *profile_args,
                f"--window-size={width},{height}", f"--screenshot={target}", source.as_uri()]
    if shutil.which("convert"):
        return ["convert", str(source), str(target)]
    raise ConversionError(
        "未找到 SVG 转 PNG 工具。macOS 可使用系统自带 sips；Linux 请安装 librsvg（rsvg-convert）"
        "或 ImageMagick；Windows 请安装 Chrome 或 Edge。"
    )


def convert_svg(source: Path, target: Path) -> Path:
    """Render *source* SVG as a PNG at *target* and verify its creation."""
    source = source.resolve()
    target = target.resolve()
    if source.suffix.lower() != ".svg":
        raise ConversionError(f"输入不是 SVG：{source}")
    if not source.is_file():
        raise ConversionError(f"找不到 SVG 文件：{source}")
    if target.suffix.lower() != ".png":
        raise ConversionError(f"输出必须是 PNG：{target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    # Chrome on Windows may emit UTF-8 diagnostics while the process default
    # encoding is GBK.  Diagnostics must never make an otherwise valid render
    # crash during decoding.
    browser_profile: Path | None = None
    if windows_browser():
        browser_profile = Path(tempfile.mkdtemp(prefix="content-dispatcher-chrome-"))
    try:
        result = subprocess.run(
            renderer_command(source, target, browser_profile), check=False, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
    finally:
        if browser_profile:
            shutil.rmtree(browser_profile, ignore_errors=True)
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        detail = (result.stderr or result.stdout).strip()
        raise ConversionError(f"SVG 转换失败：{source}\n{detail}")
    return target


def crop_svg_to_wechat_cover(source: Path, target: Path, crop_y: int = 0) -> Path:
    """Render a 1080px-wide vertical SVG as a 900×383 WeChat cover.

    The source remains the single editable card.  ``crop_y`` chooses the
    top edge of its 1080×460 safe crop in source coordinates.
    """
    width, height = svg_dimensions(source)
    crop_height = 460
    if width != 1080 or height < crop_height or not 0 <= crop_y <= height - crop_height:
        raise ConversionError(f"公众号裁切要求 1080px 宽 SVG 和有效 crop_y：{source}")
    text = source.read_text(encoding="utf-8")
    start = text.find(">")
    end = text.rfind("</svg>")
    if start < 0 or end < 0:
        raise ConversionError(f"不是完整 SVG：{source}")
    crop_source = target.with_suffix(".crop.svg")
    crop_source.parent.mkdir(parents=True, exist_ok=True)
    crop_source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="383" '
        f'viewBox="0 {crop_y} 1080 {crop_height}">' + text[start + 1:end] + "</svg>",
        encoding="utf-8",
    )
    try:
        return convert_svg(crop_source, target)
    finally:
        crop_source.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="将一张 SVG 素材转换为 PNG。")
    parser.add_argument("source", type=Path, help="输入 SVG")
    parser.add_argument("target", type=Path, help="输出 PNG")
    args = parser.parse_args()
    try:
        result = convert_svg(args.source, args.target)
    except ConversionError as error:
        parser.error(str(error))
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
