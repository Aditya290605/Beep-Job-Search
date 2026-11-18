"""
backend/app/adapters/github_jobs.py - Open-Source GitHub Fresher Feeds Adapter

Pulls entry-level, graduate, and internship positions from curated,
daily-updating community fresher lists (e.g. New-Grad-Jobs, 2026 Grad Positions).
Permissive MIT/CC0 open-source licensing.
Connects directly to raw markdown tables and extracts verified company career links.
"""

import re
import json
import logging
from typing import List
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
from app.models import RawJob
from app.adapters.base import (
    clean_html,
    is_india_location,
    is_fresher_job,
    extract_job_type,
    fetch_json,
    SENIOR_REGEX
)

logger = logging.getLogger(__name__)

# Verified curated community repositories syncing directly with company ATS portals
GITHUB_FEEDS = [
    {
        "name": "India-Tech-Internships-Live-JSON",
        "url": "https://raw.githubusercontent.com/Sarthzk/internship-tracker/main/data/listings.json",
        "format": "json"
    },
    {
        "name": "India-Tech-Internships-Tracker",
        "url": "https://raw.githubusercontent.com/Sarthzk/internship-tracker/main/README.md",
        "format": "markdown"
    },
    {
        "name": "New-Grad-Jobs",
        "url": "https://raw.githubusercontent.com/ambicuity/New-Grad-Jobs/main/README.md",
        "format": "markdown"
    },
    {
        "name": "SimplifyJobs-New-Grad",
        "url": "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md",
        "format": "markdown"
    },
    {
        "name": "SimplifyJobs-Internships",
        "url": "https://raw.githubusercontent.com/SimplifyJobs/Summer2025-Internships/dev/README.md",
        "format": "markdown"
    },
    {
        "name": "SWE-College-Jobs-2026",
        "url": "https://raw.githubusercontent.com/speedyapply/2026-SWE-College-Jobs/main/README.md",
        "format": "markdown"
    }
]


def clean_markdown_cell(cell: str) -> str:
    """Removes markdown bold, italics, HTML tags, and markdown link anchors to yield clean text."""
    # Drop <sub> captions (e.g. "Fintech", degree notes) so they don't leak into names/titles
    text = re.sub(r'<sub>.*?</sub>', ' ', cell, flags=re.S)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Remove emoji / pictographs and escaped markdown underscores
    text = re.sub(r'[\U0001F000-\U0001FAFF\u2600-\u27BF]', '', text)
    text = text.replace('\\_', ' ')
    # Extract anchor text from markdown links: [Text](url) -> Text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Strip markdown bold/italics
    text = text.replace('**', '').replace('*', '').strip()
    return re.sub(r'\s+', ' ', text).strip()


def extract_url_from_row(line: str) -> str:
    """Extracts first valid external application link from a markdown row."""
    # Pattern 1: [Apply](url) or [Apply](<url>) or [Link](url)
    apply_match = re.search(r'\[(?:Apply|Link|Apply Here|Submit)\]\((?:<([^>]+)>|([^)]+))\)', line, re.I)
    if apply_match:
        url = (apply_match.group(1) or apply_match.group(2) or "").strip()
        if url.startswith("http"):
            return url

    # Pattern 2: <a href="url">
    href_match = re.search(r'href=["\'](https?://[^"\']+)["\']', line, re.I)
    if href_match:
        return href_match.group(1).strip()

    # Pattern 3: Any markdown link pointing to an external job page
    for match in re.finditer(r'\[[^\]]+\]\((https?://[^)]+)\)', line):
        url = match.group(1).strip()
        # Avoid linking to GitHub repos or contributor profiles
        if "github.com" not in url:
            return url

    return ""


