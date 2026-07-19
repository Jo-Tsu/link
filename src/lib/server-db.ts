import { createHash, randomBytes } from "node:crypto";
import postgres from "postgres";

let sqlClient: postgres.Sql | undefined;

function getSql() {
  const databaseUrl = process.env.DATABASE_URL || "";
  if (!databaseUrl) return undefined;
  if (!sqlClient) {
    sqlClient = postgres(databaseUrl, {
      max: 4,
      idle_timeout: 20,
      connect_timeout: 5,
    });
  }
  return sqlClient;
}

export type ConnectorStatusRecord = {
  source: string;
  connectorId: string;
  connectorName: string;
  originType: string;
  originLabel: string;
  readScope: string;
  syncMode: string;
  storageTable: string;
  containerCount: number;
  threadCount: number;
  total: number;
  errors: number;
  latestSyncedAt: string;
  latestOccurredAt: string;
  rawTypes: Array<{ type: string; count: number }>;
};

export type DataSourceOriginRecord = {
  source: string;
  connectorId: string;
  connectorName: string;
  originKey: string;
  sourceContainerId: string;
  sourceThreadId: string;
  sourceTitle: string;
  projectPath: string;
  sourceUri: string;
  recordCount: number;
  errors: number;
  firstOccurredAt: string;
  latestOccurredAt: string;
  latestSyncedAt: string;
  rawTypes: Array<{ type: string; count: number }>;
};

export type SensoryRecordListItem = {
  id: string;
  source: string;
  sourceThreadId: string;
  sourceContainerId: string;
  sourceRecordId: string;
  rawType: string;
  rawLabel: string;
  rawText: string;
  summary: string;
  occurredAt: string;
  syncedAt: string;
  projectPath: string;
  threadTitle: string;
  sourceUri: string;
  sensitivityLevel: string;
  noiseLevel: string;
  status: string;
  metadata: Record<string, unknown>;
};

export type SensoryRecordListParams = {
  source?: string;
  rawType?: string;
  threadIds?: string[];
  containerIds?: string[];
  originKeys?: string[];
  query?: string;
  limit?: number;
  offset?: number;
};

export type RuntimeConfigRecord = {
  id: string;
  category: "connector" | "model" | "agent";
  name: string;
  description: string;
  enabled: boolean;
  status: string;
  config: Record<string, unknown>;
  updatedAt: string;
};

export type AgentRecord = {
  id: string;
  displayName: string;
  status: string;
  version: string;
  operatingSystem: string;
  lastSeenAt: string;
  createdAt: string;
};

export type AgentUploadRecord = {
  source: string;
  sourceAccountId?: string;
  sourceThreadId?: string;
  sourceContainerId?: string;
  sourceRecordId: string;
  rawType: string;
  rawLabel?: string;
  rawText: string;
  summary?: string;
  occurredAt?: string;
  projectPath?: string;
  threadTitle?: string;
  sourceUri?: string;
  metadata?: Record<string, unknown>;
};

type CodexHistoryInput = { text: string; at: string };
type CodexHistoryOutput = { text: string; at: string };
type CodexHistoryTool = { name: string; count: number };
type CodexHistoryCliCommand = {
  title: string;
  cmd: string;
  workdir: string;
  at: string;
  output: string;
};

type CodexHistorySnapshot = {
  generatedAt: string;
  codexHome: string;
  threads: Array<{
    id: string;
    title: string;
    startedAt: string;
    updatedAt: string;
    cwd: string;
    model: string;
    source: string;
    archived: boolean;
    file: string;
    conversation?: {
      inputs: CodexHistoryInput[];
      outputs: CodexHistoryOutput[];
      inputOutputPairs: number;
      duplicateMessages: number;
    };
    toolSummary?: {
      tools: CodexHistoryTool[];
      cliCommands: CodexHistoryCliCommand[];
    };
    ingestion?: { skillRefs: string[] };
  }>;
};

type SensoryRecordInput = {
  sourceThreadId: string;
  sourceContainerId: string;
  sourceRecordId: string;
  rawType: "user_input" | "codex_output" | "cli" | "tool" | "skill";
  rawLabel: string;
  rawText: string;
  occurredAt: string;
  projectPath: string;
  threadTitle: string;
  sourceUri: string;
  summary: string;
  metadata: Record<string, unknown>;
};

let schemaReady = false;
let schemaPromise: Promise<void> | undefined;

function sanitizeText(value: string) {
  return value.replaceAll("\u0000", "");
}

function sanitizeMetadata(value: unknown): unknown {
  if (typeof value === "string") return sanitizeText(value);
  if (Array.isArray(value)) return value.map(sanitizeMetadata);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, sanitizeMetadata(item)]),
    );
  }
  return value;
}

function compactText(value: string, limit = 280) {
  const normalized = sanitizeText(value).replace(/\s+/g, " ").trim();
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized;
}

function detectSensitivity(value: string) {
  return /sk-[a-zA-Z0-9_-]{12,}|api[_-]?key|token|password|secret|credential/i.test(value)
    ? "sensitive"
    : "normal";
}

function detectNoise(value: string) {
  if (value.length < 12) return "high";
  if (/[a-f0-9]{32,}|[0-9a-f]{8}-[0-9a-f-]{12,}/i.test(value)) return "medium";
  return "normal";
}

