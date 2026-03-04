"""Tests for output folder structure.

Verifies that the pipeline creates the expected directory layout.
Uses a mock HTTP client to avoid network calls.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from microhistory.models import (
    FactItem,
    License,
    PipelineConfig,
    ResearchResult,
    SourceAsset,
)


def _make_research(topic: str = "Test Topic") -> ResearchResult:
    """Create a minimal ResearchResult for testing."""
    return ResearchResult(
        topic=topic,
        summary="A test summary for the topic.",
        facts=[
            FactItem(
                claim=f"Fact {i}: something interesting happened in history that relates to this topic and has been documented.",
                source_urls=["https://en.wikipedia.org/wiki/Test"],
                confidence="medium",
            )
            for i in range(20)
        ],
        assets=[
            SourceAsset(
                asset_id=f"asset_{i:03d}",
                url=f"https://commons.wikimedia.org/wiki/File:test_{i}.jpg",
                title=f"Test Asset {i}",
                description="A test archival image",
                source_api="wikimedia_commons",
                license=License.PUBLIC_DOMAIN,
                attribution=f"Test attribution {i}",
                filetype="jpg",
            )
            for i in range(5)
        ],
    )


class TestFolderStructure:
    """Test that the pipeline creates the correct folder structure."""

    def test_full_output_structure(self, tmp_path: Path):
        """Run pipeline with mocked research and verify all expected files."""
        research = _make_research("Test Topic")

        # Patch at the source module since run_pipeline uses late imports
        with patch("microhistory.topic_research.research_topic", return_value=research):
            from microhistory.main import run_pipeline

            config = PipelineConfig(
                topic="Test Topic",
                target_length_sec=540,
                num_shorts=3,
                download_assets=False,
                render=False,
                output_dir=tmp_path,
            )
            output_dir = run_pipeline(config)

        # Check top-level files
        assert (output_dir / "sources.json").exists()
        assert (output_dir / "script.md").exists()
        assert (output_dir / "fact_check_report.md").exists()
        assert (output_dir / "storyboard.md").exists()
        assert (output_dir / "voiceover.txt").exists()
        assert (output_dir / "ATTRIBUTION.txt").exists()

        # Check AI generation directory
        ai_dir = output_dir / "ai_generation"
        assert (ai_dir / "shot_prompts.json").exists()
        assert (ai_dir / "veo3_prompts.md").exists()
        assert (ai_dir / "gemini_prompts.md").exists()
        assert (ai_dir / "seedance_prompts.md").exists()

        # Check edits directory
        edits_dir = output_dir / "edits"
        assert (edits_dir / "longform" / "timeline.csv").exists()
        assert (edits_dir / "longform" / "edit_instructions.md").exists()

        # Check shorts directories
        for i in range(1, 4):  # 3 shorts
            short_dir = edits_dir / "shorts" / f"short_{i:02d}"
            assert short_dir.exists(), f"Missing short_{i:02d} directory"
            assert (short_dir / "script.txt").exists()
            assert (short_dir / "captions.srt").exists()
            assert (short_dir / "timeline.csv").exists()

        # Check metadata directory
        meta_dir = output_dir / "metadata"
        assert (meta_dir / "title_options.txt").exists()
        assert (meta_dir / "description_short.txt").exists()
        assert (meta_dir / "description_long.txt").exists()
        assert (meta_dir / "tags.txt").exists()
        assert (meta_dir / "chapters.txt").exists()
        assert (meta_dir / "thumbnail_brief.txt").exists()

        # Check scheduling directory
        sched_dir = output_dir / "scheduling"
        assert (sched_dir / "schedule_recommendation.md").exists()
        assert (sched_dir / "upload_calendar.csv").exists()
        assert (sched_dir / "posting_checklist.md").exists()

    def test_sources_json_valid(self, tmp_path: Path):
        """Verify sources.json is valid JSON with expected structure."""
        research = _make_research()

        with patch("microhistory.topic_research.research_topic", return_value=research):
            from microhistory.main import run_pipeline

            config = PipelineConfig(
                topic="Test Topic",
                target_length_sec=300,
                num_shorts=2,
                output_dir=tmp_path,
            )
            output_dir = run_pipeline(config)

        sources_path = output_dir / "sources.json"
        data = json.loads(sources_path.read_text())
        assert "topic" in data
        assert "facts" in data
        assert "assets" in data
        assert isinstance(data["assets"], list)

    def test_slugified_directory_name(self, tmp_path: Path):
        """Verify topic is slugified for the directory name."""
        research = _make_research("Dyatlov Pass incident")

        with patch("microhistory.topic_research.research_topic", return_value=research):
            from microhistory.main import run_pipeline

            config = PipelineConfig(
                topic="Dyatlov Pass incident",
                output_dir=tmp_path,
            )
            output_dir = run_pipeline(config)

        assert output_dir.name == "dyatlov_pass_incident"
