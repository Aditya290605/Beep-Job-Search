# BROKE_LOG.md - What Broke & How We Fixed It

> Running log of bugs, edge cases, integration failures, and their fixes throughout development.
> Needed for the 5-minute Loom video architecture & debugging walkthrough.

---

### Entry 1: Sandbox Network Isolation vs. External Feasibility Testing
- **Phase:** Phase 1 (Source Research & Feasibility)
- **Symptom:** Running API calls directly in the local sandbox failed with `urllib.error.URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>` because the local agent sandbox disables outbound networking.
- **Root Cause:** By design, the local environment enforces zero network egress to protect against unauthorized data transmission. All live API endpoints (Adzuna, Greenhouse, Lever, Ashby) must be validated via Cloud Shell or authorized runners.
- **Fix:** Designed `scripts/feasibility.py` using Python standard library (`urllib.request`, `json`, `re`) with zero 3rd-party dependencies so it runs instantly inside GCP Cloud Shell in one paste, and added an offline mock test mode (`--mock`) so the pipeline parsing logic can still be tested locally in the development sandbox.

---

### Entry 2: Adzuna Free Tier Limit (25 calls/day) & Pivot to Zero-Key Sources
- **Phase:** Phase 1 / Phase 2 (Data Source Evaluation)
- **Symptom:** Adzuna's free developer tier was found to provide only 25 API requests per day. Running our 2-hour scheduled refresh with multiple pagination queries would exhaust the quota within hours.
- **Root Cause:** Adzuna recently restricted free evaluation accounts to a strict 25 calls/day ceiling.
- **Architectural Decision:** **Completely removed Adzuna.** Why depend on a brittle 25-call quota and commercial trial licensing when we have superior, keyless sources?
- **Fix:** Switched entirely to 100% keyless, public legal sources with zero daily caps:
  1. **Direct ATS APIs:** Greenhouse, Lever, Ashby, and SmartRecruiters (querying 60+ top tech companies with India engineering hubs).
  2. **Free Public APIs:** Jobicy Remote Jobs API and Remotive API (filtering for India/APAC and fresher/intern tags).
  3. **Zero Secrets for Ingestion:** The ingestion pipeline now needs zero API keys or signups to collect jobs.

---

### Entry 3: Schema DDL Incompatibilities in Offline SQLite Test Runner
- **Phase:** Phase 2 (Database Layer & Unit Tests)
- **Symptom:** Running offline unit tests against `schema.sql` failed with `sqlite3.OperationalError: near "(": syntax error` and `sqlite3.OperationalError: no such table: jobs`.
- **Root Cause:** 
  1. `schema.sql` utilizes Postgres-specific constructs (`DEFAULT NOW()` instead of SQLite's `DEFAULT CURRENT_TIMESTAMP`, and Postgres multi-line GIN index syntax `USING gin(to_tsvector(...))`).
  2. Standard SQLite in-memory `:memory:` connections are ephemeral and destroy their tables when closed between query helper calls.
- **Fix:** Updated `db.py`'s SQLite translation layer to dynamically replace `NOW()` with `CURRENT_TIMESTAMP`, strip Postgres GIN index statements cleanly on SQLite, and maintain a persistent connection handle for in-memory test databases. All 8 test suites now run and pass in 0.001s with zero external dependencies.

---

### Entry 4: Location Normalization Precedence Bug
- **Phase:** Phase 2 (Adapter Utilities)
- **Symptom:** Location strings like `"Remote (India)"` were classified as `"India (Multiple/Other)"` instead of canonical `"Remote"`.
- **Root Cause:** In `is_india_location()`, the check for the substring `"india"` ran before evaluating the remote-eligibility condition.
- **Fix:** Reordered matching logic so that explicit cities match first (e.g., "Pune / Remote" -> "Pune"), followed by Remote-India detection (e.g. "Remote (India)" -> "Remote"), and then broad country fallback.

---

### Entry 5: False Merge Vulnerabilities in Fuzzy Deduplication
- **Phase:** Phase 3 (Deduplication Engine)
- **Symptom:** Pure Levenshtein/string distance matching risked falsely merging distinct roles (e.g. `"Software Engineer I"` vs `"Software Engineer II"`, or `"Frontend Engineer"` vs `"Frontend Intern"`), while missing valid duplicates with corporate noise (e.g. `"Razorpay Software Private Limited"` vs `"Razorpay"`).
- **Root Cause:** Generic fuzzy string algorithms do not understand employment domain semantics (internship vs full-time, roman numerals, or legal corporate entity suffixes).
- **Fix:** Implemented domain-aware preprocessing:
  1. **Corporate Noise Stripping:** Removed legal suffixes (`Pvt Ltd`, `Private Limited`, `Technologies`, `Inc`).
  2. **Tech Abbreviation Expansion:** Expanded `SDE` -> `software development engineer`, `SWE` -> `software engineer`, etc.
  3. **Hard Guardrails:** Enforced that postings with different cities, different job types (`job` vs `internship`), or different numeral levels (`I` vs `II`) are strictly excluded from merging before any similarity score is evaluated.

---

### Entry 6: Substring Keyword Collision in Heuristic Role Classification
- **Phase:** Phase 4 (LLM Tagger & Offline Test Runner)
- **Symptom:** The role classification fallback misclassified `"Talent Acquisition Trainee"` as `"Data/ML"` instead of `"HR"`, and `"Growth Marketing Associate"` as `"Data/ML"` instead of `"Marketing"`.
- **Root Cause:**
  1. Two-letter acronyms like `"ai"` and `"ml"` were matched as substrings inside ordinary English words (`"ai"` matched inside `"trainee"` and `"acquisition"`, `"ml"` matched inside `"html"`).
  2. The word `"analytics"` in the description matched the keyword `"analyst"` for Data/ML before marketing title signals were checked.
- **Fix:** 
  1. Refactored keyword matching to use strict regex word boundaries (`\b(ai|ml|data)\b`).
  2. Enforced that job title signals take strict precedence over description snippet keywords.
  3. Extended design root matches (`design\w*`) to cleanly catch `"Designer"` and `"Designing"`.

---
