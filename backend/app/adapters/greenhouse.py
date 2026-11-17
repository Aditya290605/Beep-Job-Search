"""
adapters/greenhouse.py - Greenhouse Job Boards Adapter

Pulls public job listings from Greenhouse boards of top companies with India offices.
Official endpoint: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
No authentication required.
"""

import logging
from typing import List
from app.models import RawJob
from app.adapters.base import fetch_json, clean_html, is_india_location, is_fresher_job, extract_job_type

logger = logging.getLogger(__name__)

# List of tech companies with India offices using Greenhouse
GREENHOUSE_COMPANIES = [
    ("razorpay", "Razorpay"),
    ("cred", "CRED"),
    ("swiggy", "Swiggy"),
    ("postman", "Postman"),
    ("browserstack", "BrowserStack"),
    ("clevertap", "CleverTap"),
    ("elastic", "Elastic"),
    ("couchbase", "Couchbase"),
    ("thoughtspot", "ThoughtSpot"),
    ("rubrik", "Rubrik"),
    ("airbase", "Airbase"),
    ("gusto", "Gusto"),
    ("samsara", "Samsara"),
    ("sprinklr", "Sprinklr"),
    ("branch", "Branch"),
    ("harness", "Harness"),
    ("coinbase", "Coinbase"),
    ("rippling", "Rippling"),
    ("databricks", "Databricks"),
    ("stripe", "Stripe"),
    ("affirm", "Affirm"),
    ("klaviyo", "Klaviyo"),
    ("canva", "Canva"),
    ("mongodb", "MongoDB")
]


def fetch_greenhouse_jobs() -> List[RawJob]:
    """Fetches and normalizes fresher jobs from all configured Greenhouse boards."""
    results: List[RawJob] = []

    for token, display_name in GREENHOUSE_COMPANIES:
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        try:
            data = fetch_json(url, timeout=7, retries=1)
            jobs = data.get("jobs", [])
            for item in jobs:
                title = item.get("title", "").strip()
                location_obj = item.get("location") or {}
                location_raw = location_obj.get("name", "").strip()
                content_html = item.get("content", "")
                desc_text = clean_html(content_html)

                # Location check (must be India / India-Remote, drop Unknown)
                valid_loc, city = is_india_location(location_raw)
                if not valid_loc or city == "Unknown":
                    continue

                # Fresher check (0-1 yrs, intern, trainee, graduate)
                if not is_fresher_job(title, desc_text):
                    continue

                job_type = extract_job_type(title, desc_text)
                apply_url = item.get("absolute_url") or ""
                source_job_id = str(item.get("id", ""))
                updated_at = item.get("updated_at")

                results.append(RawJob(
                    title=title,
                    company=display_name,
                    location_raw=location_raw,
                    city=city,
                    job_type=job_type,
                    apply_url=apply_url,
                    description=desc_text[:3000],  # Bound description size
                    source_name="greenhouse",
                    source_job_id=source_job_id,
                    posted_date=updated_at
                ))
        except Exception as e:
            logger.debug(f"Greenhouse board {token} skipped: {e}")
            continue

    logger.info(f"Greenhouse adapter collected {len(results)} fresher jobs")
    return results
