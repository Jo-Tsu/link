import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAgentLifecycle } from "./useAgentLifecycle";

const originalRequestAnimationFrame = window.requestAnimationFrame;
const originalCancelAnimationFrame = window.cancelAnimationFrame;

describe("useAgentLifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(window, "requestAnimationFrame", {
      value: undefined,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(window, "cancelAnimationFrame", {
      value: undefined,
      configurable: true,
      writable: true,
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "requestAnimationFrame", {
      value: originalRequestAnimationFrame,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(window, "cancelAnimationFrame", {
      value: originalCancelAnimationFrame,
      configurable: true,
      writable: true,
    });
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("owns connection, busy state, and streaming buffers", () => {
    const { result } = renderHook(() => useAgentLifecycle());

    act(() => result.current[1].onConnected());
    act(() => result.current[1].onTurnRequested());
    act(() => result.current[1].handleEvent({ type: "assistant_delta", data: { text: "Hi" } }));
    act(() => result.current[1].handleEvent({ type: "reasoning_delta", data: { text: "Think" } }));
    act(() => {
      vi.advanceTimersByTime(16);
    });

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
      vi.advanceTimersByTime(16);
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

  it("batches multiple delta flushes to one animation frame while getters stay synchronous", () => {
    let nextFrameId = 1;
    const callbacks = new Map<number, FrameRequestCallback>();
    const requestAnimationFrame = vi.fn((cb: FrameRequestCallback) => {
      const id = nextFrameId++;
      callbacks.set(id, cb);
      return id;
    });
    const cancelAnimationFrame = vi.fn((id: number) => {
      callbacks.delete(id);
    });
    Object.defineProperty(window, "requestAnimationFrame", {
      value: requestAnimationFrame,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(window, "cancelAnimationFrame", {
      value: cancelAnimationFrame,
      configurable: true,
      writable: true,
    });

    const { result } = renderHook(() => useAgentLifecycle());

    act(() => {
      result.current[1].onTurnRequested();
      result.current[1].handleEvent({ type: "assistant_delta", data: { text: "Hel" } });
      result.current[1].handleEvent({ type: "assistant_delta", data: { text: "lo" } });
      result.current[1].handleEvent({ type: "reasoning_delta", data: { text: "Think" } });
    });

    expect(requestAnimationFrame).toHaveBeenCalledTimes(1);
    expect(result.current[1].getStreamBuffer()).toBe("Hello");
    expect(result.current[1].getReasoningBuffer()).toBe("Think");
    expect(result.current[0].streamBuffer).toBe("");
    expect(result.current[0].reasoningBuffer).toBe("");

    act(() => {
      callbacks.get(1)?.(0);
    });

    expect(result.current[0].streamBuffer).toBe("Hello");
    expect(result.current[0].reasoningBuffer).toBe("Think");
  });

  it("cancels a pending delta flush when a terminal event arrives", () => {
    let nextFrameId = 1;
    const callbacks = new Map<number, FrameRequestCallback>();
    const requestAnimationFrame = vi.fn((cb: FrameRequestCallback) => {
      const id = nextFrameId++;
      callbacks.set(id, cb);
      return id;
    });
    const cancelAnimationFrame = vi.fn((id: number) => {
      callbacks.delete(id);
    });
    Object.defineProperty(window, "requestAnimationFrame", {
      value: requestAnimationFrame,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(window, "cancelAnimationFrame", {
      value: cancelAnimationFrame,
      configurable: true,
      writable: true,
    });

    const { result } = renderHook(() => useAgentLifecycle());

    act(() => {
      result.current[1].onTurnRequested();
      result.current[1].handleEvent({ type: "assistant_delta", data: { text: "stale" } });
      result.current[1].handleEvent({ type: "assistant_message", data: { text: "final" } });
    });

    expect(cancelAnimationFrame).toHaveBeenCalledWith(1);
    expect(result.current[1].getStreamBuffer()).toBe("");
    expect(result.current[0].streamBuffer).toBe("");
    expect(result.current[0].phase).toBe("thinking");

    act(() => {
      callbacks.get(1)?.(0);
    });

    expect(result.current[0].streamBuffer).toBe("");
    expect(result.current[0].reasoningBuffer).toBe("");
  });

  it("cancels pending flushes on reset disconnect and unmount", () => {
    const { result, unmount } = renderHook(() => useAgentLifecycle());

    act(() => {
      result.current[1].onTurnRequested();
      result.current[1].handleEvent({ type: "assistant_delta", data: { text: "pending" } });
      result.current[1].reset();
    });
    act(() => {
      vi.advanceTimersByTime(16);
    });
    expect(result.current[0].streamBuffer).toBe("");
    expect(result.current[1].getStreamBuffer()).toBe("");

    act(() => {
      result.current[1].onConnected();
      result.current[1].onTurnRequested();
      result.current[1].handleEvent({ type: "assistant_delta", data: { text: "pending" } });
      result.current[1].onDisconnected();
    });
    act(() => {
      vi.advanceTimersByTime(16);
    });
    expect(result.current[0].streamBuffer).toBe("");
    expect(result.current[1].getStreamBuffer()).toBe("");

    act(() => {
      result.current[1].onTurnRequested();
      result.current[1].handleEvent({ type: "assistant_delta", data: { text: "pending" } });
    });
    unmount();
    act(() => {
      vi.advanceTimersByTime(16);
    });
  });

  it("keeps non-delta events immediate while delta state waits for the frame", () => {
    const { result } = renderHook(() => useAgentLifecycle());

    act(() => {
      result.current[1].handleEvent({ type: "assistant_delta", data: { text: "partial" } });
      result.current[1].handleEvent({ type: "phase_changed", data: { phase: "executing" } });
    });

    expect(result.current[1].getStreamBuffer()).toBe("partial");
    expect(result.current[0].phase).toBe("executing");
    expect(result.current[0].streamBuffer).toBe("");

    act(() => {
      vi.advanceTimersByTime(16);
    });

    expect(result.current[0].phase).toBe("executing");
    expect(result.current[0].streamBuffer).toBe("partial");
  });

  it("preserves pending delta refs across a later render before RAF flush", () => {
    let nextFrameId = 1;
    const callbacks = new Map<number, FrameRequestCallback>();
    const requestAnimationFrame = vi.fn((cb: FrameRequestCallback) => {
      const id = nextFrameId++;
      callbacks.set(id, cb);
      return id;
    });
    const cancelAnimationFrame = vi.fn((id: number) => {
      callbacks.delete(id);
    });
    Object.defineProperty(window, "requestAnimationFrame", {
      value: requestAnimationFrame,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(window, "cancelAnimationFrame", {
      value: cancelAnimationFrame,
      configurable: true,
      writable: true,
    });

    const { result } = renderHook(() => useAgentLifecycle());

    act(() => {
      result.current[1].onTurnRequested();
      result.current[1].handleEvent({ type: "assistant_delta", data: { text: "first" } });
    });

    expect(result.current[1].getStreamBuffer()).toBe("first");
    expect(result.current[0].streamBuffer).toBe("");
    expect(requestAnimationFrame).toHaveBeenCalledTimes(1);

    act(() => {
      result.current[1].handleEvent({ type: "phase_changed", data: { phase: "executing" } });
    });

    expect(result.current[0].phase).toBe("executing");
    expect(result.current[0].streamBuffer).toBe("");
    expect(result.current[1].getStreamBuffer()).toBe("first");

    act(() => {
      callbacks.get(1)?.(0);
    });

    expect(result.current[0].phase).toBe("executing");
    expect(result.current[0].streamBuffer).toBe("first");
    expect(result.current[1].getStreamBuffer()).toBe("first");
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
