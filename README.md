# MicroHistory

A local production pipeline for faceless YouTube history channels. Given a topic keyword, it produces a complete "episode pack" with script, storyboard, AI generation prompts, edit timelines, metadata, and scheduling — all using properly licensed sources.

## Features

- **Topic Research** – Wikipedia, Wikimedia Commons, Library of Congress, and Internet Archive APIs
- **Original Scriptwriting** – Cinematic 8–10 minute narration with visual/SFX cues every 10–20 seconds
- **Storyboard Generation** – Timestamped shot list matching archival assets or AI-generated visuals
- **AI Prompt Packs** – Ready-to-use prompts for Veo3, Gemini, and Seedance with a continuity bible
- **Voiceover Packaging** – Clean narration text, SSML with pacing tags, pronunciation guide
- **FFmpeg Editor** – Ken Burns rough cuts for longform + 9:16 Shorts with SRT captions
- **YouTube Metadata** – 10 title options, descriptions, tags, chapters, thumbnail briefs
- **Scheduling** – 30-day upload calendar, strategy recommendations, posting checklist

### YouTube Shorts Automation (New)

- **Strange Event Discovery** – Curated seed bank of 30+ viral-worthy events + Wikipedia category scraping
- **120-Word Micro-Scripts** – Hook → Build → Reveal structure optimised for 40-second retention
- **ElevenLabs Voiceover** – Automatic TTS narration with cinematic voice
- **AI Video Clips** – 5 cinematic clips per Short via Veo3, Runway Gen-3, or Gemini Imagen
- **Automated Assembly** – FFmpeg-powered 9:16 vertical video with crossfade transitions
- **Animated Subtitles** – Word-by-word uppercase captions for maximum retention
- **Shorts SEO** – Optimised titles, descriptions, and hashtags for discovery
- **Daily Scheduling** – 30-day posting calendar with optimal time slots

## Requirements

- Python 3.11+
- FFmpeg (optional, for rough-cut rendering)

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

### Longform Episodes

```bash
python -m microhistory.main \
  --topic "Dyatlov Pass incident" \
  --length 9min \
  --num_shorts 6 \
  --download_assets true \
  --render true
```

### YouTube Shorts Pipeline

```bash
# Single Short from a specific topic
python -m microhistory.main \
  --shorts --topic "Dancing plague of 1518"

# Auto-discover 3 strange events and produce daily Shorts
python -m microhistory.main \
  --shorts --topic auto --daily_count 3

# Use Runway for video clips instead of Gemini images
python -m microhistory.main \
  --shorts --topic "Great Molasses Flood" --video_backend runway

# Full automation with Veo3 video generation
python -m microhistory.main \
  --shorts --topic auto --daily_count 1 --video_backend veo3
```

### CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--topic` | *(required)* | Episode topic keyword (use `auto` in Shorts mode for discovery) |
| `--length` | `9min` | Target video length (`9min`, `540`, `10min`) |
| `--num_shorts` | `6` | Number of Shorts to generate |
| `--download_assets` | `false` | Download archival assets locally |
| `--render` | `false` | Render rough-cut MP4s (requires FFmpeg) |
| `--output_dir` | `output` | Output directory |
| `--assets_dir` | — | Directory with stock/paid assets |
| `--shorts` | `false` | Run the YouTube Shorts automation pipeline |
| `--daily_count` | `1` | Number of Shorts to produce per run (Shorts mode) |
| `--video_backend` | `gemini_image` | Video generation backend: `runway`, `veo3`, or `gemini_image` |

## Output Structure

```
output/<topic_slug>/
  script.md
  sources.json
  fact_check_report.md
  storyboard.md
  voiceover.txt
  voiceover.ssml
  pronunciation_guide.txt
  ATTRIBUTION.txt
  ai_generation/
    shot_prompts.json
    veo3_prompts.md
    gemini_prompts.md
    seedance_prompts.md
  edits/
    longform/
      timeline.csv
      edit_instructions.md
      roughcut.mp4          # if --render true
    shorts/
      short_01/
        script.txt
        captions.srt
        timeline.csv
        roughcut.mp4        # if --render true
      short_02/ ...
  metadata/
    title_options.txt
    description_short.txt
    description_long.txt
    tags.txt
    chapters.txt
    thumbnail_brief.txt
  scheduling/
    schedule_recommendation.md
    upload_calendar.csv
    posting_checklist.md
```

## Modules

| Module | Purpose |
|--------|---------|
| `topic_research.py` | Gathers facts and licensed media via official APIs; discovers strange events |
| `scriptwriter.py` | Generates original cinematic narration with inline cues |
| `shorts_scriptwriter.py` | Generates 120-word Hook→Build→Reveal scripts for Shorts |
| `storyboard.py` | Maps script to timestamped shots (archival or AI-generated) |
| `ai_prompt_generator.py` | Creates platform-specific prompt packs with continuity bible |
| `voiceover_packager.py` | Extracts clean VO text, SSML, and pronunciation guide |
| `tts_generator.py` | Converts text to speech via ElevenLabs API |
| `visual_generator.py` | Generates images (Gemini Imagen) and video clips (Veo3/Runway) |
| `editor_ffmpeg.py` | Builds timelines, rough cuts, and Shorts assembly with animated subtitles |
| `metadata_generator.py` | Produces YouTube-ready titles, descriptions, tags, Shorts SEO |
| `scheduler.py` | Generates upload calendar, posting checklist, and daily Shorts schedule |
| `shorts_pipeline.py` | End-to-end Shorts automation orchestrator |

## Compliance

- **No scraping** – Only official APIs (Wikipedia, Wikimedia, LoC, Internet Archive)
- **License filtering** – Automatically skips non-commercial-use assets
- **No automated posting** – Scheduling is planning-only; manual upload via YouTube Studio
- **Original narration** – All text is paraphrased with source citations in `fact_check_report.md`
- **Attribution** – Full credits in `ATTRIBUTION.txt` and video description

## Tests

```bash
pytest tests/ -v
```

Tests cover license filtering, output folder structure, and scheduling CSV format.

## License

MIT
