from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from bookbuild.cli import main

from tests.helpers import make_fixture


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.fixture = make_fixture(self.root)
        self.settings = str(self.fixture["settings"])

    def tearDown(self) -> None:
        self.directory.cleanup()

    def run_cli(self, *arguments: str) -> tuple[int, dict | None, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(arguments))
        text = out.getvalue().strip()
        payload = json.loads(text) if text else None
        return code, payload, err.getvalue()

    def test_status_shape(self) -> None:
        code, payload, _ = self.run_cli("status", "--settings", self.settings)
        self.assertEqual(code, 0)
        self.assertEqual(payload["next_chapter"], None)
        self.assertTrue(payload["ready_for_all"])
        self.assertTrue(payload["frontmatter_complete"])
        self.assertGreater(payload["chapters"][0]["words"], 30)

    def test_context_contains_source_text(self) -> None:
        code, payload, _ = self.run_cli(
            "context", "--settings", self.settings, "--chapter", "1"
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload["chapter"]["number"], 1)
        self.assertIn("doc01", payload["sources"])
        texts = [block["text"] for block in payload["blocks"]]
        self.assertTrue(any("alpha line" in text for text in texts))

    def test_validate_and_render(self) -> None:
        code, payload, _ = self.run_cli("validate", "--settings", self.settings, "--all")
        self.assertEqual(code, 0)
        self.assertTrue(payload["ready_for_all"])

        code, payload, _ = self.run_cli("render", "--settings", self.settings, "--all")
        self.assertEqual(code, 0)
        output = Path(payload["output"])
        self.assertTrue(output.is_file())
        self.assertGreater(output.stat().st_size, 5000)

    def test_init_writes_plan_then_refuses_overwrite(self) -> None:
        shutil.rmtree(self.fixture["book"])
        code, payload, _ = self.run_cli("init", "--settings", self.settings)
        self.assertEqual(code, 0)
        self.assertTrue(Path(payload["plan"]).is_file())
        chapter_titles = [chapter["title"] for chapter in payload["chapters"]]
        self.assertEqual(chapter_titles, ["Ecology"])

        code, _, error = self.run_cli("init", "--settings", self.settings)
        self.assertEqual(code, 4)
        self.assertIn("--force", error)

    def test_missing_settings_exits_2(self) -> None:
        code, _, error = self.run_cli(
            "status", "--settings", str(self.root / "nope.json")
        )
        self.assertEqual(code, 2)
        self.assertIn("not found", error)

    def test_missing_manifest_exits_3(self) -> None:
        self.fixture["manifest"].unlink()
        code, _, error = self.run_cli("status", "--settings", self.settings)
        self.assertEqual(code, 3)
        self.assertIn("manifest", error)

    def test_bad_quote_exits_4(self) -> None:
        chapter = self.fixture["chapters"] / "01-ecology.md"
        chapter.write_text(
            chapter.read_text(encoding="utf-8").replace(
                "The alpha line runs east—west and covers 1810–1960 m.",
                "The alpha line runs in a direction nobody recorded.",
            ),
            encoding="utf-8",
        )
        code, _, error = self.run_cli("validate", "--settings", self.settings, "--all")
        self.assertEqual(code, 4)
        self.assertIn("not found verbatim", error)

    def test_chapter_range_is_checked(self) -> None:
        code, _, error = self.run_cli(
            "render", "--settings", self.settings, "--chapter", "9"
        )
        self.assertEqual(code, 2)
        self.assertIn("between 1 and 1", error)


if __name__ == "__main__":
    unittest.main()
