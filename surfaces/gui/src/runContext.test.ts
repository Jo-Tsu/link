import { describe, expect, it } from "vitest";

import {
  activeRunContextForSession,
  bindPendingSessionPrompt,
  bindRunContext,
  consumePendingSessionPrompt,
  runTaskOrNull,
} from "./runContext";

describe("runContext helpers", () => {
  it("binds pending prompts to a target session", () => {
    expect(bindPendingSessionPrompt({}, "", "ship it")).toEqual({});
    expect(bindPendingSessionPrompt({}, "__run__1", "")).toEqual({});
    expect(bindPendingSessionPrompt({}, "__run__1", "ship it")).toEqual({
      __run__1: "ship it",
    });
  });

  it("consumes pending prompts only for the matching connected session", () => {
    const pending = bindPendingSessionPrompt({}, "__run__1", "ship it");
    expect(consumePendingSessionPrompt("session-2", pending)).toEqual({
      nextPendingPrompts: pending,
      prompt: null,
    });
    expect(consumePendingSessionPrompt("__run__1", pending)).toEqual({
      nextPendingPrompts: {},
      prompt: "ship it",
    });
  });

  it("keeps concurrent run prompts isolated by session", () => {
    const pendingA = bindPendingSessionPrompt({}, "__run__a", "run A");
    const pendingBoth = bindPendingSessionPrompt(pendingA, "__run__b", "run B");
    const consumedB = consumePendingSessionPrompt("__run__b", pendingBoth);

    expect(consumedB.prompt).toBe("run B");
    expect(consumedB.nextPendingPrompts).toEqual({ __run__a: "run A" });
    expect(consumePendingSessionPrompt("__run__a", consumedB.nextPendingPrompts)).toEqual({
      nextPendingPrompts: {},
      prompt: "run A",
    });
  });

  it("builds a run task only when the event carries task_id", () => {
    expect(runTaskOrNull(undefined, "Nightly sync")).toBeNull();
    expect(runTaskOrNull("task-1", "Nightly sync")).toEqual({
      id: "task-1",
      title: "Nightly sync",
    });
    expect(runTaskOrNull("task-1", undefined)).toEqual({
      id: "task-1",
      title: "",
    });
  });

  it("binds run context only for __run__ sessions", () => {
    expect(bindRunContext("session-1", { id: "task-1", title: "Nightly sync" })).toBeNull();
    expect(bindRunContext("__run__abc", { id: "task-1", title: "Nightly sync" })).toEqual({
      sessionId: "__run__abc",
      id: "task-1",
      title: "Nightly sync",
    });
  });

  it("derives the active run context for the current session only", () => {
    const bound = bindRunContext("__run__abc", { id: "task-1", title: "Nightly sync" });
    expect(activeRunContextForSession("__run__abc", bound)).toEqual(bound);
    expect(activeRunContextForSession("__run__other", bound)).toBeNull();
    expect(activeRunContextForSession("session-1", bound)).toBeNull();
  });

  it("drops stale run context for ordinary sessions and unrelated async selections", () => {
    const stale = {
      sessionId: "__run__old",
      id: "task-1",
      title: "Nightly sync",
    };
    expect(activeRunContextForSession("session-2", stale)).toBeNull();
    expect(activeRunContextForSession("__run__new", stale)).toBeNull();
  });
});
