# Beep Job Hub — Technical Submission Report

**Candidate Submission:** Gen AI & Engineering  
**Submission Date:** November 20, 2026  
**Live Application URL:** https://beep-job-hub-524515781472.asia-south1.run.app/  
**GitHub Repository:** https://github.com/Aditya290605/Beep-Job-Search  

---

## 1. System Architecture & Operational Design

Beep Job Hub is a production web application engineered to ingest, verify, deduplicate, classify, and index active entry-level (0–1 YOE) fresher and internship opportunities across India.

```
                              [ Cloud Scheduler ]
                                (0 */2 * * * IST)
                                       │ (HTTP Trigger)
                                       ▼
                             [ Cloud Run Job ]
                           (beep-refresh-job, 900s)
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                     ▼
   [ 8 Public Adapters ]                                 [ Deduplication Engine ]
   - Workday CXS (128 active)                            - Level 1: Canonical normalized key
   - GitHub Curated Trackers (56 active)                 - Level 2: RapidFuzz token_sort_ratio
   - Greenhouse API (29 active)                          - Guardrails: city, job_type, cohort,
   - Lever API (16 active)                                 and discipline-track barriers
   - SmartRecruiters API (6 active)                               │
   - Ashby API (1 active)                                         ▼
   - Remotive API (1 active)                             [ LLM Tagger & Verifier ]
   - Jobicy API (0 active)                               - Gemini 3.5 Flash-Lite (temp=0.1)
            │                                            - Live ATS JD & JSON-LD hydration
            │                                            - Strict 0-1 YOE gate & taxonomy
            │                                            - Cost logged to llm_cost_logs ($0.61/1k)
            └──────────────────────────┬──────────────────────────┘
                                       ▼
                       [ Cloud SQL PostgreSQL 15 ]
                        (beep-jobs-db, jobs_db)
                        - jobs (GIN index, full text search)
                        - job_sources (multi-source canonical URLs)
                        - pipeline_runs (audit & telemetry logs)
                        - llm_cost_logs (token usage tracking)
                                       │
                                       ▼
                       [ Cloud Run Web Service ]
                         (beep-job-hub, FastAPI)
                         - /api/jobs (p95 query response < 200ms)
                         - /api/filters, /api/status, /api/health
                         - Vanilla ES6 Single-Page UI (Zero npm bloat)
```

### Core Architecture Highlights
- **237 Active Verified Roles:** Covers 87 enterprise and high-growth technology employers in India (Google, Microsoft, Micron, HPE, Deutsche Bank, GSK, Rubrik, Swiggy, Meesho, PhonePe).
- **Zero-Scraping Data Ingestion:** 100% of postings originate from open, public ATS APIs and career site endpoints (Greenhouse, Lever, SmartRecruiters, Ashby, Workday CXS, Remotive). No brittle scraping of private aggregators (LinkedIn, Indeed, Naukri).
- **Deterministic Deduplication ($0 LLM Cost):** Exact canonical keys combined with `RapidFuzz` `token_sort_ratio` (`>=85%` company, `>=80%` title) bounded by domain-level guardrails preventing cross-discipline collisions.
- **Unattended Execution:** Cloud Scheduler triggers the Cloud Run Job every 2 hours. Over 7 consecutive unattended production runs have completed with 100% success rate.
- **Automated CI/CD:** GitHub Actions pipeline (`.github/workflows/deploy.yml`) runs 29 backend unit tests, validates JS syntax, builds Docker containers, pushes images to Artifact Registry, deploys Cloud Run services and jobs, and executes post-deployment smoke tests on every push to `main`.

---

## 2. Data Sources & Legal Compliance

All data acquisition adheres strictly to documented, publicly exposed API interfaces. Zero CAPTCHA solving, session forgery, or authenticated crawling is employed.

