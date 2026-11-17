"""
pipeline.py - Pipeline Orchestrator for Fresher Jobs India

Executes all independent source adapters, aggregates fresher jobs,
deduplicates them, inserts them into PostgreSQL (Cloud SQL), and logs the run metrics.
Can be executed as a Cloud Run Job or standalone script.
"""

import sys
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import config
from app.models import RawJob, PipelineRunStats
from app.db import Database

# Import adapters
from app.adapters.greenhouse import fetch_greenhouse_jobs
from app.adapters.lever import fetch_lever_jobs
from app.adapters.ashby import fetch_ashby_jobs
from app.adapters.smartrecruiters import fetch_smartrecruiters_jobs
from app.adapters.jobicy import fetch_jobicy_jobs
from app.adapters.remotive import fetch_remotive_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("pipeline")


def run_pipeline(db: Database = None) -> PipelineRunStats:
    """
    Executes the ingestion pipeline across all configured sources:
    1. Initializes DB tables if not present.
    2. Runs each adapter with full fault isolation (one failure never kills the run).
    3. Drops posts with Unknown city.
    4. Idempotently writes new jobs to DB and links duplicates in job_sources.
    5. Records run metrics to pipeline_runs table.
    """
    if db is None:
        db = Database()
        db.init_db()

    run_id = db.start_pipeline_run()
    logger.info(f"--- Starting Pipeline Run #{run_id} ---")

    stats = PipelineRunStats(started_at=datetime.now(timezone.utc))
    adapters = [
        ("greenhouse", fetch_greenhouse_jobs),
        ("lever", fetch_lever_jobs),
        ("ashby", fetch_ashby_jobs),
        ("smartrecruiters", fetch_smartrecruiters_jobs),
        ("jobicy", fetch_jobicy_jobs),
        ("remotive", fetch_remotive_jobs)
    ]

    all_raw_jobs: List[RawJob] = []

    for name, adapter_fn in adapters:
        try:
            logger.info(f"Running adapter: {name}...")
            jobs = adapter_fn()
            # Strict filter: location must not be Unknown
            filtered_jobs = [j for j in jobs if j.city and j.city != "Unknown"]
            stats.sources_summary[name] = len(filtered_jobs)
            all_raw_jobs.extend(filtered_jobs)
            logger.info(f"Adapter {name} returned {len(filtered_jobs)} valid jobs")
        except Exception as e:
            logger.error(f"Adapter {name} encountered an error: {e}", exc_info=True)
            stats.sources_summary[name] = 0
            stats.failed_count += 1

    stats.total_fetched = len(all_raw_jobs)
    logger.info(f"Total valid fresher jobs fetched across all sources: {stats.total_fetched}")

    # Database insertion & deduplication
    try:
        inserted, dupes = db.insert_jobs(all_raw_jobs)
        stats.new_posts = inserted
        stats.duplicates_skipped = dupes
        stats.status = "success" if stats.failed_count == 0 else "partial_failure"
        logger.info(f"Insertion complete: {inserted} new posts added, {dupes} duplicates linked")
    except Exception as e:
        logger.error(f"Database insertion failed: {e}", exc_info=True)
        stats.status = "failed"
        stats.error_message = str(e)

    stats.finished_at = datetime.now(timezone.utc)
    db.finish_pipeline_run(run_id, stats)
    logger.info(f"--- Finished Pipeline Run #{run_id} with status: {stats.status} ---")
    return stats


if __name__ == "__main__":
    stats = run_pipeline()
    print("\n================ PIPELINE RUN SUMMARY ================")
    print(f"Status:             {stats.status}")
    print(f"Total Fetched:      {stats.total_fetched}")
    print(f"New Posts Inserted: {stats.new_posts}")
    print(f"Duplicates Linked:  {stats.duplicates_skipped}")
    print(f"Failed Adapters:    {stats.failed_count}")
    print(f"Source Breakdown:   {stats.sources_summary}")
    print("======================================================")
