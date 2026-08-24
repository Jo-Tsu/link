/**
 * useAgentLifecycle — single source of truth for agent lifecycle state.
 *
 * Replaces scattered running/connected/streaming booleans with a deterministic
 * state machine driven by server events. Supports both the new phase_changed
 * event and inference from legacy content events for backward compatibility.
 */

import { useCallback, useEffect, useReducer, useRef } from "react";
import type { WsEvent } from "./types";

export type AgentPhase =
  | "idle"
  | "starting"
  | "thinking"
  | "tool_pending"
  | "awaiting_approval"
  | "executing"
  | "completing"
  | "errored"
  | "interrupted";

export interface AgentLifecycle {
  phase: AgentPhase;
  connected: boolean;
  busy: boolean;
  streamBuffer: string;
  reasoningBuffer: string;
}

export interface LifecycleActions {
  handleEvent: (event: WsEvent) => void;
  onConnected: () => void;
  onDisconnected: () => void;
  onTurnRequested: () => void;
  reset: () => void;
  getStreamBuffer: () => string;
  getReasoningBuffer: () => string;
}

interface State {
  phase: AgentPhase;
  connected: boolean;
  streamBuffer: string;
  reasoningBuffer: string;
  optimisticRestorePhase: AgentPhase | null;
  bufferEpoch: number;
  phaseEpoch: number;
}

type Action =
  | { type: "EVENT"; event: WsEvent }
  | {
      type: "FLUSH_BUFFERS";
      streamBuffer: string;
      reasoningBuffer: string;
      bufferEpoch: number;
      phaseEpoch: number;
    }
  | { type: "CONNECTED" }
  | { type: "DISCONNECTED" }
  | { type: "TURN_REQUESTED" }
  | { type: "RESET" };

const VALID_PHASES: Set<AgentPhase> = new Set([
  "idle",
  "starting",
  "thinking",
  "tool_pending",
  "awaiting_approval",
  "executing",
  "completing",
  "errored",
  "interrupted",
]);

function readyPhase(data: any): AgentPhase | null {
  const phase = data?.phase;
  if (typeof phase === "string" && VALID_PHASES.has(phase as AgentPhase)) {
    const restored = phase as AgentPhase;
    return data?.busy === true && !BUSY_PHASES.has(restored) ? "starting" : restored;
  }
  if (data?.busy === true) return "starting";
  return null;
}

