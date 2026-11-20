"""
backend/app/api/queries.py - Parameterized Query Layer for Search, Filters & Analytics

Provides high-performance, indexed database queries with:
- Sub-500ms full-text search across titles, companies, and descriptions
- Dynamic filter aggregations (cities, roles, job types, sources)
- Multi-source link attachment for deduplicated jobs
- Pipeline status audit and LLM cost analytics
"""

import json
import math
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from app.db import Database


def search_jobs(
    db: Database,
    q: Optional[str] = None,
    city: Optional[str] = None,
    role: Optional[str] = None,
    job_type: Optional[str] = None,
    workplace: Optional[str] = None,
    source: Optional[str] = None,
    posted_within: Optional[str] = None,
    min_exp: Optional[int] = None,
    max_exp: Optional[int] = None,
    page: int = 1,
    limit: int = 12,
    sort_by: str = "newest"
) -> Dict[str, Any]:
    """
    Executes search and filter query with pagination.
    Returns: { "total": int, "page": int, "limit": int, "total_pages": int, "jobs": List[dict] }
    """
    page = max(1, page)
    limit = max(1, min(100, limit))
    offset = (page - 1) * limit

    # Read-only query: expired postings are excluded below (and deactivated during scheduled pipeline runs)
    conditions = ["is_active = 1" if db.is_sqlite else "is_active = TRUE"]
    params: List[Any] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    if db.is_sqlite:
        conditions.append("(expires_at IS NULL OR expires_at = '' OR expires_at > ?)")
        params.append(now_iso)
    else:
        conditions.append("(expires_at IS NULL OR expires_at > NOW())")

    # 1. Full-text search / text matching
    if q and q.strip():
        search_term = q.strip()
        if db.is_sqlite:
            conditions.append(
                "(LOWER(title) LIKE ? OR LOWER(company) LIKE ? OR LOWER(description) LIKE ? OR LOWER(skills) LIKE ?)"
            )
            like_val = f"%{search_term.lower()}%"
            params.extend([like_val, like_val, like_val, like_val])
        else:
            # PostgreSQL full-text search with fallback to ILIKE across title, company, and skills
            conditions.append(
                "(to_tsvector('english', title || ' ' || company || ' ' || COALESCE(description, '')) @@ plainto_tsquery('english', %s) "
                "OR title ILIKE %s OR company ILIKE %s OR COALESCE(skills::text, '') ILIKE %s)"
            )
            like_val = f"%{search_term}%"
            params.extend([search_term, like_val, like_val, like_val])

    # 2. City filter
    if city and city.strip():
        conditions.append("city = ?" if db.is_sqlite else "city = %s")
        params.append(city.strip())

    # 3. Role taxonomy filter
    if role and role.strip():
        conditions.append("role_tag = ?" if db.is_sqlite else "role_tag = %s")
        params.append(role.strip())

    # 4. Job type filter ('job' or 'internship')
    if job_type and job_type.strip():
        conditions.append("job_type = ?" if db.is_sqlite else "job_type = %s")
        params.append(job_type.strip().lower())

    # 4b. Workplace type filter ('remote' or 'onsite')
    if workplace and workplace.strip():
        wp = workplace.strip().lower()
        if wp == "remote":
            conditions.append("city = ?" if db.is_sqlite else "city = %s")
            params.append("Remote")
        elif wp == "onsite":
            conditions.append("city != ?" if db.is_sqlite else "city != %s")
            params.append("Remote")

    # 5. Source filter
    if source and source.strip():
        conditions.append("source_name = ?" if db.is_sqlite else "source_name = %s")
        params.append(source.strip().lower())

    # 6. Experience range filter
    if min_exp is not None:
        conditions.append("min_exp >= ?" if db.is_sqlite else "min_exp >= %s")
        params.append(min_exp)
    if max_exp is not None:
        conditions.append("max_exp <= ?" if db.is_sqlite else "max_exp <= %s")
        params.append(max_exp)

    # 7. Posted within filter ('24h', '7d', '30d')
    if posted_within in ("24h", "7d", "30d"):
        hours = {"24h": 24, "7d": 168, "30d": 720}[posted_within]
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        if db.is_sqlite:
            conditions.append("posted_date >= ?")
            params.append(cutoff)
        else:
            conditions.append("posted_date >= %s")
            params.append(cutoff)

    # By default, exclude stale posts not seen in the last 60 days
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    if db.is_sqlite:
        conditions.append("(last_seen_at IS NULL OR last_seen_at >= ?)")
        params.append(stale_cutoff)
    else:
        conditions.append("(last_seen_at IS NULL OR last_seen_at >= %s)")
        params.append(stale_cutoff)

    where_clause = " WHERE " + " AND ".join(conditions)

    # Sort order
    order_clause = " ORDER BY posted_date DESC, id DESC"
    if sort_by == "oldest":
        order_clause = " ORDER BY posted_date ASC, id ASC"

    conn = db.get_connection()
    try:
        cur = conn.cursor()

        # 1. Count query
        count_query = f"SELECT COUNT(*) FROM jobs{where_clause}"
        cur.execute(count_query, params)
        total_count = cur.fetchone()[0]

        # 2. Paginated data query
        data_query = (
            f"SELECT id, normalized_key, title, company, location_raw, city, job_type, "
            f"posted_date, apply_url, description, source_name, source_job_id, "
            f"first_seen_at, last_seen_at, role_tag, is_fresher_friendly, min_exp, "
            f"max_exp, skills, confidence, expires_at, last_verified_at "
            f"FROM jobs{where_clause}{order_clause} LIMIT ? OFFSET ?"
            if db.is_sqlite else
            f"SELECT id, normalized_key, title, company, location_raw, city, job_type, "
            f"posted_date, apply_url, description, source_name, source_job_id, "
            f"first_seen_at, last_seen_at, role_tag, is_fresher_friendly, min_exp, "
            f"max_exp, skills, confidence, expires_at, last_verified_at "
            f"FROM jobs{where_clause}{order_clause} LIMIT %s OFFSET %s"
        )
        data_params = list(params) + [limit, offset]
        cur.execute(data_query, data_params)
        rows = cur.fetchall()

        jobs = []
        job_ids = []
        for r in rows:
            if db.is_sqlite:
                raw_skills = r["skills"]
                parsed_skills = json.loads(raw_skills) if isinstance(raw_skills, str) else (raw_skills or [])
                job_dict = {
                    "id": r["id"],
                    "title": r["title"],
                    "company": r["company"],
                    "location_raw": r["location_raw"],
                    "city": r["city"],
                    "job_type": r["job_type"],
                    "posted_date": r["posted_date"],
                    "apply_url": r["apply_url"],
                    "description": r["description"],
                    "source_name": r["source_name"],
                    "role_tag": r["role_tag"],
                    "is_fresher_friendly": bool(r["is_fresher_friendly"]),
                    "min_exp": r["min_exp"],
                    "max_exp": r["max_exp"],
                    "skills": parsed_skills,
                    "confidence": float(r["confidence"]) if r["confidence"] else 1.0,
                    "first_seen_at": r["first_seen_at"],
                    "expires_at": r["expires_at"],
                    "last_verified_at": r["last_verified_at"],
                    "sources": []
                }
            else:
                raw_skills = r[18]
                parsed_skills = json.loads(raw_skills) if isinstance(raw_skills, str) else (raw_skills or [])
                job_dict = {
                    "id": r[0],
                    "title": r[2],
                    "company": r[3],
                    "location_raw": r[4],
                    "city": r[5],
                    "job_type": r[6],
                    "posted_date": r[7].isoformat() if hasattr(r[7], 'isoformat') else r[7],
                    "apply_url": r[8],
                    "description": r[9],
                    "source_name": r[10],
                    "role_tag": r[14],
                    "is_fresher_friendly": bool(r[15]),
                    "min_exp": r[16],
                    "max_exp": r[17],
                    "skills": parsed_skills,
                    "confidence": float(r[19]) if r[19] else 1.0,
                    "first_seen_at": r[12].isoformat() if hasattr(r[12], 'isoformat') else r[12],
                    "expires_at": r[20].isoformat() if hasattr(r[20], 'isoformat') else r[20],
                    "last_verified_at": r[21].isoformat() if hasattr(r[21], 'isoformat') else r[21],
                    "sources": []
                }
            jobs.append(job_dict)
            job_ids.append(job_dict["id"])

        # 3. Fetch linked sources for all retrieved jobs in one query
        if job_ids:
            placeholders = ",".join(["?"] * len(job_ids)) if db.is_sqlite else ",".join(["%s"] * len(job_ids))
            sources_query = f"SELECT job_id, source_name, url FROM job_sources WHERE job_id IN ({placeholders})"
            cur.execute(sources_query, job_ids)
            source_rows = cur.fetchall()
            sources_map: Dict[int, List[Dict[str, str]]] = {jid: [] for jid in job_ids}
            for s in source_rows:
                jid = s[0] if isinstance(s, tuple) else s["job_id"]
                s_name = s[1] if isinstance(s, tuple) else s["source_name"]
                s_url = s[2] if isinstance(s, tuple) else s["url"]
                sources_map[jid].append({"source_name": s_name, "url": s_url})

            for job in jobs:
                job["sources"] = sources_map.get(job["id"], [])

        total_pages = math.ceil(total_count / limit) if limit > 0 else 1

        return {
            "total": total_count,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "jobs": jobs
        }
    finally:
        if not db._sqlite_mem_conn:
            conn.close()


