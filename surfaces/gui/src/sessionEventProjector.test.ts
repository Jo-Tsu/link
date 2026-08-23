import { describe, expect, it } from "vitest";

import { projectSessionEvent, type SessionProjectionContext } from "./sessionEventProjector";
import type { Item, WsEvent } from "./types";

const baseContext: SessionProjectionContext = {
  unattended: false,
  streamBuffer: "",
  reasoningBuffer: "",
  now: () => 123,
  newId: () => "tool-id",
  tr: (english, params) =>
    english.replace(/\{(\w+)\}/g, (match, key) =>
      params?.[key] === undefined ? match : String(params[key]),
    ),
};

function apply(event: WsEvent, items: Item[] = [], context = baseContext) {
  const projection = projectSessionEvent(event, context);
  return {
    ...projection,
    items: projection.updateItems ? projection.updateItems(items) : items,
  };
}

describe("projectSessionEvent", () => {
  it("projects ready facts without changing the transcript", () => {
    const result = apply({
      type: "ready",
      data: {
        model: "model-a",
        mode: "plan",
        workspace: "/tmp/work",
        command_trust: { required: true, reason: "untrusted" },
      },
    });

    expect(result.items).toEqual([]);
    expect(result.effects).toEqual({
      model: "model-a",
      mode: "plan",
      workspace: "/tmp/work",
      workspaceTrust: { required: true, reason: "untrusted" },
    });
  });

  it("deduplicates foreground input and adds background connector input", () => {
    const existing: Item[] = [{ kind: "user", text: "hello", ts: 1 }];
    const duplicate = apply({ type: "turn_start", data: { input: "hello" } }, existing);
    expect(duplicate.items).toBe(existing);

    const source = {
      connector: "slack",
      kind: "channel" as const,
      channel_id: "C1",
      channel_name: "#support",
      sender_id: "U1",
      sender_name: "Ada",
      ts: 12,
      text: "from Slack",
    };
    const background = apply({ type: "turn_start", data: { source } }, existing);
    expect(background.items[background.items.length - 1]).toEqual({ kind: "connector", source });
  });

  it("uses buffered reasoning when finalizing an assistant message", () => {
    const result = apply(
      { type: "assistant_message", data: { text: "answer" } },
      [],
      { ...baseContext, reasoningBuffer: "thinking" },
    );

    expect(result.items).toEqual([
      { kind: "assistant", text: "answer", reasoning: "thinking", ts: 123 },
    ]);
  });

  it.each(["error", "interrupted"] as const)(
    "makes partial output durable before the %s notice",
    (type) => {
      const result = apply(
        { type, data: type === "error" ? { error: "offline" } : {} },
        [],
        { ...baseContext, streamBuffer: "partial", reasoningBuffer: "thinking" },
      );

      expect(result.items[0]).toEqual({
        kind: "assistant",
        text: "partial",
        reasoning: "thinking",
        ts: 123,
      });
      expect(result.items[1]).toMatchObject({
        kind: "notice",
        tone: "warn",
        ...(type === "error" ? { text: "Error: offline", retriable: true } : { text: "Interrupted." }),
      });
    },
  );

  it("normalizes todos and completes the matching pending tool", () => {
    const proposed = apply({
      type: "tool_proposed",
      data: {
        name: "todo_write",
        arguments: { todos: ["first", { content: "second", status: "completed" }] },
      },
    });

    expect(proposed.todo).toEqual([
      { content: "first", status: "pending" },
      { content: "second", status: "done" },
    ]);
    expect(proposed.items).toEqual([
      {
        kind: "tool",
        id: "tool-id",
        name: "todo_write",
        args: { todos: ["first", { content: "second", status: "completed" }] },
        status: "…",
      },
    ]);

    const finished = apply(
      {
        type: "tool_finished",
        data: {
          name: "todo_write",
          status: "done",
          result_preview: "updated",
          display: { hidden_by_filters: 2 },
          standing_rule: "todo_write → current",
        },
      },
      proposed.items,
    );
    expect(finished.items[0]).toMatchObject({
      status: "done",
      preview: "updated",
      hidden: 2,
      standingRule: "todo_write → current",
    });
  });

  it("suppresses inbox-routed prompts while unattended", () => {
    for (const event of [
      { type: "permission_required", data: { name: "shell" } },
      { type: "directory_requested", data: { path: "/tmp" } },
      { type: "plan_proposed", data: { plan: "do it" } },
    ] as WsEvent[]) {
      const existing: Item[] = [{ kind: "user", text: "keep" }];
      expect(apply(event, existing, { ...baseContext, unattended: true }).items).toBe(existing);
    }
  });

  it("reports browser/session refresh effects without embedding UI work", () => {
    const browser = apply({
      type: "tool_finished",
      data: { name: "browser_click", status: "done" },
    });
    expect(browser.effects.refreshBrowser).toBe(true);

    const done = apply({ type: "turn_done", data: {} });
    expect(done.effects).toEqual({ refreshBrowser: true, refreshSessions: true });
  });
});
