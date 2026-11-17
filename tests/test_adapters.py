"""
tests/test_adapters.py - Unit tests for normalization, adapters, and database deduplication
"""

import unittest
from adapters.base import is_india_location, is_fresher_job, clean_html, extract_job_type
from models import RawJob, generate_normalized_key, PipelineRunStats
from db import Database


class TestAdapterUtilities(unittest.TestCase):

    def test_location_normalization(self):
        # Known Indian tech hubs
        valid, city = is_india_location("Bengaluru, Karnataka, India")
        self.assertTrue(valid)
        self.assertEqual(city, "Bangalore")

        valid, city = is_india_location("Gurgaon, HR")
        self.assertTrue(valid)
        self.assertEqual(city, "Gurugram")

        valid, city = is_india_location("Pune, Maharashtra")
        self.assertTrue(valid)
        self.assertEqual(city, "Pune")

        # Remote options
        valid, city = is_india_location("Remote (India)")
        self.assertTrue(valid)
        self.assertEqual(city, "Remote")

        valid, city = is_india_location("Worldwide Remote")
        self.assertTrue(valid)
        self.assertEqual(city, "Remote")

        # Foreign / Unknown locations
        valid, city = is_india_location("San Francisco, CA, USA")
        self.assertFalse(valid)
        self.assertEqual(city, "Unknown")

        valid, city = is_india_location("")
        self.assertFalse(valid)
        self.assertEqual(city, "Unknown")

    def test_fresher_detector(self):
        self.assertTrue(is_fresher_job("Software Development Engineer Intern"))
        self.assertTrue(is_fresher_job("Graduate Trainee Engineer"))
        self.assertTrue(is_fresher_job("Associate Software Engineer", "Requires 0-1 years of experience."))
        self.assertTrue(is_fresher_job("Junior Backend Developer"))
        
        # Non-fresher jobs
        self.assertFalse(is_fresher_job("Senior Staff Engineer", "10+ years of distributed systems experience."))
        self.assertFalse(is_fresher_job("Lead Architect", "Seeking experienced leader."))

    def test_clean_html(self):
        raw = "<p>Join our <strong>engineering</strong> team!&nbsp;Apply today &amp; grow.</p>"
        cleaned = clean_html(raw)
        self.assertEqual(cleaned, "Join our engineering team! Apply today & grow.")

    def test_normalized_key(self):
        key1 = generate_normalized_key("Razorpay", "SDE Intern", "Bangalore")
        key2 = generate_normalized_key("razorpay ", "sde intern", "bangalore")
        self.assertEqual(key1, "razorpay:sdeintern:bangalore")
        self.assertEqual(key1, key2)


class TestDatabaseOperations(unittest.TestCase):

    def setUp(self):
        # In-memory SQLite for test isolation
        self.db = Database("sqlite:///:memory:")
        self.db.init_db("schema.sql")

    def test_idempotent_insertion_and_deduplication(self):
        job1 = RawJob(
            title="SDE Intern",
            company="Razorpay",
            location_raw="Bangalore",
            city="Bangalore",
            job_type="internship",
            apply_url="https://boards.greenhouse.io/razorpay/jobs/101",
            description="Payments engineering internship",
            source_name="greenhouse",
            source_job_id="101"
        )

        job2 = RawJob(
            title="Frontend Associate",
            company="Cred",
            location_raw="Bangalore",
            city="Bangalore",
            job_type="job",
            apply_url="https://boards.greenhouse.io/cred/jobs/202",
            description="Frontend role for freshers",
            source_name="greenhouse",
            source_job_id="202"
        )

        # 1. Insert two unique jobs
        inserted, dupes = self.db.insert_jobs([job1, job2])
        self.assertEqual(inserted, 2)
        self.assertEqual(dupes, 0)

        # 2. Re-insert job1 from a different source (simulating duplicate on another board)
        duplicate_job1 = RawJob(
            title="SDE Intern",
            company="Razorpay",
            location_raw="Bengaluru",
            city="Bangalore",  # Same normalized city
            job_type="internship",
            apply_url="https://jobicy.com/jobs/999",
            description="Duplicate posting on jobicy",
            source_name="jobicy",
            source_job_id="999"
        )

        inserted_second, dupes_second = self.db.insert_jobs([duplicate_job1])
        self.assertEqual(inserted_second, 0, "Duplicate should not create a new canonical job row")
        self.assertEqual(dupes_second, 1, "Duplicate should be counted as skipped")

        # Verify job_sources records both URLs
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM job_sources")
        sources_count = cur.fetchone()[0]
        self.assertEqual(sources_count, 3, "Both original posts and duplicate source should be linked")
        conn.close()

    def test_pipeline_run_lifecycle(self):
        run_id = self.db.start_pipeline_run()
        self.assertGreater(run_id, 0)

        stats = PipelineRunStats(
            status="success",
            total_fetched=10,
            new_posts=8,
            duplicates_skipped=2,
            tagged_count=8,
            sources_summary={"greenhouse": 5, "lever": 5}
        )
        self.db.finish_pipeline_run(run_id, stats)

        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT status, total_fetched, new_posts FROM pipeline_runs WHERE id = ?", (run_id,))
        row = cur.fetchone()
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["total_fetched"], 10)
        self.assertEqual(row["new_posts"], 8)
        conn.close()


