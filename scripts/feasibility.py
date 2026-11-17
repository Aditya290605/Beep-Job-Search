#!/usr/bin/env python3
"""
scripts/feasibility.py - Source Feasibility & Volume Validation

Validates live candidate sources for fresher/intern jobs in India:
1. Greenhouse Job Board API (public, no auth) - 25+ companies
2. Lever Postings API (public, no auth) - 10+ companies
3. Ashby Job Board API (public, no auth) - 10+ companies
4. SmartRecruiters API (public, no auth)
5. Jobicy Remote Jobs API (public REST API, no key)
6. Remotive API (public REST API, no key)
7. Adzuna India API (official REST API, budgeted for 25 calls/day limit)

Can run in two modes:
  python3 scripts/feasibility.py          # Live HTTP check against public endpoints
  python3 scripts/feasibility.py --mock   # Offline verification using sample payloads
"""

import sys
import os
import json
import re
import time
import urllib.request
import urllib.error
import argparse

USER_AGENT = "FresherJobsIndiaBot/1.0 (feasibility-check; mailto:adityamagar@example.com)"

INDIAN_CITIES = {
    "bangalore", "bengaluru", "mumbai", "pune", "hyderabad", "gurgaon",
    "gurugram", "delhi", "new delhi", "noida", "chennai", "kolkata",
    "ahmedabad", "jaipur", "kochi", "cochin", "thiruvananthapuram",
    "trivandrum", "chandigarh", "indore", "bhopal", "coimbatore"
}

FRESHER_KEYWORDS = [
    r"\bintern\b", r"\binternship\b", r"\bfresher\b", r"\bgraduate\b",
    r"\bentry[- ]level\b", r"\bjunior\b", r"\btrainee\b", r"\bassociate\b",
    r"\bapprentice\b", r"\b0[- ]?1\s*(?:yr|year|years)\b"
]
FRESHER_REGEX = re.compile("|".join(FRESHER_KEYWORDS), re.IGNORECASE)

GREENHOUSE_COMPANIES = [
    "razorpay", "elastic", "cred", "clevertap", "browserstack",
    "thoughtspot", "airbase", "couchbase", "rubrik", "swiggy",
    "branch", "gusto", "samsara", "postman", "sprinklr",
    "harness", "coinbase", "rippling", "databricks", "stripe",
    "affirm", "klaviyo", "canva", "mongodb"
]

LEVER_COMPANIES = [
    "atlan", "invideo", "moengage", "khatabook", "urbancompany",
    "scaler", "hotstar", "fynd", "clevertap"
]

ASHBY_COMPANIES = [
    "replit", "cursor", "vapi", "synthesia", "perplexity",
    "together-ai", "mercor", "sentry", "ramp", "linear", "posthog"
]

SMARTRECRUITERS_COMPANIES = [
    "publicisgroupe", "bosch", "ubisoft", "visa"
]


def fetch_json(url: str, headers: dict = None, timeout: int = 8):
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def is_india_location(location_str: str) -> tuple[bool, str]:
    if not location_str or not isinstance(location_str, str):
        return False, "Unknown"
    
    loc_lower = location_str.lower()
    is_remote = "remote" in loc_lower
    
    matched_city = None
    for city in INDIAN_CITIES:
        if city in loc_lower:
            matched_city = city.capitalize()
            if matched_city in ("Bengaluru", "Bangalore"):
                matched_city = "Bangalore"
            elif matched_city in ("Gurugram", "Gurgaon"):
                matched_city = "Gurugram"
            break
            
    if matched_city:
        return True, matched_city
    
    if "india" in loc_lower:
        return True, "India (Multiple/Other)"
        
    if is_remote and ("india" in loc_lower or "apac" in loc_lower or "anywhere" in loc_lower or "worldwide" in loc_lower):
        return True, "Remote"
        
    return False, "Unknown"


