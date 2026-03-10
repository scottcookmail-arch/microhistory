"""Background job manager for pipeline execution."""

from __future__ import annotations

import datetime as _dt
import os
import threading
import uuid
from pathlib import Path
from queue import Empty, Queue
from typing import Optional

from dotenv import load_dotenv

from microhistory.models import PipelineConfig
from microhistory.web.schemas import JobRequest, JobSummary, StepInfo

# ---------------------------------------------------------------------------
# Lightweight console proxy – captures ``console.rule()`` / ``console.print()``
# calls inside the pipeline and converts them into progress events.
# ---------------------------------------------------------------------------

class _ConsoleProxy:
    """Drop-in replacement for ``rich.console.Console`` that pushes
    progress events to a queue instead of printing to stdout."""

    def __init__(self, queue: Queue) -> None:
        self._q = queue

    # The pipeline calls console.rule("[bold blue]1. Topic Research") etc.
    def rule(self, text: str = "", **_kw) -> None:  # noqa: ARG002
        clean = _strip_rich(text)
        self._q.put({"type": "step", "name": clean})

    def print(self, *args, **_kw) -> None:  # noqa: ARG002
        parts = [_strip_rich(str(a)) for a in args]
        msg = " ".join(parts)
        if msg.strip():
            self._q.put({"type": "log", "message": msg.strip()})

    # Panel is passed as an object, not a string
    def __call__(self, *args, **kwargs):  # noqa: ARG002
        pass


def _strip_rich(text: str) -> str:
    """Remove Rich markup tags like [bold blue]...[/]."""
    import re
    return re.sub(r"\[/?[^\]]*\]", "", text).strip()


# ---------------------------------------------------------------------------
# Job dataclass
# ---------------------------------------------------------------------------

class Job:
    """Represents a single pipeline run."""

    def __init__(self, job_id: str, request: JobRequest) -> None:
        self.job_id = job_id
        self.topic = request.topic
        self.mode = request.mode
        self.video_backend = request.video_backend
        self.daily_count = request.daily_count
        self.target_length = request.target_length
        self.status = "queued"
        self.created = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        self.steps: list[StepInfo] = []
        self.output_dir: Optional[str] = None
        self.error: Optional[str] = None
        self.progress_queue: Queue = Queue()
        self.cancel_event = threading.Event()

    def to_summary(self) -> JobSummary:
        return JobSummary(
            job_id=self.job_id,
            topic=self.topic,
            mode=self.mode,
            status=self.status,
            created=self.created,
            steps=list(self.steps),
            output_dir=self.output_dir,
            error=self.error,
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class JobManager:
    """In-memory job store.  Runs one pipeline at a time in a background thread."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    # -- public API ----------------------------------------------------------

    def submit(self, request: JobRequest) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id, request)
        with self._lock:
            self._jobs[job_id] = job
        t = threading.Thread(target=self._run, args=(job,), daemon=True)
        t.start()
        return job_id

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[JobSummary]:
        return [j.to_summary() for j in reversed(list(self._jobs.values()))]

    # -- runner --------------------------------------------------------------

    def _run(self, job: Job) -> None:
        load_dotenv()
        job.status = "running"
        proxy = _ConsoleProxy(job.progress_queue)

        try:
            if job.mode == "shorts":
                self._run_shorts(job, proxy)
            else:
                self._run_longform(job, proxy)
            job.status = "completed"
            job.progress_queue.put({"type": "done", "status": "completed"})
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.progress_queue.put({"type": "done", "status": "failed", "error": str(exc)})

    def _run_shorts(self, job: Job, proxy: _ConsoleProxy) -> None:
        import microhistory.shorts_pipeline as sp

        # Monkeypatch the module-level console
        original = sp.console
        sp.console = proxy  # type: ignore[assignment]
        try:
            config = PipelineConfig(
                topic=job.topic,
                shorts_mode=True,
                daily_count=job.daily_count,
                output_dir=Path("output"),
                auto=True,
                render=True,
            )
            sp.run_shorts_pipeline(config, video_backend=job.video_backend)
            job.output_dir = str(config.output_dir / "shorts")
        finally:
            sp.console = original

    def _run_longform(self, job: Job, proxy: _ConsoleProxy) -> None:
        import microhistory.main as mm

        original = mm.console
        mm.console = proxy  # type: ignore[assignment]
        try:
            from microhistory.main import _parse_length

            config = PipelineConfig(
                topic=job.topic,
                target_length_sec=_parse_length(job.target_length),
                output_dir=Path("output"),
                auto=True,
                render=True,
            )
            result_dir = mm.run_pipeline(config)
            job.output_dir = str(result_dir)
        finally:
            mm.console = original


# Singleton
manager = JobManager()