class TestAdapterParsingWithFixtures(unittest.TestCase):

    def test_jobicy_parsing(self):
        sample_jobicy_payload = {
            "jobs": [
                {
                    "id": 1001,
                    "url": "https://jobicy.com/jobs/1001",
                    "jobTitle": "Junior Frontend Engineer",
                    "companyName": "Acme Software",
                    "jobDescription": "<p>Looking for a junior engineer (0-1 yrs exp) with React knowledge.</p>",
                    "jobGeo": "India, Remote",
                    "pubDate": "2026-11-17T10:00:00Z"
                },
                {
                    "id": 1002,
                    "url": "https://jobicy.com/jobs/1002",
                    "jobTitle": "Lead Staff Architect (12+ yrs)",
                    "companyName": "BigCorp",
                    "jobDescription": "<p>Senior leadership position.</p>",
                    "jobGeo": "USA Remote",
                    "pubDate": "2026-11-17T11:00:00Z"
                }
            ]
        }
        
        parsed = []
        for item in sample_jobicy_payload["jobs"]:
            valid_loc, city = is_india_location(item["jobGeo"])
            desc = clean_html(item["jobDescription"])
            if valid_loc and city != "Unknown" and is_fresher_job(item["jobTitle"], desc):
                parsed.append(RawJob(
                    title=item["jobTitle"],
                    company=item["companyName"],
                    location_raw=item["jobGeo"],
                    city=city,
                    job_type=extract_job_type(item["jobTitle"], desc),
                    apply_url=item["url"],
                    description=desc,
                    source_name="jobicy",
                    source_job_id=str(item["id"])
                ))
                
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].title, "Junior Frontend Engineer")
        self.assertEqual(parsed[0].city, "Remote")
        self.assertEqual(parsed[0].job_type, "job")

    def test_greenhouse_parsing(self):
        sample_gh_payload = {
            "jobs": [
                {
                    "id": 2001,
                    "title": "Software Development Engineer - Intern",
                    "location": {"name": "Bengaluru, India"},
                    "content": "<p>6-month internship for pre-final / final year students.</p>",
                    "absolute_url": "https://boards.greenhouse.io/razorpay/jobs/2001",
                    "updated_at": "2026-11-17T09:00:00Z"
                }
            ]
        }
        
        parsed = []
        for item in sample_gh_payload["jobs"]:
            location_raw = (item.get("location") or {}).get("name", "")
            valid_loc, city = is_india_location(location_raw)
            desc = clean_html(item.get("content", ""))
            if valid_loc and city != "Unknown" and is_fresher_job(item["title"], desc):
                parsed.append(RawJob(
                    title=item["title"],
                    company="Razorpay",
                    location_raw=location_raw,
                    city=city,
                    job_type=extract_job_type(item["title"], desc),
                    apply_url=item["absolute_url"],
                    description=desc,
                    source_name="greenhouse",
                    source_job_id=str(item["id"])
                ))
                
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].company, "Razorpay")
        self.assertEqual(parsed[0].city, "Bangalore")
        self.assertEqual(parsed[0].job_type, "internship")


if __name__ == "__main__":
    unittest.main()
