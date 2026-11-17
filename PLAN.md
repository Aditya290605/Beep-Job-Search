# PLAN.md: phase-wise plan (awaiting approval)

Deadline Fri 20 Nov 23:59. Target submit Thu 19 Nov night. Today is Tue 17 Nov, evening.
**I never start a phase until you say so.**

## Environment facts that shape the plan
- You run nothing on your Mac. Everything outside this IDE is done in the GCP web console and **Cloud Shell**.
- My sandbox has Python 3.15 and Node 24, so I can run unit tests and the frontend build here. It has **no network**, so anything that calls a real API (feasibility, seeding, Vertex) runs in Cloud Shell or in a command you approve.
- Deploy path: GitHub repo, then Cloud Build, then Cloud Run (Dockerfile), all from the console.
- LLM: Vertex AI Gemini Flash-Lite through the Cloud Run service account (no key). I verify the current model name and price in the official docs in Phase 4. The desk figure is about \$0.10 in and \$0.40 out per 1M tokens.
- Your four answered questions land at these points:
  - **Cloud Shell OK?** Needed in Phases 1, 7 and 8. I give you copy-paste commands.
  - **GitHub account / public?** Needed at the end of Phase 2. Please decide by then.
  - **Sandbox version check:** done (above).
  - **Cost alternatives after credits:** covered in Phase 7 (pause Cloud SQL, export and delete, or a cheaper Postgres) and written into the README.

## Phases

| Ph | Goal | Time |
|---|---|---|
| 0 | **You:** GCP setup in the console | 1-1.5 h |
| 1 | Source approval and feasibility count | 1.5 h |
| 2 | Repo scaffold, DB schema, adapters | 3 h |
| 3 | Dedupe | 1.5 h |
| 4 | LLM tagging and cost logging | 2 h |
| 5 | API | 2 h |
| 6 | Frontend | 4 h |
| 7 | Deploy, scheduler, alerts | 2.5 h |
| 8 | Evaluation and cost reports | 1.5 h |
| 9 | Polish, docs, Loom prep | 2 h |

Total is about 21 h. It fits in the 3 days only if Phase 0 starts tonight, because Cloud SQL and billing setup can take a while.

### Phase 0: GCP setup (you, in the console; I give a click-by-click guide)
- **Goal:** project ready, APIs on, budget alert set.
- **Steps:** create the project, link billing, enable APIs (Cloud Run, Cloud SQL Admin, Cloud Build, Secret Manager, Scheduler, Vertex AI, Artifact Registry), set a budget alert (\$10, \$50) to your email, create the Cloud SQL Postgres instance in asia-south1 (smallest shared-core), and create a service account with least privilege.
- **Files:** none.
- **Test:** the console shows the instance "Runnable". Cloud Shell opens.
- **Done when:** you give me the project ID and instance name. **Risk:** billing verification delays. **Adzuna sign-up** also happens here (you get `app_id` and `app_key`, stored in Secret Manager).

### Phase 1: Source approval and feasibility
- **Goal:** prove 200+ unique India fresher/intern posts exist from legal sources.
- **Steps:** you approve SOURCES.md. I write one throwaway script (`scripts/feasibility.py`) that calls each source, filters by India and fresher keywords in plain code, and counts unique posts by normalised key. You run it in Cloud Shell. I record the results back in SOURCES.md.
- **Files:** `scripts/feasibility.py`, SOURCES.md update, BROKE_LOG.md started.
- **Test:** the script prints a count per source and a total.
- **Done when:** the total is 250 or more, which leaves headroom for dedupe and dropping unknown cities. **Risk:** the Adzuna cap, and dead company tokens. The fix is to add more tokens or sources.

### Phase 2: Scaffold, schema, adapters
- **Goal:** the pipeline fetches and normalises into Postgres.
- **Files:** `adapters/{adzuna,greenhouse,lever,ashby,smartrecruiters}.py`, `schema.sql`, `db.py`, `models.py` (common schema), `pipeline.py`, `config.py`, `.env.example`, `requirements.txt`, `.gitignore`, `README.md`. Adapter tests use saved sample JSON.
- **How it works:** each adapter is about 40 lines, returns a list of normalised jobs, and has a timeout, retries and its own try/except. Dedupe is a unique key in Postgres.
- **Test:** unit tests in my sandbox. A real fetch runs in Cloud Shell.
- **Done when:** a rerun creates 0 new rows. **GitHub:** push the repo here, and I ask you for the account and visibility.
- **Risk:** source format changes. The fix is that each source fails alone.

