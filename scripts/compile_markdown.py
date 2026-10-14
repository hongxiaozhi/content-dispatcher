#!/usr/bin/env python3
"""Compile one Markdown post into review data and YiXiaoEr platform payloads.

The compiler deliberately has no publish command. It can optionally upload assets
through ``yxer upload``; final validate/dry-run/publish stay in yxer_publish.py.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
from urllib.parse import quote
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from svg_to_png import ConversionError, convert_svg, crop_svg_to_wechat_cover


IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LIST_RE = re.compile(r"^\s*(?:[-*+] |\d+[.)] )(.+)$")
HASHTAG_LINE_RE = re.compile(r"^\s*(?:#[^\s#]+\s*)+$")
CONTENT_BLOCK_RE = re.compile(
    r"<!--\s*content:(full|short):(start|end)\s*-->", re.IGNORECASE
)
DEFAULT_THEME_PATH = Path(__file__).resolve().parents[1] / "themes" / "default.json"
DEFAULT_YXER_EXECUTABLE = "yxer.cmd" if os.name == "nt" else "yxer"


class CompileError(ValueError):
    """Raised for a source document that cannot safely become a payload."""


@dataclass
class Asset:
    reference: str
    alt: str
    source: Path
    generated: Path | None = None
    resource: dict[str, Any] | None = None
    wechat_crop_y: int | None = None


@dataclass
class Article:
    source: Path
    title: str
    body: str
    summary: str
    tags: list[str]
    assets: list[Asset]
    cover: Asset
    platform: dict[str, Any] = field(default_factory=dict)
    inline_references: list[str] = field(default_factory=list)


def parse_scalar(value: str) -> Any:
    """Parse the small scalar/list YAML subset used by content source files."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        return [item.strip().strip('"').strip("'") for item in value[1:-1].split(",") if item.strip()]
    return value.strip('"').strip("'")


def extract_content_variants(text: str) -> tuple[str | None, str | None]:
    """Return the validated full/short bodies, or ``(None, None)`` for legacy Markdown."""
    matches = list(CONTENT_BLOCK_RE.finditer(text))
    if not matches:
        return None, None
    expected = [("full", "start"), ("full", "end"), ("short", "start"), ("short", "end")]
    actual = [(match.group(1).lower(), match.group(2).lower()) for match in matches]
    if actual != expected:
        raise CompileError("正文标记必须按 full:start、full:end、short:start、short:end 各出现一次。")
    outside = (text[:matches[0].start()] + text[matches[1].end():matches[2].start()] + text[matches[3].end():]).strip()
    if outside:
        raise CompileError("双正文标记外只能保留空白；请把正文放入 full 或 short 区。")
    full = text[matches[0].end():matches[1].start()].strip()
    short = text[matches[2].end():matches[3].start()].strip()
    if not full or not short:
        raise CompileError("full 与 short 正文都不能为空。")
    return full, short


def parse_simple_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Parse the small YAML subset used by this workspace without dependencies."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as error:
        raise CompileError("Front matter 缺少结束的 ---") from error

    metadata: dict[str, Any] = {}
    index = 1
    while index < end:
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not match:
            index += 1
            continue
        key, value = match.groups()
        if key == "platforms" and not value:
            index += 1
            platforms: dict[str, dict[str, Any]] = {}
            while index < end and lines[index].startswith("  "):
                platform_match = re.match(r"^  ([A-Za-z_][\w-]*):\s*$", lines[index])
                if not platform_match:
                    raise CompileError(f"platforms 格式错误（第 {index + 1} 行）。")
                platform_name = platform_match.group(1)
                index += 1
                options: dict[str, Any] = {}
                while index < end and lines[index].startswith("    "):
                    option_match = re.match(r"^    ([A-Za-z_][\w-]*):\s*(.*)$", lines[index])
                    if not option_match:
                        raise CompileError(f"平台配置格式错误（第 {index + 1} 行）。")
                    option, option_value = option_match.groups()
                    if option_value == "|":
                        index += 1
                        values: list[str] = []
                        while index < end and (lines[index].startswith("      ") or not lines[index].strip()):
                            values.append(lines[index][6:] if lines[index].startswith("      ") else "")
                            index += 1
                        options[option] = "\n".join(values).strip()
                        continue
                    if option_value:
                        options[option] = parse_scalar(option_value)
                        index += 1
                        continue
                    index += 1
                    values: list[str] = []
                    while index < end and re.match(r"^      -\s+", lines[index]):
                        values.append(re.sub(r"^      -\s+", "", lines[index]).strip().strip('"'))
                        index += 1
                    options[option] = values
                platforms[platform_name] = options
            metadata[key] = platforms
            continue
        if value == "|":
            index += 1
            values: list[str] = []
            while index < end and (lines[index].startswith("  ") or not lines[index].strip()):
                values.append(lines[index][2:] if lines[index].startswith("  ") else "")
                index += 1
            metadata[key] = "\n".join(values).strip()
            continue
        if not value:
            index += 1
            values = []
            while index < end and re.match(r"^\s+-\s+", lines[index]):
                values.append(re.sub(r"^\s+-\s+", "", lines[index]).strip().strip('"'))
                index += 1
            metadata[key] = values
            continue
        metadata[key] = parse_scalar(value)
        index += 1
    return metadata, "\n".join(lines[end + 1:]).strip()


