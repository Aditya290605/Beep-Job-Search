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
            else:
                cur.execute(ddl)
            conn.commit()
            logger.info("Database initialized successfully.")
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

                # 1. Level 1: Exact match on normalized_key
                if self.is_sqlite:
                    cur.execute("SELECT id FROM jobs WHERE normalized_key = ?", (norm_key,))
                    existing = cur.fetchone()
                else:
                    cur.execute("SELECT id FROM jobs WHERE normalized_key = %s", (norm_key,))
                    existing = cur.fetchone()

                existing_job_id = None
                if existing:
                    existing_job_id = existing[0] if isinstance(existing, tuple) else existing["id"]
                else:
                    # 2. Level 2: Fuzzy near-duplicate match (rapidfuzz / difflib)
                    fuzzy_match_id = dedupe_index.find_duplicate(job)
                    if fuzzy_match_id:
                        existing_job_id = fuzzy_match_id

                if existing_job_id:
                    duplicates_skipped += 1
                    # Link duplicate source URL to canonical job
                    if self.is_sqlite:
                        cur.execute(
                            """
                            INSERT OR IGNORE INTO job_sources (job_id, source_name, source_job_id, url)
                            VALUES (?, ?, ?, ?)
                            """,
                            (existing_job_id, job.source_name, job.source_job_id, job.apply_url)
                        )
                    else:
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
                    now_str = datetime.now(timezone.utc).isoformat()
                    if self.is_sqlite:
                        cur.execute(
                            """
                            INSERT INTO jobs (
                                normalized_key, title, company, location_raw, city,
                                job_type, posted_date, apply_url, description,
                                source_name, source_job_id, first_seen_at, last_seen_at, is_active
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                            """,
                            (
                                norm_key, job.title, job.company, job.location_raw, job.city,
                                job.job_type, job.posted_date or now_str, job.apply_url, job.description,
                                job.source_name, job.source_job_id, now_str, now_str
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
                                source_name, source_job_id, first_seen_at, last_seen_at, is_active
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), TRUE)
                            RETURNING id
                            """,
                            (
                                norm_key, job.title, job.company, job.location_raw, job.city,
                                job.job_type, job.posted_date, job.apply_url, job.description,
                                job.source_name, job.source_job_id
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
