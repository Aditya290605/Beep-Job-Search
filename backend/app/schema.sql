-- schema.sql: PostgreSQL schema for Fresher Jobs India aggregator

-- 1. Main canonical jobs table
CREATE TABLE IF NOT EXISTS jobs (
    id BIGSERIAL PRIMARY KEY,
    normalized_key VARCHAR(255) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    company VARCHAR(255) NOT NULL,
    location_raw TEXT NOT NULL,
    city VARCHAR(100) NOT NULL,
    job_type VARCHAR(50) NOT NULL DEFAULT 'job', -- 'job' or 'internship'
    posted_date TIMESTAMPTZ,
    apply_url TEXT NOT NULL,
    description TEXT,
    source_name VARCHAR(100) NOT NULL,
    source_job_id VARCHAR(255),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    last_verified_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- LLM enrichment fields (populated in Phase 4)
    role_tag VARCHAR(50) DEFAULT 'Other', -- SDE, Data/ML, Hardware, Design, Marketing, Sales, Ops, Finance, HR, Other
    is_fresher_friendly BOOLEAN DEFAULT TRUE,
    min_exp INTEGER DEFAULT 0,
    max_exp INTEGER DEFAULT 1,
    skills JSONB DEFAULT '[]'::jsonb,
    confidence NUMERIC(3, 2) DEFAULT 1.00,
    tagged_at TIMESTAMPTZ
);

-- Indexes for lightning-fast search and filtering (<500ms p95)
CREATE INDEX IF NOT EXISTS idx_jobs_city ON jobs(city);
CREATE INDEX IF NOT EXISTS idx_jobs_role_tag ON jobs(role_tag);
CREATE INDEX IF NOT EXISTS idx_jobs_job_type ON jobs(job_type);
CREATE INDEX IF NOT EXISTS idx_jobs_posted_date ON jobs(posted_date DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen_at ON jobs(first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_is_active ON jobs(is_active);

-- Full-text search index across title, company, and description
CREATE INDEX IF NOT EXISTS idx_jobs_fts ON jobs USING gin(
    to_tsvector('english', title || ' ' || company || ' ' || COALESCE(description, ''))
);

-- 2. Job Sources table (tracks all source links if a job was found on multiple boards)
CREATE TABLE IF NOT EXISTS job_sources (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT REFERENCES jobs(id) ON DELETE CASCADE,
    source_name VARCHAR(100) NOT NULL,
    source_job_id VARCHAR(255),
    url TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(job_id, source_name, url)
);

CREATE INDEX IF NOT EXISTS idx_job_sources_job_id ON job_sources(job_id);

-- 3. Pipeline Runs table (powers /status endpoint & auditability)
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status VARCHAR(50) NOT NULL DEFAULT 'running', -- 'running', 'success', 'partial_failure', 'failed'
    sources_summary JSONB DEFAULT '{}'::jsonb,
    total_fetched INTEGER DEFAULT 0,
    new_posts INTEGER DEFAULT 0,
    duplicates_skipped INTEGER DEFAULT 0,
    tagged_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started_at ON pipeline_runs(started_at DESC);

-- 4. LLM Cost Logs table (powers cost report per 1,000 posts)
CREATE TABLE IF NOT EXISTS llm_cost_logs (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    model_name VARCHAR(100) NOT NULL,
    posts_count INTEGER NOT NULL DEFAULT 1,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd NUMERIC(8, 6) NOT NULL DEFAULT 0.000000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_cost_logs_run_id ON llm_cost_logs(run_id);
