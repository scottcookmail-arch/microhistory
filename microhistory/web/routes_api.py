"""REST API routes for jobs, settings, and file downloads."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from queue import Empty
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from dotenv import set_key

from microhistory.web.job_manager import manager
from microhistory.web.schemas import (
    ApiKeyStatus,
    ApiKeyUpdate,
    FileInfo,
    JobRequest,
)

router = APIRouter(prefix="/api")

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@router.post("/jobs")
async def create_job(req: JobRequest):
    job_id = manager.submit(req)
    return {"job_id": job_id}


@router.get("/jobs")
async def list_jobs():
    return manager.list_jobs()


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.to_summary()


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str):
    """Server-Sent Events stream of progress updates."""
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    async def stream() -> AsyncGenerator[str, None]:
        import asyncio

        while job.status in ("queued", "running"):
            try:
                event = job.progress_queue.get_nowait()
                yield f"data: {json.dumps(event)}\n\n"
            except Empty:
                yield ": keepalive\n\n"
                await asyncio.sleep(1)

        # Drain remaining events
        while not job.progress_queue.empty():
            try:
                event = job.progress_queue.get_nowait()
                yield f"data: {json.dumps(event)}\n\n"
            except Empty:
                break

        # Final done event
        done = {"type": "done", "status": job.status}
        if job.error:
            done["error"] = job.error
        yield f"data: {json.dumps(done)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# File downloads
# ---------------------------------------------------------------------------


def _format_size(size: int) -> str:
    if size > 1_000_000:
        return f"{size / 1_000_000:.1f} MB"
    if size > 1_000:
        return f"{size / 1_000:.1f} KB"
    return f"{size} B"


@router.get("/jobs/{job_id}/files")
async def list_files(job_id: str):
    job = manager.get(job_id)
    if not job or not job.output_dir:
        raise HTTPException(404, "Job not found or not yet complete")

    out = Path(job.output_dir)
    if not out.exists():
        return []

    files: list[FileInfo] = []
    for p in sorted(out.rglob("*")):
        if p.is_file():
            size = p.stat().st_size
            files.append(FileInfo(
                name=p.name,
                path=str(p.relative_to(out)),
                size=size,
                size_display=_format_size(size),
            ))
    return files


@router.get("/jobs/{job_id}/files/{file_path:path}")
async def download_file(job_id: str, file_path: str):
    job = manager.get(job_id)
    if not job or not job.output_dir:
        raise HTTPException(404, "Job not found")

    out = Path(job.output_dir)
    full = (out / file_path).resolve()

    # Path traversal protection
    if not full.is_relative_to(out.resolve()):
        raise HTTPException(403, "Access denied")
    if not full.is_file():
        raise HTTPException(404, "File not found")

    return FileResponse(full, filename=full.name)


@router.get("/jobs/{job_id}/zip")
async def download_zip(job_id: str):
    job = manager.get(job_id)
    if not job or not job.output_dir:
        raise HTTPException(404, "Job not found or not yet complete")

    out = Path(job.output_dir)
    if not out.exists():
        raise HTTPException(404, "Output directory not found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in out.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(out))
    buf.seek(0)

    filename = f"microhistory_{job_id}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

_KEY_NAMES = ["GOOGLE_API_KEY", "ELEVENLABS_API_KEY", "RUNWAY_API_KEY", "ELEVENLABS_VOICE_ID"]


def _mask(value: str) -> str:
    if not value:
        return "not set"
    if len(value) <= 8:
        return "****"
    return value[:4] + "..." + value[-4:]


@router.get("/settings")
async def get_settings():
    status = {}
    for k in _KEY_NAMES:
        val = os.environ.get(k, "")
        status[k] = _mask(val)
    return ApiKeyStatus(**status)


@router.put("/settings")
async def update_settings(keys: ApiKeyUpdate):
    # Ensure .env exists
    if not _ENV_PATH.exists():
        _ENV_PATH.touch()

    for key_name, value in keys.model_dump(exclude_none=True).items():
        if value is not None:
            set_key(str(_ENV_PATH), key_name, value)
            os.environ[key_name] = value

    return {"status": "ok"}