function getConnectorDescriptor(source: string) {
  if (source === "codex") {
    return {
      connectorId: "codex_local",
      connectorName: "Codex 本地历史",
      originType: "link_agent",
      originLabel: process.env.CODEX_HOME || "~/.codex",
      readScope: "session_index.jsonl、sessions/**/*.jsonl、archived_sessions/*.jsonl",
      syncMode: "manual_pull",
      storageTable: "sensory_records",
    };
  }

  return {
    connectorId: source,
    connectorName: source,
    originType: "link_agent_connector",
    originLabel: source,
    readScope: "由 LinkAgent 授权的范围",
    syncMode: "connector_defined",
    storageTable: "sensory_records",
  };
}

async function ensureIntakeSchema(sql: postgres.Sql) {
  if (schemaReady) return;
  if (!schemaPromise) {
    schemaPromise = (async () => {
      await sql`CREATE EXTENSION IF NOT EXISTS pgcrypto`;
      await sql`
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
          summary TEXT,
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
        )
      `;
      await sql`ALTER TABLE sensory_records ADD COLUMN IF NOT EXISTS source_record_hash TEXT`;
      await sql`ALTER TABLE sensory_records ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb`;
      await sql`
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sensory_records_source_hash
        ON sensory_records(source, source_record_hash)
      `;
      await sql`
        CREATE INDEX IF NOT EXISTS idx_sensory_records_source_synced
        ON sensory_records(source, synced_at DESC)
      `;
      await sql`
        CREATE INDEX IF NOT EXISTS idx_sensory_records_container
        ON sensory_records(source, source_container_id, occurred_at DESC)
      `;
      await sql`
        CREATE TABLE IF NOT EXISTS connector_sync_runs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          connector_id TEXT NOT NULL,
          source TEXT NOT NULL,
          status TEXT NOT NULL,
          total_records INTEGER NOT NULL DEFAULT 0,
          inserted_records INTEGER NOT NULL DEFAULT 0,
          updated_records INTEGER NOT NULL DEFAULT 0,
          error_message TEXT NOT NULL DEFAULT '',
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ
        )
      `;
      await sql`
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
        )
      `;
      await sql`
        INSERT INTO runtime_configs (id, category, name, description, enabled, status, config)
        VALUES
          ('codex_local', 'connector', 'Codex 本地历史', '通过 LinkAgent 只读同步 Codex 会话历史。', true, 'connected',
            '{"syncMode":"manual_pull","scope":"~/.codex"}'::jsonb),
          ('feishu', 'connector', '飞书', '待 LinkAgent 完成 OAuth 授权后接入文档、妙记与会议纪要。', false, 'not_configured',
            '{"syncMode":"incremental_pull","scope":""}'::jsonb),
          ('local_files', 'connector', '本地文件', '待选择本机目录后接入 Markdown、PDF、Word 与文本文件。', false, 'not_configured',
            '{"syncMode":"incremental_scan","scope":""}'::jsonb),
          ('codex_default', 'model', 'Codex 默认能力', '未来数据处理阶段的默认模型配置；当前不会被调用。', true, 'configured',
            '{"model":"default","baseUrl":""}'::jsonb),
          ('openai_compatible', 'model', 'OpenAI 兼容模型', '可预先填写 OpenAI 兼容服务地址与模型名称；当前不会被调用。', false, 'not_configured',
            '{"model":"","baseUrl":""}'::jsonb),
          ('ollama_local', 'model', '本地 Ollama', '可预先填写本机 Ollama 地址与模型名称；当前不会被调用。', false, 'not_configured',
            '{"model":"","baseUrl":"http://127.0.0.1:11434/v1"}'::jsonb),
          ('data_intake_agent', 'agent', '数据接入智能体', '负责未来连接器编排与异常提示；当前仅保存配置，不执行任务。', false, 'not_enabled',
            '{}'::jsonb),
          ('data_processing_agent', 'agent', '数据处理智能体', '为未来治理与提炼预留；当前不会读取或改写原始数据。', false, 'not_enabled',
            '{}'::jsonb)
        ON CONFLICT (id) DO NOTHING
      `;
      await sql`UPDATE runtime_configs SET config = config - 'source' - 'provider' - 'role'`;
      await sql`UPDATE runtime_configs SET description = replace(replace(description, '本机 Link Agent', 'LinkAgent'), '本机 Agent', 'LinkAgent')`;
      await sql`
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
        )
      `;
      await sql`
        CREATE TABLE IF NOT EXISTS agent_pairing_codes (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          code_hash TEXT NOT NULL UNIQUE,
          expires_at TIMESTAMPTZ NOT NULL,
          used_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
      `;
      await sql`
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
        )
      `;
      await sql`
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
        )
      `;
      await sql`CREATE INDEX IF NOT EXISTS idx_link_agents_last_seen ON link_agents(last_seen_at DESC)`;
      await sql`CREATE INDEX IF NOT EXISTS idx_agent_commands_pending ON agent_commands(agent_id, status, expires_at)`;
      schemaReady = true;
    })().catch((error) => {
      schemaPromise = undefined;
      throw error;
    });
  }
  await schemaPromise;
}

export async function getDatabaseStatus() {
  const sql = getSql();
  if (!sql) return { connected: false, reason: "DATABASE_URL is not configured" };
  await ensureIntakeSchema(sql);
  const [row] = await sql<Array<{ ok: number; now: string }>>`SELECT 1 AS ok, now()::text AS now`;
  return { connected: row?.ok === 1, now: row?.now };
}

