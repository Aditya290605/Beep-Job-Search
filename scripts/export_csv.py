"""Export all active fresher jobs from SQLite to CSV."""

import csv
import os
import sqlite3

DB_PATH = os.environ.get("SQLITE_PATH", "test_live.db")
OUTPUT_PATH = "exports/fresher_jobs_india.csv"


def export():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id,
            title,
            company,
            location_raw,
            city,
            job_type,
            role_tag,
            min_exp,
            max_exp,
            source_name,
            apply_url,
            posted_date,
            is_active,
            is_fresher_friendly,
            confidence,
            skills,
            first_seen_at,
            last_seen_at
        FROM jobs
        WHERE is_active = 1
        ORDER BY posted_date DESC, id DESC
    """
    )
    rows = cur.fetchall()

    headers = [
        "job_id",
        "title",
        "company",
        "location_raw",
        "city",
        "job_type",
        "role_tag",
        "min_exp",
        "max_exp",
        "source_name",
        "apply_url",
        "posted_date",
        "is_fresher_friendly",
        "confidence",
        "skills",
        "first_seen_at",
        "last_seen_at",
    ]

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for r in rows:
            writer.writerow(
                [
                    r["id"],
                    r["title"],
                    r["company"],
                    r["location_raw"],
                    r["city"],
                    r["job_type"],
                    r["role_tag"],
                    r["min_exp"],
                    r["max_exp"],
                    r["source_name"],
                    r["apply_url"],
                    r["posted_date"],
                    r["is_fresher_friendly"],
                    f"{r['confidence']:.2f}" if r["confidence"] else "",
                    r["skills"],
                    r["first_seen_at"],
                    r["last_seen_at"],
                ]
            )

    print(f"Exported {len(rows)} active jobs to {OUTPUT_PATH}")
    conn.close()


if __name__ == "__main__":
    export()
