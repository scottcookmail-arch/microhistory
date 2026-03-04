"""Module 1 – Topic Research.

Uses official APIs (Wikipedia, Wikimedia Commons, Library of Congress,
Internet Archive) to gather a factual outline and licensed media for a
given topic.  Outputs ``sources.json`` and a compact facts outline.
"""

from __future__ import annotations

import hashlib
import json
import re
import textwrap
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

import httpx

from microhistory.logging_config import get_logger
from microhistory.models import (
    AssetType,
    FactItem,
    License,
    ResearchResult,
    SourceAsset,
)

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_LOC_API = "https://www.loc.gov/search/"
_IA_API = "https://archive.org/advancedsearch.php"

_TIMEOUT = httpx.Timeout(30.0)
_HEADERS = {
    "User-Agent": "MicroHistory/0.1.0 (https://github.com/microhistory; educational project)",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _asset_id(url: str) -> str:
    """Deterministic short ID from a URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def _classify_filetype(filename: str) -> tuple[str, AssetType]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mapping = {
        "jpg": AssetType.IMAGE, "jpeg": AssetType.IMAGE, "png": AssetType.IMAGE,
        "gif": AssetType.IMAGE, "svg": AssetType.IMAGE, "tif": AssetType.IMAGE,
        "tiff": AssetType.IMAGE, "webp": AssetType.IMAGE,
        "mp4": AssetType.VIDEO, "webm": AssetType.VIDEO, "ogv": AssetType.VIDEO,
        "mp3": AssetType.AUDIO, "ogg": AssetType.AUDIO, "wav": AssetType.AUDIO,
        "flac": AssetType.AUDIO,
        "pdf": AssetType.DOCUMENT, "djvu": AssetType.DOCUMENT,
    }
    return ext, mapping.get(ext, AssetType.IMAGE)


_LICENSE_PATTERNS: list[tuple[str, License]] = [
    ("public domain", License.PUBLIC_DOMAIN),
    ("pd-us", License.PUBLIC_DOMAIN),
    ("pd-old", License.PUBLIC_DOMAIN),
    ("pd-art", License.PUBLIC_DOMAIN),
    ("cc0", License.CC0),
    ("cc-zero", License.CC0),
    ("cc-by-sa", License.CC_BY_SA),
    ("cc-by-nc", License.CC_BY_NC),
    ("cc-by", License.CC_BY),
    ("united states government", License.US_GOV),
    ("usgovernment", License.US_GOV),
    ("usgov", License.US_GOV),
]


def _detect_license(text: str) -> License:
    """Heuristic license detection from category/description text."""
    lower = text.lower()
    for pattern, lic in _LICENSE_PATTERNS:
        if pattern in lower:
            return lic
    return License.UNKNOWN


# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------

def fetch_wikipedia_summary(topic: str, client: httpx.Client) -> tuple[str, list[FactItem], list[str]]:
    """Return (summary, facts, timeline) from Wikipedia."""
    log.info("[bold blue]Wikipedia[/] – fetching summary for '%s'", topic)
    params = {
        "action": "query",
        "titles": topic,
        "prop": "extracts|categories",
        "exintro": False,
        "explaintext": True,
        "format": "json",
        "redirects": 1,
    }
    resp = client.get(_WIKIPEDIA_API, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    if not pages:
        log.warning("No Wikipedia page found for '%s'", topic)
        return "", [], []

    page = next(iter(pages.values()))
    extract: str = page.get("extract", "")
    page_title = page.get("title", topic)
    page_url = f"https://en.wikipedia.org/wiki/{quote_plus(page_title.replace(' ', '_'))}"

    # Split into paragraphs → treat each as a factual claim
    paragraphs = [p.strip() for p in extract.split("\n") if p.strip() and len(p.strip()) > 40]

    facts: list[FactItem] = []
    timeline: list[str] = []
    for para in paragraphs[:20]:  # cap
        # Extract sentences as individual facts
        sentences = re.split(r'(?<=[.!?])\s+', para)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20:
                continue
            facts.append(FactItem(
                claim=sentence,
                source_urls=[page_url],
                confidence="medium",
            ))
            # Look for years to build a timeline
            years = re.findall(r'\b(1[0-9]{3}|20[0-2][0-9])\b', sentence)
            if years:
                timeline.append(f"{years[0]}: {sentence[:120]}")

    summary = extract[:2000] if extract else ""
    log.info("[bold blue]Wikipedia[/] – got %d facts, %d timeline entries", len(facts), len(timeline))
    return summary, facts, sorted(set(timeline))


# ---------------------------------------------------------------------------
# Wikimedia Commons
# ---------------------------------------------------------------------------

def fetch_commons_assets(topic: str, client: httpx.Client, limit: int = 20) -> list[SourceAsset]:
    """Search Wikimedia Commons for licensed media."""
    log.info("[bold green]Commons[/] – searching for '%s' media", topic)
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap|video {topic}",
        "gsrlimit": str(limit),
        "prop": "imageinfo|categories",
        "iiprop": "url|extmetadata|mediatype|size",
        "format": "json",
    }
    resp = client.get(_COMMONS_API, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})

    assets: list[SourceAsset] = []
    for page in pages.values():
        title = page.get("title", "")
        info_list = page.get("imageinfo", [])
        if not info_list:
            continue
        info = info_list[0]
        url = info.get("url", "")
        if not url:
            continue

        # License detection from categories + extmetadata
        cats = " ".join(c.get("title", "") for c in page.get("categories", []))
        ext_meta = info.get("extmetadata", {})
        license_text = ext_meta.get("LicenseShortName", {}).get("value", "")
        combined_license_text = f"{cats} {license_text}"
        detected_license = _detect_license(combined_license_text)

        desc = ext_meta.get("ImageDescription", {}).get("value", "")
        # Strip HTML tags from description
        desc = re.sub(r'<[^>]+>', '', desc)[:300]

        attribution = ext_meta.get("Artist", {}).get("value", "")
        attribution = re.sub(r'<[^>]+>', '', attribution)[:200]
        if not attribution:
            attribution = f"Wikimedia Commons – {title}"

        filetype, asset_type = _classify_filetype(url)

        assets.append(SourceAsset(
            asset_id=_asset_id(url),
            url=f"https://commons.wikimedia.org/wiki/{quote_plus(title.replace(' ', '_'))}",
            download_url=url,
            title=title.replace("File:", ""),
            description=desc,
            source_api="wikimedia_commons",
            license=detected_license,
            attribution=attribution,
            filetype=filetype,
            asset_type=asset_type,
            relevance_score=0.7,
        ))

    log.info("[bold green]Commons[/] – found %d assets", len(assets))
    return assets


# ---------------------------------------------------------------------------
# Library of Congress
# ---------------------------------------------------------------------------

def fetch_loc_assets(topic: str, client: httpx.Client, limit: int = 10) -> list[SourceAsset]:
    """Search Library of Congress for public-domain media."""
    log.info("[bold yellow]LoC[/] – searching for '%s'", topic)
    params = {
        "q": topic,
        "fo": "json",
        "c": str(limit),
        "fa": "online-format:image",
    }
    try:
        resp = client.get(_LOC_API, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        log.warning("LoC search failed: %s", exc)
        return []

    results = data.get("results", [])
    assets: list[SourceAsset] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        item_url = item.get("url", "") or item.get("id", "")
        title = item.get("title", "Untitled")
        description = item.get("description", [""])[0] if isinstance(item.get("description"), list) else str(item.get("description", ""))

        # LoC items are generally US Government works / public domain
        image_url = ""
        if isinstance(item.get("image_url"), list) and item["image_url"]:
            image_url = item["image_url"][0]
        elif isinstance(item.get("image_url"), str):
            image_url = item["image_url"]

        if not item_url:
            continue

        assets.append(SourceAsset(
            asset_id=_asset_id(item_url),
            url=item_url,
            download_url=image_url or None,
            title=title[:200],
            description=description[:300],
            source_api="library_of_congress",
            license=License.US_GOV,
            attribution=f"Library of Congress – {title[:100]}",
            filetype="jpg",
            asset_type=AssetType.IMAGE,
            relevance_score=0.6,
        ))

    log.info("[bold yellow]LoC[/] – found %d assets", len(assets))
    return assets


# ---------------------------------------------------------------------------
# Internet Archive
# ---------------------------------------------------------------------------

def fetch_ia_assets(topic: str, client: httpx.Client, limit: int = 10) -> list[SourceAsset]:
    """Search Internet Archive for public-domain media."""
    log.info("[bold magenta]IA[/] – searching for '%s'", topic)
    query = f'("{topic}") AND mediatype:(image OR movies) AND licenseurl:(*creativecommons* OR *publicdomain*)'
    params = {
        "q": query,
        "fl[]": "identifier,title,description,mediatype,licenseurl",
        "rows": str(limit),
        "page": "1",
        "output": "json",
    }
    try:
        resp = client.get(_IA_API, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        log.warning("Internet Archive search failed: %s", exc)
        return []

    docs = data.get("response", {}).get("docs", [])
    assets: list[SourceAsset] = []
    for doc in docs:
        identifier = doc.get("identifier", "")
        if not identifier:
            continue
        item_url = f"https://archive.org/details/{identifier}"
        title = doc.get("title", identifier)
        desc = doc.get("description", "")
        if isinstance(desc, list):
            desc = desc[0] if desc else ""
        desc = re.sub(r'<[^>]+>', '', str(desc))[:300]
        license_url = doc.get("licenseurl", "")
        detected = _detect_license(license_url)
        media = doc.get("mediatype", "")
        atype = AssetType.VIDEO if media == "movies" else AssetType.IMAGE

        assets.append(SourceAsset(
            asset_id=_asset_id(item_url),
            url=item_url,
            title=title[:200],
            description=desc,
            source_api="internet_archive",
            license=detected if detected != License.UNKNOWN else License.PUBLIC_DOMAIN,
            attribution=f"Internet Archive – {title[:100]}",
            filetype="mp4" if atype == AssetType.VIDEO else "jpg",
            asset_type=atype,
            relevance_score=0.5,
        ))

    log.info("[bold magenta]IA[/] – found %d assets", len(assets))
    return assets


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------

def download_asset(asset: SourceAsset, dest_dir: Path, client: httpx.Client) -> Optional[Path]:
    """Download a single asset to *dest_dir*.  Returns local path or None."""
    url = asset.download_url or asset.url
    if not url or url.startswith("https://archive.org/details/"):
        return None  # detail page, not a direct file

    safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', asset.title[:60])
    ext = asset.filetype or "bin"
    dest = dest_dir / f"{asset.asset_id}_{safe_name}.{ext}"
    if dest.exists():
        return dest

    log.info("  Downloading %s …", dest.name)
    try:
        with client.stream("GET", url, timeout=_TIMEOUT, follow_redirects=True) as r:
            r.raise_for_status()
            dest_dir.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(8192):
                    f.write(chunk)
        asset.local_path = str(dest)
        return dest
    except httpx.HTTPError as exc:
        log.warning("  Download failed for %s: %s", asset.title[:40], exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def research_topic(
    topic: str,
    download: bool = False,
    output_dir: Optional[Path] = None,
) -> ResearchResult:
    """Run the full research pipeline for *topic*.

    Returns a ``ResearchResult`` with facts, timeline, and assets.
    If *download* is True, assets are saved under *output_dir*/assets/.
    """
    log.info("[bold]Starting research for topic: [cyan]%s[/cyan][/]", topic)

    with httpx.Client(follow_redirects=True, headers=_HEADERS) as client:
        # 1. Wikipedia
        try:
            summary, facts, timeline = fetch_wikipedia_summary(topic, client)
        except httpx.HTTPError as exc:
            log.warning("Wikipedia fetch failed: %s", exc)
            summary, facts, timeline = "", [], []

        # 2. Wikimedia Commons
        try:
            commons = fetch_commons_assets(topic, client)
        except httpx.HTTPError as exc:
            log.warning("Commons fetch failed: %s", exc)
            commons = []

        # 3. Library of Congress
        loc = fetch_loc_assets(topic, client)

        # 4. Internet Archive
        ia = fetch_ia_assets(topic, client)

        # Merge assets & filter for commercial safety
        all_assets = commons + loc + ia
        safe_assets = [a for a in all_assets if a.is_commercial_safe]
        skipped = len(all_assets) - len(safe_assets)
        if skipped:
            log.info("Filtered out %d assets with non-commercial licenses", skipped)

        # Sort by relevance
        safe_assets.sort(key=lambda a: a.relevance_score, reverse=True)

        # Optional download
        if download and output_dir:
            assets_dir = output_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            for asset in safe_assets:
                download_asset(asset, assets_dir, client)

    result = ResearchResult(
        topic=topic,
        summary=summary,
        facts=facts,
        assets=safe_assets,
        timeline=timeline,
    )
    log.info(
        "[bold green]Research complete[/] – %d facts, %d timeline entries, %d safe assets",
        len(facts), len(timeline), len(safe_assets),
    )
    return result


def write_sources_json(result: ResearchResult, path: Path) -> None:
    """Serialise the research result to sources.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    log.info("Wrote %s", path)
