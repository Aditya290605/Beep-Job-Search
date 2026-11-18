"""
adapters/smartrecruiters.py - SmartRecruiters Postings Adapter

Pulls public job listings from SmartRecruiters API for enterprise tech companies in India.
Official endpoint: https://api.smartrecruiters.com/v1/companies/{company}/postings
No authentication required.
"""

import logging
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.models import RawJob
from app.adapters.base import fetch_json, is_india_location, is_fresher_job, extract_job_type, SENIOR_REGEX

logger = logging.getLogger(__name__)

SMARTRECRUITERS_COMPANIES = [
    ("swiggy", "Swiggy"),
    ("PHONEPELIMITED", "PhonePe"),
    ("freshworks", "Freshworks"),
    ("ixigo", "ixigo"),
    ("ServiceNow", "ServiceNow"),
    ("BoschGroup", "Bosch"),
    ("publicisgroupe", "Publicis Sapient"),
    ("ubisoft", "Ubisoft"),
    ("visa", "Visa"),
    ("Informatica", "Informatica"),
    ("SchneiderElectric", "Schneider Electric"),
    ("AveryDennison", "Avery Dennison"),
    ("siemens", "Siemens"),
    ("honeywell", "Honeywell"),
    ("alstom", "Alstom"),
    ("volvo", "Volvo Group"),
    ("here", "HERE Technologies"),
    ("wipro", "Wipro"),
    ("hitachi", "Hitachi"),
    ("nxp", "NXP Semiconductors"),
    ("teradata", "Teradata"),
    ("uber", "Uber")
]


def fetch_single_smartrecruiters_company(company_id: str, display_name: str) -> List[RawJob]:
    """Fetches a single SmartRecruiters board and extracts fresher jobs in India."""
    url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings?limit=100"
    board_jobs: List[RawJob] = []
    try:
        data = fetch_json(url, timeout=6, retries=1)
        items = data.get("content", [])
        for item in items:
            title = item.get("name", "").strip()
            loc = item.get("location") or {}
            location_raw = f"{loc.get('city', '')}, {loc.get('region', '')}, {loc.get('country', '')}".strip(" ,")

            valid_loc, city = is_india_location(location_raw)
            if not valid_loc or city == "Unknown":
                continue

            exp_level = (item.get("experienceLevel") or {}).get("id", "").lower()
            is_entry = exp_level in ("entry_level", "internship", "student", "associate") and not SENIOR_REGEX.search(title)

            if not (is_entry or is_fresher_job(title)):
                continue

            job_type = "internship" if (exp_level == "internship" or "intern" in title.lower()) else extract_job_type(title)
            job_id = str(item.get("id", ""))
            apply_url = f"https://jobs.smartrecruiters.com/{company_id}/{job_id}"
            released_date = item.get("releasedDate")

            board_jobs.append(RawJob(
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
    return board_jobs


def fetch_smartrecruiters_jobs() -> List[RawJob]:
    """Fetches and normalizes fresher jobs from all configured SmartRecruiters companies concurrently."""
    results: List[RawJob] = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_single_smartrecruiters_company, cid, name) for cid, name in SMARTRECRUITERS_COMPANIES]
        for f in as_completed(futures):
            try:
                results.extend(f.result())
            except Exception:
                pass

    logger.info(f"SmartRecruiters adapter collected {len(results)} fresher jobs")
    return results
