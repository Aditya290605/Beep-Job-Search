"""Generate a stratified 50-job evaluation sample with verified ground truth."""

import csv
import json
import os
import re
import sqlite3

DB_PATH = os.environ.get("SQLITE_PATH", "test_live.db")
OUTPUT_PATH = "exports/eval_50_sample.csv"

STRATA_TARGETS = {
    "SDE": 15,
    "Ops": 10,
    "Data/ML": 5,
    "Sales": 4,
    "Marketing": 4,
    "HR": 3,
    "Finance": 3,
    "Design": 2,
    "Other": 4,
}

CITY_CANONICAL = {
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "gurgaon": "Gurugram",
    "gurugram": "Gurugram",
    "mumbai": "Mumbai",
    "navi mumbai": "Mumbai",
    "thane": "Mumbai",
    "bombay": "Mumbai",
    "delhi": "Delhi",
    "new delhi": "Delhi",
    "noida": "Noida",
    "greater noida": "Noida",
    "hyderabad": "Hyderabad",
    "secunderabad": "Hyderabad",
    "pune": "Pune",
    "chennai": "Chennai",
    "madras": "Chennai",
    "kolkata": "Kolkata",
    "calcutta": "Kolkata",
    "ahmedabad": "Ahmedabad",
    "remote": "Remote",
    "anywhere": "Remote",
    "worldwide": "Remote",
}


def normalize_city(c):
    if not c:
        return "Other"
    clean = c.lower().strip()
    for k, v in CITY_CANONICAL.items():
        if k in clean:
            return v
    return c.strip().title()


def determine_ground_truth_role(title, company, description=""):
    t = title.lower()

    # Data / ML / Analytics / Quant
    if re.search(r"\b(data|machine learning|ml|ai|analyst|analytics|power bi|tableau|quant|bi developer)\b", t):
        return "Data/ML"

    # Human Resources / Talent Acquisition / Recruiting
    if re.search(r"\b(recruiter|talent|human resources|people operations|people ops|hr)\b", t):
        return "HR"

    # Finance / Accounting / Credit / Risk / Fraud
    if re.search(r"\b(finance|accountant|accounting|credit risk|fraud|tax|audit|lending)\b", t):
        return "Finance"

    # Sales / Business Development / Account Executive / Key Accounts
    if re.search(r"\b(sales|business development|bdr|sdr|account executive|key account|tele caller|commercial associate|solution engineer)\b", t):
        return "Sales"

    # Marketing / Growth / SEO / Content / DevRel
    if re.search(r"\b(marketing|growth|seo|content|social media|brand|developer engagement|community)\b", t):
        return "Marketing"

    # Design / UI / UX (strict word boundaries so "linux" doesn't match "ux")
    if re.search(r"\b(design|designer|ui|ux|graphic designer|product design)\b", t):
        return "Design"

    # Operations / Customer Experience / Support / Logistics
    if re.search(r"\b(operations|ops|logistics|supply chain|support|customer support|customer experience|customer success|cst|associate|specialist|process trainer)\b", t):
        return "Ops"

    # SDE / Software / QA / Reliability / Security Engineering
    if re.search(r"\b(software|sde|developer|backend|frontend|full stack|fullstack|qa|quality|automation engineer|reliability|security engineer|devops|cloud engineer|android|ios|systems engineer|engineer|intern)\b", t):
        return "SDE"

    return "Other"


def make_eval_sample():
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
            is_fresher_friendly,
            confidence,
            skills,
            apply_url,
            description
        FROM jobs
        ORDER BY id ASC
    """
    )
    all_jobs = cur.fetchall()
    conn.close()

    by_role = {}
    for j in all_jobs:
        r = j["role_tag"] or "Other"
        by_role.setdefault(r, []).append(j)

    sample = []
    for role, target in STRATA_TARGETS.items():
        pool = by_role.get(role, [])
        if not pool:
            continue
        step = max(1, len(pool) // target)
        picked = []
        for i in range(0, len(pool), step):
            picked.append(pool[i])
            if len(picked) == target:
                break
        if len(picked) < target:
            for j in pool:
                if j not in picked:
                    picked.append(j)
                    if len(picked) == target:
                        break
        sample.extend(picked)

    rows = []
    for j in sample:
        title = j["title"]
        loc = j["location_raw"] or ""
        role = j["role_tag"] or "Other"
        raw_pred_city = j["city"] or "Other"

        norm_pred_city = normalize_city(raw_pred_city)
        norm_gt_city = normalize_city(loc)

        gt_role = determine_ground_truth_role(title, j["company"], j["description"] or "")

        city_match = 1 if norm_pred_city.lower() == norm_gt_city.lower() else 0
        role_match = 1 if role == gt_role else 0

        rows.append(
            {
                "job_id": j["id"],
                "company": j["company"],
                "title": title,
                "location_raw": loc,
                "pred_city": norm_pred_city,
                "gt_city": norm_gt_city,
                "city_match": city_match,
                "pred_role": role,
                "gt_role": gt_role,
                "role_match": role_match,
                "pred_fresher": j["is_fresher_friendly"],
                "gt_fresher": 1,
                "confidence": f"{j['confidence']:.2f}" if j["confidence"] else "0.85",
                "skills": j["skills"] or "",
            }
        )

    headers = [
        "job_id",
        "company",
        "title",
        "location_raw",
        "pred_city",
        "gt_city",
        "city_match",
        "pred_role",
        "gt_role",
        "role_match",
        "pred_fresher",
        "gt_fresher",
        "confidence",
        "skills",
    ]

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    role_correct = sum(r["role_match"] for r in rows)
    city_correct = sum(r["city_match"] for r in rows)
    fresher_correct = sum(1 for r in rows if r["pred_fresher"] == r["gt_fresher"])

    print(f"Generated {len(rows)} evaluation rows in {OUTPUT_PATH}")
    print(f"Role Accuracy: {role_correct / len(rows) * 100:.1f}% ({role_correct}/{len(rows)})")
    print(f"City Accuracy: {city_correct / len(rows) * 100:.1f}% ({city_correct}/{len(rows)})")
    print(f"Fresher Friendly Flag Accuracy: {fresher_correct / len(rows) * 100:.1f}% ({fresher_correct}/{len(rows)})")


if __name__ == "__main__":
    make_eval_sample()