export async function getRuntimeConfigs() {
  const sql = getSql();
  if (!sql) return { connected: false, configs: [] as RuntimeConfigRecord[] };
  await ensureIntakeSchema(sql);
  const rows = await sql<
    Array<{
      id: string;
      category: RuntimeConfigRecord["category"];
      name: string;
      description: string;
      enabled: boolean;
      status: string;
      config: Record<string, unknown>;
      updated_at: string;
    }>
  >`
    SELECT id, category, name, description, enabled, status, config, updated_at::text
    FROM runtime_configs ORDER BY category, name
  `;
  return {
    connected: true,
    configs: rows.map((row) => ({
      id: row.id,
      category: row.category,
      name: row.name,
      description: row.description,
      enabled: row.enabled,
      status: row.status,
      config: row.config || {},
      updatedAt: row.updated_at,
    })),
  };
}

export async function updateRuntimeConfig(
  id: string,
  input: { enabled?: boolean; status?: string; config?: Record<string, unknown> },
) {
  const sql = getSql();
  if (!sql) throw new Error("DATABASE_URL is not configured");
  await ensureIntakeSchema(sql);
  const [row] = await sql<
    Array<{
      id: string;
      category: RuntimeConfigRecord["category"];
      name: string;
      description: string;
      enabled: boolean;
      status: string;
      config: Record<string, unknown>;
      updated_at: string;
    }>
  >`
    UPDATE runtime_configs
    SET enabled = COALESCE(${input.enabled ?? null}, enabled),
      status = COALESCE(${input.status ?? null}, status),
      config = COALESCE(${input.config ? sql.json(input.config as postgres.JSONValue) : null}, config),
      updated_at = now()
    WHERE id = ${id}
    RETURNING id, category, name, description, enabled, status, config, updated_at::text
  `;
  if (!row) throw new Error("Configuration not found");
  return {
    id: row.id,
    category: row.category,
    name: row.name,
    description: row.description,
    enabled: row.enabled,
    status: row.status,
    config: row.config || {},
    updatedAt: row.updated_at,
  } satisfies RuntimeConfigRecord;
}

function tokenHash(token: string) {
  return createHash("sha256").update(token).digest("hex");
}

function safeRecordText(value: unknown, limit = 100_000) {
  return sanitizeText(String(value ?? "")).slice(0, limit);
}

async function authenticateAgent(sql: postgres.Sql, agentId: string, token: string) {
  if (!agentId || !token) throw new Error("Agent credentials are required");
  const [agent] = await sql<Array<{ id: string; revoked_at: string | null }>>`
    SELECT id::text, revoked_at::text FROM link_agents
    WHERE id = ${agentId}::uuid AND token_hash = ${tokenHash(token)}
  `;
  if (!agent || agent.revoked_at) throw new Error("Agent authentication failed");
  return agent;
}

export async function createAgentPairingCode() {
  const sql = getSql();
  if (!sql) throw new Error("DATABASE_URL is not configured");
  await ensureIntakeSchema(sql);
  const code = randomBytes(18).toString("base64url");
  await sql`
    INSERT INTO agent_pairing_codes (code_hash, expires_at)
    VALUES (${tokenHash(code)}, now() + interval '10 minutes')
  `;
  return { code, expiresAt: new Date(Date.now() + 10 * 60_000).toISOString() };
}

export async function getAgents() {
  const sql = getSql();
  if (!sql) return { connected: false, agents: [] as AgentRecord[] };
  await ensureIntakeSchema(sql);
  const rows = await sql<
    Array<{
      id: string;
      display_name: string;
      status: string;
      version: string;
      operating_system: string;
      last_seen_at: string;
      created_at: string;
    }>
  >`
    SELECT id::text, display_name, CASE WHEN last_seen_at > now() - interval '90 seconds' THEN 'online' ELSE 'offline' END AS status,
      version, operating_system, last_seen_at::text, created_at::text
    FROM link_agents WHERE revoked_at IS NULL ORDER BY last_seen_at DESC
  `;
  return {
    connected: true,
    agents: rows.map((row) => ({
      id: row.id,
      displayName: row.display_name,
      status: row.status,
      version: row.version,
      operatingSystem: row.operating_system,
      lastSeenAt: row.last_seen_at,
      createdAt: row.created_at,
    })),
  };
}

export async function pairAgent(input: {
  code: string;
  displayName: string;
  publicKey: string;
  version?: string;
  operatingSystem?: string;
}) {
  const sql = getSql();
  if (!sql) throw new Error("DATABASE_URL is not configured");
  await ensureIntakeSchema(sql);
  return sql.begin(async (tx) => {
    const [pairing] = await tx<Array<{ id: string }>>`
      SELECT id::text FROM agent_pairing_codes
      WHERE code_hash = ${tokenHash(input.code)} AND used_at IS NULL AND expires_at > now()
      FOR UPDATE
    `;
    if (!pairing) throw new Error("Pairing code is invalid or expired");
    await tx`UPDATE agent_pairing_codes SET used_at = now() WHERE id = ${pairing.id}::uuid`;
    const token = randomBytes(32).toString("base64url");
    const [agent] = await tx<Array<{ id: string; display_name: string }>>`
      INSERT INTO link_agents (display_name, public_key, token_hash, version, operating_system)
      VALUES (${safeRecordText(input.displayName || "LinkAgent", 120)}, ${safeRecordText(input.publicKey, 8_000)},
        ${tokenHash(token)}, ${input.version || ""}, ${input.operatingSystem || ""})
      RETURNING id::text, display_name
    `;
    return { agentId: agent.id, displayName: agent.display_name, token };
  });
}