| # | Source Name | Endpoint / Ingestion Method | Method Type | Auth | Active Posts | Unique Companies | Compliance Assessment |
|---|-------------|-----------------------------|-------------|------|:------------:|:----------------:|-----------------------|
| 1 | **Workday CXS API** (`adapters/workday.py`) | `POST https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{portal}/jobs` | Official Career Site JSON Endpoint | None | **128** (54.0%) | 17 | **Clean & Legal:** Public JSON search endpoint powering career portals of GSK, Micron, HPE, Deutsche Bank, Walmart, AMD. |
| 2 | **GitHub Trackers + ATS Hydration** (`adapters/github_feeds.py` + `verifier.py`) | Community curated fresher trackers (`SimplifyJobs/New-Grad-Positions`, etc.) + live ATS API hydration | Raw JSON/MD + HTTP GET | None | **56** (23.6%) | 38 | **Clean & Legal:** Community feeds used solely for discovery; complete job specifications are hydrated directly from official ATS APIs. |
| 3 | **Greenhouse Job Board API** (`adapters/greenhouse.py`) | `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | Official Documented Public JSON API | None | **29** (12.2%) | 12 | **Clean & Legal:** Documented public career API for Greenhouse customers (Rubrik, Stripe, Figma, Databricks, InMobi). |
| 4 | **Lever Postings API** (`adapters/lever.py`) | `GET https://api.lever.co/v0/postings/{slug}?mode=json` | Official Documented Public Postings API | None | **16** (6.8%) | 10 | **Clean & Legal:** Official public posting feed for Lever boards (CRED, Meesho, Hevo Data, Porter, Pocket FM). |
| 5 | **SmartRecruiters API** (`adapters/smartrecruiters.py`) | `GET https://api.smartrecruiters.com/v1/companies/{id}/postings` | Official Documented Public Posting API | None | **6** (2.5%) | 6 | **Clean & Legal:** Official public API for SmartRecruiters portals (Swiggy, PhonePe, Bosch, Visa). |
| 6 | **Ashby Job Board API** (`adapters/ashby.py`) | `GET https://api.ashbyhq.com/posting-api/job-board/{board}` | Official Documented Public API | None | **1** (0.4%) | 1 | **Clean & Legal:** Documented public API for Ashby boards (Sarvam AI, Atlan, Plane, SigNoz). |
| 7 | **Remotive API** (`adapters/remotive.py`) | `GET https://remotive.com/api/remote-jobs?limit=100` | Official Public Syndication API | None | **1** (0.4%) | 1 | **Clean & Legal:** Public syndication feed. Preserves direct apply URLs and attribution. |
| 8 | **Jobicy API** (`adapters/jobicy.py`) | `GET https://jobicy.com/api/v2/remote-jobs?count=50&geo=apac` | Official Public API | None | **0** (0.0%) | 0 | **Clean & Legal:** Syndication API. Currently 0 India fresher matches. |

**Total Ingestion Footprint:** **237 active postings** across **87 unique companies**. 100% of application links direct candidates to the employer's official recruitment portal.

---

## 3. LLM Configuration, System Prompts & Schema

### Runtime Specifications
- **Primary Model:** `gemini-3.5-flash-lite` (via Gemini REST API `/v1beta/models/gemini-3.5-flash-lite:generateContent`).
- **Fallback Hierarchy:** `gemini-3.5-flash-lite` $\rightarrow$ `gemini-2.5-flash-lite` $\rightarrow$ `gemini-2.5-flash` $\rightarrow$ Heuristic regex word-boundary fallback.
- **Parameters:** `temperature=0.1`, `maxOutputTokens=4096`, `responseMimeType="application/json"`.
- **Reasoning Tokens:** 0 thinking tokens (`thoughtsTokenCount=0`).
- **Batching:** 8 postings per API request.
- **Context Handling:** Up to 6,000 characters per job description via `extract_relevant_snippet()`, capturing both introductory scope and explicit qualification blocks.

