BEGIN;

CREATE TABLE IF NOT EXISTS audit_log (
    id               BIGSERIAL PRIMARY KEY,
    ts               TIMESTAMPTZ NOT NULL DEFAULT now(),
    source           TEXT        NOT NULL,
    target           TEXT        NOT NULL,
    endpoint         TEXT        NOT NULL,
    method           TEXT        NOT NULL,
    request_summary  JSONB,
    response_status  INTEGER,
    response_summary JSONB,
    duration_ms      INTEGER,
    error            TEXT
);
CREATE INDEX IF NOT EXISTS audit_log_ts_idx ON audit_log (ts DESC);
CREATE INDEX IF NOT EXISTS audit_log_target_idx ON audit_log (target, ts DESC);

CREATE SCHEMA IF NOT EXISTS telemetry;
CREATE SCHEMA IF NOT EXISTS paper_metrics;

CREATE TABLE IF NOT EXISTS telemetry.schema_migrations (
    version      TEXT PRIMARY KEY,
    applied_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS telemetry.sessions (
    session_id      UUID PRIMARY KEY,
    subject_id      TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    app_version     TEXT,
    prompt_version  TEXT,
    prompt_lang     TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS telemetry_sessions_subject_idx
    ON telemetry.sessions (subject_id, started_at DESC);

CREATE TABLE IF NOT EXISTS telemetry.workflow_runs (
    run_id             UUID PRIMARY KEY,
    session_id         UUID NOT NULL,
    parent_run_id      UUID,
    module             TEXT NOT NULL,
    operation          TEXT NOT NULL,
    section            TEXT,
    status             TEXT NOT NULL DEFAULT 'running',
    http_method        TEXT,
    path               TEXT,
    http_status        INTEGER,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_segment_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at       TIMESTAMPTZ,
    duration_ms        BIGINT,
    error              TEXT,
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS telemetry_workflow_session_idx
    ON telemetry.workflow_runs (session_id, started_at DESC);
CREATE INDEX IF NOT EXISTS telemetry_workflow_module_idx
    ON telemetry.workflow_runs (module, operation, started_at DESC);

CREATE TABLE IF NOT EXISTS telemetry.llm_calls (
    call_id                UUID PRIMARY KEY,
    run_id                 UUID,
    session_id             UUID,
    module                 TEXT,
    operation              TEXT,
    section                TEXT,
    iteration              INTEGER,
    attempt                INTEGER,
    provider               TEXT NOT NULL,
    model                  TEXT NOT NULL,
    started_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_ms            BIGINT,
    input_tokens           BIGINT,
    output_tokens          BIGINT,
    total_tokens           BIGINT,
    cached_input_tokens    BIGINT,
    reasoning_tokens       BIGINT,
    token_source           TEXT NOT NULL DEFAULT 'provider',
    finish_reason          TEXT,
    request_chars          BIGINT,
    response_chars         BIGINT,
    message_count          INTEGER,
    tool_definition_count  INTEGER,
    status                 TEXT NOT NULL,
    error                  TEXT,
    metadata               JSONB NOT NULL DEFAULT '{}'::jsonb
);
ALTER TABLE telemetry.llm_calls
    ADD COLUMN IF NOT EXISTS request_chars BIGINT;

CREATE INDEX IF NOT EXISTS telemetry_llm_run_idx
    ON telemetry.llm_calls (run_id, started_at);
CREATE INDEX IF NOT EXISTS telemetry_llm_session_idx
    ON telemetry.llm_calls (session_id, started_at DESC);
CREATE INDEX IF NOT EXISTS telemetry_llm_model_idx
    ON telemetry.llm_calls (provider, model, started_at DESC);

CREATE TABLE IF NOT EXISTS telemetry.tool_calls (
    id                      BIGSERIAL PRIMARY KEY,
    run_id                  UUID,
    session_id              UUID,
    llm_call_id             UUID,
    provider_tool_call_id   TEXT NOT NULL,
    module                  TEXT,
    iteration               INTEGER,
    server                  TEXT NOT NULL,
    tool_name               TEXT NOT NULL,
    approval_mode           TEXT NOT NULL,
    status                  TEXT NOT NULL,
    requested_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at             TIMESTAMPTZ,
    started_at              TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    approval_wait_ms        BIGINT,
    duration_ms             BIGINT,
    input_summary           JSONB,
    output_summary          JSONB,
    error                   TEXT,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (run_id, provider_tool_call_id)
);
CREATE INDEX IF NOT EXISTS telemetry_tool_run_idx
    ON telemetry.tool_calls (run_id, requested_at);
CREATE INDEX IF NOT EXISTS telemetry_tool_name_idx
    ON telemetry.tool_calls (server, tool_name, requested_at DESC);

CREATE TABLE IF NOT EXISTS telemetry.external_calls (
    id            BIGSERIAL PRIMARY KEY,
    run_id        UUID,
    session_id    UUID,
    module        TEXT,
    service       TEXT NOT NULL,
    operation     TEXT NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_ms   BIGINT,
    status_code   INTEGER,
    result_count  INTEGER,
    status        TEXT NOT NULL,
    error         TEXT,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS telemetry_external_run_idx
    ON telemetry.external_calls (run_id, started_at);

CREATE TABLE IF NOT EXISTS telemetry.workflow_events (
    id          BIGSERIAL PRIMARY KEY,
    run_id      UUID,
    session_id  UUID,
    module      TEXT,
    operation   TEXT,
    section     TEXT,
    event_type  TEXT NOT NULL,
    phase       TEXT,
    attempt     INTEGER,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS telemetry_event_run_idx
    ON telemetry.workflow_events (run_id, ts);
CREATE INDEX IF NOT EXISTS telemetry_event_type_idx
    ON telemetry.workflow_events (event_type, ts DESC);

CREATE OR REPLACE VIEW paper_metrics.session_summary AS
WITH run_agg AS (
    SELECT session_id,
           count(*) AS workflow_runs,
           count(*) FILTER (WHERE status = 'succeeded') AS successful_runs,
           count(*) FILTER (WHERE status IN ('failed', 'cancelled', 'denied', 'limit_reached')) AS unsuccessful_runs,
           sum(duration_ms) AS workflow_duration_ms
    FROM telemetry.workflow_runs
    GROUP BY session_id
), llm_agg AS (
    SELECT session_id,
           count(*) AS llm_calls,
           sum(input_tokens) AS input_tokens,
           sum(output_tokens) AS output_tokens,
           sum(total_tokens) AS total_tokens,
           sum(duration_ms) AS llm_compute_ms
    FROM telemetry.llm_calls
    GROUP BY session_id
), tool_agg AS (
    SELECT session_id,
           count(*) AS tool_calls,
           count(*) FILTER (WHERE status = 'succeeded') AS successful_tool_calls,
           count(*) FILTER (WHERE approval_mode = 'manual') AS manual_tool_calls,
           count(*) FILTER (WHERE approval_mode = 'auto') AS auto_tool_calls,
           sum(duration_ms) AS tool_compute_ms,
           sum(approval_wait_ms) AS approval_wait_ms
    FROM telemetry.tool_calls
    GROUP BY session_id
)
SELECT s.session_id, s.subject_id, s.started_at, s.last_seen_at,
       s.app_version, s.prompt_version, s.prompt_lang,
       COALESCE(r.workflow_runs, 0) AS workflow_runs,
       COALESCE(r.successful_runs, 0) AS successful_runs,
       COALESCE(r.unsuccessful_runs, 0) AS unsuccessful_runs,
       COALESCE(r.workflow_duration_ms, 0) AS workflow_duration_ms,
       COALESCE(l.llm_calls, 0) AS llm_calls,
       COALESCE(l.input_tokens, 0) AS input_tokens,
       COALESCE(l.output_tokens, 0) AS output_tokens,
       COALESCE(l.total_tokens, 0) AS total_tokens,
       COALESCE(l.llm_compute_ms, 0) AS llm_compute_ms,
       COALESCE(t.tool_calls, 0) AS tool_calls,
       COALESCE(t.successful_tool_calls, 0) AS successful_tool_calls,
       COALESCE(t.manual_tool_calls, 0) AS manual_tool_calls,
       COALESCE(t.auto_tool_calls, 0) AS auto_tool_calls,
       COALESCE(t.tool_compute_ms, 0) AS tool_compute_ms,
       COALESCE(t.approval_wait_ms, 0) AS approval_wait_ms
FROM telemetry.sessions s
LEFT JOIN run_agg r USING (session_id)
LEFT JOIN llm_agg l USING (session_id)
LEFT JOIN tool_agg t USING (session_id);

CREATE OR REPLACE VIEW paper_metrics.module_performance AS
SELECT module, operation, section,
       count(*) AS run_count,
       count(*) FILTER (WHERE status = 'succeeded') AS success_count,
       count(*) FILTER (WHERE status <> 'succeeded') AS non_success_count,
       count(*) FILTER (WHERE status = 'waiting_approval') AS waiting_approval_count,
       count(*) FILTER (WHERE status IN ('failed', 'cancelled', 'denied', 'limit_reached')) AS unsuccessful_count,
       avg(duration_ms)::bigint AS mean_duration_ms,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS median_duration_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_duration_ms
FROM telemetry.workflow_runs
WHERE completed_at IS NOT NULL
GROUP BY module, operation, section;

CREATE OR REPLACE VIEW paper_metrics.chat_tool_summary AS
SELECT server, tool_name, approval_mode,
       count(*) AS call_count,
       count(*) FILTER (WHERE status = 'succeeded') AS success_count,
       count(*) FILTER (WHERE status = 'failed') AS failure_count,
       count(*) FILTER (WHERE status = 'denied') AS denied_count,
       count(*) FILTER (WHERE status IN ('requested', 'approved')) AS incomplete_count,
       avg(duration_ms)::bigint AS mean_duration_ms,
       avg(approval_wait_ms)::bigint AS mean_approval_wait_ms,
       max(iteration) AS max_iteration
FROM telemetry.tool_calls
GROUP BY server, tool_name, approval_mode;

CREATE OR REPLACE VIEW paper_metrics.llm_usage_summary AS
SELECT module, operation, section, provider, model,
       count(*) AS call_count,
       count(*) FILTER (WHERE status = 'succeeded') AS success_count,
       count(*) FILTER (WHERE status = 'failed') AS failure_count,
       count(total_tokens) AS calls_with_provider_usage,
       sum(input_tokens) AS input_tokens,
       sum(output_tokens) AS output_tokens,
       sum(total_tokens) AS total_tokens,
       sum(cached_input_tokens) AS cached_input_tokens,
       sum(reasoning_tokens) AS reasoning_tokens,
       sum(request_chars) AS request_chars,
       sum(response_chars) AS response_chars,
       avg(duration_ms)::bigint AS mean_duration_ms,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS median_duration_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_duration_ms
FROM telemetry.llm_calls
GROUP BY module, operation, section, provider, model;

CREATE OR REPLACE VIEW paper_metrics.run_summary AS
WITH llm AS (
    SELECT run_id,
           count(*) AS llm_calls,
           count(*) FILTER (WHERE status = 'failed') AS failed_llm_calls,
           sum(input_tokens) AS input_tokens,
           sum(output_tokens) AS output_tokens,
           sum(total_tokens) AS total_tokens,
           sum(duration_ms) AS llm_compute_ms
    FROM telemetry.llm_calls
    WHERE run_id IS NOT NULL
    GROUP BY run_id
), tools AS (
    SELECT run_id,
           count(*) AS tool_calls,
           count(*) FILTER (WHERE status = 'failed') AS failed_tool_calls,
           count(*) FILTER (WHERE approval_mode = 'manual') AS manual_tool_calls,
           count(*) FILTER (WHERE status = 'denied') AS denied_tool_calls,
           sum(duration_ms) AS tool_compute_ms,
           sum(approval_wait_ms) AS approval_wait_ms
    FROM telemetry.tool_calls
    WHERE run_id IS NOT NULL
    GROUP BY run_id
), external AS (
    SELECT run_id,
           count(*) AS external_calls,
           count(*) FILTER (WHERE status = 'failed') AS failed_external_calls,
           sum(duration_ms) AS external_compute_ms,
           sum(result_count) AS external_result_count
    FROM telemetry.external_calls
    WHERE run_id IS NOT NULL
    GROUP BY run_id
)
SELECT r.run_id, r.session_id, r.module, r.operation, r.section, r.status,
       r.started_at, r.completed_at, r.duration_ms AS wall_duration_ms,
       COALESCE(l.llm_calls, 0) AS llm_calls,
       COALESCE(l.failed_llm_calls, 0) AS failed_llm_calls,
       COALESCE(l.input_tokens, 0) AS input_tokens,
       COALESCE(l.output_tokens, 0) AS output_tokens,
       COALESCE(l.total_tokens, 0) AS total_tokens,
       COALESCE(l.llm_compute_ms, 0) AS llm_compute_ms,
       COALESCE(t.tool_calls, 0) AS tool_calls,
       COALESCE(t.failed_tool_calls, 0) AS failed_tool_calls,
       COALESCE(t.manual_tool_calls, 0) AS manual_tool_calls,
       COALESCE(t.denied_tool_calls, 0) AS denied_tool_calls,
       COALESCE(t.tool_compute_ms, 0) AS tool_compute_ms,
       COALESCE(t.approval_wait_ms, 0) AS approval_wait_ms,
       COALESCE(e.external_calls, 0) AS external_calls,
       COALESCE(e.failed_external_calls, 0) AS failed_external_calls,
       COALESCE(e.external_compute_ms, 0) AS external_compute_ms,
       COALESCE(e.external_result_count, 0) AS external_result_count
FROM telemetry.workflow_runs r
LEFT JOIN llm l USING (run_id)
LEFT JOIN tools t USING (run_id)
LEFT JOIN external e USING (run_id);

INSERT INTO telemetry.schema_migrations (version)
VALUES ('001_telemetry')
ON CONFLICT (version) DO NOTHING;

COMMIT;
