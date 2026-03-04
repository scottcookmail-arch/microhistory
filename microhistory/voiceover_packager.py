"""Module 5 – Voiceover Packager.

Outputs voiceover.txt (clean narration) and optional SSML with pacing
tags, plus a pronunciation guide for foreign names and places.
"""

from __future__ import annotations

import re
from pathlib import Path

from microhistory.logging_config import get_logger
from microhistory.models import Script

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Narration extraction
# ---------------------------------------------------------------------------

_CUE_PATTERN = re.compile(r'\[(?:SHOT-ID|VISUAL|SFX|ON-SCREEN TEXT):[^\]]*\]')


def _strip_cues(text: str) -> str:
    """Remove all inline cues, leaving clean narration."""
    clean = _CUE_PATTERN.sub('', text)
    # Collapse whitespace
    clean = re.sub(r'\n{2,}', '\n\n', clean)
    clean = re.sub(r'  +', ' ', clean)
    return clean.strip()


# ---------------------------------------------------------------------------
# Pronunciation guide
# ---------------------------------------------------------------------------

# Common foreign / unusual terms likely to appear in historical topics
_PRONUNCIATION_DB: dict[str, str] = {
    "dyatlov": "dee-AHT-loff",
    "kholat": "koh-LAHT",
    "syakhl": "see-AHKL",
    "mansi": "MAHN-see",
    "otorten": "oh-TOR-ten",
    "pompeii": "pom-PAY",
    "vesuvius": "veh-SOO-vee-us",
    "tutankhamun": "too-tahn-KAH-moon",
    "machu picchu": "MAH-choo PEE-choo",
    "tenochtitlan": "teh-noch-TEET-lahn",
    "versailles": "vehr-SY",
    "charlemagne": "SHAR-leh-main",
    "genghis": "GENG-gis",
    "thermopylae": "ther-MOP-ih-lee",
    "carthage": "KAR-thij",
    "hannibal": "HAN-ih-bal",
    "cleopatra": "klee-oh-PAT-ruh",
    "rasputin": "ras-PYOO-tin",
    "chernobyl": "cher-NOH-bil",
    "sarajevo": "SAR-ah-yeh-voh",
    "gavrilo princip": "GAV-ree-loh PRIN-tsip",
    "czar": "ZAHR",
    "tsar": "ZAHR",
    "pharaoh": "FAIR-oh",
    "guillotine": "GEE-uh-teen",
    "renaissance": "REN-ih-sahns",
    "bourgeoisie": "boor-zhwah-ZEE",
    "reich": "RYKE",
    "blitzkrieg": "BLITS-kreeg",
    "kamikaze": "KAH-mih-KAH-zee",
    "samurai": "SAM-uh-rye",
    "shogun": "SHOH-gun",
    "haiku": "HY-koo",
    "tsunami": "tsoo-NAH-mee",
    "krakatoa": "krak-uh-TOH-uh",
    "galapagos": "guh-LAH-puh-gohs",
    "magellan": "muh-JEL-in",
    "ptolemy": "TAHL-uh-mee",
    "byzantium": "bih-ZAN-tee-um",
    "constantinople": "kon-stan-tih-NOH-pul",
}


def _find_foreign_terms(text: str) -> dict[str, str]:
    """Scan text for words in the pronunciation database."""
    lower = text.lower()
    found: dict[str, str] = {}
    for term, pron in _PRONUNCIATION_DB.items():
        if term in lower:
            found[term.title()] = pron
    return found


# ---------------------------------------------------------------------------
# SSML generation
# ---------------------------------------------------------------------------

def _text_to_ssml(text: str) -> str:
    """Convert clean narration to SSML with pacing tags."""
    # Wrap in <speak> root
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<speak>", ""]

    paragraphs = text.split("\n\n")
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Add pauses at paragraph boundaries
        lines.append('  <p>')

        # Break into sentences
        sentences = re.split(r'(?<=[.!?])\s+', para)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # Slow down for dramatic effect on short sentences
            if len(sentence.split()) <= 5:
                lines.append(f'    <s><prosody rate="slow">{_escape_xml(sentence)}</prosody></s>')
            # Speed up slightly for longer expository sentences
            elif len(sentence.split()) > 25:
                lines.append(f'    <s><prosody rate="medium">{_escape_xml(sentence)}</prosody></s>')
            else:
                lines.append(f'    <s>{_escape_xml(sentence)}</s>')

        lines.append('  </p>')
        lines.append('  <break time="800ms"/>')
        lines.append("")

    lines.append("</speak>")
    return "\n".join(lines)


def _escape_xml(text: str) -> str:
    """Escape XML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def package_voiceover(script: Script) -> tuple[str, str, dict[str, str]]:
    """Extract clean voiceover text, SSML, and pronunciation guide.

    Returns (voiceover_text, ssml, pronunciation_guide).
    """
    log.info("[bold]Packaging voiceover for [cyan]%s[/cyan][/]", script.topic)

    # Build clean narration
    narration_parts: list[str] = []
    for seg in script.segments:
        clean = _strip_cues(seg.narration)
        if clean:
            narration_parts.append(clean)

    voiceover_text = "\n\n".join(narration_parts)
    ssml = _text_to_ssml(voiceover_text)
    pronunciation = _find_foreign_terms(voiceover_text)

    log.info(
        "[bold green]Voiceover packaged[/] – %d words, %d pronunciation entries",
        len(voiceover_text.split()), len(pronunciation),
    )
    return voiceover_text, ssml, pronunciation


def write_voiceover(script: Script, output_dir: Path) -> None:
    """Write voiceover.txt, voiceover.ssml, and pronunciation_guide.txt."""
    voiceover_text, ssml, pronunciation = package_voiceover(script)

    output_dir.mkdir(parents=True, exist_ok=True)

    # voiceover.txt
    vo_path = output_dir / "voiceover.txt"
    vo_path.write_text(voiceover_text, encoding="utf-8")
    log.info("Wrote %s", vo_path)

    # voiceover.ssml
    ssml_path = output_dir / "voiceover.ssml"
    ssml_path.write_text(ssml, encoding="utf-8")
    log.info("Wrote %s", ssml_path)

    # pronunciation guide
    if pronunciation:
        pron_path = output_dir / "pronunciation_guide.txt"
        lines = ["# Pronunciation Guide", ""]
        for term, pron in sorted(pronunciation.items()):
            lines.append(f"  {term:30s} → {pron}")
        pron_path.write_text("\n".join(lines), encoding="utf-8")
        log.info("Wrote %s", pron_path)
