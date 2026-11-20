"""
adapters/base.py - Shared utilities for source adapters
"""

import urllib.request
import urllib.error
import html as html_lib
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
    "coimbatore": "Coimbatore",
    "nagpur": "Nagpur",
    "vadodara": "Vadodara",
    "bhubaneswar": "Bhubaneswar",
    "visakhapatnam": "Visakhapatnam",
    "vizag": "Visakhapatnam",
    "mysore": "Mysore",
    "surat": "Surat",
    "goa": "Goa"
}

FRESHER_KEYWORDS = [
    r"\bintern\b", r"\binternship\b", r"\bfresher\b", r"\bgraduate\b",
    r"\bentry[- ]level\b", r"\bjunior\b", r"\btrainee\b",
    r"\bassociate\b(?!\s+(?:director|manager|vp|partner|lead|principal))",
    r"\bapprentice(?:ship)?\b",
    r"\b0[- ]?1\s*(?:yr|year|years|yrs)\b",
    r"\b(?:0|no)\s*(?:years?|yrs?)\s*(?:of\s*)?experience\b",
    r"\b(?:sde|swe|engineer|developer|analyst|programmer|sdet|qa)\s*[- ]?(?:1|i|one)\b",
    r"\bgraduate engineer trainee\b",
    r"\bnew grad\b", r"\bnew graduate\b",
    r"\bcampus\b", r"\bcollege\b", r"\buniversity graduate\b"
]
FRESHER_REGEX = re.compile("|".join(FRESHER_KEYWORDS), re.IGNORECASE)

SENIOR_TITLE_KEYWORDS = [
    r"\bsenior\b", r"\bsr\.?\b", r"\bdirector\b", r"\blead\b", r"\bleader\b", r"\bteam lead(?:er)?\b", r"\bstaff\b",
    r"\bprincipal\b", r"\bhead of\b", r"\bvp\b", r"\bvice president\b", r"\bmanager\b",
    r"\barchitect\b",
    r"\b(?:sde|swe|engineer|developer|analyst|consultant|specialist|associate)\s*[- ]?(?:ii|iii|iv|v|2|3|4|5)\b",
    r"\(consultant\)\s*[- ]?(?:ii|iii|iv|v|2|3|4|5)\b"
]
SENIOR_EXP_KEYWORDS = [
    r"\b(?:2|3|4|5|6|7|8|9|10|11|12)\s*[-–to]+\s*\d+\+?\s*(?:yr|year|years|yrs)\b",
    r"\b(?:2|3|4|5|6|7|8|9|10|11|12)\+\s*(?:yr|year|years|yrs)\b",
    r"\b(?:2|3|4|5|6|7|8|9|10|11|12)\+?\s*(?:yr|year|years|yrs)\s+(?:of\s+)?(?:\w+\s+){0,3}(?:experience|exp)\b",
    r"\b(?:minimum|at least)\s+(?:of\s+)?(?:2|3|4|5|6|7|8|9|10|two|three|four|five|six|seven|eight|nine|ten)\+?\s*(?:yr|year|years|yrs)\b",
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten)\s*(?:or more|\+|[-–]|to\s+\w+)\s*(?:yr|year|years|yrs)\b",
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten)\s+(?:yr|year|years|yrs)\s+(?:of\s+)?(?:\w+\s+){0,3}(?:experience|exp)\b"
]
SENIOR_KEYWORDS = SENIOR_TITLE_KEYWORDS + SENIOR_EXP_KEYWORDS
SENIOR_TITLE_REGEX = re.compile("|".join(SENIOR_TITLE_KEYWORDS), re.IGNORECASE)
SENIOR_EXP_REGEX = re.compile("|".join(SENIOR_EXP_KEYWORDS), re.IGNORECASE)
SENIOR_REGEX = re.compile("|".join(SENIOR_KEYWORDS), re.IGNORECASE)

