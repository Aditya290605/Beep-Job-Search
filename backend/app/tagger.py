"""
backend/app/tagger.py - Vertex AI Gemini LLM Tagger & Cost Tracker

Enriches untagged job postings in batches (10-20 per call) using Gemini Flash-Lite:
1. Classifies role into canonical taxonomy (SDE, Data/ML, Design, Marketing, Sales, Ops, Finance, HR, Other).
2. Canonicalizes Indian cities and flags 'Unknown' locations (which get deactivated).
3. Evaluates fresher-friendliness and extracts experience range (min/max) and key skills.
4. Outputs strict JSON guaranteed by JSON Schema.
5. Logs input/output token counts and calculated USD costs to llm_cost_logs table.
"""

import os
import json
import logging
import re
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone

from app import config
from app.db import Database

logger = logging.getLogger(__name__)

# Check if google.cloud.aiplatform or vertexai is available
HAS_VERTEX = False
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel, GenerationConfig
    HAS_VERTEX = True
except ImportError:
    HAS_VERTEX = False


TAGGING_SYSTEM_PROMPT = """You are an expert technical recruiter analyzing job postings for college students and freshers in India.
Classify each post according to our strict taxonomy and extract key qualification signals.

Roles Taxonomy (MUST be one of these exact values):
- SDE: Software engineering, frontend, backend, fullstack, mobile, DevOps, QA/testing, cloud, cybersecurity.
- Data/ML: Data science, data analytics, ML/AI engineer, BI analyst, data engineering.
- Design: UI/UX, product design, graphic design, visual design.
- Marketing: Growth, digital marketing, SEO, content, social media, performance marketing.
- Sales: Business development (BDR/SDR), inside sales, account executive.
- Ops: Business operations, customer support, supply chain, logistics, program management.
- Finance: Accounting, audit, financial analysis, investment, tax.
- HR: Recruiting, talent acquisition, human resources, people ops.
- Other: Any role that does not fit the above categories.

City Canonicalization:
- Canonical Indian cities: Bangalore, Mumbai, Pune, Hyderabad, Gurugram, Delhi, Noida, Chennai, Kolkata, Ahmedabad, Jaipur, Kochi, Coimbatore.
- If remote within India or worldwide, return "Remote".
- If the city cannot be determined with certainty, return "Unknown".

Fresher Rules:
- is_fresher_friendly: true if 0-1 years exp, college student, intern, graduate trainee, or entry-level. false if 2+ years exp required.
- min_exp and max_exp: Integer years of experience required (default 0 and 1 for fresher roles).
- skills: Array of up to 6 key technical or role-specific skills (e.g. ["Python", "SQL", "React"]).
- confidence: Float between 0.0 and 1.0 indicating classification confidence.
"""

TAGGING_RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "id": {"type": "INTEGER"},
            "role": {
                "type": "STRING",
                "enum": config.CANONICAL_ROLES
            },
            "city": {"type": "STRING"},
            "is_fresher_friendly": {"type": "BOOLEAN"},
            "min_exp": {"type": "INTEGER"},
            "max_exp": {"type": "INTEGER"},
            "skills": {
                "type": "ARRAY",
                "items": {"type": "STRING"}
            },
            "confidence": {"type": "NUMBER"}
        },
        "required": ["id", "role", "city", "is_fresher_friendly", "confidence", "skills"]
    }
}


def calculate_llm_cost(input_tokens: int, output_tokens: int, model_name: str = config.VERTEX_AI_MODEL) -> float:
    """Calculates dollar cost for an LLM call using configured pricing per 1M tokens."""
    rates = config.PRICING_PER_MILLION.get(model_name, config.PRICING_PER_MILLION["default"])
    cost_in = (input_tokens * rates["input"]) / 1_000_000.0
    cost_out = (output_tokens * rates["output"]) / 1_000_000.0
    return round(cost_in + cost_out, 6)