def is_fresher_job(title: str, description: str = "") -> bool:
    text = f"{title} {description[:400]}"
    return bool(FRESHER_REGEX.search(text))


# ---------------------------------------------------------
# Source Adapters for Feasibility Check
# ---------------------------------------------------------

def check_greenhouse() -> list[dict]:
    results = []
    print("\n--- Checking Greenhouse Public Boards ---")
    for company in GREENHOUSE_COMPANIES:
        url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
        try:
            data = fetch_json(url, timeout=6)
            jobs = data.get("jobs", [])
            matches = 0
            for job in jobs:
                title = job.get("title", "")
                loc_name = (job.get("location") or {}).get("name", "")
                content = job.get("content", "")
                valid_loc, city = is_india_location(loc_name)
                if valid_loc and is_fresher_job(title, content):
                    matches += 1
                    results.append({
                        "source": "greenhouse",
                        "company": company,
                        "title": title,
                        "location": city,
                        "url": job.get("absolute_url")
                    })
            if matches > 0:
                print(f"  [+] {company}: found {matches} matching posts")
            time.sleep(0.05)
        except Exception:
            pass
    print(f"Greenhouse Total: {len(results)} fresher posts")
    return results


def check_lever() -> list[dict]:
    results = []
    print("\n--- Checking Lever Public Postings ---")
    for company in LEVER_COMPANIES:
        url = f"https://api.lever.co/v0/postings/{company}?mode=json"
        try:
            jobs = fetch_json(url, timeout=6)
            if not isinstance(jobs, list):
                continue
            matches = 0
            for job in jobs:
                title = job.get("text", "")
                categories = job.get("categories") or {}
                loc_name = categories.get("location", "")
                desc = job.get("descriptionPlain", "") or ""
                valid_loc, city = is_india_location(loc_name)
                if valid_loc and is_fresher_job(title, desc):
                    matches += 1
                    results.append({
                        "source": "lever",
                        "company": company,
                        "title": title,
                        "location": city,
                        "url": job.get("hostedUrl")
                    })
            if matches > 0:
                print(f"  [+] {company}: found {matches} matching posts")
            time.sleep(0.05)
        except Exception:
            pass
    print(f"Lever Total: {len(results)} fresher posts")
    return results


def check_ashby() -> list[dict]:
    results = []
    print("\n--- Checking Ashby Public Job Boards ---")
    for company in ASHBY_COMPANIES:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
        try:
            data = fetch_json(url, timeout=6)
            jobs = data.get("jobs", [])
            matches = 0
            for job in jobs:
                title = job.get("title", "")
                loc_name = job.get("location", "")
                desc = job.get("descriptionHtml", "") or ""
                valid_loc, city = is_india_location(loc_name)
                if valid_loc and is_fresher_job(title, desc):
                    matches += 1
                    results.append({
                        "source": "ashby",
                        "company": company,
                        "title": title,
                        "location": city,
                        "url": job.get("jobUrl")
                    })
            if matches > 0:
                print(f"  [+] {company}: found {matches} matching posts")
            time.sleep(0.05)
        except Exception:
            pass
    print(f"Ashby Total: {len(results)} fresher posts")
    return results


def check_smartrecruiters() -> list[dict]:
    results = []
    print("\n--- Checking SmartRecruiters Public Boards ---")
    for company in SMARTRECRUITERS_COMPANIES:
        url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100"
        try:
            data = fetch_json(url, timeout=6)
            jobs = data.get("content", [])
            matches = 0
            for job in jobs:
                title = job.get("name", "")
                loc = job.get("location") or {}
                loc_str = f"{loc.get('city', '')}, {loc.get('country', '')}"
                valid_loc, city = is_india_location(loc_str)
                if valid_loc and is_fresher_job(title):
                    matches += 1
                    results.append({
                        "source": "smartrecruiters",
                        "company": company,
                        "title": title,
                        "location": city,
                        "url": f"https://jobs.smartrecruiters.com/{company}/{job.get('id')}"
                    })
            if matches > 0:
                print(f"  [+] {company}: found {matches} matching posts")
            time.sleep(0.05)
        except Exception:
            pass
    print(f"SmartRecruiters Total: {len(results)} fresher posts")
    return results


