BEGIN;

CREATE TABLE IF NOT EXISTS llm_call_audit (
  id UUID PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  timestamp_request TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  timestamp_response TIMESTAMPTZ,
  started_at TIMESTAMPTZ NOT NULL,
  duration_ms INTEGER NOT NULL,
  agent TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  lesson_topic TEXT,
  request_payload TEXT NOT NULL,
  response_payload TEXT,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  total_tokens INTEGER,
  request_type TEXT NOT NULL,
  purpose TEXT,
  call_index TEXT,
  job_id TEXT,
  status TEXT NOT NULL,
  error_message TEXT
);

ALTER TABLE llm_call_audit
  ADD COLUMN IF NOT EXISTS timestamp_request TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS timestamp_response TIMESTAMPTZ;

UPDATE llm_call_audit
SET timestamp_request = COALESCE(timestamp_request, started_at, created_at)
WHERE timestamp_request IS NULL;

CREATE INDEX IF NOT EXISTS llm_call_audit_created_at_idx ON llm_call_audit (created_at);
CREATE INDEX IF NOT EXISTS llm_call_audit_agent_idx ON llm_call_audit (agent);
CREATE INDEX IF NOT EXISTS llm_call_audit_model_idx ON llm_call_audit (model);
CREATE INDEX IF NOT EXISTS llm_call_audit_topic_idx ON llm_call_audit (lesson_topic);

CREATE TABLE IF NOT EXISTS llm_audit_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO llm_audit_meta (key, value)
VALUES ('schema_version', '2')
ON CONFLICT (key)
DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();

COMMIT;