### Phase 3: Dedupe
- **Goal:** one record per real job.
- **Files:** `dedupe.py`, `tests/test_dedupe.py`.
- **How:** normalise company + title + city, exact key (DB-unique), then rapidfuzz for near-matches across sources, with thresholds in one config block. All source URLs are kept in a `job_sources` table.
- **Test:** unit tests with real duplicate examples. **Done when:** I show you real duplicate pairs and misses before any V2.
- **Risk:** false merges ("Software Engineer" vs "Software Engineer II").

### Phase 4: LLM tagging
- **Goal:** role, city, fresher flag, experience, skills, confidence for new posts only.
- **Files:** `tagger.py`, `prompts.py` (also logged in PROMPTS.md), `llm_calls` table.
- **How:** batches of 10-20, JSON schema output, thinking off. Tokens and cost are logged per call. Posts with city "Unknown" are dropped. Optional retry of low-confidence posts on a larger Flash model.
- **Test:** unit tests with a fake LLM. A real call runs in Cloud Shell. **Risk:** invalid JSON, so the fallback is a retry and then "Other" with low confidence.

### Phase 5: API
- **Goal:** `/api/jobs`, `/api/filters`, `/api/status`, `/healthz`.
- **Files:** `api/main.py`, `api/queries.py`. Server-side pagination, Postgres full-text search plus trigram, parameterised SQL, rate limiting, CORS, and indexes.
- **Test:** pytest against a test Postgres, or fall back to SQLite-like fakes if Postgres is not available in my sandbox (I will tell you which). **Done when:** p95 is under about 500 ms on 1k rows.

### Phase 6: Frontend
- **Goal:** the polished UI from your brief.
- **Stack:** React + Vite + Tailwind. I add a small component set (Radix primitives for the modal and selects, for accessibility) with a colourful, student-friendly look. This beats hand-rolling dialogs.
- **Files:** `web/src/...` (cards, filters, pagination, modal, status page), with URL-synced state.
- **Test:** build in my sandbox, plus a browser check. **Done when:** no dead buttons, and the loading, empty and error states work.

### Phase 7: Deploy, scheduler, alerts
- **Goal:** live URL and automatic refresh every 2 hours.
- **Files:** `Dockerfile`, `deploy.md` (console steps and gcloud commands).
- **You do:** connect GitHub to Cloud Build, create the Cloud Run service and the refresh job, attach Cloud SQL, add secrets, create the Scheduler (`0 */2 * * *`, Asia/Kolkata), and create a log-based alert to your email. Then you run the seed in Cloud Shell.
- **Cold start trade-off (min instances 0):** the first visit after idle takes a few seconds. It costs nothing when idle. Min instance 1 removes that delay but costs about \$10-15 a month.
- **Cost after credits:** Cloud SQL is the main cost, about \$10-15 a month. Cloud Run, Scheduler and Secret Manager are about \$0-1. Alternatives: (a) pause the instance (storage still charged), (b) export to CSV and delete it, (c) move to a free-tier Postgres. All go in README "Shutdown".
- **Done when:** the live URL shows 200+ posts and /status shows a scheduled run.

### Phase 8: Evaluation and cost reports
- **Files:** `scripts/eval_export.py` (random 50, spread across sources, held out from the tuning set), `scripts/eval_score.py` (accuracy, error examples, confusion list), `scripts/cost_report.py`, `scripts/export_csv.py`.
- **You do:** hand-check the 50 rows in a sheet (about 30-45 min).

### Phase 9: Polish and docs
- README with architecture diagram, BROKE_LOG.md, PROMPTS.md, the live-change cheat sheet, the 5-minute Loom outline, the submission doc, and a security and secrets check.

## What I need from you now
1. **Approve SOURCES.md**, or tell me to add or drop sources.
2. **Approve the plan**, then say "start Phase X". I suggest you start Phase 0 tonight while I do Phase 1.
3. A note: Adzuna's free tier is licensed for evaluation use. That is fine for this assessment, and I list it as a risk in the README.
