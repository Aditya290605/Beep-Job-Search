"""
adapters/workday.py - Workday CXS Public Job Boards Adapter

Pulls live, verified fresher & intern job postings in India from official enterprise
Workday CXS JSON endpoints (NVIDIA, Intel, Micron, Cisco, HPE, Airbus, Salesforce,
Citi, Morgan Stanley, Cadence, S&P Global, GE HealthCare, GE Vernova, Marvell, etc.).
Fetches the full official job description, direct single-job apply URL, and expiry date.
No authentication required. Pure Python stdlib.
"""

import json
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List, Tuple

from app.models import RawJob
from app.adapters.base import (
    clean_html,
    is_india_location,
    is_fresher_job,
    extract_job_type,
    SENIOR_TITLE_REGEX,
)

logger = logging.getLogger(__name__)

# Verified active enterprise Workday CXS boards hiring freshers & interns in India
WORKDAY_COMPANIES: List[Tuple[str, str, str, str]] = [
    ("nvidia", "wd5", "NVIDIAExternalCareerSite", "NVIDIA"),
    ("intel", "wd1", "External", "Intel"),
    ("micron", "wd1", "External", "Micron"),
    ("cisco", "wd5", "Cisco_Careers", "Cisco"),
    ("cadence", "wd1", "External_Careers", "Cadence"),
    ("marvell", "wd1", "MarvellCareers", "Marvell"),
    ("analogdevices", "wd1", "External", "Analog Devices"),
    ("amat", "wd1", "External", "Applied Materials"),
    ("globalfoundries", "wd1", "External", "GlobalFoundries"),
    ("hpe", "wd5", "Jobsathpe", "HPE"),
    ("ag", "wd3", "Airbus", "Airbus"),
    ("boeing", "wd1", "EXTERNAL_CAREERS", "Boeing"),
    ("salesforce", "wd12", "External_Career_Site", "Salesforce"),
    ("salesforce", "wd12", "Futureforce_Internships", "Salesforce"),
    ("workday", "wd5", "Workday", "Workday"),
    ("crowdstrike", "wd5", "crowdstrikecareers", "CrowdStrike"),
    ("autodesk", "wd1", "Ext", "Autodesk"),
    ("gevernova", "wd5", "Vernova_ExternalSite", "GE Vernova"),
    ("gehc", "wd5", "GEHC_ExternalSite", "GE HealthCare"),
    ("philips", "wd3", "jobs-and-careers", "Philips"),
    ("abb", "wd3", "External_Career_Page", "ABB"),
    ("spgi", "wd5", "SPGI_Careers", "S&P Global"),
    ("mastercard", "wd1", "CorporateCareers", "Mastercard"),
    ("citi", "wd5", "2", "Citi"),
    ("ms", "wd5", "External", "Morgan Stanley"),
    ("barclays", "wd3", "External_Career_Site_Barclays", "Barclays"),
    ("db", "wd3", "DBWebsite", "Deutsche Bank"),
    ("blackrock", "wd1", "BlackRock_Professional", "BlackRock"),
    ("nasdaq", "wd1", "Global_External_Site", "Nasdaq"),
    ("lseg", "wd3", "Careers", "LSEG"),
    ("thomsonreuters", "wd5", "External_Career_Site", "Thomson Reuters"),
    ("transunion", "wd5", "TransUnion", "TransUnion"),
    ("equifax", "wd5", "External", "Equifax"),
    ("target", "wd5", "targetcareers", "Target"),
    ("motorolasolutions", "wd5", "Careers", "Motorola Solutions"),
    ("paypal", "wd1", "jobs", "PayPal"),
    ("adobe", "wd5", "external_experienced", "Adobe"),
    ("jabil", "wd5", "Jabil_Careers", "Jabil"),
    ("cat", "wd5", "CaterpillarCareers", "Caterpillar"),
    ("medtronic", "wd1", "MedtronicCareers", "Medtronic"),
    ("novartis", "wd3", "Novartis_Careers", "Novartis"),
    ("sanofi", "wd3", "SanofiCareers", "Sanofi"),
    ("pfizer", "wd1", "PfizerCareers", "Pfizer"),
    ("astrazeneca", "wd3", "Careers", "AstraZeneca"),
    ("hp", "wd5", "ExternalCareerSite", "HP"),
    ("stryker", "wd1", "StrykerCareers", "Stryker"),
    ("statestreet", "wd1", "Global", "State Street"),
    ("kyndryl", "wd5", "KyndrylProfessionalCareers", "Kyndryl"),
    ("redhat", "wd5", "Jobs", "Red Hat"),
    ("ebay", "wd5", "apply", "eBay"),
    ("visa", "wd5", "Visa", "Visa"),
    ("gartner", "wd5", "EXT", "Gartner"),
    ("iqvia", "wd1", "IQVIA", "IQVIA"),
    ("abbott", "wd5", "abbottcareers", "Abbott"),
    ("baxter", "wd1", "Baxter", "Baxter"),
    ("bdx", "wd1", "EXTERNAL_CAREER_SITE_INDIA", "BD"),
    ("danaher", "wd1", "DanaherJobs", "Danaher"),
    ("thermofisher", "wd5", "ThermoFisherCareers", "Thermo Fisher"),
    ("roche", "wd3", "roche-ext", "Roche"),
    ("gsk", "wd5", "GSKCareers", "GSK"),
    ("amgen", "wd1", "Careers", "Amgen"),
    ("unilever", "wd3", "Unilever_Experienced_Professionals", "Unilever"),
    ("pg", "wd5", "1000", "Procter & Gamble"),
    ("diageo", "wd3", "Diageo_Careers", "Diageo"),
    ("nike", "wd1", "nke", "Nike"),
    ("maersk", "wd3", "Maersk_Careers", "Maersk"),
    ("generalmotors", "wd5", "Careers_GM", "General Motors"),
    ("fiserv", "wd5", "EXT", "Fiserv"),
]

