"""Module 8 – Scheduler.

Planning-only module: generates schedule recommendations, an upload
calendar, and a posting checklist.  Does NOT auto-post or handle
credentials.
"""

from __future__ import annotations

import csv
import io
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

from microhistory.logging_config import get_logger
from microhistory.models import CalendarEntry, Schedule, VideoType

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Schedule recommendation
# ---------------------------------------------------------------------------

def _generate_recommendation(topic: str) -> str:
    """Generate a schedule strategy document."""
    return textwrap.dedent(f"""\
        # Schedule Recommendation: {topic}

        ## Strategy Overview

        Consistent posting is the single most important factor for YouTube growth
        in the documentary/history niche.  The algorithm rewards channels that
        publish on a predictable cadence.

        ## Recommended Cadence

        ### Long-form Episodes
        - **Frequency:** 2–3 episodes per week
        - **Best days:** Tuesday, Thursday, Saturday
        - **Best times:** 2:00 PM – 5:00 PM EST (peak browse time for English-speaking audiences)
        - **Rationale:** Spacing uploads allows each video 48+ hours of initial algorithmic testing
          before the next video competes for impressions.

        ### YouTube Shorts
        - **Frequency:** 1–2 Shorts per day
        - **Best times:** 8:00 AM, 12:00 PM, 6:00 PM EST
        - **Rationale:** Shorts feed is active during commute and lunch hours.
          Multiple daily uploads increase surface area in the Shorts shelf.

        ## Content Strategy

        1. **Lead with a Short** – Post a teaser Short 6–12 hours before the full episode.
           Include a CTA: "Full episode drops at [time] – subscribe!"
        2. **Stagger Shorts** – Spread the 3–6 Shorts from each episode across 2–3 days
           after the long-form upload.
        3. **Repurpose** – Each Short should standalone but also drive traffic to the long-form.

        ## Thumbnail & Title A/B Testing

        - Prepare 2–3 thumbnail variants per video.
        - After 48 hours, check CTR in YouTube Analytics.
        - Swap thumbnail if CTR is below 5%.

        ## Community Engagement

        - Pin a comment with a question related to the topic (drives comment velocity).
        - Reply to top comments within the first 2 hours (signals engagement to algorithm).
        - Use Community tab to tease upcoming episodes.

        ## Growth Milestones

        | Milestone | Target | Key Action |
        |-----------|--------|------------|
        | First 30 days | 20+ videos, build library | Focus on volume and consistency |
        | 100 subscribers | Social proof | Celebrate with a community post |
        | 1,000 subscribers | Monetisation threshold | Optimize CTR and watch time |
        | 4,000 watch hours | Monetisation | Apply for YouTube Partner Program |
    """)


# ---------------------------------------------------------------------------
# Upload calendar
# ---------------------------------------------------------------------------

def _generate_calendar(
    topic: str,
    num_shorts: int = 6,
    days: int = 30,
) -> list[CalendarEntry]:
    """Generate a 30-day upload calendar."""
    entries: list[CalendarEntry] = []
    start_date = datetime.now()

    # Pattern: T/Th/Sat = long-form, daily shorts
    long_days = {1, 3, 5}  # Tue, Thu, Sat (0=Mon)
    short_times = ["08:00", "12:00", "18:00"]

    long_count = 0
    short_counter = 0
    topics_pool = [
        topic,
        f"{topic} – Part 2",
        f"The Aftermath of {topic}",
        f"Mysteries Surrounding {topic}",
        f"People of {topic}",
        f"{topic} – Theories",
        f"Places of {topic}",
        f"Timeline of {topic}",
    ]

    for day_offset in range(days):
        current = start_date + timedelta(days=day_offset)
        date_str = current.strftime("%Y-%m-%d")
        weekday = current.weekday()

        # Long-form on designated days
        if weekday in long_days:
            ep_topic = topics_pool[long_count % len(topics_pool)]
            entries.append(CalendarEntry(
                date=date_str,
                time="15:00",
                video_type=VideoType.LONG,
                topic=ep_topic,
                title_draft=f"The Untold Story of {ep_topic}",
                cta="Subscribe for more hidden history!",
                asset_notes="Ensure thumbnail, end screen, and cards are set before publishing.",
            ))
            long_count += 1

        # 1–2 Shorts per day
        shorts_today = 2 if weekday in long_days else 1
        for s in range(shorts_today):
            short_topic = topics_pool[short_counter % len(topics_pool)]
            entries.append(CalendarEntry(
                date=date_str,
                time=short_times[s % len(short_times)],
                video_type=VideoType.SHORT,
                topic=short_topic,
                title_draft=f"Did You Know? {short_topic} #{short_counter + 1}",
                cta="Full episode on our channel!",
                asset_notes=f"Short {(short_counter % num_shorts) + 1} from episode pack.",
            ))
            short_counter += 1

    return entries


