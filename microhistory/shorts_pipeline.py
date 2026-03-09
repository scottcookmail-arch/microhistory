"""Shorts Pipeline – End-to-end YouTube Shorts automation.

Orchestrates the full workflow:
  1. Discover strange historical events
  2. Research topic via Wikipedia
  3. Generate 120-word cinematic micro-history script
  4. Convert script to voiceover (ElevenLabs)
  5. Generate 5 cinematic video clips (Veo3 / Runway)
  6. Assemble clips into 40-second 9:16 video with animated subtitles
  7. Generate SEO title, description, hashtags
  8. Create daily posting schedule
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel

from microhistory.logging_config import get_logger
from microhistory.models import (
    PipelineConfig,
    ShortsEpisode,
    ShortsVideoSpec,
)

log = get_logger(__name__)
console = Console()


def run_shorts_pipeline(
    config: PipelineConfig,
    video_backend: str = "gemini_image",
) -> list[ShortsEpisode]:
    """Run the full Shorts production pipeline.

    Parameters
    ----------
    config : PipelineConfig
        Pipeline configuration with ``shorts_mode=True``.
    video_backend : str
        Backend for video clip generation: "runway", "veo3", or "gemini_image".

    Returns
    -------
    list[ShortsEpisode]
        Completed episode packages.
    """
    from microhistory.topic_research import (
        discover_strange_events,
        research_short_topic,
    )
    from microhistory.shorts_scriptwriter import (
        generate_shorts_script,
        script_to_plain_text,
        write_shorts_script,
    )
    from microhistory.tts_generator import synthesize_speech, _get_api_key as _get_el_key, _get_voice_id
    from microhistory.visual_generator import (
        build_shorts_clip_prompts,
        generate_shorts_clips,
    )
    from microhistory.editor_ffmpeg import (
        generate_animated_srt,
        assemble_shorts_video,
    )
    from microhistory.metadata_generator import generate_shorts_seo, write_shorts_seo
    from microhistory.scheduler import generate_daily_shorts_schedule, write_schedule

    base_dir = config.output_dir / "shorts"
    base_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel(
        f"[bold cyan]MicroHistory Shorts Pipeline[/]\n"
        f"Topic: [bold]{config.topic or 'auto-discover'}[/]\n"
        f"Daily count: {config.daily_count}\n"
        f"Video backend: {video_backend}\n"
        f"Output: {base_dir}",
        title="Shorts Mode",
    ))

    episodes: list[ShortsEpisode] = []

    # ---- Step 1: Discover strange events ----
    console.rule("[bold blue]1. Discovering Strange Historical Events")
    if config.topic and config.topic.lower() != "auto":
        # User specified a topic directly
        events = [{"topic": config.topic, "date": "", "hook": ""}]
    else:
        events = discover_strange_events(count=config.daily_count)
    log.info("Selected %d topic(s): %s", len(events), [e["topic"] for e in events])

    all_topics: list[str] = []

    for idx, event in enumerate(events, 1):
        topic = event["topic"]
        seed_hook = event.get("hook", "")
        all_topics.append(topic)

        slug = topic.lower().replace(" ", "_")[:60]
        ep_dir = base_dir / f"{idx:03d}_{slug}"
        ep_dir.mkdir(parents=True, exist_ok=True)

        console.rule(f"[bold magenta]Episode {idx}/{len(events)}: {topic}")

        episode = ShortsEpisode(topic=topic, event_date=event.get("date", ""))

        # ---- Step 2: Research ----
        console.print("  [blue]2. Researching topic...[/]")
        research = research_short_topic(topic)

        # ---- Step 3: Script ----
        console.print("  [blue]3. Generating 120-word script...[/]")
        script = generate_shorts_script(research, seed_hook=seed_hook)
        write_shorts_script(script, ep_dir / "script.txt")
        episode.script = script

        narration_text = script_to_plain_text(script)

        # ---- Step 4: Voiceover (ElevenLabs) ----
        console.print("  [blue]4. Generating voiceover (ElevenLabs)...[/]")
        audio_path = ep_dir / "voiceover.mp3"
        try:
            el_key = _get_el_key()
            voice_id = _get_voice_id()
            if synthesize_speech(narration_text, audio_path, el_key, voice_id):
                episode.voiceover_path = str(audio_path)
                console.print("  [green]Voiceover generated[/]")
            else:
                console.print("  [yellow]Voiceover generation failed — continuing without audio[/]")
        except RuntimeError as exc:
            console.print(f"  [yellow]Skipping voiceover: {exc}[/]")

        # ---- Step 5: Generate 5 cinematic video clips ----
        console.print(f"  [blue]5. Generating 5 video clips ({video_backend})...[/]")
        clip_prompts = build_shorts_clip_prompts(
            topic, narration_text, num_clips=5, target_duration=40.0,
        )

        # Save prompts for reference
        prompts_path = ep_dir / "clip_prompts.json"
        prompts_path.write_text(
            json.dumps(clip_prompts, indent=2), encoding="utf-8",
        )

        clips_dir = ep_dir / "clips"
        try:
            clip_paths = generate_shorts_clips(
                clip_prompts, clips_dir, backend=video_backend,
            )
        except RuntimeError as exc:
            console.print(f"  [yellow]Clip generation error: {exc}[/]")
            clip_paths = []

        for i, cp in enumerate(clip_paths, 1):
            episode.clips.append(ShortsVideoSpec(
                clip_number=i,
                duration_sec=8.0,
                prompt=clip_prompts[i - 1]["prompt"] if i <= len(clip_prompts) else "",
                local_path=str(cp),
            ))

        if clip_paths:
            console.print(f"  [green]{len(clip_paths)} clips generated[/]")
        else:
            console.print("  [yellow]No clips generated — video assembly will be skipped[/]")

        # ---- Step 6: Animated subtitles ----
        console.print("  [blue]6. Generating animated subtitles...[/]")
        srt_content = generate_animated_srt(
            narration_text,
            max_duration_sec=float(script.target_duration_sec),
            words_per_caption=3,
        )
        srt_path = ep_dir / "captions.srt"
        srt_path.write_text(srt_content, encoding="utf-8")
        episode.captions_srt = srt_content

        # ---- Step 6b + 7: Assemble into 9:16 video ----
        if clip_paths:
            console.print("  [blue]7. Assembling 40s vertical video (9:16)...[/]")
            final_path = ep_dir / "final_short.mp4"
            vo_path = Path(episode.voiceover_path) if episode.voiceover_path else None
            ok = assemble_shorts_video(
                clip_paths=clip_paths,
                audio_path=vo_path,
                srt_path=srt_path,
                output_path=final_path,
                target_duration=40.0,
            )
            if ok:
                episode.final_video_path = str(final_path)
                console.print(f"  [green]Final video: {final_path}[/]")
            else:
                console.print("  [yellow]Video assembly failed[/]")
        else:
            console.print("  [dim]7. Skipping assembly (no clips)[/]")

        # ---- Step 8: SEO ----
        console.print("  [blue]8. Generating SEO metadata...[/]")
        seo = generate_shorts_seo(topic, narration_text)
        write_shorts_seo(seo, ep_dir / "seo.json")
        episode.seo = seo

        episodes.append(episode)

    # ---- Step 9: Daily posting schedule ----
    console.rule("[bold blue]9. Generating Daily Posting Schedule")
    schedule = generate_daily_shorts_schedule(
        topics=all_topics,
        days=30,
        posts_per_day=config.daily_count,
    )
    write_schedule(schedule, base_dir)

    # ---- Summary ----
    _print_shorts_summary(episodes, base_dir)

    return episodes


def _print_shorts_summary(
    episodes: list[ShortsEpisode],
    base_dir: Path,
) -> None:
    """Print a summary of all generated Shorts episodes."""
    from rich.table import Table

    table = Table(title="Generated Shorts Episodes", show_lines=True)
    table.add_column("#", style="bold", width=4)
    table.add_column("Topic", style="cyan")
    table.add_column("Words", justify="right")
    table.add_column("Clips", justify="right")
    table.add_column("Audio", justify="center")
    table.add_column("Video", justify="center")
    table.add_column("SEO", justify="center")

    for i, ep in enumerate(episodes, 1):
        wc = str(ep.script.total_word_count) if ep.script else "—"
        clips = str(len(ep.clips))
        audio = "[green]Yes[/]" if ep.voiceover_path else "[red]No[/]"
        video = "[green]Yes[/]" if ep.final_video_path else "[red]No[/]"
        seo = "[green]Yes[/]" if ep.seo else "[red]No[/]"
        table.add_row(str(i), ep.topic[:40], wc, clips, audio, video, seo)

    console.print()
    console.print(table)
    console.print()
    console.print(f"[bold green]Shorts pipeline complete![/]  Output: {base_dir}")
    console.print()