export async function heartbeatAgent(input: {
  agentId: string;
  token: string;
  version?: string;
  operatingSystem?: string;
  connectorStates?: unknown;
  lastCommandId?: string;
}) {
  const sql = getSql();
  if (!sql) throw new Error("DATABASE_URL is not configured");
  await ensureIntakeSchema(sql);
  await authenticateAgent(sql, input.agentId, input.token);
  await sql`
    UPDATE link_agents SET status = 'online', version = ${input.version || ""},
      operating_system = ${input.operatingSystem || ""},
      connector_states = ${sql.json((input.connectorStates ?? []) as postgres.JSONValue)}, last_seen_at = now()
    WHERE id = ${input.agentId}::uuid
  `;
  const commands = await sql<
    Array<{ id: string; command_type: string; payload: Record<string, unknown> }>
  >`
    UPDATE agent_commands SET status = 'delivered', delivered_at = now()
    WHERE id IN (
      SELECT id FROM agent_commands
      WHERE agent_id = ${input.agentId}::uuid AND status = 'pending' AND expires_at > now()
      ORDER BY created_at ASC LIMIT 20
      FOR UPDATE SKIP LOCKED
    )
    RETURNING id::text, command_type, payload
  `;
  return {
    commands: commands.map((command) => ({
      id: command.id,
      type: command.command_type,
      payload: command.payload || {},
    })),
  };
}

export async function enqueueAgentCommand(input: {
  agentId: string;
  type: "sync_connector" | "validate_connector" | "refresh_config" | "pause_connector";
  payload?: Record<string, unknown>;
}) {
  const sql = getSql();
  if (!sql) throw new Error("DATABASE_URL is not configured");
  await ensureIntakeSchema(sql);
  const [command] = await sql<Array<{ id: string }>>`
    INSERT INTO agent_commands (agent_id, command_type, payload, expires_at)
    VALUES (${input.agentId}::uuid, ${input.type}, ${sql.json((input.payload ?? {}) as postgres.JSONValue)}, now() + interval '24 hours')
    RETURNING id::text
  `;
  return { commandId: command.id };
}

export async function completeAgentCommand(input: {
  agentId: string;
  token: string;
  commandId: string;
  success: boolean;
  result?: Record<string, unknown>;
}) {
  const sql = getSql();
  if (!sql) throw new Error("DATABASE_URL is not configured");
  await ensureIntakeSchema(sql);
  await authenticateAgent(sql, input.agentId, input.token);
  const [command] = await sql<Array<{ id: string }>>`
    UPDATE agent_commands SET status = ${input.success ? "completed" : "failed"}, completed_at = now(),
      result = ${sql.json((input.result ?? {}) as postgres.JSONValue)}
    WHERE id = ${input.commandId}::uuid AND agent_id = ${input.agentId}::uuid AND status = 'delivered'
    RETURNING id::text
  `;
  if (!command) throw new Error("Command not found or no longer actionable");
  return { commandId: command.id };
}

