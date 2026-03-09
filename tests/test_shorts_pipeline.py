"""Tests for the YouTube Shorts automation pipeline."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from microhistory.models import (
    FactItem,
    License,
    PipelineConfig,
    ResearchResult,
    ShortsSEO,
    ShortsScript,
    ShortsEpisode,
    ShortsVideoSpec,
    SourceAsset,
)


def _make_research(topic: str = "Dancing plague of 1518") -> ResearchResult:
    """Create a minimal ResearchResult for Shorts testing."""
    return ResearchResult(
        topic=topic,
        summary="In 1518, a strange mania seized the city of Strasbourg.",
        facts=[
            FactItem(
                claim=f"Fact {i}: In 1518, hundreds of people danced for days without rest in Strasbourg.",
                source_urls=["https://en.wikipedia.org/wiki/Dancing_plague_of_1518"],
                confidence="medium",
            )
            for i in range(10)
        ],
        assets=[
            SourceAsset(
                asset_id=f"asset_{i:03d}",
                url=f"https://commons.wikimedia.org/wiki/File:dance_{i}.jpg",
                title=f"Historical dance image {i}",
                description="A historical illustration",
                source_api="wikimedia_commons",
                license=License.PUBLIC_DOMAIN,
                attribution=f"Wikimedia Commons {i}",
                filetype="jpg",
            )
            for i in range(3)
        ],
    )


# ---------------------------------------------------------------------------
# Topic discovery tests
# ---------------------------------------------------------------------------

class TestStrangeEventDiscovery:
    """Test the strange event discovery system."""

    def test_discover_returns_events(self):
        from microhistory.topic_research import discover_strange_events

        with patch("microhistory.topic_research._fetch_category_members", return_value=[]):
            events = discover_strange_events(count=3)

        assert len(events) <= 3
        for event in events:
            assert "topic" in event
            assert "date" in event
            assert "hook" in event

    def test_discover_excludes_topics(self):
        from microhistory.topic_research import discover_strange_events

        with patch("microhistory.topic_research._fetch_category_members", return_value=[]):
            events = discover_strange_events(
                count=5,
                exclude_topics=["Dancing plague of 1518"],
            )

        topics = [e["topic"] for e in events]
        assert "Dancing plague of 1518" not in topics

    def test_seed_events_have_hooks(self):
        from microhistory.topic_research import _SEED_STRANGE_EVENTS

        for event in _SEED_STRANGE_EVENTS:
            assert event["hook"], f"Missing hook for {event['topic']}"
            assert event["topic"], "Missing topic"


# ---------------------------------------------------------------------------
# Shorts scriptwriter tests
# ---------------------------------------------------------------------------

class TestShortsScriptwriter:
    """Test the 120-word Shorts script generator."""

    def test_generate_script_structure(self):
        from microhistory.shorts_scriptwriter import generate_shorts_script

        research = _make_research()
        script = generate_shorts_script(research, seed_hook="An entire city danced itself to death.")

        assert isinstance(script, ShortsScript)
        assert script.topic == "Dancing plague of 1518"
        assert script.hook != ""
        assert script.build != ""
        assert script.reveal != ""
        assert script.total_word_count > 0

    def test_script_word_count_target(self):
        from microhistory.shorts_scriptwriter import generate_shorts_script

        research = _make_research()
        script = generate_shorts_script(research)

        # Should be roughly 120 words (allow range for padding/trimming)
        assert 50 <= script.total_word_count <= 200

    def test_script_to_plain_text(self):
        from microhistory.shorts_scriptwriter import generate_shorts_script, script_to_plain_text

        research = _make_research()
        script = generate_shorts_script(research)
        text = script_to_plain_text(script)

        assert isinstance(text, str)
        assert len(text) > 50
        # Should contain words from all three sections
        assert script.hook.split()[0] in text

    def test_write_shorts_script(self, tmp_path: Path):
        from microhistory.shorts_scriptwriter import generate_shorts_script, write_shorts_script

        research = _make_research()
        script = generate_shorts_script(research)
        path = tmp_path / "script.txt"
        write_shorts_script(script, path)

        assert path.exists()
        content = path.read_text()
        assert "HOOK" in content
        assert "BUILD" in content
        assert "REVEAL" in content


# ---------------------------------------------------------------------------
# Shorts SEO tests
# ---------------------------------------------------------------------------

class TestShortsSEO:
    """Test the Shorts SEO metadata generator."""

    def test_generate_seo(self):
        from microhistory.metadata_generator import generate_shorts_seo

        seo = generate_shorts_seo("Dancing plague of 1518", "An entire city danced itself to death.")

        assert isinstance(seo, ShortsSEO)
        assert len(seo.title) > 10
        assert len(seo.title) <= 100  # Shorts title limit
        assert "#history" in seo.description.lower() or "#shorts" in seo.description.lower()
        assert len(seo.hashtags) > 0
        assert len(seo.tags) > 0

    def test_seo_has_topic_hashtags(self):
        from microhistory.metadata_generator import generate_shorts_seo

        seo = generate_shorts_seo("Tunguska event")
        hashtag_text = " ".join(seo.hashtags).lower()
        # Should have at least one topic-related hashtag
        assert "#tunguska" in hashtag_text or "#event" in hashtag_text

    def test_write_seo(self, tmp_path: Path):
        from microhistory.metadata_generator import generate_shorts_seo, write_shorts_seo

        seo = generate_shorts_seo("Test Topic")
        path = tmp_path / "seo.json"
        write_shorts_seo(seo, path)

        assert path.exists()
        data = json.loads(path.read_text())
        assert "title" in data
        assert "hashtags" in data


# ---------------------------------------------------------------------------
# Animated subtitles tests
# ---------------------------------------------------------------------------

class TestAnimatedSubtitles:
    """Test the animated SRT generation for Shorts."""

    def test_generate_animated_srt(self):
        from microhistory.editor_ffmpeg import generate_animated_srt

        text = "This is a test sentence for subtitle generation with multiple words."
        srt = generate_animated_srt(text, max_duration_sec=10.0, words_per_caption=3)

        assert len(srt) > 0
        lines = srt.strip().split("\n")
        # SRT format: number, timecode, text, blank line
        assert lines[0] == "1"
        assert "-->" in lines[1]
        # Should be uppercase (retention style)
        assert lines[2] == lines[2].upper()

    def test_srt_covers_all_words(self):
        from microhistory.editor_ffmpeg import generate_animated_srt

        text = "one two three four five six seven eight nine ten"
        srt = generate_animated_srt(text, max_duration_sec=10.0, words_per_caption=2)

        # All words should appear in the SRT
        for word in text.split():
            assert word.upper() in srt.upper()

    def test_empty_text_returns_empty(self):
        from microhistory.editor_ffmpeg import generate_animated_srt

        assert generate_animated_srt("") == ""


# ---------------------------------------------------------------------------
# Visual clip prompt tests
# ---------------------------------------------------------------------------

class TestClipPrompts:
    """Test video clip prompt generation."""

    def test_build_clip_prompts(self):
        from microhistory.visual_generator import build_shorts_clip_prompts

        prompts = build_shorts_clip_prompts(
            "Dancing plague of 1518",
            "People danced in the streets of Strasbourg without stopping.",
            num_clips=5,
            target_duration=40.0,
        )

        assert len(prompts) == 5
        for p in prompts:
            assert "prompt" in p
            assert "camera_motion" in p
            assert "duration_sec" in p
            assert "9:16" in p["prompt"]  # vertical framing
            assert float(p["duration_sec"]) > 0

    def test_clip_durations_sum_to_target(self):
        from microhistory.visual_generator import build_shorts_clip_prompts

        prompts = build_shorts_clip_prompts("Test", "Test text.", num_clips=5, target_duration=40.0)
        total = sum(float(p["duration_sec"]) for p in prompts)
        assert abs(total - 40.0) < 0.5


# ---------------------------------------------------------------------------
# Daily schedule tests
# ---------------------------------------------------------------------------

class TestDailyShortsSchedule:
    """Test the daily Shorts scheduling."""

    def test_generates_entries(self):
        from microhistory.scheduler import generate_daily_shorts_schedule

        schedule = generate_daily_shorts_schedule(
            topics=["Topic A", "Topic B"],
            days=7,
            posts_per_day=1,
        )

        assert len(schedule.calendar) == 7
        for entry in schedule.calendar:
            assert entry.video_type.value == "Short"

    def test_multi_post_per_day(self):
        from microhistory.scheduler import generate_daily_shorts_schedule

        schedule = generate_daily_shorts_schedule(
            topics=["Topic A"],
            days=3,
            posts_per_day=2,
        )

        assert len(schedule.calendar) == 6

    def test_recommendation_not_empty(self):
        from microhistory.scheduler import generate_daily_shorts_schedule

        schedule = generate_daily_shorts_schedule(topics=["Test"], days=7)
        assert len(schedule.recommendation_md) > 100


# ---------------------------------------------------------------------------
# Shorts models tests
# ---------------------------------------------------------------------------

class TestShortsModels:
    """Test the new Shorts-specific Pydantic models."""

    def test_shorts_script(self):
        script = ShortsScript(
            topic="Test",
            hook="This is the hook.",
            build="This is the build section.",
            reveal="This is the reveal.",
            total_word_count=15,
        )
        assert script.target_duration_sec == 40

    def test_shorts_video_spec(self):
        spec = ShortsVideoSpec(clip_number=1, duration_sec=8.0, prompt="Test prompt")
        assert spec.camera_motion == "slow_push"

    def test_shorts_seo_model(self):
        seo = ShortsSEO(
            title="Test Title",
            description="Test desc",
            hashtags=["#test", "#history"],
            tags=["test", "history"],
        )
        assert len(seo.hashtags) == 2

    def test_shorts_episode(self):
        ep = ShortsEpisode(topic="Test Event")
        assert ep.script is None
        assert ep.clips == []
        assert ep.final_video_path is None

    def test_pipeline_config_shorts_mode(self):
        cfg = PipelineConfig(topic="Test", shorts_mode=True, daily_count=3)
        assert cfg.shorts_mode is True
        assert cfg.daily_count == 3


# ---------------------------------------------------------------------------
# Full Shorts pipeline integration test
# ---------------------------------------------------------------------------

class TestShortsPipelineIntegration:
    """Integration test for the full Shorts pipeline (mocked APIs)."""

    def test_shorts_pipeline_produces_outputs(self, tmp_path: Path):
        research = _make_research()

        with patch("microhistory.topic_research.research_short_topic", return_value=research), \
             patch("microhistory.topic_research.discover_strange_events", return_value=[
                 {"topic": "Dancing plague of 1518", "date": "1518", "hook": "An entire city danced."}
             ]), \
             patch("microhistory.tts_generator._get_api_key", side_effect=RuntimeError("No key")), \
             patch("microhistory.visual_generator.generate_shorts_clips", return_value=[]):

            from microhistory.shorts_pipeline import run_shorts_pipeline

            config = PipelineConfig(
                topic="auto",
                shorts_mode=True,
                daily_count=1,
                output_dir=tmp_path,
            )
            episodes = run_shorts_pipeline(config, video_backend="gemini_image")

        assert len(episodes) == 1
        ep = episodes[0]
        assert ep.topic == "Dancing plague of 1518"
        assert ep.script is not None
        assert ep.script.total_word_count > 0
        assert ep.seo is not None
        assert ep.seo.title != ""

        # Check files were created
        shorts_dir = tmp_path / "shorts"
        assert shorts_dir.exists()

        # Check scheduling files
        assert (shorts_dir / "scheduling" / "upload_calendar.csv").exists()