### Production System Prompt (`backend/app/tagger.py`)
```text
You are an expert technical recruiter analyzing job postings for college students and freshers in India.
Classify each post according to our strict taxonomy and extract EVERY real qualification signal directly from the job description.

Roles Taxonomy (MUST be one of these exact values):
- SDE: Software engineering, backend, frontend, fullstack, mobile, DevOps, cloud, QA/SDET, application/cloud security.
- Data/ML: Data science, data analytics, ML/AI engineer, BI analyst, data engineering, quantitative research.
- Hardware: Hardware engineering, silicon, VLSI, RTL, FPGA, ASIC, PCB, motherboard, embedded electronics, firmware, power electronics, semiconductor, RF/circuit design, board bring-up. NEVER put Hardware/VLSI/Silicon/PCB/Motherboard/Embedded Electronics roles into SDE!
- Design: UI/UX, product design, graphic design, visual design.
- Marketing: Growth, digital marketing, SEO, content, social media, performance marketing.
- Sales: Business development (BDR/SDR), inside sales, account executive.
- Ops: Business operations, customer support, supply chain, logistics, program/product management.
- Finance: Accounting, audit, financial analysis, investment, tax.
- HR: Recruiting, talent acquisition, human resources, people ops.
- Other: Any role that does not fit the above categories.

City Canonicalization:
- Canonical Indian cities: Bangalore, Mumbai, Pune, Hyderabad, Gurugram, Delhi, Noida, Chennai, Kolkata, Ahmedabad, Jaipur, Kochi, Coimbatore.
- If remote within India or worldwide, return "Remote".
- If the job is located in India but specific city is not a single metro (e.g. "India, Multiple Locations", "India", or unlisted Indian city), return "India (Multiple/Other)" or "Remote" or the dominant Indian city mentioned.
- If the role is definitively outside India or foreign-only (e.g., US-only, UK-only), return "Unknown".

Fresher & Experience Rules (STRICT — ZERO COMPROMISE):
- is_fresher_friendly: Boolean. Set TRUE ONLY IF the opening genuinely welcomes freshers, interns, apprentices, new college graduates, or candidates with 0-1 years of industry experience.
- Set is_fresher_friendly: FALSE if the job description requires 2+ years of experience — watch carefully for BOTH digits (2+ years, 2-5 years, 3-6 yrs, 4+ yrs) AND spelled-out words ("two or more years", "at least three years", "five or more years", "minimum of two years").
- min_exp: Integer minimum years of full-time industry experience required by the JD (e.g. 0 for intern/fresher/new grad, 2 for "2-5 years", 5 for "five or more years").
```

---

## 4. Cost Analysis per 1,000 Posts & Monthly Run Cost

### Telemetry from Database Logs (`llm_cost_logs`)
- Total posts tagged in production runs: **298 posts**
- Total recorded input tokens: **533,333**
- Total recorded output tokens: **36,063**
- Empirical averages: **1,789.7 input tokens / post** | **121.0 output tokens / post**

### Official Pricing Reference (Verified Nov 20, 2026)
Source: Google AI Studio (`ai.google.dev/pricing`) & Vertex AI (`cloud.google.com/vertex-ai/generative-ai/pricing`):
- `gemini-3.5-flash-lite`: **$0.30 per 1M input tokens** | **$2.50 per 1M output tokens**

### Arithmetic: Cost per 1,000 Posts

#### Baseline Implementation (With Duplicate Description Key)
$$\text{Input Cost} = 1,000 \times 1,789.7 \times \frac{\$0.30}{1,000,000} = \$0.5369$$
$$\text{Output Cost} = 1,000 \times 121.0 \times \frac{\$2.50}{1,000,000} = \$0.3025$$
$$\mathbf{\text{Baseline Cost per 1,000 Posts}} = \$0.5369 + \$0.3025 = \mathbf{\$0.8394 \approx \$0.84}$$

