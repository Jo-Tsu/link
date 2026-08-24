export interface RunTask {
  id: string;
  title: string;
}

export interface RunSessionContext extends RunTask {
  sessionId: string;
}

export type PendingSessionPrompts = Record<string, string>;

export function runTaskOrNull(
  taskId?: string | null,
  title?: string | null,
): RunTask | null {
  if (!taskId) return null;
  return { id: taskId, title: title || "" };
}

export function bindPendingSessionPrompt(
  pendingPrompts: PendingSessionPrompts,
  sessionId: string,
  prompt?: string | null,
): PendingSessionPrompts {
  if (!sessionId || !prompt) return pendingPrompts;
  return { ...pendingPrompts, [sessionId]: prompt };
}

export function consumePendingSessionPrompt(
  sessionId: string,
  pendingPrompts: PendingSessionPrompts,
): { nextPendingPrompts: PendingSessionPrompts; prompt: string | null } {
  const prompt = pendingPrompts[sessionId];
  if (!prompt) return { nextPendingPrompts: pendingPrompts, prompt: null };
  const nextPendingPrompts = { ...pendingPrompts };
  delete nextPendingPrompts[sessionId];
  return { nextPendingPrompts, prompt };
}

export function bindRunContext(
  sessionId: string,
  runTask?: RunTask | null,
): RunSessionContext | null {
  if (!runTask || !sessionId.startsWith("__run__")) return null;
  return { sessionId, ...runTask };
}

export function activeRunContextForSession(
  sessionId: string,
  runContext: RunSessionContext | null,
): RunSessionContext | null {
  if (!runContext) return null;
  if (!sessionId.startsWith("__run__")) return null;
  return runContext.sessionId === sessionId ? runContext : null;
}
