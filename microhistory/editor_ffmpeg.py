"""Module 6 – FFmpeg Editor.

Local rough-cut generator using FFmpeg.  Creates longform and short
roughcuts with Ken Burns effects, dissolve transitions, and on-screen
captions.  If no assets are available or FFmpeg is not installed, still
generates timelines and edit instructions.
"""

from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from microhistory.logging_config import get_logger
from microhistory.models import (
    Script,
    ShortPack,
    Storyboard,
    TimelineRow,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# FFmpeg detection
# ---------------------------------------------------------------------------

def ffmpeg_available() -> bool:
    """Return True if ffmpeg is on PATH."""
    return shutil.which("ffmpeg") is not None


# ---------------------------------------------------------------------------
# Timeline generation
# ---------------------------------------------------------------------------

def generate_longform_timeline(storyboard: Storyboard) -> list[TimelineRow]:
    """Build a longform timeline from the storyboard."""
    rows: list[TimelineRow] = []
    motions = ["ken_burns", "pan", "zoom_in", "zoom_out", "static"]
    for i, shot in enumerate(storyboard.shots):
        # Parse timecodes
        def _tc_to_sec(tc: str) -> float:
            parts = tc.split(":")
            return int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else 0.0

        start = _tc_to_sec(shot.timecode_start)
        end = _tc_to_sec(shot.timecode_end)

        asset_ref = shot.asset_id or f"ai_{shot.shot_id}"
        motion = motions[i % len(motions)]

        rows.append(TimelineRow(
            start_sec=start,
            end_sec=end,
            asset=asset_ref,
            motion_type=motion,
            text_overlay=shot.text_overlay,
            transition="dissolve" if i > 0 else "cut",
        ))
    return rows


def generate_short_packs(
    script: Script,
    storyboard: Storyboard,
    num_shorts: int = 6,
) -> list[ShortPack]:
    """Generate Short packs from the script and storyboard."""
    packs: list[ShortPack] = []
    # Divide script segments into short-worthy chunks
    all_segments = script.segments

    # Pick the most dramatic segments for shorts
    priority_sections = ["hook", "turning_point", "escalation", "theories", "aftermath", "scene_setting"]
    selected: list[int] = []
    for section in priority_sections:
        for i, seg in enumerate(all_segments):
            if seg.section == section and i not in selected:
                selected.append(i)
                if len(selected) >= num_shorts:
                    break
        if len(selected) >= num_shorts:
            break

    # Fill remaining slots
    for i in range(len(all_segments)):
        if len(selected) >= num_shorts:
            break
        if i not in selected:
            selected.append(i)

    for short_num, seg_idx in enumerate(selected[:num_shorts], 1):
        seg = all_segments[seg_idx]
        # Clean narration for the short
        clean = re.sub(r'\[(?:SHOT-ID|VISUAL|SFX|ON-SCREEN TEXT):[^\]]*\]', '', seg.narration)
        clean = re.sub(r'\s+', ' ', clean).strip()

        # Trim to ~45 seconds of narration (≈112 words at 150 WPM)
        words = clean.split()
        short_words = words[:112]
        short_text = " ".join(short_words)

        # Generate captions SRT
        captions = _generate_srt(short_text, max_duration_sec=55)

        # Timeline for the short
        shots_for_short = [s for s in storyboard.shots if s.source_type == "ai_generated"]
        start_idx = (short_num - 1) * 3
        short_shots = shots_for_short[start_idx:start_idx + 6] if shots_for_short else []

        timeline: list[TimelineRow] = []
        t = 0.0
        for shot in short_shots[:6]:
            dur = min(shot.duration_sec, 8.0)
            timeline.append(TimelineRow(
                start_sec=t,
                end_sec=t + dur,
                asset=shot.asset_id or f"ai_{shot.shot_id}",
                motion_type="ken_burns",
                text_overlay=shot.text_overlay,
                transition="cut",
            ))
            t += dur

        packs.append(ShortPack(
            short_number=short_num,
            title=f"Short {short_num}: {seg.section.replace('_', ' ').title()}",
            script_text=short_text,
            captions_srt=captions,
            timeline=timeline,
        ))

    return packs


def _generate_srt(text: str, max_duration_sec: float = 55) -> str:
    """Generate an SRT caption file from text."""
    words = text.split()
    total_words = len(words)
    if total_words == 0:
        return ""

    # Approx 3 words per second
    wps = max(2, total_words / max_duration_sec) if max_duration_sec > 0 else 3
    words_per_caption = max(3, min(8, int(wps * 2.5)))

    srt_lines: list[str] = []
    cap_num = 0
    word_idx = 0
    current_sec = 0.0

    while word_idx < total_words:
        cap_num += 1
        chunk = words[word_idx:word_idx + words_per_caption]
        chunk_text = " ".join(chunk)
        duration = len(chunk) / wps
        end_sec = current_sec + duration

        srt_lines.append(str(cap_num))
        srt_lines.append(f"{_srt_time(current_sec)} --> {_srt_time(end_sec)}")
        srt_lines.append(chunk_text)
        srt_lines.append("")

        current_sec = end_sec
        word_idx += words_per_caption

    return "\n".join(srt_lines)


def _srt_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------------------
# Timeline CSV writer
# ---------------------------------------------------------------------------

def write_timeline_csv(timeline: list[TimelineRow], path: Path) -> None:
    """Write a timeline to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["start_sec", "end_sec", "asset", "motion_type", "text_overlay", "transition"])
    for row in timeline:
        writer.writerow([row.start_sec, row.end_sec, row.asset, row.motion_type, row.text_overlay, row.transition])
    path.write_text(buf.getvalue(), encoding="utf-8")
    log.info("Wrote %s", path)


# ---------------------------------------------------------------------------
# Edit instructions
# ---------------------------------------------------------------------------

def generate_edit_instructions(storyboard: Storyboard, topic: str) -> str:
    """Generate human-readable editing instructions."""
    lines = [
        f"# Edit Instructions: {topic}",
        "",
        "## General",
        "",
        "- Use dissolve transitions between shots (0.5–1s crossfade).",
        "- Apply Ken Burns pan/zoom on all still images.",
        "- Maintain 16:9 aspect ratio for longform; 9:16 for Shorts.",
        "- Add subtle film grain overlay (opacity 10–15%).",
        "- Color grade: desaturated warm tones (lift shadows toward blue, highlights toward amber).",
        "",
        "## Shot-by-Shot Guide",
        "",
    ]
    for shot in storyboard.shots:
        lines.append(f"### {shot.shot_id} ({shot.timecode_start}–{shot.timecode_end})")
        lines.append(f"- **Asset:** {'Archival ' + (shot.asset_id or '') if shot.source_type == 'archival' else 'AI-generated clip'}")
        lines.append(f"- **Motion:** {shot.camera_motion.replace('_', ' ')}")
        if shot.text_overlay:
            lines.append(f'- **Text overlay:** "{shot.text_overlay}" – lower-third, serif font, off-white on semi-transparent dark bar')
        lines.append(f"- **Duration:** {shot.duration_sec}s")
        lines.append("")

    lines += [
        "## Audio",
        "",
        "- Layer voiceover narration, matching timing to shot timecodes.",
        "- Add ambient music underscore (orchestral/ambient electronic, -18 dB under voice).",
        "- Place SFX cues at marked positions in the script.",
        "",
        "## Export Settings",
        "",
        "- Longform: 1920x1080, H.264, 8 Mbps, AAC 320 kbps",
        "- Shorts: 1080x1920, H.264, 6 Mbps, AAC 256 kbps",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# FFmpeg rough-cut rendering
# ---------------------------------------------------------------------------

def render_roughcut(
    timeline: list[TimelineRow],
    assets_dir: Path,
    output_path: Path,
    resolution: str = "1920x1080",
) -> bool:
    """Render a rough cut MP4 from assets using FFmpeg.

    Returns True on success, False on failure or missing assets.
    """
    if not ffmpeg_available():
        log.warning("FFmpeg not found – skipping render")
        return False

    # Collect available assets
    available: dict[str, Path] = {}
    if assets_dir.exists():
        for f in assets_dir.iterdir():
            if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm"}:
                # Match by asset ID prefix
                available[f.stem.split("_")[0]] = f

    if not available:
        log.warning("No assets found in %s – skipping render", assets_dir)
        return False

    # Build FFmpeg filter complex
    width, height = resolution.split("x")
    inputs: list[str] = []
    filter_parts: list[str] = []
    concat_inputs: list[str] = []

    for i, row in enumerate(timeline):
        asset_key = row.asset.split("_")[0] if "_" in row.asset else row.asset
        asset_path = available.get(asset_key)
        if not asset_path:
            # Use a black frame as placeholder
            inputs.extend(["-f", "lavfi", "-i", f"color=c=black:s={resolution}:d={row.end_sec - row.start_sec}"])
        else:
            duration = row.end_sec - row.start_sec
            if asset_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                inputs.extend(["-loop", "1", "-t", str(duration), "-i", str(asset_path)])
            else:
                inputs.extend(["-t", str(duration), "-i", str(asset_path)])

        # Scale + Ken Burns effect
        if row.motion_type in ("ken_burns", "zoom_in"):
            filter_parts.append(
                f"[{i}:v]scale={int(int(width)*1.2)}:{int(int(height)*1.2)},"
                f"zoompan=z='min(zoom+0.0005,1.2)':d={int((row.end_sec-row.start_sec)*25)}:"
                f"s={resolution},setsar=1[v{i}]"
            )
        else:
            filter_parts.append(f"[{i}:v]scale={resolution},setsar=1[v{i}]")

        concat_inputs.append(f"[v{i}]")

    n = len(timeline)
    filter_parts.append(f"{''.join(concat_inputs)}concat=n={n}:v=1:a=0[outv]")

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Rendering rough cut → %s", output_path)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            log.warning("FFmpeg render failed: %s", result.stderr[-500:] if result.stderr else "unknown error")
            return False
        log.info("[bold green]Rough cut rendered[/] → %s", output_path)
        return True
    except subprocess.TimeoutExpired:
        log.warning("FFmpeg render timed out")
        return False
    except FileNotFoundError:
        log.warning("FFmpeg binary not found")
        return False


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------

def run_editor(
    script: Script,
    storyboard: Storyboard,
    output_dir: Path,
    num_shorts: int = 6,
    render: bool = False,
    assets_dir: Optional[Path] = None,
) -> None:
    """Run the full editor pipeline: timelines, instructions, optional renders."""
    log.info("[bold]Running editor for [cyan]%s[/cyan][/]", script.topic)

    edits_dir = output_dir / "edits"

    # --- Longform ---
    longform_dir = edits_dir / "longform"
    longform_dir.mkdir(parents=True, exist_ok=True)

    lf_timeline = generate_longform_timeline(storyboard)
    write_timeline_csv(lf_timeline, longform_dir / "timeline.csv")

    instructions = generate_edit_instructions(storyboard, script.topic)
    (longform_dir / "edit_instructions.md").write_text(instructions, encoding="utf-8")
    log.info("Wrote %s", longform_dir / "edit_instructions.md")

    if render and assets_dir:
        render_roughcut(lf_timeline, assets_dir, longform_dir / "roughcut.mp4")

    # --- Shorts ---
    shorts_packs = generate_short_packs(script, storyboard, num_shorts)
    for pack in shorts_packs:
        short_dir = edits_dir / "shorts" / f"short_{pack.short_number:02d}"
        short_dir.mkdir(parents=True, exist_ok=True)

        (short_dir / "script.txt").write_text(pack.script_text, encoding="utf-8")
        (short_dir / "captions.srt").write_text(pack.captions_srt, encoding="utf-8")
        write_timeline_csv(pack.timeline, short_dir / "timeline.csv")

        if render and assets_dir:
            render_roughcut(
                pack.timeline, assets_dir,
                short_dir / "roughcut.mp4",
                resolution="1080x1920",
            )

    log.info(
        "[bold green]Editor complete[/] – longform + %d shorts processed",
        len(shorts_packs),
    )
