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

# Verified active company boards on Greenhouse with engineering & product presence in India
GREENHOUSE_COMPANIES = [
    ("razorpaysoftwareprivatelimited", "Razorpay"),
    ("groww", "Groww"),
    ("inmobi", "InMobi"),
    ("slice", "Slice"),
    ("contentstack", "Contentstack"),
    ("glance", "Glance"),
    ("sigmoid", "Sigmoid"),
    ("highradius", "HighRadius"),
    ("druva", "Druva"),
    ("observeai", "Observe.AI"),
    ("zetaglobal", "Zeta Global"),
    ("towerresearchcapital", "Tower Research Capital"),
    ("gravitonresearchcapital", "Graviton Research Capital"),
    ("alphagrepsecurities", "AlphaGrep"),
    ("squarepointcapital", "Squarepoint Capital"),
    ("worldquant", "WorldQuant"),
    ("aqr", "AQR Capital"),
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
    ("fivetran", "Fivetran"),
    ("tripactions", "Navan"),
    ("agoda", "Agoda"),
    ("sumologic", "Sumo Logic"),
    ("launchdarkly", "LaunchDarkly"),
    ("jfrog", "JFrog"),
    ("coursera", "Coursera"),
    ("mixpanel", "Mixpanel"),
    ("figma", "Figma"),
    ("grafanalabs", "Grafana Labs"),
    ("newrelic", "New Relic"),
    ("cockroachlabs", "Cockroach Labs"),
    ("vercel", "Vercel"),
    ("turing", "Turing"),
    ("zuora", "Zuora"),
    ("commvault", "Commvault"),
    ("toast", "Toast"),
    ("roblox", "Roblox"),
    ("couchbaseinc", "Couchbase"),
    ("hackerrank", "HackerRank"),
    ("celonis", "Celonis")
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
            source_job_id = str(item.get("id", ""))
            apply_url = (item.get("absolute_url") or "").strip()
            # Avoid generic company /jobs/search or /careers pages when direct Greenhouse job URL works cleanly
            if not apply_url or any(p in apply_url.lower() for p in ("/jobs/search", "/careers/search")):
                apply_url = f"https://job-boards.greenhouse.io/{token}/jobs/{source_job_id}"
            updated_at = item.get("updated_at")

            board_jobs.append(RawJob(
                title=title,
                company=display_name,
                location_raw=location_raw,
                city=city,
                job_type=job_type,
                apply_url=apply_url,
                description=desc_text[:8000],
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
