-- Run in Supabase SQL Editor
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT NOT NULL,
    raw_prompt TEXT NOT NULL,
    prompt TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'ltx-video',
    status TEXT NOT NULL DEFAULT 'pending',
    provider TEXT,
    worker_id TEXT,
    result_url TEXT,
    telegram_file_id TEXT,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id);

-- Atomic claim (prevents race conditions)
CREATE OR REPLACE FUNCTION claim_next_job(p_worker_id TEXT, p_provider TEXT)
RETURNS SETOF jobs LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    UPDATE jobs
    SET status = 'processing',
        worker_id = p_worker_id,
        provider = p_provider,
        claimed_at = now()
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'pending'
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING *;
END;
$$;

-- Mark complete
CREATE OR REPLACE FUNCTION mark_job_complete(p_job_id UUID, p_result_url TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    UPDATE jobs
    SET status = 'complete',
        result_url = p_result_url,
        completed_at = now()
    WHERE id = p_job_id;
END;
$$;

-- Mark failed
CREATE OR REPLACE FUNCTION mark_job_failed(p_job_id UUID, p_error TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    UPDATE jobs
    SET status = 'failed',
        error = p_error,
        completed_at = now()
    WHERE id = p_job_id;
END;
$$;