# Cost Report — LLM Tagging & Monthly GCP Run Cost (Evidence-Based)

> **Audit Date:** 2026-11-20  
> **Live Data Source:** `GET https://beep-job-hub-524515781472.asia-south1.run.app/api/metrics/cost` + live dry-run `usageMetadata` probe on `gemini-3.5-flash-lite`.

---

## 1. Where Tokens Are Logged (and What Was Wrong Before)

- **Database table:** `llm_cost_logs` (`backend/app/schema.sql:70-79`), written by `Database.log_llm_cost()` (`db.py:473-499`) on every batch inside `enrich_untagged_jobs()` (`tagger.py:524-531`), and served live at `GET /api/metrics/cost`.
- **Live Cloud SQL Totals (through Run #12, `2026-11-20T04:37Z`):**
  - **API calls:** `43`
  - **Posts tagged:** `298`
  - **Total input tokens:** `533,333` (**1,789.7 input tokens / post**)
  - **Total output tokens:** `36,063` (**121.0 output tokens / post**)
  - **Thinking tokens:** **0** — *Note: `tagger.py:402-404` does NOT log `thoughtsTokenCount`, so we verified directly via live REST API dry-run (`2026-11-20`) on `gemini-3.5-flash-lite`: `promptTokenCount=10008`, `candidatesTokenCount=946`, `totalTokenCount=10954` (`10008 + 946 = 10954`, zero thinking tokens).*
- **Two Critical Cost Bugs Found in Code:**
  1. **Outdated pricing constant (`backend/app/config.py:110`):** Hardcoded `gemini-3.5-flash-lite` at `$0.10 / 1M` input and `$0.40 / 1M` output (which is `gemini-2.5-flash-lite`'s price). Official Google pricing for `gemini-3.5-flash-lite` (checked `2026-11-20` on `ai.google.dev/gemini-api/docs/pricing` & `cloud.google.com/vertex-ai/generative-ai/pricing`) is **$0.30 / 1M input** and **$2.50 / 1M output** (Global Standard). Thus the app's `/api/metrics/cost` endpoint (`$0.0678` total / `$0.2274` per 1k) **under-reports true `gemini-3.5-flash-lite` cost by 3.7x**!
  2. **Duplicated description field (`backend/app/tagger.py:132-133`):** `build_tagging_payload()` sends **both** `"description": snippet` and `"description_snippet": snippet` (up to 6,000 chars each = 12,000 chars per job). Live Gemini API test on 8 jobs proved removing the duplicate key cuts prompt tokens by **43.2%** (`10,008` -> `5,686` tokens).

---

## 2. Official Google Gemini Pricing Used (Cited `2026-11-20`)

Sources: `https://ai.google.dev/gemini-api/docs/pricing` and `https://cloud.google.com/vertex-ai/generative-ai/pricing` (verified `2026-11-20`):

| Model | Input ($ / 1M tokens) | Output ($ / 1M tokens, incl. thinking) | Notes |
|-------|-----------------------|----------------------------------------|-------|
| `gemini-3.5-flash-lite` *(currently active)* | **$0.30** | **$2.50** | Global standard ($0.33/$2.75 non-global) |
| `gemini-2.5-flash-lite` | **$0.10** | **$0.40** | Cheapest Flash-Lite tier |
| `gemini-3.5-flash` *(bigger Flash)* | **$1.50** ($0.75 promo) | **$7.50** ($3.75 promo) | Standard tier / promotional rate |
| `gemini-2.5-flash` *(deprecated)* | **$0.30** | **$2.50** | Routes to `gemini-3.5-flash-lite` |

---

## 3. Cost per 1,000 Posts (Exact Arithmetic)

Baseline per-post averages from 298 live logged posts:
- **Current code (6,000 chars, duplicated key):** `1,789.7` input tokens/post, `121.0` output tokens/post, `0` thinking tokens/post.
- **Deduplicated 6,000 chars** (empirically `-43.2%` prompt tokens in live API test: `5,686 / 10,008 = 0.5681`): `~1,016.8` input tokens/post, `121.0` output tokens/post.
- **Trimmed 3,000 chars, deduplicated** (empirically `-50.1%` prompt tokens vs current: `4,991 / 10,008 = 0.4987`): `~892.5` input tokens/post, `121.0` output tokens/post.

| Scenario | Model | Input Tokens / 1k Posts | Output Tokens / 1k Posts | Arithmetic | Cost / 1,000 Posts |
|----------|-------|-------------------------|--------------------------|------------|--------------------|
| **App Logged (WRONG rate)** | `gemini-3.5-flash-lite` @ $0.10/$0.40 | 1,789,708 | 121,017 | `(1.7897 × $0.10) + (0.1210 × $0.40)` | **$0.2274** *(understated)* |
| **TRUE Current Live Code** | `gemini-3.5-flash-lite` @ $0.30/$2.50 | 1,789,708 | 121,017 | `(1.7897 × $0.30) + (0.1210 × $2.50)` | **$0.8395** |
| **Fix duplicate key (keep 6,000 chars)** | `gemini-3.5-flash-lite` @ $0.30/$2.50 | 1,016,800 | 121,017 | `(1.0168 × $0.30) + (0.1210 × $2.50)` | **$0.6076** (-27.6%) |
| **Trim to 3,000 chars (no dup key)** | `gemini-3.5-flash-lite` @ $0.30/$2.50 | 892,500 | 121,017 | `(0.8925 × $0.30) + (0.1210 × $2.50)` | **$0.5703** (-32.1%) |
| **Switch to `gemini-2.5-flash-lite` (3,000 chars)** | `gemini-2.5-flash-lite` @ $0.10/$0.40 | 892,500 | 121,017 | `(0.8925 × $0.10) + (0.1210 × $0.40)` | **$0.1377** (-83.6%) |
| **Bigger Flash (Current 6,000 dup)** | `gemini-3.5-flash` @ $1.50/$7.50 | 1,789,708 | 121,017 | `(1.7897 × $1.50) + (0.1210 × $7.50)` | **$3.5922** ($1.7961 promo) |
| **Bigger Flash (Trimmed 3,000)** | `gemini-3.5-flash` @ $1.50/$7.50 | 892,500 | 121,017 | `(0.8925 × $1.50) + (0.1210 × $7.50)` | **$2.2464** ($1.1232 promo) |

---

## 4. Monthly Run Cost (2-Hourly Refresh at Current Volume)

Observed live steady-state volume from Runs #7–#12 (12 hours = 6 unattended runs):
- New posts per 12 hours: `8 + 1 + 0 + 0 + 1 + 3 = 13` new posts $\approx$ **26 new posts/day** $\approx$ **780 new posts/month** (let's budget conservatively at **1,000 new posts/month**).
- Refresh runs per month: `12 runs/day × 30 days = 360 runs/month`, averaging **6.8 minutes (408s)** per run at 1 vCPU / 512 MiB RAM.

| GCP / AI Component | Usage Calculation | Monthly Cost (USD) |
|--------------------|-------------------|--------------------|
| **LLM Tagging (`gemini-3.5-flash-lite`)** | ~1,000 new posts/month @ `$0.84 / 1k` (current) or `$0.57 / 1k` (fixed 3k) | **$0.57 – $0.84** |
| **Cloud Run Job (`beep-refresh-job`)** | 360 runs × 408s = `146,880` vCPU-s & `73,440` GiB-s (within Cloud Run monthly free tier of `180,000` vCPU-s & `360,000` GiB-s!) | **$0.00** *(~$2–$3 if free tier exceeded)* |
| **Cloud Run Service (`beep-job-hub`)** | Scale-to-zero (`--min-instances 0`), low demo/student traffic (<50k req/mo, well inside 2M free req/mo) | **$0.00** |
| **Cloud Scheduler (`beep-refresh-2hr`)** | 1 job (first 3 jobs/month free; `$0.10/job` after) | **$0.00** |
| **Cloud SQL PostgreSQL (`db-f1-micro`, `asia-south1`)** | Always-on shared-core compute (~$8.00/mo) + 10 GB SSD storage (~$1.70/mo) + automated backups (~$0.50/mo) | **~$10.20 / month** |
| **TOTAL MONTHLY RUN COST** | Dominated 92% by always-on Cloud SQL | **~$10.77 – $11.04 / month** |

*Optimization note:* Moving from `2-hour` to `6-hour` cadence cuts Cloud Run Job compute by 3x (zero impact on freshness for campus jobs), and using Neon/Supabase free Postgres tier or Cloud SQL pause after demo cuts Cloud SQL from ~$10.20/mo to $0/mo.
