"""Module 3 – Storyboard.

Converts the script into a timestamped storyboard.  Each shot references
either (A) a licensed archival asset from ``sources.json`` or (B) an
AI-generated shot request.
"""

from __future__ import annotations

import re
from pathlib import Path

from microhistory.logging_config import get_logger
from microhistory.models import (
    ResearchResult,
    Script,
    ShotSpec,
    SourceAsset,
    Storyboard,
)

log = get_logger(__name__)


def _timecode(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


def _match_asset(shot_desc: str, assets: list[SourceAsset]) -> SourceAsset | None:
    """Try to match a shot description to an available archival asset."""
    desc_lower = shot_desc.lower()
    best: SourceAsset | None = None
    best_score = 0.0

    for asset in assets:
        if not asset.is_commercial_safe:
            continue
        # Simple keyword overlap scoring
        asset_words = set(re.findall(r'\w+', (asset.title + " " + asset.description).lower()))
        shot_words = set(re.findall(r'\w+', desc_lower))
        overlap = len(asset_words & shot_words)
        score = overlap * asset.relevance_score
        if score > best_score:
            best_score = score
            best = asset

    # Only match if there's meaningful overlap
    if best_score >= 1.5:
        return best
    return None


# Camera motion options for variety
_CAMERA_MOTIONS = [
    "slow_push", "slow_pull", "pan_left", "pan_right",
    "ken_burns_zoom_in", "ken_burns_zoom_out",
    "tilt_up", "tilt_down", "static_hold", "dolly_forward",
]


def generate_storyboard(
    script: Script,
    research: ResearchResult,
) -> Storyboard:
    """Build a timestamped storyboard from the script and research assets."""
    log.info("[bold]Generating storyboard for [cyan]%s[/cyan][/]", script.topic)

    safe_assets = [a for a in research.assets if a.is_commercial_safe]
    shots: list[ShotSpec] = []
    cumulative_sec = 0
    motion_idx = 0

    for seg in script.segments:
        # Extract shot IDs from the annotated narration
        shot_ids = re.findall(r'\[SHOT-ID:\s*(SHOT-\d+)\]', seg.narration)
        visual_descs = re.findall(r'\[VISUAL:\s*([^\]]+)\]', seg.narration)
        text_overlays = re.findall(r'\[ON-SCREEN TEXT:\s*"([^"]+)"\]', seg.narration)

        # Clean narration for excerpts (remove cue markers)
        clean_narration = re.sub(r'\[(?:SHOT-ID|VISUAL|SFX|ON-SCREEN TEXT):[^\]]*\]', '', seg.narration)
        clean_words = clean_narration.split()

        # Calculate per-shot duration
        num_shots = max(1, len(shot_ids))
        shot_duration = seg.approx_duration_sec / num_shots

        for i, shot_id in enumerate(shot_ids):
            start_sec = cumulative_sec
            end_sec = start_sec + shot_duration

            # Visual description
            visual_desc = visual_descs[i] if i < len(visual_descs) else f"Visual for {seg.section}"

            # Try to match an archival asset
            matched_asset = _match_asset(visual_desc, safe_assets)

            # Narration excerpt for this shot
            words_per_shot = max(1, len(clean_words) // num_shots)
            excerpt_start = i * words_per_shot
            excerpt = " ".join(clean_words[excerpt_start:excerpt_start + words_per_shot])[:150]

            # Text overlay
            overlay = text_overlays[i] if i < len(text_overlays) else ""

            # Camera motion (cycle through options)
            motion = _CAMERA_MOTIONS[motion_idx % len(_CAMERA_MOTIONS)]
            motion_idx += 1

            shots.append(ShotSpec(
                shot_id=shot_id,
                timecode_start=_timecode(int(start_sec)),
                timecode_end=_timecode(int(end_sec)),
                duration_sec=round(shot_duration, 1),
                description=visual_desc.strip(),
                source_type="archival" if matched_asset else "ai_generated",
                asset_id=matched_asset.asset_id if matched_asset else None,
                narration_excerpt=excerpt,
                camera_motion=motion,
                text_overlay=overlay,
            ))

            cumulative_sec = end_sec

    storyboard = Storyboard(topic=script.topic, shots=shots)
    archival_count = sum(1 for s in shots if s.source_type == "archival")
    ai_count = sum(1 for s in shots if s.source_type == "ai_generated")
    log.info(
        "[bold green]Storyboard generated[/] – %d shots (%d archival, %d AI-generated)",
        len(shots), archival_count, ai_count,
    )
    return storyboard


def write_storyboard_md(storyboard: Storyboard, path: Path) -> None:
    """Write the storyboard as a Markdown file."""
    lines = [
        f"# Storyboard: {storyboard.topic}",
        "",
        f"**Total shots:** {len(storyboard.shots)}",
        "",
        "| Shot ID | Time | Duration | Source | Camera | Description | Text Overlay |",
        "|---------|------|----------|--------|--------|-------------|--------------|",
    ]
    for shot in storyboard.shots:
        src = f"archival ({shot.asset_id})" if shot.source_type == "archival" else "AI-generated"
        desc = shot.description[:50].replace("|", "–")
        overlay = shot.text_overlay[:30].replace("|", "–") if shot.text_overlay else ""
        lines.append(
            f"| {shot.shot_id} | {shot.timecode_start}–{shot.timecode_end} "
            f"| {shot.duration_sec}s | {src} | {shot.camera_motion} "
            f"| {desc} | {overlay} |"
        )

    lines += [
        "",
        "## Shot Details",
        "",
    ]
    for shot in storyboard.shots:
        lines.append(f"### {shot.shot_id} ({shot.timecode_start}–{shot.timecode_end})")
        lines.append(f"- **Source:** {shot.source_type}")
        if shot.asset_id:
            lines.append(f"- **Asset ID:** {shot.asset_id}")
        lines.append(f"- **Camera:** {shot.camera_motion}")
        lines.append(f"- **Description:** {shot.description}")
        if shot.text_overlay:
            lines.append(f'- **Text overlay:** "{shot.text_overlay}"')
        lines.append(f"- **Narration:** _{shot.narration_excerpt[:100]}_")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", path)