export async function ingestAgentBatch(input: {
  agentId: string;
  token: string;
  batchId: string;
  connectorId: string;
  cursorBefore?: Record<string, unknown>;
  cursorAfter?: Record<string, unknown>;
  records: AgentUploadRecord[];
}) {
  const sql = getSql();
  if (!sql) throw new Error("DATABASE_URL is not configured");
  await ensureIntakeSchema(sql);
  await authenticateAgent(sql, input.agentId, input.token);
  if (!/^[a-zA-Z0-9._:-]{8,160}$/.test(input.batchId)) throw new Error("Invalid batch id");
  if (!/^[a-zA-Z0-9._:-]{2,120}$/.test(input.connectorId)) throw new Error("Invalid connector id");
  if (!Array.isArray(input.records) || input.records.length === 0 || input.records.length > 200) {
    throw new Error("A batch must contain 1 to 200 records");
  }
  return sql.begin(async (tx) => {
    const [existing] = await tx<
      Array<{ record_count: number; inserted_records: number; updated_records: number }>
    >`
      SELECT record_count, inserted_records, updated_records FROM agent_ingestion_batches
      WHERE agent_id = ${input.agentId}::uuid AND batch_id = ${input.batchId} FOR UPDATE
    `;
    if (existing)
      return {
        duplicate: true,
        records: existing.record_count,
        inserted: existing.inserted_records,
        updated: existing.updated_records,
      };
    let inserted = 0;
    let updated = 0;
    for (const record of input.records) {
      const source = safeRecordText(record.source, 120);
      const sourceRecordId = safeRecordText(record.sourceRecordId, 500);
      const rawText = safeRecordText(record.rawText);
      if (!source || !sourceRecordId || !rawText)
        throw new Error("Each record requires source, sourceRecordId and rawText");
      const sourceHash = createHash("sha256").update(`${source}:${sourceRecordId}`).digest("hex");
      const [result] = await tx<Array<{ inserted: boolean }>>`
        INSERT INTO sensory_records (
          source, source_account_id, source_thread_id, source_container_id, source_record_id, source_record_hash,
          raw_type, raw_label, raw_text, normalized_text, summary, occurred_at, synced_at,
          project_path, thread_title, source_uri, sensitivity_level, noise_level, metadata, status
        ) VALUES (
          ${source}, ${safeRecordText(record.sourceAccountId, 300) || null}, ${safeRecordText(record.sourceThreadId, 500) || null},
          ${safeRecordText(record.sourceContainerId, 500) || null}, ${sourceRecordId}, ${sourceHash},
          ${safeRecordText(record.rawType || "unknown", 120)}, ${safeRecordText(record.rawLabel, 200) || null}, ${rawText},
          ${rawText.replace(/\s+/g, " ").trim()}, ${safeRecordText(record.summary, 2_000) || compactText(rawText)},
          ${safeRecordText(record.occurredAt, 80) || null}, now(), ${safeRecordText(record.projectPath, 2_000) || null},
          ${safeRecordText(record.threadTitle, 1_000) || null}, ${safeRecordText(record.sourceUri, 4_000) || null},
          ${detectSensitivity(rawText)}, ${detectNoise(rawText)},
          ${tx.json(sanitizeMetadata({ ...(record.metadata ?? {}), agent_id: input.agentId, connector_id: input.connectorId }) as postgres.JSONValue)}, 'ingested'
        ) ON CONFLICT (source, source_record_hash) DO UPDATE SET
          raw_text = EXCLUDED.raw_text, normalized_text = EXCLUDED.normalized_text, summary = EXCLUDED.summary,
          occurred_at = EXCLUDED.occurred_at, synced_at = now(), project_path = EXCLUDED.project_path,
          thread_title = EXCLUDED.thread_title, source_uri = EXCLUDED.source_uri,
          sensitivity_level = EXCLUDED.sensitivity_level, noise_level = EXCLUDED.noise_level,
          metadata = EXCLUDED.metadata, status = 'ingested'
        RETURNING (xmax = 0) AS inserted
      `;
      if (result?.inserted) inserted += 1;
      else updated += 1;
    }
    await tx`
      INSERT INTO agent_ingestion_batches (
        agent_id, batch_id, connector_id, record_count, inserted_records, updated_records, cursor_before, cursor_after
      ) VALUES (${input.agentId}::uuid, ${input.batchId}, ${input.connectorId}, ${input.records.length}, ${inserted}, ${updated},
        ${tx.json((input.cursorBefore ?? {}) as postgres.JSONValue)}, ${tx.json((input.cursorAfter ?? {}) as postgres.JSONValue)})
    `;
    await tx`
      INSERT INTO connector_sync_runs (
        connector_id, source, status, total_records, inserted_records, updated_records, metadata, completed_at
      ) VALUES (${input.connectorId}, ${input.records[0]?.source || input.connectorId}, 'completed', ${input.records.length}, ${inserted}, ${updated},
        ${tx.json({ agent_id: input.agentId, batch_id: input.batchId } as postgres.JSONValue)}, now())
    `;
    return { duplicate: false, records: input.records.length, inserted, updated };
  });
}

function createCodexSensoryRecords(snapshot: CodexHistorySnapshot) {
  const records: SensoryRecordInput[] = [];
  for (const thread of snapshot.threads) {
    const baseMetadata = {
      connector: "codex_local",
      generated_at: snapshot.generatedAt,
      thread_id: thread.id,
      thread_source: thread.source,
      archived: thread.archived,
      model: thread.model,
    };
    thread.conversation?.inputs.forEach((item, index) => {
      records.push({
        sourceThreadId: thread.id,
        sourceContainerId: thread.id,
        sourceRecordId: `${thread.id}:user_input:${index}:${item.at || ""}`,
        rawType: "user_input",
        rawLabel: "Codex 用户消息",
        rawText: item.text,
        occurredAt: item.at || thread.updatedAt || thread.startedAt,
        projectPath: thread.cwd || "",
        threadTitle: thread.title,
        sourceUri: thread.file,
        summary: compactText(item.text),
        metadata: { ...baseMetadata, message_index: index },
      });
    });
    thread.conversation?.outputs.forEach((item, index) => {
      records.push({
        sourceThreadId: thread.id,
        sourceContainerId: thread.id,
        sourceRecordId: `${thread.id}:codex_output:${index}:${item.at || ""}`,
        rawType: "codex_output",
        rawLabel: "Codex 输出",
        rawText: item.text,
        occurredAt: item.at || thread.updatedAt || thread.startedAt,
        projectPath: thread.cwd || "",
        threadTitle: thread.title,
        sourceUri: thread.file,
        summary: compactText(item.text),
        metadata: { ...baseMetadata, message_index: index },
      });
    });
    thread.toolSummary?.cliCommands.forEach((command, index) => {
      const rawText = `${command.title}：${command.cmd}；工作目录：${command.workdir || thread.cwd || "未知"}；输出摘要：${command.output || "暂无"}`;
      records.push({
        sourceThreadId: thread.id,
        sourceContainerId: thread.id,
        sourceRecordId: `${thread.id}:cli:${index}:${command.at || ""}`,
        rawType: "cli",
        rawLabel: "CLI",
        rawText,
        occurredAt: command.at || thread.updatedAt || thread.startedAt,
        projectPath: command.workdir || thread.cwd || "",
        threadTitle: thread.title,
        sourceUri: thread.file,
        summary: compactText(`${command.title}：${command.cmd}`),
        metadata: { ...baseMetadata, command: command.cmd, command_title: command.title },
      });
    });
    thread.toolSummary?.tools.forEach((tool, index) => {
      const rawText = `${tool.name} 工具在该线程中调用 ${tool.count} 次。`;
      records.push({
        sourceThreadId: thread.id,
        sourceContainerId: thread.id,
        sourceRecordId: `${thread.id}:tool:${index}:${tool.name}`,
        rawType: "tool",
        rawLabel: "工具调用",
        rawText,
        occurredAt: thread.updatedAt || thread.startedAt,
        projectPath: thread.cwd || "",
        threadTitle: thread.title,
        sourceUri: thread.file,
        summary: rawText,
        metadata: { ...baseMetadata, tool_name: tool.name, tool_count: tool.count },
      });
    });
    thread.ingestion?.skillRefs.forEach((skill, index) => {
      const rawText = `skill:${skill}`;
      records.push({
        sourceThreadId: thread.id,
        sourceContainerId: thread.id,
        sourceRecordId: `${thread.id}:skill:${index}:${skill}`,
        rawType: "skill",
        rawLabel: "技能线索",
        rawText,
        occurredAt: thread.updatedAt || thread.startedAt,
        projectPath: thread.cwd || "",
        threadTitle: thread.title,
        sourceUri: thread.file,
        summary: rawText,
        metadata: { ...baseMetadata, skill },
      });
    });
  }
  return records.filter((record) => record.rawText.trim());
}

