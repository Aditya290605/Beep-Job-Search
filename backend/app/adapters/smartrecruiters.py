"""
adapters/smartrecruiters.py - SmartRecruiters Postings Adapter

Pulls public job listings from SmartRecruiters API for enterprise tech companies in India.
Official endpoint: https://api.smartrecruiters.com/v1/companies/{company}/postings
No authentication required.
"""

import logging
from typing import List
from app.models import RawJob
from app.adapters.base import fetch_json, is_india_location, is_fresher_job, extract_job_type

logger = logging.getLogger(__name__)

SMARTRECRUITERS_COMPANIES = [
    ("publicisgroupe", "Publicis Sapient"),
    ("bosch", "Bosch"),
    ("ubisoft", "Ubisoft"),
    ("visa", "Visa")
]


def fetch_smartrecruiters_jobs() -> List[RawJob]:
    """Fetches and normalizes fresher jobs from all configured SmartRecruiters companies."""
    results: List[RawJob] = []

    for company_id, display_name in SMARTRECRUITERS_COMPANIES:
        url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings?limit=100"
        try:
            data = fetch_json(url, timeout=7, retries=1)
            items = data.get("content", [])
            for item in items:
                title = item.get("name", "").strip()
                loc = item.get("location") or {}
                location_raw = f"{loc.get('city', '')}, {loc.get('region', '')}, {loc.get('country', '')}".strip(" ,")

                valid_loc, city = is_india_location(location_raw)
                if not valid_loc or city == "Unknown":
                    continue

                if not is_fresher_job(title):
                    continue

                job_type = extract_job_type(title)
                job_id = str(item.get("id", ""))
                apply_url = f"https://jobs.smartrecruiters.com/{company_id}/{job_id}"
                released_date = item.get("releasedDate")

                results.append(RawJob(
                    title=title,
                    company=display_name,
                    location_raw=location_raw,
                    city=city,
                    job_type=job_type,
                    apply_url=apply_url,
                    description=f"{title} position at {display_name} in {city}.",
                    source_name="smartrecruiters",
                    source_job_id=job_id,
                    posted_date=released_date
                ))
        except Exception as e:
            logger.debug(f"SmartRecruiters company {company_id} skipped: {e}")
            continue

    logger.info(f"SmartRecruiters adapter collected {len(results)} fresher jobs")
    return results