function phaseFromEvent(eventType: string, current: AgentPhase): AgentPhase {
  switch (eventType) {
    case "turn_start":
      return "starting";
    case "assistant_delta":
    case "reasoning_delta":
    case "assistant_message":
      return "thinking";
    case "tool_proposed":
      return "tool_pending";
    case "permission_required":
    case "directory_requested":
    case "question_requested":
    case "plan_proposed":
      return "awaiting_approval";
    case "tool_started":
      return "executing";
    case "tool_finished":
      return "thinking";
    case "turn_end":
      return "completing";
    case "turn_done":
      return "idle";
    case "input_rejected":
      return current;
    case "error":
      return "errored";
    case "interrupted":
      return "interrupted";
    default:
      return current;
  }
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "CONNECTED":
      return { ...state, connected: true };
    case "DISCONNECTED":
      return {
        ...state,
        connected: false,
        phase: "idle",
        streamBuffer: "",
        reasoningBuffer: "",
        optimisticRestorePhase: null,
        bufferEpoch: state.bufferEpoch + 1,
        phaseEpoch: state.phaseEpoch + 1,
      };
    case "TURN_REQUESTED":
      if (BUSY_PHASES.has(state.phase)) {
        return {
          ...state,
          optimisticRestorePhase: state.phase,
        };
      }
      return {
        ...state,
        phase: "starting",
        streamBuffer: "",
        reasoningBuffer: "",
        optimisticRestorePhase: state.phase,
        bufferEpoch: state.bufferEpoch + 1,
        phaseEpoch: state.phaseEpoch + 1,
      };
    case "RESET":
      return {
        phase: "idle",
        connected: false,
        streamBuffer: "",
        reasoningBuffer: "",
        optimisticRestorePhase: null,
        bufferEpoch: state.bufferEpoch + 1,
        phaseEpoch: state.phaseEpoch + 1,
      };
    case "FLUSH_BUFFERS":
      if (action.bufferEpoch !== state.bufferEpoch) return state;
      const phase = action.phaseEpoch === state.phaseEpoch ? "thinking" : state.phase;
      if (
        state.phase === phase &&
        state.streamBuffer === action.streamBuffer &&
        state.reasoningBuffer === action.reasoningBuffer &&
        state.optimisticRestorePhase === null
      ) {
        return state;
      }
      return {
        ...state,
        phase,
        streamBuffer: action.streamBuffer,
        reasoningBuffer: action.reasoningBuffer,
        optimisticRestorePhase: null,
      };
    case "EVENT": {
      const ev = action.event;

      // If the backend sends phase_changed directly, trust it.
      if (ev.type === "phase_changed" && ev.data?.phase) {
        return {
          ...state,
          phase: ev.data.phase as AgentPhase,
          optimisticRestorePhase: null,
          phaseEpoch: state.phaseEpoch + 1,
        };
      }

      const next = { ...state };
      const restoredReadyPhase = ev.type === "ready" ? readyPhase(ev.data) : null;

      if (ev.type === "turn_start") {
        next.streamBuffer = "";
        next.reasoningBuffer = "";
        next.bufferEpoch += 1;
      } else if (
        ev.type === "assistant_message" ||
        ev.type === "error" ||
        ev.type === "interrupted" ||
        ev.type === "turn_done"
      ) {
        next.streamBuffer = "";
        next.reasoningBuffer = "";
        next.bufferEpoch += 1;
      } else if (ev.type === "input_rejected") {
        const restorePhase = state.optimisticRestorePhase ?? state.phase;
        if (restorePhase === "idle" && !BUSY_PHASES.has(state.phase)) {
          next.streamBuffer = "";
          next.reasoningBuffer = "";
          next.bufferEpoch += 1;
        }
      }

      // Derive phase from legacy events (fallback when phase_changed not present)
      if (ev.type === "input_rejected") {
        next.phase = state.optimisticRestorePhase ?? (BUSY_PHASES.has(state.phase) ? state.phase : "idle");
        next.optimisticRestorePhase = null;
      } else if (restoredReadyPhase) {
        next.phase = restoredReadyPhase;
      } else {
        next.phase = phaseFromEvent(ev.type, state.phase);
        if (ev.type !== "ready" && ev.type !== "memory_cited" && ev.type !== "model_changed" && ev.type !== "inbound") {
          next.optimisticRestorePhase = null;
        }
      }

      if (next.phase !== state.phase) {
        next.phaseEpoch += 1;
      }

      return next;
    }
  }
}

const INITIAL_STATE: State = {
  phase: "idle",
  connected: false,
  streamBuffer: "",
  reasoningBuffer: "",
  optimisticRestorePhase: null,
  bufferEpoch: 0,
  phaseEpoch: 0,
};

const BUSY_PHASES: Set<AgentPhase> = new Set([
  "starting", "thinking", "tool_pending", "awaiting_approval", "executing", "completing",
]);

type ScheduledFrame = { id: number; kind: "raf" | "timeout" };

function requestFlushFrame(callback: FrameRequestCallback): ScheduledFrame {
  if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
    return { id: window.requestAnimationFrame(callback), kind: "raf" };
  }
  return {
    id: globalThis.setTimeout(() => callback(Date.now()), 16) as unknown as number,
    kind: "timeout",
  };
}

function cancelFlushFrame(frame: ScheduledFrame) {
  if (frame.kind === "raf" && typeof window !== "undefined" && typeof window.cancelAnimationFrame === "function") {
    window.cancelAnimationFrame(frame.id);
    return;
  }
  globalThis.clearTimeout(frame.id);
}