def get_filter_options(db: Database) -> Dict[str, Any]:
    """
    Returns active non-expired counts for cities, roles, job types, and sources to populate filter UI.
    """
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        if db.is_sqlite:
            active_clause = "WHERE is_active = 1 AND (expires_at IS NULL OR expires_at = '' OR expires_at > ?)"
            f_params: tuple = (now_iso,)
        else:
            active_clause = "WHERE is_active = TRUE AND (expires_at IS NULL OR expires_at > NOW())"
            f_params = ()

        # Cities
        cur.execute(f"SELECT city, COUNT(*) as cnt FROM jobs {active_clause} GROUP BY city ORDER BY cnt DESC", f_params)
        cities = [{"name": r[0] if isinstance(r, tuple) else r["city"], "count": r[1] if isinstance(r, tuple) else r["cnt"]} for r in cur.fetchall()]

        # Roles
        cur.execute(f"SELECT role_tag, COUNT(*) as cnt FROM jobs {active_clause} GROUP BY role_tag ORDER BY cnt DESC", f_params)
        roles = [{"name": r[0] if isinstance(r, tuple) else r["role_tag"], "count": r[1] if isinstance(r, tuple) else r["cnt"]} for r in cur.fetchall()]

        # Job types
        cur.execute(f"SELECT job_type, COUNT(*) as cnt FROM jobs {active_clause} GROUP BY job_type ORDER BY cnt DESC", f_params)
        job_types = [{"name": r[0] if isinstance(r, tuple) else r["job_type"], "count": r[1] if isinstance(r, tuple) else r["cnt"]} for r in cur.fetchall()]

        # Sources
        cur.execute(f"SELECT source_name, COUNT(*) as cnt FROM jobs {active_clause} GROUP BY source_name ORDER BY cnt DESC", f_params)
        sources = [{"name": r[0] if isinstance(r, tuple) else r["source_name"], "count": r[1] if isinstance(r, tuple) else r["cnt"]} for r in cur.fetchall()]

        # Total active count
        cur.execute(f"SELECT COUNT(*) FROM jobs {active_clause}", f_params)
        total = cur.fetchone()[0]

        return {
            "cities": cities,
            "roles": roles,
            "job_types": job_types,
            "sources": sources,
            "total_active_jobs": total
        }
    finally:
        if not db._sqlite_mem_conn:
            conn.close()


