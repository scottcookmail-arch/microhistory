"""Module 2b – Shorts Scriptwriter.

Generates a tight 120-word cinematic micro-history script structured as
Hook → Build → Reveal, optimised for 40-second YouTube Shorts retention.
"""

from __future__ import annotations

import re
from pathlib import Path

from microhistory.logging_config import get_logger
from microhistory.models import ResearchResult, ShortsScript

log = get_logger(__name__)

_WPM = 180  # Shorts narration is slightly faster paced than longform

# Target word budget per section
_HOOK_WORDS = 20
_BUILD_WORDS = 70
_REVEAL_WORDS = 30
_TOTAL_WORDS = 120


def _clean_sentence(s: str) -> str:
    """Normalise whitespace and strip trailing junk."""
    return re.sub(r"\s+", " ", s).strip().rstrip(",;:")


def _extract_key_facts(research: ResearchResult, limit: int = 6) -> list[str]:
    """Pull the most interesting factual sentences from research."""
    facts: list[str] = []
    for f in research.facts:
        claim = f.claim.strip()
        if len(claim) < 20:
            continue
        # Prefer sentences containing years or dramatic language
        score = 0
        if re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", claim):
            score += 2
        for w in ("died", "killed", "vanished", "mysterious", "unknown",
                   "discovered", "secret", "strange", "never", "impossible"):
            if w in claim.lower():
                score += 1
        facts.append((score, claim))
    facts.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in facts[:limit]]


def _paraphrase(text: str) -> str:
    """Light deterministic paraphrase to avoid verbatim copying."""
    words = text.split()
    if len(words) > 10:
        mid = len(words) // 2
        return (
            f"{' '.join(words[:mid]).rstrip('.,;:')}, "
            f"and {' '.join(words[mid:]).lstrip('.,;:').lower()}"
        )
    return text


def _build_hook(topic: str, seed_hook: str, facts: list[str]) -> str:
    """Create the opening hook (~20 words).

    Uses the seed hook if available, otherwise builds from facts.
    """
    if seed_hook:
        hook = seed_hook.strip()
        if not hook.endswith((".", "!", "?")):
            hook += "."
        # Pad slightly if too short
        word_count = len(hook.split())
        if word_count < 10:
            hook = f"In all of history, this is one of the strangest things that ever happened. {hook}"
        return _trim_to_words(hook, _HOOK_WORDS + 5)

    # Construct from first fact
    if facts:
        core = _clean_sentence(facts[0])
        if len(core.split()) > 15:
            core = " ".join(core.split()[:15]) + "."
        return f"This sounds impossible — but it actually happened. {core}"

    return f"The story of {topic} is one of history's strangest mysteries."


def _build_middle(topic: str, facts: list[str]) -> str:
    """Build the middle section (~70 words) from research facts."""
    if not facts:
        return (
            f"The events surrounding {topic} unfolded in a way nobody expected. "
            f"Witnesses reported details so unusual that historians still debate them today. "
            f"The evidence left behind only deepened the mystery. "
            f"What we know for certain is strange enough — but what we don't know is even stranger."
        )

    paragraphs: list[str] = []
    words_so_far = 0

    for fact in facts[1:]:  # skip first (used in hook)
        if words_so_far >= _BUILD_WORDS:
            break
        paraphrased = _paraphrase(_clean_sentence(fact))
        if not paraphrased.endswith("."):
            paraphrased += "."
        paragraphs.append(paraphrased)
        words_so_far += len(paraphrased.split())

    # Pad if needed
    if words_so_far < _BUILD_WORDS // 2:
        filler = (
            f"The circumstances surrounding {topic} grew even more puzzling. "
            f"Every new detail raised more questions than answers."
        )
        paragraphs.append(filler)

    return " ".join(paragraphs)


def _build_reveal(topic: str, facts: list[str]) -> str:
    """Create the closing reveal/twist (~30 words)."""
    endings = [
        f"To this day, the truth about {topic} remains one of history's unsolved riddles.",
        f"And the strangest part? Nobody has ever been able to fully explain what happened.",
        f"Centuries later, {topic} still defies explanation — and probably always will.",
        f"The mystery of {topic} has never been solved. Maybe it never will be.",
    ]
    import hashlib
    idx = int(hashlib.md5(topic.encode()).hexdigest(), 16) % len(endings)
    return endings[idx]


def _trim_to_words(text: str, max_words: int) -> str:
    """Trim text to approximately max_words, ending at a sentence boundary."""
    words = text.split()
    if len(words) <= max_words:
        return text
    trimmed = " ".join(words[:max_words])
    # Try to end at sentence boundary
    last_period = trimmed.rfind(".")
    if last_period > len(trimmed) // 2:
        return trimmed[: last_period + 1]
    return trimmed + "."


def generate_shorts_script(
    research: ResearchResult,
    seed_hook: str = "",
    target_words: int = _TOTAL_WORDS,
) -> ShortsScript:
    """Generate a 120-word cinematic micro-history script.

    Structure: Hook (~20 words) → Build (~70 words) → Reveal (~30 words).
    """
    topic = research.topic
    log.info("[bold]Generating Shorts script for [cyan]%s[/cyan][/]", topic)

    facts = _extract_key_facts(research)

    hook = _build_hook(topic, seed_hook, facts)
    build = _build_middle(topic, facts)
    reveal = _build_reveal(topic, facts)

    # Trim each section to budget
    hook = _trim_to_words(hook, _HOOK_WORDS + 5)
    build = _trim_to_words(build, _BUILD_WORDS + 10)
    reveal = _trim_to_words(reveal, _REVEAL_WORDS + 5)

    total = len(hook.split()) + len(build.split()) + len(reveal.split())
    duration = int(total / _WPM * 60)

    script = ShortsScript(
        topic=topic,
        hook=hook,
        build=build,
        reveal=reveal,
        total_word_count=total,
        target_duration_sec=min(duration, 55),
    )

    log.info(
        "[bold green]Shorts script generated[/] – %d words ≈ %ds",
        total, duration,
    )
    return script


def script_to_plain_text(script: ShortsScript) -> str:
    """Combine hook + build + reveal into a single narration string."""
    return f"{script.hook} {script.build} {script.reveal}".strip()


def write_shorts_script(script: ShortsScript, path: Path) -> None:
    """Write the Shorts script to a text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Shorts Script: {script.topic}",
        f"# Words: {script.total_word_count} | Duration: ~{script.target_duration_sec}s",
        "",
        "## HOOK",
        script.hook,
        "",
        "## BUILD",
        script.build,
        "",
        "## REVEAL",
        script.reveal,
        "",
        "---",
        "",
        "## Full Narration",
        script_to_plain_text(script),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", path)
