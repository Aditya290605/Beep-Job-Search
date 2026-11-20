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
import urllib.request
import urllib.error
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
Classify each post according to our strict taxonomy and extract EVERY real qualification signal directly from the job description.

Roles Taxonomy (MUST be one of these exact values):
- SDE: Software engineering, backend, frontend, fullstack, mobile, DevOps, cloud, QA/SDET, application/cloud security.
- Data/ML: Data science, data analytics, ML/AI engineer, BI analyst, data engineering, quantitative research.
- Hardware: Hardware engineering, silicon, VLSI, RTL, FPGA, ASIC, PCB, motherboard, embedded electronics, firmware, power electronics, semiconductor, RF/circuit design, board bring-up. NEVER put Hardware/VLSI/Silicon/PCB/Motherboard/Embedded Electronics roles into SDE!
- Design: UI/UX, product design, graphic design, visual design.
- Marketing: Growth, digital marketing, SEO, content, social media, performance marketing.
- Sales: Business development (BDR/SDR), inside sales, account executive.
- Ops: Business operations, customer support, supply chain, logistics, program/product management.
- Finance: Accounting, audit, financial analysis, investment, tax.
- HR: Recruiting, talent acquisition, human resources, people ops.
- Other: Any role that does not fit the above categories.

City Canonicalization:
- Canonical Indian cities: Bangalore, Mumbai, Pune, Hyderabad, Gurugram, Delhi, Noida, Chennai, Kolkata, Ahmedabad, Jaipur, Kochi, Coimbatore.
- If remote within India or worldwide, return "Remote".
- If the job is located in India but specific city is not a single metro (e.g. "India, Multiple Locations", "India", or unlisted Indian city), return "India (Multiple/Other)" or "Remote" or the dominant Indian city mentioned.
- If the role is definitively outside India or foreign-only (e.g., US-only, UK-only), return "Unknown".

Fresher & Experience Rules (STRICT — ZERO COMPROMISE):
- is_fresher_friendly: Boolean. Set TRUE ONLY IF the opening genuinely welcomes freshers, interns, apprentices, new college graduates, or candidates with 0-1 years of industry experience.
- Set is_fresher_friendly: FALSE if the job description requires 2+ years of experience — watch carefully for BOTH digits (2+ years, 2-5 years, 3-6 yrs, 4+ yrs) AND spelled-out words ("two or more years", "at least three years", "five or more years", "minimum of two years").
- min_exp: Integer minimum years of full-time industry experience required by the JD (e.g. 0 for intern/fresher/new grad, 2 for "2-5 years", 5 for "five or more years").
- max_exp: Integer maximum years of experience stated (e.g. 1 for fresher/intern, 5 for 2-5 yrs, 8 for 5+ yrs).
- skills: Array of ALL concrete technical, tool, language, framework, hardware, protocol, and domain skills explicitly mentioned in the job description (extract 8 to 15 distinct skills whenever the JD lists that many; capture specific tools/standards like SAML 2.0, OAuth 2.0, Verilog, SystemVerilog, PCB Design, SPICE, Oscilloscope, PyTorch, FastAPI, Docker, Kubernetes, Active Directory, etc.). Do NOT fabricate generic skills like "Data Structures" or "Python" if they are not actually mentioned or required in the JD.
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
        "required": ["id", "role", "city", "is_fresher_friendly", "min_exp", "max_exp", "confidence", "skills"]
    }
}


def calculate_llm_cost(input_tokens: int, output_tokens: int, model_name: str = config.VERTEX_AI_MODEL) -> float:
    """Calculates dollar cost for an LLM call using configured pricing per 1M tokens."""
    rates = config.PRICING_PER_MILLION.get(model_name, config.PRICING_PER_MILLION["default"])
    cost_in = (input_tokens * rates["input"]) / 1_000_000.0
    cost_out = (output_tokens * rates["output"]) / 1_000_000.0
    return round(cost_in + cost_out, 6)


