#!/usr/bin/env python3
"""Migrate legacy content Markdown to the workspace full/short content protocol.

The script intentionally does not invent copy.  It promotes the legacy article
body to ``full`` and its legacy Xiaohongshu description to ``short``.  Platform
media settings are retained while duplicated platform copy is removed.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from compile_markdown import CompileError, extract_content_variants, parse_simple_front_matter


CONTENT_FIELDS = {"digest", "summary", "description", "hashtags"}
SHORT_FALLBACKS = {
    "01-分子对接到底在回答什么.md": (
        "计算化学用明确的物理和化学模型研究分子的结构、能量与变化趋势。"
        "它能比较假设、解释实验线索，但结论依赖模型、结构和计算条件，不能脱离这些条件理解。"
    ),
    "02-对接MD和DFT怎么选.md": (
        "分子对接提供候选结合姿势与评分线索；MD 描述特定模型条件下的动态变化；"
        "DFT 用于电子结构、成键或反应问题。它们不是固定流水线，应按研究目标需要的证据选择。"
    ),
}


def split_front_matter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CompileError("迁移文章必须包含 YAML front matter。")
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as error:
        raise CompileError("Front matter 缺少结束的 ---") from error
    return "\n".join(lines[1:end]), "\n".join(lines[end + 1:]).strip()


def remove_platform_copy(front: str) -> str:
    """Drop content replicas from platform blocks, retaining technical media options."""
    output: list[str] = []
    lines = front.splitlines()
    index = 0
    platform_name = ""
    while index < len(lines):
        line = lines[index]
        platform_match = re.match(r"^  ([A-Za-z_][\w-]*):\s*$", line)
        if platform_match:
            platform_name = platform_match.group(1)
            output.append(line)
            index += 1
            continue
        match = re.match(r"^    ([A-Za-z_][\w-]*):\s*(.*)$", line)
        remove_title = bool(match and match.group(1) == "title" and platform_name != "xiaohongshu")
        if match and (match.group(1) in CONTENT_FIELDS or remove_title):
            value = match.group(2).strip()
            index += 1
            if value in {"|", ">"}:
                while index < len(lines) and (lines[index].startswith("      ") or not lines[index].strip()):
                    index += 1
            continue
        output.append(line)
        index += 1
    return "\n".join(output).strip()


def migrate(path: Path, write: bool) -> str:
    text = path.read_text(encoding="utf-8")
    front, legacy_body = split_front_matter(text)
    full, short = extract_content_variants(legacy_body)
    if full is not None:
        metadata, _ = parse_simple_front_matter("---\n" + front + "\n---\n")
        if not str(metadata.get("title") or "").strip() or not str(metadata.get("summary") or "").strip():
            raise CompileError("已迁移文章仍必须包含顶层 title 和 summary。")
        platforms = metadata.get("platforms") if isinstance(metadata.get("platforms"), dict) else {}
        xhs = platforms.get("xiaohongshu") if isinstance(platforms.get("xiaohongshu"), dict) else {}
        if xhs.get("title") and len(str(xhs["title"])) > 20:
            raise CompileError(f"小红书精简标题超过 20 字：{xhs['title']}")
        for config in platforms.values():
            if any(key in config for key in ("digest", "description", "summary")):
                raise CompileError("已迁移文章不能保留平台摘要或正文副本。")
        return "already migrated"
    old_metadata, _ = parse_simple_front_matter("---\n" + front + "\n---\n")
    old_platforms = old_metadata.get("platforms") if isinstance(old_metadata.get("platforms"), dict) else {}
    old_xhs = old_platforms.get("xiaohongshu") if isinstance(old_platforms.get("xiaohongshu"), dict) else {}
    short = str(old_xhs.get("description") or SHORT_FALLBACKS.get(path.name, "")).strip()
    if not short:
        raise CompileError("旧文章没有可迁移的小红书简化正文。")
    front = remove_platform_copy(front)
    metadata, _ = parse_simple_front_matter("---\n" + front + "\n---\n")
    title = str(metadata.get("title") or "")
    summary = str(metadata.get("summary") or "")
    if not title or not summary:
        raise CompileError("迁移文章必须含有顶层 title 和 summary。")
    migrated = (
        f"---\n{front}\n---\n\n"
        "<!-- content:full:start -->\n\n"
        f"{legacy_body.strip()}\n\n"
        "<!-- content:full:end -->\n\n"
        "<!-- content:short:start -->\n\n"
        f"{short}\n\n"
        "<!-- content:short:end -->\n"
    )
    if write:
        path.write_text(migrated, encoding="utf-8")
    return "migrated"


def main() -> int:
    parser = argparse.ArgumentParser(description="将旧 Markdown 迁移为 full/short 正文协议。")
    parser.add_argument("articles", nargs="+", type=Path)
    parser.add_argument("--write", action="store_true", help="实际写入；省略时仅检查迁移可行性。")
    args = parser.parse_args()
    try:
        for article in args.articles:
            print(f"{article}: {migrate(article, args.write)}")
    except CompileError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
