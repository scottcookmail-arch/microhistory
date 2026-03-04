"""Module 4 – AI Prompt Generator.

Generates prompt packs for multiple AI video/image platforms (Veo3,
Gemini, Seedance) from the storyboard.  Maintains consistent shot IDs,
style, and a continuity bible.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from microhistory.logging_config import get_logger
from microhistory.models import AspectRatio, ShotPrompt, Storyboard

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Continuity bible
# ---------------------------------------------------------------------------

_CONTINUITY_BIBLE = textwrap.dedent("""\
    ## Continuity Bible

    ### Visual Style
    - **Overall look:** Cinematic documentary, desaturated warm tones with dramatic lighting.
    - **Color palette:** Muted earth tones (sepia, slate, ochre) with selective color pops for emphasis.
    - **Lighting:** Volumetric light rays, golden-hour warmth, or cold blue moonlight for night scenes.
    - **Grain:** Subtle film grain overlay to evoke archival footage feel.

    ### Camera Language
    - **Default motion:** Slow, deliberate moves (push, pull, pan). No handheld shake.
    - **Transitions:** Dissolve or match-cut between shots. No hard cuts unless dramatic.
    - **Aspect ratio (longform):** 16:9 cinematic widescreen.
    - **Aspect ratio (shorts):** 9:16 vertical portrait.

    ### Subjects & Props
    - **People:** Silhouettes, anonymous figures, back-turned or partial-face compositions.
      Never recognisable modern individuals or copyrighted characters.
    - **Period accuracy:** Props, clothing, and architecture must match the era described.
    - **Maps & documents:** Aged parchment texture, hand-drawn cartographic style.

    ### Text & Graphics
    - **Font style:** Serif or slab-serif, slightly weathered.
    - **Text overlays:** Lower-third positioning, subtle drop-shadow.
    - **Color:** Off-white (#F5F0E8) on dark backgrounds.

    ### Audio Direction (for reference in visual pacing)
    - **Music:** Orchestral or ambient electronic underscore; rises and falls with narrative tension.
    - **SFX:** Period-appropriate environmental sounds, no modern sound effects.
""")


# ---------------------------------------------------------------------------
# Shot prompt generation
# ---------------------------------------------------------------------------

def _infer_environment(description: str) -> str:
    """Extract or generate environment description from shot description."""
    desc = description.lower()
    if any(w in desc for w in ("mountain", "snow", "ice", "summit", "peak")):
        return "snow-covered mountain landscape, harsh winter conditions"
    if any(w in desc for w in ("city", "street", "building", "urban")):
        return "period-accurate urban street, historical architecture"
    if any(w in desc for w in ("forest", "woods", "tree")):
        return "dense forest, filtered sunlight through canopy"
    if any(w in desc for w in ("ocean", "sea", "ship", "water", "coast")):
        return "vast ocean expanse, dramatic sky"
    if any(w in desc for w in ("desert", "sand", "arid")):
        return "arid desert landscape, heat haze on horizon"
    if any(w in desc for w in ("interior", "room", "inside", "document")):
        return "dimly lit interior, warm lamp light on aged surfaces"
    if any(w in desc for w in ("night", "dark", "moon")):
        return "night scene, moonlight with deep shadows"
    return "atmospheric landscape, cinematic lighting"


def _infer_era_props(description: str) -> str:
    """Infer period-appropriate props from description."""
    desc = description.lower()
    if any(w in desc for w in ("ancient", "roman", "greek", "egypt")):
        return "ancient stone architecture, torches, scrolls, togas or period garments"
    if any(w in desc for w in ("medieval", "castle", "knight")):
        return "stone fortifications, candlelight, chainmail, banners"
    if any(w in desc for w in ("victorian", "19th century", "1800")):
        return "gas lamps, top hats, cobblestones, horse-drawn carriages"
    if any(w in desc for w in ("1900", "early 20th", "edwardian")):
        return "early automobiles, telegraphs, formal period attire"
    if any(w in desc for w in ("1950", "1960", "cold war", "soviet")):
        return "mid-century furnishings, rotary phones, military uniforms, propaganda posters"
    if any(w in desc for w in ("map", "document", "manuscript")):
        return "aged parchment, ink, compass, magnifying glass"
    return "historically plausible props matching the narrative era"


def generate_shot_prompts(
    storyboard: Storyboard,
    include_shorts: bool = True,
    num_shorts: int = 6,
) -> list[ShotPrompt]:
    """Create unified ShotPrompt specs from the storyboard."""
    log.info("[bold]Generating shot prompts for [cyan]%s[/cyan][/]", storyboard.topic)

    prompts: list[ShotPrompt] = []
    for shot in storyboard.shots:
        if shot.source_type == "archival":
            # Archival shots don't need AI generation prompts
            continue

        prompts.append(ShotPrompt(
            shot_id=shot.shot_id,
            duration_sec=shot.duration_sec,
            aspect_ratio=AspectRatio.LANDSCAPE,
            style="cinematic documentary",
            camera_motion=shot.camera_motion,
            environment=_infer_environment(shot.description),
            subject=shot.description,
            era_props=_infer_era_props(shot.description),
            text_overlays=shot.text_overlay,
            negative_prompts="modern logos, copyrighted characters, text watermarks, low quality, blurry, cartoon style",
            continuity_notes="Follow continuity bible: muted earth tones, film grain, no recognisable faces",
        ))

    # Generate short-specific prompts (9:16 vertical crops)
    if include_shorts:
        for i in range(min(num_shorts, len(storyboard.shots))):
            shot = storyboard.shots[i * (len(storyboard.shots) // max(1, num_shorts))]
            if shot.source_type == "archival":
                continue
            short_id = f"SHORT-{i + 1:02d}-{shot.shot_id}"
            prompts.append(ShotPrompt(
                shot_id=short_id,
                duration_sec=min(shot.duration_sec, 8.0),
                aspect_ratio=AspectRatio.PORTRAIT,
                style="cinematic documentary, vertical framing",
                camera_motion=shot.camera_motion,
                environment=_infer_environment(shot.description),
                subject=shot.description,
                era_props=_infer_era_props(shot.description),
                text_overlays=shot.text_overlay or shot.narration_excerpt[:40],
                negative_prompts="modern logos, copyrighted characters, text watermarks, low quality, blurry",
                continuity_notes="Vertical 9:16 crop. Center subject. Large bold text overlays for mobile.",
            ))

    log.info("[bold green]Generated %d shot prompts[/]", len(prompts))
    return prompts


# ---------------------------------------------------------------------------
# Platform-specific renderers
# ---------------------------------------------------------------------------

def _render_veo3_prompt(p: ShotPrompt) -> str:
    """Render a single Veo3 prompt."""
    motion_map = {
        "slow_push": "Slowly push camera forward",
        "slow_pull": "Slowly pull camera backward",
        "pan_left": "Smooth horizontal pan from right to left",
        "pan_right": "Smooth horizontal pan from left to right",
        "ken_burns_zoom_in": "Ken Burns slow zoom into subject",
        "ken_burns_zoom_out": "Ken Burns slow zoom out revealing scene",
        "tilt_up": "Slow tilt upward from ground to sky",
        "tilt_down": "Slow tilt downward from sky to ground",
        "static_hold": "Locked-off static shot, no camera movement",
        "dolly_forward": "Dolly forward through the scene",
    }
    camera_instruction = motion_map.get(p.camera_motion, "Slow cinematic camera movement")

    return textwrap.dedent(f"""\
        ### {p.shot_id}
        **Duration:** {p.duration_sec}s | **Aspect:** {p.aspect_ratio.value}

        **Prompt:**
        Cinematic documentary shot. {p.environment}. {p.subject}.
        Props and details: {p.era_props}.
        {camera_instruction}. Film grain, desaturated warm tones, volumetric lighting.
        {f'Text overlay: "{p.text_overlays}".' if p.text_overlays else ''}

        **Camera:** {camera_instruction}
        **Negative:** {p.negative_prompts}
        **Continuity:** {p.continuity_notes}
    """)


def _render_gemini_prompt(p: ShotPrompt) -> str:
    """Render a single Gemini prompt."""
    return textwrap.dedent(f"""\
        ### {p.shot_id}
        **Type:** {"Storyboard frame" if "SHORT" in p.shot_id else "B-roll / key visual"}
        **Aspect:** {p.aspect_ratio.value} | **Duration guidance:** {p.duration_sec}s

        **Image prompt:**
        Create a {p.style} image: {p.subject}.
        Environment: {p.environment}.
        Period details: {p.era_props}.
        Visual style: muted earth tones, subtle film grain, dramatic lighting.
        {f'Include text overlay: "{p.text_overlays}".' if p.text_overlays else ''}

        **Avoid:** {p.negative_prompts}
    """)


def _render_seedance_prompt(p: ShotPrompt) -> str:
    """Render a single Seedance prompt."""
    return textwrap.dedent(f"""\
        ### {p.shot_id}
        **Duration:** {p.duration_sec}s | **Aspect:** {p.aspect_ratio.value}

        **Video prompt:**
        [{p.style}] {p.subject}. Setting: {p.environment}.
        Camera: {p.camera_motion.replace('_', ' ')}.
        Era-appropriate details: {p.era_props}.
        Color grading: desaturated warm, film grain.
        {f'Overlay text: "{p.text_overlays}".' if p.text_overlays else ''}

        **Motion guidance:** {p.camera_motion.replace('_', ' ')} at slow, deliberate pace.
        **Negative:** {p.negative_prompts}
    """)


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_shot_prompts_json(prompts: list[ShotPrompt], path: Path) -> None:
    """Write shot_prompts.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [p.model_dump() for p in prompts]
    # Convert enum values to strings
    for d in data:
        if isinstance(d.get("aspect_ratio"), AspectRatio):
            d["aspect_ratio"] = d["aspect_ratio"].value
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    log.info("Wrote %s (%d prompts)", path, len(prompts))


def write_veo3_prompts(prompts: list[ShotPrompt], path: Path) -> None:
    """Write veo3_prompts.md."""
    lines = [
        "# Veo3 Prompt Pack",
        "",
        _CONTINUITY_BIBLE,
        "",
        "---",
        "",
    ]
    for p in prompts:
        lines.append(_render_veo3_prompt(p))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", path)


def write_gemini_prompts(prompts: list[ShotPrompt], path: Path) -> None:
    """Write gemini_prompts.md."""
    lines = [
        "# Gemini Prompt Pack",
        "",
        _CONTINUITY_BIBLE,
        "",
        "---",
        "",
    ]
    for p in prompts:
        lines.append(_render_gemini_prompt(p))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", path)


def write_seedance_prompts(prompts: list[ShotPrompt], path: Path) -> None:
    """Write seedance_prompts.md."""
    lines = [
        "# Seedance Prompt Pack",
        "",
        _CONTINUITY_BIBLE,
        "",
        "---",
        "",
    ]
    for p in prompts:
        lines.append(_render_seedance_prompt(p))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", path)
