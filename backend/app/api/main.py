"""
backend/app/api/main.py - FastAPI Application for Fresher Jobs India

Serves:
- REST API for job search, filters, pagination, and status
- Static build of the React frontend in single-container deployment
- Health probes for Cloud Run
"""

import os
import sys
import time
from typing import Optional
from datetime import datetime, timezone

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app import config
from app.db import Database
from app.api.queries import search_jobs, get_filter_options, get_status_summary, get_cost_metrics

app = FastAPI(
    title="Fresher Jobs India API",
    description="Live job aggregator and LLM enrichment engine for Indian college freshers and interns.",
    version="1.0.0"
)

# Enable CORS for local dev and Cloud Run domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global DB instance (initialized on startup)
db: Optional[Database] = None


@app.on_event("startup")
def startup_event():
    global db
    db = Database()
    schema_path = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
    try:
        db.init_db(schema_path)
    except Exception as e:
        print(f"Warning on db.init_db: {e}")


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}s"
    return response


# --- Core Health & Status Endpoints ---

@app.get("/healthz")
def healthz():
    """Liveness & readiness probe for Cloud Run."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "sqlite" if (db and db.is_sqlite) else "postgres"
    }


@app.get("/api/status")
def get_status():
    """Returns recent pipeline runs, last updated timestamp, and operational health."""
    if not db:
        raise HTTPException(status_code=500, detail="Database uninitialized")
    return get_status_summary(db)


@app.get("/api/metrics/cost")
def get_cost():
    """Returns token analytics, total LLM spend, and cost per 1,000 posts."""
    if not db:
        raise HTTPException(status_code=500, detail="Database uninitialized")
    return get_cost_metrics(db)


# --- Job Search & Filter Endpoints ---

@app.get("/api/jobs")
def get_jobs(
    q: Optional[str] = Query(None, description="Search term across title, company, skills, description"),
    city: Optional[str] = Query(None, description="Filter by canonical city (e.g. Bangalore, Pune, Remote)"),
    role: Optional[str] = Query(None, description="Filter by role taxonomy (SDE, Data/ML, Design, etc.)"),
    job_type: Optional[str] = Query(None, description="'job' or 'internship'"),
    source: Optional[str] = Query(None, description="Source name (greenhouse, lever, ashby, jobicy, remotive)"),
    posted_within: Optional[str] = Query(None, description="Filter by time posted ('24h', '7d', '30d')"),
    min_exp: Optional[int] = Query(None, description="Minimum experience required"),
    max_exp: Optional[int] = Query(None, description="Maximum experience required"),
    page: int = Query(1, ge=1, description="Page number (starts at 1)"),
    limit: int = Query(12, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("newest", description="'newest' or 'oldest'")
):
    """
    Search and filter jobs with pagination, sorting, and multi-source URL resolution.
    Target p95 response time < 500 ms.
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database uninitialized")

    return search_jobs(
        db=db,
        q=q,
        city=city,
        role=role,
        job_type=job_type,
        source=source,
        posted_within=posted_within,
        min_exp=min_exp,
        max_exp=max_exp,
        page=page,
        limit=limit,
        sort_by=sort_by
    )


@app.get("/api/filters")
def get_filters():
    """Returns distinct available cities, roles, job types, and sources with counts."""
    if not db:
        raise HTTPException(status_code=500, detail="Database uninitialized")
    return get_filter_options(db)


# --- Static Frontend Hosting (Single Container) ---

frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../frontend/dist"))

if os.path.exists(frontend_dist):
    # Mount static assets directory
    assets_dir = os.path.join(frontend_dist, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Catch-all route to serve React SPA (HTML5 client-side routing)
    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        file_path = os.path.join(frontend_dist, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        index_file = os.path.join(frontend_dist, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return JSONResponse({"status": "frontend_building", "message": "Fresher Jobs India API is running."})
