"""
db.py - Database Access Layer for Fresher Jobs India

Connects to PostgreSQL (Cloud SQL / Neon / standard Postgres) with a seamless
SQLite fallback for local unit tests without requiring external daemons.
"""

import os
import json
import logging
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone
from app import config
from app.models import RawJob, PipelineRunStats
from app.dedupe import DeduplicationIndex

logger = logging.getLogger(__name__)

# Check if psycopg2 or psycopg is available
HAS_PG = False
try:
    import psycopg2
    import psycopg2.extras
    HAS_PG = True
except ImportError:
    try:
        import psycopg
        HAS_PG = True
    except ImportError:
        HAS_PG = False

import sqlite3


def _normalize_ts(val: Any) -> Optional[str]:
    """Converts Unix epoch ints/floats or strings to valid ISO-8601 UTC strings for PostgreSQL TIMESTAMPTZ."""
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, (int, float)):
        ts = float(val) / 1000.0 if val > 10_000_000_000 else float(val)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    s = str(val).strip()
    if not s:
        return None
    if s.isdigit():
        iv = int(s)
        ts = float(iv) / 1000.0 if iv > 10_000_000_000 else float(iv)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return s
    except Exception:
        return None


class Database:
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or config.get_database_url()
        self.is_sqlite = self.db_url.startswith("sqlite") or not HAS_PG
        self._sqlite_mem_conn = None
        if self.is_sqlite:
            path = self.db_url.replace("sqlite:///", "").replace("sqlite://", "")
            if not path or path == ":memory:":
                # Retain in-memory connection across queries
                self._sqlite_mem_conn = sqlite3.connect(":memory:")
                self._sqlite_mem_conn.row_factory = sqlite3.Row

    def get_connection(self):
        if self.is_sqlite:
            if self._sqlite_mem_conn is not None:
                return self._sqlite_mem_conn
            path = self.db_url.replace("sqlite:///", "").replace("sqlite://", "")
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn
        else:
            return psycopg2.connect(self.db_url)

    def init_db(self, schema_file: str = "schema.sql"):
        """Initializes tables using schema.sql (or SQLite-compatible translation)."""
        if not os.path.exists(schema_file):
            fallback_schema = os.path.join(os.path.dirname(__file__), "schema.sql")
            if os.path.exists(fallback_schema):
                schema_file = fallback_schema
            else:
                logger.warning(f"Schema file {schema_file} not found.")
                return

        with open(schema_file, "r") as f:
            ddl = f.read()

        if self.is_sqlite:
            # Translate Postgres-specific types for SQLite compatibility
            ddl = ddl.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            ddl = ddl.replace("TIMESTAMPTZ", "TIMESTAMP")
            ddl = ddl.replace("JSONB", "TEXT")
            ddl = ddl.replace("::jsonb", "")
            ddl = ddl.replace("NUMERIC(3, 2)", "REAL")
            ddl = ddl.replace("NUMERIC(8, 6)", "REAL")
            ddl = ddl.replace("NOW()", "CURRENT_TIMESTAMP")
            
            # Remove Postgres GIN full text index block for SQLite
            statements = ddl.split(";")
            filtered_stmts = []
            for stmt in statements:
                cleaned = stmt.strip()
                if not cleaned:
                    continue
                if "idx_jobs_fts" in cleaned or "USING gin" in cleaned or "to_tsvector" in cleaned:
                    continue
                filtered_stmts.append(cleaned)
            ddl = ";\n".join(filtered_stmts) + ";"

        conn = self.get_connection()
        try:
            cur = conn.cursor()
            if self.is_sqlite:
                cur.executescript(ddl)
                # Auto-migrate expiry/verification columns on existing SQLite DBs
                existing_cols = {r[1] for r in cur.execute("PRAGMA table_info(jobs)").fetchall()}
                if "expires_at" not in existing_cols:
                    cur.execute("ALTER TABLE jobs ADD COLUMN expires_at TIMESTAMP")
                if "last_verified_at" not in existing_cols:
                    cur.execute("ALTER TABLE jobs ADD COLUMN last_verified_at TIMESTAMP")
            else:
                cur.execute(ddl)
                cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ")
                cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ")
            conn.commit()
            logger.info("Database initialized successfully.")
        finally:
            if not self._sqlite_mem_conn:
                conn.close()
        if os.getenv("AUTO_SEED_ON_BOOT", "false").lower() == "true":
            try:
                self.seed_from_defaults()
            except Exception as e:
                logger.warning(f"Default seeding skipped or failed: {e}")

    def seed_from_defaults(self):
        """Seeds jobs, pipeline_runs, and llm_cost_logs from static seed json files if empty."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM jobs")
            cnt = cur.fetchone()[0]
            if cnt > 0:
                return

            seed_dir = os.path.dirname(__file__)
            jobs_path = os.path.join(seed_dir, "seed_jobs.json")
            if os.path.exists(jobs_path):
                with open(jobs_path, "r", encoding="utf-8") as f:
                    jobs = json.load(f)
                for j in jobs:
                    cols = [
                        "normalized_key", "title", "company", "location_raw", "city",
                        "job_type", "posted_date", "apply_url", "description", "source_name",
                        "source_job_id", "first_seen_at", "last_seen_at", "expires_at",
                        "last_verified_at", "is_active", "role_tag", "is_fresher_friendly",
                        "min_exp", "max_exp", "skills", "confidence", "tagged_at"
                    ]
                    is_active_val = bool(j.get("is_active", 1))
                    is_fresher_val = bool(j.get("is_fresher_friendly", True))
                    vals = [
                        j.get("normalized_key"), j.get("title"), j.get("company"),
                        j.get("location_raw"), j.get("city"), j.get("job_type"),
                        _normalize_ts(j.get("posted_date")), j.get("apply_url"), j.get("description"),
                        j.get("source_name"), j.get("source_job_id"), _normalize_ts(j.get("first_seen_at")),
                        _normalize_ts(j.get("last_seen_at")), _normalize_ts(j.get("expires_at")), _normalize_ts(j.get("last_verified_at")),
                        (1 if is_active_val else 0) if self.is_sqlite else is_active_val,
                        j.get("role_tag"),
                        (1 if is_fresher_val else 0) if self.is_sqlite else is_fresher_val,
                        j.get("min_exp", 0), j.get("max_exp", 1),
                        json.dumps(j.get("skills", [])) if isinstance(j.get("skills"), list) else j.get("skills"),
                        j.get("confidence", 0.85), _normalize_ts(j.get("tagged_at"))
                    ]
                    if self.is_sqlite:
                        placeholders = ", ".join(["?"] * len(cols))
                        col_str = ", ".join(cols)
                        cur.execute(f"INSERT OR IGNORE INTO jobs ({col_str}) VALUES ({placeholders})", vals)
                    else:
                        placeholders = ", ".join(["%s"] * len(cols))
                        col_str = ", ".join(cols)
                        cur.execute(f"INSERT INTO jobs ({col_str}) VALUES ({placeholders}) ON CONFLICT (normalized_key) DO NOTHING", vals)
                conn.commit()
                logger.info(f"Seeded {len(jobs)} initial jobs from {jobs_path}")

            runs_path = os.path.join(seed_dir, "seed_runs.json")
            if os.path.exists(runs_path):
                with open(runs_path, "r", encoding="utf-8") as f:
                    runs = json.load(f)
                for r in runs:
                    finished = r.get("finished_at") or r.get("completed_at")
                    if self.is_sqlite:
                        cur.execute(
                            "INSERT OR IGNORE INTO pipeline_runs (id, status, started_at, finished_at, total_fetched, new_posts, duplicates_skipped, tagged_count, failed_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (r.get("id"), r.get("status"), r.get("started_at"), finished, r.get("total_fetched"), r.get("new_posts"), r.get("duplicates_skipped"), r.get("tagged_count"), r.get("failed_count"))
                        )
                    else:
                        cur.execute(
                            "INSERT INTO pipeline_runs (id, status, started_at, finished_at, total_fetched, new_posts, duplicates_skipped, tagged_count, failed_count) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                            (r.get("id"), r.get("status"), r.get("started_at"), finished, r.get("total_fetched"), r.get("new_posts"), r.get("duplicates_skipped"), r.get("tagged_count"), r.get("failed_count"))
                        )
                if not self.is_sqlite:
                    cur.execute("SELECT setval(pg_get_serial_sequence('pipeline_runs', 'id'), COALESCE((SELECT MAX(id) FROM pipeline_runs), 1))")
                conn.commit()

            costs_path = os.path.join(seed_dir, "seed_costs.json")
            if os.path.exists(costs_path):
                with open(costs_path, "r", encoding="utf-8") as f:
                    costs = json.load(f)
                for c in costs:
                    if self.is_sqlite:
                        cur.execute(
                            "INSERT OR IGNORE INTO llm_cost_logs (id, run_id, model_name, posts_count, input_tokens, output_tokens, cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (c.get("id"), c.get("run_id"), c.get("model_name"), c.get("posts_count"), c.get("input_tokens"), c.get("output_tokens"), c.get("cost_usd"), c.get("created_at"))
                        )
                    else:
                        cur.execute(
                            "INSERT INTO llm_cost_logs (id, run_id, model_name, posts_count, input_tokens, output_tokens, cost_usd, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                            (c.get("id"), c.get("run_id"), c.get("model_name"), c.get("posts_count"), c.get("input_tokens"), c.get("output_tokens"), c.get("cost_usd"), c.get("created_at"))
                        )
                if not self.is_sqlite:
                    cur.execute("SELECT setval(pg_get_serial_sequence('llm_cost_logs', 'id'), COALESCE((SELECT MAX(id) FROM llm_cost_logs), 1))")
                conn.commit()
        finally:
            if not self._sqlite_mem_conn:
                conn.close()

    def load_dedupe_index(self) -> DeduplicationIndex:
        """Loads active jobs into the in-memory DeduplicationIndex for fast near-duplicate matching."""
        index = DeduplicationIndex()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, company, title, city, job_type, apply_url FROM jobs WHERE is_active = 1" if self.is_sqlite else "SELECT id, company, title, city, job_type, apply_url FROM jobs WHERE is_active = TRUE")
            rows = cur.fetchall()
            for row in rows:
                if self.is_sqlite:
                    index.index_job(
                        job_id=row["id"], company=row["company"], title=row["title"],
                        city=row["city"], job_type=row["job_type"], apply_url=row["apply_url"]
                    )
                else:
                    index.index_job(
                        job_id=row[0], company=row[1], title=row[2],
                        city=row[3], job_type=row[4], apply_url=row[5]
                    )
            return index
        finally:
            if not self._sqlite_mem_conn:
                conn.close()

    def insert_jobs(self, jobs: List[RawJob], dedupe_index: Optional[DeduplicationIndex] = None) -> Tuple[int, int]:
        """
        Inserts a batch of jobs idempotently with exact + fuzzy deduplication.
        Returns: (inserted_count, duplicates_skipped)
        """
        if not jobs:
            return 0, 0

        if dedupe_index is None:
            dedupe_index = self.load_dedupe_index()

        conn = self.get_connection()
        inserted_count = 0
        duplicates_skipped = 0

        try:
            cur = conn.cursor()
            for job in jobs:
                norm_key = job.normalized_key

                # 1. Level 1: Exact match on normalized_key OR exact apply_url
                if self.is_sqlite:
                    cur.execute("SELECT id, length(COALESCE(description, '')) FROM jobs WHERE normalized_key = ? OR apply_url = ? LIMIT 1", (norm_key, job.apply_url))
                    existing = cur.fetchone()
                else:
                    cur.execute("SELECT id, length(COALESCE(description, '')) FROM jobs WHERE normalized_key = %s OR apply_url = %s LIMIT 1", (norm_key, job.apply_url))
                    existing = cur.fetchone()

                existing_job_id = None
                existing_desc_len = 0
                if existing:
                    existing_job_id = existing[0] if isinstance(existing, tuple) else existing["id"]
                    existing_desc_len = existing[1] if isinstance(existing, tuple) else existing[1]
                else:
                    # 2. Level 2: Fuzzy near-duplicate match (rapidfuzz / difflib)
                    fuzzy_match_id = dedupe_index.find_duplicate(job)
                    if fuzzy_match_id:
                        existing_job_id = fuzzy_match_id

                now_str = datetime.now(timezone.utc).isoformat()
                posted_iso = _normalize_ts(job.posted_date) or now_str
                expires_iso = _normalize_ts(job.expires_at)
                verified_iso = _normalize_ts(job.last_verified_at) or now_str
                if existing_job_id:
                    duplicates_skipped += 1
                    # Refresh last_seen_at / expires_at / last_verified_at (and upgrade stub description if real JD arrived)
                    if self.is_sqlite:
                        if job.description and len(job.description) > max(existing_desc_len, 250):
                            # If upgrading a short stub to a real full JD, reset tagged_at so Gemini re-evaluates with full JD
                            if existing_desc_len < 250:
                                cur.execute(
                                    "UPDATE jobs SET last_seen_at = ?, last_verified_at = COALESCE(?, last_verified_at), expires_at = COALESCE(?, expires_at), description = ?, tagged_at = NULL WHERE id = ?",
                                    (now_str, verified_iso, expires_iso, job.description, existing_job_id)
                                )
                            else:
                                cur.execute(
                                    "UPDATE jobs SET last_seen_at = ?, last_verified_at = COALESCE(?, last_verified_at), expires_at = COALESCE(?, expires_at), description = ? WHERE id = ?",
                                    (now_str, verified_iso, expires_iso, job.description, existing_job_id)
                                )
                        else:
                            cur.execute(
                                "UPDATE jobs SET last_seen_at = ?, last_verified_at = COALESCE(?, last_verified_at), expires_at = COALESCE(?, expires_at) WHERE id = ?",
                                (now_str, verified_iso, expires_iso, existing_job_id)
                            )
                        cur.execute(
                            """
                            INSERT OR IGNORE INTO job_sources (job_id, source_name, source_job_id, url)
                            VALUES (?, ?, ?, ?)
                            """,
                            (existing_job_id, job.source_name, job.source_job_id, job.apply_url)
                        )
                    else:
                        cur.execute(
                            "UPDATE jobs SET last_seen_at = NOW(), last_verified_at = COALESCE(%s, NOW()), expires_at = COALESCE(%s, expires_at) WHERE id = %s",
                            (verified_iso, expires_iso, existing_job_id)
                        )
                        cur.execute(
                            """
                            INSERT INTO job_sources (job_id, source_name, source_job_id, url)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (job_id, source_name, url) DO NOTHING
                            """,
                            (existing_job_id, job.source_name, job.source_job_id, job.apply_url)
                        )
                else:
                    # 3. Insert new canonical job
                    if self.is_sqlite:
                        cur.execute(
                            """
                            INSERT INTO jobs (
                                normalized_key, title, company, location_raw, city,
                                job_type, posted_date, apply_url, description,
                                source_name, source_job_id, first_seen_at, last_seen_at,
                                expires_at, last_verified_at, is_active
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                            """,
                            (
                                norm_key, job.title, job.company, job.location_raw, job.city,
                                job.job_type, posted_iso, job.apply_url, job.description,
                                job.source_name, job.source_job_id, now_str, now_str,
                                expires_iso, verified_iso
                            )
                        )
                        job_id = cur.lastrowid
                        cur.execute(
                            """
                            INSERT INTO job_sources (job_id, source_name, source_job_id, url)
                            VALUES (?, ?, ?, ?)
                            """,
                            (job_id, job.source_name, job.source_job_id, job.apply_url)
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO jobs (
                                normalized_key, title, company, location_raw, city,
                                job_type, posted_date, apply_url, description,
                                source_name, source_job_id, first_seen_at, last_seen_at,
                                expires_at, last_verified_at, is_active
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), %s, COALESCE(%s, NOW()), TRUE)
                            RETURNING id
                            """,
                            (
                                norm_key, job.title, job.company, job.location_raw, job.city,
                                job.job_type, posted_iso, job.apply_url, job.description,
                                job.source_name, job.source_job_id, expires_iso, verified_iso
                            )
                        )
                        job_id = cur.fetchone()[0]
                        cur.execute(
                            """
                            INSERT INTO job_sources (job_id, source_name, source_job_id, url)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            (job_id, job.source_name, job.source_job_id, job.apply_url)
                        )

                    # Add new job to dedupe index so subsequent jobs in the same batch can match against it
                    dedupe_index.index_job(
                        job_id=job_id, company=job.company, title=job.title,
                        city=job.city, job_type=job.job_type, apply_url=job.apply_url
                    )
                    inserted_count += 1

            conn.commit()
            return inserted_count, duplicates_skipped
        finally:
            if not self._sqlite_mem_conn:
                conn.close()

    def start_pipeline_run(self) -> int:
        """Records the start of a pipeline run, returning its run_id."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            if self.is_sqlite:
                now_str = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    "INSERT INTO pipeline_runs (started_at, status) VALUES (?, 'running')",
                    (now_str,)
                )
                run_id = cur.lastrowid
            else:
                cur.execute(
                    "INSERT INTO pipeline_runs (started_at, status) VALUES (NOW(), 'running') RETURNING id"
                )
                run_id = cur.fetchone()[0]
            conn.commit()
            return run_id
        finally:
            if not self._sqlite_mem_conn:
                conn.close()

    def finish_pipeline_run(self, run_id: int, stats: PipelineRunStats):
        """Updates pipeline run record with final metrics and status."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            summary_json = json.dumps(stats.sources_summary)
            if self.is_sqlite:
                now_str = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    """
                    UPDATE pipeline_runs
                    SET finished_at = ?, status = ?, sources_summary = ?,
                        total_fetched = ?, new_posts = ?, duplicates_skipped = ?,
                        tagged_count = ?, failed_count = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (
                        now_str, stats.status, summary_json, stats.total_fetched,
                        stats.new_posts, stats.duplicates_skipped, stats.tagged_count,
                        stats.failed_count, stats.error_message, run_id
                    )
                )
            else:
                cur.execute(
                    """
                    UPDATE pipeline_runs
                    SET finished_at = NOW(), status = %s, sources_summary = %s::jsonb,
                        total_fetched = %s, new_posts = %s, duplicates_skipped = %s,
                        tagged_count = %s, failed_count = %s, error_message = %s
                    WHERE id = %s
                    """,
                    (
                        stats.status, summary_json, stats.total_fetched,
                        stats.new_posts, stats.duplicates_skipped, stats.tagged_count,
                        stats.failed_count, stats.error_message, run_id
                    )
                )
            conn.commit()
        finally:
            if not self._sqlite_mem_conn:
                conn.close()

    def log_llm_cost(self, run_id: Optional[int], model_name: str, posts_count: int,
                     in_tokens: int, out_tokens: int, cost_usd: float):
        """Logs LLM token usage and cost for analytics."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            if self.is_sqlite:
                now_str = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    """
                    INSERT INTO llm_cost_logs (run_id, model_name, posts_count, input_tokens, output_tokens, cost_usd, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, model_name, posts_count, in_tokens, out_tokens, cost_usd, now_str)
                )
            else:
                cur.execute(
                    """
                    INSERT INTO llm_cost_logs (run_id, model_name, posts_count, input_tokens, output_tokens, cost_usd, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (run_id, model_name, posts_count, in_tokens, out_tokens, cost_usd)
                )
            conn.commit()
        finally:
            if not self._sqlite_mem_conn:
                conn.close()

    def deactivate_expired_jobs(self) -> int:
        """Marks any active job whose expires_at timestamp is in the past as inactive."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            if self.is_sqlite:
                now_str = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    "UPDATE jobs SET is_active = 0 WHERE is_active = 1 AND expires_at IS NOT NULL AND expires_at != '' AND expires_at < ?",
                    (now_str,)
                )
            else:
                cur.execute(
                    "UPDATE jobs SET is_active = FALSE WHERE is_active = TRUE AND expires_at IS NOT NULL AND expires_at < NOW()"
                )
            count = cur.rowcount or 0
            conn.commit()
            return count
        finally:
            if not self._sqlite_mem_conn:
                conn.close()
