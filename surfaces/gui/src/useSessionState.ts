import { useCallback, useRef, useState, type SetStateAction } from "react";
import type { Item, TodoItem } from "./types";

let _id = 0;
export function newId(): string {
  return `${Date.now().toString(36)}-${(++_id).toString(36)}`;
}

export interface SessionState {
  items: Item[];
  updateItems: (value: SetStateAction<Item[]>) => void;
  streaming: string;
  setStreaming: (value: string | ((s: string) => string)) => void;
  streamingRef: React.RefObject<string>;
  reasoningStream: string;
  setReasoningStream: (value: string) => void;
  reasoningRef: React.RefObject<string>;
  running: boolean;
  setRunning: (value: boolean) => void;
  connected: boolean;
  setConnected: (value: boolean) => void;
  sessionId: string;
  setSessionId: (value: string) => void;
  activeSessionIdRef: React.RefObject<string>;
  transcriptRevisionRef: React.RefObject<number>;
  todo: TodoItem[];
  setTodo: (value: SetStateAction<TodoItem[]>) => void;
  historyLoading: boolean;
  setHistoryLoading: (value: boolean) => void;
  resetForNewSession: () => void;
}

export function useSessionState(): SessionState {
  const [items, setItems] = useState<Item[]>([]);
  const [streaming, setStreamingState] = useState("");
  const streamingRef = useRef("");
  const [reasoningStream, setReasoningStreamState] = useState("");
  const reasoningRef = useRef("");
  const [running, setRunning] = useState(false);
  const [connected, setConnected] = useState(false);
  const [sessionId, setSessionId] = useState<string>(newId());
  const activeSessionIdRef = useRef(sessionId);
  const transcriptRevisionRef = useRef(0);
  const [todo, setTodo] = useState<TodoItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const setStreaming = useCallback((value: string | ((s: string) => string)) => {
    streamingRef.current = typeof value === "function" ? value(streamingRef.current) : value;
    setStreamingState(streamingRef.current);
  }, []);

  const setReasoningStream = useCallback((value: string) => {
    reasoningRef.current = value;
    setReasoningStreamState(value);
  }, []);

  const updateItems = useCallback((value: SetStateAction<Item[]>) => {
    transcriptRevisionRef.current += 1;
    setItems(value);
  }, []);

  const resetForNewSession = useCallback(() => {
    setItems([]);
    setStreamingState("");
    streamingRef.current = "";
    setReasoningStreamState("");
    reasoningRef.current = "";
    setRunning(false);
    setTodo([]);
    transcriptRevisionRef.current = 0;
  }, []);

  return {
    items,
    updateItems,
    streaming,
    setStreaming,
    streamingRef,
    reasoningStream,
    setReasoningStream,
    reasoningRef,
    running,
    setRunning,
    connected,
    setConnected,
    sessionId,
    setSessionId,
    activeSessionIdRef,
    transcriptRevisionRef,
    todo,
    setTodo,
    historyLoading,
    setHistoryLoading,
    resetForNewSession,
  };
}
