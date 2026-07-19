CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS sensory_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,
  source_thread_id TEXT,
  source_account_id TEXT,
  source_container_id TEXT,
  source_record_id TEXT,
  source_record_hash TEXT,
  raw_type TEXT NOT NULL,
  raw_label TEXT,
  raw_text TEXT NOT NULL,
  normalized_text TEXT,
  occurred_at TIMESTAMPTZ,
  synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  project_path TEXT,
  thread_title TEXT,
  source_uri TEXT,
  sensitivity_level TEXT NOT NULL DEFAULT 'normal',
  noise_level TEXT NOT NULL DEFAULT 'normal',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'ingested',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sensory_records_source_hash
  ON sensory_records (source, source_record_hash)
  WHERE source_record_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sensory_records_source_synced_at
  ON sensory_records (source, synced_at DESC);

CREATE INDEX IF NOT EXISTS idx_sensory_records_container_occurred_at
  ON sensory_records (source_container_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS connector_sync_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  connector_id TEXT NOT NULL,
  source TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'completed',
  total_records INTEGER NOT NULL DEFAULT 0,
  inserted_records INTEGER NOT NULL DEFAULT 0,
  updated_records INTEGER NOT NULL DEFAULT 0,
  error_message TEXT NOT NULL DEFAULT '',
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_connector_sync_runs_source_completed_at
  ON connector_sync_runs (source, completed_at DESC);

CREATE TABLE IF NOT EXISTS runtime_configs (
  id TEXT PRIMARY KEY,
  category TEXT NOT NULL CHECK (category IN ('connector', 'model', 'agent')),
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  enabled BOOLEAN NOT NULL DEFAULT false,
  status TEXT NOT NULL DEFAULT 'not_configured',
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS link_agents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name TEXT NOT NULL,
  public_key TEXT NOT NULL DEFAULT '',
  token_hash TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'online',
  version TEXT NOT NULL DEFAULT '',
  operating_system TEXT NOT NULL DEFAULT '',
  connector_states JSONB NOT NULL DEFAULT '[]'::jsonb,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS agent_pairing_codes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code_hash TEXT NOT NULL UNIQUE,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_commands (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id UUID NOT NULL REFERENCES link_agents(id) ON DELETE CASCADE,
  command_type TEXT NOT NULL CHECK (command_type IN ('sync_connector', 'validate_connector', 'refresh_config', 'pause_connector')),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivered', 'completed', 'failed', 'cancelled')),
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  delivered_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  result JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS agent_ingestion_batches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id UUID NOT NULL REFERENCES link_agents(id) ON DELETE CASCADE,
  batch_id TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'completed',
  record_count INTEGER NOT NULL DEFAULT 0,
  inserted_records INTEGER NOT NULL DEFAULT 0,
  updated_records INTEGER NOT NULL DEFAULT 0,
  cursor_before JSONB NOT NULL DEFAULT '{}'::jsonb,
  cursor_after JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (agent_id, batch_id)
);

CREATE INDEX IF NOT EXISTS idx_link_agents_last_seen ON link_agents (last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_commands_pending ON agent_commands (agent_id, status, expires_at);
