"""Re-evaluates all jobs in SQLite database:
1. Filters out and deactivates any jobs that mention 2+ years of experience or senior roles.
2. Uses Gemini 3.5 Flash Lite with full 2,500-character descriptions to extract genuine skills.
3. Re-syncs mock-data.js and exports.
"""

import json
import logging
import os
import re
import sqlite3
import time
from typing import List, Dict, Any

from app import config
from app.adapters.base import SENIOR_REGEX, FRESHER_REGEX
from app.tagger import _call_gemini_rest_api, calculate_llm_cost

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = "test_live.db"


def clean_database():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT id, title, company, description, is_active FROM jobs")
    rows = cur.fetchall()

    deactivated = 0
    active_fresher_ids = []

    exp_pattern = re.compile(
        r"\b(?:2|3|4|5|6|7|8|9|10)\s*[-–to]+\s*\d+\s*(?:yr|year|years|yrs)\b|"
        r"\b(?:2|3|4|5|6|7|8|9|10)\+?\s*(?:yr|year|years|yrs)\s*(?:of\s*)?exp\b|"
        r"\b(?:2|3|4|5|6|7|8|9|10)\s*\+\s*(?:yr|year|years|yrs)\b|"
        r"\b(?:minimum|at least)\s+(?:of\s+)?(?:2|3|4|5|6|7|8|9|10)\s*(?:yr|year|years|yrs)\b",
        re.I
    )

    for r in rows:
        jid = r["id"]
        title = r["title"]
        desc = r["description"] or ""
        sample = f"{title} {desc}"

        is_senior_title = bool(SENIOR_REGEX.search(title))
        has_senior_exp = bool(exp_pattern.search(sample))

        if is_senior_title or has_senior_exp:
            # Mark as not fresher and deactivate
            cur.execute(
                "UPDATE jobs SET is_fresher_friendly = 0, is_active = 0, min_exp = 2 WHERE id = ?",
                (jid,)
            )
            deactivated += 1
            logger.info(f"Deactivated non-fresher job #{jid}: {r['company']} - {title}")
        else:
            active_fresher_ids.append(jid)

    conn.commit()
    conn.close()
    logger.info(f"Audit complete: Deactivated {deactivated} non-fresher jobs. {len(active_fresher_ids)} genuine fresher jobs remaining.")
    return active_fresher_ids


def re_tag_fresher_jobs(fresher_ids: List[int], batch_size: int = 15):
    api_key = config.GEMINI_API_KEY
    if not api_key:
        logger.error("GEMINI_API_KEY not configured!")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    placeholders = ",".join("?" * len(fresher_ids))
    cur.execute(
        f"""
        SELECT id, title, company, location_raw, city, job_type, description
        FROM jobs
        WHERE id IN ({placeholders})
        ORDER BY id ASC
        """,
        fresher_ids
    )
    jobs_to_tag = [dict(r) for r in cur.fetchall()]
    conn.close()

    logger.info(f"Sending {len(jobs_to_tag)} jobs to Gemini 3.5 Flash Lite with full 2,500-char descriptions...")

    total_tagged = 0
    total_cost = 0.0

    for i in range(0, len(jobs_to_tag), batch_size):
        batch = jobs_to_tag[i:i + batch_size]
        batch_num = i // batch_size + 1
        logger.info(f"Tagging batch {batch_num} ({len(batch)} jobs)...")

        results = None
        for attempt in range(3):
            try:
                results, in_tok, out_tok, cost_usd = _call_gemini_rest_api(
                    batch,
                    model_name="gemini-3.5-flash-lite",
                    api_key=api_key
                )
                break
            except Exception as e:
                logger.warning(f"Batch {batch_num} attempt {attempt + 1} error: {e}")
                time.sleep(3.0 * (attempt + 1))

        if not results:
            logger.error(f"Batch {batch_num} failed across all retries, skipping...")
            continue

        total_cost += cost_usd
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        for item in results:
            jid = item["id"]
            role = item.get("role", "Other")
            city = item.get("city", "Remote")
            is_fresher = 1 if item.get("is_fresher_friendly", True) else 0
            min_exp = item.get("min_exp", 0)
            max_exp = item.get("max_exp", 1)
            skills = item.get("skills", [])
            conf = float(item.get("confidence", 0.95))

            # Deactivate if Gemini flagged 2+ years experience
            is_active = 0 if (not is_fresher or min_exp >= 2 or city == "Unknown") else 1

            cur.execute(
                """
                UPDATE jobs
                SET role_tag = ?, city = ?, is_fresher_friendly = ?,
                    min_exp = ?, max_exp = ?, skills = ?, confidence = ?,
                    is_active = ?
                WHERE id = ?
                """,
                (role, city, is_fresher, min_exp, max_exp, json.dumps(skills), conf, is_active, jid)
            )

        cur.execute(
            """
            INSERT INTO llm_cost_logs (model_name, posts_count, input_tokens, output_tokens, cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            ("gemini-3.5-flash-lite", len(batch), in_tok, out_tok, cost_usd)
        )
        conn.commit()
        conn.close()

        total_tagged += len(results)
        time.sleep(1.0)

    logger.info(f"Re-tagging complete! Tagged {total_tagged} jobs. Total LLM Cost: ${total_cost:.5f}")


def sync_all_exports():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM jobs ORDER BY posted_date DESC, id DESC")
    all_jobs = []
    for r in cur.fetchall():
        d = dict(r)
        try:
            d["skills"] = json.loads(d["skills"]) if d["skills"] else []
        except:
            d["skills"] = []
        d["is_fresher_friendly"] = bool(d["is_fresher_friendly"])
        all_jobs.append(d)

    with open("frontend/assets/mock-data.js", "w", encoding="utf-8") as f:
        f.write("// Auto-synced from test_live.db\n")
        f.write(f"window.__MOCK_JOBS__ = {json.dumps(all_jobs, indent=2)};\n")

    # Update backend/jobs.db as well
    import shutil
    shutil.copyfile("test_live.db", "backend/jobs.db")

    conn.close()
    logger.info("Synced mock-data.js and backend/jobs.db.")


if __name__ == "__main__":
    fresher_ids = clean_database()
    re_tag_fresher_jobs(fresher_ids, batch_size=15)
    sync_all_exports()
