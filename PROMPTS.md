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

## 2. In-App LLM Prompts (to be implemented in Phase 4)

### 2.1 Job Tagging & Normalization Prompt (Draft / Template)
*(Will be finalized with Vertex AI JSON Schema structured output in Phase 4)*

```text
You are an expert technical recruiter analyzing job postings in India for college freshers.
Given a batch of job posts, output a strict JSON list conforming to the schema.

Taxonomy Roles:
- SDE
- Data/ML
- Design
- Marketing
- Sales
- Ops
- Finance
- HR
- Other

Rules:
1. city: Normalize to canonical Indian cities (e.g. "Bengaluru" / "Bangalore" -> "Bangalore", "Gurgaon" / "Gurugram" -> "Gurugram", "Remote", or "Unknown"). If no specific Indian city or remote can be determined, return "Unknown".
2. is_fresher_friendly: true if 0-1 years exp, mentions freshers, graduates, interns, or entry-level.
3. min_years / max_years: Extract integer years (null if not specified).
4. skills: Extract up to 6 key technical or role-specific skills.
5. confidence: Float between 0.0 and 1.0 indicating extraction confidence.
```

---
