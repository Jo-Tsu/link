import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useAgentLifecycle } from "./useAgentLifecycle";

describe("useAgentLifecycle", () => {
  it("owns connection, busy state, and streaming buffers", () => {
    const { result } = renderHook(() => useAgentLifecycle());

    act(() => result.current[1].onConnected());
    act(() => result.current[1].onTurnRequested());
    act(() => result.current[1].handleEvent({ type: "assistant_delta", data: { text: "Hi" } }));
    act(() => result.current[1].handleEvent({ type: "reasoning_delta", data: { text: "Think" } }));

    expect(result.current[0]).toMatchObject({
      connected: true,
      busy: true,
      phase: "thinking",
      streamBuffer: "Hi",
      reasoningBuffer: "Think",
    });

    act(() => result.current[1].handleEvent({ type: "turn_done", data: {} }));
    expect(result.current[0].busy).toBe(false);
    expect(result.current[0].streamBuffer).toBe("");
    expect(result.current[0].reasoningBuffer).toBe("");
  });

  it("clears all session-scoped state when switching sessions", () => {
    const { result } = renderHook(() => useAgentLifecycle());
    act(() => result.current[1].onConnected());
    act(() => result.current[1].onTurnRequested());
    act(() => result.current[1].handleEvent({ type: "assistant_delta", data: { text: "old" } }));

    act(() => result.current[1].reset());

    expect(result.current[0]).toEqual({
      phase: "idle",
      connected: false,
      busy: false,
      streamBuffer: "",
      reasoningBuffer: "",
    });
  });

  it("exposes the latest token synchronously to event handlers", () => {
    const { result } = renderHook(() => useAgentLifecycle());

    act(() => {
      result.current[1].onTurnRequested();
      result.current[1].handleEvent({ type: "assistant_delta", data: { text: "partial" } });
      expect(result.current[1].getStreamBuffer()).toBe("partial");
    });
  });

  it("returns an optimistically started request to idle when input is rejected", () => {
    const { result } = renderHook(() => useAgentLifecycle());
    act(() => result.current[1].onTurnRequested());

    act(() =>
      result.current[1].handleEvent({
        type: "input_rejected",
        data: { error: "invalid message" },
      }),
    );

    expect(result.current[0].phase).toBe("idle");
    expect(result.current[0].busy).toBe(false);
  });

  it("keeps the existing busy phase when a second optimistic request is rejected", () => {
    const { result } = renderHook(() => useAgentLifecycle());

    act(() => {
      result.current[1].onTurnRequested();
      result.current[1].handleEvent({ type: "assistant_delta", data: { text: "live" } });
    });

    expect(result.current[0].phase).toBe("thinking");
    expect(result.current[0].busy).toBe(true);
    expect(result.current[0].streamBuffer).toBe("live");

    act(() => result.current[1].onTurnRequested());
    act(() =>
      result.current[1].handleEvent({
        type: "input_rejected",
        data: { error: "already running" },
      }),
    );

    expect(result.current[0].phase).toBe("thinking");
    expect(result.current[0].busy).toBe(true);
    expect(result.current[0].streamBuffer).toBe("live");
  });

  it("bootstraps busy fallback when assistant or tool events arrive without turn_start", () => {
    const { result } = renderHook(() => useAgentLifecycle());

    act(() => result.current[1].handleEvent({ type: "assistant_message", data: { text: "answer" } }));
    expect(result.current[0].phase).toBe("thinking");
    expect(result.current[0].busy).toBe(true);

    act(() => result.current[1].handleEvent({ type: "turn_done", data: {} }));
    expect(result.current[0].phase).toBe("idle");
    expect(result.current[0].busy).toBe(false);

    act(() => result.current[1].handleEvent({ type: "tool_proposed", data: { name: "shell" } }));
    expect(result.current[0].phase).toBe("tool_pending");
    expect(result.current[0].busy).toBe(true);
  });

  it("restores the server-reported phase from ready", () => {
    const { result } = renderHook(() => useAgentLifecycle());

    act(() =>
      result.current[1].handleEvent({
        type: "ready",
        data: { phase: "executing" },
      }),
    );

    expect(result.current[0].phase).toBe("executing");
    expect(result.current[0].busy).toBe(true);
  });

  it("falls back to starting when ready only reports busy", () => {
    const { result } = renderHook(() => useAgentLifecycle());

    act(() =>
      result.current[1].handleEvent({
        type: "ready",
        data: { busy: true },
      }),
    );

    expect(result.current[0].phase).toBe("starting");
    expect(result.current[0].busy).toBe(true);
  });

  it("keeps a just-claimed session busy when ready still reports idle phase", () => {
    const { result } = renderHook(() => useAgentLifecycle());

    act(() =>
      result.current[1].handleEvent({
        type: "ready",
        data: { phase: "idle", busy: true },
      }),
    );

    expect(result.current[0].phase).toBe("starting");
    expect(result.current[0].busy).toBe(true);
  });

  it("keeps legacy ready payloads backward compatible", () => {
    const { result } = renderHook(() => useAgentLifecycle());

    act(() =>
      result.current[1].handleEvent({
        type: "ready",
        data: { model: "gpt-5.6-sol" },
      }),
    );

    expect(result.current[0].phase).toBe("idle");
    expect(result.current[0].busy).toBe(false);
  });
});