def get_status_summary(db: Database, limit: int = 10) -> Dict[str, Any]:
    """
    Returns recent pipeline runs and audit metrics for the /status dashboard.
    """
    conn = db.get_connection()
    try:
        cur = conn.cursor()

        # Total jobs & last update
        cur.execute("SELECT COUNT(*) FROM jobs WHERE is_active = 1" if db.is_sqlite else "SELECT COUNT(*) FROM jobs WHERE is_active = TRUE")
        total_jobs = cur.fetchone()[0]

        cur.execute("SELECT MAX(finished_at) FROM pipeline_runs WHERE status = 'success'")
        last_updated_row = cur.fetchone()
        last_updated = last_updated_row[0] if last_updated_row else None

        # Recent runs
        cur.execute(
            f"SELECT id, started_at, finished_at, status, sources_summary, total_fetched, "
            f"new_posts, duplicates_skipped, tagged_count, failed_count, error_message "
            f"FROM pipeline_runs ORDER BY started_at DESC LIMIT {limit}"
        )
        rows = cur.fetchall()
        runs = []
        for r in rows:
            if db.is_sqlite:
                summary_raw = r["sources_summary"]
                parsed_summary = json.loads(summary_raw) if isinstance(summary_raw, str) else (summary_raw or {})
                runs.append({
                    "id": r["id"],
                    "started_at": r["started_at"],
                    "finished_at": r["finished_at"],
                    "status": r["status"],
                    "sources_summary": parsed_summary,
                    "total_fetched": r["total_fetched"],
                    "new_posts": r["new_posts"],
                    "duplicates_skipped": r["duplicates_skipped"],
                    "tagged_count": r["tagged_count"],
                    "failed_count": r["failed_count"],
                    "error_message": r["error_message"]
                })
            else:
                summary_raw = r[4]
                parsed_summary = json.loads(summary_raw) if isinstance(summary_raw, str) else (summary_raw or {})
                runs.append({
                    "id": r[0],
                    "started_at": r[1].isoformat() if hasattr(r[1], 'isoformat') else r[1],
                    "finished_at": r[2].isoformat() if hasattr(r[2], 'isoformat') else r[2],
                    "status": r[3],
                    "sources_summary": parsed_summary,
                    "total_fetched": r[5],
                    "new_posts": r[6],
                    "duplicates_skipped": r[7],
                    "tagged_count": r[8],
                    "failed_count": r[9],
                    "error_message": r[10]
                })

        return {
            "last_updated": last_updated,
            "total_active_jobs": total_jobs,
            "recent_runs": runs
        }
    finally:
        if not db._sqlite_mem_conn:
            conn.close()


def get_cost_metrics(db: Database) -> Dict[str, Any]:
    """
    Computes total LLM tokens, total spend, and cost per 1,000 posts.
    """
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), SUM(posts_count), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd) FROM llm_cost_logs")
        row = cur.fetchone()

        total_calls = row[0] or 0
        total_posts_tagged = row[1] or 0
        total_in_tokens = row[2] or 0
        total_out_tokens = row[3] or 0
        total_cost_usd = float(row[4] or 0.0)

        cost_per_1000 = (total_cost_usd / total_posts_tagged * 1000.0) if total_posts_tagged > 0 else 0.0

        return {
            "total_api_calls": total_calls,
            "total_posts_tagged": total_posts_tagged,
            "total_input_tokens": total_in_tokens,
            "total_output_tokens": total_out_tokens,
            "total_cost_usd": round(total_cost_usd, 6),
            "cost_per_1000_posts_usd": round(cost_per_1000, 4)
        }
    finally:
        if not db._sqlite_mem_conn:
            conn.close()
