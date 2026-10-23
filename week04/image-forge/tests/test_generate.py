"""Tests for job planning: selection, resume, naming, and reference bases."""
from __future__ import annotations

import base64
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ConfigError, load_settings, resolve_appearance  # noqa: E402
from generate import Job, build_jobs, generate_one  # noqa: E402
from prompts import build_prompt, collect_subjects  # noqa: E402

SETTINGS = """
runtime:
  output_dir: out
tasks:
  one:
    prompt: "A picture of {subject}."
    subjects:
      first: the first
      second: the second
  two:
    prompt: "A picture of {subject}."
    subjects:
      third: the third
"""


class PlanTest(unittest.TestCase):
    def make_settings(self, body: str):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        path = root / "settings.yaml"
        path.write_text(body, encoding="utf-8")
        return load_settings(path), root

    def test_id_matches_in_one_task_without_failing_others(self):
        settings, _ = self.make_settings(SETTINGS)
        jobs = build_jobs(settings, ["one", "two"], "first", force=False)
        self.assertEqual([job.subject.stem for job in jobs], ["first"])

    def test_unknown_id_is_rejected(self):
        settings, _ = self.make_settings(SETTINGS)
        with self.assertRaisesRegex(ConfigError, "no subject matches"):
            build_jobs(settings, ["one", "two"], "missing", force=False)

    def test_existing_output_is_skipped(self):
        settings, root = self.make_settings(SETTINGS)
        existing = root / "out" / "one" / "first.png"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"not a real png")

        jobs = build_jobs(settings, ["one"], None, force=False)
        self.assertEqual([job.subject.stem for job in jobs], ["second"])

    def test_force_includes_existing_output(self):
        settings, root = self.make_settings(SETTINGS)
        existing = root / "out" / "one" / "first.png"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"not a real png")

        jobs = build_jobs(settings, ["one"], None, force=True)
        self.assertEqual([job.subject.stem for job in jobs], ["first", "second"])

    def test_output_extension_follows_format(self):
        body = """
appearance:
  format: webp
runtime:
  output_dir: out
tasks:
  one:
    prompt: "A picture of {subject}."
    subjects: [first]
"""
        settings, root = self.make_settings(body)
        jobs = build_jobs(settings, ["one"], None, force=False)
        self.assertEqual(jobs[0].out_path, root / "out" / "one" / "first.webp")

    def test_base_points_at_the_reference_job(self):
        body = """
runtime:
  output_dir: out
tasks:
  one:
    prompt: "A picture of {subject}."
    subjects:
      base-one: the base
      variant:
        subject: the variant
        base: base-one
"""
        settings, root = self.make_settings(body)
        jobs = build_jobs(settings, ["one"], None, force=False)
        self.assertEqual(len(jobs), 2)
        self.assertIsNone(jobs[0].base_path)
        self.assertEqual(jobs[1].base_path, root / "out" / "one" / "base_one.png")

    def test_base_can_be_an_explicit_reference_file(self):
        body = """
runtime:
  output_dir: out
tasks:
  one:
    prompt: "A picture of {subject}."
    subjects:
      variant:
        subject: the variant
        base: refs/anchor.png
"""
        settings, root = self.make_settings(body)
        reference = root / "refs" / "anchor.png"
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b"not a real png")

        jobs = build_jobs(settings, ["one"], None, force=False)
        self.assertEqual(jobs[0].base_path, reference.resolve())

    def test_missing_base_with_only_id_is_rejected(self):
        body = """
runtime:
  output_dir: out
tasks:
  one:
    prompt: "A picture of {subject}."
    subjects:
      base-one: the base
      variant:
        subject: the variant
        base: base-one
"""
        settings, _ = self.make_settings(body)
        with self.assertRaisesRegex(ConfigError, "base 'base_one'"):
            build_jobs(settings, ["one"], "variant", force=False)


class FakeImages:
    """Minimal stand-in for client.images with generate/edit recording."""

    def __init__(self, image_bytes: bytes):
        self.image_bytes = image_bytes
        self.generate_calls: list[dict] = []
        self.edit_calls: list[dict] = []

    def _response(self):
        encoded = base64.b64encode(self.image_bytes).decode()
        return SimpleNamespace(data=[SimpleNamespace(b64_json=encoded)])

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return self._response()

    def edit(self, **kwargs):
        # Read the reference now: generate_one closes it after the call.
        kwargs["image"] = kwargs["image"].read()
        self.edit_calls.append(kwargs)
        return self._response()


class FakeClient:
    def __init__(self, image_bytes: bytes):
        self.images = FakeImages(image_bytes)


class GenerateOneTest(unittest.TestCase):
    def synthetic_png(self) -> bytes:
        image = Image.new("RGB", (64, 64), (255, 255, 255))
        ImageDraw.Draw(image).rectangle((16, 16, 48, 48), fill=(180, 30, 30))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()

    def make_job(self, root: Path, *, base_path: Path | None = None):
        config_dir = root / "config"
        config_dir.mkdir()
        settings_path = config_dir / "settings.yaml"
        settings_path.write_text(
            """
appearance:
  size: 1024x1024
tasks:
  demo:
    prompt: "A picture of {subject}."
    subjects:
      one: a red square
""",
            encoding="utf-8",
        )
        settings = load_settings(settings_path)
        task_name = "demo"
        subject = collect_subjects(settings, task_name)[0]
        appearance = resolve_appearance(
            settings, settings.tasks[task_name], subject.appearance
        )
        job = Job(
            task=task_name,
            subject=subject,
            prompt=build_prompt(settings, task_name, subject),
            appearance=appearance,
            out_path=root / f"{subject.stem}.png",
            base_path=base_path,
        )
        return job

    def test_generate_writes_and_passes_appearance_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = self.make_job(root)
            client = FakeClient(self.synthetic_png())

            with contextlib.redirect_stdout(io.StringIO()):
                status, _ = generate_one(
                    client, job, dry_run=False, retries=1, backoff=0
                )

            self.assertEqual(status, "ok")
            self.assertTrue(job.out_path.exists())
            with Image.open(job.out_path) as written:
                self.assertEqual(written.size, (64, 64))

            call = client.images.generate_calls[0]
            self.assertEqual(call["model"], "gpt-image-1")
            self.assertEqual(call["quality"], "medium")
            self.assertEqual(call["size"], "1024x1024")
            self.assertEqual(call["background"], "opaque")

    def test_reference_job_uses_images_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.png"
            reference.write_bytes(self.synthetic_png())
            job = self.make_job(root, base_path=reference)
            client = FakeClient(self.synthetic_png())

            with contextlib.redirect_stdout(io.StringIO()):
                status, _ = generate_one(
                    client, job, dry_run=False, retries=1, backoff=0
                )

            self.assertEqual(status, "ok")
            self.assertEqual(len(client.images.edit_calls), 1)
            self.assertEqual(client.images.generate_calls, [])
            self.assertEqual(client.images.edit_calls[0]["image"], reference.read_bytes())

    def test_missing_base_fails_without_calling_the_api(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = self.make_job(root, base_path=root / "missing.png")
            client = FakeClient(self.synthetic_png())

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                status, _ = generate_one(
                    client, job, dry_run=False, retries=1, backoff=0
                )

            self.assertEqual(status, "fail")
            self.assertEqual(client.images.generate_calls, [])
            self.assertEqual(client.images.edit_calls, [])


if __name__ == "__main__":
    unittest.main()
