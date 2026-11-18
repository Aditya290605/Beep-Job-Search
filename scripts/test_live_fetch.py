#!/usr/bin/env python3
"""
scripts/test_live_fetch.py - Live Ingestion & Backend Verification Script

Connects to the live public endpoints (Greenhouse, Lever, Ashby, SmartRecruiters, Jobicy, Remotive),
fetches real fresher jobs, runs deduplication, stores them in an isolated test database,
and queries the API layer to display sample live jobs.
"""

import sys
import os
import json

# Add backend to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from app.db import Database
from app.pipeline import run_pipeline
from app.api.queries import search_jobs, get_filter_options

def main():
    print("=================================================================")
    print("LIVE BACKEND & JOB INGESTION TEST")
    print("Connecting to live public APIs (Greenhouse, Lever, Ashby, Jobicy)...")
    print("=================================================================\n")

    # Use a local test SQLite DB file for inspection
    db_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "../test_live.db"))
    if os.path.exists(db_file):
        os.remove(db_file)

    db = Database(f"sqlite:///{db_file}")
    schema_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend/app/schema.sql"))
    db.init_db(schema_path)

    # Run the full pipeline
    stats = run_pipeline(db)

    print("\n-----------------------------------------------------------------")
    print("PIPELINE EXECUTION SUMMARY")
    print("-----------------------------------------------------------------")
    print(f"Status:             {stats.status}")
    print(f"Total Fetched:      {stats.total_fetched}")
    print(f"New Posts Stored:   {stats.new_posts}")
    print(f"Duplicates Skipped: {stats.duplicates_skipped}")
    print(f"Source Breakdown:   {json.dumps(stats.sources_summary, indent=2)}")

    print("\n-----------------------------------------------------------------")
    print("QUERYING API LAYER FOR STORED JOBS (First 10 Posts):")
    print("-----------------------------------------------------------------")
    results = search_jobs(db, page=1, limit=10)
    print(f"Total Jobs Available in DB: {results['total']}\n")

    for i, job in enumerate(results["jobs"], 1):
        print(f"[{i}] {job['company']} - {job['title']}")
        print(f"    City:        {job['city']} ({job['location_raw']})")
        print(f"    Role Tag:    {job['role_tag']} | Type: {job['job_type']}")
        print(f"    Skills:      {', '.join(job['skills']) if job['skills'] else 'N/A'}")
        print(f"    Apply URL:   {job['apply_url']}")
        print(f"    Source:      {job['source_name']}")
        if job["sources"]:
            print(f"    Other Links: {len(job['sources'])} alternative source(s) linked")
        print("")

    # Filter counts
    filters = get_filter_options(db)
    print("-----------------------------------------------------------------")
    print("DYNAMIC FILTER AGGREGATIONS:")
    print("-----------------------------------------------------------------")
    print("Top Cities:", [f"{c['name']} ({c['count']})" for c in filters['cities'][:6]])
    print("Roles:     ", [f"{r['name']} ({r['count']})" for r in filters['roles']])
    print("Job Types: ", [f"{t['name']} ({t['count']})" for t in filters['job_types']])
    print("Sources:   ", [f"{s['name']} ({s['count']})" for s in filters['sources']])
    print("=================================================================\n")

if __name__ == "__main__":
    main()