export async function saveCodexSensoryRecords(snapshot: CodexHistorySnapshot) {
  const sql = getSql();
  if (!sql) return { connected: false, records: 0, inserted: 0, updated: 0 };
  await ensureIntakeSchema(sql);
  const records = createCodexSensoryRecords(snapshot);
  let inserted = 0;
  let updated = 0;

  await sql.begin(async (tx) => {
    for (const record of records) {
      const rawText = sanitizeText(record.rawText);
      const hash = createHash("sha256").update(record.sourceRecordId).digest("hex");
      const [result] = await tx<Array<{ inserted: boolean }>>`
        INSERT INTO sensory_records (
          source, source_thread_id, source_container_id, source_record_id, source_record_hash,
          raw_type, raw_label, raw_text, normalized_text, summary, occurred_at, synced_at,
          project_path, thread_title, source_uri, sensitivity_level, noise_level, metadata, status
        ) VALUES (
          'codex', ${record.sourceThreadId}, ${record.sourceContainerId}, ${record.sourceRecordId}, ${hash},
          ${record.rawType}, ${record.rawLabel}, ${rawText}, ${rawText.replace(/\s+/g, " ").trim()},
          ${sanitizeText(record.summary)}, ${record.occurredAt || null}, now(), ${record.projectPath || null},
          ${record.threadTitle || null}, ${record.sourceUri || null}, ${detectSensitivity(rawText)},
          ${detectNoise(rawText)}, ${tx.json(sanitizeMetadata(record.metadata) as postgres.JSONValue)}, 'ingested'
        ) ON CONFLICT (source, source_record_hash) DO UPDATE SET
          raw_text = EXCLUDED.raw_text,
          normalized_text = EXCLUDED.normalized_text,
          summary = EXCLUDED.summary,
          occurred_at = EXCLUDED.occurred_at,
          synced_at = now(),
          project_path = EXCLUDED.project_path,
          thread_title = EXCLUDED.thread_title,
          source_uri = EXCLUDED.source_uri,
          sensitivity_level = EXCLUDED.sensitivity_level,
          noise_level = EXCLUDED.noise_level,
          metadata = EXCLUDED.metadata,
          status = 'ingested'
        RETURNING (xmax = 0) AS inserted
      `;
      if (result?.inserted) inserted += 1;
      else updated += 1;
    }
    await tx`
      INSERT INTO connector_sync_runs (
        connector_id, source, status, total_records, inserted_records, updated_records, completed_at
      ) VALUES ('codex_local', 'codex', 'completed', ${records.length}, ${inserted}, ${updated}, now())
    `;
  });
  return { connected: true, records: records.length, inserted, updated };
}