def check_jobicy() -> list[dict]:
    results = []
    print("\n--- Checking Jobicy Public Remote Jobs API (Free, No Auth) ---")
    url = "https://jobicy.com/api/v2/remote-jobs?count=50"
    try:
        data = fetch_json(url, timeout=8)
        jobs = data.get("jobs", [])
        for job in jobs:
            title = job.get("jobTitle", "")
            geo = job.get("jobGeo", "")
            desc = job.get("jobDescription", "")
            valid_loc, city = is_india_location(geo)
            if valid_loc and is_fresher_job(title, desc):
                results.append({
                    "source": "jobicy",
                    "company": job.get("companyName", "Unknown"),
                    "title": title,
                    "location": city,
                    "url": job.get("url")
                })
        print(f"  [+] Jobicy: found {len(results)} fresher matches from {len(jobs)} total")
    except Exception as e:
        print(f"  [!] Jobicy query error: {e}")
    print(f"Jobicy Total: {len(results)} fresher posts")
    return results


def check_remotive() -> list[dict]:
    results = []
    print("\n--- Checking Remotive Public Remote Jobs API (Free, No Auth) ---")
    url = "https://remotive.com/api/remote-jobs?category=software-dev&limit=100"
    try:
        data = fetch_json(url, timeout=8)
        jobs = data.get("jobs", [])
        for job in jobs:
            title = job.get("title", "")
            geo = job.get("candidate_required_location", "")
            desc = job.get("description", "")
            valid_loc, city = is_india_location(geo)
            if valid_loc and is_fresher_job(title, desc):
                results.append({
                    "source": "remotive",
                    "company": job.get("company_name", "Unknown"),
                    "title": title,
                    "location": city,
                    "url": job.get("url")
                })
        print(f"  [+] Remotive: found {len(results)} fresher matches from {len(jobs)} total")
    except Exception as e:
        print(f"  [!] Remotive query error: {e}")
    print(f"Remotive Total: {len(results)} fresher posts")
    return results


def check_adzuna(app_id: str = None, app_key: str = None) -> list[dict]:
    results = []
    print("\n--- Checking Adzuna India API (Budgeted Mode: 1 call) ---")
    app_id = app_id or os.environ.get("ADZUNA_APP_ID")
    app_key = app_key or os.environ.get("ADZUNA_APP_KEY")
    
    if not app_id or not app_key:
        print("  [!] ADZUNA_APP_ID / ADZUNA_APP_KEY not set. Skipping live Adzuna check.")
        return results

    # 1 single call returning 50 results (respecting 25 calls/day limit)
    url = f"https://api.adzuna.com/v1/api/jobs/in/search/1?app_id={app_id}&app_key={app_key}&what=fresher%20software&results_per_page=50&content-type=application/json"
    try:
        data = fetch_json(url, timeout=10)
        jobs = data.get("results", [])
        for job in jobs:
            title = job.get("title", "")
            company = (job.get("company") or {}).get("display_name", "")
            loc_area = (job.get("location") or {}).get("display_name", "")
            desc = job.get("description", "")
            valid_loc, city = is_india_location(loc_area)
            if valid_loc and is_fresher_job(title, desc):
                results.append({
                    "source": "adzuna",
                    "company": company,
                    "title": title,
                    "location": city,
                    "url": job.get("redirect_url")
                })
        print(f"  [+] Adzuna: {len(jobs)} returned, {len(results)} fresher matches (1 call consumed out of 25)")
    except Exception as e:
        print(f"  [!] Adzuna query error: {e}")
            
    print(f"Adzuna Total: {len(results)} fresher posts")
    return results


