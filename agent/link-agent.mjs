#!/usr/bin/env node

import { execFile } from "node:child_process";
import { generateKeyPairSync, randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const version = "0.1.0";
const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const agentHome = process.env.LINK_AGENT_HOME || path.join(os.homedir(), ".link-agent");
const configPath = path.join(agentHome, "config.json");
const queueDir = path.join(agentHome, "queue");
const cursorDir = path.join(agentHome, "cursors");
const logPath = path.join(agentHome, "logs", "agent.log");

function usage() {
  console.log(`link-agent ${version}

Usage:
  link-agent init
  link-agent connect <platform-url> --code <pairing-code> [--name <device-name>]
  link-agent start [--once]
  link-agent status
  link-agent sync codex [--limit <record-count>]
  link-agent logs`);
}

async function ensureHome() {
  await fs.mkdir(queueDir, { recursive: true, mode: 0o700 });
  await fs.mkdir(cursorDir, { recursive: true, mode: 0o700 });
  await fs.mkdir(path.dirname(logPath), { recursive: true, mode: 0o700 });
}

async function appendLog(event, detail = {}) {
  await ensureHome();
  await fs.appendFile(
    logPath,
    `${JSON.stringify({ at: new Date().toISOString(), event, ...detail })}\n`,
    {
      mode: 0o600,
    },
  );
}

async function readConfig(required = true) {
  try {
    return JSON.parse(await fs.readFile(configPath, "utf8"));
  } catch (error) {
    if (!required && error && error.code === "ENOENT") return undefined;
    throw new Error("Agent is not initialized. Run: link-agent init");
  }
}

async function writeConfig(config) {
  await ensureHome();
  await fs.writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 });
  await fs.chmod(configPath, 0o600);
}

async function readCursor(connectorId) {
  try {
    return JSON.parse(await fs.readFile(path.join(cursorDir, `${connectorId}.json`), "utf8"));
  } catch (error) {
    if (error && error.code === "ENOENT") return {};
    throw error;
  }
}

async function writeCursor(connectorId, cursor) {
  await fs.writeFile(
    path.join(cursorDir, `${connectorId}.json`),
    `${JSON.stringify(cursor, null, 2)}\n`,
    {
      mode: 0o600,
    },
  );
}

function trimPlatformUrl(value) {
  return value.replace(/\/$/, "");
}

async function request(config, endpoint, body) {
  const response = await fetch(`${trimPlatformUrl(config.platformUrl)}${endpoint}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(config.token ? { authorization: `Bearer ${config.token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.ok)
    throw new Error(result.error || `Platform request failed (${response.status})`);
  return result;
}

async function initialize() {
  const existing = await readConfig(false);
  if (existing) {
    console.log(`Agent already initialized: ${agentHome}`);
    return;
  }
  await writeConfig({
    version,
    platformUrl: "",
    agentId: "",
    token: "",
    publicKey: "",
    displayName: os.hostname(),
    createdAt: new Date().toISOString(),
  });
  await appendLog("initialized", { agentHome });
  console.log(`Initialized LinkAgent at ${agentHome}`);
}

function optionValue(args, name) {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] || "" : "";
}

async function connect(args) {
  const platformUrl = args[0];
  const code = optionValue(args, "--code");
  const displayName = optionValue(args, "--name") || os.hostname();
  if (!platformUrl || !code)
    throw new Error("Usage: link-agent connect <platform-url> --code <pairing-code>");
  const config = await readConfig();
  const { publicKey } = generateKeyPairSync("ed25519", {
    publicKeyEncoding: { type: "spki", format: "pem" },
  });
  const response = await request({ platformUrl }, "/api/agents/pair", {
    code,
    publicKey,
    displayName,
    version,
    operatingSystem: `${process.platform}-${process.arch}`,
  });
  await writeConfig({
    ...config,
    platformUrl: trimPlatformUrl(platformUrl),
    agentId: response.agentId,
    token: response.token,
    publicKey,
    displayName: response.displayName,
    pairedAt: new Date().toISOString(),
  });
  await appendLog("paired", {
    agentId: response.agentId,
    platformUrl: trimPlatformUrl(platformUrl),
  });
  console.log(`Paired as ${response.displayName} (${response.agentId})`);
}