def extract_relevant_snippet(desc: str, max_chars: int = 6000) -> str:
    """Extracts up to 6,000 chars of the job description, preserving BOTH intro context AND full requirements/qualifications."""
    if not desc:
        return ""
    if len(desc) <= max_chars:
        return desc

    # Search for requirements or qualifications headings
    req_match = re.search(
        r"(?:requirements|qualifications|what['’]s required|what you(?:’|')ll need|you should apply if|what we(?:’|')re looking for|skills|eligibility|preferred qualifications|minimum qualifications):?",
        desc,
        re.IGNORECASE,
    )
    if req_match and req_match.start() > 1400:
        intro = desc[:1400].rstrip()
        req_start = max(1400, req_match.start() - 150)
        reqs = desc[req_start:req_start + (max_chars - len(intro) - 10)]
        return f"{intro}\n...\n{reqs}"
    return desc[:max_chars]


def build_tagging_payload(jobs: List[Dict[str, Any]]) -> str:
    """Formats a batch of untagged jobs into a compact JSON payload for the LLM."""
    payload = []
    for j in jobs:
        snippet = extract_relevant_snippet(j.get("description") or "", max_chars=6000)
        payload.append({
            "id": j["id"],
            "title": j["title"],
            "company": j["company"],
            "location_raw": j.get("location_raw", ""),
            "city": j.get("city", ""),
            "job_type": j.get("job_type", "job"),
            "description": snippet,
        })
    return json.dumps(payload, indent=2)


