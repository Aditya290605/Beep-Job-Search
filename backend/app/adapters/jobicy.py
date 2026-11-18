"""
adapters/jobicy.py - Jobicy Remote Jobs API Adapter

Pulls public remote tech jobs from Jobicy's official developer API.
Official endpoint: https://jobicy.com/api/v2/remote-jobs?count=50
No authentication required. Attribution: jobicy.com
"""

import logging
from typing import List
from app.models import RawJob
from app.adapters.base import fetch_json, clean_html, is_india_location, is_fresher_job, extract_job_type

logger = logging.getLogger(__name__)


def fetch_jobicy_jobs() -> List[RawJob]:
    """Fetches and normalizes fresher/intern remote jobs from Jobicy."""
    results: List[RawJob] = []
    url = "https://jobicy.com/api/v2/remote-jobs?count=50&geo=apac"

    try:
        data = fetch_json(url, timeout=10, retries=2)
        jobs = data.get("jobs", [])
        for item in jobs:
            title = item.get("jobTitle", "").strip()
            company = item.get("companyName", "Tech Company").strip()
            geo = item.get("jobGeo", "").strip()
            desc_html = item.get("jobDescription", "")
            desc_text = clean_html(desc_html)

            valid_loc, city = is_india_location(geo)
            if not valid_loc or city == "Unknown":
                continue

            if not is_fresher_job(title, desc_text):
                continue

            job_type = extract_job_type(title, desc_text)
            apply_url = item.get("url") or ""
            source_job_id = str(item.get("id", ""))
            pub_date = item.get("pubDate")

            results.append(RawJob(
                title=title,
                company=company,
                location_raw=geo or "Remote",
                city=city,
                job_type=job_type,
                apply_url=apply_url,
                description=desc_text[:3000],
                source_name="jobicy",
                source_job_id=source_job_id,
                posted_date=pub_date
            ))
    except Exception as e:
        logger.warning(f"Jobicy API fetch error: {e}")

    logger.info(f"Jobicy adapter collected {len(results)} fresher jobs")
    return results
