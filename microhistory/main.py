"""MicroHistory CLI – Episode Pack Generator.

Usage:
    python main.py --topic "Dyatlov Pass incident" --length 9min --num_shorts 6
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from microhistory.logging_config import get_logger
from microhistory.models import PipelineConfig

log = get_logger(__name__)
console = Console()


def _slugify(text: str) -> str:
    """Convert topic text to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '_', slug)
    return slug.strip('_')[:80]


def _parse_length(length_str: str) -> int:
    """Parse length string like '9min' or '540' into seconds."""
    length_str = length_str.strip().lower()
    m = re.match(r'^(\d+)\s*min(?:utes?)?$', length_str)
    if m:
        return int(m.group(1)) * 60
    m = re.match(r'^(\d+)\s*s(?:ec(?:onds?)?)?$', length_str)
    if m:
        return int(m.group(1))
    try:
        val = int(length_str)
        # If small number, assume minutes
        return val * 60 if val < 30 else val
    except ValueError:
        return 540  # default 9 min


def run_pipeline(config: PipelineConfig) -> Path:
    """Execute the full episode-pack pipeline.

    Returns the path to the output directory.
    """
    # Late imports to keep CLI startup fast
    from microhistory.topic_research import research_topic, write_sources_json
    from microhistory.scriptwriter import generate_script, write_script_md, write_fact_check
    from microhistory.storyboard import generate_storyboard, write_storyboard_md
    from microhistory.ai_prompt_generator import (
        generate_shot_prompts,
        write_shot_prompts_json,
        write_veo3_prompts,
        write_gemini_prompts,
        write_seedance_prompts,
    )
    from microhistory.voiceover_packager import write_voiceover
    from microhistory.editor_ffmpeg import run_editor
    from microhistory.metadata_generator import generate_metadata, write_metadata
    from microhistory.scheduler import generate_schedule, write_schedule
    from microhistory.visual_generator import run_visual_generator
    from microhistory.tts_generator import run_tts

    slug = _slugify(config.topic)
    output_dir = config.output_dir / slug
    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel(
        f"[bold cyan]MicroHistory Pipeline[/]\n"
        f"Topic: [bold]{config.topic}[/]\n"
        f"Target: {config.target_length_sec // 60}m {config.target_length_sec % 60}s · "
        f"{config.num_shorts} Shorts\n"
        f"Output: {output_dir}",
        title="Episode Pack",
    ))

    # ---- 1. Research ----
    console.rule("[bold blue]1. Topic Research")
    research = research_topic(
        config.topic,
        download=config.download_assets,
        output_dir=output_dir,
    )
    write_sources_json(research, output_dir / "sources.json")

    # ---- 2. Script ----
    console.rule("[bold blue]2. Script Generation")
    script = generate_script(research, config.target_length_sec)
    write_script_md(script, output_dir / "script.md")
    write_fact_check(script, research, output_dir / "fact_check_report.md")

    # ---- 3. Storyboard ----
    console.rule("[bold blue]3. Storyboard")
    storyboard = generate_storyboard(script, research)
    write_storyboard_md(storyboard, output_dir / "storyboard.md")

    # ---- 4. AI Prompts ----
    console.rule("[bold blue]4. AI Prompt Generation")
    ai_dir = output_dir / "ai_generation"
    shot_prompts = generate_shot_prompts(storyboard, num_shorts=config.num_shorts)
    write_shot_prompts_json(shot_prompts, ai_dir / "shot_prompts.json")
    write_veo3_prompts(shot_prompts, ai_dir / "veo3_prompts.md")
    write_gemini_prompts(shot_prompts, ai_dir / "gemini_prompts.md")
    write_seedance_prompts(shot_prompts, ai_dir / "seedance_prompts.md")

    # ---- 5. Voiceover ----
    console.rule("[bold blue]5. Voiceover Packaging")
    write_voiceover(script, output_dir)

    # ---- 5b. AI Visual Generation (--auto) ----
    if config.auto:
        console.rule("[bold magenta]5b. AI Visual Generation (Gemini Imagen)")
        try:
            generated = run_visual_generator(output_dir)
            console.print(f"  [green]Generated {len(generated)} images[/]")
        except RuntimeError as exc:
            console.print(f"  [yellow]Skipping visual generation: {exc}[/]")

    # ---- 5c. TTS Narration (--auto) ----
    if config.auto:
        console.rule("[bold magenta]5c. TTS Narration (ElevenLabs)")
        try:
            audio_files = run_tts(output_dir)
            console.print(f"  [green]Generated {len(audio_files)} audio files[/]")
        except RuntimeError as exc:
            console.print(f"  [yellow]Skipping TTS: {exc}[/]")

    # ---- 6. Editor ----
    console.rule("[bold blue]6. Editor / Timeline")
    assets_dir = config.assets_dir or output_dir / "assets"
    # If --auto was used, also look in the generated assets folder
    if config.auto and not config.assets_dir:
        generated_dir = output_dir / "assets" / "generated"
        if generated_dir.exists() and any(generated_dir.iterdir()):
            assets_dir = generated_dir
    run_editor(
        script, storyboard, output_dir,
        num_shorts=config.num_shorts,
        render=config.render or config.auto,
        assets_dir=assets_dir,
    )

    # ---- 7. Metadata ----
    console.rule("[bold blue]7. Metadata")
    metadata = generate_metadata(script, research)
    write_metadata(metadata, output_dir)

    # ---- 8. Schedule ----
    console.rule("[bold blue]8. Scheduling")
    schedule = generate_schedule(config.topic, config.num_shorts)
    write_schedule(schedule, output_dir)

    # ---- 9. Attribution ----
    console.rule("[bold blue]9. Attribution")
    _write_attribution(research, output_dir)

    # ---- Summary ----
    _print_summary(output_dir)

    return output_dir