FOREIGN_EXCLUSIONS = [
    r"\busa\b", r"\bus\b", r"\bunited states\b", r"\buk\b", r"\bunited kingdom\b",
    r"\bcanada\b", r"\bgermany\b", r"\bemea\b", r"\blatam\b", r"\beurope\b",
    r"\baustralia\b", r"\bireland\b", r"\bpoland\b", r"\bfrance\b", r"\bjapan\b",
    r"\b(?:mst|pst|est|cst)\b", r"\b(?:california|texas|new york|atlanta|seattle|austin|san francisco|chicago|boston)\b"
]
FOREIGN_REGEX = re.compile("|".join(FOREIGN_EXCLUSIONS), re.IGNORECASE)


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
    """Unescapes HTML entities (including double-escaped Greenhouse HTML), strips tags cleanly, and preserves readability."""
    if not raw_html:
        return ""
    # Unescape twice to handle double-escaped payloads (e.g. &lt;p&gt; from Greenhouse API)
    text = html_lib.unescape(html_lib.unescape(raw_html))
    # Remove script/style blocks completely
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', text, flags=re.IGNORECASE | re.DOTALL)
    # Turn list items and block tags into newlines so paragraphs & bullets survive
    text = re.sub(r'<li[^>]*>', '\n• ', text, flags=re.IGNORECASE)
    text = re.sub(r'</(?:p|div|h[1-6]|li|tr|section|article)>|<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    # Strip remaining HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Normalize spaces per line and collapse excessive blank lines
    lines = [re.sub(r'[ \t\xa0]+', ' ', ln).strip() for ln in text.splitlines()]
    cleaned = "\n".join(ln for ln in lines if ln)
    return cleaned.strip()


def is_india_location(location_str: Optional[str], allow_bare_remote: bool = True) -> Tuple[bool, str]:
    """
    Verifies if a location string corresponds to India or an India-eligible remote role.
    Returns (is_valid, normalized_city).
    If city cannot be determined or is foreign-only, returns (False, "Unknown").
    """
    if not location_str or not isinstance(location_str, str):
        return False, "Unknown"

    loc_lower = location_str.lower()
    has_real_india = bool(re.search(r'\bindia\b', loc_lower))
    has_global = any(w in loc_lower for w in ["worldwide", "global", "anywhere"])

    # Reject foreign locations unless India, Worldwide, or Global is explicitly mentioned
    # (prevents "Indianapolis, IN" or "Indiana" or "Remote-United-States" from falsely matching India)
    if FOREIGN_REGEX.search(loc_lower) and not has_real_india and not has_global:
        return False, "Unknown"

    # 1. Match specific known Indian cities first
    for pattern, canonical in INDIAN_CITIES.items():
        if pattern in loc_lower:
            return True, canonical

    # 2. Check Remote / Global eligibility
    is_remote_signal = any(w in loc_lower for w in ["remote", "worldwide", "anywhere", "global", "telecommute", "work from home"])
    if is_remote_signal or loc_lower.strip() in ("worldwide", "anywhere", "global", "apac"):
        if any(w in loc_lower for w in ["india", "apac", "worldwide", "anywhere", "global"]):
            return True, "Remote"
        if allow_bare_remote and loc_lower.strip() in ("remote", "fully remote", "remote / flexible", "work from anywhere"):
            return True, "Remote"

    # 3. Check general "India" as a standalone word
    if has_real_india:
        return True, "India (Multiple/Other)"

    return False, "Unknown"


def is_fresher_job(title: str, description: str = "") -> bool:
    """Determines whether a job is suited for freshers (0-1 yrs exp, intern, trainee, etc.)."""
    # Guard 1: Reject if title contains senior/lead/manager/level-2+ keywords
    if SENIOR_TITLE_REGEX.search(title) or SENIOR_EXP_REGEX.search(title):
        return False

    # Guard 2: Reject if description explicitly requires 2+ years of experience (digits OR spelled-out words)
    if description and SENIOR_EXP_REGEX.search(description[:8000]):
        return False

    sample = f"{title} {description[:5000]}"
    return bool(FRESHER_REGEX.search(sample))


def extract_job_type(title: str, description: str = "") -> str:
    """Returns 'internship' if title or description mentions intern/internship (word-boundary safe), else 'job'."""
    text = f"{title} {description[:300]}".lower()
    if re.search(r"\bintern(?:ship|s)?\b", text):
        return "internship"
    return "job"
