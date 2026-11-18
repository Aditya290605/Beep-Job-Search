"""
adapters/greenhouse.py - Greenhouse Job Boards Adapter

Pulls public job listings from Greenhouse boards of top tech companies & Indian unicorns.
Official endpoint: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
No authentication required.
"""

import logging
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.models import RawJob
from app.adapters.base import fetch_json, clean_html, is_india_location, is_fresher_job, extract_job_type

logger = logging.getLogger(__name__)

# 65+ verified active company boards with engineering & product presence in India
GREENHOUSE_COMPANIES = [
    ("mongodb", "MongoDB"),
    ("rubrik", "Rubrik"),
    ("stripe", "Stripe"),
    ("elastic", "Elastic"),
    ("gitlab", "GitLab"),
    ("twilio", "Twilio"),
    ("affirm", "Affirm"),
    ("gusto", "Gusto"),
    ("scaleai", "Scale AI"),
    ("databricks", "Databricks"),
    ("coinbase", "Coinbase"),
    ("samsara", "Samsara"),
    ("icapitalnetwork", "iCapital"),
    ("purestorage", "Pure Storage"),
    ("okta", "Okta"),
    ("pinterest", "Pinterest"),
    ("dropbox", "Dropbox"),
    ("datadog", "Datadog"),
    ("zscaler", "Zscaler"),
    ("highradius", "HighRadius"),
    ("druva", "Druva"),
    ("pagerduty", "PagerDuty"),
    ("hp", "HP"),
    ("tcs", "TCS"),
    ("airbnb", "Airbnb"),
    ("cloudflare", "Cloudflare"),
    ("canonical", "Canonical"),
    ("verkada", "Verkada"),
    ("airtable", "Airtable"),
    ("duolingo", "Duolingo"),
    ("instacart", "Instacart"),
    ("lyft", "Lyft"),
    ("asana", "Asana"),
    ("workato", "Workato"),
    ("groww", "Groww"),
    ("inmobi", "InMobi"),
    ("slice", "Slice"),
    ("swiggy", "Swiggy"),
    ("zepto", "Zepto"),
    ("postman", "Postman"),
    ("browserstack", "BrowserStack"),
    ("urbancompany", "Urban Company"),
    ("clevertap", "CleverTap"),
    ("moengage", "MoEngage"),
    ("khatabook", "Khatabook"),
    ("navi", "Navi"),
    ("porter", "Porter"),
    ("atlassian", "Atlassian"),
    ("snowflake", "Snowflake"),
    ("qualtrics", "Qualtrics"),
    ("couchbase", "Couchbase"),
    ("thoughtworks", "Thoughtworks"),
    ("dream11", "Dream11"),
    ("cars24", "Cars24"),
    ("unacademy", "Unacademy"),
    ("udaan", "Udaan"),
    ("coindcx", "CoinDCX"),
    ("cloudera", "Cloudera"),
    ("nutanix", "Nutanix"),
    ("splunk", "Splunk"),
    ("paloaltonetworks", "Palo Alto Networks"),
    ("akamai", "Akamai"),
    ("gojek", "Gojek"),
    ("grab", "Grab"),
    ("toast", "Toast"),
    ("confluent", "Confluent"),
    ("hashicorp", "HashiCorp"),
    ("hubspot", "HubSpot"),
    ("box", "Box"),
    ("roblox", "Roblox"),
    ("roche", "Roche India")
]


def fetch_single_board(token: str, display_name: str) -> List[RawJob]:
    """Fetches a single Greenhouse board and filters for fresher jobs in India."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    board_jobs: List[RawJob] = []
    try:
        data = fetch_json(url, timeout=6, retries=1)
        jobs = data.get("jobs", [])
        for item in jobs:
            title = item.get("title", "").strip()
            location_obj = item.get("location") or {}
            location_raw = location_obj.get("name", "").strip()
            content_html = item.get("content", "")
            desc_text = clean_html(content_html)

            valid_loc, city = is_india_location(location_raw)
            if not valid_loc or city == "Unknown":
                continue

            if not is_fresher_job(title, desc_text):
                continue

            job_type = extract_job_type(title, desc_text)
            apply_url = item.get("absolute_url") or ""
            source_job_id = str(item.get("id", ""))
            updated_at = item.get("updated_at")

            board_jobs.append(RawJob(
                title=title,
                company=display_name,
                location_raw=location_raw,
                city=city,
                job_type=job_type,
                apply_url=apply_url,
                description=desc_text[:3000],
                source_name="greenhouse",
                source_job_id=source_job_id,
                posted_date=updated_at
            ))
    except Exception as e:
        logger.debug(f"Greenhouse board {token} skipped: {e}")
    return board_jobs


def fetch_greenhouse_jobs() -> List[RawJob]:
    """Fetches and normalizes fresher jobs across all configured Greenhouse boards concurrently."""
    results: List[RawJob] = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_single_board, token, name) for token, name in GREENHOUSE_COMPANIES]
        for f in as_completed(futures):
            try:
                results.extend(f.result())
            except Exception:
                pass

    logger.info(f"Greenhouse adapter collected {len(results)} fresher jobs")
    return results