def find_heading_title(text: str) -> str | None:
    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match and len(match.group(1)) == 1:
            return match.group(2).strip()
    return None


def image_refs(text: str) -> list[tuple[str, str]]:
    return [(alt.strip(), ref.strip()) for alt, ref in IMAGE_RE.findall(text)]


def cover_ref_from_section(text: str) -> str | None:
    lines = text.splitlines()
    in_cover = False
    for line in lines:
        heading = HEADING_RE.match(line)
        if heading:
            level, title = heading.groups()
            if len(level) == 2 and title.strip() == "封面":
                in_cover = True
                continue
            if in_cover and len(level) <= 2:
                return None
        if in_cover:
            match = IMAGE_RE.search(line)
            if match:
                return match.group(2).strip()
    return None


def without_cover_block(text: str, cover_ref: str) -> str:
    """Remove only the explicit ``## 封面`` block, retaining body image order."""
    lines = text.splitlines()
    output: list[str] = []
    in_cover = False
    for line in lines:
        heading = HEADING_RE.match(line)
        if heading:
            level, title = heading.groups()
            if len(level) == 2 and title.strip() == "封面":
                in_cover = True
                continue
            if in_cover and len(level) <= 2:
                in_cover = False
        if in_cover and cover_ref in line:
            continue
        if not in_cover:
            output.append(line)
    return "\n".join(output).strip()


def resolve_asset(article_path: Path, reference: str) -> Path:
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", reference):
        raise CompileError(f"图片必须是文章目录内的本地文件，不能直接引用 URL：{reference}")
    candidate = (article_path.parent / reference).resolve()
    try:
        candidate.relative_to(article_path.parent.resolve())
    except ValueError as error:
        raise CompileError(f"图片路径越出文章目录：{reference}") from error
    if not candidate.is_file():
        raise CompileError(f"找不到图片：{reference}")
    return candidate