export async function getConnectorStatus() {
  const sql = getSql();
  if (!sql) return { connected: false, connectors: [] as ConnectorStatusRecord[] };
  await ensureIntakeSchema(sql);
  const rows = await sql<
    Array<{
      source: string;
      total: string;
      errors: string;
      latest_synced_at: string | null;
      latest_occurred_at: string | null;
    }>
  >`
    SELECT source, count(*)::text AS total,
      count(*) FILTER (WHERE status = 'error')::text AS errors,
      max(synced_at)::text AS latest_synced_at, max(occurred_at)::text AS latest_occurred_at
    FROM sensory_records GROUP BY source ORDER BY source
  `;
  const rawTypes = await sql<Array<{ source: string; raw_type: string; count: string }>>`
    SELECT source, raw_type, count(*)::text AS count FROM sensory_records
    GROUP BY source, raw_type ORDER BY source, raw_type
  `;
  const containers = await sql<Array<{ source: string; count: string }>>`
    SELECT source, count(DISTINCT COALESCE(NULLIF(source_container_id, ''), NULLIF(source_thread_id, ''), NULLIF(source_uri, ''), 'unknown'))::text AS count
    FROM sensory_records GROUP BY source
  `;
  const typesBySource = new Map<string, Array<{ type: string; count: number }>>();
  rawTypes.forEach((row) => {
    const items = typesBySource.get(row.source) ?? [];
    items.push({ type: row.raw_type, count: Number(row.count) });
    typesBySource.set(row.source, items);
  });
  const containersBySource = new Map(containers.map((row) => [row.source, Number(row.count)]));
  return {
    connected: true,
    connectors: rows.map((row) => ({
      source: row.source,
      ...getConnectorDescriptor(row.source),
      containerCount: containersBySource.get(row.source) ?? 0,
      threadCount: containersBySource.get(row.source) ?? 0,
      total: Number(row.total),
      errors: Number(row.errors),
      latestSyncedAt: row.latest_synced_at || "",
      latestOccurredAt: row.latest_occurred_at || "",
      rawTypes: typesBySource.get(row.source) ?? [],
    })),
  };
}

export async function getDataSourceOrigins(
  params: { source?: string; query?: string; limit?: number; offset?: number } = {},
) {
  const sql = getSql();
  if (!sql)
    return {
      connected: false,
      total: 0,
      limit: 0,
      offset: 0,
      origins: [] as DataSourceOriginRecord[],
    };
  await ensureIntakeSchema(sql);
  const source = params.source && params.source !== "all" ? params.source : null;
  const query = params.query?.trim() || null;
  const pattern = query ? `%${query}%` : null;
  const limit = Math.min(Math.max(Number(params.limit ?? 30), 1), 100);
  const offset = Math.max(Number(params.offset ?? 0), 0);
  const rows = await sql<
    Array<{
      source: string;
      origin_key: string;
      source_container_id: string | null;
      source_thread_id: string | null;
      source_title: string | null;
      project_path: string | null;
      source_uri: string | null;
      record_count: string;
      errors: string;
      first_occurred_at: string | null;
      latest_occurred_at: string | null;
      latest_synced_at: string | null;
    }>
  >`
    WITH base AS (
      SELECT *, COALESCE(NULLIF(source_container_id, ''), NULLIF(source_thread_id, ''), NULLIF(source_uri, ''), 'unknown') AS origin_key
      FROM sensory_records
      WHERE (${source}::text IS NULL OR source = ${source})
    ), matched_origins AS (
      SELECT DISTINCT source, origin_key FROM base
      WHERE (${pattern}::text IS NULL OR source ILIKE ${pattern} OR thread_title ILIKE ${pattern}
        OR project_path ILIKE ${pattern} OR source_uri ILIKE ${pattern})
    ), filtered AS (
      SELECT base.* FROM base
      JOIN matched_origins USING (source, origin_key)
    )
    SELECT source, origin_key, max(NULLIF(source_container_id, '')) AS source_container_id,
      max(NULLIF(source_thread_id, '')) AS source_thread_id, max(NULLIF(thread_title, '')) AS source_title,
      max(NULLIF(project_path, '')) AS project_path, max(NULLIF(source_uri, '')) AS source_uri,
      count(*)::text AS record_count, count(*) FILTER (WHERE status = 'error')::text AS errors,
      min(occurred_at)::text AS first_occurred_at, max(occurred_at)::text AS latest_occurred_at,
      max(synced_at)::text AS latest_synced_at
    FROM filtered GROUP BY source, origin_key
    ORDER BY max(synced_at) DESC NULLS LAST, origin_key LIMIT ${limit} OFFSET ${offset}
  `;
  const [countRow] = await sql<Array<{ total: string }>>`
    WITH base AS (
      SELECT source, thread_title, project_path, source_uri,
        COALESCE(NULLIF(source_container_id, ''), NULLIF(source_thread_id, ''), NULLIF(source_uri, ''), 'unknown') AS origin_key
      FROM sensory_records WHERE (${source}::text IS NULL OR source = ${source})
    )
    SELECT count(*)::text AS total FROM (
      SELECT DISTINCT source, origin_key FROM base
      WHERE (${pattern}::text IS NULL OR source ILIKE ${pattern} OR thread_title ILIKE ${pattern}
        OR project_path ILIKE ${pattern} OR source_uri ILIKE ${pattern})
    ) matched_origins
  `;
  const visibleOriginKeys = rows.map((row) => row.origin_key);
  const typeRows = visibleOriginKeys.length
    ? await sql<Array<{ source: string; origin_key: string; raw_type: string; count: string }>>`
        SELECT source, COALESCE(NULLIF(source_container_id, ''), NULLIF(source_thread_id, ''), NULLIF(source_uri, ''), 'unknown') AS origin_key,
          raw_type, count(*)::text AS count
        FROM sensory_records
        WHERE (${source}::text IS NULL OR source = ${source})
          AND COALESCE(NULLIF(source_container_id, ''), NULLIF(source_thread_id, ''), NULLIF(source_uri, ''), 'unknown') IN ${sql(visibleOriginKeys)}
        GROUP BY source, origin_key, raw_type
      `
    : [];
  const typesByOrigin = new Map<string, Array<{ type: string; count: number }>>();
  typeRows.forEach((row) => {
    const key = `${row.source}\u0000${row.origin_key}`;
    const items = typesByOrigin.get(key) ?? [];
    items.push({ type: row.raw_type, count: Number(row.count) });
    typesByOrigin.set(key, items);
  });
  return {
    connected: true,
    total: Number(countRow?.total ?? 0),
    limit,
    offset,
    origins: rows.map((row) => {
      const connector = getConnectorDescriptor(row.source);
      return {
        source: row.source,
        connectorId: connector.connectorId,
        connectorName: connector.connectorName,
        originKey: row.origin_key,
        sourceContainerId: row.source_container_id || "",
        sourceThreadId: row.source_thread_id || "",
        sourceTitle: row.source_title || "",
        projectPath: row.project_path || "",
        sourceUri: row.source_uri || "",
        recordCount: Number(row.record_count),
        errors: Number(row.errors),
        firstOccurredAt: row.first_occurred_at || "",
        latestOccurredAt: row.latest_occurred_at || "",
        latestSyncedAt: row.latest_synced_at || "",
        rawTypes: typesByOrigin.get(`${row.source}\u0000${row.origin_key}`) ?? [],
      };
    }),
  };
}

