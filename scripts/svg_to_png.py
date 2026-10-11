#!/usr/bin/env python3
"""Convert an SVG source asset to a PNG without changing the source file."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


class ConversionError(RuntimeError):
    """Raised when no supported SVG renderer can produce the target PNG."""


def renderer_command(source: Path, target: Path) -> list[str]:
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
    if shutil.which("convert"):
        return ["convert", str(source), str(target)]
    raise ConversionError(
        "未找到 SVG 转 PNG 工具。macOS 可使用系统自带 sips；"
        "Linux 请安装 librsvg（rsvg-convert）或 ImageMagick。"
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
    result = subprocess.run(renderer_command(source, target), check=False, capture_output=True, text=True)
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        detail = (result.stderr or result.stdout).strip()
        raise ConversionError(f"SVG 转换失败：{source}\n{detail}")
    return target


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
