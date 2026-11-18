#!/usr/bin/env python3
"""
scripts/run_llm_tagger.py — Live Gemini Flash-Lite LLM Tagging & Accuracy Verification

Re-tags all active jobs in test_live.db using the configured Gemini LLM
(GEMINI_API_KEY or VERTEX_ACCESS_TOKEN in .env), logs token usage and USD cost
to llm_cost_logs, syncs frontend/assets/mock-data.js, and prints a detailed
verification report.
"""

import os
import sys
import json
from datetime import datetime, timezone

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
sys.path.insert(0, BACKEND_DIR)

from app import config
from app.db import Database
from app.tagger import enrich_untagged_jobs
from app.api.queries import search_jobs, get_filter_options, get_cost_metrics


def main() -> None:
    db_file = os.path.join(ROOT_DIR, "test_live.db")
    db = Database(f"sqlite:///{db_file}")

    api_key = os.environ.get("GEMINI_API_KEY") or config.GEMINI_API_KEY
    vertex_token = os.environ.get("VERTEX_ACCESS_TOKEN") or config.VERTEX_ACCESS_TOKEN

    print("=================================================================")
    print("LIVE LLM TAGGING & TAXONOMY VERIFICATION")
    if api_key:
        print(f"LLM Mode:     LIVE Gemini REST API (Model: {config.VERTEX_AI_MODEL})")
    elif vertex_token:
        print(f"LLM Mode:     LIVE Vertex AI REST API (Model: {config.VERTEX_AI_MODEL})")
    else:
        print("LLM Mode:     Deterministic Heuristic Fallback (Set GEMINI_API_KEY in .env for live Gemini calls)")
    print("=================================================================\n")

    # Reset tagged_at so all active jobs are freshly tagged in this verification run
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE jobs SET tagged_at = NULL WHERE is_active = 1")
    cur.execute("DELETE FROM llm_cost_logs")
    conn.commit()
    conn.close()

    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM pipeline_runs WHERE status = 'success' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    run_id = row[0] if row else db.start_pipeline_run()
    conn.close()

    tagged_count = enrich_untagged_jobs(db, run_id=run_id, batch_size=30)

    filters = get_filter_options(db)
    cost = get_cost_metrics(db)
    sample = search_jobs(db, page=1, limit=15)

    # Sync frontend/assets/mock-data.js with the freshly tagged DB rows
    all_jobs, page = [], 1
    while True:
        r = search_jobs(db, page=page, limit=100)
        all_jobs.extend(r["jobs"])
        if page >= r["total_pages"]:
            break
        page += 1
    keep = ["id", "title", "company", "location_raw", "city", "job_type", "posted_date", "apply_url", "description", "source_name", "role_tag", "min_exp", "max_exp", "skills", "sources"]
    trimmed = [{k: j.get(k) for k in keep} for j in all_jobs]
    mock_out = (
        "// Snapshot of verified open rows from the live pipeline (test_live.db), in the exact /api/jobs shape.\n"
        + "window.MOCK = "
        + json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "jobs": trimmed}, ensure_ascii=False)
        + ";\n"
    )
    with open(os.path.join(ROOT_DIR, "frontend", "assets", "mock-data.js"), "w", encoding="utf-8") as f:
        f.write(mock_out)

    print("\n-----------------------------------------------------------------")
    print("LLM TAGGING & COST SUMMARY")
    print("-----------------------------------------------------------------")
    print(f"Total Jobs Tagged:       {tagged_count}")
    print(f"Total Input Tokens:      {cost['total_input_tokens']:,}")
    print(f"Total Output Tokens:     {cost['total_output_tokens']:,}")
    print(f"Total Run Cost (USD):    ${cost['total_cost_usd']:.5f}")
    print(f"Cost per 1,000 Posts:    ${cost['cost_per_1000_posts_usd']:.4f}")
    roles_str = [f"{r['name']} ({r['count']})" for r in filters["roles"]]
    cities_str = [f"{c['name']} ({c['count']})" for c in filters["cities"][:8]]
    print(f"Role Distribution:       {roles_str}")
    print(f"Top Cities:              {cities_str}")

    print("\n-----------------------------------------------------------------")
    print("SAMPLE TAGGED POSTS (First 15):")
    print("-----------------------------------------------------------------")
    for i, j in enumerate(sample["jobs"], 1):
        print(f"[{i:2d}] {j['company']} — {j['title']}")
        print(f"     Role: {j['role_tag']:10s} | City: {j['city']:12s} | Type: {j['job_type']:10s} | Confidence: {j['confidence']:.2f}")
        print(f"     Skills: {', '.join(j['skills'])}")
    print("=================================================================")


if __name__ == "__main__":
    main()
