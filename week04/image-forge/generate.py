"""image-forge - generic batch picture generation driven by settings.yaml.

Define one or more tasks in `settings.yaml`, each with a prompt template and a
list of subjects. The settings file also holds every quality and appearance
knob: model, quality tier, size, background, output format, keying,
normalization, resize, padding and the global art-direction brief.

Examples (from this directory):

    python generate.py --list                     # show configured tasks
    python generate.py --dry-run --limit 3        # show prompts, no API calls
    python generate.py --task postcards           # one task, full scope
    python generate.py --task inventory-icons     # one task, full scope
    python generate.py --id lighthouse-storm      # one subject
    python generate.py --task postcards --limit 2 # draft only two images
    python generate.py --force                    # regenerate existing files

Outputs land under `output/<task>/<stem>.<format>`. Reruns skip files that
already exist unless `--force` is passed.
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from config import (
    ConfigError,
    Settings,
    load_settings,
    resolve_appearance,
)
from postprocess import process_image
from prompts import Subject, build_prompt, collect_subjects

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "settings.yaml"
SUPPORTED_EXTENSIONS = ("png", "webp", "jpeg", "jpg")


@dataclass
class Job:
    """One planned image."""

    task: str
    subject: Subject
    prompt: str
    appearance: dict[str, Any]
    out_path: Path
    base_path: Path | None = None


def output_root(settings: Settings) -> Path:
    directory = Path(settings.runtime["output_dir"])
    if not directory.is_absolute():
        directory = settings.base_dir / directory
    return directory.resolve()


def task_output_dir(settings: Settings, task_name: str) -> Path:
    root = output_root(settings)
    subfolder = settings.tasks[task_name].get("output") or task_name
    target = (root / subfolder).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ConfigError(
            f"tasks.{task_name}.output: must stay inside output_dir ({root})"
        ) from exc
    return target


def _extension(appearance: dict[str, Any]) -> str:
    fmt = str(appearance["format"]).lower()
    return "jpg" if fmt == "jpg" else fmt


def build_jobs(
    settings: Settings,
    task_names: list[str],
    only_id: str | None,
    force: bool,
) -> list[Job]:
    """Plan every image for the selected tasks."""
    jobs: list[Job] = []
    matched_any = False

    for task_name in task_names:
        task = settings.tasks[task_name]
        subjects = collect_subjects(settings, task_name)
        if only_id:
            subjects = [
                subject
                for subject in subjects
                if only_id in (subject.raw, subject.stem)
            ]
            if not subjects:
                continue
            matched_any = True

        out_dir = task_output_dir(settings, task_name)
        planned: list[Job] = []
        by_stem: dict[str, Job] = {}

        for subject in subjects:
            where = f"tasks.{task_name}.subjects[{subject.raw!r}]"
            appearance = resolve_appearance(
                settings, task, subject.appearance, where=where
            )
            prompt = build_prompt(settings, task_name, subject)
            out_path = out_dir / f"{subject.stem}.{_extension(appearance)}"
            job = Job(task_name, subject, prompt, appearance, out_path)
            planned.append(job)
            by_stem[subject.stem] = job

        for job in planned:
            base = job.subject.base
            if not base:
                continue
            if job.subject.base_is_file:
                reference = Path(base)
                if not reference.is_absolute():
                    reference = settings.base_dir / reference
                reference = reference.resolve()
                if not reference.exists():
                    raise ConfigError(
                        f"tasks.{task_name}: reference image for "
                        f"{job.subject.raw!r} not found: {reference}"
                    )
                job.base_path = reference
                continue
            target = by_stem.get(base)
            if target is not None:
                job.base_path = target.out_path
                continue
            # A base from an earlier run: look for any supported extension.
            for extension in SUPPORTED_EXTENSIONS:
                candidate = out_dir / f"{base}.{extension}"
                if candidate.exists():
                    job.base_path = candidate
                    break
            if job.base_path is None:
                raise ConfigError(
                    f"tasks.{task_name}: base {base!r} for {job.subject.raw!r} "
                    f"does not exist in {out_dir}. Generate it first or add it "
                    f"to this task's subjects."
                )

        keep_existing = settings.runtime["skip_existing"] and not force
        jobs.extend(
            job
            for job in planned
            if not (keep_existing and job.out_path.exists())
        )

    if only_id and not matched_any:
        raise ConfigError(f"no subject matches --id {only_id!r}")
    return jobs


def select_tasks(settings: Settings, requested: list[str] | None) -> list[str]:
    if not requested:
        return list(settings.tasks)
    ordered = list(dict.fromkeys(requested))
    unknown = [name for name in ordered if name not in settings.tasks]
    if unknown:
        raise ConfigError(
            f"unknown task(s): {', '.join(unknown)}; "
            f"available: {', '.join(settings.tasks)}"
        )
    return ordered


def list_tasks(settings: Settings, task_names: list[str]) -> None:
    print(f"Tasks in {settings.path.name}")
    for task_name in task_names:
        task = settings.tasks[task_name]
        subjects = collect_subjects(settings, task_name)
        appearance = resolve_appearance(settings, task, where=f"tasks.{task_name}")
        folder = task.get("output") or task_name
        description = (task.get("description") or "").strip()
        print(f"\n  {task_name}  ({len(subjects)} subject(s))")
        if description:
            print(f"    {description}")
        print(
            f"    folder={folder}  quality={appearance['quality']}  "
            f"size={appearance['size']}  background={appearance['background']}  "
            f"format={appearance['format']}"
        )
        changes = []
        if appearance["key_out"]["enabled"]:
            changes.append(f"key_out={appearance['key_out']['mode']}")
        if appearance["normalize"]["enabled"]:
            changes.append(f"normalize={appearance['normalize']['canvas']}px")
        if appearance["resize"]["enabled"]:
            changes.append(
                f"resize={appearance['resize']['width']}x{appearance['resize']['height']}"
            )
        if appearance["pad"]["enabled"]:
            changes.append("pad")
        if changes:
            print(f"    post: {', '.join(changes)}")


def _preview(prompt: str, limit: int = 6) -> None:
    lines = prompt.splitlines()
    for line in lines[:limit]:
        print(f"      {line}")
    if len(lines) > limit:
        print("      ...")


def generate_one(
    client: OpenAI | None,
    job: Job,
    *,
    dry_run: bool,
    retries: int,
    backoff: float,
) -> tuple[str, Job]:
    """Generate, post-process, and write one image."""
    appearance = job.appearance
    label = f"{job.task}/{job.out_path.name}"

    if dry_run:
        source = f"  base={job.base_path.name}" if job.base_path else ""
        print(
            f"[DRY] {label}  q={appearance['quality']}  size={appearance['size']}  "
            f"bg={appearance['background']}  fmt={appearance['format']}{source}"
        )
        _preview(job.prompt)
        return ("dry", job)

    if job.base_path is not None and not job.base_path.exists():
        print(f"[FAIL] {label}: base image missing: {job.base_path}", file=sys.stderr)
        return ("fail", job)

    assert client is not None
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            common = {
                "model": appearance["model"],
                "prompt": job.prompt,
                "size": appearance["size"],
                "quality": appearance["quality"],
                "background": appearance["background"],
                "n": 1,
            }
            if job.base_path is not None:
                with job.base_path.open("rb") as reference:
                    response = client.images.edit(image=reference, **common)
            else:
                response = client.images.generate(**common)

            b64 = response.data[0].b64_json
            if not b64:
                raise RuntimeError(
                    "image response contained no b64_json; "
                    "check that the configured model returns base64"
                )

            data = process_image(base64.b64decode(b64), appearance)
            job.out_path.parent.mkdir(parents=True, exist_ok=True)
            job.out_path.write_bytes(data)
            print(f"[OK]   {label}  ({len(data) // 1024} KB, attempt {attempt})")
            return ("ok", job)

        except Exception as exc:  # retry is deliberately broad: transient wins
            last_error = exc
            if attempt < retries:
                wait = backoff * (2 ** attempt)
                print(
                    f"[WARN] {label}: {exc!r} - retry {attempt + 1}/{retries} "
                    f"in {wait:g}s",
                    file=sys.stderr,
                )
                time.sleep(wait)

    print(f"[FAIL] {label}: {last_error!r}", file=sys.stderr)
    return ("fail", job)


def execute(
    jobs: list[Job],
    client: OpenAI | None,
    *,
    dry_run: bool,
    concurrency: int,
    retries: int,
    backoff: float,
) -> list[tuple[str, Job]]:
    """Run base images first, then reference-edit jobs that depend on them."""
    results: list[tuple[str, Job]] = []
    phases = (
        [job for job in jobs if job.base_path is None],
        [job for job in jobs if job.base_path is not None],
    )
    for phase in phases:
        if not phase:
            continue
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = [
                pool.submit(
                    generate_one,
                    client,
                    job,
                    dry_run=dry_run,
                    retries=retries,
                    backoff=backoff,
                )
                for job in phase
            ]
            for future in as_completed(futures):
                results.append(future.result())
    return results


def _print_plan(jobs: list[Job]) -> None:
    active_tasks = list(dict.fromkeys(job.task for job in jobs))
    print(
        f"Planned: {len(jobs)} image(s) across {len(active_tasks)} task(s) "
        f"[{', '.join(active_tasks)}]"
    )
    for job in jobs:
        source = f"  (edit from {job.base_path.name})" if job.base_path else ""
        print(
            f"  - {job.task}/{job.out_path.name}  "
            f"q={job.appearance['quality']}  size={job.appearance['size']}  "
            f"fmt={job.appearance['format']}{source}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate pictures in batches from settings.yaml."
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Settings file (default: settings.yaml next to generate.py).",
    )
    parser.add_argument(
        "--task",
        action="append",
        help="Task to run (repeatable). Default: every task in the settings file.",
    )
    parser.add_argument(
        "--id",
        dest="only_id",
        help="Generate one subject by its raw name or filename stem.",
    )
    parser.add_argument(
        "--limit", type=int, help="Maximum number of images to generate this run."
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        help="Parallel API calls (default: runtime.concurrency in settings).",
    )
    parser.add_argument(
        "--force", action="store_true", help="Regenerate existing files."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the plan and prompts, no API calls."
    )
    parser.add_argument(
        "--list", action="store_true", help="List tasks and exit."
    )
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.concurrency is not None and args.concurrency < 1:
        parser.error("--concurrency must be at least 1")

    try:
        settings = load_settings(args.config)
        task_names = select_tasks(settings, args.task)

        if args.list:
            list_tasks(settings, task_names)
            return 0

        # A custom settings file may live next to its own .env.
        load_dotenv(HERE / ".env")
        if settings.base_dir != HERE:
            load_dotenv(settings.base_dir / ".env")

        jobs = build_jobs(settings, task_names, args.only_id, args.force)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.limit is not None:
        jobs = jobs[: args.limit]

    if not jobs:
        print("Nothing to do. Every planned image already exists; use --force to redo.")
        return 0

    if not args.dry_run and not os.environ.get("OPENAI_API_KEY"):
        print(
            "ERROR: OPENAI_API_KEY is not set. Copy .env.example to .env and "
            "fill it in, or export the variable.",
            file=sys.stderr,
        )
        return 2

    concurrency = args.concurrency or settings.runtime["concurrency"]
    retries = settings.runtime["retries"]
    backoff = settings.runtime["retry_backoff_seconds"]

    _print_plan(jobs)
    print(
        f"Concurrency={concurrency}  retries={retries}  "
        f"force={args.force}  dry_run={args.dry_run}\n"
    )

    client = None if args.dry_run else OpenAI()
    results = execute(
        jobs,
        client,
        dry_run=args.dry_run,
        concurrency=concurrency,
        retries=retries,
        backoff=backoff,
    )

    ok = sum(1 for status, _ in results if status == "ok")
    failed = sum(1 for status, _ in results if status == "fail")
    dry = sum(1 for status, _ in results if status == "dry")
    print(f"\nDone. ok={ok}  fail={failed}  dry={dry}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
