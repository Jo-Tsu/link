import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";

const codexHome = process.env.CODEX_HOME || path.join(os.homedir(), ".codex");
const sessionsDir = path.join(codexHome, "sessions");
const archivedDir = path.join(codexHome, "archived_sessions");
const indexPath = path.join(codexHome, "session_index.jsonl");
const jsonOutPath =
  process.env.CODEX_HISTORY_OUTPUT ||
  path.join(process.cwd(), "src", "lib", "codex-history.generated.json");

function envInt(name, fallback) {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

const messageTextLimit = envInt("CODEX_MESSAGE_TEXT_LIMIT", 1200);
const cliCommandTextLimit = envInt("CODEX_CLI_COMMAND_TEXT_LIMIT", 600);
const cliOutputTextLimit = envInt("CODEX_CLI_OUTPUT_TEXT_LIMIT", 1200);
const toolInputTextLimit = envInt("CODEX_TOOL_INPUT_TEXT_LIMIT", 600);
const nulChar = String.fromCharCode(0);

function walkJsonl(dir) {
  if (!fs.existsSync(dir)) return [];
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walkJsonl(full));
    if (entry.isFile() && entry.name.endsWith(".jsonl")) out.push(full);
  }
  return out;
}

async function readJsonl(file) {
  if (!fs.existsSync(file)) return [];
  const rows = [];
  const stream = fs.createReadStream(file, { encoding: "utf8" });
  const lines = readline.createInterface({
    input: stream,
    crlfDelay: Infinity,
  });

  for await (const line of lines) {
    if (!line) continue;
    try {
      rows.push(JSON.parse(line));
    } catch {
      // Ignore malformed partial lines; Codex source files remain untouched.
    }
  }

  return rows;
}

function textFromContent(content) {
  if (!Array.isArray(content)) return "";
  return content
    .map((item) => item?.text || item?.output_text || "")
    .filter(Boolean)
    .join("\n")
    .trim();
}

