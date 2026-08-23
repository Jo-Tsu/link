import type { MessageSource, WorkspaceCommandTrust } from "./api";
import type { Item, TodoItem, WsEvent } from "./types";

const FILE_WRITE_TOOLS = new Set([
  "write_file",
  "apply_patch",
  "apply_unified_diff",
  "replace_in_file",
]);

type Translate = (english: string, params?: Record<string, string | number>) => string;
type ItemUpdate = (items: Item[]) => Item[];

export interface SessionProjectionContext {
  unattended: boolean;
  streamBuffer: string;
  reasoningBuffer: string;
  now: () => number;
  newId: () => string;
  tr: Translate;
}

export interface SessionEventEffects {
  model?: string;
  mode?: string;
  workspace?: string;
  workspaceTrust?: WorkspaceCommandTrust;
  refreshBrowser?: boolean;
  refreshSessions?: boolean;
}

export interface SessionEventProjection {
  updateItems?: ItemUpdate;
  todo?: TodoItem[];
  effects: SessionEventEffects;
}

function append(...next: Item[]): ItemUpdate {
  return (items) => [...items, ...next];
}

function normalizeTodos(raw: unknown): TodoItem[] {
  if (!Array.isArray(raw)) return [];
  const statuses = new Set(["pending", "in_progress", "done"]);
  return raw.map((entry: any) => {
    if (entry && typeof entry === "object") {
      const status = entry.status === "completed" ? "done" : entry.status;
      return {
        content: String(entry.content ?? ""),
        status: statuses.has(status) ? status : "pending",
      };
    }
    return { content: String(entry ?? ""), status: "pending" as const };
  });
}

function updateLastTool(
  items: Item[],
  name: string,
  status: string,
  preview?: string,
  hidden?: number,
  standingRule?: string,
): Item[] {
  const copy = [...items];
  for (let i = copy.length - 1; i >= 0; i--) {
    const item = copy[i];
    if (item.kind === "tool" && item.name === name && item.status === "…") {
      copy[i] = {
        ...item,
        status,
        preview,
        ...(hidden ? { hidden } : {}),
        ...(standingRule ? { standingRule } : {}),
      };
      break;
    }
  }
  return copy;
}

/**
 * Pure projection from one session WebSocket event to transcript/todo updates and
 * the small set of product-level effects App still owns. Lifecycle buffers are
 * supplied before useAgentLifecycle consumes terminal events, so partial output
 * can be made durable on interruption/error.
 */
export function projectSessionEvent(
  event: WsEvent,
  context: SessionProjectionContext,
): SessionEventProjection {
  const data = event.data || {};
  const effects: SessionEventEffects = {};

  switch (event.type) {
    case "ready":
      if (data.model) effects.model = data.model;
      if (data.mode) effects.mode = data.mode;
      if (data.workspace) effects.workspace = data.workspace;
      if (data.command_trust?.required) effects.workspaceTrust = data.command_trust;
      break;

    case "turn_start":
      if (data.source?.connector) {
        const source = data.source as MessageSource;
        return {
          effects,
          updateItems: (items) => {
            const last = items[items.length - 1];
            return last &&
              last.kind === "connector" &&
              last.source.ts === source.ts &&
              last.source.text === source.text
              ? items
              : [...items, { kind: "connector", source }];
          },
        };
      }
      if (typeof data.input === "string" && data.input) {
        return {
          effects,
          updateItems: (items) => {
            const last = items[items.length - 1];
            return last && last.kind === "user" && last.text === data.input
              ? items
              : [...items, { kind: "user", text: data.input, ts: context.now() }];
          },
        };
      }
      break;

    case "assistant_message": {
      const reasoning = data.reasoning || context.reasoningBuffer;
      if (data.text || reasoning) {
        return {
          effects,
          updateItems: append({
            kind: "assistant",
            text: data.text || "",
            ts: context.now(),
            ...(reasoning ? { reasoning } : {}),
          }),
        };
      }
      break;
    }

    case "tool_proposed": {
      const rawTodos = data.name === "todo_write"
        ? data.arguments?.todos || data.arguments?.items
        : undefined;
      return {
        effects,
        ...(rawTodos ? { todo: normalizeTodos(rawTodos) } : {}),
        updateItems: append({
          kind: "tool",
          id: context.newId(),
          name: data.name,
          args: data.arguments,
          status: "…",
        }),
      };
    }

    case "permission_required":
      if (!context.unattended) {
        return {
          effects,
          updateItems: append({
            kind: "approval",
            name: data.name,
            args: data.arguments,
            reason: data.reason,
            category: data.category,
            standingTarget: data.standing_target || undefined,
          }),
        };
      }
      break;

    case "directory_requested":
      if (!context.unattended) {
        return {
          effects,
          updateItems: append({
            kind: "dirreq",
            reason: data.reason || "",
            path: data.path || "",
            writable: !!data.writable,
          }),
        };
      }
      break;

    case "plan_proposed":
      if (!context.unattended) {
        return {
          effects,
          updateItems: append({ kind: "planreq", plan: data.plan || "" }),
        };
      }
      break;

    case "question_requested":
      return {
        effects,
        updateItems: append({
          kind: "question",
          question: data.question || "",
          options: data.options || [],
          allow_text: data.allow_text !== false,
          multi: !!data.multi,
        }),
      };

    case "tool_finished":
      effects.refreshBrowser =
        String(data.name || "").startsWith("browser_") || FILE_WRITE_TOOLS.has(data.name);
      return {
        effects,
        updateItems: (items) =>
          updateLastTool(
            items,
            data.name,
            data.status,
            data.result_preview || data.reason,
            data.display?.hidden_by_filters,
            data.standing_rule,
          ),
      };

    case "memory_cited":
      if (data.memories?.length > 0) {
        return {
          effects,
          updateItems: append({ kind: "memory_cited", memories: data.memories }),
        };
      }
      break;

    case "turn_end":
      if (data.status === "max_iterations_exceeded") {
        return {
          effects,
          updateItems: append({
            kind: "notice",
            tone: "warn",
            text: context.tr("Stopped: max iterations reached."),
          }),
        };
      }
      break;

    case "model_changed":
      if (data.model) effects.model = data.model;
      return {
        effects,
        updateItems: append({
          kind: "notice",
          tone: "info",
          text: data.text || context.tr("Model switched"),
        }),
      };

    case "interrupted": {
      const partial = partialAssistant(context);
      return {
        effects,
        updateItems: append(
          ...(partial ? [partial] : []),
          { kind: "notice", tone: "warn", text: context.tr("Interrupted.") },
        ),
      };
    }

    case "error": {
      const partial = partialAssistant(context);
      return {
        effects,
        updateItems: append(
          ...(partial ? [partial] : []),
          {
            kind: "notice",
            tone: "warn",
            text: context.tr("Error: {error}", { error: data.error || context.tr("unknown") }),
            retriable: true,
          },
        ),
      };
    }

    case "input_rejected":
      return {
        effects,
        updateItems: append({
          kind: "notice",
          tone: "warn",
          text: data.error || context.tr("That message was rejected."),
        }),
      };

    case "turn_done":
      effects.refreshSessions = true;
      effects.refreshBrowser = true;
      break;
  }

  return { effects };
}

function partialAssistant(context: SessionProjectionContext): Extract<Item, { kind: "assistant" }> | null {
  if (!context.streamBuffer && !context.reasoningBuffer) return null;
  return {
    kind: "assistant",
    text: context.streamBuffer,
    ts: context.now(),
    ...(context.reasoningBuffer ? { reasoning: context.reasoningBuffer } : {}),
  };
}