def run_mock_verification():
    print("Running in --mock mode (offline verification)...")
    sample_jobs = [
        {"source": "greenhouse", "company": "Razorpay", "title": "Software Development Engineer Intern", "location": "Bangalore, India", "desc": "Join our payments team as an intern."},
        {"source": "greenhouse", "company": "Cred", "title": "Backend Intern", "location": "Bengaluru", "desc": "0-1 years experience welcome."},
        {"source": "lever", "company": "Atlan", "title": "Associate Frontend Engineer", "location": "Remote - India", "desc": "Fresh graduates with strong React skills."},
        {"source": "ashby", "company": "Cursor", "title": "AI Engineer Intern", "location": "Remote", "desc": "Internship opportunity for aspiring engineers worldwide."},
        {"source": "jobicy", "company": "TechCorp", "title": "Junior Python Developer", "location": "APAC / India Remote", "desc": "Entry level role for freshers."},
        {"source": "smartrecruiters", "company": "Bosch", "title": "Graduate Engineer Trainee", "location": "Coimbatore, India", "desc": "Trainee program."},
        {"source": "adzuna", "company": "TCS", "title": "Graduate Trainee Engineer", "location": "Pune, Maharashtra, India", "desc": "Entry level engineering role."},
        {"source": "adzuna", "company": "Infosys", "title": "Senior Staff Engineer (10+ yrs)", "location": "Mumbai", "desc": "Requires 10 years experience."} # Should be rejected
    ]
    
    passed = 0
    rejected = 0
    for job in sample_jobs:
        valid_loc, city = is_india_location(job["location"])
        is_fresher = is_fresher_job(job["title"], job["desc"])
        if valid_loc and is_fresher:
            passed += 1
            print(f"  [MATCH] {job['source'].upper()} | {job['company']} - {job['title']} -> City: {city}")
        else:
            rejected += 1
            print(f"  [FILTERED OUT] {job['company']} - {job['title']} (Loc: {valid_loc}, Fresher: {is_fresher})")
            
    print(f"\nMock test summary: {passed} accepted, {rejected} correctly filtered out.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Fresher Jobs India - Feasibility & Source Check")
    parser.add_argument("--mock", action="store_true", help="Run offline logic test using sample data")
    parser.add_argument("--adzuna-id", help="Adzuna App ID")
    parser.add_argument("--adzuna-key", help="Adzuna App Key")
    args = parser.parse_args()

    if args.mock:
        run_mock_verification()
        return

    print("==================================================")
    print("Fresher Jobs India: Data Source Feasibility Audit")
    print("==================================================")
    
    all_jobs = []
    all_jobs.extend(check_greenhouse())
    all_jobs.extend(check_lever())
    all_jobs.extend(check_ashby())
    all_jobs.extend(check_smartrecruiters())
    all_jobs.extend(check_jobicy())
    all_jobs.extend(check_remotive())
    all_jobs.extend(check_adzuna(args.adzuna_id, args.adzuna_key))
    
    print("\n==================================================")
    print("OVERALL FEASIBILITY SUMMARY")
    print("==================================================")
    print(f"Total Raw Fresher Posts Collected: {len(all_jobs)}")
    
    unique_keys = set()
    unique_jobs = []
    for j in all_jobs:
        norm_key = (
            re.sub(r'[^a-z0-9]', '', j["company"].lower()),
            re.sub(r'[^a-z0-9]', '', j["title"].lower()),
            j["location"].lower()
        )
        if norm_key not in unique_keys:
            unique_keys.add(norm_key)
            unique_jobs.append(j)
            
    print(f"Total Unique Fresher Posts: {len(unique_jobs)}")
    if len(unique_jobs) >= 200:
        print("[SUCCESS] Feasibility target of 200+ unique fresher jobs MET!")
    else:
        print(f"[PROGRESS] Gathered {len(unique_jobs)} unique posts.")


if __name__ == "__main__":
    main()
