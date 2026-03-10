"""Request / response schemas for the web API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class JobRequest(BaseModel):
    """Payload for POST /api/jobs."""

    topic: str = Field(default="auto", description="Topic or 'auto' for discovery")
    mode: str = Field(default="shorts", description="'shorts' or 'longform'")
    video_backend: str = Field(default="gemini_image", description="runway / veo3 / gemini_image")
    daily_count: int = Field(default=1, ge=1, le=10)
    target_length: str = Field(default="9min", description="Target length for longform mode")


class StepInfo(BaseModel):
    name: str
    status: str = "pending"  # pending / running / completed / failed
    detail: str = ""


class JobSummary(BaseModel):
    job_id: str
    topic: str
    mode: str
    status: str  # queued / running / completed / failed
    created: str = ""
    steps: list[StepInfo] = Field(default_factory=list)
    output_dir: Optional[str] = None
    error: Optional[str] = None


class FileInfo(BaseModel):
    name: str
    path: str
    size: int
    size_display: str = ""


class ApiKeyUpdate(BaseModel):
    GOOGLE_API_KEY: Optional[str] = None
    ELEVENLABS_API_KEY: Optional[str] = None
    RUNWAY_API_KEY: Optional[str] = None
    ELEVENLABS_VOICE_ID: Optional[str] = None


class ApiKeyStatus(BaseModel):
    GOOGLE_API_KEY: str = "not set"
    ELEVENLABS_API_KEY: str = "not set"
    RUNWAY_API_KEY: str = "not set"
    ELEVENLABS_VOICE_ID: str = "not set"