export function useAgentLifecycle(): [AgentLifecycle, LifecycleActions] {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const streamRef = useRef(state.streamBuffer);
  const reasonRef = useRef(state.reasoningBuffer);
  const phaseRef = useRef(state.phase);
  const optimisticRestoreRef = useRef(state.optimisticRestorePhase);
  const bufferEpochRef = useRef(state.bufferEpoch);
  const phaseEpochRef = useRef(state.phaseEpoch);
  const scheduledFlushRef = useRef<ScheduledFrame | null>(null);
  phaseRef.current = state.phase;
  optimisticRestoreRef.current = state.optimisticRestorePhase;
  bufferEpochRef.current = state.bufferEpoch;
  phaseEpochRef.current = state.phaseEpoch;

  const cancelScheduledFlush = useCallback(() => {
    const scheduled = scheduledFlushRef.current;
    if (!scheduled) return;
    scheduledFlushRef.current = null;
    cancelFlushFrame(scheduled);
  }, []);

  const clearBuffers = useCallback(() => {
    cancelScheduledFlush();
    streamRef.current = "";
    reasonRef.current = "";
    bufferEpochRef.current += 1;
  }, [cancelScheduledFlush]);

  const scheduleBufferFlush = useCallback(() => {
    if (scheduledFlushRef.current) return;
    const bufferEpoch = bufferEpochRef.current;
    const phaseEpoch = phaseEpochRef.current;
    scheduledFlushRef.current = requestFlushFrame(() => {
      scheduledFlushRef.current = null;
      dispatch({
        type: "FLUSH_BUFFERS",
        streamBuffer: streamRef.current,
        reasoningBuffer: reasonRef.current,
        bufferEpoch,
        phaseEpoch,
      });
    });
  }, []);

  useEffect(() => cancelScheduledFlush, [cancelScheduledFlush]);

  const handleEvent = useCallback((event: WsEvent) => {
    if (event.type === "assistant_delta") {
      streamRef.current += event.data?.text || event.data?.delta || "";
      phaseRef.current = "thinking";
      optimisticRestoreRef.current = null;
      scheduleBufferFlush();
      return;
    }
    if (event.type === "reasoning_delta") {
      reasonRef.current += event.data?.text || event.data?.delta || "";
      phaseRef.current = "thinking";
      optimisticRestoreRef.current = null;
      scheduleBufferFlush();
      return;
    }
    if (
      event.type === "turn_start" ||
      event.type === "assistant_message" ||
      event.type === "error" ||
      event.type === "interrupted" ||
      event.type === "turn_done"
    ) {
      clearBuffers();
    } else if (event.type === "input_rejected") {
      const restorePhase = optimisticRestoreRef.current ?? phaseRef.current;
      if (restorePhase === "idle" && !BUSY_PHASES.has(phaseRef.current)) {
        clearBuffers();
      }
    }
    dispatch({ type: "EVENT", event });
  }, [clearBuffers, scheduleBufferFlush]);

  const onConnected = useCallback(() => dispatch({ type: "CONNECTED" }), []);
  const onDisconnected = useCallback(() => {
    clearBuffers();
    dispatch({ type: "DISCONNECTED" });
  }, [clearBuffers]);
  const onTurnRequested = useCallback(() => {
    if (!BUSY_PHASES.has(phaseRef.current)) {
      phaseRef.current = "starting";
      phaseEpochRef.current += 1;
      clearBuffers();
    }
    dispatch({ type: "TURN_REQUESTED" });
  }, [clearBuffers]);
  const reset = useCallback(() => {
    clearBuffers();
    dispatch({ type: "RESET" });
  }, [clearBuffers]);

  const lifecycle: AgentLifecycle = {
    phase: state.phase,
    connected: state.connected,
    busy: BUSY_PHASES.has(state.phase),
    streamBuffer: state.streamBuffer,
    reasoningBuffer: state.reasoningBuffer,
  };

  const actions: LifecycleActions = {
    handleEvent,
    onConnected,
    onDisconnected,
    onTurnRequested,
    reset,
    getStreamBuffer: () => streamRef.current,
    getReasoningBuffer: () => reasonRef.current,
  };

  return [lifecycle, actions];
}
