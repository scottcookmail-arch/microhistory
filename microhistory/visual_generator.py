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


# ---------------------------------------------------------------------------
# Shorts-specific video clip generation (Veo3 / Runway)
# ---------------------------------------------------------------------------

_RUNWAY_API_BASE = "https://api.dev.runwayml.com/v1"
_VEO3_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

_SHORTS_CAMERA_MOTIONS = [
    "slow_push", "slow_pull", "pan_left", "tilt_up", "dolly_forward",
]

_SHORTS_CLIP_STYLES = [
    "Cinematic documentary, muted earth tones, film grain, volumetric lighting",
    "Dark atmospheric, desaturated, dramatic shadows, period-accurate",
    "Sepia-toned archival footage look, subtle vignette, warm highlights",
    "Cold blue moonlight, mysterious atmosphere, fog, slow reveal",
    "Golden hour, sweeping landscape, cinematic depth of field",
]


def build_shorts_clip_prompts(
    topic: str,
    script_text: str,
    num_clips: int = 5,
    target_duration: float = 40.0,
) -> list[dict[str, str]]:
    """Build video generation prompts for Shorts clips.

    Returns a list of dicts with keys: prompt, camera_motion, duration_sec.
    Each clip targets target_duration / num_clips seconds.
    """
    from microhistory.models import ShortsVideoSpec

    clip_duration = round(target_duration / num_clips, 1)
    words = script_text.split()
    words_per_clip = max(5, len(words) // num_clips)

    clips: list[dict[str, str]] = []
    for i in range(num_clips):
        start = i * words_per_clip
        excerpt = " ".join(words[start : start + words_per_clip])
        style = _SHORTS_CLIP_STYLES[i % len(_SHORTS_CLIP_STYLES)]
        motion = _SHORTS_CAMERA_MOTIONS[i % len(_SHORTS_CAMERA_MOTIONS)]

        prompt = (
            f"{style}. Scene depicting: {excerpt}. "
            f"Historical setting related to {topic}. "
            f"Camera: {motion.replace('_', ' ')}. "
            f"9:16 vertical portrait framing. "
            f"No text, no watermarks, no modern elements, no recognisable faces."
        )
        clips.append({
            "clip_number": str(i + 1),
            "prompt": prompt,
            "camera_motion": motion,
            "duration_sec": str(clip_duration),
        })

    return clips


def generate_shorts_clip_runway(
    prompt: str,
    output_path: Path,
    duration_sec: float = 8.0,
    api_key: Optional[str] = None,
) -> bool:
    """Generate a single video clip via the Runway Gen-3 API.

    Returns True on success, False on failure.
    Requires RUNWAY_API_KEY environment variable.
    """
    if output_path.exists() and output_path.stat().st_size > 0:
        log.info("  Skipping %s (already exists)", output_path.name)
        return True

    if api_key is None:
        api_key = os.environ.get("RUNWAY_API_KEY", "")
    if not api_key:
        log.warning("RUNWAY_API_KEY not set — cannot generate video clip")
        return False

    url = f"{_RUNWAY_API_BASE}/image_to_video"

    payload = {
        "promptText": prompt,
        "model": "gen3a_turbo",
        "duration": int(min(duration_sec, 10)),
        "ratio": "9:16",
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Runway-Version": "2024-11-06",
    }

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                # Submit generation task
                resp = client.post(url, json=payload, headers=headers)

                if resp.status_code == 429:
                    wait = _RETRY_DELAY * (2 ** (attempt - 1))
                    log.warning("  Rate limited, waiting %.0fs", wait)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                task = resp.json()
                task_id = task.get("id", "")

                if not task_id:
                    log.warning("  No task ID returned for clip")
                    return False

                # Poll for completion
                result_url = _poll_runway_task(task_id, api_key)
                if not result_url:
                    return False

                # Download the generated video
                dl_resp = client.get(result_url, timeout=_TIMEOUT)
                dl_resp.raise_for_status()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(dl_resp.content)
                log.info("  Generated clip %s", output_path.name)
                return True

        except httpx.HTTPError as exc:
            log.warning("  Runway error: %s (attempt %d/%d)", exc, attempt, _MAX_RETRIES)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY * (2 ** (attempt - 1)))

    return False


def _poll_runway_task(task_id: str, api_key: str, max_polls: int = 60) -> Optional[str]:
    """Poll a Runway task until completion, returning the output URL."""
    url = f"{_RUNWAY_API_BASE}/tasks/{task_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Runway-Version": "2024-11-06",
    }

    for _ in range(max_polls):
        time.sleep(5)
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            status = data.get("status", "")
            if status == "SUCCEEDED":
                output = data.get("output", [])
                if output:
                    return output[0] if isinstance(output, list) else output
                return None
            if status in ("FAILED", "CANCELLED"):
                log.warning("  Runway task %s: %s", task_id, status)
                return None
        except httpx.HTTPError:
            continue

    log.warning("  Runway task %s timed out", task_id)
    return None