#### Optimized Pipeline (Current Codebase)
Removing the redundant `description_snippet` payload field decreased input tokens by 43.2% (down to ~1,016.8 input tokens/post):
$$\text{Optimized Input Cost} = 1,000 \times 1,016.8 \times \frac{\$0.30}{1,000,000} = \$0.3050$$
$$\text{Output Cost} = 1,000 \times 121.0 \times \frac{\$2.50}{1,000,000} = \$0.3025$$
$$\mathbf{\text{Optimized Cost per 1,000 Posts}} = \$0.3050 + \$0.3025 = \mathbf{\$0.6075 \approx \$0.61} \quad (-27.6\%)$$

#### Comparative Cost Matrix
| Configuration | Input Tokens / 1k | Output Tokens / 1k | Cost / 1,000 Posts |
|---|:---:|:---:|:---:|
| **Baseline (6k chars, duplicate key)** | 1,789,700 | 121,000 | **$0.84** |
| **Optimized (6k chars, deduplicated)** | 1,016,800 | 121,000 | **$0.61** |
| **Trimmed (3k chars, deduplicated)** | 892,500 | 121,000 | **$0.57** |
| **`gemini-2.5-flash-lite` ($0.10/$0.40 per 1M)** | 892,500 | 121,000 | **$0.14** |
| **`gemini-3.5-flash` ($1.50/$7.50 per 1M)** | 1,016,800 | 121,000 | **$2.43** |

### Monthly GCP Operating Cost (Current Production Cadence)
| Component | Configuration | Monthly Cost |
|---|---|:---:|
| **Cloud SQL (PostgreSQL 15)** | `db-f1-micro` (0.6 GB RAM, 10 GB SSD, Mumbai) | ~$10.20 |
| **Cloud Run Service (`beep-job-hub`)** | 1 vCPU, 512 MB RAM (within free tier 2M req/mo) | $0.00 |
| **Cloud Run Job (`beep-refresh-job`)** | 360 runs/mo $\times$ 6.8 min $\times$ 1 vCPU / 512 MB | $0.00 |
| **Cloud Scheduler (`beep-refresh-2hr`)** | 1 cron job (`0 */2 * * *` IST) | $0.00 |
| **Gemini 3.5 Flash-Lite LLM** | ~1,000 newly discovered postings / month | ~$0.61 |
| **Total Monthly Operating Cost** | | **~$10.81 / month** |

---

## 5. Hand-Checked Accuracy Measurement (50 Random Posts)

A uniform random sample of 50 active postings was drawn across the active database using random seed `4242`. All 50 rows were independently evaluated against the full job specifications.

