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
