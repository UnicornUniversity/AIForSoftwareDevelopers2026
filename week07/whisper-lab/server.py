#!/usr/bin/env python
"""Local web UI for Whisper Lab.

    python server.py            # http://127.0.0.1:8000
    python server.py --port 9000

The browser only uploads a file and polls job status; transcription happens in
a background thread and the finished transcript can be sent to Ollama for
notes. Nothing leaves the machine.
"""

from __future__ import annotations

import argparse
import gc
import threading
import time
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from whisper_lab import formats, llm
from whisper_lab.engine import (
    Transcriber,
    Transcription,
    cuda_device_count,
    resolve_compute_type,
    resolve_device,
)
from whisper_lab.jobs import Job, JobOptions, JobStore, run_job

app = FastAPI(title="Whisper Lab", docs_url="/api/docs", openapi_url="/api/openapi.json")

store = JobStore(ttl_seconds=config.JOB_TTL_S)

# One model at a time: students usually have one GPU and a few gigabytes of
# VRAM. The lock prevents two uploads from fighting over memory, and evicting
# the cache when the model changes frees VRAM before the next load.
_model_cache: dict[tuple[str, str, str], Transcriber] = {}
_cache_lock = threading.Lock()
_job_lock = threading.Lock()


class SampleRequest(BaseModel):
    name: str
    model: str = config.DEFAULT_MODEL
    language: str = "auto"
    task: str = "transcribe"
    vad: bool = True
    words: bool = False


class SummaryRequest(BaseModel):
    focus: str = ""


def get_transcriber(model_name: str) -> Transcriber:
    device = resolve_device(config.DEFAULT_DEVICE)
    compute_type = resolve_compute_type(device, config.DEFAULT_COMPUTE_TYPE)
    key = (model_name, device, compute_type)

    with _cache_lock:
        transcriber = _model_cache.get(key)
        if transcriber is not None:
            return transcriber

        if _model_cache:
            _model_cache.clear()
            gc.collect()

        transcriber = Transcriber(
            model_name=model_name,
            device=device,
            compute_type=compute_type,
        )
        _model_cache[key] = transcriber
        return transcriber


def validate_options(model: str, task: str, language: str) -> None:
    if model not in config.MODEL_NAMES:
        raise HTTPException(400, f"Unknown model {model!r}. Choose one of: {', '.join(config.MODEL_NAMES)}")
    if task not in ("transcribe", "translate"):
        raise HTTPException(400, "task must be 'transcribe' or 'translate'")
    if not language or len(language) > 8:
        raise HTTPException(400, "Invalid language code")


def options_from(model: str, language: str, task: str, vad: bool, words: bool) -> JobOptions:
    validate_options(model, task, language)
    return JobOptions(
        model=model,
        language=None if language == "auto" else language,
        task=task,
        vad_filter=vad,
        word_timestamps=words,
        beam_size=config.BEAM_SIZE,
    )


def start_worker(job: Job) -> None:
    thread = threading.Thread(target=_worker, args=(job,), daemon=True, name=f"job-{job.id}")
    thread.start()


def _worker(job: Job) -> None:
    # Set "loading" only once this job owns the GPU, so queued jobs stay
    # "queued" instead of claiming to load a model they are waiting for.
    with _job_lock:
        with job.lock:
            job.status = "loading"
            job.started_at = time.time()
        try:
            transcriber = get_transcriber(job.options.model)
            run_job(job, transcriber)
        except Exception as exc:  # noqa: BLE001 - reported in the UI
            job.fail(f"{type(exc).__name__}: {exc}")


def get_job_or_404(job_id: str) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found (it may have expired).")
    return job


def sample_files() -> list[Path]:
    if not config.SAMPLES_DIR.is_dir():
        return []
    return sorted(
        path
        for path in config.SAMPLES_DIR.iterdir()
        if path.suffix.lower() in config.AUDIO_EXTENSIONS
    )


# ---------------------------------------------------------------- API ------


@app.get("/api/status")
def status() -> dict:
    device = resolve_device(config.DEFAULT_DEVICE)
    return {
        "device": device,
        "compute_type": resolve_compute_type(device, config.DEFAULT_COMPUTE_TYPE),
        "cuda_devices": cuda_device_count(),
        "default_model": config.DEFAULT_MODEL,
        "models": config.MODEL_CATALOG,
        "languages": config.LANGUAGES,
        "samples": [{"name": path.name, "size_mb": round(path.stat().st_size / 1e6, 1)} for path in sample_files()],
        "max_upload_mb": config.MAX_UPLOAD_MB,
    }