def generate_shorts_clip_veo3(
    prompt: str,
    output_path: Path,
    duration_sec: float = 8.0,
    api_key: Optional[str] = None,
) -> bool:
    """Generate a single video clip via Google Veo 3 API.

    Returns True on success, False on failure.
    Requires GOOGLE_API_KEY environment variable.
    """
    if output_path.exists() and output_path.stat().st_size > 0:
        log.info("  Skipping %s (already exists)", output_path.name)
        return True

    if api_key is None:
        api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        log.warning("GOOGLE_API_KEY not set — cannot generate video clip via Veo3")
        return False

    url = f"{_VEO3_API_BASE}/models/veo-2.0-generate-001:predictLongRunning"

    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "aspectRatio": "9:16",
            "durationSeconds": int(min(duration_sec, 8)),
            "personGeneration": "dont_allow",
            "sampleCount": 1,
        },
    }

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=httpx.Timeout(300.0)) as client:
                resp = client.post(
                    url,
                    json=payload,
                    params={"key": api_key},
                    headers={"Content-Type": "application/json"},
                )

                if resp.status_code == 429:
                    wait = _RETRY_DELAY * (2 ** (attempt - 1))
                    log.warning("  Rate limited, waiting %.0fs", wait)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

                # Veo returns a long-running operation — poll for result
                op_name = data.get("name", "")
                if not op_name:
                    # Direct response (some endpoints)
                    predictions = data.get("predictions", [])
                    if predictions:
                        import base64
                        video_b64 = predictions[0].get("bytesBase64Encoded", "")
                        if video_b64:
                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            output_path.write_bytes(base64.b64decode(video_b64))
                            log.info("  Generated clip %s via Veo3", output_path.name)
                            return True
                    log.warning("  No operation name or predictions from Veo3")
                    return False

                # Poll the operation
                video_url = _poll_veo3_operation(op_name, api_key)
                if video_url:
                    import base64
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(base64.b64decode(video_url))
                    log.info("  Generated clip %s via Veo3", output_path.name)
                    return True
                return False

        except httpx.HTTPError as exc:
            log.warning("  Veo3 error: %s (attempt %d/%d)", exc, attempt, _MAX_RETRIES)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY * (2 ** (attempt - 1)))

    return False


def _poll_veo3_operation(
    op_name: str,
    api_key: str,
    max_polls: int = 120,
) -> Optional[str]:
    """Poll a Veo3 long-running operation. Returns base64 video data or None."""
    url = f"{_VEO3_API_BASE}/{op_name}"

    for _ in range(max_polls):
        time.sleep(5)
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.get(url, params={"key": api_key})
                resp.raise_for_status()
                data = resp.json()

            if data.get("done"):
                response = data.get("response", {})
                predictions = response.get("predictions", [])
                if predictions:
                    return predictions[0].get("bytesBase64Encoded", "")
                return None

            if data.get("error"):
                log.warning("  Veo3 operation error: %s", data["error"])
                return None

        except httpx.HTTPError:
            continue

    log.warning("  Veo3 operation %s timed out", op_name)
    return None


def generate_shorts_clips(
    clip_prompts: list[dict[str, str]],
    output_dir: Path,
    backend: str = "runway",
    api_key: Optional[str] = None,
) -> list[Path]:
    """Generate all video clips for a Short.

    *backend* can be "runway", "veo3", or "gemini_image" (fallback to stills).
    Returns list of generated file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    for clip in clip_prompts:
        num = clip["clip_number"]
        prompt = clip["prompt"]
        dur = float(clip["duration_sec"])

        if backend == "runway":
            path = output_dir / f"clip_{num}.mp4"
            ok = generate_shorts_clip_runway(prompt, path, dur, api_key)
        elif backend == "veo3":
            path = output_dir / f"clip_{num}.mp4"
            ok = generate_shorts_clip_veo3(prompt, path, dur, api_key)
        else:
            # Fallback: generate a still image via Gemini Imagen
            path = output_dir / f"clip_{num}.png"
            from microhistory.models import ShotPrompt, AspectRatio
            shot_prompt = ShotPrompt(
                shot_id=f"SHORT-CLIP-{num}",
                duration_sec=dur,
                aspect_ratio=AspectRatio.PORTRAIT,
                subject=prompt,
            )
            ok = generate_image(shot_prompt, path, api_key or _get_api_key())

        if ok:
            generated.append(path)
            log.info("[%s/%s] Clip %s generated", num, len(clip_prompts), path.name)
        else:
            log.warning("[%s/%s] Clip generation failed", num, len(clip_prompts))

        # Rate limit
        if int(num) < len(clip_prompts):
            time.sleep(2.0)

    log.info(
        "[bold green]Shorts clip generation complete[/] – %d/%d clips",
        len(generated), len(clip_prompts),
    )
    return generated
