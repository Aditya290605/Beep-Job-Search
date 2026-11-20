# Tools, Stack & AI Workflow Used

## 1. Application Stack
- **Backend API:** Python 3.11, FastAPI (`>=0.110.0`), Uvicorn (`>=0.28.0`), Pydantic (`>=2.6.0`)
- **HTTP / Ingestion:** Python Standard Library (`urllib.request`, `concurrent.futures.ThreadPoolExecutor`, `html`, `re`, `json`) — zero external scraping frameworks
- **Deduplication:** Plain Python normalization + `rapidfuzz` (`fuzz.token_sort_ratio`, with stdlib `difflib` fallback)
- **Database:** PostgreSQL 15 on Google Cloud SQL (`psycopg2-binary`), with SQLite3 compatibility mode for local dev and 27 unit tests
- **Frontend:** Vanilla HTML5, CSS3, ES6 JavaScript (zero npm/bundler dependencies, URL-synced filter state, `localStorage` saved bookmarks, Web Animations API intro screen)
- **Containerization:** Single-container `Dockerfile` (`python:3.11-slim`) serving both FastAPI API and static frontend, reused as the Cloud Run Job image

## 2. Cloud Infrastructure (Google Cloud Platform — `asia-south1`, Mumbai)
- **Cloud Run Service (`beep-job-hub`):** Hosts FastAPI + static UI (`https://beep-job-hub-524515781472.asia-south1.run.app/`)
- **Cloud Run Job (`beep-refresh-job`):** Executes `python -m app.pipeline` unattended
- **Cloud Scheduler (`beep-refresh-2hr`):** Cron `0 */2 * * *` (`Asia/Kolkata`) triggering `beep-refresh-job` every 2 hours
- **Cloud SQL (`beep-jobs-db`):** PostgreSQL 15 (`db-f1-micro`), database `jobs_db`, connected via Unix socket `/cloudsql/...`
- **Artifact Registry & Cloud Build:** Container image build and storage

## 3. AI / LLM Models Used
- **In-App Classification Model:** Google Gemini `gemini-3.5-flash-lite` via Gemini REST API (`generativelanguage.googleapis.com/v1beta`), with structured JSON schema output (`temperature=0.1`, `thoughtsTokenCount=0`). Fallback chain: `gemini-2.5-flash-lite` -> `gemini-2.5-flash` -> deterministic regex fallback.
- **Coding & Audit Assistance:** Antigravity IDE agent (Google DeepMind) used for iterative architecture, adapter development, debugging Postgres/GCP issues, unit tests, and this read-only pre-submission audit.

## 4. Testing & Evaluation Tooling
- **Unit Tests:** Python `unittest` (`27` tests in `backend/tests/test_{adapters,api,dedupe,tagger}.py`, 0.03s runtime)
- **Accuracy Evaluation:** `submission/accuracy_sample_50.csv` (seed `20261120`, 50 posts stratified across all 7 active sources) + `submission/eval_accuracy.py` (Wilson 95% CI, per-source accuracy, confusion list, confidence calibration)
