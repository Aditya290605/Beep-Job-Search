"""
adapters/ashby.py - Ashby Job Board Adapter

Pulls public job listings from Ashby job boards for high-growth tech & AI startups.
Official endpoint: https://api.ashbyhq.com/posting-api/job-board/{board}
No authentication required.
"""

import logging
from typing import List
from app.models import RawJob
from app.adapters.base import fetch_json, clean_html, is_india_location, is_fresher_job, extract_job_type

logger = logging.getLogger(__name__)

ASHBY_COMPANIES = [
    ("replit", "Replit"),
    ("cursor", "Cursor / Anysphere"),
    ("vapi", "Vapi"),
    ("synthesia", "Synthesia"),
    ("perplexity", "Perplexity AI"),
    ("together-ai", "Together AI"),
    ("mercor", "Mercor"),
    ("sentry", "Sentry"),
    ("ramp", "Ramp"),
    ("linear", "Linear"),
    ("posthog", "PostHog"),
    ("retool", "Retool")
]


def fetch_ashby_jobs() -> List[RawJob]:
    """Fetches and normalizes fresher jobs from all configured Ashby boards."""
    results: List[RawJob] = []

    for board, display_name in ASHBY_COMPANIES:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
        try:
            data = fetch_json(url, timeout=7, retries=1)
            jobs = data.get("jobs", [])
            for item in jobs:
                title = item.get("title", "").strip()
                location_raw = item.get("location", "").strip()
                desc_html = item.get("descriptionHtml", "")
                desc_text = clean_html(desc_html)

                valid_loc, city = is_india_location(location_raw)
                if not valid_loc or city == "Unknown":
                    continue

                if not is_fresher_job(title, desc_text):
                    continue

                job_type = extract_job_type(title, desc_text)
                apply_url = item.get("jobUrl") or item.get("applyUrl") or ""
                source_job_id = str(item.get("id", ""))
                published_at = item.get("publishedAt")

                results.append(RawJob(
                    title=title,
                    company=display_name,
                    location_raw=location_raw,
                    city=city,
                    job_type=job_type,
                    apply_url=apply_url,
                    description=desc_text[:3000],
                    source_name="ashby",
                    source_job_id=source_job_id,
                    posted_date=published_at
                ))
        except Exception as e:
            logger.debug(f"Ashby board {board} skipped: {e}")
            continue

    logger.info(f"Ashby adapter collected {len(results)} fresher jobs")
    return results
