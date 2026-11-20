# PROMPTS.md — Verbatim In-App LLM Prompts (Submission Copy)

> **Audit Note:** Extracted verbatim from `backend/app/tagger.py` (commit `5a359de` / `ca3c9dd`).
> **Important:** The application uses **ONLY ONE** LLM task: job tagging & enrichment (`backend/app/tagger.py`). There is **NO** LLM deduplication prompt in the codebase — deduplication is 100% deterministic code + RapidFuzz (`backend/app/dedupe.py`).

---

## 1. Model & Runtime Configuration (`backend/app/config.py:102-106`, `backend/app/tagger.py:309-336, 472`)

- **Primary Model:** `gemini-3.5-flash-lite` (REST fallback chain: `gemini-3.5-flash-lite` -> `gemini-2.5-flash-lite` -> `gemini-2.5-flash`)
- **Endpoint (live):** `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` (with Vertex AI REST & SDK fallbacks)
- **Temperature:** `0.1`
- **Max Output Tokens:** `4096`
- **Thinking / Reasoning Config:** Not explicitly set (`thinkingConfig` omitted). Verified live on `gemini-3.5-flash-lite`: `thoughtsTokenCount` = `0` (`promptTokenCount + candidatesTokenCount == totalTokenCount`).
- **Batch Size:** `8` jobs/call in production pipeline (`tagger.py:472`). *(Note: standalone scripts `run_llm_tagger.py` and `re_evaluate_jobs.py` override to `30` and `15`.)*
- **Input Truncation:** `max_chars=6000` per job via `extract_relevant_snippet()` (`tagger.py:99-117`), which preserves the first 1,400 chars plus the requirements/qualifications section if found past char 1,400.
  - **Known Code Bug Found in Audit (`tagger.py:132-133`):** `build_tagging_payload()` currently emits **both** `"description": snippet` and `"description_snippet": snippet`, sending the 6,000-char description twice per job (~43% wasted input tokens).
- **Output Format:** Structured JSON via `responseMimeType: "application/json"` + `responseSchema: TAGGING_RESPONSE_SCHEMA`.
- **Retries & Fallback:** Up to 5 attempts per URL with linear backoff `2.5 * (attempt + 1)` seconds on HTTP `429` or `503`. If all models/endpoints fail or return invalid JSON, falls back silently to `heuristic_fallback_tagger()` (word-boundary regex classifier).

---

## 2. System Instruction (`TAGGING_SYSTEM_PROMPT` — `backend/app/tagger.py:36-64`)

```text
You are an expert technical recruiter analyzing job postings for college students and freshers in India.
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
```

---

## 3. User Prompt Template (`backend/app/tagger.py:311, 442`)

```text
Analyze and classify these fresher job postings:

<JSON array of up to 8 job objects containing: id, title, company, location_raw, city, job_type, description, description_snippet>
```

---

## 4. Structured Output JSON Schema (`TAGGING_RESPONSE_SCHEMA` — `backend/app/tagger.py:66-88`)

```json
{
  "type": "ARRAY",
  "items": {
    "type": "OBJECT",
    "properties": {
      "id": {"type": "INTEGER"},
      "role": {
        "type": "STRING",
        "enum": ["SDE", "Data/ML", "Hardware", "Design", "Marketing", "Sales", "Ops", "Finance", "HR", "Other"]
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
```

---

## 5. OpenAI-Compatible Fallback Suffix (`backend/app/tagger.py:252-256`)

Used only if `GEMINI_API_KEY` starts with `gsk_` (Groq `llama-3.3-70b-versatile`) or `sk-` (OpenRouter `google/gemini-2.5-flash-lite`):

```text
<TAGGING_SYSTEM_PROMPT>
Return ONLY a JSON object with a single key "items" containing the array of classified job objects: {"items": [{"id": int, "role": str, "city": str, "is_fresher_friendly": bool, "min_exp": int, "max_exp": int, "skills": [str], "confidence": float}]}
```
