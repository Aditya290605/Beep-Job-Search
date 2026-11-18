"""
backend/tests/test_api.py - Unit tests for API query engine, search, filters & pagination
"""

import sys
import os
import unittest
import json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import RawJob
from app.db import Database
from app.api.queries import (
    search_jobs,
    get_filter_options,
    get_status_summary,
    get_cost_metrics
)


class TestAPIQueries(unittest.TestCase):

    def setUp(self):
        self.db = Database("sqlite:///:memory:")
        schema_path = os.path.join(os.path.dirname(__file__), "..", "app", "schema.sql")
        self.db.init_db(schema_path)

        # Seed test jobs
        now = datetime.now(timezone.utc)
        self.jobs = [
            RawJob(
                title="Software Development Engineer Intern",
                company="Razorpay",
                location_raw="Bengaluru, Karnataka",
                city="Bangalore",
                job_type="internship",
                apply_url="https://boards.greenhouse.io/razorpay/1",
                description="Python, Docker, Backend payments engineering.",
                source_name="greenhouse",
                source_job_id="1",
                posted_date=now.isoformat()
            ),
            RawJob(
                title="Associate Data Scientist",
                company="CRED",
                location_raw="Bangalore",
                city="Bangalore",
                job_type="job",
                apply_url="https://boards.greenhouse.io/cred/2",
                description="SQL, Python, machine learning models.",
                source_name="greenhouse",
                source_job_id="2",
                posted_date=(now - timedelta(days=2)).isoformat()
            ),
            RawJob(
                title="Frontend Developer Intern",
                company="Atlan",
                location_raw="Remote - India",
                city="Remote",
                job_type="internship",
                apply_url="https://lever.co/atlan/3",
                description="React, TypeScript, CSS wireframes.",
                source_name="lever",
                source_job_id="3",
                posted_date=(now - timedelta(days=5)).isoformat()
            ),
            RawJob(
                title="Product Designer Trainee",
                company="Swiggy",
                location_raw="Pune",
                city="Pune",
                job_type="internship",
                apply_url="https://greenhouse.io/swiggy/4",
                description="Figma, UI/UX prototyping.",
                source_name="greenhouse",
                source_job_id="4",
                posted_date=(now - timedelta(days=10)).isoformat()
            ),
            RawJob(
                title="Growth Marketing Associate",
                company="InVideo",
                location_raw="Mumbai",
                city="Mumbai",
                job_type="job",
                apply_url="https://lever.co/invideo/5",
                description="SEO, user acquisition, digital campaigns.",
                source_name="lever",
                source_job_id="5",
                posted_date=(now - timedelta(days=20)).isoformat()
            )
        ]

        self.db.insert_jobs(self.jobs)

        # Simulate enrichment by updating role tags and skills
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE jobs SET role_tag = 'SDE', skills = '[\"Python\", \"Docker\"]', tagged_at = ? WHERE id = 1", (now.isoformat(),))
        cur.execute("UPDATE jobs SET role_tag = 'Data/ML', skills = '[\"SQL\", \"Python\"]', tagged_at = ? WHERE id = 2", (now.isoformat(),))
        cur.execute("UPDATE jobs SET role_tag = 'SDE', skills = '[\"React\", \"TypeScript\"]', tagged_at = ? WHERE id = 3", (now.isoformat(),))
        cur.execute("UPDATE jobs SET role_tag = 'Design', skills = '[\"Figma\", \"UI/UX\"]', tagged_at = ? WHERE id = 4", (now.isoformat(),))
        cur.execute("UPDATE jobs SET role_tag = 'Marketing', skills = '[\"SEO\", \"Campaigns\"]', tagged_at = ? WHERE id = 5", (now.isoformat(),))
        conn.commit()

    def test_search_all_paginated(self):
        res = search_jobs(self.db, page=1, limit=3)
        self.assertEqual(res["total"], 5)
        self.assertEqual(len(res["jobs"]), 3)
        self.assertEqual(res["total_pages"], 2)
        self.assertEqual(res["page"], 1)

    def test_search_by_query_text(self):
        # Search for "React"
        res = search_jobs(self.db, q="React")
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["jobs"][0]["company"], "Atlan")

        # Search for "Razorpay"
        res2 = search_jobs(self.db, q="Razorpay")
        self.assertEqual(res2["total"], 1)
        self.assertEqual(res2["jobs"][0]["title"], "Software Development Engineer Intern")

    def test_filter_by_city(self):
        res = search_jobs(self.db, city="Bangalore")
        self.assertEqual(res["total"], 2)
        for j in res["jobs"]:
            self.assertEqual(j["city"], "Bangalore")

    def test_filter_by_role(self):
        res = search_jobs(self.db, role="SDE")
        self.assertEqual(res["total"], 2)
        for j in res["jobs"]:
            self.assertEqual(j["role_tag"], "SDE")

    def test_filter_by_job_type(self):
        res = search_jobs(self.db, job_type="internship")
        self.assertEqual(res["total"], 3)
        for j in res["jobs"]:
            self.assertEqual(j["job_type"], "internship")

    def test_filter_by_posted_within(self):
        # Only posted in last 24h
        res_24h = search_jobs(self.db, posted_within="24h")
        self.assertGreaterEqual(res_24h["total"], 1)

        # Posted in last 7d
        res_7d = search_jobs(self.db, posted_within="7d")
        self.assertEqual(res_7d["total"], 3)

    def test_filter_options_aggregation(self):
        opts = get_filter_options(self.db)
        self.assertEqual(opts["total_active_jobs"], 5)

        # Check city counts
        cities = {c["name"]: c["count"] for c in opts["cities"]}
        self.assertEqual(cities["Bangalore"], 2)
        self.assertEqual(cities["Remote"], 1)
        self.assertEqual(cities["Pune"], 1)
        self.assertEqual(cities["Mumbai"], 1)

        # Check role counts
        roles = {r["name"]: r["count"] for r in opts["roles"]}
        self.assertEqual(roles["SDE"], 2)
        self.assertEqual(roles["Data/ML"], 1)
        self.assertEqual(roles["Design"], 1)
        self.assertEqual(roles["Marketing"], 1)

    def test_status_summary_and_cost_metrics(self):
        run_id = self.db.start_pipeline_run()
        self.db.log_llm_cost(run_id, "gemini-2.0-flash-lite", posts_count=5, in_tokens=1000, out_tokens=250, cost_usd=0.0002)

        status = get_status_summary(self.db)
        self.assertEqual(status["total_active_jobs"], 5)
        self.assertGreater(len(status["recent_runs"]), 0)

        cost = get_cost_metrics(self.db)
        self.assertEqual(cost["total_posts_tagged"], 5)
        self.assertEqual(cost["total_input_tokens"], 1000)
        self.assertEqual(cost["total_output_tokens"], 250)
        self.assertGreater(cost["cost_per_1000_posts_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
