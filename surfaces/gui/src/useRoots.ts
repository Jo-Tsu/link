import { useCallback, useEffect, useRef, useState } from "react";
import { addRoot, getRoots, removeRoot, type RootInfo } from "./api";

// Shared roots state for a session — used by the Session settings drawer's Working-directories
// section, the settings row's folder glance, and the session start panel. Reads are live;
// mutations go through the manager, which applies them to the running engine and persists them.
// `reloadKey` bumps force a refetch (e.g. when the drawer reopens).
export function useRoots(sessionId: string, reloadKey?: number) {
  const [roots, setRoots] = useState<RootInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestRef = useRef(0);

  const reload = useCallback(
    () => {
      const requestId = ++requestRef.current;
      return getRoots(sessionId)
        .then((next) => {
          if (requestRef.current === requestId) setRoots(next);
          return next;
        })
        .catch(() => {
          if (requestRef.current === requestId) setRoots([]);
          return [];
        });
    },
    [sessionId],
  );
  useEffect(() => {
    setRoots([]);
    reload();
    return () => {
      requestRef.current += 1;
    };
  }, [reload, reloadKey]);

  // Several components hold their own instance of this hook (composer chip, start panel) — a
  // mutation in one broadcasts so the others refetch and stay in sync.
  useEffect(() => {
    const onChanged = (e: Event) => {
      if ((e as CustomEvent).detail === sessionId) reload();
    };
    window.addEventListener("link:roots-changed", onChanged);
    return () => window.removeEventListener("link:roots-changed", onChanged);
  }, [sessionId, reload]);

  const apply = useCallback((res: { ok: boolean; error?: string; roots?: RootInfo[] }): boolean => {
    if (res.ok && res.roots) {
      setRoots(res.roots);
      setError("");
      window.dispatchEvent(new CustomEvent("link:roots-changed", { detail: sessionId }));
      return true;
    }
    setError(res.error || "could not update directories");
    reload();
    return false;
  }, [reload, sessionId]);

  const mutate = useCallback(
    async (operation: () => Promise<{ ok: boolean; error?: string; roots?: RootInfo[] }>) => {
      setBusy(true);
      try {
        return apply(await operation());
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "could not update directories");
        void reload();
        return false;
      } finally {
        setBusy(false);
      }
    },
    [apply, reload],
  );

  const add = useCallback(
    async (path: string, writable: boolean): Promise<boolean> => {
      return mutate(() => addRoot(sessionId, path, writable));
    },
    [mutate, sessionId],
  );

  const toggleAccess = useCallback(
    async (r: RootInfo) => {
      if (r.primary) return;
      await mutate(() => addRoot(sessionId, r.path, !r.writable)); // re-add updates access in place
    },
    [mutate, sessionId],
  );

  const remove = useCallback(
    async (path: string) => {
      await mutate(() => removeRoot(sessionId, path));
    },
    [mutate, sessionId],
  );

  return { roots, busy, error, reload, addRoot: add, toggleAccess, removeRoot: remove };
}
