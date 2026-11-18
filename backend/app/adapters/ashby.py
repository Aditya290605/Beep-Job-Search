"""
adapters/ashby.py - Ashby Job Board Adapter

Pulls public job listings from Ashby job boards for high-growth tech & AI startups.
Official endpoint: https://api.ashbyhq.com/posting-api/job-board/{board}
No authentication required.
"""

import logging
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.models import RawJob
from app.adapters.base import fetch_json, clean_html, is_india_location, is_fresher_job, extract_job_type

logger = logging.getLogger(__name__)

ASHBY_COMPANIES = [
    ("sentry", "Sentry"),
    ("replit", "Replit"),
    ("linear", "Linear"),
    ("posthog", "PostHog"),
    ("vapi", "Vapi"),
    ("ramp", "Ramp"),
    ("retool", "Retool"),
    ("anysphere", "Cursor / Anysphere"),
    ("modal", "Modal Labs"),
    ("perplexity", "Perplexity AI"),
    ("elevenlabs", "ElevenLabs"),
    ("together-ai", "Together AI"),
    ("dust", "Dust"),
    ("baseten", "Baseten"),
    ("resend", "Resend"),
    ("synthesia", "Synthesia"),
    ("langchain", "LangChain"),
    ("cohere", "Cohere"),
    ("dbt-labs", "dbt Labs"),
    ("clerk", "Clerk"),
    ("railway", "Railway"),
    ("render", "Render"),
    ("sourcegraph", "Sourcegraph")
]


def fetch_single_ashby_board(board: str, display_name: str) -> List[RawJob]:
    """Fetches a single Ashby board and filters for fresher jobs in India."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    board_jobs: List[RawJob] = []
    try:
        data = fetch_json(url, timeout=6, retries=1)
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

            board_jobs.append(RawJob(
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
    return board_jobs


def fetch_ashby_jobs() -> List[RawJob]:
    """Fetches and normalizes fresher jobs from all configured Ashby boards concurrently."""
    results: List[RawJob] = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_single_ashby_board, board, name) for board, name in ASHBY_COMPANIES]
        for f in as_completed(futures):
            try:
                results.extend(f.result())
            except Exception:
                pass

    logger.info(f"Ashby adapter collected {len(results)} fresher jobs")
    return results
