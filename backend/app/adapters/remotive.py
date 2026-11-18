"""
adapters/remotive.py - Remotive Remote Jobs API Adapter

Pulls public remote developer jobs from Remotive's developer API.
Official endpoint: https://remotive.com/api/remote-jobs?category=software-dev&limit=100
No authentication required. Attribution: remotive.com
"""

import logging
from typing import List
from app.models import RawJob
from app.adapters.base import fetch_json, clean_html, is_india_location, is_fresher_job, extract_job_type

logger = logging.getLogger(__name__)


def fetch_remotive_jobs() -> List[RawJob]:
    """Fetches and normalizes fresher/intern remote tech & data jobs from Remotive."""
    results: List[RawJob] = []
    url = "https://remotive.com/api/remote-jobs?limit=100"

    try:
        data = fetch_json(url, timeout=10, retries=1)
        jobs = data.get("jobs", [])
        for item in jobs:
            title = item.get("title", "").strip()
            company = item.get("company_name", "Startup").strip()
            location_raw = item.get("candidate_required_location", "").strip()
            desc_html = item.get("description", "")
            desc_text = clean_html(desc_html)

            valid_loc, city = is_india_location(location_raw)
            if not valid_loc or city == "Unknown":
                continue

            if not is_fresher_job(title, desc_text):
                continue

            job_type = extract_job_type(title, desc_text)
            apply_url = item.get("url") or ""
            source_job_id = str(item.get("id", ""))
            pub_date = item.get("publication_date")

            results.append(RawJob(
                title=title,
                company=company,
                location_raw=location_raw or "Remote",
                city=city,
                job_type=job_type,
                apply_url=apply_url,
                description=desc_text[:3000],
                source_name="remotive",
                source_job_id=source_job_id,
                posted_date=pub_date
            ))
    except Exception as e:
        logger.warning(f"Remotive API fetch error: {e}")

    logger.info(f"Remotive adapter collected {len(results)} fresher jobs")
    return results