def _write_attribution(research, output_dir: Path) -> None:
    """Write ATTRIBUTION.txt with all source credits."""
    from microhistory.models import SourceAsset

    lines = [
        f"ATTRIBUTION – {research.topic}",
        "=" * 60,
        "",
        "This episode uses the following licensed and public-domain assets.",
        "All assets are either public domain, Creative Commons licensed,",
        "US Government works, or AI-generated original content.",
        "",
        "-" * 60,
        "",
    ]
    for asset in research.assets:
        if asset.is_commercial_safe:
            lines.append(f"Title:       {asset.title}")
            lines.append(f"Source:      {asset.source_api}")
            lines.append(f"URL:         {asset.url}")
            lines.append(f"License:     {asset.license.value}")
            lines.append(f"Attribution: {asset.attribution}")
            lines.append("")

    lines += [
        "-" * 60,
        "",
        "AI-generated visuals were created using original prompts and do",
        "not incorporate copyrighted material.",
        "",
        "Narration is original, paraphrased from public sources.",
        "See fact_check_report.md for source verification.",
    ]

    attr_path = output_dir / "ATTRIBUTION.txt"
    attr_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", attr_path)


def _print_summary(output_dir: Path) -> None:
    """Print a summary table of generated files."""
    table = Table(title="Generated Files", show_lines=True)
    table.add_column("File", style="cyan")
    table.add_column("Size", justify="right")

    for p in sorted(output_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(output_dir)
            size = p.stat().st_size
            if size > 1_000_000:
                size_str = f"{size / 1_000_000:.1f} MB"
            elif size > 1_000:
                size_str = f"{size / 1_000:.1f} KB"
            else:
                size_str = f"{size} B"
            table.add_row(str(rel), size_str)

    console.print()
    console.print(table)
    console.print()
    console.print("[bold green]Episode pack complete![/]")


def cli() -> None:
    """CLI entry point."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="microhistory",
        description="MicroHistory – Faceless YouTube Channel Production Pipeline",
    )
    parser.add_argument(
        "--topic", required=True,
        help='Episode topic, e.g. "Dyatlov Pass incident"',
    )
    parser.add_argument(
        "--length", default="9min",
        help="Target video length (e.g. 9min, 540, 10min). Default: 9min",
    )
    parser.add_argument(
        "--num_shorts", type=int, default=6,
        help="Number of Shorts to generate. Default: 6",
    )
    parser.add_argument(
        "--download_assets", type=str, default="false",
        help="Download archival assets locally (true/false). Default: false",
    )
    parser.add_argument(
        "--render", type=str, default="false",
        help="Render rough-cut MP4s with FFmpeg (true/false). Default: false",
    )
    parser.add_argument(
        "--output_dir", type=str, default="output",
        help="Output directory. Default: output",
    )
    parser.add_argument(
        "--assets_dir", type=str, default=None,
        help="Directory containing stock/paid assets to use.",
    )
    parser.add_argument(
        "--auto", action="store_true", default=False,
        help="Full automation: generate visuals (Gemini) + narration (ElevenLabs) + render. "
             "Requires GOOGLE_API_KEY and ELEVENLABS_API_KEY env vars.",
    )

    args = parser.parse_args()

    config = PipelineConfig(
        topic=args.topic,
        target_length_sec=_parse_length(args.length),
        num_shorts=args.num_shorts,
        download_assets=args.download_assets.lower() in ("true", "1", "yes"),
        render=args.render.lower() in ("true", "1", "yes"),
        output_dir=Path(args.output_dir),
        assets_dir=Path(args.assets_dir) if args.assets_dir else None,
        auto=args.auto,
    )

    try:
        run_pipeline(config)
    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline interrupted by user.[/]")
        sys.exit(1)
    except Exception as exc:
        console.print(f"\n[bold red]Pipeline error:[/] {exc}")
        log.exception("Pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    cli()