def parse_article(article_path: Path, target: str | None = None) -> Article:
    source = article_path.resolve()
    if not source.is_file():
        raise CompileError(f"找不到 Markdown：{source}")
    metadata, remaining = parse_simple_front_matter(source.read_text(encoding="utf-8"))
    platforms = metadata.get("platforms") if isinstance(metadata.get("platforms"), dict) else {}
    platform = platforms.get(target, {}) if target else {}
    if not isinstance(platform, dict):
        raise CompileError(f"platforms.{target} 必须是对象。")
    full_body, short_body = extract_content_variants(remaining)
    if full_body is None:
        raise CompileError("文章必须使用 content:full 与 content:short 正文标记；请先运行迁移工具。")
    body = short_body if target == "xiaohongshu" else full_body
    main_title = str(metadata.get("title") or "").strip()
    title = str(platform.get("title") or main_title) if target == "xiaohongshu" else main_title
    if not title:
        raise CompileError("文章必须包含 title 或一级标题")

    declared_images = platform.get("images") if isinstance(platform.get("images"), list) else metadata.get("images") if isinstance(metadata.get("images"), list) else []
    all_refs: list[tuple[str, str]] = []
    for ref in declared_images:
        all_refs.append(("", str(ref)))
    if not (target == "xiaohongshu" and isinstance(platform.get("images"), list)):
        all_refs.extend(image_refs(full_body))
    configured_cover = platform.get("cover")
    if isinstance(configured_cover, str) and configured_cover.strip() and not any(ref == configured_cover.strip() for _, ref in all_refs):
        all_refs.insert(0, ("", configured_cover.strip()))
    deduplicated: list[tuple[str, str]] = []
    seen: set[str] = set()
    for alt, ref in all_refs:
        if ref not in seen:
            deduplicated.append((alt, ref))
            seen.add(ref)
        elif alt:
            for index, (known_alt, known_ref) in enumerate(deduplicated):
                if known_ref == ref and not known_alt:
                    deduplicated[index] = (alt, ref)
                    break
    if not deduplicated:
        raise CompileError("文章没有图片。图文发布至少需要一张封面图。")

    cover_ref = str(configured_cover or cover_ref_from_section(remaining) or (declared_images[0] if declared_images else deduplicated[0][1]))
    assets = [Asset(reference=ref, alt=alt, source=resolve_asset(source, ref)) for alt, ref in deduplicated]
    asset_by_ref = {asset.reference: asset for asset in assets}
    if cover_ref not in asset_by_ref:
        raise CompileError(f"封面未出现在图片清单中：{cover_ref}")
    cover = asset_by_ref[cover_ref]
    if target == "wechat" and platform.get("cover_crop_y") not in (None, ""):
        try:
            cover.wechat_crop_y = int(platform["cover_crop_y"])
        except (TypeError, ValueError) as error:
            raise CompileError("platforms.wechat.cover_crop_y 必须是整数。") from error
    ordered = [cover, *(asset for asset in assets if asset is not cover)]
    body = without_cover_block(body, cover_ref)
    body = re.sub(r"^#\s+.+?$", "", body, count=1, flags=re.MULTILINE).strip()
    tags = metadata.get("hashtags") if isinstance(metadata.get("hashtags"), list) else []
    if not tags:
        tags = [tag for line in body.splitlines() if HASHTAG_LINE_RE.match(line) for tag in re.findall(r"#([^\s#]+)", line)]
    body = "\n".join(line for line in body.splitlines() if not HASHTAG_LINE_RE.match(line)).strip()
    summary = str(metadata.get("summary") or "").strip()
    if not summary:
        raise CompileError("文章必须包含共享 summary。")
    return Article(source=source, title=title, body=body, summary=summary, tags=[str(tag).lstrip("#") for tag in tags],
                   assets=ordered, cover=cover, platform=platform, inline_references=[ref for _, ref in image_refs(body)])


def materialize_assets(article: Article, output_dir: Path) -> None:
    asset_dir = output_dir / "assets"
    for index, asset in enumerate(article.assets, start=1):
        suffix = ".png" if asset.source.suffix.lower() == ".svg" else asset.source.suffix.lower()
        target = asset_dir / f"{index:02d}-{asset.source.stem}{suffix}"
        if asset.source.suffix.lower() == ".svg":
            if asset.wechat_crop_y is not None:
                crop_svg_to_wechat_cover(asset.source, target, asset.wechat_crop_y)
            else:
                convert_svg(asset.source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset.source, target)
        asset.generated = target