### Hand-Checked Evaluation Results
- **Dataset Sample File:** [`submission/accuracy_sample_50.csv`](https://github.com/Aditya290605/Beep-Job-Search/blob/main/submission/accuracy_sample_50.csv)
- **Role Classification Accuracy:** **49 / 50 = 98.0%**  
  *Wilson 95% Confidence Interval: [89.5%, 99.6%]*
- **City Canonicalization Accuracy:** **49 / 50 = 98.0%**  
  *Wilson 95% Confidence Interval: [89.5%, 99.6%]*
- **Exact Match on Both Dimensions:** **48 / 50 = 96.0%**  
  *Wilson 95% Confidence Interval: [86.5%, 98.9%]*

### Evaluation Breakdown by Source
- **Workday** ($n=21$): Role 21/21 (100.0%) | City 20/21 (95.2%)
- **GitHub Feeds** ($n=14$): Role 13/14 (92.9%) | City 14/14 (100.0%)
- **Lever** ($n=7$): Role 7/7 (100.0%) | City 7/7 (100.0%)
- **Greenhouse** ($n=4$): Role 4/4 (100.0%) | City 4/4 (100.0%)
- **SmartRecruiters** ($n=4$): Role 4/4 (100.0%) | City 4/4 (100.0%)

### Disagreement Analysis (2 Discrepancies Identified)
1. **City Mismatch (`ID: 145`, Deutsche Bank CFO Intern):**
   - *Raw Location:* `(do not use) Mumbai Nirlon Knowledge Pk B1`
   - *LLM Prediction:* `Mumbai` | *Hand-Check Label:* `Pune`
   - *Root Cause:* The internal requisition title included outdated placeholder text; the model parsed the literal mention of Mumbai Nirlon Park.
2. **Role Mismatch (`ID: 168`, Kielo Research Survey Programmer - Contractor):**
   - *LLM Prediction:* `Data/ML` | *Hand-Check Label:* `Other`
   - *Root Cause:* The posting contained data processing terminology for survey scripts; the model misclassified the custom survey tool setup as Data/ML rather than Other.

---

## 6. Production Incidents & Engineering Resolutions

### Incident 1: Senior Roles Leaking into Fresher Index (Stub JDs & Spelled-Out Years)
- **Issue:** A Point72 "Associate Identity Security Engineer" posting appeared on the live site labeled `0–1 YOE Fresher Friendly`, despite the employer requiring 5+ years of experience.
- **Root Cause:** 
  1. The upstream community feed provided only a single-line summary stub rather than the complete job description.
  2. The employer's actual Greenhouse posting specified experience using spelled-out words: *"Five or more years of industry experience"*, which bypassed numeric regex patterns (`5+`).
- **Resolution:**
  1. Built `backend/app/verifier.py` to hydrate complete official job descriptions directly from ATS APIs prior to LLM enrichment.
  2. Expanded experience regex patterns to parse spelled-out numbers (`two` through `ten` years).
  3. Increased context window to 6,000 characters and guaranteed inclusion of the qualifications section.

### Incident 2: PostgreSQL `TIMESTAMPTZ` Transaction Crash on Live Cloud Run
- **Issue:** Production pipeline runs crashed on Cloud Run with: `column "posted_date" is of type timestamp with time zone but expression is of type integer`.
- **Root Cause:** Upstream community feeds provided mixed date formats, including raw Unix epoch integers (`1775092170`). SQLite accepted epoch integers, but PostgreSQL strictly rejected non-string timestamps during `INSERT INTO jobs`, aborting the database transaction.
- **Resolution:**
  1. Implemented `_normalize_ts()` in `backend/app/db.py` to convert all integer timestamps, millisecond epochs, and ISO variants into canonical ISO-8601 UTC strings before executing SQL queries.
  2. Added missing database indexes on `expires_at`, `last_seen_at`, and `apply_url`.

### Incident 3: Disciplinary Collisions in Deduplication (PhD Intern False Merge)
- **Issue:** A Google "Software Engineering PhD Intern" and Google "Silicon Engineering PhD Intern" in Bangalore were wrongly deduplicated into a single listing.
- **Root Cause:** Token sort similarity between the two titles reached ~82% (above the 80% threshold) because company name, city, and degree tokens ("PhD Intern") dominated the character set.
- **Resolution:**
  1. Implemented `CONFLICTING_TRACK_GROUPS` guardrails in `backend/app/dedupe.py`, enforcing mutually exclusive discipline barriers (`software` vs `silicon/hardware`, `backend` vs `frontend`, `data` vs `design`).
  2. Added cohort graduation year matching: postings targeting conflicting graduating years (e.g. 2024 vs 2027) are barred from merging.

---

## 7. Submission Verification Checklist

- [x] **Live Web Application:** `https://beep-job-hub-524515781472.asia-south1.run.app/` (237 active roles, p95 < 200ms)
- [x] **GitHub Repository:** `https://github.com/Aditya290605/Beep-Job-Search` (29 passing tests, CI/CD automated)
- [x] **5-Minute Loom Walkthrough Script:** `submission/LOOM_SCRIPT_5MIN.md`
- [x] **Hand-Checked 50-Post Dataset:** `submission/accuracy_sample_50.csv` (98% role accuracy, 98% city accuracy)
- [x] **Accuracy Evaluator Script:** `submission/eval_accuracy.py`
- [x] **Cost & Token Telemetry Report:** `submission/COST_REPORT.md` ($0.61 / 1,000 posts)
- [x] **Data Sources Legality Document:** `submission/SOURCES.md`
- [x] **Verbatim Prompts Documentation:** `submission/PROMPTS.md` and `submission/prompts.csv`
