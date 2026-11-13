import tempfile
import time
import unittest
from pathlib import Path

from whisper_lab.engine import Segment
from whisper_lab.jobs import JobOptions, JobStore


def options() -> JobOptions:
    return JobOptions(model="tiny")


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = JobStore(ttl_seconds=3600)

    def test_lifecycle_and_snapshot(self):
        job = self.store.create(
            filename="demo.wav",
            audio_path=Path("samples/demo.wav"),
            options=options(),
        )
        job.append_segment(Segment(start=0.0, end=1.5, text=" Hello."))
        job.append_segment(Segment(start=1.5, end=3.0, text=" World."))
        self.assertEqual(job.snapshot()["text"], "Hello. World.")

        job.started_at = time.time()
        job.finish(duration=3.0, language="en", probability=0.99, device="cpu", compute_type="int8")
        snapshot = job.snapshot()
        self.assertEqual(snapshot["status"], "done")
        self.assertEqual(snapshot["progress"], 1.0)
        self.assertEqual(len(snapshot["segments"]), 2)
        self.assertIsNotNone(snapshot["elapsed"])

    def test_progress_is_clamped(self):
        job = self.store.create(filename="a.wav", audio_path=Path("a.wav"), options=options())
        job.duration = 10.0
        job.append_segment(Segment(start=0.0, end=20.0, text=" Overrun."))
        self.assertEqual(job.progress, 1.0)

    def test_error_state(self):
        job = self.store.create(filename="a.wav", audio_path=Path("a.wav"), options=options())
        job.fail("boom")
        self.assertEqual(job.status, "error")
        self.assertEqual(job.error, "boom")
        self.assertIsNotNone(job.finished_at)

    def test_get_and_delete(self):
        job = self.store.create(
            filename="a.wav",
            audio_path=Path("a.wav"),
            options=options(),
            job_id="fixed-id",
        )
        self.assertIs(self.store.get("fixed-id"), job)
        self.assertTrue(self.store.delete("fixed-id"))
        self.assertIsNone(self.store.get("fixed-id"))
        self.assertFalse(self.store.delete("missing"))

    def test_expired_jobs_are_pruned_on_create(self):
        store = JobStore(ttl_seconds=0)
        old = store.create(filename="old.wav", audio_path=Path("old.wav"), options=options())
        old.finished_at = time.time() - 10
        store.create(filename="new.wav", audio_path=Path("new.wav"), options=options())
        self.assertIsNone(store.get(old.id))

    def test_pruning_deletes_uploaded_files_but_not_sample_files(self):
        with tempfile.TemporaryDirectory() as directory:
            upload = Path(directory) / "upload.wav"
            upload.write_bytes(b"audio")
            sample = Path(directory) / "sample.wav"
            sample.write_bytes(b"audio")

            store = JobStore(ttl_seconds=60)
            uploaded = store.create(
                filename="upload.wav", audio_path=upload, options=options(), owned_file=True
            )
            bundled = store.create(
                filename="sample.wav", audio_path=sample, options=options(), owned_file=False
            )
            expired_at = time.time() - 120
            for job in (uploaded, bundled):
                job.created_at = expired_at
                job.finished_at = expired_at

            store.create(filename="new.wav", audio_path=Path("new.wav"), options=options())

            self.assertFalse(upload.exists())
            self.assertTrue(sample.exists())


if __name__ == "__main__":
    unittest.main()
