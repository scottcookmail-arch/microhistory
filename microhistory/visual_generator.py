"""Module 10 – Visual Generator.

Calls Google Gemini Imagen API to generate images from shot_prompts.json.
Saves generated images to the assets directory so FFmpeg can assemble them.

Requires: GOOGLE_API_KEY environment variable.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx

from microhistory.logging_config import get_logger
from microhistory.models import ShotPrompt

log = get_logger(__name__)

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT = httpx.Timeout(120.0)
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0  # seconds, doubles each retry


def _get_api_key() -> str:
    """Return the Google API key from the environment."""
    key = os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        raise RuntimeError(
            "GOOGLE_API_KEY environment variable is not set. "
            "Get one at https://aistudio.google.com/apikey"
        )
    return key


def _build_prompt(prompt: ShotPrompt) -> str:
    """Build a text prompt string for Gemini image generation."""
    parts = [
        f"Cinematic documentary photograph. {prompt.style}.",
        f"Scene: {prompt.subject}.",
        f"Environment: {prompt.environment}.",
        f"Period details: {prompt.era_props}.",
        "Visual style: muted earth tones, subtle film grain, dramatic volumetric lighting.",
        "No text, no watermarks, no modern elements.",
    ]
    if prompt.text_overlays:
        # Don't ask the model to render text — we overlay it in FFmpeg
        parts.append(f"The scene should evoke: {prompt.text_overlays}.")
    parts.append(f"Avoid: {prompt.negative_prompts}.")
    return " ".join(parts)


def generate_image(
    prompt: ShotPrompt,
    output_path: Path,
    api_key: str,
) -> bool:
    """Generate a single image using Gemini Imagen API.

    Returns True on success, False on failure.
    """
    if output_path.exists():
        log.info("  Skipping %s (already exists)", output_path.name)
        return True

    text_prompt = _build_prompt(prompt)
    url = f"{_GEMINI_API_BASE}/models/imagen-3.0-generate-002:predict"

    payload = {
        "instances": [{"prompt": text_prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "16:9" if prompt.aspect_ratio.value == "16:9" else "9:16",
            "personGeneration": "dont_allow",
            "safetySetting": "block_medium_and_above",
        },
    }

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(
                    url,
                    json=payload,
                    params={"key": api_key},
                    headers={"Content-Type": "application/json"},
                )

                if resp.status_code == 429:
                    wait = _RETRY_DELAY * (2 ** (attempt - 1))
                    log.warning("  Rate limited, waiting %.0fs (attempt %d/%d)", wait, attempt, _MAX_RETRIES)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

            # Extract image bytes from response
            predictions = data.get("predictions", [])
            if not predictions:
                log.warning("  No predictions returned for %s", prompt.shot_id)
                return False

            import base64
            image_b64 = predictions[0].get("bytesBase64Encoded", "")
            if not image_b64:
                log.warning("  Empty image data for %s", prompt.shot_id)
                return False

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(base64.b64decode(image_b64))
            log.info("  Generated %s", output_path.name)
            return True

        except httpx.HTTPStatusError as exc:
            log.warning("  API error for %s: %s (attempt %d/%d)", prompt.shot_id, exc.response.status_code, attempt, _MAX_RETRIES)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY * (2 ** (attempt - 1)))
        except httpx.HTTPError as exc:
            log.warning("  Network error for %s: %s (attempt %d/%d)", prompt.shot_id, exc, attempt, _MAX_RETRIES)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY * (2 ** (attempt - 1)))

    log.error("  Failed to generate %s after %d attempts", prompt.shot_id, _MAX_RETRIES)
    return False


def generate_all_visuals(
    prompts: list[ShotPrompt],
    assets_dir: Path,
    api_key: Optional[str] = None,
) -> dict[str, Path]:
    """Generate images for all shot prompts.

    Returns a mapping of shot_id → local file path for successful generations.
    """
    if api_key is None:
        api_key = _get_api_key()

    assets_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Path] = {}
    total = len(prompts)

    log.info("[bold]Generating %d visuals via Gemini Imagen[/]", total)

    for i, prompt in enumerate(prompts, 1):
        log.info("[%d/%d] Generating %s …", i, total, prompt.shot_id)
        safe_id = prompt.shot_id.replace("/", "_").replace(" ", "_")
        output_path = assets_dir / f"{safe_id}.png"

        if generate_image(prompt, output_path, api_key):
            results[prompt.shot_id] = output_path

        # Small delay between requests to avoid rate limiting
        if i < total:
            time.sleep(1.0)

    log.info(
        "[bold green]Visual generation complete[/] – %d/%d successful",
        len(results), total,
    )
    return results


def load_prompts_from_json(json_path: Path) -> list[ShotPrompt]:
    """Load shot prompts from shot_prompts.json."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return [ShotPrompt(**item) for item in data]


def run_visual_generator(output_dir: Path, api_key: Optional[str] = None) -> dict[str, Path]:
    """Top-level entry point: load prompts and generate all visuals.

    Returns mapping of shot_id → file path.
    """
    json_path = output_dir / "ai_generation" / "shot_prompts.json"
    if not json_path.exists():
        log.error("shot_prompts.json not found at %s", json_path)
        return {}

    prompts = load_prompts_from_json(json_path)
    assets_dir = output_dir / "assets" / "generated"
    return generate_all_visuals(prompts, assets_dir, api_key)
