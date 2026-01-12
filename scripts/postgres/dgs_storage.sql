BEGIN;

CREATE TABLE IF NOT EXISTS dgs_jobs (
  job_id TEXT PRIMARY KEY,
  request JSONB NOT NULL,
  status TEXT NOT NULL,
  phase TEXT NOT NULL,
  subphase TEXT,
  total_steps INTEGER,
  completed_steps INTEGER,
  progress DOUBLE PRECISION,
  logs JSONB NOT NULL,
  result_json JSONB,
  artifacts JSONB,
  validation JSONB,
  cost JSONB,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  ttl INTEGER,
  idempotency_key TEXT
);

CREATE INDEX IF NOT EXISTS dgs_jobs_status_created_idx ON dgs_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS dgs_jobs_idempotency_idx ON dgs_jobs (idempotency_key);

CREATE TABLE IF NOT EXISTS dgs_lessons (
  lesson_id TEXT PRIMARY KEY,
  topic TEXT NOT NULL,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  provider_a TEXT NOT NULL,
  model_a TEXT NOT NULL,
  provider_b TEXT NOT NULL,
  model_b TEXT NOT NULL,
  lesson_json TEXT NOT NULL,
  status TEXT NOT NULL,
  latency_ms INTEGER NOT NULL,
  idempotency_key TEXT,
  tags TEXT[]
);

CREATE INDEX IF NOT EXISTS dgs_lessons_idempotency_idx ON dgs_lessons (idempotency_key);

CREATE TABLE IF NOT EXISTS dgs_storage_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO dgs_storage_meta (key, value)
VALUES ('schema_version', '1')
ON CONFLICT (key)
DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();

COMMIT;
