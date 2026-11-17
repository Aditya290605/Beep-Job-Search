# PROMPTS.md - Prompts Used Log

> Running record of every LLM prompt used in the application (tagging, taxonomy normalization) 
> and the system prompts / user instructions used to build it.

---

## 1. System & Build Prompts

### 1.1 Initial Project Brief
```text
PROJECT BRIEF: "Fresher Jobs India" live job aggregator (Beep Gen AI & Engineering assessment)
- 200+ fresher/intern job posts in India from public legal sources
- Deduplication with plain code (normalized key + rapidfuzz)
- LLM tagging: role taxonomy, normalized city (drop Unknown), fresher-friendly, experience, skills, confidence
- Live searchable web tool on Cloud Run (FastAPI + React static export), Cloud SQL PostgreSQL, Cloud Scheduler (every 2 hrs)
- Cloud Logging, token & cost tracking per 1,000 posts, evaluation tooling (50 hand-checked)
```

---

## 2. In-App LLM Prompts (Phase 4 - Active in `backend/app/tagger.py`)

### 2.1 Model & Configuration
- **Model:** `gemini-2.0-flash-lite-preview-02-05` (fallback `gemini-1.5-flash`)
- **API:** Google Cloud Vertex AI
- **Execution:** Batched (10–15 jobs per request)
- **Temperature:** `0.1` (deterministic classification)
- **Output Mode:** JSON Schema Structured Output (`response_mime_type="application/json"`)
- **Thinking:** Disabled / minimal (latency & cost optimization)
- **Pricing:** \$0.10 / 1M input tokens, \$0.40 / 1M output tokens

### 2.2 System Instruction (`TAGGING_SYSTEM_PROMPT`)
```text
You are an expert technical recruiter analyzing job postings for college students and freshers in India.
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
```

### 2.3 JSON Structured Output Schema (`TAGGING_RESPONSE_SCHEMA`)
```json
{
  "type": "ARRAY",
  "items": {
    "type": "OBJECT",
    "properties": {
      "id": {"type": "INTEGER"},
      "role": {
        "type": "STRING",
        "enum": ["SDE", "Data/ML", "Design", "Marketing", "Sales", "Ops", "Finance", "HR", "Other"]
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
```

### 2.4 User Request Payload Example (Sent to Model in Batches)
```json
Analyze and classify these fresher job postings:

[
  {
    "id": 101,
    "title": "Software Development Engineer - Intern",
    "company": "Razorpay",
    "location_raw": "Bengaluru, Karnataka",
    "city": "Bangalore",
    "job_type": "internship",
    "description_snippet": "Join our payments checkout team. Looking for pre-final/final year students proficient in Python, Go, and relational databases. 6-month full-time internship."
  },
  {
    "id": 102,
    "title": "Data Analyst Trainee",
    "company": "Swiggy",
    "location_raw": "Bangalore, India",
    "city": "Bangalore",
    "job_type": "job",
    "description_snippet": "Fresh college graduates with strong SQL, Excel, and analytical thinking. Will build dashboards and analyze customer delivery metrics."
  }
]
```

### 2.5 Model Response Example (Guaranteed by Schema)
```json
[
  {
    "id": 101,
    "role": "SDE",
    "city": "Bangalore",
    "is_fresher_friendly": true,
    "min_exp": 0,
    "max_exp": 1,
    "skills": ["Python", "Go", "Relational Databases", "Backend"],
    "confidence": 0.98
  },
  {
    "id": 102,
    "role": "Data/ML",
    "city": "Bangalore",
    "is_fresher_friendly": true,
    "min_exp": 0,
    "max_exp": 1,
    "skills": ["SQL", "Excel", "Data Analytics", "Dashboards"],
    "confidence": 0.96
  }
]
```
