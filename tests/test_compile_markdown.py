from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("compile_markdown", SCRIPTS / "compile_markdown.py")
assert SPEC and SPEC.loader
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


class MarkdownCompilerTests(unittest.TestCase):
    def test_first_post_uses_xiaohongshu_cover_and_keeps_card_order(self) -> None:
        root = Path(__file__).parents[2]
        article = compiler.parse_article(root / "content/chemistry/计算化学入门/01-分子对接到底在回答什么.md", "xiaohongshu")
        self.assertEqual(article.title, "计算化学，到底在算什么？")
        self.assertEqual(article.cover.reference, "assets/01-cover.svg")
        self.assertEqual([asset.reference for asset in article.assets], [
            "assets/01-cover.svg", "assets/01-page-1.svg", "assets/01-page-2.svg",
        ])
        self.assertEqual(article.inline_references, [])

    def test_wechat_payload_places_uploaded_body_images_in_html(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cover.png").write_bytes(b"cover")
            (root / "body.png").write_bytes(b"body")
            source = root / "post.md"
            source.write_text("""---
title: "标题"
summary: "摘要"
platforms:
  wechat:
    cover: "cover.png"
---
<!-- content:full:start -->

正文。

![正文图](body.png)

<!-- content:full:end -->
<!-- content:short:start -->

简化正文。

<!-- content:short:end -->
""", encoding="utf-8")
            article = compiler.parse_article(source, "wechat")
            for index, asset in enumerate(article.assets):
                asset.resource = {"key": f"asset-{index}.png", "size": 1, "width": 10, "height": 10, "format": "png"}
            payload = compiler.make_wechat_payload(article, "account-id", "https://assets.example/{key}")
            content = payload["publishArgs"]["platformForms"]["微信公众号"]["articles"][0]["content"]
            self.assertIn("https://assets.example/asset-1.png", content)
            self.assertIn("alt=\"正文图\"", content)

    def test_wechat_digest_is_a_single_line_within_platform_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cover = root / "cover.png"
            cover.write_bytes(b"cover")
            source = root / "post.md"
            source.write_text("""---
title: "标题"
summary: """ + "计算化学。" * 80 + """
platforms:
  wechat:
    cover: "cover.png"
---
<!-- content:full:start -->

完整正文。

<!-- content:full:end -->
<!-- content:short:start -->

简化正文。

<!-- content:short:end -->
""", encoding="utf-8")
            article = compiler.parse_article(source, "wechat")
            digest = compiler.wechat_digest(article)
            self.assertLessEqual(len(digest), 120)
            self.assertNotIn("\n", digest)

    def test_platform_configuration_uses_xhs_short_title_and_shared_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("wechat.png", "xhs-cover.png", "xhs-card.png"):
                (root / name).write_bytes(b"image")
            source = root / "post.md"
            source.write_text(
                """---
title: "通用标题"
summary: "通用摘要"
platforms:
  wechat:
    cover: "wechat.png"
  xiaohongshu:
    title: "小红书精简标题"
    cover: "xhs-cover.png"
    images:
      - xhs-cover.png
      - xhs-card.png
---

<!-- content:full:start -->

完整正文。

<!-- content:full:end -->
<!-- content:short:start -->

简化正文。

<!-- content:short:end -->
""",
                encoding="utf-8",
            )
            wechat = compiler.parse_article(source, "wechat")
            xiaohongshu = compiler.parse_article(source, "xiaohongshu")
            self.assertEqual(wechat.title, "通用标题")
            self.assertEqual(compiler.wechat_digest(wechat), "通用摘要")
            self.assertEqual(xiaohongshu.title, "小红书精简标题")
            self.assertEqual([asset.reference for asset in xiaohongshu.assets], ["xhs-cover.png", "xhs-card.png"])

    def test_dual_content_uses_shared_metadata_and_platform_selected_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("cover.png", "card.png"):
                (root / name).write_bytes(b"image")
            source = root / "post.md"
            source.write_text(
                """---
title: "统一标题"
summary: "统一摘要"
hashtags: [计算化学, 分子对接]
platforms:
  wechat:
    cover: "cover.png"
  xiaohongshu:
    cover: "cover.png"
    images:
      - cover.png
      - card.png
---

<!-- content:full:start -->

完整正文，包含必要限制。

<!-- content:full:end -->

<!-- content:short:start -->

简化正文，保留必要限制。

<!-- content:short:end -->
""",
                encoding="utf-8",
            )
            wechat = compiler.parse_article(source, "wechat")
            xiaohongshu = compiler.parse_article(source, "xiaohongshu")
            self.assertEqual(wechat.title, "统一标题")
            self.assertEqual(wechat.summary, "统一摘要")
            self.assertEqual(wechat.body, "完整正文，包含必要限制。")
            self.assertEqual(xiaohongshu.body, "简化正文，保留必要限制。")
            self.assertEqual(xiaohongshu.tags, ["计算化学", "分子对接"])

    def test_dual_content_rejects_text_outside_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cover.png").write_bytes(b"image")
            source = root / "post.md"
            source.write_text(
                """---
title: "标题"
platforms:
  wechat:
    cover: "cover.png"
---

不应发布的文字。
<!-- content:full:start -->
完整正文。
<!-- content:full:end -->
<!-- content:short:start -->
简化正文。
<!-- content:short:end -->
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(compiler.CompileError, "标记外"):
                compiler.parse_article(source, "wechat")

    def test_legacy_body_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cover.png").write_bytes(b"image")
            source = root / "post.md"
            source.write_text("""---
title: "标题"
summary: "摘要"
platforms:
  wechat:
    cover: "cover.png"
---

旧正文不能由正式发布解析器读取。
""", encoding="utf-8")
            with self.assertRaisesRegex(compiler.CompileError, "content:full"):
                compiler.parse_article(source, "wechat")

    def test_xhs_title_limit_reports_instead_of_truncating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cover.png").write_bytes(b"image")
            source = root / "post.md"
            source.write_text("""---
title: "这是一个超过小红书二十字限制的完整技术文章主标题示例"
summary: "摘要"
platforms:
  xiaohongshu:
    cover: "cover.png"
    images:
      - cover.png
---
<!-- content:full:start -->

完整正文。

<!-- content:full:end -->
<!-- content:short:start -->

简化正文。

<!-- content:short:end -->
""", encoding="utf-8")
            article = compiler.parse_article(source, "xiaohongshu")
            article.assets[0].resource = {"key": "cover", "size": 1, "width": 1, "height": 1, "format": "png"}
            with self.assertRaisesRegex(compiler.CompileError, "标题超过"):
                compiler.make_xiaohongshu_payload(article, "account")

    def test_missing_configured_image_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "post.md"
            source.write_text("""---
title: "标题"
summary: "摘要"
platforms:
  wechat:
    cover: "missing.png"
---
<!-- content:full:start -->

完整正文。

<!-- content:full:end -->
<!-- content:short:start -->

简化正文。

<!-- content:short:end -->
""", encoding="utf-8")
            with self.assertRaisesRegex(compiler.CompileError, "找不到图片"):
                compiler.parse_article(source, "wechat")

    def test_preview_uses_converted_assets_and_reports_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cover.png").write_bytes(b"cover")
            (root / "body.png").write_bytes(b"body")
            source = root / "post.md"
            source.write_text("""---
title: "标题"
summary: "摘要"
platforms:
  wechat:
    cover: "cover.png"
---
<!-- content:full:start -->

正文。

![正文图](body.png)

<!-- content:full:end -->
<!-- content:short:start -->

简化正文。

<!-- content:short:end -->
""", encoding="utf-8")
            article = compiler.parse_article(source, "wechat")
            output = root / "build"
            compiler.materialize_assets(article, output)
            review = compiler.review(article)
            theme = compiler.load_theme(None)
            compiler.write_preview(article, output, review, theme)
            preview = (output / "preview.html").read_text(encoding="utf-8")
            self.assertIn("assets/02-body.png", preview)
            self.assertIn("<h1>标题</h1>", preview)


if __name__ == "__main__":
    unittest.main()
