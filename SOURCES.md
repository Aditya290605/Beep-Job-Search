# SOURCES.md: Data Sources Audit & Legal Compliance

> Last updated: 17 Nov 2026.
> Strategy: Multi-source aggregation prioritizing official public APIs with NO keys or rate limits, complemented by a quota-budgeted Adzuna adapter and verified legal public endpoints.

---

## 1. Summary of Active Sources (All 100% Free, Zero API Keys, No Daily Caps)

| # | Source | Method | Auth Required | Daily Limit | Legal / ToS / robots.txt Verdict | India Fresher Expected Yield |
|---|--------|--------|---------------|-------------|-----------------------------------|------------------------------|
| 1 | **Greenhouse Job Boards** | Public JSON `boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true` | None (Public) | None | **100% Legal & Approved**: Official public career site API provided by Greenhouse for public job syndication. | 60–150 posts across 30+ companies |
| 2 | **Lever Postings API** | Public JSON `api.lever.co/v0/postings/{company}?mode=json` | None (Public) | None | **100% Legal & Approved**: Official public syndication feed provided by Lever. | 30–80 posts across 20+ companies |
| 3 | **Ashby Job Boards** | Public JSON `api.ashbyhq.com/posting-api/job-board/{board}` | None (Public) | None | **100% Legal & Approved**: Official public career site API provided by Ashby. | 25–60 posts across 15+ companies |
| 4 | **SmartRecruiters API** | Public JSON `api.smartrecruiters.com/v1/companies/{company}/postings` | None (Public) | None | **100% Legal & Approved**: Official public postings API for active jobs. | 30–70 posts |
| 5 | **Jobicy Remote Jobs API** | REST API `jobicy.com/api/v2/remote-jobs?count=50&geo=india` | None (Public) | Generous (~100 req/hr) | **100% Legal & Approved**: Dedicated free developer API for job syndication with attribution. | 20–50 posts |
| 6 | **Remotive API** | REST API `remotive.com/api/remote-jobs` | None (Public) | Rate-limited to ~2 req/min | **100% Legal & Approved**: Official public API for developer aggregators. Requires backlink/attribution. | 20–40 fresher/intern posts |

*(Note: Adzuna was evaluated and completely dropped due to its restrictive 25 calls/day limit and commercial licensing terms. We have 6 robust zero-key sources that easily supply 200+ posts.)*

---

## 2. Robots.txt & Scraping Assessment of Popular Job Boards

| Platform | `robots.txt` Status | Terms of Service (ToS) | Bot Protection | Verdict |
|----------|---------------------|------------------------|----------------|---------|
| **Naukri.com** | `Disallow: /` on job searches, search results | Explicitly prohibits automated data harvesting & bots | Cloudflare / Akamai Enterprise | **STRICTLY EXCLUDED**: Violates ToS and triggers automated IP bans. |
| **LinkedIn Jobs** | `Disallow: /jobs/search/` | Prohibits scrapers, automated access without written agreement | PerimeterX / Cloudflare | **STRICTLY EXCLUDED**: High legal & ban risk. |
| **Internshala** | `Disallow: /internships/*` for non-standard bots | Strict clause against commercial or automated scraping | Cloudflare Turnstile | **STRICTLY EXCLUDED**: Prohibited by terms. |
| **Indeed India** | `Disallow: /jobs` for scrapers | Explicit anti-scraping policy in Terms of Use | Cloudflare + CAPTCHAs | **STRICTLY EXCLUDED**: Violates ToS. |
| **Cutshort.io** | Disallows automated search queries | Forbids unauthorized harvesting of job seeker / employer data | Cloudflare | **EXCLUDED**: Better to use ATS endpoints directly. |
| **Instahyre** | Disallows search result enumeration | Forbids scraping job listings and candidate profiles | Rate limiting + Cloudflare | **EXCLUDED**. |
| **Hasjob (Hasgeek)** | Allows reading public feeds; has Atom/RSS feed | Open source platform; respectful crawling of RSS feeds allowed | Low / standard | **Candidate for RSS feed parsing** |

### Why Direct ATS Feeds Win:
Rather than scraping protected portals (which violates ToS and breaks whenever HTML changes), querying direct ATS endpoints (Greenhouse, Lever, Ashby, SmartRecruiters) connects directly to the **origin of the job post**. Employers publish their jobs to Greenhouse/Lever so they can be discovered. These endpoints are permanent, structured JSON, legal, and require zero credentials!

---

## 3. Top India Hiring Companies Configured in ATS Directory

### Greenhouse Companies (India Hubs):
`razorpay`, `cred`, `swiggy`, `postman`, `browserstack`, `clevertap`, `elastic`, `couchbase`, `thoughtspot`, `rubrik`, `airbase`, `gusto`, `samsara`, `sprinklr`, `branch`, `harness`, `coinbase`, `rippling`, `databricks`, `stripe`, `affirm`, `klaviyo`, `canva`, `mongodb`

### Lever Companies (India Hubs):
`atlan`, `invideo`, `moengage`, `khatabook`, `urbancompany`, `scaler`, `hotstar`, `fynd`, `kredivo`

### Ashby Companies (Tech & AI Startups with Remote/India):
`replit`, `cursor`, `vapi`, `synthesia`, `perplexity`, `together-ai`, `mercor`, `sentry`, `ramp`, `linear`, `posthog`, `retool`

### SmartRecruiters Companies:
`publicisgroupe`, `bosch`, `ubisoft`, `visa`
