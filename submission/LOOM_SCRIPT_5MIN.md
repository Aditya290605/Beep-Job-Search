# 5-Minute Loom Video Walkthrough Script

> **Target Length:** 4:30 – 4:55 (strictly under 5:00)  
> **Live URL:** `https://beep-job-hub-524515781472.asia-south1.run.app/`  
> **Repo:** `https://github.com/Aditya290605/Beep-Job-Search`

---

### [0:00 – 0:45] Live Demo & Problem Statement (Show Live App)
- Open `https://beep-job-hub-524515781472.asia-south1.run.app/`, let the 1.35s Beep intro finish, click **Continue**.
- State the problem: Indian freshers (0–1 YOE) waste hours on scraped aggregators full of expired postings, duplicates, and disguised 5+ year "entry-level" roles.
- Point out live numbers on screen: **237 active verified fresher & intern roles** across **87 companies**, all linking directly to official career portals (15/15 random links verified open via live ATS APIs).
- Quick live interactions:
  - Filter by **Categories -> Hardware** (22 VLSI/PCB/SoC roles cleanly separated from SDE) and **SDE** (50 roles).
  - Filter by **Location -> Bangalore** (95 roles), click a job card, show **Required Skills**, **Apply Before** expiry date, and click **Apply Now** (opens official portal in new tab).
  - Bookmark 1 role and click **Pipeline Status** to show live telemetry.

---

### [0:45 – 1:55] Real Architecture Walkthrough (Show System Diagram / Code)
- **Single-Container GCP Deployment (`asia-south1` Mumbai):**
  - **Web App:** Cloud Run service (`beep-job-hub`) running FastAPI + vanilla HTML/CSS/JS (zero npm bloat).
  - **Database:** Cloud SQL PostgreSQL 15 (`beep-jobs-db`, DB `jobs_db`) with GIN full-text search index + `jobs`, `job_sources`, `pipeline_runs`, `llm_cost_logs`.
  - **Automated Refresh:** Cloud Scheduler (`0 */2 * * *` IST) triggers Cloud Run Job (`beep-refresh-job`) every 2 hours. Show `/api/status`: **7 consecutive unattended runs** succeeded (`22:30` to `04:30 UTC`), taking ~6.5 min each and only calling Gemini on net-new posts (`0` new -> `0` LLM calls!).
- **Sources & Legality:**
  - Zero scraping of LinkedIn/Naukri/Indeed/Internshala.
  - 8 zero-key adapters: Workday CXS (128 live), GitHub community trackers with live ATS JD hydration (56), Greenhouse API (29), Lever API (16), SmartRecruiters API (6), Ashby (1), Remotive (1), Jobicy (0).
- **Deduplication (Plain Code, $0 LLM Cost):**
  - Level 1: exact `normalized_key` (`company:title:city`) + exact `apply_url`.
  - Level 2: `RapidFuzz` `token_sort_ratio` (`company >= 85%`, `title >= 80%`) with hard guardrails (same city, same job_type, same roman/numeric seniority level). All duplicate URLs linked in `job_sources`.

---

### [1:55 – 3:15] What Broke & How I Fixed It (Pick 3 Real Production Bugs)
1. **The "Point72 5+ Years Fresher" Bug (Spelled-Out Experience & Stub JDs):**
   - *Broke:* A Point72 Identity Security Engineer role appeared as `0–1 yrs` because the GitHub tracker only gave a 1-line stub, and the actual Greenhouse JD wrote `"Five or more years"` in words instead of digits!
   - *Fixed:* Built `backend/app/verifier.py` to hydrate full JDs directly from official ATS APIs + JSON-LD before tagging, expanded regex to catch spelled-out years (`two`–`ten`), increased LLM input window to 6,000 chars preserving the requirements section, and added an explicit `Hardware` category so VLSI/PCB roles stopped leaking into `SDE`.
2. **PostgreSQL `TIMESTAMPTZ` Crash on Live Cloud Run (`Run #2` & `Run #4`):**
   - *Broke:* Worked fine on SQLite locally, but live Cloud Run Job crashed on Cloud SQL Postgres with `column "posted_date" is of type timestamp with time zone but expression is of type integer` because 6 SimplifyJobs records used Unix epoch ints (`1775092170`).
   - *Fixed:* Added `_normalize_ts()` in `db.py` to convert epoch ints/ms to ISO-8601 UTC strings before insert; Runs #6–#12 immediately went 7/7 green.
3. **Geo-Collisions & Cloud SQL Password Bash Escaping:**
   - *Broke:* `"Indianapolis, IN"` matched substring `"india"`, `"Remote - USA"` leaked through bare `"remote"`, and `!` in our Cloud SQL password broke shell escaping.
   - *Fixed:* Strict `\bindia\b` word boundary + foreign exclusion regex + `urllib.parse.quote_plus()` URL-encoding in `config.py`.

---

### [3:15 – 4:25] Evaluation Accuracy & Cost Honesty
- **LLM Tagging (`gemini-3.5-flash-lite`, `temperature=0.1`, strict JSON schema, `0` thinking tokens):**
  - Evaluated on a random 50-post stratified sample (`seed=20261120`) — state YOUR final hand-checked numbers from `eval_accuracy.py` here! *(Example: "Role accuracy X% [95% CI ...], City accuracy Y% [95% CI ...], main disagreements were banking ops vs finance and pre-sales consulting.")*
- **Cost per 1,000 Posts (Honest Numbers):**
  - Logged 298 posts = `533,333` input tokens (`1,790/post`), `36,063` output tokens (`121/post`).
  - Be transparent about what our audit caught:
    - True `gemini-3.5-flash-lite` price (`$0.30/$2.50` per 1M) puts current cost at **`$0.84 / 1,000 posts`**.
    - Removing a redundant `description_snippet` key cuts input tokens 43% to **`$0.61 / 1,000`** (and **`$0.57 / 1,000`** at 3,000 chars, or **`$0.14 / 1,000`** on `gemini-2.5-flash-lite`).
  - Total monthly GCP run cost: **~$11/month** (~$10.20 Cloud SQL `db-f1-micro` + <$1 LLM; Cloud Run & Scheduler stay inside GCP free tier).

---

### [4:25 – 4:55] What I Would Improve Next (Shows Engineering Maturity)
- Mention 3 concrete next upgrades you're ready to live-code on the call:
  1. Remove duplicate `description_snippet` key + update `config.py` pricing constant (`5 min`).
  2. Fix `"intern"` substring bug in `extract_job_type` (`\bintern(?:ship)?\b`) and tighten `Associate 2` senior guard (`10 min`).
  3. Add domain-aware negative guard in dedupe so Google `Software Engineering PhD Intern` never merges with `Silicon Engineering PhD Intern`, plus redact API key from error logs.
- Thank the team and wrap up!