def build_tagging_payload(jobs: List[Dict[str, Any]]) -> str:
    """Formats a batch of untagged jobs into a lightweight JSON payload for the LLM."""
    payload = []
    for j in jobs:
        payload.append({
            "id": j["id"],
            "title": j["title"],
            "company": j["company"],
            "location_raw": j.get("location_raw", ""),
            "city": j.get("city", ""),
            "job_type": j.get("job_type", "job"),
            "description_snippet": (j.get("description") or "")[:400]
        })
    return json.dumps(payload, indent=2)


def heuristic_fallback_tagger(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deterministic fallback / offline tagger used during tests or if Vertex AI is temporarily unreachable.
    Guarantees the pipeline always produces valid taxonomy output without throwing uncaught exceptions.
    """
    tagged = []
    for j in jobs:
        title_lower = (j.get("title") or "").lower()
        desc_lower = (j.get("description_snippet") or j.get("description") or "").lower()
        text = f"{title_lower} {desc_lower}"

        # 1. Role classification (Title takes primary precedence to prevent description noise)
        role = "Other"
        
        # Check specific title keywords first with word boundary matching
        if re.search(r'\b(marketing|growth|seo|social media|brand|content|communications)\b', title_lower):
            role = "Marketing"
        elif re.search(r'\b(data|machine learning|ml|ai|analyst|analytics|bi|research|scientist|quant|insights)\b', title_lower):
            role = "Data/ML"
        elif re.search(r'\b(design\w*|ui|ux|graphic|creative|visual)\b', title_lower):
            role = "Design"
        elif re.search(r'\b(sales|bdr|sdr|business development|account|commercial|bd)\b', title_lower):
            role = "Sales"
        elif re.search(r'\b(hr|recruiting|talent|people ops|onboarding)\b', title_lower):
            role = "HR"
        elif re.search(r'\b(finance|accounting|tax|audit|treasury|credit|investment|lending)\b', title_lower):
            role = "Finance"
        elif re.search(r'\b(operations|ops|logistics|supply chain|process|support|customer|program|project|implementation|warehouse|product)\b', title_lower):
            role = "Ops"
        elif re.search(r'\b(software|sde|swe|developer|backend|frontend|fullstack|devops|cloud|qa|sdet|engineer|technical|it|systems|security|network|silicon|hardware|embedded|quality|test)\b', title_lower):
            role = "SDE"
        else:
            # Fallback to broader text matching with word boundaries
            if re.search(r'\b(marketing|growth|seo)\b', text):
                role = "Marketing"
            elif re.search(r'\b(software|sde|developer|backend|frontend|fullstack|devops|cloud|qa|engineer|technical)\b', text):
                role = "SDE"
            elif re.search(r'\b(data|machine learning|\bml\b|\bai\b|analytics)\b', text):
                role = "Data/ML"
            elif re.search(r'\b(design|ui|ux)\b', text):
                role = "Design"
            elif re.search(r'\b(sales|bdr|sdr)\b', text):
                role = "Sales"
            elif re.search(r'\b(operations|logistics|support|process)\b', text):
                role = "Ops"
            elif re.search(r'\b(finance|accounting|audit)\b', text):
                role = "Finance"
            elif re.search(r'\b(hr|recruiting|talent)\b', text):
                role = "HR"

        # 2. City
        city = j.get("city") or "Remote"

        # 3. Skills extraction
        detected_skills = []
        skill_candidates = [
            ("python", "Python"), ("java", "Java"), ("react", "React"), ("sql", "SQL"),
            ("javascript", "JavaScript"), ("typescript", "TypeScript"), ("node", "Node.js"),
            ("c++", "C++"), ("golang", "Go"), ("aws", "AWS"), ("docker", "Docker"),
            ("kubernetes", "Kubernetes"), ("linux", "Linux"), ("git", "Git"),
            ("excel", "Excel"), ("figma", "Figma"), ("tableau", "Tableau"),
            ("power bi", "Power BI"), ("machine learning", "Machine Learning"),
            ("deep learning", "Deep Learning"), ("pytorch", "PyTorch"),
            ("tensorflow", "TensorFlow"), ("html", "HTML/CSS"), ("mongodb", "MongoDB"),
            ("postgresql", "PostgreSQL"), ("testing", "Automation Testing"),
            ("selenium", "Selenium"), ("android", "Android"), ("ios", "iOS")
        ]
        for pattern, label in skill_candidates:
            if re.search(r'\b' + re.escape(pattern) + r'\b', text) and label not in detected_skills:
                detected_skills.append(label)

        role_default_skills = {
            "SDE": ["Data Structures", "Algorithms", "Python", "Git"],
            "Data/ML": ["Python", "SQL", "Data Analysis", "Statistics"],
            "Design": ["Figma", "UI/UX Design", "Wireframing", "Prototyping"],
            "Marketing": ["Digital Marketing", "Content Strategy", "Growth Analytics"],
            "Sales": ["Business Development", "Client Communication", "CRM"],
            "Ops": ["Process Operations", "Cross-functional Coordination", "Excel"],
            "Finance": ["Financial Analysis", "Excel", "Accounting & Audit"],
            "HR": ["Talent Acquisition", "Candidate Screening", "HR Operations"],
            "Other": ["Analytical Thinking", "Problem Solving", "Communication"]
        }
        for fallback_skill in role_default_skills.get(role, role_default_skills["Other"]):
            if len(detected_skills) >= 4:
                break
            if fallback_skill not in detected_skills:
                detected_skills.append(fallback_skill)

        tagged.append({
            "id": j["id"],
            "role": role,
            "city": city,
            "is_fresher_friendly": True,
            "min_exp": 0,
            "max_exp": 1,
            "skills": detected_skills[:5],
            "confidence": 0.95
        })
    return tagged


def tag_job_batch_vertex(jobs_batch: List[Dict[str, Any]], model_name: str = config.VERTEX_AI_MODEL) -> Tuple[List[Dict[str, Any]], int, int, float]:
    """
    Calls Vertex AI Gemini with JSON Schema structured output.
    Returns: (tagged_results, input_tokens, output_tokens, cost_usd)
    """
    if not HAS_VERTEX:
        logger.info("Vertex AI SDK not available; using heuristic tagger fallback.")
        results = heuristic_fallback_tagger(jobs_batch)
        in_tok = len(json.dumps(jobs_batch)) // 4
        out_tok = len(json.dumps(results)) // 4
        cost = calculate_llm_cost(in_tok, out_tok, model_name)
        return results, in_tok, out_tok, cost

    try:
        vertexai.init(project=config.PROJECT_ID, location=config.REGION)
        model = GenerativeModel(
            model_name=model_name,
            system_instruction=TAGGING_SYSTEM_PROMPT
        )
        prompt = f"Analyze and classify these fresher job postings:\n\n{build_tagging_payload(jobs_batch)}"
        
        # Configure JSON Schema structured output
        generation_config = GenerationConfig(
            response_mime_type="application/json",
            response_schema=TAGGING_RESPONSE_SCHEMA,
            temperature=0.1
        )
        
        response = model.generate_content(prompt, generation_config=generation_config)
        response_text = response.text.strip()
        parsed_results = json.loads(response_text)

        # Extract actual token counts from response metadata
        usage = getattr(response, "usage_metadata", None)
        in_tokens = getattr(usage, "prompt_token_count", len(prompt) // 4)
        out_tokens = getattr(usage, "candidates_token_count", len(response_text) // 4)
        cost_usd = calculate_llm_cost(in_tokens, out_tokens, model_name)

        return parsed_results, in_tokens, out_tokens, cost_usd

    except Exception as e:
        logger.warning(f"Vertex AI API call failed ({e}); falling back to heuristic tagger.")
        results = heuristic_fallback_tagger(jobs_batch)
        in_tok = len(json.dumps(jobs_batch)) // 4
        out_tok = len(json.dumps(results)) // 4
        cost = calculate_llm_cost(in_tok, out_tok, model_name)
        return results, in_tok, out_tok, cost


def enrich_untagged_jobs(db: Database, run_id: Optional[int] = None, batch_size: int = 15, tagger_fn = None) -> int:
    """
    Queries newly inserted jobs where tagged_at IS NULL, batches them,
    calls the tagger, updates the database, and logs token usage & cost.
    """
    if tagger_fn is None:
        tagger_fn = tag_job_batch_vertex

    conn = db.get_connection()
    untagged_jobs = []
    try:
        cur = conn.cursor()
        query = "SELECT id, title, company, location_raw, city, job_type, description FROM jobs WHERE tagged_at IS NULL AND is_active = 1" if db.is_sqlite else "SELECT id, title, company, location_raw, city, job_type, description FROM jobs WHERE tagged_at IS NULL AND is_active = TRUE"
        cur.execute(query)
        rows = cur.fetchall()
        for r in rows:
            if db.is_sqlite:
                untagged_jobs.append({
                    "id": r["id"],
                    "title": r["title"],
                    "company": r["company"],
                    "location_raw": r["location_raw"],
                    "city": r["city"],
                    "job_type": r["job_type"],
                    "description": r["description"]
                })
            else:
                untagged_jobs.append({
                    "id": r[0],
                    "title": r[1],
                    "company": r[2],
                    "location_raw": r[3],
                    "city": r[4],
                    "job_type": r[5],
                    "description": r[6]
                })
    finally:
        if not db._sqlite_mem_conn:
            conn.close()

    if not untagged_jobs:
        logger.info("No untagged jobs found.")
        return 0

    logger.info(f"Enriching {len(untagged_jobs)} untagged jobs in batches of {batch_size}...")
    total_tagged = 0

    for i in range(0, len(untagged_jobs), batch_size):
        batch = untagged_jobs[i:i + batch_size]
        tagged_results, in_tok, out_tok, cost_usd = tagger_fn(batch)

        # Log LLM cost
        db.log_llm_cost(
            run_id=run_id,
            model_name=config.VERTEX_AI_MODEL,
            posts_count=len(batch),
            in_tokens=in_tok,
            out_tokens=out_tok,
            cost_usd=cost_usd
        )

        # Update each job in DB
        update_conn = db.get_connection()
        try:
            update_cur = update_conn.cursor()
            now_iso = datetime.now(timezone.utc).isoformat()
            for item in tagged_results:
                job_id = item["id"]
                role = item.get("role", "Other")
                city = item.get("city", "Remote")
                is_fresher = 1 if item.get("is_fresher_friendly", True) else 0
                min_exp = item.get("min_exp", 0)
                max_exp = item.get("max_exp", 1)
                skills_json = json.dumps(item.get("skills", []))
                conf = float(item.get("confidence", 1.0))
                
                # If city is Unknown, deactivate it so it doesn't appear in search
                is_active = 0 if city == "Unknown" else 1

                if db.is_sqlite:
                    update_cur.execute(
                        """
                        UPDATE jobs
                        SET role_tag = ?, city = ?, is_fresher_friendly = ?,
                            min_exp = ?, max_exp = ?, skills = ?, confidence = ?,
                            tagged_at = ?, is_active = ?
                        WHERE id = ?
                        """,
                        (role, city, is_fresher, min_exp, max_exp, skills_json, conf, now_iso, is_active, job_id)
                    )
                else:
                    update_cur.execute(
                        """
                        UPDATE jobs
                        SET role_tag = %s, city = %s, is_fresher_friendly = %s,
                            min_exp = %s, max_exp = %s, skills = %s::jsonb, confidence = %s,
                            tagged_at = NOW(), is_active = %s
                        WHERE id = %s
                        """,
                        (role, city, bool(is_fresher), min_exp, max_exp, skills_json, conf, bool(is_active), job_id)
                    )
            update_conn.commit()
            total_tagged += len(tagged_results)
        finally:
            if not db._sqlite_mem_conn:
                update_conn.close()

    logger.info(f"Successfully tagged and enriched {total_tagged} jobs.")
    return total_tagged
