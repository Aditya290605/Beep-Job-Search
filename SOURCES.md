# Data Sources & Legality Audit (Submission Copy)

> **Verified Against:** Live Cloud Run PostgreSQL database (`237` active jobs as of `2026-11-20T04:37Z`, Run #12) and codebase `backend/app/adapters/*.py`.
> **Automated `robots.txt` check in code:** **NO** — none of the adapters programmatically fetch or parse `robots.txt` before making requests. Compliance relies on using public JSON job syndication APIs and open-source GitHub feeds rather than scraping blocked consumer portals (Naukri, LinkedIn, Indeed, Internshala).

---

## Ready-to-Paste SOURCES Table

| # | Source Name | Endpoint / URL Pattern | Access Method | Auth Required | Live Active Posts (Cloud SQL) | Local DB Active Posts | `robots.txt` Checked in Code? | Legal / Terms / Risk Assessment |
|---|-------------|------------------------|---------------|---------------|-------------------------------|-----------------------|-------------------------------|---------------------------------|
| 1 | **Workday CXS** (`adapters/workday.py`) | `POST/GET https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` (68 enterprise boards: NVIDIA, Intel, Citi, Deutsche Bank, Cisco, HPE, Airbus, Mastercard, etc.) | Undocumented public JSON XHR API (reverse-engineered career portal backend) | None | **128** (54.0%) | 112 | No | **MODERATE RISK (Grey Area):** Publicly readable JSON used by companies' own career pages, no login/bypass, identifies as `BeepJobHub/1.0`. However, Workday CXS is not a formally published developer API; individual employer ToS may restrict automated harvesting and rate-limit bursts (currently 14 search queries × 2 offsets × 68 boards). Should add polite rate limiting & `robots.txt` check. |
| 2 | **GitHub Fresher Feeds** (`adapters/github_jobs.py` + `verifier.py`) | 6 raw GitHub files (`Sarthzk/internship-tracker`, `SimplifyJobs/New-Grad-Positions`, `SimplifyJobs/Summer2025-Internships`, `ambicuity/New-Grad-Jobs`, `speedyapply/2026-SWE-College-Jobs`) **+ live HTTP/ATS hydration of each apply URL** | Public raw GitHub JSON/Markdown + ATS JSON APIs + HTML GET for JSON-LD on non-ATS URLs | None | **56** (23.6%) | 43 | No | **LOW-TO-MODERATE RISK:** GitHub community trackers are public open-source repos (MIT/CC0/community lists). However, `_verify_generic_http()` (`verifier.py:295-348`) sends a Chrome browser `User-Agent` string (`Chrome/126.0.0.0`) to fetch HTML from arbitrary employer career pages (e.g., Microsoft, Swiss Re, Rippling) without checking `robots.txt` — spoofing a browser UA on non-ATS sites is a yellow flag you should clean up or explicitly defend. |
| 3 | **Greenhouse Job Board API** (`adapters/greenhouse.py`) | `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` (70 boards: Razorpay, Stripe, Rubrik, Canonical, Roblox, Celonis, etc.) | Official documented Public Job Board JSON API | None | **29** (12.2%) | 29 | No | **LOW RISK (Clean & Legal):** Explicitly documented public syndication API published by Greenhouse for external career sites and aggregators (`developers.greenhouse.io/job-board.html`). Uses custom `FresherJobsIndiaBot/1.0` UA. |
| 4 | **Lever Postings API** (`adapters/lever.py`) | `GET https://api.lever.co/v0/postings/{slug}?mode=json` (10 boards: Paytm, CRED, Meesho, Hevo Data, Porter, Pocket FM, etc.) | Official documented Public Postings JSON API | None | **16** (6.8%) | 15 | No | **LOW RISK (Clean & Legal):** Official public JSON feed documented by Lever for external job boards (`github.com/lever/postings-api`). |
| 5 | **SmartRecruiters Posting API** (`adapters/smartrecruiters.py`) | `GET https://api.smartrecruiters.com/v1/companies/{id}/postings` & `/postings/{job_id}` (22 boards: Swiggy, PhonePe, Bosch, Visa, Avery Dennison, etc.) | Official documented Public Posting API | None | **6** (2.5%) | 6 | No | **LOW RISK (Clean & Legal):** Official public SmartRecruiters Posting API (`developers.smartrecruiters.com/reference/posting-api`). |
| 6 | **Ashby Public Job Board API** (`adapters/ashby.py`) | `GET https://api.ashbyhq.com/posting-api/job-board/{board}` (29 boards: Sarvam AI, Atlan, Plane, SigNoz, Linear, PostHog, etc.) | Official documented Public Job Board API | None | **1** (0.4%) | 1 | No | **LOW RISK (Clean & Legal):** Official public Posting API documented by Ashby (`developers.ashbyhq.com/docs/public-job-posting-api`). |
| 7 | **Remotive API** (`adapters/remotive.py`) | `GET https://remotive.com/api/remote-jobs?limit=100` | Official public REST API | None | **1** (0.4%) | 1 | No | **LOW RISK (Attribution Required):** Official public API. Remotive ToS requires: (a) max ~4 requests/day (our 2-hour cron calls it **12x/day — exceeds Remotive's recommended 4x/day limit!**), (b) direct link back to `remotive.com` URL (we DO preserve `item["url"]`), and (c) visible Remotive attribution (shown as "Verified via Remotive API"). |
| 8 | **Jobicy API** (`adapters/jobicy.py`) | `GET https://jobicy.com/api/v2/remote-jobs?count=50&geo=apac` | Official public REST API | None | **0** (0.0%) | 0 | No | **LOW RISK (Attribution Required):** Official public API for remote job syndication. Currently returning 0 India fresher matches (APAC remote roles are mostly senior). |

**Total Live Active Posts:** **237** across **87** unique companies (all 237 have unique `apply_url` values).

---

## Explicitly Excluded Platforms (Compliance Safeguards)

The following high-traffic Indian job portals were intentionally **NOT** scraped because their `robots.txt` and Terms of Service forbid automated harvesting and enforce anti-bot protections:
- **LinkedIn Jobs** — Prohibits scraping in User Agreement; `robots.txt` disallows `/jobs/search/`.
- **Naukri.com** — Prohibits automated extraction in ToS; Akamai/Cloudflare WAF.
- **Indeed India** — Explicitly prohibits automated scraping in ToS.
- **Internshala** — Prohibits scraping in ToS; Cloudflare Turnstile protection.
