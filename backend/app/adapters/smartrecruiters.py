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
from app.adapters.base import fetch_json, clean_html, is_india_location, is_fresher_job, extract_job_type, SENIOR_TITLE_REGEX, SENIOR_EXP_REGEX

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
    """Fetches a single SmartRecruiters board, hydrates full qualifications, and strictly filters for freshers in India."""
    board_jobs: List[RawJob] = []
    try:
        items = []
        for offset in (0, 100, 200):
            url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings?offset={offset}&limit=100"
            data = fetch_json(url, timeout=6, retries=1)
            page_items = data.get("content", [])
            if not page_items:
                break
            items.extend(page_items)
            if len(page_items) < 100:
                break

        for item in items:
            title = item.get("name", "").strip()
            if SENIOR_TITLE_REGEX.search(title) or SENIOR_EXP_REGEX.search(title):
                continue

            loc = item.get("location") or {}
            location_raw = f"{loc.get('city', '')}, {loc.get('region', '')}, {loc.get('country', '')}".strip(" ,")

            valid_loc, city = is_india_location(location_raw, allow_bare_remote=False)
            if not valid_loc or city == "Unknown":
                continue

            exp_level = (item.get("experienceLevel") or {}).get("id", "").lower()
            is_entry = exp_level in ("entry_level", "internship", "student", "associate")

            if not (is_entry or is_fresher_job(title)):
                continue

            job_id = str(item.get("id", ""))
            # Hydrate full official description + qualifications so senior roles (e.g. 3+ yrs) never slip through
            full_desc = ""
            posting_url = f"https://jobs.smartrecruiters.com/{company_id}/{job_id}"
            try:
                detail = fetch_json(f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings/{job_id}", timeout=5, retries=0)
                if detail.get("active") is False:
                    continue
                posting_url = detail.get("postingUrl") or posting_url
                sections = (detail.get("jobAd") or {}).get("sections") or {}
                parts = []
                for sec_key in ("jobDescription", "qualifications", "additionalInformation"):
                    sec = sections.get(sec_key) or {}
                    sec_title = (sec.get("title") or "").strip()
                    sec_text = clean_html(sec.get("text", ""))
                    if sec_text:
                        parts.append(f"{sec_title}\n{sec_text}" if sec_title else sec_text)
                full_desc = "\n\n".join(parts)[:8000]
            except Exception:
                continue

            # Reject if real qualifications require 2+ years of experience
            if not full_desc or SENIOR_EXP_REGEX.search(full_desc):
                continue
            if not (exp_level in ("internship", "student") or is_fresher_job(title, full_desc)):
                continue

            job_type = "internship" if (exp_level == "internship" or "intern" in title.lower()) else extract_job_type(title, full_desc)
            released_date = item.get("releasedDate")

            board_jobs.append(RawJob(
                title=title,
                company=display_name,
                location_raw=location_raw,
                city=city,
                job_type=job_type,
                apply_url=posting_url,
                description=full_desc,
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
