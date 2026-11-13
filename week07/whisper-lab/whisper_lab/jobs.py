"""In-memory job store for the web UI.

A local teaching app does not need a database or a task queue: one process,
one user, and a handful of jobs. A dict protected by a lock is enough, and it
keeps the whole flow readable in class.

The worker runs in a plain ``threading.Thread`` because transcription releases
the GIL inside CTranslate2. FastAPI serves the job status from the request
thread while the worker appends segments.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .engine import Segment, Transcriber


@dataclass(slots=True)
class JobOptions:
    model: str
    language: str | None = None
    task: str = "transcribe"
    vad_filter: bool = True
    word_timestamps: bool = False
    beam_size: int = 5


@dataclass
class Job:
    id: str
    filename: str
    audio_path: Path
    options: JobOptions
    status: str = "queued"  # queued | loading | running | done | error
    progress: float = 0.0
    duration: float = 0.0
    language: str = ""
    language_probability: float = 0.0
    device: str = ""
    compute_type: str = ""
    segments: list[Segment] = field(default_factory=list)
    text: str = ""
    summary: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    owned_file: bool = False  # True for uploads; never delete bundled samples
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "id": self.id,
                "filename": self.filename,
                "status": self.status,
                "progress": round(self.progress, 4),
                "duration": self.duration,
                "language": self.language,
                "language_probability": self.language_probability,
                "device": self.device,
                "compute_type": self.compute_type,
                "model": self.options.model,
                "task": self.options.task,
                "segments": [segment.to_dict() for segment in self.segments],
                "text": self.text,
                "summary": self.summary,
                "error": self.error,
                "elapsed": (self.finished_at - self.started_at)
                if self.started_at and self.finished_at
                else None,
            }

    def append_segment(self, segment: Segment) -> None:
        with self.lock:
            self.segments.append(segment)
            self.text = "".join(item.text for item in self.segments).strip()
            if self.duration > 0:
                self.progress = min(segment.end / self.duration, 1.0)

    def finish(self, *, duration: float, language: str, probability: float, device: str, compute_type: str) -> None:
        with self.lock:
            self.duration = duration
            self.language = language
            self.language_probability = probability
            self.device = device
            self.compute_type = compute_type
            self.status = "done"
            self.progress = 1.0
            self.finished_at = time.time()

    def fail(self, message: str) -> None:
        with self.lock:
            self.status = "error"
            self.error = message
            self.finished_at = time.time()


class JobStore:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        filename: str,
        audio_path: Path,
        options: JobOptions,
        job_id: str | None = None,
        owned_file: bool = False,
    ) -> Job:
        job = Job(
            id=job_id or uuid.uuid4().hex[:12],
            filename=filename,
            audio_path=audio_path,
            options=options,
            owned_file=owned_file,
        )
        with self._lock:
            self._prune_locked()
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def delete(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def _prune_locked(self) -> None:
        cutoff = time.time() - self._ttl_seconds
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if (job.finished_at or job.created_at) < cutoff
        ]
        for job_id in expired:
            job = self._jobs.pop(job_id, None)
            if job is not None and job.owned_file:
                job.audio_path.unlink(missing_ok=True)


def run_job(job: Job, transcriber: Transcriber) -> None:
    """Transcribe one job on the calling thread and record every outcome."""
    with job.lock:
        job.status = "running"
        job.started_at = time.time()

    try:
        result = transcriber.transcribe(
            job.audio_path,
            language=job.options.language,
            task=job.options.task,
            beam_size=job.options.beam_size,
            vad_filter=job.options.vad_filter,
            word_timestamps=job.options.word_timestamps,
            on_segment=job.append_segment,
        )
        job.finish(
            duration=result.duration,
            language=result.language,
            probability=result.language_probability,
            device=result.device,
            compute_type=result.compute_type,
        )
    except Exception as exc:  # noqa: BLE001 - the message is shown in the UI
        job.fail(f"{type(exc).__name__}: {exc}")
