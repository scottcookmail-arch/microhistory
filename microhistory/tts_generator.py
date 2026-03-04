"""Module 11 – TTS Generator (ElevenLabs).

Converts voiceover text or SSML into narration audio using the ElevenLabs API.
Saves the output as MP3 files for longform and each short.

Requires: ELEVENLABS_API_KEY environment variable.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import httpx

from microhistory.logging_config import get_logger

log = get_logger(__name__)

_API_BASE = "https://api.elevenlabs.io/v1"
_TIMEOUT = httpx.Timeout(180.0)  # TTS can take a while for long text
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0

# Default voice — "Adam" is a popular deep male narrator voice.
# Users can override via ELEVENLABS_VOICE_ID env var.
_DEFAULT_VOICE_ID = "pNInz6obpgDQGcFmaJgB"  # Adam

# ElevenLabs models
_MODEL_MULTILINGUAL_V2 = "eleven_multilingual_v2"
_MODEL_TURBO_V2_5 = "eleven_turbo_v2_5"


def _get_api_key() -> str:
    """Return the ElevenLabs API key from the environment."""
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY environment variable is not set. "
            "Get one at https://elevenlabs.io/app/settings/api-keys"
        )
    return key


def _get_voice_id() -> str:
    """Return the voice ID to use."""
    return os.environ.get("ELEVENLABS_VOICE_ID", _DEFAULT_VOICE_ID)


def synthesize_speech(
    text: str,
    output_path: Path,
    api_key: str,
    voice_id: Optional[str] = None,
    model_id: str = _MODEL_MULTILINGUAL_V2,
) -> bool:
    """Synthesize speech from text and save as MP3.

    Returns True on success, False on failure.
    """
    if output_path.exists() and output_path.stat().st_size > 0:
        log.info("  Skipping %s (already exists)", output_path.name)
        return True

    if not text.strip():
        log.warning("  Empty text, skipping %s", output_path.name)
        return False

    voice = voice_id or _get_voice_id()
    url = f"{_API_BASE}/text-to-speech/{voice}"

    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.3,
            "use_speaker_boost": True,
        },
    }

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(url, json=payload, headers=headers)

                if resp.status_code == 429:
                    wait = _RETRY_DELAY * (2 ** (attempt - 1))
                    log.warning("  Rate limited, waiting %.0fs (attempt %d/%d)", wait, attempt, _MAX_RETRIES)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()

                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(resp.content)
                size_kb = len(resp.content) / 1024
                log.info("  Saved %s (%.1f KB)", output_path.name, size_kb)
                return True

        except httpx.HTTPStatusError as exc:
            log.warning("  API error: %s (attempt %d/%d)", exc.response.status_code, attempt, _MAX_RETRIES)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY * (2 ** (attempt - 1)))
        except httpx.HTTPError as exc:
            log.warning("  Network error: %s (attempt %d/%d)", exc, attempt, _MAX_RETRIES)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY * (2 ** (attempt - 1)))

    log.error("  Failed to synthesize %s after %d attempts", output_path.name, _MAX_RETRIES)
    return False


def run_tts(
    output_dir: Path,
    api_key: Optional[str] = None,
    voice_id: Optional[str] = None,
) -> dict[str, Path]:
    """Generate narration audio for the longform video and all shorts.

    Reads voiceover.txt for longform and each short's script.txt.
    Returns mapping of label → audio file path.
    """
    if api_key is None:
        api_key = _get_api_key()
    if voice_id is None:
        voice_id = _get_voice_id()

    results: dict[str, Path] = {}

    # --- Longform narration ---
    vo_path = output_dir / "voiceover.txt"
    if vo_path.exists():
        log.info("[bold]Generating longform narration audio[/]")
        narration_text = vo_path.read_text(encoding="utf-8")
        audio_path = output_dir / "narration.mp3"

        # ElevenLabs has a character limit per request (~5000 chars).
        # For longer text, we split into chunks and concatenate.
        if len(narration_text) > 4500:
            success = _synthesize_long_text(narration_text, audio_path, api_key, voice_id)
        else:
            success = synthesize_speech(narration_text, audio_path, api_key, voice_id)

        if success:
            results["longform"] = audio_path
    else:
        log.warning("voiceover.txt not found at %s", vo_path)

    # --- Short narrations ---
    shorts_dir = output_dir / "edits" / "shorts"
    if shorts_dir.exists():
        for short_dir in sorted(shorts_dir.iterdir()):
            if not short_dir.is_dir():
                continue
            script_path = short_dir / "script.txt"
            if not script_path.exists():
                continue

            label = short_dir.name
            log.info("[bold]Generating %s narration[/]", label)
            text = script_path.read_text(encoding="utf-8")
            audio_path = short_dir / "narration.mp3"

            if synthesize_speech(text, audio_path, api_key, voice_id):
                results[label] = audio_path

            # Small delay between requests
            time.sleep(0.5)

    log.info(
        "[bold green]TTS complete[/] – %d audio files generated",
        len(results),
    )
    return results


def _synthesize_long_text(
    text: str,
    output_path: Path,
    api_key: str,
    voice_id: str,
    chunk_size: int = 4000,
) -> bool:
    """Split long text into chunks, synthesize each, and concatenate."""
    # Split on paragraph boundaries
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 > chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = para
        else:
            current_chunk = current_chunk + "\n\n" + para if current_chunk else para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    if not chunks:
        return False

    log.info("  Splitting into %d chunks for long narration", len(chunks))

    # Synthesize each chunk
    chunk_paths: list[Path] = []
    output_path.parent.mkdir(parents=True, exist_ok=True)

    for i, chunk in enumerate(chunks, 1):
        chunk_path = output_path.parent / f"_chunk_{i:03d}.mp3"
        log.info("  Chunk %d/%d (%d chars)", i, len(chunks), len(chunk))

        if not synthesize_speech(chunk, chunk_path, api_key, voice_id):
            log.warning("  Chunk %d failed, aborting long narration", i)
            # Clean up chunk files
            for p in chunk_paths:
                p.unlink(missing_ok=True)
            return False

        chunk_paths.append(chunk_path)
        time.sleep(1.0)  # Rate limit between chunks

    # Concatenate chunks using simple binary concatenation (MP3 is streamable)
    with open(output_path, "wb") as out:
        for cp in chunk_paths:
            out.write(cp.read_bytes())

    # Clean up chunk files
    for cp in chunk_paths:
        cp.unlink(missing_ok=True)

    size_kb = output_path.stat().st_size / 1024
    log.info("  Combined narration: %s (%.1f KB)", output_path.name, size_kb)
    return True
