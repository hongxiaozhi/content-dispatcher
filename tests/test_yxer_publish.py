from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "yxer_publish.py"
SPEC = importlib.util.spec_from_file_location("yxer_publish", SCRIPT)
assert SPEC and SPEC.loader
yxer_publish = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = yxer_publish
SPEC.loader.exec_module(yxer_publish)


class ConfigTests(unittest.TestCase):
    def write_config(self, directory: Path, body: str) -> Path:
        config = directory / "config.toml"
        config.write_text(body, encoding="utf-8")
        return config

    def test_cloud_config_builds_consistent_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "post.json").write_text("{}", encoding="utf-8")
            config = yxer_publish.load_config(self.write_config(root, """[yxer]\nexecutable = \"yxer.cmd\"\n\n[publication]\nplatform = \"小红书\"\ncontent_type = \"imageText\"\npayload = \"post.json\"\nchannel = \"cloud\"\n"""))
            validate = yxer_publish.command_for("validate", config)
            dry_run = yxer_publish.command_for("dry-run", config)
            self.assertIn("--publish-channel", validate)
            self.assertIn("cloud", validate)
            self.assertIn("--dry-run", dry_run)
            self.assertNotIn("--client-id", validate)

    def test_local_requires_client_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.write_config(root, """[yxer]\nexecutable = \"yxer.cmd\"\n\n[publication]\nplatform = \"小红书\"\ncontent_type = \"imageText\"\npayload = \"post.json\"\nchannel = \"local\"\n""")
            with self.assertRaises(yxer_publish.ConfigurationError):
                yxer_publish.load_config(config)

    def test_publish_is_not_a_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "post.json").write_text("{}", encoding="utf-8")
            config = yxer_publish.load_config(self.write_config(root, """[yxer]\nexecutable = \"yxer.cmd\"\n\n[publication]\nplatform = \"小红书\"\ncontent_type = \"imageText\"\npayload = \"post.json\"\nchannel = \"cloud\"\n"""))
            self.assertNotIn("--dry-run", yxer_publish.command_for("publish", config))


if __name__ == "__main__":
    unittest.main()