# ---------------------------------------------------------------------------
# Posting checklist
# ---------------------------------------------------------------------------

def _generate_checklist() -> str:
    """Generate a manual posting checklist for YouTube Studio."""
    return textwrap.dedent("""\
        # Posting Checklist

        Use this checklist for every upload in YouTube Studio.

        ## Pre-Upload
        - [ ] Verify video file plays correctly and audio is synced
        - [ ] Confirm all text overlays are readable
        - [ ] Check that no copyrighted content is present
        - [ ] Review ATTRIBUTION.txt for required credits

        ## Upload (YouTube Studio)
        - [ ] Upload video file
        - [ ] Set title (from title_options.txt)
        - [ ] Paste description (from description_long.txt)
        - [ ] Add tags (from tags.txt)
        - [ ] Set visibility: Scheduled (per upload_calendar.csv)
        - [ ] Select category: Education or Entertainment

        ## Metadata
        - [ ] Add chapter timestamps to description (from chapters.txt)
        - [ ] Add attribution/source credits at bottom of description
        - [ ] Set video language: English
        - [ ] Add subtitles/CC if available

        ## Thumbnail
        - [ ] Upload custom thumbnail (follow thumbnail_brief.txt concepts)
        - [ ] Verify thumbnail is 1280x720, <2 MB
        - [ ] Check text readability at small sizes (mobile preview)

        ## End Screen & Cards
        - [ ] Add end screen: subscribe button + best-for-viewer video
        - [ ] Add card linking to related episode at turning-point timestamp
        - [ ] Add card linking to playlist at 30-second mark

        ## Shorts-Specific
        - [ ] Verify aspect ratio is 9:16 (vertical)
        - [ ] Duration is under 60 seconds
        - [ ] Captions are burned in or added as subtitles
        - [ ] Add #Shorts tag in title or description

        ## Post-Publish
        - [ ] Pin a discussion-starter comment
        - [ ] Share to Community tab with teaser text
        - [ ] Reply to first 5 comments within 2 hours
        - [ ] After 48 hours: check CTR, consider thumbnail swap if <5%
    """)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_schedule(
    topic: str,
    num_shorts: int = 6,
) -> Schedule:
    """Generate the full scheduling pack."""
    log.info("[bold]Generating schedule for [cyan]%s[/cyan][/]", topic)

    schedule = Schedule(
        recommendation_md=_generate_recommendation(topic),
        calendar=_generate_calendar(topic, num_shorts),
        checklist_md=_generate_checklist(),
    )

    log.info(
        "[bold green]Schedule generated[/] – %d calendar entries",
        len(schedule.calendar),
    )
    return schedule


def write_schedule(schedule: Schedule, output_dir: Path) -> None:
    """Write scheduling files to the output directory."""
    sched_dir = output_dir / "scheduling"
    sched_dir.mkdir(parents=True, exist_ok=True)

    # Recommendation
    (sched_dir / "schedule_recommendation.md").write_text(
        schedule.recommendation_md, encoding="utf-8",
    )

    # Calendar CSV
    csv_path = sched_dir / "upload_calendar.csv"
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "time", "type", "topic", "title_draft", "cta", "asset_notes"])
    for entry in schedule.calendar:
        writer.writerow([
            entry.date, entry.time, entry.video_type.value,
            entry.topic, entry.title_draft, entry.cta, entry.asset_notes,
        ])
    csv_path.write_text(buf.getvalue(), encoding="utf-8")

    # Checklist
    (sched_dir / "posting_checklist.md").write_text(
        schedule.checklist_md, encoding="utf-8",
    )

    log.info("Wrote scheduling files to %s", sched_dir)
