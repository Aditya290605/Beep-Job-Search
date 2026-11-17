"""
adapters/base.py - Shared utilities for source adapters
"""

import urllib.request
import urllib.error
import json
import re
import time
import logging
from typing import Optional, Tuple, Dict, Any
from app import config

logger = logging.getLogger(__name__)

# Indian major tech cities and variants
INDIAN_CITIES = {
    "bangalore": "Bangalore",
    "bengaluru": "Bangalore",
    "mumbai": "Mumbai",
    "pune": "Pune",
    "hyderabad": "Hyderabad",
    "gurgaon": "Gurugram",
    "gurugram": "Gurugram",
    "delhi": "Delhi",
    "new delhi": "Delhi",
    "noida": "Noida",
    "chennai": "Chennai",
    "kolkata": "Kolkata",
    "ahmedabad": "Ahmedabad",
    "jaipur": "Jaipur",
    "kochi": "Kochi",
    "cochin": "Kochi",
    "trivandrum": "Kochi",
    "thiruvananthapuram": "Kochi",
    "chandigarh": "Chandigarh",
    "indore": "Indore",
    "bhopal": "Bhopal",
    "coimbatore": "Coimbatore"
}

FRESHER_KEYWORDS = [
    r"\bintern\b", r"\binternship\b", r"\bfresher\b", r"\bgraduate\b",
    r"\bentry[- ]level\b", r"\bjunior\b", r"\btrainee\b", r"\bassociate\b",
    r"\bapprentice\b", r"\b0[- ]?1\s*(?:yr|year|years)\b"
]
FRESHER_REGEX = re.compile("|".join(FRESHER_KEYWORDS), re.IGNORECASE)


def fetch_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 10, retries: int = 2) -> Any:
    """
    Fetches JSON from a URL with custom user-agent, timeout, and exponential backoff retry.
    """
    req_headers = {
        "User-Agent": config.USER_AGENT,
        "Accept": "application/json"
    }
    if headers:
        req_headers.update(headers)

    last_exc = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except Exception as e:
            last_exc = e
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))  # Exponential backoff
            else:
                logger.warning(f"Failed to fetch {url} after {retries + 1} attempts: {e}")
                raise last_exc


def clean_html(raw_html: Optional[str]) -> str:
    """Strips HTML tags and normalizes whitespace."""
    if not raw_html:
        return ""
    # Strip HTML tags
    clean_text = re.sub(r'<[^>]+>', ' ', raw_html)
    # Decode HTML entities
    clean_text = clean_text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # Normalize multiple whitespace
    return re.sub(r'\s+', ' ', clean_text).strip()


def is_india_location(location_str: Optional[str]) -> Tuple[bool, str]:
    """
    Verifies if a location string corresponds to India or an India-eligible remote role.
    Returns (is_valid, normalized_city).
    If city cannot be determined, returns (False, "Unknown").
    """
    if not location_str or not isinstance(location_str, str):
        return False, "Unknown"

    loc_lower = location_str.lower()
    is_remote = "remote" in loc_lower

    # 1. Match specific known Indian cities first
    for pattern, canonical in INDIAN_CITIES.items():
        if pattern in loc_lower:
            return True, canonical

    # 2. Check Remote if eligible for India / APAC / Worldwide
    if is_remote and ("india" in loc_lower or "apac" in loc_lower or "anywhere" in loc_lower or "worldwide" in loc_lower or "remote" in loc_lower):
        return True, "Remote"

    # 3. Check general "India"
    if "india" in loc_lower:
        return True, "India (Multiple/Other)"

    return False, "Unknown"


def is_fresher_job(title: str, description: str = "") -> bool:
    """Determines whether a job is suited for freshers (0-1 yrs exp, intern, trainee, etc.)."""
    sample = f"{title} {description[:500]}"
    return bool(FRESHER_REGEX.search(sample))


def extract_job_type(title: str, description: str = "") -> str:
    """Returns 'internship' if title or description mentions intern, else 'job'."""
    text = f"{title} {description[:300]}".lower()
    if "intern" in text:
        return "internship"
    return "job"
