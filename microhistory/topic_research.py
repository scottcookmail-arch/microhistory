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


# ---------------------------------------------------------------------------
# Strange / unusual event discovery for Shorts
# ---------------------------------------------------------------------------

# Wikipedia categories rich in strange, viral-worthy historical events
_STRANGE_EVENT_CATEGORIES = [
    "Unsolved_deaths",
    "Hoaxes_in_science",
    "Mass_hysteria",
    "Unexplained_disappearances",
    "Historical_mysteries",
    "Ancient_unsolved_mysteries",
    "Military_scandals",
    "Conspiracy_theories",
    "Anomalous_experiences",
    "Maritime_mysteries",
    "Curses",
    "Archaeological_discoveries",
    "Lost_cities",
    "Unusual_deaths",
    "History_of_espionage",
]

# Curated seed list of strange events with high Shorts potential
_SEED_STRANGE_EVENTS: list[dict[str, str]] = [
    {"topic": "Dancing plague of 1518", "date": "1518", "hook": "An entire city danced itself to death."},
    {"topic": "Great Molasses Flood", "date": "1919", "hook": "A 25-foot wave of molasses killed 21 people."},
    {"topic": "Tunguska event", "date": "1908", "hook": "Something flattened 80 million trees — and nobody knows what."},
    {"topic": "Dyatlov Pass incident", "date": "1959", "hook": "Nine hikers died in the most bizarre way imaginable."},
    {"topic": "The Wow! signal", "date": "1977", "hook": "We may have heard from aliens — once."},
    {"topic": "Voynich manuscript", "date": "1400s", "hook": "A book no one can read has baffled experts for 600 years."},
    {"topic": "Lead masks of Vintem Hill", "date": "1966", "hook": "Two men were found dead wearing homemade lead masks."},
    {"topic": "Taos Hum", "date": "1990s", "hook": "A town heard a hum that no machine could find."},
    {"topic": "Sailing stones", "date": "ongoing", "hook": "Rocks that move on their own across the desert."},
    {"topic": "Mary Celeste", "date": "1872", "hook": "A ghost ship found drifting with no crew — but dinner still on the table."},
    {"topic": "Flannan Isles mystery", "date": "1900", "hook": "Three lighthouse keepers vanished without a trace."},
    {"topic": "Spring Heeled Jack", "date": "1837", "hook": "A fire-breathing figure terrorized Victorian London."},
    {"topic": "The Hinterkaifeck murders", "date": "1922", "hook": "Someone lived in the family's attic before killing them all."},
    {"topic": "Amber Room", "date": "1941", "hook": "The Nazis stole a room made of 6 tons of amber — it was never found."},
    {"topic": "Codex Gigas", "date": "1200s", "hook": "A monk allegedly wrote this giant book in one night — with the Devil's help."},
    {"topic": "Phaistos Disc", "date": "1700 BC", "hook": "A 3,700-year-old disc covered in symbols no one can decode."},
    {"topic": "Roanoke Colony", "date": "1590", "hook": "117 colonists disappeared and left only one word behind: CROATOAN."},
    {"topic": "The Green Children of Woolpit", "date": "1100s", "hook": "Two green-skinned children appeared in an English village from nowhere."},
    {"topic": "Eruption of Mount Tambora", "date": "1815", "hook": "A volcano erased summer for an entire year."},
    {"topic": "Baghdad Battery", "date": "200 BC", "hook": "Someone may have invented the battery 2,000 years early."},
    {"topic": "Antikythera mechanism", "date": "100 BC", "hook": "An ancient Greek computer that shouldn't exist."},
    {"topic": "London Beer Flood", "date": "1814", "hook": "A tidal wave of beer destroyed an entire neighborhood."},
    {"topic": "Emu War", "date": "1932", "hook": "Australia went to war against emus — and lost."},
    {"topic": "The Kentucky meat shower", "date": "1876", "hook": "Chunks of meat fell from a clear sky in Kentucky."},
    {"topic": "Bloop (sound)", "date": "1997", "hook": "The ocean made a sound so loud it was heard 5,000 km away."},
    {"topic": "SS Ourang Medan", "date": "1947", "hook": "Every crew member was found dead — frozen in terror."},
    {"topic": "Cicada 3301", "date": "2012", "hook": "The internet's most mysterious puzzle — and nobody knows who made it."},
    {"topic": "Numbers stations", "date": "1960s", "hook": "Secret radio stations broadcasting coded messages to spies — still running today."},
    {"topic": "Great Emu War", "date": "1932", "hook": "The Australian military lost a war to birds."},
    {"topic": "The Man from Taured", "date": "1954", "hook": "A man arrived at an airport from a country that doesn't exist."},
]


def discover_strange_events(
    count: int = 5,
    exclude_topics: Optional[list[str]] = None,
) -> list[dict[str, str]]:
    """Return a list of strange historical event dicts from the seed bank
    and Wikipedia category pages.

    Each dict has keys: ``topic``, ``date``, ``hook``.
    """
    import random

    exclude = set(t.lower() for t in (exclude_topics or []))
    pool = [
        e for e in _SEED_STRANGE_EVENTS
        if e["topic"].lower() not in exclude
    ]

    # Supplement with Wikipedia category scraping
    with httpx.Client(follow_redirects=True, headers=_HEADERS) as client:
        extra = _fetch_category_members(client, count=count * 2)
        for title in extra:
            if title.lower() not in exclude and not any(
                e["topic"].lower() == title.lower() for e in pool
            ):
                pool.append({
                    "topic": title,
                    "date": "",
                    "hook": "",
                })

    random.shuffle(pool)
    return pool[:count]


def _fetch_category_members(
    client: httpx.Client,
    count: int = 20,
) -> list[str]:
    """Fetch article titles from random Wikipedia strange-event categories."""
    import random

    cats = random.sample(
        _STRANGE_EVENT_CATEGORIES,
        min(3, len(_STRANGE_EVENT_CATEGORIES)),
    )
    titles: list[str] = []

    for cat in cats:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{cat}",
            "cmlimit": "20",
            "cmtype": "page",
            "format": "json",
        }
        try:
            resp = client.get(_WIKIPEDIA_API, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            members = resp.json().get("query", {}).get("categorymembers", [])
            for m in members:
                title = m.get("title", "")
                if title and ":" not in title:
                    titles.append(title)
        except httpx.HTTPError as exc:
            log.warning("Category fetch failed for %s: %s", cat, exc)

        if len(titles) >= count:
            break

    return titles[:count]


def research_short_topic(topic: str) -> ResearchResult:
    """Lightweight research pass for a single Shorts episode.

    Fetches Wikipedia summary (trimmed) and a few Wikimedia Commons assets.
    Faster than the full ``research_topic`` since Shorts only need 120 words.
    """
    log.info("[bold]Quick research for Short: [cyan]%s[/cyan][/]", topic)

    with httpx.Client(follow_redirects=True, headers=_HEADERS) as client:
        try:
            summary, facts, timeline = fetch_wikipedia_summary(topic, client)
        except httpx.HTTPError:
            summary, facts, timeline = "", [], []

        try:
            commons = fetch_commons_assets(topic, client, limit=5)
        except httpx.HTTPError:
            commons = []

    safe = [a for a in commons if a.is_commercial_safe]
    return ResearchResult(
        topic=topic,
        summary=summary[:800],
        facts=facts[:10],
        assets=safe,
        timeline=timeline[:5],
    )