def fetch_single_feed(feed: dict) -> List[RawJob]:
    """Fetches and parses a single GitHub fresher feed (JSON or Markdown)."""
    feed_jobs: List[RawJob] = []
    try:
        req = urllib.request.Request(feed["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            content = r.read().decode("utf-8", errors="ignore")

        # JSON Feed handler
        if feed.get("format") == "json":
            data = json.loads(content)
            for item in data:
                # Tracker keeps closed listings for history; only open ones are real openings
                if item.get("status") != "open":
                    continue
                title = clean_markdown_cell(item.get("title", ""))
                company = clean_markdown_cell(item.get("company", ""))
                apply_url = (item.get("url") or "").strip()
                locs = item.get("locations") or []
                location_raw = ", ".join(locs) if locs else "India"
                posted_date = item.get("last_seen") or item.get("date_posted") or item.get("first_seen")

                if not apply_url or not apply_url.startswith("http"):
                    continue

                valid_loc, city = is_india_location(location_raw)
                if not valid_loc or city == "Unknown":
                    continue

                if SENIOR_REGEX.search(title):
                    continue

                category = item.get("category", "")
                is_intern = "intern" in title.lower() or "intern" in category.lower()
                job_type = "internship" if is_intern else extract_job_type(title)

                feed_jobs.append(RawJob(
                    title=title,
                    company=company,
                    location_raw=location_raw,
                    city=city,
                    job_type=job_type,
                    apply_url=apply_url,
                    description=f"{title} position at {company} in {city}. Apply via official career portal.",
                    source_name="github_feeds",
                    source_job_id=re.sub(r'[^a-zA-Z0-9]', '', f"{company}_{title}")[:40],
                    posted_date=posted_date or datetime.now(timezone.utc).isoformat()
                ))
            return feed_jobs

        # Markdown Table handler
        lines = content.splitlines()
        for line in lines:
            if "|" not in line:
                continue

            cells = [c.strip() for c in line.split("|")]
            # Strip leading and trailing empty cells from | row |
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]

            if len(cells) < 3:
                continue

            # Header lines check
            if any("---" in c for c in cells):
                continue

            # Extract URL
            apply_url = extract_url_from_row(line)
            if not apply_url:
                continue

            company = clean_markdown_cell(cells[0])
            title = clean_markdown_cell(cells[1])
            location_raw = clean_markdown_cell(cells[2]) if len(cells) > 2 else ""

            # If company or title looks like header, skip
            if company.lower() in ("company", "name", "organization") or title.lower() in ("role", "position", "job title"):
                continue

            # Filter by location (must be India, drop Unknown)
            valid_loc, city = is_india_location(location_raw)
            if not valid_loc or city == "Unknown":
                # Check if location was in cell 3 instead
                if len(cells) > 3:
                    alt_loc = clean_markdown_cell(cells[3])
                    valid_loc, city = is_india_location(alt_loc)
                    if valid_loc and city != "Unknown":
                        location_raw = alt_loc
                    else:
                        continue
                else:
                    continue

            # Curated fresher feed logic:
            if SENIOR_REGEX.search(title):
                continue
            if not is_fresher_job(title) and not any(k in feed["name"].lower() for k in ["grad", "intern", "college"]):
                continue

            is_intern = "intern" in feed["name"].lower() or "intern" in title.lower()
            job_type = "internship" if is_intern else extract_job_type(title)
            now_iso = datetime.now(timezone.utc).isoformat()

            feed_jobs.append(RawJob(
                title=title,
                company=company,
                location_raw=location_raw,
                city=city,
                job_type=job_type,
                apply_url=apply_url,
                description=f"{title} position at {company} in {city}. Apply via official career portal.",
                source_name="github_feeds",
                source_job_id=re.sub(r'[^a-zA-Z0-9]', '', f"{company}_{title}")[:40],
                posted_date=now_iso
            ))
    except Exception as e:
        logger.warning(f"Failed to fetch GitHub feed {feed['name']}: {e}")

    return feed_jobs


def fetch_github_fresher_jobs() -> List[RawJob]:
    """Fetches and normalizes fresher jobs from open GitHub aggregators concurrently."""
    results: List[RawJob] = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fetch_single_feed, feed) for feed in GITHUB_FEEDS]
        for f in as_completed(futures):
            try:
                results.extend(f.result())
            except Exception:
                pass

    logger.info(f"GitHub fresher feed adapter collected {len(results)} fresher jobs")
    return results