def heuristic_fallback_tagger(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deterministic fallback / offline tagger used during unit tests or if LLM API is temporarily unreachable.
    Guarantees valid taxonomy output and strictly respects Hardware vs SDE boundaries & experience guards.
    """
    from app.adapters.base import SENIOR_EXP_REGEX

    tagged = []
    for j in jobs:
        title_lower = (j.get("title") or "").lower()
        desc_lower = (j.get("description_snippet") or j.get("description") or "").lower()
        text = f"{title_lower} {desc_lower}"

        # 1. Role classification (Hardware checked BEFORE SDE!)
        role = "Other"

        if re.search(r'\b(hardware|silicon|vlsi|fpga|asic|rtl|pcb|motherboard|embedded|firmware|semiconductor|power electronics|circuit|analog|mixed[- ]signal|rf engineer|board bring[- ]up|soc verification)\b', title_lower):
            role = "Hardware"
        elif re.search(r'\b(marketing|growth|seo|social media|brand|content|communications)\b', title_lower):
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
        elif re.search(r'\b(software|sde|swe|developer|backend|frontend|fullstack|devops|cloud|qa|sdet|engineer|technical|it|systems|security|network|quality|test)\b', title_lower):
            role = "SDE"
        else:
            if re.search(r'\b(verilog|systemverilog|vlsi|fpga|asic|pcb|motherboard|schematic|oscilloscope|power electronics)\b', text):
                role = "Hardware"
            elif re.search(r'\b(marketing|growth|seo)\b', text):
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

        # 3. Experience check (never falsely mark 2+ yr JDs as fresher even in fallback)
        is_senior_desc = bool(SENIOR_EXP_REGEX.search(desc_lower))

        # 4. Skills extraction (extract ONLY skills actually present in text; broad real-world vocabulary)
        detected_skills = []
        skill_candidates = [
            ("python", "Python"), ("java", "Java"), ("react", "React"), ("sql", "SQL"),
            ("javascript", "JavaScript"), ("typescript", "TypeScript"), ("node.js", "Node.js"), ("nodejs", "Node.js"),
            ("c++", "C++"), ("golang", "Go"), ("rust", "Rust"), ("aws", "AWS"), ("azure", "Azure"), ("gcp", "GCP"),
            ("docker", "Docker"), ("kubernetes", "Kubernetes"), ("linux", "Linux"), ("git", "Git"),
            ("verilog", "Verilog"), ("systemverilog", "SystemVerilog"), ("vhdl", "VHDL"), ("fpga", "FPGA"),
            ("asic", "ASIC"), ("vlsi", "VLSI"), ("rtl", "RTL Design"), ("pcb", "PCB Design"),
            ("motherboard", "Motherboard Architecture"), ("firmware", "Firmware"), ("embedded", "Embedded Systems"),
            ("rtos", "RTOS"), ("spice", "SPICE"), ("oscilloscope", "Oscilloscope"), ("cadence", "Cadence"),
            ("synopsys", "Synopsys"), ("matlab", "MATLAB"), ("simulink", "Simulink"), ("i2c", "I2C"), ("spi", "SPI"),
            ("uart", "UART"), ("pcie", "PCIe"), ("ddr", "DDR Memory"), ("arm", "ARM Architecture"),
            ("saml", "SAML 2.0"), ("oauth", "OAuth 2.0"), ("oidc", "OpenID Connect"), ("scim", "SCIM"),
            ("active directory", "Active Directory"), ("siem", "SIEM"), ("iam", "IAM"), ("fido2", "FIDO2"),
            ("excel", "Excel"), ("figma", "Figma"), ("tableau", "Tableau"), ("power bi", "Power BI"),
            ("machine learning", "Machine Learning"), ("deep learning", "Deep Learning"),
            ("pytorch", "PyTorch"), ("tensorflow", "TensorFlow"), ("cuda", "CUDA"), ("llm", "LLMs"),
            ("fastapi", "FastAPI"), ("django", "Django"), ("spring boot", "Spring Boot"),
            ("html", "HTML/CSS"), ("mongodb", "MongoDB"), ("postgresql", "PostgreSQL"), ("redis", "Redis"),
            ("kafka", "Kafka"), ("spark", "Apache Spark"), ("airflow", "Airflow"), ("terraform", "Terraform"),
            ("ci/cd", "CI/CD"), ("rest api", "REST APIs"), ("graphql", "GraphQL"),
            ("selenium", "Selenium"), ("playwright", "Playwright"), ("android", "Android"), ("ios", "iOS"),
            ("kotlin", "Kotlin"), ("swift", "Swift"), ("c#", "C#"), (".net", ".NET")
        ]
        for pattern, label in skill_candidates:
            if re.search(r'(?<!\w)' + re.escape(pattern) + r'(?!\w)', text) and label not in detected_skills:
                detected_skills.append(label)

        tagged.append({
            "id": j["id"],
            "role": role,
            "city": city,
            "is_fresher_friendly": not is_senior_desc,
            "min_exp": 2 if is_senior_desc else 0,
            "max_exp": 5 if is_senior_desc else 1,
            "skills": detected_skills[:12],
            "confidence": 0.85
        })
    return tagged


def _call_openai_compatible_api(
    jobs_batch: List[Dict[str, Any]],
    api_key: str
) -> Tuple[List[Dict[str, Any]], int, int, float]:
    """
    Calls Groq (gsk_...) or OpenRouter (sk-or-...) OpenAI-compatible JSON endpoint
    using Python's standard library urllib.request. Zero billing/prepay setup required on Groq.
    """
    is_groq = api_key.startswith("gsk_")
    url = "https://api.groq.com/openai/v1/chat/completions" if is_groq else "https://openrouter.ai/api/v1/chat/completions"
    model = "llama-3.3-70b-versatile" if is_groq else "google/gemini-2.5-flash-lite"

    schema_instruction = (
        TAGGING_SYSTEM_PROMPT
        + "\nReturn ONLY a JSON object with a single key \"items\" containing the array of classified job objects: "
        + "{\"items\": [{\"id\": int, \"role\": str, \"city\": str, \"is_fresher_friendly\": bool, \"min_exp\": int, \"max_exp\": int, \"skills\": [str], \"confidence\": float}]}"
    )
    prompt = f"Analyze and classify these fresher job postings:\n\n{build_tagging_payload(jobs_batch)}"

    body = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": schema_instruction},
            {"role": "user", "content": prompt}
        ]
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "BeepJobHub/1.0"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        resp_data = json.loads(resp.read().decode("utf-8"))

    content = resp_data["choices"][0]["message"]["content"].strip()
    parsed = json.loads(content)
    parsed_results = parsed.get("items") if isinstance(parsed, dict) else parsed
    if not isinstance(parsed_results, list):
        raise ValueError(f"Expected list in 'items', got: {content[:200]}")

    usage = resp_data.get("usage") or {}
    in_tokens = int(usage.get("prompt_tokens") or (len(prompt) // 4))
    out_tokens = int(usage.get("completion_tokens") or (len(content) // 4))
    cost_usd = calculate_llm_cost(in_tokens, out_tokens, "gemini-2.5-flash-lite")
    return parsed_results, in_tokens, out_tokens, cost_usd


def _call_gemini_rest_api(
    jobs_batch: List[Dict[str, Any]],
    model_name: str,
    api_key: str = "",
    vertex_token: str = ""
) -> Tuple[List[Dict[str, Any]], int, int, float]:
    """
    Calls Gemini 2.5 Flash-Lite over HTTPS using Python's standard library urllib.request.
    Automatically routes:
    - gsk_... / sk-or-... -> Groq / OpenRouter JSON API
    - AIza... -> Normal Google Gemini API (generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent)
    """
    if api_key and (api_key.startswith("gsk_") or api_key.startswith("sk-")):
        return _call_openai_compatible_api(jobs_batch, api_key)

    clean_model = "gemini-3.5-flash-lite" if ("2.0-flash-lite" in model_name or "2.5-flash-lite" in model_name) else model_name
    vertex_region = getattr(config, "VERTEX_REGION", "us-central1")
    prompt = f"Analyze and classify these fresher job postings:\n\n{build_tagging_payload(jobs_batch)}"

    body = {
        "systemInstruction": {
            "role": "system",
            "parts": [{"text": TAGGING_SYSTEM_PROMPT}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
            "responseSchema": TAGGING_RESPONSE_SCHEMA
        }
    }

    if api_key:
        candidate_models = list(dict.fromkeys([clean_model, "gemini-2.5-flash-lite", "gemini-2.5-flash"]))
        urls = [
            f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
            for m in candidate_models
        ]
        headers = {"Content-Type": "application/json"}
    else:
        candidate_models = list(dict.fromkeys([clean_model, "gemini-2.5-flash-lite", "gemini-2.5-flash"]))
        urls = []
        for m in candidate_models:
            urls.append(
                f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
            )
            urls.append(
                f"https://aiplatform.googleapis.com/v1/projects/{config.PROJECT_ID}"
                f"/locations/global/publishers/google/models/{m}:generateContent"
            )
            urls.append(
                f"https://us-central1-aiplatform.googleapis.com/v1/projects/{config.PROJECT_ID}"
                f"/locations/us-central1/publishers/google/models/{m}:generateContent"
            )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {vertex_token}",
            "x-goog-user-project": config.PROJECT_ID
        }

    resp_data = None
    last_err = None
    used_model = clean_model
    payload_bytes = json.dumps(body).encode("utf-8")
    for url in urls:
        safe_url = re.sub(r"([?&]key=)[^&\s]+", r"\1REDACTED", url)
        m_match = re.search(r"/models/([^:/?]+)", safe_url)
        candidate_m = m_match.group(1) if m_match else clean_model
        for attempt in range(5):
            try:
                req = urllib.request.Request(
                    url,
                    data=payload_bytes,
                    headers=headers,
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    used_model = resp_data.get("modelVersion") or candidate_m
                    break
            except urllib.error.HTTPError as he:
                err_body = he.read().decode("utf-8", errors="ignore")[:1200]
                last_err = RuntimeError(f"HTTP {he.code} on {safe_url}: {err_body}")
                if he.code in (503, 429) and attempt < 4:
                    import time
                    time.sleep(2.5 * (attempt + 1))
                    continue
                break
            except Exception as ex:
                last_err = RuntimeError(f"{type(ex).__name__} on {safe_url}: {ex}")
                break
        if resp_data is not None:
            break

    if resp_data is None:
        raise last_err or RuntimeError("All Vertex AI endpoints failed")

    candidates = resp_data.get("candidates") or []
    if not candidates:
        raise ValueError(f"Empty candidates from Gemini REST API: {resp_data}")

    parts = (candidates[0].get("content") or {}).get("parts") or []
    response_text = (parts[0].get("text") or "").strip()
    parsed_results = json.loads(response_text)

    usage = resp_data.get("usageMetadata") or {}
    in_tokens = int(usage.get("promptTokenCount") or (len(prompt) // 4))
    cand_tokens = int(usage.get("candidatesTokenCount") or (len(response_text) // 4))
    think_tokens = int(usage.get("thoughtsTokenCount") or 0)
    out_tokens = cand_tokens + think_tokens
    cost_usd = calculate_llm_cost(in_tokens, out_tokens, used_model)

    return parsed_results, in_tokens, out_tokens, cost_usd


def tag_job_batch_vertex(jobs_batch: List[Dict[str, Any]], model_name: str = config.VERTEX_AI_MODEL) -> Tuple[List[Dict[str, Any]], int, int, float]:
    """
    Calls Gemini Flash-Lite (via REST API if GEMINI_API_KEY / VERTEX_ACCESS_TOKEN is set,
    or via Vertex AI Python SDK on Cloud Run) with JSON Schema structured output.
    Returns: (tagged_results, input_tokens, output_tokens, cost_usd)
    """
    api_key = os.environ.get("GEMINI_API_KEY") or config.GEMINI_API_KEY
    vertex_token = os.environ.get("VERTEX_ACCESS_TOKEN") or config.VERTEX_ACCESS_TOKEN

    if api_key or vertex_token:
        try:
            mode_label = "Gemini REST API" if api_key else "Vertex AI REST API"
            logger.info(f"Calling live {mode_label} ({model_name}) for batch of {len(jobs_batch)} jobs...")
            return _call_gemini_rest_api(jobs_batch, model_name, api_key=api_key, vertex_token=vertex_token)
        except Exception as e:
            logger.warning(f"Live {mode_label} call failed ({e}); falling back to heuristic tagger.")

    if not HAS_VERTEX:
        logger.info("Vertex AI SDK / API key not configured; using heuristic tagger fallback.")
        results = heuristic_fallback_tagger(jobs_batch)
        return results, 0, 0, 0.0

    try:
        vertex_region = getattr(config, "VERTEX_REGION", "us-central1")
        vertexai.init(project=config.PROJECT_ID, location=vertex_region)
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
        cand_tokens = getattr(usage, "candidates_token_count", len(response_text) // 4)
        think_tokens = getattr(usage, "thoughts_token_count", 0) or 0
        out_tokens = cand_tokens + think_tokens
        cost_usd = calculate_llm_cost(in_tokens, out_tokens, model_name)

        return parsed_results, in_tokens, out_tokens, cost_usd

    except Exception as e:
        logger.warning(f"Vertex AI API call failed ({e}); falling back to heuristic tagger.")
        results = heuristic_fallback_tagger(jobs_batch)
        return results, 0, 0, 0.0


def enrich_untagged_jobs(db: Database, run_id: Optional[int] = None, batch_size: int = 8, tagger_fn = None) -> int:
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

        # Log LLM cost (distinguish zero-cost heuristic fallback from real LLM calls)
        logged_model = "heuristic_fallback" if (in_tok == 0 and out_tok == 0 and cost_usd == 0.0) else config.VERTEX_AI_MODEL
        db.log_llm_cost(
            run_id=run_id,
            model_name=logged_model,
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
            batch_city_map = {j["id"]: j.get("city") for j in batch}
            for item in tagged_results:
                job_id = item["id"]
                role = item.get("role", "Other")
                if role not in config.CANONICAL_ROLES:
                    role = "Other"
                city = (item.get("city") or "Remote").strip()
                orig_city = batch_city_map.get(job_id)
                # Keep valid India location if LLM tentatively returned Unknown, unless original was generic Remote
                if city == "Unknown" and orig_city and orig_city not in ("Unknown", "Remote"):
                    city = orig_city

                is_fresher = 1 if item.get("is_fresher_friendly", True) else 0
                min_exp = item.get("min_exp", 0)
                max_exp = item.get("max_exp", 1)
                skills_json = json.dumps(item.get("skills", []))
                conf = float(item.get("confidence", 1.0))
                
                # If role requires 2+ yrs exp, is not fresher-friendly, or city is Unknown, deactivate it
                is_active = 0 if (city == "Unknown" or is_fresher == 0 or min_exp >= 2) else 1

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
