"""Enrich sparse skills (< 3 skills) with relevant role fundamentals."""

import json
import sqlite3

DB_PATH = "test_live.db"

ROLE_CORE_SKILLS = {
    "SDE": ["Algorithms", "Data Structures", "Problem Solving", "Git"],
    "Data/ML": ["Python", "SQL", "Data Analysis", "Statistical Modeling"],
    "Design": ["UI/UX Design", "Figma", "Wireframing", "User Research"],
    "Marketing": ["Digital Marketing", "Content Strategy", "Social Media", "Communication"],
    "Sales": ["Client Communication", "Market Research", "Lead Generation", "CRM"],
    "Ops": ["Operations Management", "Process Optimization", "Cross-Functional Collaboration", "Problem Solving"],
    "HR": ["Talent Sourcing", "Interview Coordination", "Candidate Screening", "Communication"],
    "Finance": ["Financial Analysis", "Advanced Excel", "Accounting Principles", "Data Verification"],
    "Other": ["Analytical Thinking", "Problem Solving", "Communication", "Team Collaboration"],
}


def enrich():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT id, title, role_tag, skills FROM jobs")
    rows = cur.fetchall()

    updated = 0
    for jid, title, role, skills_json in rows:
        try:
            skills = json.loads(skills_json) if skills_json else []
        except:
            skills = []

        if len(skills) < 4:
            role_key = role if role in ROLE_CORE_SKILLS else "Other"
            supplements = ROLE_CORE_SKILLS[role_key]
            for s in supplements:
                if s not in skills and len(skills) < 5:
                    skills.append(s)
            cur.execute("UPDATE jobs SET skills = ? WHERE id = ?", (json.dumps(skills), jid))
            updated += 1

    conn.commit()
    print(f"Enriched {updated} jobs with core competency skills.")

    # Re-sync mock-data.js
    cur.execute(
        """
        SELECT
            id, normalized_key, title, company, location_raw, city,
            job_type, posted_date, apply_url, description, source_name,
            source_job_id, first_seen_at, last_seen_at, is_active,
            role_tag, is_fresher_friendly, min_exp, max_exp, skills, confidence
        FROM jobs
        ORDER BY posted_date DESC, id DESC
    """
    )
    cols = [
        "id", "normalized_key", "title", "company", "location_raw", "city",
        "job_type", "posted_date", "apply_url", "description", "source_name",
        "source_job_id", "first_seen_at", "last_seen_at", "is_active",
        "role_tag", "is_fresher_friendly", "min_exp", "max_exp", "skills", "confidence"
    ]
    all_jobs = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        try:
            d["skills"] = json.loads(d["skills"]) if d["skills"] else []
        except:
            d["skills"] = []
        d["is_fresher_friendly"] = bool(d["is_fresher_friendly"])
        all_jobs.append(d)

    with open("frontend/assets/mock-data.js", "w", encoding="utf-8") as f:
        f.write("// Auto-synced from test_live.db\n")
        f.write(f"window.__MOCK_JOBS__ = {json.dumps(all_jobs, indent=2)};\n")

    print(f"Updated frontend/assets/mock-data.js with {len(all_jobs)} enriched jobs.")
    conn.close()


if __name__ == "__main__":
    enrich()
