"""
backend/app/verifier.py - Live ATS Job Hydration & Expiry Verifier

Verifies that a job URL is genuinely OPEN (not 404, closed, or redirected to a generic
careers search page) and hydrates the REAL full job description, location, and official
expiry date (expires_at / validThrough / endDate) directly from official ATS APIs or JSON-LD.

Uses Python standard library only.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import urlparse, parse_qs

from app.adapters.base import clean_html

logger = logging.getLogger(__name__)

CLOSED_TEXT_RE = re.compile(
    r"this job is no longer available|"
    r"job is no longer available|"
    r"position is no longer available|"
    r"job posting is no longer|"
    r"no longer accepting applications|"
    r"position has been filled|"
    r"this posting has expired|"
    r"this posting is closed|"
    r"this job has been closed|"
    r"job has expired|"
    r"requisition is no longer open|"
    r"sorry,?\s*the job you are looking for|"
    r"job not found|"
    r"couldn['’]t find that job|"
    r"we couldn['’]t find the page",
    re.IGNORECASE,
)

GENERIC_PATH_RE = re.compile(
    r"^/?(careers|jobs|jobs/search|careers/search|open-roles|open-positions|students|search)/?$",
    re.IGNORECASE,
)

# Simple in-process cache for Ashby boards during a single run
_ASHBY_BOARD_CACHE: Dict[str, Dict[str, dict]] = {}


@dataclass
class VerificationResult:
    is_open: bool
    reason: str = "ok"
    description: Optional[str] = None
    location_raw: Optional[str] = None
    apply_url: Optional[str] = None
    posted_date: Optional[str] = None
    expires_at: Optional[str] = None
    verified_at: str = ""

    def __post_init__(self):
        if not self.verified_at:
            self.verified_at = datetime.now(timezone.utc).isoformat()


def _http_get_json(url: str, timeout: int = 8) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; BeepJobHub/1.0)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def _parse_iso_date(val: Optional[str]) -> Optional[str]:
    if not val or not isinstance(val, str):
        return None
    s = val.strip()
    if not s:
        return None
    try:
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            dt = datetime.fromisoformat(s + "T23:59:59+00:00")
            return dt.isoformat()
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


def _is_expired_iso(iso_str: Optional[str]) -> bool:
    if not iso_str:
        return False
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt < datetime.now(timezone.utc)
    except Exception:
        return False


def _verify_greenhouse(board: str, job_id: str, orig_url: str, timeout: int = 8) -> VerificationResult:
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
    try:
        data = _http_get_json(api_url, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return VerificationResult(is_open=False, reason=f"greenhouse_{e.code}")
        return VerificationResult(is_open=True, reason=f"greenhouse_http_{e.code}")
    except Exception as e:
        return VerificationResult(is_open=True, reason=f"greenhouse_err_{type(e).__name__}")

    desc = clean_html(data.get("content", ""))[:8000]
    loc = ((data.get("location") or {}).get("name") or "").strip() or None
    updated = _parse_iso_date(data.get("updated_at"))
    abs_url = (data.get("absolute_url") or orig_url or "").strip()
    # If company's custom absolute_url points to a generic search page, prefer direct Greenhouse board URL
    parsed = urlparse(abs_url)
    if GENERIC_PATH_RE.match(parsed.path or ""):
        abs_url = f"https://job-boards.greenhouse.io/{board}/jobs/{job_id}"
    return VerificationResult(
        is_open=True,
        reason="greenhouse_open",
        description=desc or None,
        location_raw=loc,
        apply_url=abs_url,
        posted_date=updated,
    )


def _verify_lever(company: str, job_id: str, orig_url: str, timeout: int = 8) -> VerificationResult:
    api_url = f"https://api.lever.co/v0/postings/{company}/{job_id}"
    try:
        data = _http_get_json(api_url, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return VerificationResult(is_open=False, reason=f"lever_{e.code}")
        return VerificationResult(is_open=True, reason=f"lever_http_{e.code}")
    except Exception as e:
        return VerificationResult(is_open=True, reason=f"lever_err_{type(e).__name__}")

    parts = []
    intro = data.get("descriptionPlain") or clean_html(data.get("description", ""))
    if intro:
        parts.append(intro)
    for lst in data.get("lists") or []:
        heading = (lst.get("text") or "").strip()
        content = clean_html(lst.get("content", ""))
        if heading and content:
            parts.append(f"{heading}\n{content}")
        elif content:
            parts.append(content)
    extra = data.get("additionalPlain") or clean_html(data.get("additional", ""))
    if extra:
        parts.append(extra)
    full_desc = "\n\n".join(parts)[:8000]
    loc = ((data.get("categories") or {}).get("location") or "").strip() or None
    return VerificationResult(
        is_open=True,
        reason="lever_open",
        description=full_desc or None,
        location_raw=loc,
        apply_url=data.get("hostedUrl") or orig_url,
    )


def _verify_smartrecruiters(company: str, job_id: str, orig_url: str, timeout: int = 8) -> VerificationResult:
    api_url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{job_id}"
    try:
        data = _http_get_json(api_url, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return VerificationResult(is_open=False, reason=f"smartrecruiters_{e.code}")
        return VerificationResult(is_open=True, reason=f"smartrecruiters_http_{e.code}")
    except Exception as e:
        return VerificationResult(is_open=True, reason=f"smartrecruiters_err_{type(e).__name__}")

    if data.get("active") is False:
        return VerificationResult(is_open=False, reason="smartrecruiters_inactive")

    sections = (data.get("jobAd") or {}).get("sections") or {}
    parts = []
    for sec_key in ("jobDescription", "qualifications", "additionalInformation"):
        sec = sections.get(sec_key) or {}
        title = (sec.get("title") or "").strip()
        text = clean_html(sec.get("text", ""))
        if text:
            parts.append(f"{title}\n{text}" if title else text)
    full_desc = "\n\n".join(parts)[:8000]
    loc_obj = data.get("location") or {}
    loc = ", ".join(filter(None, [loc_obj.get("city"), loc_obj.get("region"), loc_obj.get("country")])) or None
    return VerificationResult(
        is_open=True,
        reason="smartrecruiters_open",
        description=full_desc or None,
        location_raw=loc,
        apply_url=data.get("postingUrl") or orig_url,
        posted_date=_parse_iso_date(data.get("releasedDate")),
    )


def _verify_workday(url: str, timeout: int = 8) -> VerificationResult:
    # Matches https://{tenant}.{wd}.myworkdayjobs.com/(en-US/)?{site}/job/...
    m = re.match(
        r"^https?://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/job/[^?#]+)",
        url,
    )
    if not m:
        return _verify_generic_http(url, timeout=timeout)
    tenant, wd, site, job_path = m.group(1), m.group(2), m.group(3), m.group(4)
    cxs_url = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{job_path}"
    try:
        data = _http_get_json(cxs_url, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return VerificationResult(is_open=False, reason=f"workday_{e.code}")
        return VerificationResult(is_open=True, reason=f"workday_http_{e.code}")
    except Exception as e:
        return VerificationResult(is_open=True, reason=f"workday_err_{type(e).__name__}")

    info = data.get("jobPostingInfo") or {}
    if not info:
        return VerificationResult(is_open=False, reason="workday_empty_info")

    desc = clean_html(info.get("jobDescription", ""))[:8000]
    loc = (info.get("location") or "").strip() or None
    start_date = _parse_iso_date(info.get("startDate"))
    end_date = _parse_iso_date(info.get("endDate"))
    if _is_expired_iso(end_date):
        return VerificationResult(is_open=False, reason="workday_expired_endDate", expires_at=end_date)

    return VerificationResult(
        is_open=True,
        reason="workday_open",
        description=desc or None,
        location_raw=loc,
        apply_url=info.get("externalUrl") or url,
        posted_date=start_date,
        expires_at=end_date,
    )


def _verify_ashby(board: str, job_id: str, orig_url: str, timeout: int = 8) -> VerificationResult:
    if board not in _ASHBY_BOARD_CACHE:
        try:
            data = _http_get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}", timeout=timeout)
            _ASHBY_BOARD_CACHE[board] = {str(j.get("id")): j for j in (data.get("jobs") or [])}
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                _ASHBY_BOARD_CACHE[board] = {}
            else:
                return VerificationResult(is_open=True, reason=f"ashby_http_{e.code}")
        except Exception as e:
            return VerificationResult(is_open=True, reason=f"ashby_err_{type(e).__name__}")

    item = _ASHBY_BOARD_CACHE[board].get(job_id)
    if not item:
        return VerificationResult(is_open=False, reason="ashby_not_listed")
    desc = (item.get("descriptionPlain") or clean_html(item.get("descriptionHtml", "")))[:8000]
    return VerificationResult(
        is_open=True,
        reason="ashby_open",
        description=desc or None,
        location_raw=item.get("location") or None,
        apply_url=item.get("jobUrl") or orig_url,
        posted_date=_parse_iso_date(item.get("publishedAt")),
    )


def _extract_jsonld_job(html_body: str) -> Optional[dict]:
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_body, re.I | re.S):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        candidates = parsed if isinstance(parsed, list) else (parsed.get("@graph", [parsed]) if isinstance(parsed, dict) else [])
        for obj in candidates:
            if isinstance(obj, dict) and str(obj.get("@type", "")).lower() == "jobposting":
                return obj
    return None


def _verify_generic_http(url: str, timeout: int = 8) -> VerificationResult:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; BeepJobHub/1.0; +https://github.com/Aditya290605/Beep-Job-Search)",
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            body = resp.read(250000).decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return VerificationResult(is_open=False, reason=f"http_{e.code}")
        # 403/429 are often bot firewalls (e.g. Cloudflare on Rubrik) rather than closed jobs
        return VerificationResult(is_open=True, reason=f"http_{e.code}_unverified")
    except Exception as e:
        return VerificationResult(is_open=True, reason=f"err_{type(e).__name__}")

    # Reject explicit closed/not-found redirect query markers (e.g. Rippling ?rr_message=job_not_found)
    if re.search(r"(?:job_not_found|posting_closed|position_filled|error=not_found)", final_url, re.I):
        return VerificationResult(is_open=False, reason="closed_query_marker", apply_url=final_url)

    # If redirected to an ATS URL (e.g. shortlink -> Greenhouse/Lever/Workday), verify via ATS API!
    if final_url != url and any(
        d in final_url for d in ("greenhouse.io/", "jobs.lever.co/", "jobs.smartrecruiters.com/", "myworkdayjobs.com/", "jobs.ashbyhq.com/")
    ):
        return verify_and_hydrate(final_url, timeout=timeout)

    # Detect redirect to a generic careers/search homepage (classic closed-job behavior, e.g. Stripe /careers/search)
    parsed_final = urlparse(final_url)
    if GENERIC_PATH_RE.match(parsed_final.path or "") and not any(
        k in (parsed_final.query or "").lower() for k in ("jobid=", "id=", "req=")
    ):
        return VerificationResult(is_open=False, reason="redirected_to_generic_careers_page", apply_url=final_url)

    # Check JSON-LD JobPosting structured data (Gold standard for Google/Microsoft/Apple/Oracle/custom portals)
    jld = _extract_jsonld_job(body)
    if jld:
        valid_through = _parse_iso_date(jld.get("validThrough"))
        if _is_expired_iso(valid_through):
            return VerificationResult(is_open=False, reason="jsonld_expired", expires_at=valid_through)
        desc = clean_html(jld.get("description", ""))[:8000]
        posted = _parse_iso_date(jld.get("datePosted"))
        return VerificationResult(
            is_open=True,
            reason="jsonld_open",
            description=desc or None,
            apply_url=final_url,
            posted_date=posted,
            expires_at=valid_through,
        )

    if CLOSED_TEXT_RE.search(body):
        return VerificationResult(is_open=False, reason="closed_text_detected")

    return VerificationResult(is_open=True, reason="http_ok", apply_url=final_url)


def verify_and_hydrate(
    apply_url: str,
    source_name: str = "",
    source_job_id: str = "",
    gh_board_hint: Optional[str] = None,
    timeout: int = 8,
) -> VerificationResult:
    """
    Verifies liveness and hydrates full JD/location/expiry for any job URL.
    Automatically dispatches to official ATS JSON APIs whenever recognized.
    """
    if not apply_url or not apply_url.startswith("http"):
        return VerificationResult(is_open=False, reason="invalid_url")

    # 1. Greenhouse URL pattern
    m_gh = re.search(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/([^/]+)/jobs/(\d+)", apply_url)
    if m_gh:
        return _verify_greenhouse(m_gh.group(1), m_gh.group(2), apply_url, timeout=timeout)

    # Greenhouse custom domain with ?gh_jid= (infer board slug from domain if hint not supplied)
    parsed_u = urlparse(apply_url)
    qs = parse_qs(parsed_u.query)
    if "gh_jid" in qs:
        board_guess = gh_board_hint
        if not board_guess:
            host_parts = [p for p in (parsed_u.netloc or "").lower().split(".") if p not in ("www", "jobs", "careers", "apply", "com", "co", "io", "ai", "in", "org", "net")]
            if host_parts:
                board_guess = re.sub(r"[^a-z0-9]", "", host_parts[0])
        if board_guess:
            res = _verify_greenhouse(board_guess, qs["gh_jid"][0], apply_url, timeout=timeout)
            if res.reason == "greenhouse_open" or res.reason in ("greenhouse_404", "greenhouse_410"):
                return res

    # 2. Lever URL pattern
    m_lv = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{20,})", apply_url, re.IGNORECASE)
    if m_lv:
        return _verify_lever(m_lv.group(1), m_lv.group(2), apply_url, timeout=timeout)

    # 3. SmartRecruiters URL pattern
    m_sr = re.search(r"jobs\.smartrecruiters\.com/([^/]+)/(\d+)", apply_url)
    if m_sr:
        return _verify_smartrecruiters(m_sr.group(1), m_sr.group(2), apply_url, timeout=timeout)

    # 4. Workday URL pattern
    if ".myworkdayjobs.com/" in apply_url:
        return _verify_workday(apply_url, timeout=timeout)

    # 5. Ashby URL pattern
    m_ash = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{20,})", apply_url, re.IGNORECASE)
    if m_ash:
        return _verify_ashby(m_ash.group(1), m_ash.group(2), apply_url, timeout=timeout)

    # 6. Generic HTTP / JSON-LD fallback
    return _verify_generic_http(apply_url, timeout=timeout)