def upload_asset(asset: Asset, executable: str) -> None:
    assert asset.generated is not None
    result = subprocess.run([executable, "upload", "--file", str(asset.generated), "--json"], check=False,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise CompileError(f"上传失败：{asset.generated.name}\n{result.stderr.strip() or result.stdout.strip()}")
    try:
        response = json.loads(result.stdout)
        data = response["data"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise CompileError(f"无法解析上传结果：{asset.generated.name}") from error
    required = ("key", "size", "width", "height", "format")
    if not response.get("ok") or any(key not in data for key in required):
        raise CompileError(f"上传结果缺少资源字段：{asset.generated.name}")
    asset.resource = {key: data[key] for key in required}


def render_inline(text: str, image_html: dict[str, str]) -> str:
    parts: list[str] = []
    cursor = 0
    for match in IMAGE_RE.finditer(text):
        parts.append(html.escape(text[cursor:match.start()]))
        parts.append(image_html.get(match.group(2).strip(), ""))
        cursor = match.end()
    parts.append(html.escape(text[cursor:]))
    rendered = "".join(parts)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)


def markdown_to_html(article: Article, image_html: dict[str, str], platform: str = "") -> str:
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            style = ' style="margin:0 0 18px;line-height:1.85;color:#243746;"' if platform == "wechat" else ""
            blocks.append(f"<p{style}>{render_inline(' '.join(paragraph), image_html)}</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            style = ' style="margin:0 0 18px;padding-left:1.5em;line-height:1.85;color:#243746;"' if platform == "wechat" else ""
            blocks.append(f"<ol{style}>" + "".join(f"<li>{render_inline(item, image_html)}</li>" for item in list_items) + "</ol>")
            list_items = []

    for raw_line in article.body.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue
        image_match = IMAGE_RE.fullmatch(line)
        if image_match:
            flush_paragraph()
            flush_list()
            rendered = image_html.get(image_match.group(2).strip())
            if rendered:
                blocks.append(rendered)
            continue
        heading = HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            flush_list()
            level, value = heading.groups()
            # The document title is already rendered as <h1> by the preview.
            # Authors therefore use Markdown ``##`` for ordinary article sections.
            level_number = min(len(level), 4)
            style = (' style="margin:34px 0 15px;padding-left:12px;border-left:4px solid #426B88;'
                     'font-size:20px;line-height:1.45;color:#243746;"') if platform == "wechat" and level_number == 2 else ""
            blocks.append(f"<h{level_number}{style}>{render_inline(value, image_html)}</h{level_number}>")
            continue
        item = LIST_RE.match(line)
        if item:
            flush_paragraph()
            list_items.append(item.group(1))
            continue
        flush_list()
        paragraph.append(line)
    flush_paragraph()
    flush_list()
    return "\n".join(blocks)


def plain_text(article: Article) -> str:
    text = IMAGE_RE.sub("", article.body)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def wechat_digest(article: Article) -> str:
    """Return a one-line WeChat digest within the platform's 120-character limit."""
    source = article.platform.get("digest") or article.summary or plain_text(article)
    return re.sub(r"\s+", " ", str(source)).strip()[:120]


def uploaded_image(asset: Asset) -> dict[str, Any]:
    if asset.resource is None:
        raise CompileError("生成发布 payload 前必须上传所有图片；请添加 --upload。")
    return dict(asset.resource)


def format_xiaohongshu_description(text: str) -> str:
    """Turn blank-line paragraphs and Markdown bold into conservative HTML."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    rendered: list[str] = []
    for paragraph in paragraphs:
        safe = html.escape(paragraph)
        safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
        rendered.append(f"<p>{safe.replace(chr(10), '<br />')}</p>")
    return "".join(rendered)


def xiaohongshu_description(article: Article) -> str:
    """Return the exact HTML description used by the XHS payload before tags."""
    return format_xiaohongshu_description(plain_text(article).strip())


def make_xiaohongshu_payload(article: Article, account_id: str) -> dict[str, Any]:
    if len(article.assets) > 9:
        raise CompileError("小红书图文最多 9 张图，请拆分文章。")
    if len(article.title) > 20:
        raise CompileError("小红书标题超过 20 个字符，请在 Markdown 中使用更短标题。")
    images = [uploaded_image(asset) for asset in article.assets]
    # Long-form Markdown may exceed a Xiaohongshu note's 1,000-character
    # description limit.  A platform-specific summary keeps one source file
    # while letting its card images carry the detailed tutorial.
    description = xiaohongshu_description(article)
    if article.tags:
        description += "<p>" + " ".join(f"#{tag}" for tag in article.tags) + "</p>"
    if len(description) > 1000:
        raise CompileError("小红书正文超过 1000 个字符，请压缩内容。")
    return {
        "action": "publish", "publishType": "imageText", "platforms": ["小红书"], "publishChannel": "cloud",
        "publishArgs": {"accountForms": [{
            "platformAccountId": account_id, "cover": images[0], "coverKey": images[0]["key"], "images": images,
            "contentPublishForm": {"formType": "task", "title": article.title, "description": description,
                                   "images": images, "visibleType": 0},
        }]},
    }


def make_wechat_payload(article: Article, account_id: str, resource_url_template: str) -> dict[str, Any]:
    image_html = {
        asset.reference: f'<p><img src="{html.escape(resource_url_template.format(key=uploaded_image(asset)["key"]), quote=True)}" alt="{html.escape(asset.alt, quote=True)}" /></p>'
        for asset in article.assets if asset is not article.cover
    }
    content = markdown_to_html(article, image_html, "wechat")
    for asset in article.assets[1:]:
        if asset.reference not in article.inline_references:
            content += "\n" + image_html[asset.reference]
    cover = uploaded_image(article.cover)
    notify = 1 if str(article.platform.get("notify_subscribers", "false")).lower() in {"1", "true", "yes"} else 0
    return {
        "action": "publish", "publishType": "article", "platforms": ["微信公众号"], "publishChannel": "cloud",
        "desc": plain_text(article)[:120],
        "publishArgs": {"accountForms": [{"platformAccountId": account_id, "platformName": "微信公众号"}], "platformForms": {"微信公众号": {
            "articles": [{"title": article.title, "content": content, "digest": wechat_digest(article), "type": 0,
                          "cover": {"key": cover["key"], "raw": {}}}],
            "notifySubscribers": notify, "pubType": 1,
        }}},
    }


def review(article: Article) -> dict[str, Any]:
    warnings: list[str] = []
    if len(article.assets) == 1:
        warnings.append("文章只有封面，没有正文图片。")
    if (not article.inline_references and len(article.assets) > 1
            and not isinstance(article.platform.get("images"), list)):
        warnings.append("正文没有内嵌图片标记；非封面图片会追加到文章末尾。")
    if re.search(r"评论区|留一个关键词|关注我|点个赞|私信", article.body):
        warnings.append("检测到互动话术；教程稿发布前建议人工确认是否删除。")
    return {"title": article.title, "cover": article.cover.reference,
            "body_images": [asset.reference for asset in article.assets if asset is not article.cover], "warnings": warnings}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_theme(path: Path | None) -> dict[str, str]:
    """Load a small visual theme; article content never comes from this file."""
    theme_path = path or DEFAULT_THEME_PATH
    try:
        raw = json.loads(theme_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CompileError(f"找不到预览主题：{theme_path}") from error
    except json.JSONDecodeError as error:
        raise CompileError(f"预览主题不是有效 JSON：{theme_path}") from error
    required = ("brand_name", "accent", "ink", "muted", "background", "surface", "max_width")
    if not isinstance(raw, dict) or any(not isinstance(raw.get(key), str) or not raw[key].strip() for key in required):
        raise CompileError("预览主题缺少必要的字符串字段。")
    return {key: raw[key].strip() for key in required}


def local_asset_url(asset: Asset, output_dir: Path) -> str:
    assert asset.generated is not None
    return quote(asset.generated.relative_to(output_dir).as_posix())


def write_preview(article: Article, output_dir: Path, review_result: dict[str, Any], theme: dict[str, str], target: str = "wechat") -> None:
    """Generate a self-contained, review-only HTML preview from converted assets."""
    image_html = {
        asset.reference: (
            '<figure class="article-image"><img src="%s" alt="%s" loading="lazy" />'
            '<figcaption>%s</figcaption></figure>'
        ) % (html.escape(local_asset_url(asset, output_dir), quote=True), html.escape(asset.alt, quote=True), html.escape(asset.alt))
        for asset in article.assets if asset is not article.cover
    }
    if target == "xiaohongshu":
        body = xiaohongshu_description(article)
        if article.tags:
            body += "<p>" + " ".join(f"#{html.escape(tag)}" for tag in article.tags) + "</p>"
        body += "\n" + "\n".join(
            image_html[asset.reference] for asset in article.assets if asset is not article.cover
        )
    else:
        body = markdown_to_html(article, image_html, "wechat")
        for asset in article.assets[1:]:
            if asset.reference not in article.inline_references:
                body += "\n" + image_html[asset.reference]
    warnings = "".join(f"<li>{html.escape(item)}</li>" for item in review_result["warnings"])
    warning_block = f'<aside class="review"><strong>审核提示</strong><ul>{warnings}</ul></aside>' if warnings else ""
    css = """
      :root { --accent: %(accent)s; --ink: %(ink)s; --muted: %(muted)s; --bg: %(background)s; --surface: %(surface)s; --width: %(max_width)s; }
      * { box-sizing: border-box; }
      body { margin: 0; background: var(--bg); color: var(--ink); font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; }
      .site { max-width: var(--width); margin: 0 auto; padding: 32px 20px 72px; }
      .brand { color: var(--accent); font-size: 14px; font-weight: 700; letter-spacing: .08em; margin: 0 0 18px; }
      article { background: var(--surface); border-radius: 18px; padding: 28px clamp(22px, 6vw, 56px) 48px; box-shadow: 0 12px 42px rgba(36, 55, 70, .08); }
      h1 { margin: 0 0 22px; font-size: clamp(30px, 7vw, 46px); line-height: 1.22; letter-spacing: -.03em; }
      h2 { margin: 42px 0 16px; padding-left: 14px; border-left: 4px solid var(--accent); font-size: 23px; line-height: 1.35; }
      h3, h4 { margin: 30px 0 12px; font-size: 19px; }
      p, li { font-size: 17px; line-height: 1.9; }
      p { margin: 0 0 18px; } ol { padding-left: 1.35em; margin: 0 0 18px; } strong { color: var(--accent); }
      .cover { display: block; width: 100%%; margin: 0 0 30px; border-radius: 12px; background: #eef2f3; }
      .article-image { margin: 30px 0; } .article-image img { display: block; width: 100%%; border-radius: 10px; background: #eef2f3; }
      figcaption { margin-top: 9px; text-align: center; color: var(--muted); font-size: 13px; }
      .review { margin: 20px 0 0; padding: 16px 18px; background: #fff7e6; border-left: 4px solid #d99020; border-radius: 8px; color: #6f4b11; }
      .review ul { margin: 8px 0 0; padding-left: 1.2em; } .review li { font-size: 14px; line-height: 1.6; }
      @media (max-width: 560px) { .site { padding: 16px 10px 40px; } article { border-radius: 12px; padding: 22px 18px 34px; } p, li { font-size: 16px; } }
    """ % theme
    preview = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title><style>{css}</style></head><body><main class="site"><p class="brand">{brand}</p><article>
<h1>{title}</h1><img class="cover" src="{cover}" alt="{cover_alt}" />{body}</article>{warnings}</main></body></html>
""".format(title=html.escape(article.title), css=css, brand=html.escape(theme["brand_name"]),
           cover=html.escape(local_asset_url(article.cover, output_dir), quote=True), cover_alt=html.escape(article.cover.alt),
           body=body, warnings=warning_block)
    (output_dir / "preview.html").write_text(preview, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="将图文 Markdown 编译为小红书或公众号 payload。")
    parser.add_argument("article", type=Path, help="Markdown 文章路径")
    parser.add_argument("--target", choices=("xiaohongshu", "wechat"), required=True)
    parser.add_argument("--account-id", help="目标平台账号 ID；生成 payload 时必填")
    parser.add_argument("--output-dir", type=Path, default=Path("build/content"))
    parser.add_argument("--upload", action="store_true", help="转换后通过 yxer upload 上传图片")
    parser.add_argument("--yxer", default=DEFAULT_YXER_EXECUTABLE, help="yxer 可执行文件路径")
    parser.add_argument("--theme", type=Path, help="预览主题 JSON；默认使用 themes/default.json")
    parser.add_argument("--resource-url-template", default="https://oss-v2.yixiaoer.cn/{key}",
                        help="公众号正文内图的内部资源 URL 模板")
    args = parser.parse_args()
    try:
        article = parse_article(args.article, args.target)
        output_dir = args.output_dir.resolve()
        materialize_assets(article, output_dir)
        review_result = review(article)
        write_json(output_dir / "review.json", review_result)
        write_preview(article, output_dir, review_result, load_theme(args.theme), args.target)
        if args.upload:
            if not args.account_id:
                raise CompileError("使用 --upload 生成发布 payload 时必须提供 --account-id。")
            for asset in article.assets:
                upload_asset(asset, args.yxer)
            payload = make_xiaohongshu_payload(article, args.account_id) if args.target == "xiaohongshu" else make_wechat_payload(article, args.account_id, args.resource_url_template)
            write_json(output_dir / f"payload.{args.target}.json", payload)
        manifest = {"source": str(article.source), "title": article.title, "target": args.target,
                    "assets": [{"reference": asset.reference, "alt": asset.alt, "generated": str(asset.generated), "resource": asset.resource} for asset in article.assets]}
        write_json(output_dir / "manifest.json", manifest)
    except (CompileError, ConversionError) as error:
        parser.error(str(error))
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