SEARCH_QUERIES = [
    "India intern", "India graduate", "India fresher", "India apprentice",
    "India trainee", "India associate", "India campus", "India junior",
    "India entry", "India analyst", "India developer",
    "Bengaluru intern", "Hyderabad intern", "Pune intern"
]


def _post_json(url: str, payload: dict, timeout: int = 7) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; BeepJobHub/1.0)",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def _get_json(url: str, timeout: int = 7) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; BeepJobHub/1.0)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def _to_iso_date(date_str: str) -> str:
    if not date_str:
        return ""
    s = date_str.strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return f"{s}T23:59:59+00:00"
    return s


def fetch_single_workday_company(tenant: str, wd: str, site: str, display_name: str) -> List[RawJob]:
    """Queries a Workday CXS board for India fresher/intern postings and hydrates full JDs."""
    base_api = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    list_url = f"{base_api}/jobs"
    seen_paths = set()
    candidates = []

    for q in SEARCH_QUERIES:
        for offset in (0, 20):
            try:
                data = _post_json(list_url, {"limit": 20, "offset": offset, "searchText": q}, timeout=6)
                postings = data.get("jobPostings") or []
                for item in postings:
                    ext_path = item.get("externalPath")
                    if not ext_path or ext_path in seen_paths:
                        continue
                    title = (item.get("title") or "").strip()
                    if not title or SENIOR_TITLE_REGEX.search(title):
                        continue
                    loc_text = (item.get("locationsText") or "").strip()
                    # Check locationText OR externalPath for India signal (Workday often puts "2 Locations" in locationsText)
                    hint = f"{loc_text} {ext_path.replace('-', ' ')}"
                    valid_loc, _ = is_india_location(hint, allow_bare_remote=False)
                    if not valid_loc and "locations" not in loc_text.lower():
                        continue
                    seen_paths.add(ext_path)
                    candidates.append((title, loc_text, ext_path))
                if len(postings) < 20:
                    break
            except Exception as e:
                logger.debug(f"Workday query {tenant}/{site} ({q}@{offset}) skipped: {e}")
                break

    jobs: List[RawJob] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for title, list_loc, ext_path in candidates[:65]:
        try:
            detail = _get_json(f"{base_api}{ext_path}", timeout=6)
            info = detail.get("jobPostingInfo") or {}
            if not info:
                continue

            # Resolve real location from primary + additional locations
            primary_loc = (info.get("location") or "").strip()
            add_locs = [str(x) for x in (info.get("additionalLocations") or [])]
            loc_raw = primary_loc or list_loc
            valid_loc, city = is_india_location(loc_raw, allow_bare_remote=False)
            if not valid_loc or city == "Unknown":
                for al in add_locs:
                    v, c = is_india_location(al, allow_bare_remote=False)
                    if v and c != "Unknown":
                        valid_loc, city, loc_raw = True, c, al
                        break
            if not valid_loc or city == "Unknown":
                continue

            desc_text = clean_html(info.get("jobDescription", ""))[:8000]
            if not desc_text or not is_fresher_job(title, desc_text):
                continue

            end_date = _to_iso_date(info.get("endDate") or "")
            if end_date and end_date < now_iso:
                continue

            start_date = _to_iso_date(info.get("startDate") or "") or now_iso
            apply_url = (info.get("externalUrl") or f"https://{tenant}.{wd}.myworkdayjobs.com/{site}{ext_path}").strip()
            job_req_id = str(info.get("jobReqId") or info.get("id") or ext_path.split("_")[-1])[:60]

            jobs.append(RawJob(
                title=title,
                company=display_name,
                location_raw=loc_raw,
                city=city,
                job_type=extract_job_type(title, desc_text),
                apply_url=apply_url,
                description=desc_text,
                source_name="workday",
                source_job_id=f"{tenant}:{job_req_id}",
                posted_date=start_date,
                expires_at=end_date or None,
                last_verified_at=now_iso,
            ))
        except Exception as e:
            logger.debug(f"Workday detail {tenant}{ext_path} skipped: {e}")

    return jobs


def fetch_workday_jobs() -> List[RawJob]:
    """Fetches and normalizes live fresher/intern jobs across all configured Workday boards concurrently."""
    results: List[RawJob] = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [
            executor.submit(fetch_single_workday_company, t, wd, s, name)
            for t, wd, s, name in WORKDAY_COMPANIES
        ]
        for f in as_completed(futures):
            try:
                results.extend(f.result())
            except Exception:
                pass
    logger.info(f"Workday adapter collected {len(results)} verified fresher jobs")
    return results