function cleanText(text) {
  return text
    .split(nulChar)
    .join("")
    .replace(new RegExp(os.homedir().replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g"), "~")
    .replace(/sk-[A-Za-z0-9_-]{12,}/g, "sk-***")
    .replace(/(api[_-]?key|token|password|secret)(["':=\\s]+)[^\\s"',}]+/gi, "$1$2***")
    .replace(/\s+/g, " ")
    .trim();
}

function short(text, n = 180) {
  const cleaned = cleanText(text);
  return cleaned.length > n ? `${cleaned.slice(0, n)}...` : cleaned;
}

function parseJson(value) {
  if (!value || typeof value !== "string") return {};
  try {
    return JSON.parse(value);
  } catch {
    return {};
  }
}

function messageKey(role, text) {
  return `${role}:${cleanText(text).slice(0, 400)}`;
}

function commandTitle(cmd) {
  const first = cleanText(cmd).split(/\s+/)[0] || "cli";
  if (first === "npm") return "npm 脚本";
  if (first === "node") return "Node 脚本";
  if (first === "rg") return "代码搜索";
  if (first === "sed") return "文件读取";
  if (first === "curl") return "接口检查";
  if (first === "ps") return "进程检查";
  if (first === "git") return "Git 操作";
  return first;
}

function extractSkillRefs(text) {
  const refs = new Set();
  for (const match of cleanText(text).matchAll(
    /(?:^|\/)\.codex\/skills\/([^/\s]+)|\/skills\/([^/\s]+)\/SKILL\.md/g,
  )) {
    refs.add(match[1] || match[2]);
  }
  return [...refs];
}

function isUsefulUserText(text) {
  const t = text.trim();
  if (!t) return false;
  if (t.startsWith("<environment_context>")) return false;
  if (t.startsWith("<turn_aborted>")) return false;
  if (t.includes("# In app browser:") && t.length < 280) return false;
  return true;
}

const indexById = new Map();
for (const item of await readJsonl(indexPath)) {
  if (item?.id) indexById.set(item.id, item);
}

const activeFiles = walkJsonl(sessionsDir);
const archivedFiles = walkJsonl(archivedDir);
const allFiles = [...activeFiles, ...archivedFiles];

const threads = [];
const eventTypeCounts = {};
let userMessages = 0;
let assistantMessages = 0;
let toolCalls = 0;
let toolOutputs = 0;
let totalEvents = 0;

for (const file of allFiles) {
  const rows = await readJsonl(file);
  if (rows.length === 0) continue;

  const meta = rows.find((row) => row.type === "session_meta")?.payload || {};
  const sessionId =
    meta.session_id ||
    meta.id ||
    path
      .basename(file)
      .replace(/^rollout-/, "")
      .replace(/\.jsonl$/, "");
  const index = indexById.get(sessionId);
  const title = index?.thread_name || "未命名 Codex 线程";
  const startedAt = meta.timestamp || rows[0]?.timestamp || "";
  const updatedAt = index?.updated_at || rows.at(-1)?.timestamp || startedAt;
  const cwd = meta.cwd ? cleanText(meta.cwd) : "";
  const model = meta.model || meta.model_provider || "";
  const source = meta.originator || meta.source || "Codex";
  const archived = file.includes(`${path.sep}archived_sessions${path.sep}`);

  const samples = [];
  const inputs = [];
  const outputs = [];
  const cliCommands = [];
  const toolCounts = new Map();
  const skillRefs = new Set();
  const titleSignals = new Set();
  const callById = new Map();
  const seenMessages = new Set();
  let threadUserMessages = 0;
  let threadAssistantMessages = 0;
  let threadToolCalls = 0;
  let threadToolOutputs = 0;
  let duplicateMessages = 0;

  if (title && title !== "未命名 Codex 线程") titleSignals.add(title);
  for (const value of extractSkillRefs(JSON.stringify(meta))) skillRefs.add(value);

  function addMessage(role, text, at) {
    if (role === "user" && !isUsefulUserText(text)) return;
    const key = messageKey(role, text);
    if (seenMessages.has(key)) {
      duplicateMessages += 1;
      return;
    }
    seenMessages.add(key);

    const item = { role, text: short(text), at };
    if (samples.length < 3) samples.push(item);
    if (role === "user") {
      userMessages += 1;
      threadUserMessages += 1;
      inputs.push({ text: short(text, messageTextLimit), at });
      const firstLine = cleanText(text).split(/[。.!?\n]/)[0];
      if (firstLine.length >= 4 && firstLine.length <= 48) titleSignals.add(firstLine);
    }
    if (role === "assistant") {
      assistantMessages += 1;
      threadAssistantMessages += 1;
      outputs.push({ text: short(text, messageTextLimit), at });
    }
  }

  for (const row of rows) {
    totalEvents += 1;
    const payload = row.payload || {};
    const kind = payload.type || row.type;
    eventTypeCounts[kind] = (eventTypeCounts[kind] || 0) + 1;

    if (row.type === "response_item" && payload.type === "message") {
      const role = payload.role;
      const text = textFromContent(payload.content);
      if (role === "user" || role === "assistant") addMessage(role, text, row.timestamp || "");
    }

    if (
      row.type === "event_msg" &&
      payload.type === "user_message" &&
      isUsefulUserText(payload.message || "")
    ) {
      addMessage("user", payload.message || "", row.timestamp || "");
    }

    if (["function_call", "custom_tool_call"].includes(payload.type)) {
      toolCalls += 1;
      threadToolCalls += 1;
      toolCounts.set(
        payload.name || "unknown",
        (toolCounts.get(payload.name || "unknown") || 0) + 1,
      );
      const args = payload.type === "function_call" ? parseJson(payload.arguments) : {};
      const rawInput = payload.input || payload.arguments || "";
      for (const value of extractSkillRefs(rawInput)) skillRefs.add(value);
      callById.set(payload.call_id, {
        name: payload.name || "unknown",
        type: payload.type,
        at: row.timestamp || "",
        args,
        input: short(rawInput, toolInputTextLimit),
      });

      if (payload.name === "exec_command" && args.cmd) {
        cliCommands.push({
          title: commandTitle(args.cmd),
          cmd: short(args.cmd, cliCommandTextLimit),
          workdir: args.workdir ? cleanText(args.workdir) : cwd,
          at: row.timestamp || "",
          output: "",
        });
      }
    }

    if (["function_call_output", "custom_tool_call_output"].includes(payload.type)) {
      toolOutputs += 1;
      threadToolOutputs += 1;
      const call = callById.get(payload.call_id);
      if (call?.name === "exec_command") {
        const command = [...cliCommands].reverse().find((item) => item.at === call.at);
        if (command) command.output = short(payload.output || "", cliOutputTextLimit);
      }
    }
  }

  threads.push({
    id: sessionId,
    title,
    startedAt,
    updatedAt,
    cwd,
    model,
    source,
    archived,
    file: cleanText(file),
    userMessages: threadUserMessages,
    assistantMessages: threadAssistantMessages,
    toolCalls: threadToolCalls,
    toolOutputs: threadToolOutputs,
    samples,
    conversation: {
      inputs,
      outputs,
      inputOutputPairs: Math.min(inputs.length, outputs.length),
      duplicateMessages,
    },
    toolSummary: {
      tools: [...toolCounts.entries()]
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count),
      cliCommands,
      cliCommandCount: [...callById.values()].filter((call) => call.name === "exec_command").length,
    },
    ingestion: {
      titleSignals: [...titleSignals].slice(0, 12),
      skillRefs: [...skillRefs],
      hasConversation: inputs.length > 0 || outputs.length > 0,
      hasTools: threadToolCalls > 0,
      hasCli: [...callById.values()].some((call) => call.name === "exec_command"),
      needsReview:
        duplicateMessages > 0 || inputs.length > 0 || outputs.length > 0 || threadToolCalls > 0,
    },
  });
}

threads.sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)));

const payload = {
  generatedAt: new Date().toISOString(),
  codexHome: cleanText(codexHome),
  totals: {
    threads: threads.length,
    activeThreads: threads.filter((thread) => !thread.archived).length,
    archivedThreads: threads.filter((thread) => thread.archived).length,
    totalEvents,
    userMessages,
    assistantMessages,
    toolCalls,
    toolOutputs,
    duplicateMessages: threads.reduce(
      (sum, thread) => sum + (thread.conversation?.duplicateMessages || 0),
      0,
    ),
    cliCommands: threads.reduce(
      (sum, thread) => sum + (thread.toolSummary?.cliCommandCount || 0),
      0,
    ),
  },
  eventTypes: Object.entries(eventTypeCounts)
    .map(([type, count]) => ({ type, count }))
    .sort((a, b) => b.count - a.count),
  threads,
};

fs.mkdirSync(path.dirname(jsonOutPath), { recursive: true });
fs.writeFileSync(jsonOutPath, JSON.stringify(payload, null, 2));
console.log(`Generated import payload ${jsonOutPath}`);
console.log(JSON.stringify(payload.totals, null, 2));
