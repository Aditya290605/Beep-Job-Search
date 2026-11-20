# DEPLOY.md — GCP Deployment, Cloud Scheduler (Every 2 Hours) & Alerts Guide

This guide walks through deploying **Beep Job Hub** to **Google Cloud Run** (Single-Container API + UI), connecting **Cloud SQL (PostgreSQL)** and **Vertex AI (Gemini Flash-Lite)**, scheduling the **2-hour automated refresh**, and configuring **failure email alerts**.

All commands below can be pasted directly into **GCP Cloud Shell** (zero local installation required on your Mac).

---

## 1. Set Your Project Variables in Cloud Shell

Open [GCP Cloud Shell](https://console.cloud.google.com/?cloudshell=true) and set your environment variables:

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="asia-south1"
export SQL_INSTANCE="fresher-jobs-pg"
export DB_NAME="jobs_db"
export DB_USER="postgres"
export DB_PASS="your-db-password"
export SERVICE_NAME="fresher-jobs-hub"
export JOB_NAME="fresher-jobs-refresh"

gcloud config set project $PROJECT_ID
gcloud config set run/region $REGION
```

---

## 2. Enable Required GCP APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  sqladmin.googleapis.com \
  cloudscheduler.googleapis.com \
  aiplatform.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com
```

---

## 3. Clone Your GitHub Repo in Cloud Shell & Build Container

```bash
git clone https://github.com/<your-username>/Beep-Job-Search.git
cd Beep-Job-Search

# Build and push container image via Cloud Build
gcloud builds submit --tag gcr.io/$PROJECT_ID/$SERVICE_NAME:latest .
```

---

## 4. Deploy Cloud Run Service (Web UI + FastAPI `/api/*`)

This single command deploys the container, attaches your Cloud SQL Postgres instance over the Unix socket `/cloudsql/...`, grants Vertex AI access for Gemini Flash-Lite tagging, and auto-seeds on first boot if the database is empty:

```bash
export INSTANCE_CONNECTION_NAME="$PROJECT_ID:$REGION:$SQL_INSTANCE"
export DATABASE_URL="postgresql://$DB_USER:$DB_PASS@/$DB_NAME?host=/cloudsql/$INSTANCE_CONNECTION_NAME"

gcloud run deploy $SERVICE_NAME \
  --image gcr.io/$PROJECT_ID/$SERVICE_NAME:latest \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --add-cloudsql-instances $INSTANCE_CONNECTION_NAME \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_REGION=$REGION,DATABASE_URL=$DATABASE_URL,AUTO_SEED_ON_BOOT=true" \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 3 \
  --port 8080
```

Once deployed, Cloud Run prints your live URL:
`https://fresher-jobs-hub-<hash>-el.a.run.app`

Verify health & live endpoints:
- `https://<your-cloud-run-url>/` (Beep Job Hub UI with 230+ roles)
- `https://<your-cloud-run-url>/api/health` (Liveness & database check — use `/api/health` externally because Cloud Run's Google Frontend intercepts `/healthz`)
- `https://<your-cloud-run-url>/api/status` (Pipeline telemetry & unattended run history)
- `https://<your-cloud-run-url>/api/metrics/cost` (LLM token & cost per 1,000 posts)

---

## 5. Create the Cloud Run Job & 2-Hour Cloud Scheduler (`0 */2 * * *` IST)

### Option A: Cloud Run Job + Cloud Scheduler (Recommended)

```bash
# 1. Create the Cloud Run Job using the same image, overriding command to run the pipeline
gcloud run jobs create $JOB_NAME \
  --image gcr.io/$PROJECT_ID/$SERVICE_NAME:latest \
  --region $REGION \
  --set-cloudsql-instances $INSTANCE_CONNECTION_NAME \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_REGION=$REGION,DATABASE_URL=$DATABASE_URL" \
  --command "python" \
  --args "-m,app.pipeline" \
  --memory 512Mi \
  --task-timeout 900s

# 2. Execute the job immediately once to verify initial seed & Gemini tagging
gcloud run jobs execute $JOB_NAME --region $REGION --wait
```

### Option B: Schedule Every 2 Hours via `POST /api/refresh`

```bash
export SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region $REGION --format='value(status.url)')

gcloud scheduler jobs create http fresher-jobs-2h-cron \
  --location $REGION \
  --schedule "0 */2 * * *" \
  --time-zone "Asia/Kolkata" \
  --uri "$SERVICE_URL/api/refresh" \
  --http-method POST \
  --attempt-deadline 300s
```

Test triggering the scheduler immediately:
```bash
gcloud scheduler jobs run fresher-jobs-2h-cron --location $REGION
```

---

## 6. Configure Failure Email Alert (Cloud Monitoring)

1. In the GCP Console, open **Logging → Logs Explorer**.
2. Paste this log filter to catch any pipeline or container error:
   ```text
   resource.type=("cloud_run_revision" OR "cloud_run_job")
   severity>=ERROR
   ```
3. Click **Create alert** in the query results bar:
   - **Alert name:** `Beep Job Hub Pipeline Failure Alert`
   - **Notification frequency:** `5 minutes`
   - **Notification channel:** Select or create your **Email** channel.
   - Click **Save**.

---

## 7. Cold-Start Trade-Off & Post-Review Cost Shutdown Plan

### Cold-Start Trade-Off (`--min-instances 0` vs `1`)
- With `--min-instances 0`, Cloud Run scales to zero when idle ($0 compute cost when nobody is browsing). The first request after idle takes ~2–3 seconds to warm up.
- During the founder review window, you can optionally set `--min-instances 1` for instant 0ms cold starts, then revert to `0` afterward.

### Post-Submission Shutdown / Zero-Cost Preservation Plan
Cloud SQL (`db-f1-micro`) is the primary ongoing cost (~$9–$12/month after free credits). Once the assessment review is complete, you have three clean options:
1. **Pause Cloud SQL Instance (Quickest):**
   ```bash
   gcloud sql instances patch $SQL_INSTANCE --activation-policy NEVER
   ```
2. **Switch Cloud Run to Built-In SQLite Snapshot (Zero Cloud SQL Cost):**
   Remove `DATABASE_URL` so the container uses its built-in SQLite + `AUTO_SEED_ON_BOOT=true` mode at $0/month, and delete the Cloud SQL instance:
   ```bash
   gcloud sql instances delete $SQL_INSTANCE
   ```
3. **Full Project Teardown:**
   The active dataset is archived in `submission/dataset_active_jobs.csv`. Then delete the GCP project or disable billing when the evaluation is complete.
