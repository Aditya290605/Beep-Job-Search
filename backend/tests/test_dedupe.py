"""
backend/tests/test_dedupe.py - Unit tests for Level 1 (Exact) and Level 2 (Fuzzy) Deduplication
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.dedupe import (
    normalize_company,
    normalize_title,
    is_duplicate_pair,
    DeduplicationIndex
)
from app.models import RawJob
from app.db import Database


class TestDedupeEngine(unittest.TestCase):

    def test_company_normalization(self):
        self.assertEqual(normalize_company("Razorpay Software Private Limited"), "razorpay")
        self.assertEqual(normalize_company("Dreamplug Technologies (CRED)"), "cred")
        self.assertEqual(normalize_company("Atlan India Pvt Ltd"), "atlan")
        self.assertEqual(normalize_company("Swiggy Technologies"), "swiggy")
        self.assertEqual(normalize_company("Hewlett Packard Enterprise"), "hpe")

    def test_discipline_and_cohort_guardrails(self):
        # Google Software Engineering PhD Intern vs Silicon Engineering Intern, PhD must NEVER merge
        is_dupe, reason = is_duplicate_pair(
            job1_company="Google",
            job1_title="Software Engineering PhD Intern, Summer 2027",
            job1_city="Bangalore",
            job1_type="internship",
            job2_company="Google",
            job2_title="Silicon Engineering Intern, PhD, Summer 2027",
            job2_city="Bangalore",
            job2_type="internship"
        )
        self.assertFalse(is_dupe, f"Must not merge Software and Silicon PhD interns: {reason}")

        # Different cohort years (2024 vs 2027) must NOT merge
        is_dupe2, _ = is_duplicate_pair(
            job1_company="NXP",
            job1_title="Technical Internship 2027",
            job1_city="Bangalore",
            job1_type="internship",
            job2_company="NXP",
            job2_title="Technical Internship 2024",
            job2_city="Bangalore",
            job2_type="internship"
        )
        self.assertFalse(is_dupe2)

    def test_title_normalization(self):
        norm1 = normalize_title("SDE Intern - 2026")
        self.assertEqual(norm1, "software development engineer intern 2026")

        norm2 = normalize_title("Junior SWE (Frontend)")
        self.assertEqual(norm2, "junior software engineer frontend")

    def test_near_duplicate_matching(self):
        # Case 1: Same company variation, abbreviation title variation, same city
        is_dupe, reason = is_duplicate_pair(
            job1_company="Razorpay",
            job1_title="SDE Intern",
            job1_city="Bangalore",
            job1_type="internship",
            job2_company="Razorpay Software Pvt Ltd",
            job2_title="Software Development Engineer - Intern",
            job2_city="Bangalore",
            job2_type="internship"
        )
        self.assertTrue(is_dupe, f"Expected duplicate, got: {reason}")

        # Case 2: Word-order swap
        is_dupe, reason = is_duplicate_pair(
            job1_company="Atlan",
            job1_title="Associate Frontend Engineer",
            job1_city="Remote",
            job1_type="job",
            job2_company="Atlan India",
            job2_title="Frontend Engineer - Associate",
            job2_city="Remote",
            job2_type="job"
        )
        self.assertTrue(is_dupe, f"Expected duplicate, got: {reason}")

    def test_guardrails_prevent_false_merges(self):
        # Guardrail 1: Different cities must NEVER match
        is_dupe, reason = is_duplicate_pair(
            job1_company="Swiggy",
            job1_title="Backend Intern",
            job1_city="Bangalore",
            job1_type="internship",
            job2_company="Swiggy",
            job2_title="Backend Intern",
            job2_city="Pune",
            job2_type="internship"
        )
        self.assertFalse(is_dupe)
        self.assertIn("Different cities", reason)

        # Guardrail 2: Internship vs Full-Time must NEVER match
        is_dupe, reason = is_duplicate_pair(
            job1_company="CRED",
            job1_title="Frontend Engineer",
            job1_city="Bangalore",
            job1_type="job",
            job2_company="CRED",
            job2_title="Frontend Engineer",
            job2_city="Bangalore",
            job2_type="internship"
        )
        self.assertFalse(is_dupe)
        self.assertIn("Different job types", reason)

        # Guardrail 3: Different levels (e.g. SDE 1 vs SDE 2) must NEVER match
        is_dupe, reason = is_duplicate_pair(
            job1_company="Postman",
            job1_title="Software Engineer I",
            job1_city="Bangalore",
            job1_type="job",
            job2_company="Postman",
            job2_title="Software Engineer II",
            job2_city="Bangalore",
            job2_type="job"
        )
        self.assertFalse(is_dupe)
        self.assertIn("Different seniority numerals", reason)


class TestDatabaseFuzzyDeduplication(unittest.TestCase):

    def setUp(self):
        self.db = Database("sqlite:///:memory:")
        schema_path = os.path.join(os.path.dirname(__file__), "..", "app", "schema.sql")
        self.db.init_db(schema_path)

    def test_database_fuzzy_dedupe_across_sources(self):
        # 1. First job from Greenhouse
        job_greenhouse = RawJob(
            title="SDE Intern",
            company="Razorpay",
            location_raw="Bangalore",
            city="Bangalore",
            job_type="internship",
            apply_url="https://boards.greenhouse.io/razorpay/jobs/5001",
            description="Greenhouse listing",
            source_name="greenhouse",
            source_job_id="5001"
        )

        inserted, dupes = self.db.insert_jobs([job_greenhouse])
        self.assertEqual(inserted, 1)
        self.assertEqual(dupes, 0)

        # 2. Near-duplicate job from Jobicy with company suffix & expanded title
        # Exact normalized_key would differ, but fuzzy match should catch it!
        job_jobicy = RawJob(
            title="Software Development Engineer - Intern",
            company="Razorpay Software Private Limited",
            location_raw="Bangalore, India",
            city="Bangalore",
            job_type="internship",
            apply_url="https://jobicy.com/jobs/9999",
            description="Jobicy syndication listing",
            source_name="jobicy",
            source_job_id="9999"
        )

        inserted_2, dupes_2 = self.db.insert_jobs([job_jobicy])
        self.assertEqual(inserted_2, 0, "Fuzzy near-duplicate must NOT create a new row in jobs")
        self.assertEqual(dupes_2, 1, "Fuzzy near-duplicate must be counted as skipped")

        # 3. Verify only 1 canonical job exists in database
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM jobs")
        job_count = cur.fetchone()[0]
        self.assertEqual(job_count, 1)

        # 4. Verify BOTH source URLs are linked in job_sources
        cur.execute("SELECT source_name, url FROM job_sources ORDER BY source_name")
        sources = cur.fetchall()
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]["source_name"], "greenhouse")
        self.assertEqual(sources[1]["source_name"], "jobicy")
        conn.close()


if __name__ == "__main__":
    unittest.main()
