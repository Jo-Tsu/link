/**
 * useAgentLifecycle — single source of truth for agent lifecycle state.
 *
 * Replaces scattered running/connected/streaming booleans with a deterministic
 * state machine driven by server events. Supports both the new phase_changed
 * event and inference from legacy content events for backward compatibility.
 */

import { useCallback, useReducer, useRef } from "react";
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
  reset: () => void;
  getStreamBuffer: () => string;
  getReasoningBuffer: () => string;
}

interface State {
  phase: AgentPhase;
  connected: boolean;
  streamBuffer: string;
  reasoningBuffer: string;
}

type Action =
  | { type: "EVENT"; event: WsEvent }
  | { type: "CONNECTED" }
  | { type: "DISCONNECTED" }
  | { type: "RESET" };

function phaseFromEvent(eventType: string, current: AgentPhase): AgentPhase {
  switch (eventType) {
    case "turn_start":
      return "starting";
    case "assistant_delta":
    case "reasoning_delta":
      return current === "idle" ? current : "thinking";
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
    case "turn_done":
      return "idle";
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
      return { ...state, connected: false, phase: "idle", streamBuffer: "", reasoningBuffer: "" };
    case "RESET":
      return { phase: "idle", connected: false, streamBuffer: "", reasoningBuffer: "" };
    case "EVENT": {
      const ev = action.event;

      // If the backend sends phase_changed directly, trust it.
      if (ev.type === "phase_changed" && ev.data?.phase) {
        return { ...state, phase: ev.data.phase as AgentPhase };
      }

      const next = { ...state };

      // Accumulate streaming text
      if (ev.type === "assistant_delta") {
        next.streamBuffer += ev.data?.text || ev.data?.delta || "";
      } else if (ev.type === "reasoning_delta") {
        next.reasoningBuffer += ev.data?.text || ev.data?.delta || "";
      } else if (ev.type === "turn_start") {
        next.streamBuffer = "";
        next.reasoningBuffer = "";
      } else if (ev.type === "assistant_message") {
        next.streamBuffer = "";
        next.reasoningBuffer = "";
      }

      // Derive phase from legacy events (fallback when phase_changed not present)
      if (ev.type !== "phase_changed") {
        next.phase = phaseFromEvent(ev.type, state.phase);
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
};

const BUSY_PHASES: Set<AgentPhase> = new Set([
  "starting", "thinking", "tool_pending", "awaiting_approval", "executing", "completing",
]);

export function useAgentLifecycle(): [AgentLifecycle, LifecycleActions] {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const streamRef = useRef(state.streamBuffer);
  const reasonRef = useRef(state.reasoningBuffer);
  streamRef.current = state.streamBuffer;
  reasonRef.current = state.reasoningBuffer;

  const handleEvent = useCallback((event: WsEvent) => {
    dispatch({ type: "EVENT", event });
  }, []);

  const onConnected = useCallback(() => dispatch({ type: "CONNECTED" }), []);
  const onDisconnected = useCallback(() => dispatch({ type: "DISCONNECTED" }), []);
  const reset = useCallback(() => dispatch({ type: "RESET" }), []);

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
    reset,
    getStreamBuffer: () => streamRef.current,
    getReasoningBuffer: () => reasonRef.current,
  };

  return [lifecycle, actions];
}
