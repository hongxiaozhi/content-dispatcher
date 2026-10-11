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
    def test_first_post_uses_cover_and_keeps_body_image_order(self) -> None:
        root = Path(__file__).parents[2]
        article = compiler.parse_article(root / "content/chemistry/计算化学入门/01-分子对接到底在回答什么.md")
        self.assertEqual(article.title, "计算化学，到底在算什么？")
        self.assertEqual(article.cover.reference, "assets/01-cover.svg")
        self.assertEqual([asset.reference for asset in article.assets], [
            "assets/01-cover.svg", "assets/01-page-1.svg", "assets/01-page-2.svg",
        ])
        self.assertEqual(article.inline_references, ["assets/01-page-1.svg", "assets/01-page-2.svg"])

    def test_wechat_payload_places_uploaded_body_images_in_html(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cover.png").write_bytes(b"cover")
            (root / "body.png").write_bytes(b"body")
            source = root / "post.md"
            source.write_text("# 标题\n\n## 封面\n\n![封面](cover.png)\n\n正文。\n\n![正文图](body.png)\n", encoding="utf-8")
            article = compiler.parse_article(source)
            for index, asset in enumerate(article.assets):
                asset.resource = {"key": f"asset-{index}.png", "size": 1, "width": 10, "height": 10, "format": "png"}
            payload = compiler.make_wechat_payload(article, "account-id", "https://assets.example/{key}")
            content = payload["publishArgs"]["platformForms"]["微信公众号"]["articles"][0]["content"]
            self.assertIn("https://assets.example/asset-1.png", content)
            self.assertIn("alt=\"正文图\"", content)

    def test_preview_uses_converted_assets_and_reports_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cover.png").write_bytes(b"cover")
            (root / "body.png").write_bytes(b"body")
            source = root / "post.md"
            source.write_text("# 标题\n\n## 封面\n\n![封面](cover.png)\n\n正文。\n\n![正文图](body.png)\n", encoding="utf-8")
            article = compiler.parse_article(source)
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
