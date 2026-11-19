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
from typing import List, Optional
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
    SENIOR_REGEX,
    SENIOR_EXP_REGEX
)
from app.verifier import verify_and_hydrate

logger = logging.getLogger(__name__)

# Verified live curated community repositories syncing directly with company ATS portals
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
        "name": "SimplifyJobs-NewGrad-Live-JSON",
        "url": "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
        "format": "json"
    },
    {
        "name": "SimplifyJobs-Summer-Live-JSON",
        "url": "https://raw.githubusercontent.com/SimplifyJobs/Summer2025-Internships/dev/.github/scripts/listings.json",
        "format": "json"
    },
    {
        "name": "New-Grad-Jobs",
        "url": "https://raw.githubusercontent.com/ambicuity/New-Grad-Jobs/main/README.md",
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

    # Pattern 2: Prioritize explicit career / ATS links in href="..."
    for m in re.finditer(r'href=["\'](https?://[^"\']+)["\']', line, re.I):
        u = m.group(1).strip()
        if any(k in u.lower() for k in ["jobs", "careers", "boards", "greenhouse", "lever", "ashby", "myworkday", "smartrecruiters", "apply", "talent", "comparably"]):
            return u

    # Pattern 3: Any markdown link pointing to an external job page
    for match in re.finditer(r'\[[^\]]+\]\((https?://[^)]+)\)', line):
        url = match.group(1).strip()
        # Avoid linking to GitHub repos or contributor profiles
        if "github.com" not in url:
            return url

    # Fallback: any external href
    for m in re.finditer(r'href=["\'](https?://[^"\']+)["\']', line, re.I):
        u = m.group(1).strip()
        if "github.com" not in u:
            return u

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
                # Sarthzk schema: status == 'open'
                if item.get("status") and item.get("status") != "open":
                    continue
                # SimplifyJobs schema: is_closed == False
                if item.get("is_closed"):
                    continue

                title = clean_markdown_cell(item.get("title", ""))
                company = clean_markdown_cell(item.get("company_name") or item.get("company") or "")
                apply_url = (item.get("url") or "").strip()
                locs = item.get("locations") or []
                location_raw = ", ".join(locs) if isinstance(locs, list) else str(locs)
                posted_date = item.get("last_seen") or item.get("date_posted") or item.get("first_seen") or item.get("date_updated")

                if not apply_url or not apply_url.startswith("http"):
                    continue

                valid_loc, city = is_india_location(location_raw, allow_bare_remote=False)
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
        last_seen_company = ""
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
            # Handle indentation symbols (↳, », -) signifying same company as previous row
            if company in ("↳", "", "»", "-") and last_seen_company:
                company = last_seen_company
            elif company.lower() not in ("company", "name", "organization", "employer"):
                last_seen_company = company

            title = clean_markdown_cell(cells[1])
            location_raw = clean_markdown_cell(cells[2]) if len(cells) > 2 else ""

            # If company or title looks like header, skip
            if company.lower() in ("company", "name", "organization") or title.lower() in ("role", "position", "job title"):
                continue

            # Filter by location (must explicitly be India / APAC / Worldwide, never bare US "Remote")
            valid_loc, city = is_india_location(location_raw, allow_bare_remote=False)
            if not valid_loc or city == "Unknown":
                # Check if location was in cell 3 instead
                if len(cells) > 3:
                    alt_loc = clean_markdown_cell(cells[3])
                    valid_loc, city = is_india_location(alt_loc, allow_bare_remote=False)
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


def _hydrate_candidate(job: RawJob) -> Optional[RawJob]:
    """Hydrates real full JD, verifies open status, and rejects senior/closed/non-India postings."""
    vr = verify_and_hydrate(job.apply_url, source_name=job.source_name, source_job_id=job.source_job_id, timeout=7)
    if not vr.is_open:
        logger.debug(f"Dropped closed GitHub feed job ({vr.reason}): {job.company} - {job.title}")
        return None
    if vr.location_raw:
        valid_loc, real_city = is_india_location(vr.location_raw, allow_bare_remote=False)
        if not valid_loc or real_city == "Unknown":
            logger.debug(f"Dropped non-India hydrated job ({vr.location_raw}): {job.company} - {job.title}")
            return None
        job.location_raw = vr.location_raw
        job.city = real_city
    if vr.description:
        # Reject any job whose real JD requires 2+ years of experience (digits or spelled-out words)
        if SENIOR_EXP_REGEX.search(vr.description):
            logger.debug(f"Dropped senior JD job (2+ yrs exp): {job.company} - {job.title}")
            return None
        job.description = vr.description
    if vr.apply_url:
        job.apply_url = vr.apply_url
    if vr.posted_date:
        job.posted_date = vr.posted_date
    job.expires_at = vr.expires_at
    job.last_verified_at = vr.verified_at
    return job


def fetch_github_fresher_jobs() -> List[RawJob]:
    """Fetches, deduplicates, hydrates real JDs, and live-verifies fresher jobs from GitHub aggregators."""
    raw_results: List[RawJob] = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fetch_single_feed, feed) for feed in GITHUB_FEEDS]
        for f in as_completed(futures):
            try:
                raw_results.extend(f.result())
            except Exception:
                pass

    # Deduplicate by normalized_key and apply_url BEFORE network hydration
    seen_keys = set()
    seen_urls = set()
    unique_candidates: List[RawJob] = []
    for job in raw_results:
        if job.normalized_key in seen_keys or job.apply_url in seen_urls:
            continue
        seen_keys.add(job.normalized_key)
        seen_urls.add(job.apply_url)
        unique_candidates.append(job)

    verified_results: List[RawJob] = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(_hydrate_candidate, job) for job in unique_candidates]
        for f in as_completed(futures):
            try:
                hydrated = f.result()
                if hydrated is not None:
                    verified_results.append(hydrated)
            except Exception:
                pass

    logger.info(f"GitHub fresher feed adapter collected {len(verified_results)} live-verified fresher jobs (from {len(unique_candidates)} unique candidates)")
    return verified_results
