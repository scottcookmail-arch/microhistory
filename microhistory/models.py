"""Pydantic models used across the pipeline."""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

class AssetType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    MAP = "map"


class License(str, enum.Enum):
    PUBLIC_DOMAIN = "public_domain"
    CC0 = "CC0"
    CC_BY = "CC-BY"
    CC_BY_SA = "CC-BY-SA"
    CC_BY_NC = "CC-BY-NC"
    US_GOV = "us_government_work"
    UNKNOWN = "unknown"


# Licenses that are safe for commercial YouTube use
COMMERCIAL_SAFE_LICENSES = {
    License.PUBLIC_DOMAIN,
    License.CC0,
    License.CC_BY,
    License.CC_BY_SA,
    License.US_GOV,
}


class AspectRatio(str, enum.Enum):
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"


class VideoType(str, enum.Enum):
    LONG = "Long"
    SHORT = "Short"


# ---------------------------------------------------------------------------
# Source / asset models
# ---------------------------------------------------------------------------

class SourceAsset(BaseModel):
    """A single licensed media asset found during research."""

    asset_id: str
    url: str
    title: str
    description: str = ""
    source_api: str = ""  # e.g. "wikimedia", "loc", "internet_archive"
    license: License = License.UNKNOWN
    attribution: str = ""
    filetype: str = ""  # e.g. "jpg", "mp4", "pdf"
    asset_type: AssetType = AssetType.IMAGE
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    local_path: Optional[str] = None
    download_url: Optional[str] = None

    @property
    def is_commercial_safe(self) -> bool:
        return self.license in COMMERCIAL_SAFE_LICENSES


class FactItem(BaseModel):
    """A single factual claim with supporting sources."""

    claim: str
    source_urls: list[str] = Field(default_factory=list)
    confidence: str = "medium"  # low / medium / high


class ResearchResult(BaseModel):
    """Output of the topic research phase."""

    topic: str
    summary: str = ""
    facts: list[FactItem] = Field(default_factory=list)
    assets: list[SourceAsset] = Field(default_factory=list)
    timeline: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Script models
# ---------------------------------------------------------------------------

class ScriptCue(BaseModel):
    """An inline cue inside the narration script."""

    cue_type: str  # VISUAL, SFX, ON-SCREEN TEXT, SHOT-ID
    content: str


class ScriptSegment(BaseModel):
    """A segment of the narration script."""

    section: str  # hook, scene_setting, escalation, turning_point, aftermath, theories, ending
    narration: str
    cues: list[ScriptCue] = Field(default_factory=list)
    approx_duration_sec: int = 0


class Script(BaseModel):
    """Full episode script."""

    topic: str
    target_length_sec: int = 540
    segments: list[ScriptSegment] = Field(default_factory=list)
    total_word_count: int = 0


# ---------------------------------------------------------------------------
# Storyboard / shot models
# ---------------------------------------------------------------------------

class ShotSpec(BaseModel):
    """A single shot in the storyboard."""

    shot_id: str
    timecode_start: str = ""  # MM:SS
    timecode_end: str = ""
    duration_sec: float = 5.0
    description: str = ""
    source_type: str = "ai_generated"  # "archival" or "ai_generated"
    asset_id: Optional[str] = None  # reference to SourceAsset.asset_id
    narration_excerpt: str = ""
    camera_motion: str = "slow_push"
    text_overlay: str = ""


class Storyboard(BaseModel):
    """Full episode storyboard."""

    topic: str
    shots: list[ShotSpec] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# AI prompt models
# ---------------------------------------------------------------------------

class ShotPrompt(BaseModel):
    """Unified AI shot prompt spec."""

    shot_id: str
    duration_sec: float = 5.0
    aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE
    style: str = "cinematic documentary"
    camera_motion: str = "slow_push"
    environment: str = ""
    subject: str = ""
    era_props: str = ""
    text_overlays: str = ""
    negative_prompts: str = "modern logos, copyrighted characters, text watermarks, low quality"
    continuity_notes: str = ""


# ---------------------------------------------------------------------------
# Editor / timeline models
# ---------------------------------------------------------------------------

class TimelineRow(BaseModel):
    """One row in a timeline CSV."""

    start_sec: float
    end_sec: float
    asset: str
    motion_type: str = "ken_burns"
    text_overlay: str = ""
    transition: str = "dissolve"


class ShortPack(BaseModel):
    """A single Short's content pack."""

    short_number: int
    title: str = ""
    script_text: str = ""
    captions_srt: str = ""
    timeline: list[TimelineRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Metadata models
# ---------------------------------------------------------------------------

class EpisodeMetadata(BaseModel):
    """YouTube metadata for the episode."""

    title_options: list[str] = Field(default_factory=list)
    description_short: str = ""
    description_long: str = ""
    tags: list[str] = Field(default_factory=list)
    chapters: list[str] = Field(default_factory=list)
    thumbnail_briefs: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Schedule models
# ---------------------------------------------------------------------------

class CalendarEntry(BaseModel):
    """One row in the upload calendar."""

    date: str
    time: str
    video_type: VideoType
    topic: str
    title_draft: str = ""
    cta: str = ""
    asset_notes: str = ""


class Schedule(BaseModel):
    """Scheduling output."""

    recommendation_md: str = ""
    calendar: list[CalendarEntry] = Field(default_factory=list)
    checklist_md: str = ""


# ---------------------------------------------------------------------------
# Pipeline config
# ---------------------------------------------------------------------------

class PipelineConfig(BaseModel):
    """Top-level configuration for a pipeline run."""

    topic: str
    target_length_sec: int = 540  # 9 minutes default
    num_shorts: int = 6
    download_assets: bool = False
    render: bool = False
    output_dir: Path = Path("output")
    assets_dir: Optional[Path] = None  # optional folder of paid/stock assets
    auto: bool = False  # full automation: generate visuals + TTS + render