@app.get("/api/llm")
def llm_status() -> dict:
    """Checked separately: an offline Ollama must not delay page load."""
    available, message = llm.availability()
    return {"available": available, "message": message}


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),  # noqa: B008 - FastAPI's dependency API
    model: str = Form(config.DEFAULT_MODEL),
    language: str = Form("auto"),
    task: str = Form("transcribe"),
    vad: bool = Form(True),
    words: bool = Form(False),
) -> dict:
    options = options_from(model, language, task, vad, words)

    suffix = Path(file.filename or "audio").suffix.lower()
    if suffix not in config.AUDIO_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type {suffix!r}. Use one of: {', '.join(sorted(config.AUDIO_EXTENSIONS))}")

    job_id = uuid.uuid4().hex[:12]
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    target = config.JOBS_DIR / f"{job_id}{suffix}"

    max_bytes = config.MAX_UPLOAD_MB * 1024 * 1024
    written = 0
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(413, f"File is larger than {config.MAX_UPLOAD_MB} MB.")
                handle.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    job = store.create(
        job_id=job_id,
        filename=Path(file.filename or target.name).name,
        audio_path=target,
        options=options,
        owned_file=True,
    )
    start_worker(job)
    return job.snapshot()


@app.post("/api/jobs/sample")
def create_sample_job(request: SampleRequest) -> dict:
    options = options_from(request.model, request.language, request.task, request.vad, request.words)
    name = Path(request.name).name  # never trust a path from the browser
    sample = config.SAMPLES_DIR / name
    if sample not in sample_files():
        raise HTTPException(404, f"Sample {name!r} not found.")

    job = store.create(filename=sample.name, audio_path=sample, options=options)
    start_worker(job)
    return job.snapshot()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return get_job_or_404(job_id).snapshot()


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    job = get_job_or_404(job_id)
    with job.lock:
        if job.status in ("loading", "running"):
            raise HTTPException(409, "The job is still running.")
    store.delete(job_id)
    if job.owned_file:
        job.audio_path.unlink(missing_ok=True)
    return {"deleted": job_id}


@app.post("/api/jobs/{job_id}/summarize")
def summarize_job(job_id: str, request: SummaryRequest) -> dict:
    job = get_job_or_404(job_id)
    with job.lock:
        text = job.text
        if job.status != "done" or not text:
            raise HTTPException(409, "Wait until the transcription is finished.")
    try:
        summary = llm.summarize(text, focus=request.focus or None)
    except llm.LLMUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    with job.lock:
        job.summary = summary
    return {"summary": summary}


@app.get("/api/jobs/{job_id}/download/{fmt}")
def download(job_id: str, fmt: str) -> Response:
    job = get_job_or_404(job_id)
    if fmt not in formats.FORMATTERS:
        raise HTTPException(404, f"Unknown format {fmt!r}")
    with job.lock:
        if job.status != "done":
            raise HTTPException(409, "The transcription is not finished.")
        elapsed = (
            job.finished_at - job.started_at
            if job.started_at is not None and job.finished_at is not None
            else 0.0
        )
        transcription = Transcription(
            text=job.text,
            segments=list(job.segments),
            language=job.language,
            language_probability=job.language_probability,
            duration=job.duration,
            elapsed=elapsed,
            model=job.options.model,
            device=job.device,
            compute_type=job.compute_type,
            task=job.options.task,
        )
    media_types = {
        "txt": "text/plain; charset=utf-8",
        "srt": "application/x-subrip; charset=utf-8",
        "vtt": "text/vtt; charset=utf-8",
        "json": "application/json; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
    }
    stem = "".join(
        character for character in Path(job.filename).stem if character.isalnum() or character in "-_ "
    ).strip() or "transcript"
    headers = {"Content-Disposition": f'attachment; filename="{stem}.{fmt}"'}
    return Response(
        content=formats.render(transcription, fmt),
        media_type=media_types[fmt],
        headers=headers,
    )


# Serve the single-page client last so /api/* keeps priority.
app.mount("/", StaticFiles(directory=str(config.PUBLIC_DIR), html=True), name="ui")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Whisper Lab web UI")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    args = parser.parse_args(argv)

    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Whisper Lab -> http://{args.host}:{args.port}")
    print(f"Device: {resolve_device(config.DEFAULT_DEVICE)}  |  models: {config.MODELS_DIR}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
