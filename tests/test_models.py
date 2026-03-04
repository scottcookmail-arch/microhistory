"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from microhistory.models import (
    AspectRatio,
    CalendarEntry,
    EpisodeMetadata,
    FactItem,
    License,
    PipelineConfig,
    ResearchResult,
    Script,
    ScriptSegment,
    ShotPrompt,
    ShotSpec,
    SourceAsset,
    Storyboard,
    TimelineRow,
    VideoType,
)


class TestSourceAsset:
    def test_create_valid(self):
        asset = SourceAsset(
            asset_id="abc123",
            url="https://example.com/image.jpg",
            title="Test Image",
        )
        assert asset.relevance_score == 0.0
        assert asset.license == License.UNKNOWN

    def test_relevance_score_bounds(self):
        with pytest.raises(ValidationError):
            SourceAsset(
                asset_id="x", url="https://x.com", title="X",
                relevance_score=1.5,
            )

    def test_commercial_safe_property(self):
        safe = SourceAsset(
            asset_id="x", url="https://x.com", title="X",
            license=License.CC0,
        )
        assert safe.is_commercial_safe

        unsafe = SourceAsset(
            asset_id="x", url="https://x.com", title="X",
            license=License.CC_BY_NC,
        )
        assert not unsafe.is_commercial_safe


class TestPipelineConfig:
    def test_defaults(self):
        cfg = PipelineConfig(topic="Rome")
        assert cfg.target_length_sec == 540
        assert cfg.num_shorts == 6
        assert cfg.download_assets is False
        assert cfg.render is False

    def test_custom(self):
        cfg = PipelineConfig(
            topic="Pompeii",
            target_length_sec=600,
            num_shorts=4,
            download_assets=True,
            render=True,
        )
        assert cfg.target_length_sec == 600
        assert cfg.num_shorts == 4


class TestShotPrompt:
    def test_defaults(self):
        p = ShotPrompt(shot_id="SHOT-001")
        assert p.aspect_ratio == AspectRatio.LANDSCAPE
        assert p.style == "cinematic documentary"


class TestTimelineRow:
    def test_create(self):
        row = TimelineRow(start_sec=0.0, end_sec=5.0, asset="test_asset")
        assert row.motion_type == "ken_burns"
        assert row.transition == "dissolve"