function compact(value, limit = 280) {
  const text = String(value || "")
    .replaceAll("\0", "")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function normalizeCodexSnapshot(snapshot) {
  const records = [];
  for (const thread of snapshot.threads || []) {
    const baseMetadata = {
      connector: "codex_local",
      generated_at: snapshot.generatedAt,
      thread_id: thread.id,
      thread_source: thread.source,
      archived: thread.archived,
      model: thread.model,
    };
    (thread.conversation?.inputs || []).forEach((item, index) =>
      records.push({
        source: "codex",
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
        summary: compact(item.text),
        metadata: { ...baseMetadata, message_index: index },
      }),
    );
    (thread.conversation?.outputs || []).forEach((item, index) =>
      records.push({
        source: "codex",
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
        summary: compact(item.text),
        metadata: { ...baseMetadata, message_index: index },
      }),
    );
    (thread.toolSummary?.cliCommands || []).forEach((command, index) => {
      const rawText = `${command.title}：${command.cmd}；工作目录：${command.workdir || thread.cwd || "未知"}；输出摘要：${command.output || "暂无"}`;
      records.push({
        source: "codex",
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
        summary: compact(`${command.title}：${command.cmd}`),
        metadata: { ...baseMetadata, command: command.cmd, command_title: command.title },
      });
    });
    (thread.toolSummary?.tools || []).forEach((tool, index) => {
      const rawText = `${tool.name} 工具在该线程中调用 ${tool.count} 次。`;
      records.push({
        source: "codex",
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
    (thread.ingestion?.skillRefs || []).forEach((skill, index) => {
      const rawText = `skill:${skill}`;
      records.push({
        source: "codex",
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
  return records.filter((record) => record.rawText && String(record.rawText).trim());
}

async function collectCodexRecords() {
  const snapshotPath = path.join(agentHome, `codex-snapshot-${randomUUID()}.json`);
  try {
    await execFileAsync(
      process.execPath,
      [path.join(rootDir, "scripts", "import-codex-history.mjs")],
      {
        cwd: rootDir,
        timeout: 120_000,
        maxBuffer: 8 * 1024 * 1024,
        env: { ...process.env, CODEX_HISTORY_OUTPUT: snapshotPath },
      },
    );
    return JSON.parse(await fs.readFile(snapshotPath, "utf8"));
  } finally {
    await fs.rm(snapshotPath, { force: true });
  }
}

async function enqueueBatch(batch) {
  const file = path.join(queueDir, `${batch.batchId}.json`);
  await fs.writeFile(file, `${JSON.stringify(batch)}\n`, { mode: 0o600 });
  return file;
}

async function flushQueue(config) {
  const entries = (await fs.readdir(queueDir)).filter((name) => name.endsWith(".json")).sort();
  let uploaded = 0;
  for (const name of entries) {
    const file = path.join(queueDir, name);
    const batch = JSON.parse(await fs.readFile(file, "utf8"));
    const result = await request(config, "/api/agents/ingestion-batches", {
      ...batch,
      agentId: config.agentId,
    });
    await fs.rm(file, { force: true });
    if (batch.cursorAfter) await writeCursor(batch.connectorId, batch.cursorAfter);
    uploaded += result.records || 0;
    await appendLog("batch_uploaded", {
      batchId: batch.batchId,
      connectorId: batch.connectorId,
      ...result,
    });
  }
  return uploaded;
}

async function syncCodex(args = []) {
  const config = await readConfig();
  if (!config.agentId || !config.token || !config.platformUrl)
    throw new Error("Agent is not paired. Run link-agent connect first.");
  const snapshot = await collectCodexRecords();
  const cursorBefore = await readCursor("codex_local");
  const latest = cursorBefore.latestOccurredAt ? Date.parse(cursorBefore.latestOccurredAt) : 0;
  let records = normalizeCodexSnapshot(snapshot).filter(
    (record) => !latest || Date.parse(record.occurredAt || 0) > latest,
  );
  const requestedLimit = Number(optionValue(args, "--limit"));
  if (Number.isFinite(requestedLimit) && requestedLimit > 0)
    records = records.slice(0, requestedLimit);
  const latestOccurredAt = records.reduce((latestAt, record) => {
    const current = record.occurredAt || "";
    return current > latestAt ? current : latestAt;
  }, cursorBefore.latestOccurredAt || "");
  const cursorAfter = { latestOccurredAt, syncedAt: new Date().toISOString() };
  for (let offset = 0; offset < records.length; offset += 200) {
    await enqueueBatch({
      batchId: `codex-${randomUUID()}`,
      connectorId: "codex_local",
      cursorBefore,
      cursorAfter,
      records: records.slice(offset, offset + 200),
    });
  }
  const uploaded = await flushQueue(config);
  await appendLog("codex_sync_finished", { queued: records.length, uploaded, cursorAfter });
  console.log(`Codex sync complete: ${uploaded} records uploaded (${records.length} selected).`);
  return { records: records.length, uploaded };
}

async function heartbeat(config) {
  const response = await request(config, "/api/agents/heartbeat", {
    agentId: config.agentId,
    version,
    operatingSystem: `${process.platform}-${process.arch}`,
    connectorStates: [{ id: "codex_local", status: "ready" }],
  });
  for (const command of response.commands || []) {
    let success = true;
    let result = {};
    try {
      if (command.type === "sync_connector" && command.payload?.connectorId === "codex_local") {
        const limit = Number(command.payload?.limit);
        result = await syncCodex(
          Number.isFinite(limit) && limit > 0 ? ["--limit", String(limit)] : [],
        );
      } else if (command.type === "refresh_config") result = { refreshed: true };
      else if (command.type === "validate_connector")
        result = { valid: command.payload?.connectorId === "codex_local" };
      else if (command.type === "pause_connector") result = { paused: true };
      else throw new Error("Unsupported command payload");
    } catch (error) {
      success = false;
      result = { error: error instanceof Error ? error.message : "Command failed" };
    }
    await request(config, "/api/agents/commands/complete", {
      agentId: config.agentId,
      commandId: command.id,
      success,
      result,
    });
  }
  return response;
}

async function start(args) {
  const config = await readConfig();
  if (!config.agentId || !config.token || !config.platformUrl)
    throw new Error("Agent is not paired. Run link-agent connect first.");
  const run = async () => {
    try {
      await heartbeat(config);
      await flushQueue(config);
      await appendLog("heartbeat", { status: "ok" });
    } catch (error) {
      await appendLog("heartbeat", {
        status: "error",
        error: error instanceof Error ? error.message : "Unknown error",
      });
      console.error(error instanceof Error ? error.message : error);
    }
  };
  await run();
  if (args.includes("--once")) return;
  console.log("LinkAgent started. Press Ctrl+C to stop.");
  setInterval(() => void run(), 30_000);
}

async function status() {
  const config = await readConfig(false);
  const queued = (await fs.readdir(queueDir).catch(() => [])).filter((name) =>
    name.endsWith(".json"),
  ).length;
  console.log(
    JSON.stringify(
      {
        initialized: Boolean(config),
        agentHome,
        agentId: config?.agentId || "",
        platformUrl: config?.platformUrl || "",
        queuedBatches: queued,
        version,
      },
      null,
      2,
    ),
  );
}

async function logs() {
  try {
    const lines = (await fs.readFile(logPath, "utf8")).trim().split("\n").slice(-80);
    console.log(lines.join("\n"));
  } catch (error) {
    if (error && error.code === "ENOENT") return;
    throw error;
  }
}

async function main() {
  const [command, ...args] = process.argv.slice(2);
  if (!command || ["help", "--help", "-h"].includes(command)) return usage();
  if (command === "init") return initialize();
  if (command === "connect") return connect(args);
  if (command === "start") return start(args);
  if (command === "status") return status();
  if (command === "sync" && args[0] === "codex") return syncCodex(args.slice(1));
  if (command === "logs") return logs();
  usage();
  process.exitCode = 1;
}

main().catch(async (error) => {
  await appendLog("fatal", {
    error: error instanceof Error ? error.message : "Unknown error",
  }).catch(() => undefined);
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
