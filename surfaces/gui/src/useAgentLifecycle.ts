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
}

type Action =
  | { type: "EVENT"; event: WsEvent }
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
      };
    case "TURN_REQUESTED":
      return {
        ...state,
        phase: BUSY_PHASES.has(state.phase) ? state.phase : "starting",
        streamBuffer: BUSY_PHASES.has(state.phase) ? state.streamBuffer : "",
        reasoningBuffer: BUSY_PHASES.has(state.phase) ? state.reasoningBuffer : "",
        optimisticRestorePhase: state.phase,
      };
    case "RESET":
      return {
        phase: "idle",
        connected: false,
        streamBuffer: "",
        reasoningBuffer: "",
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
        };
      }

      const next = { ...state };
      const restoredReadyPhase = ev.type === "ready" ? readyPhase(ev.data) : null;

      // Accumulate streaming text
      if (ev.type === "assistant_delta") {
        next.streamBuffer += ev.data?.text || ev.data?.delta || "";
      } else if (ev.type === "reasoning_delta") {
        next.reasoningBuffer += ev.data?.text || ev.data?.delta || "";
      } else if (ev.type === "turn_start") {
        next.streamBuffer = "";
        next.reasoningBuffer = "";
      } else if (
        ev.type === "assistant_message" ||
        ev.type === "error" ||
        ev.type === "interrupted" ||
        ev.type === "turn_done"
      ) {
        next.streamBuffer = "";
        next.reasoningBuffer = "";
      } else if (ev.type === "input_rejected") {
        const restorePhase = state.optimisticRestorePhase ?? state.phase;
        if (restorePhase === "idle" && !BUSY_PHASES.has(state.phase)) {
          next.streamBuffer = "";
          next.reasoningBuffer = "";
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
};

const BUSY_PHASES: Set<AgentPhase> = new Set([
  "starting", "thinking", "tool_pending", "awaiting_approval", "executing", "completing",
]);

export function useAgentLifecycle(): [AgentLifecycle, LifecycleActions] {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const streamRef = useRef(state.streamBuffer);
  const reasonRef = useRef(state.reasoningBuffer);
  const phaseRef = useRef(state.phase);
  const optimisticRestoreRef = useRef(state.optimisticRestorePhase);
  streamRef.current = state.streamBuffer;
  reasonRef.current = state.reasoningBuffer;
  phaseRef.current = state.phase;
  optimisticRestoreRef.current = state.optimisticRestorePhase;

  const handleEvent = useCallback((event: WsEvent) => {
    if (event.type === "assistant_delta") {
      streamRef.current += event.data?.text || event.data?.delta || "";
    } else if (event.type === "reasoning_delta") {
      reasonRef.current += event.data?.text || event.data?.delta || "";
    } else if (
      event.type === "turn_start" ||
      event.type === "assistant_message" ||
      event.type === "error" ||
      event.type === "interrupted" ||
      event.type === "turn_done"
    ) {
      streamRef.current = "";
      reasonRef.current = "";
    } else if (event.type === "input_rejected") {
      const restorePhase = optimisticRestoreRef.current ?? phaseRef.current;
      if (restorePhase === "idle" && !BUSY_PHASES.has(phaseRef.current)) {
        streamRef.current = "";
        reasonRef.current = "";
      }
    }
    dispatch({ type: "EVENT", event });
  }, []);

  const onConnected = useCallback(() => dispatch({ type: "CONNECTED" }), []);
  const onDisconnected = useCallback(() => {
    streamRef.current = "";
    reasonRef.current = "";
    dispatch({ type: "DISCONNECTED" });
  }, []);
  const onTurnRequested = useCallback(() => {
    streamRef.current = "";
    reasonRef.current = "";
    dispatch({ type: "TURN_REQUESTED" });
  }, []);
  const reset = useCallback(() => {
    streamRef.current = "";
    reasonRef.current = "";
    dispatch({ type: "RESET" });
  }, []);

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
