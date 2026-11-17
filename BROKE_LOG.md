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
