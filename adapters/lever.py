"""
adapters/lever.py - Lever Postings Adapter

Pulls public job listings from Lever postings API for tech companies with India offices.
Official endpoint: https://api.lever.co/v0/postings/{company}?mode=json
No authentication required.
"""

import logging
from typing import List
from datetime import datetime
from models import RawJob
from adapters.base import fetch_json, clean_html, is_india_location, is_fresher_job, extract_job_type

logger = logging.getLogger(__name__)

LEVER_COMPANIES = [
    ("atlan", "Atlan"),
    ("invideo", "InVideo"),
    ("moengage", "MoEngage"),
    ("khatabook", "Khatabook"),
    ("urbancompany", "Urban Company"),
    ("scaler", "Scaler"),
    ("hotstar", "Disney+ Hotstar"),
    ("fynd", "Fynd"),
    ("kredivo", "Kredivo")
]


def fetch_lever_jobs() -> List[RawJob]:
    """Fetches and normalizes fresher jobs from all configured Lever boards."""
    results: List[RawJob] = []

    for slug, display_name in LEVER_COMPANIES:
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            items = fetch_json(url, timeout=7, retries=1)
            if not isinstance(items, list):
                continue

            for item in items:
                title = item.get("text", "").strip()
                categories = item.get("categories") or {}
                location_raw = categories.get("location", "").strip()
                desc_plain = item.get("descriptionPlain") or clean_html(item.get("description", ""))

                valid_loc, city = is_india_location(location_raw)
                if not valid_loc or city == "Unknown":
                    continue

                if not is_fresher_job(title, desc_plain):
                    continue

                job_type = extract_job_type(title, desc_plain)
                apply_url = item.get("hostedUrl") or item.get("applyUrl") or ""
                source_job_id = str(item.get("id", ""))
                
                # Lever provides createdAt timestamp in milliseconds
                created_ms = item.get("createdAt")
                posted_date = None
                if created_ms:
                    try:
                        posted_date = datetime.utcfromtimestamp(created_ms / 1000.0).isoformat()
                    except Exception:
                        pass

                results.append(RawJob(
                    title=title,
                    company=display_name,
                    location_raw=location_raw,
                    city=city,
                    job_type=job_type,
                    apply_url=apply_url,
                    description=desc_plain[:3000],
                    source_name="lever",
                    source_job_id=source_job_id,
                    posted_date=posted_date
                ))
        except Exception as e:
            logger.debug(f"Lever board {slug} skipped: {e}")
            continue

    logger.info(f"Lever adapter collected {len(results)} fresher jobs")
    return results
