"""
backend/tests/test_tagger.py - Unit tests for Vertex AI LLM Tagger & Cost Tracking
"""

import sys
import os
import json
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.tagger import (
    calculate_llm_cost,
    build_tagging_payload,
    heuristic_fallback_tagger,
    enrich_untagged_jobs
)
from app.models import RawJob
from app.db import Database


class TestLLMTagger(unittest.TestCase):

    def test_cost_calculation(self):
        # Default model is gemini-3.5-flash-lite ($0.30/1M in, $2.50/1M out) -> $2.80 for 1M+1M
        cost_1m = calculate_llm_cost(1_000_000, 1_000_000)
        self.assertAlmostEqual(cost_1m, 2.80, places=4)

        # gemini-2.5-flash-lite ($0.10/1M in, $0.40/1M out) -> $0.50 for 1M+1M
        cost_25 = calculate_llm_cost(1_000_000, 1_000_000, model_name="gemini-2.5-flash-lite")
        self.assertAlmostEqual(cost_25, 0.50, places=4)

        # Batch of 8 posts on default model
        batch_cost = calculate_llm_cost(8_000, 960)
        expected = (8000 * 0.30 + 960 * 2.50) / 1_000_000
        self.assertAlmostEqual(batch_cost, round(expected, 6), places=6)

    def test_build_payload(self):
        sample_jobs = [
            {
                "id": 1,
                "title": "Backend Intern",
                "company": "CRED",
                "location_raw": "Bangalore",
                "city": "Bangalore",
                "job_type": "internship",
                "description": "Looking for Go/Python developers."
            }
        ]
        payload_str = build_tagging_payload(sample_jobs)
        payload = json.loads(payload_str)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], 1)
        self.assertEqual(payload[0]["title"], "Backend Intern")
        self.assertIn("Go/Python", payload[0]["description"])
        # Ensure description is NOT duplicated under description_snippet
        self.assertNotIn("description_snippet", payload[0])

    def test_heuristic_taxonomy_classification(self):
        test_posts = [
            {"id": 101, "title": "Software Development Engineer Intern", "description": "Writing code in Python and React"},
            {"id": 102, "title": "Data Analyst Trainee", "description": "SQL and dashboards"},
            {"id": 103, "title": "Product Designer Intern", "description": "Figma and user wireframes"},
            {"id": 104, "title": "Growth Marketing Associate", "description": "SEO, campaigns and analytics"},
            {"id": 105, "title": "Talent Acquisition Trainee", "description": "HR recruiting for freshers"}
        ]
        results = heuristic_fallback_tagger(test_posts)
        self.assertEqual(results[0]["role"], "SDE")
        self.assertIn("Python", results[0]["skills"])
        self.assertEqual(results[1]["role"], "Data/ML")
        self.assertIn("SQL", results[1]["skills"])
        self.assertEqual(results[2]["role"], "Design")
        self.assertIn("Figma", results[2]["skills"])
        self.assertEqual(results[3]["role"], "Marketing")
        self.assertEqual(results[4]["role"], "HR")