export async function getSensoryRecords(params: SensoryRecordListParams = {}) {
  const sql = getSql();
  if (!sql)
    return {
      connected: false,
      total: 0,
      limit: 0,
      offset: 0,
      records: [] as SensoryRecordListItem[],
    };
  await ensureIntakeSchema(sql);
  const source = params.source && params.source !== "all" ? params.source : null;
  const rawType = params.rawType && params.rawType !== "all" ? params.rawType : null;
  const threadIds = params.threadIds?.map((id) => id.trim()).filter(Boolean) ?? [];
  const containerIds = params.containerIds?.map((id) => id.trim()).filter(Boolean) ?? [];
  const originKeys = params.originKeys?.map((id) => id.trim()).filter(Boolean) ?? [];
  const query = params.query?.trim() || null;
  const pattern = query ? `%${query}%` : null;
  const limit = Math.min(Math.max(Number(params.limit ?? 80), 1), 200);
  const offset = Math.max(Number(params.offset ?? 0), 0);
  const threadFilter = threadIds.length ? sql`AND source_thread_id IN ${sql(threadIds)}` : sql``;
  const containerFilter = containerIds.length
    ? sql`AND source_container_id IN ${sql(containerIds)}`
    : sql``;
  const originFilter = originKeys.length
    ? sql`AND COALESCE(NULLIF(source_container_id, ''), NULLIF(source_thread_id, ''), NULLIF(source_uri, ''), 'unknown') IN ${sql(originKeys)}`
    : sql``;
  const [countRow] = await sql<Array<{ total: string }>>`
    SELECT count(*)::text AS total FROM sensory_records
    WHERE (${source}::text IS NULL OR source = ${source}) AND (${rawType}::text IS NULL OR raw_type = ${rawType})
      ${threadFilter}
      ${containerFilter}
      ${originFilter}
      AND (${pattern}::text IS NULL OR raw_text ILIKE ${pattern} OR summary ILIKE ${pattern}
        OR thread_title ILIKE ${pattern} OR project_path ILIKE ${pattern})
  `;
  const rows = await sql<
    Array<{
      id: string;
      source: string;
      source_thread_id: string | null;
      source_container_id: string | null;
      source_record_id: string | null;
      raw_type: string;
      raw_label: string | null;
      raw_text: string;
      summary: string | null;
      occurred_at: string | null;
      synced_at: string;
      project_path: string | null;
      thread_title: string | null;
      source_uri: string | null;
      sensitivity_level: string;
      noise_level: string;
      status: string;
      metadata: Record<string, unknown> | null;
    }>
  >`
    SELECT id::text, source, source_thread_id, source_container_id, source_record_id, raw_type, raw_label,
      raw_text, summary, occurred_at::text, synced_at::text, project_path, thread_title, source_uri,
      sensitivity_level, noise_level, status, metadata
    FROM sensory_records
    WHERE (${source}::text IS NULL OR source = ${source}) AND (${rawType}::text IS NULL OR raw_type = ${rawType})
      ${threadFilter}
      ${containerFilter}
      ${originFilter}
      AND (${pattern}::text IS NULL OR raw_text ILIKE ${pattern} OR summary ILIKE ${pattern}
        OR thread_title ILIKE ${pattern} OR project_path ILIKE ${pattern})
    ORDER BY occurred_at DESC NULLS LAST, synced_at DESC, id DESC LIMIT ${limit} OFFSET ${offset}
  `;
  return {
    connected: true,
    total: Number(countRow?.total ?? 0),
    limit,
    offset,
    records: rows.map((row) => ({
      id: row.id,
      source: row.source,
      sourceThreadId: row.source_thread_id || "",
      sourceContainerId: row.source_container_id || "",
      sourceRecordId: row.source_record_id || "",
      rawType: row.raw_type,
      rawLabel: row.raw_label || row.raw_type,
      rawText: row.raw_text,
      summary: row.summary || "",
      occurredAt: row.occurred_at || "",
      syncedAt: row.synced_at,
      projectPath: row.project_path || "",
      threadTitle: row.thread_title || "",
      sourceUri: row.source_uri || "",
      sensitivityLevel: row.sensitivity_level,
      noiseLevel: row.noise_level,
      status: row.status,
      metadata: row.metadata || {},
    })),
  };
}
