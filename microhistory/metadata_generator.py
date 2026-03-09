"""Module 7 – Metadata Generator.

Produces YouTube-ready metadata: title options, descriptions, tags,
chapters, and thumbnail briefs.
"""

from __future__ import annotations

import re
from pathlib import Path

from microhistory.logging_config import get_logger
from microhistory.models import (
    EpisodeMetadata,
    ResearchResult,
    Script,
    SourceAsset,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Title generation
# ---------------------------------------------------------------------------

_TITLE_TEMPLATES = [
    "The Untold Story of {topic}",
    "{topic}: What Really Happened",
    "The Mystery of {topic} – Finally Explained",
    "Why {topic} Changed Everything",
    "{topic}: The Dark Truth Nobody Talks About",
    "The Shocking Truth Behind {topic}",
    "{topic} – History's Greatest Mystery?",
    "What They Don't Tell You About {topic}",
    "The Real Story of {topic}",
    "{topic}: A Story Lost to Time",
]


def _generate_titles(topic: str) -> list[str]:
    """Generate 10 title options."""
    return [t.format(topic=topic) for t in _TITLE_TEMPLATES]


# ---------------------------------------------------------------------------
# Description generation
# ---------------------------------------------------------------------------

def _generate_short_description(topic: str, summary: str) -> str:
    """Generate a short YouTube description (≤200 chars)."""
    # Take first 2 sentences of the summary
    sentences = re.split(r'(?<=[.!?])\s+', summary)
    short = " ".join(sentences[:2])[:180]
    if not short.endswith("."):
        short += "."
    return short


def _generate_long_description(
    topic: str,
    summary: str,
    assets: list[SourceAsset],
    chapters: list[str],
) -> str:
    """Generate a detailed YouTube description with attribution."""
    lines = [
        f"The untold story of {topic} – a deep dive into one of history's most fascinating episodes.",
        "",
        summary[:500] if summary else f"Explore the history of {topic}.",
        "",
        "---",
        "",
        "CHAPTERS:",
    ]
    for ch in chapters:
        lines.append(ch)

    lines += [
        "",
        "---",
        "",
        "SOURCES & ATTRIBUTION:",
    ]

    # Deduplicate attributions
    seen: set[str] = set()
    for asset in assets:
        if asset.is_commercial_safe and asset.attribution not in seen:
            seen.add(asset.attribution)
            lines.append(f"• {asset.attribution} ({asset.license.value}) – {asset.url}")
            if len(seen) >= 20:
                break

    lines += [
        "",
        "---",
        "",
        "#history #documentary #microhistory",
        "",
        "All visuals are public domain, Creative Commons licensed, or AI-generated original content.",
        "No copyrighted material was used in this video.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def _generate_tags(topic: str) -> list[str]:
    """Generate relevant YouTube tags."""
    base_tags = [
        topic.lower(),
        f"{topic.lower()} history",
        f"{topic.lower()} documentary",
        f"{topic.lower()} explained",
        "history documentary",
        "historical mystery",
        "micro history",
        "history channel",
        "dark history",
        "untold history",
        "true story",
        "historical events",
        "what happened",
        "mystery explained",
        "documentary",
    ]
    # Add individual words from topic
    for word in topic.lower().split():
        if len(word) > 3 and word not in base_tags:
            base_tags.append(word)

    return base_tags[:30]  # YouTube allows max 500 chars, ~30 tags


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------

def _generate_chapters(script: Script) -> list[str]:
    """Generate YouTube chapter timestamps from script segments."""
    chapters: list[str] = []
    cumulative = 0
    for seg in script.segments:
        m, s = divmod(cumulative, 60)
        label = seg.section.replace("_", " ").title()
        chapters.append(f"{m:02d}:{s:02d} – {label}")
        cumulative += seg.approx_duration_sec
    return chapters


# ---------------------------------------------------------------------------
# Thumbnail brief
# ---------------------------------------------------------------------------

def _generate_thumbnail_briefs(topic: str) -> list[str]:
    """Generate 3 thumbnail concepts."""
    return [
        (
            f"CONCEPT 1 – 'The Reveal'\n"
            f"Background: Dramatic wide shot of key location related to {topic}, desaturated.\n"
            f"Text overlay: Large bold '{topic.upper()}' in distressed serif font, off-white.\n"
            f"Secondary text: 'WHAT REALLY HAPPENED?' in red accent bar.\n"
            f"Composition: Rule of thirds, subject left, text right.\n"
            f"Color: Dark moody, single warm highlight on text."
        ),
        (
            f"CONCEPT 2 – 'The Mystery'\n"
            f"Background: Close-up of a key artifact or document related to {topic}, aged texture.\n"
            f"Text overlay: '{topic.split()[0].upper()}' huge, partially obscured by shadow.\n"
            f"Secondary text: 'THE UNTOLD STORY' in small caps below.\n"
            f"Composition: Center-weighted, vignette edges.\n"
            f"Color: Sepia with teal shadows, high contrast."
        ),
        (
            f"CONCEPT 3 – 'The Question'\n"
            f"Background: Atmospheric landscape or map related to {topic}, aerial perspective.\n"
            f"Text overlay: '?' large symbol with '{topic}' below in clean sans-serif.\n"
            f"Secondary text: 'HISTORY'S GREATEST MYSTERY' in subtitle position.\n"
            f"Composition: Centered, symmetrical, clean.\n"
            f"Color: Cool blue-grey with single orange accent on the '?'."
        ),
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_metadata(
    script: Script,
    research: ResearchResult,
) -> EpisodeMetadata:
    """Generate full episode metadata."""
    log.info("[bold]Generating metadata for [cyan]%s[/cyan][/]", script.topic)

    chapters = _generate_chapters(script)

    metadata = EpisodeMetadata(
        title_options=_generate_titles(research.topic),
        description_short=_generate_short_description(research.topic, research.summary),
        description_long=_generate_long_description(
            research.topic, research.summary, research.assets, chapters,
        ),
        tags=_generate_tags(research.topic),
        chapters=chapters,
        thumbnail_briefs=_generate_thumbnail_briefs(research.topic),
    )

    log.info(
        "[bold green]Metadata generated[/] – %d titles, %d tags, %d chapters",
        len(metadata.title_options), len(metadata.tags), len(metadata.chapters),
    )
    return metadata


def write_metadata(metadata: EpisodeMetadata, output_dir: Path) -> None:
    """Write all metadata files to the output directory."""
    meta_dir = output_dir / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)

    (meta_dir / "title_options.txt").write_text(
        "\n".join(f"{i}. {t}" for i, t in enumerate(metadata.title_options, 1)),
        encoding="utf-8",
    )

    (meta_dir / "description_short.txt").write_text(metadata.description_short, encoding="utf-8")
    (meta_dir / "description_long.txt").write_text(metadata.description_long, encoding="utf-8")

    (meta_dir / "tags.txt").write_text("\n".join(metadata.tags), encoding="utf-8")
    (meta_dir / "chapters.txt").write_text("\n".join(metadata.chapters), encoding="utf-8")

    (meta_dir / "thumbnail_brief.txt").write_text(
        "\n\n---\n\n".join(metadata.thumbnail_briefs),
        encoding="utf-8",
    )

    log.info("Wrote metadata files to %s", meta_dir)


# ---------------------------------------------------------------------------
# Shorts-specific SEO
# ---------------------------------------------------------------------------

_SHORTS_TITLE_TEMPLATES = [
    "This {topic} story will blow your mind",
    "The {topic} mystery nobody can explain",
    "{topic}: the strangest event in history",
    "You won't believe what happened at {topic}",
    "The dark truth about {topic}",
    "History's most bizarre moment: {topic}",
    "{topic} — wait for the ending",
    "Why does nobody talk about {topic}?",
]

_SHORTS_HASHTAGS = [
    "#history", "#shorts", "#historyfacts", "#mystery",
    "#didyouknow", "#darkhistory", "#historytok", "#strange",
    "#microhistory", "#truecrime", "#unsolved", "#mindblowing",
    "#education", "#historical", "#fyp",
]


def generate_shorts_seo(
    topic: str,
    script_text: str = "",
) -> "ShortsSEO":
    """Generate SEO metadata optimised for YouTube Shorts discovery."""
    from microhistory.models import ShortsSEO
    import hashlib

    log.info("[bold]Generating Shorts SEO for [cyan]%s[/cyan][/]", topic)

    # Pick a title deterministically based on topic
    idx = int(hashlib.md5(topic.encode()).hexdigest(), 16) % len(_SHORTS_TITLE_TEMPLATES)
    title = _SHORTS_TITLE_TEMPLATES[idx].format(topic=topic)

    # Ensure title is under 100 chars (YouTube Shorts best practice)
    if len(title) > 95:
        title = title[:92] + "..."

    # Description: short, keyword-rich, with hashtags at bottom
    desc_body = script_text[:150].strip() if script_text else f"The incredible story of {topic}."
    if not desc_body.endswith((".", "!", "?")):
        desc_body += "."

    # Pick topic-relevant hashtags + generic ones
    topic_words = [w.lower() for w in topic.split() if len(w) > 3]
    topic_hashtags = [f"#{w}" for w in topic_words[:3]]

    # Combine: topic hashtags first, then generic
    all_hashtags = topic_hashtags + _SHORTS_HASHTAGS
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_hashtags: list[str] = []
    for h in all_hashtags:
        h_lower = h.lower()
        if h_lower not in seen:
            seen.add(h_lower)
            unique_hashtags.append(h)

    hashtags = unique_hashtags[:15]

    description = f"{desc_body}\n\n{' '.join(hashtags)}"

    # Tags for the upload
    tags = [
        topic.lower(),
        f"{topic.lower()} history",
        f"{topic.lower()} mystery",
        "history shorts",
        "micro history",
        "strange history",
        "historical mystery",
        "dark history",
        "did you know",
        "history facts",
    ]
    # Add individual topic words
    for w in topic_words:
        if w not in tags:
            tags.append(w)

    seo = ShortsSEO(
        title=title,
        description=description,
        hashtags=hashtags,
        tags=tags[:30],
    )

    log.info("[bold green]Shorts SEO generated[/] – title: %s", title[:60])
    return seo


def write_shorts_seo(seo: "ShortsSEO", path: Path) -> None:
    """Write Shorts SEO metadata to a JSON file."""
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(seo.model_dump(), indent=2),
        encoding="utf-8",
    )
    log.info("Wrote %s", path)