class TestDatabaseEnrichmentAndCostLogging(unittest.TestCase):

    def setUp(self):
        self.db = Database("sqlite:///:memory:")
        schema_path = os.path.join(os.path.dirname(__file__), "..", "app", "schema.sql")
        self.db.init_db(schema_path)

    def test_enrich_untagged_jobs_and_cost_logging(self):
        # 1. Insert 2 untagged jobs
        job1 = RawJob(
            title="Software Development Engineer Intern",
            company="Razorpay",
            location_raw="Bangalore",
            city="Bangalore",
            job_type="internship",
            apply_url="https://boards.greenhouse.io/razorpay/1",
            description="Work with Python, Docker, and AWS.",
            source_name="greenhouse",
            source_job_id="1"
        )
        job2 = RawJob(
            title="Data Science Intern",
            company="Postman",
            location_raw="Bangalore",
            city="Bangalore",
            job_type="internship",
            apply_url="https://boards.greenhouse.io/postman/2",
            description="Machine learning and SQL data pipelines.",
            source_name="greenhouse",
            source_job_id="2"
        )
        self.db.insert_jobs([job1, job2])

        # 2. Enrich untagged jobs
        run_id = self.db.start_pipeline_run()
        tagged_count = enrich_untagged_jobs(self.db, run_id=run_id, batch_size=2)
        self.assertEqual(tagged_count, 2)

        # 3. Verify jobs in DB are now enriched
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, title, role_tag, skills, tagged_at, is_active FROM jobs ORDER BY id")
        rows = cur.fetchall()
        self.assertEqual(len(rows), 2)
        
        # Razorpay job
        self.assertEqual(rows[0]["role_tag"], "SDE")
        self.assertIsNotNone(rows[0]["tagged_at"])
        skills_1 = json.loads(rows[0]["skills"])
        self.assertIn("Python", skills_1)

        # Postman job
        self.assertEqual(rows[1]["role_tag"], "Data/ML")
        skills_2 = json.loads(rows[1]["skills"])
        self.assertIn("SQL", skills_2)

        # 4. Verify heuristic fallback logs cleanly with $0.00 cost & heuristic_fallback model_name
        cur.execute("SELECT model_name, posts_count, input_tokens, output_tokens, cost_usd FROM llm_cost_logs WHERE run_id = ?", (run_id,))
        cost_row = cur.fetchone()
        self.assertIsNotNone(cost_row)
        self.assertEqual(cost_row["posts_count"], 2)
        self.assertEqual(cost_row["model_name"], "heuristic_fallback")
        self.assertEqual(cost_row["cost_usd"], 0.0)
        conn.close()

    def test_deactivates_unknown_city_jobs(self):
        # Insert a job
        job = RawJob(
            title="Software Trainee",
            company="MysteryCorp",
            location_raw="Unknown Location",
            city="Remote",
            job_type="job",
            apply_url="https://example.com/job",
            description="Mystery job",
            source_name="test",
            source_job_id="10"
        )
        self.db.insert_jobs([job])

        # Custom mock tagger returning city='Unknown'
        def mock_unknown_tagger(batch):
            return [{"id": batch[0]["id"], "role": "SDE", "city": "Unknown", "is_fresher_friendly": True, "min_exp": 0, "max_exp": 1, "skills": [], "confidence": 0.4}], 100, 50, 0.00003

        enrich_untagged_jobs(self.db, run_id=1, batch_size=1, tagger_fn=mock_unknown_tagger)

        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT city, is_active FROM jobs WHERE id = 1")
        row = cur.fetchone()
        self.assertEqual(row["city"], "Unknown")
        self.assertEqual(row["is_active"], 0, "Jobs with Unknown city must be deactivated")
        conn.close()

    def test_spelled_out_senior_exp_and_hardware_and_expiry_and_url_dedupe(self):
        from app.adapters.base import is_fresher_job, clean_html
        from app.api.queries import search_jobs

        # 1. Spelled-out senior years ("Five or more years") rejected
        self.assertFalse(is_fresher_job(
            "Identity Security Engineer",
            "WHAT'S REQUIRED: Five or more years in security engineering, with at least three years in IAM."
        ))

        # 2. Double-escaped HTML cleaned properly
        self.assertEqual(clean_html("&lt;p&gt;Hello &amp;amp; World&lt;/p&gt;"), "Hello & World")

        # 3. Hardware job classified as Hardware (NOT SDE) with no fake DSA padding
        hw = heuristic_fallback_tagger([{
            "id": 99,
            "title": "Hardware Design Engineer Intern",
            "description": "PCB Design, Motherboard Architecture, Verilog, SPICE, Oscilloscope, I2C, SPI"
        }])[0]
        self.assertEqual(hw["role"], "Hardware")
        self.assertIn("PCB Design", hw["skills"])
        self.assertNotIn("Data Structures", hw["skills"])

        # 4. Exact URL deduplication across slightly different company names
        j1 = RawJob(title="Analyst", company="AQR Capital", location_raw="Bangalore", city="Bangalore", job_type="job", apply_url="https://example.com/same-job", description="Fresher role", source_name="gh", source_job_id="1")
        j2 = RawJob(title="Analyst", company="AQR Capital Management", location_raw="Bangalore", city="Bangalore", job_type="job", apply_url="https://example.com/same-job", description="Fresher role", source_name="git", source_job_id="2")
        ins, dupes = self.db.insert_jobs([j1, j2])
        self.assertEqual(ins, 1)
        self.assertEqual(dupes, 1)

        # 5. Expired job automatically deactivated on load
        j_exp = RawJob(title="Old Intern", company="Acme", location_raw="Pune", city="Pune", job_type="internship", apply_url="https://example.com/old", description="Intern", source_name="wd", source_job_id="3", expires_at="2020-01-01T00:00:00+00:00")
        self.db.insert_jobs([j_exp])
        res = search_jobs(self.db, q="Old Intern")
        self.assertEqual(res["total"], 0)


if __name__ == "__main__":
    unittest.main()
