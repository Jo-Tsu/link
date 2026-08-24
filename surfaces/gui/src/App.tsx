import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent,
  type SetStateAction,
} from "react";
import {
  announceInboxUnlock,
  getArtifacts,
  getHealth,
  getProjects,
  getRecentWorkspaces,
  getSessionMessages,
  getSessions,
  announceAutomationsChanged,
  connectEvents,
  createProject,
  getSettings,
  getPersonas,
  getInbox,
  getUnattended,
  PERSONAS_CHANGED,
  resolveInboxItem,
  deleteSession,
  renameSession,
  runAutomation,
  setSessionFlags,
  setUnattended,
  Session,
  type InboxItem,
  type ModelSettings,
  type Persona,
  type SurfaceVisibility,
  type WorkspaceCommandTrust,
} from "./api";
import type { ApprovalDecision, Attachment, Item, Project, SessionInfo, TodoItem, WsEvent } from "./types";
import { isProjectScoped } from "./personaScope";
import { baseName } from "./paths";
import { itemsFromMessages } from "./itemsFromMessages";
import { streamMode } from "./streamGate";
import { InboxItemCard } from "./components/InboxItemCard";
import { isTauri, platformOS, startWindowDrag } from "./tauri";
import { Icon } from "./components/Icon";
import { Sidebar } from "./components/Sidebar";
import { CompactSidebar } from "./components/CompactSidebar";
import { ThinkingBlock, Transcript } from "./components/Transcript";
import { Composer } from "./components/Composer";
import { Markdown } from "./components/Markdown";
import { SearchModal } from "./components/SearchModal";
import { SessionIntro } from "./components/SessionIntro";
import { FolderGate } from "./components/FolderGate";
import { CreateProjectModal } from "./components/CreateProjectModal";
import { RightRail } from "./components/RightRail";
import { ApprovalCard } from "./components/ApprovalCard";
import { DirectoryRequestCard } from "./components/DirectoryRequestCard";
import { PlanCard } from "./components/PlanCard";
import { WorkspaceTrustPrompt } from "./components/WorkspaceTrustPrompt";
import { PageState } from "./components/AsyncFeedback";
import { useI18n } from "./i18n";
import { shouldStartWindowDrag } from "./windowDrag";
import { useAgentLifecycle } from "./useAgentLifecycle";
import { projectSessionEvent } from "./sessionEventProjector";
import {
  activeRunContextForSession,
  bindPendingSessionPrompt,
  bindRunContext,
  consumePendingSessionPrompt,
  runTaskOrNull,
  type PendingSessionPrompts,
  type RunSessionContext,
} from "./runContext";

const ScheduledView = lazy(() =>
  import("./components/ScheduledView").then((module) => ({ default: module.ScheduledView })),
);
const RunsView = lazy(() =>
  import("./components/RunsView").then((module) => ({ default: module.RunsView })),
);
const IntegrationsView = lazy(() =>
  import("./components/IntegrationsView").then((module) => ({ default: module.IntegrationsView })),
);
const AppsView = lazy(() =>
  import("./components/AppsView").then((module) => ({ default: module.AppsView })),
);
const ProjectView = lazy(() =>
  import("./components/ProjectView").then((module) => ({ default: module.ProjectView })),
);
const MemoryView = lazy(() =>
  import("./components/MemoryView").then((module) => ({ default: module.MemoryView })),
);
const AgentsView = lazy(() =>
  import("./components/AgentsView").then((module) => ({ default: module.AgentsView })),
);
const SettingsView = lazy(() =>
  import("./components/SettingsView").then((module) => ({ default: module.SettingsView })),
);
const PersonaView = lazy(() =>
  import("./components/PersonaView").then((module) => ({ default: module.PersonaView })),
);
const AuditView = lazy(() =>
  import("./components/AuditView").then((module) => ({ default: module.AuditView })),
);
const InboxView = lazy(() =>
  import("./components/InboxView").then((module) => ({ default: module.InboxView })),
);
const Onboarding = lazy(() =>
  import("./components/Onboarding").then((module) => ({ default: module.Onboarding })),
);

const newId = () =>
  (crypto as any).randomUUID ? crypto.randomUUID().slice(0, 12) : Math.random().toString(36).slice(2, 14);

const SUGGESTIONS = [
  { ico: "⚙", text: "Run the test suite and summarize any failures." },
  { ico: "✦", text: "Read the project and give me a 5-bullet overview." },
  { ico: "↻", text: "Find and fix the failing build." },
];

// Fallbacks used only before the persona list loads (the in-component, family-aware
// needsWorkspace/gatesWorkspace consult the real persona once available).
const needsWorkspaceFallback = (a: string) => a === "code" || a === "link";
const gatesWorkspaceFallback = (a: string) => a === "code";
const LAST_SESSION_KEY = "link:last-session-by-agent:v1";
const NAV_COLLAPSED_KEY = "link:nav-collapsed:v1";

type LastSession = { sessionId: string; workspace: string; updatedAt: number };

function readLastSessions(): Record<string, LastSession> {
  try {
    const raw = localStorage.getItem(LAST_SESSION_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function rememberLastSession(agent: string, sessionId: string, workspace: string | null) {
  if (!agent || !sessionId) return;
  try {
    const all = readLastSessions();
    all[agent] = { sessionId, workspace: workspace || "", updatedAt: Date.now() };
    localStorage.setItem(LAST_SESSION_KEY, JSON.stringify(all));
  } catch {
    /* localStorage may be unavailable; session restore is best effort. */
  }
}

function sessionTs(s: SessionInfo): number {
  return Date.parse(s.updated_at || "") || Number(s.updated_at) || 0;
}

function resumeTargetForAgent(agent: string, sessions: SessionInfo[]): LastSession | null {
  const remembered = readLastSessions()[agent];
  if (remembered?.sessionId) {
    const live = sessions.find((s) => s.session_id === remembered.sessionId && s.agent === agent);
    if (live || remembered.workspace) {
      return {
        sessionId: remembered.sessionId,
        workspace: live?.workspace ?? remembered.workspace ?? "",
        updatedAt: live ? sessionTs(live) : remembered.updatedAt,
      };
    }
  }
  const recent = sessions
    .filter((s) => s.agent === agent && s.session_id && !s.session_id.startsWith("__"))
    .sort((a, b) => sessionTs(b) - sessionTs(a))[0];
  return recent ? { sessionId: recent.session_id, workspace: recent.workspace || "", updatedAt: sessionTs(recent) } : null;
}

function fallbackWorkspace(current: string | null, projects: Project[]): string {
  if (current) return current;
  const folders = projects.filter((project) => project.project_type !== "system_app");
  const active = folders.find((p) => p.status === "active");
  return active?.workspace_path || folders[0]?.workspace_path || "";
}

function samePayload<T>(current: T, next: T): boolean {
  return JSON.stringify(current) === JSON.stringify(next);
}

function ConversationSkeleton() {
  return (
    <div className="conversation-loading" role="status" aria-label="Loading conversation">
      <div className="conversation-loading-head">
        <span className="conversation-loading-mark"><Icon name="logo" size={18} /></span>
        <span className="conversation-loading-line wide" />
      </div>
      <span className="conversation-loading-line" />
      <span className="conversation-loading-line medium" />
      <span className="conversation-loading-line short" />
    </div>
  );
}

export function App() {
  const { t, tr } = useI18n();
  const [lifecycle, lifecycleActions] = useAgentLifecycle();
  const [workspace, setWorkspace] = useState<string | null>(null);
  const [branch, setBranch] = useState<string | null>(null);
  const [showGate, setShowGate] = useState(false);
  const [showCreateProject, setShowCreateProject] = useState(false);
  const [workspaceTrustRequest, setWorkspaceTrustRequest] =
    useState<WorkspaceCommandTrust | null>(null);
  const [agent, setAgent] = useState("link");
  const [model, setModel] = useState("gpt-5.6-sol");
  const [models, setModels] = useState<string[]>([]);
  const [modelLabels, setModelLabels] = useState<Record<string, string>>({});
  const [surfaces, setSurfaces] = useState<SurfaceVisibility>({ link: true, chat: false, code: false });
  const [mode, setMode] = useState("interactive");
  const [items, setItems] = useState<Item[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const connected = lifecycle.connected;
  const running = lifecycle.busy;
  const streaming = lifecycle.streamBuffer;
  const reasoningStream = lifecycle.reasoningBuffer;
  const [todo, setTodo] = useState<TodoItem[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [sessionId, setSessionId] = useState<string>(newId());
  const activeSessionIdRef = useRef(sessionId);
  const transcriptRevisionRef = useRef(0);
  const sessionRef = useRef<Session | null>(null);
  const updateItems = (value: SetStateAction<Item[]>) => {
    transcriptRevisionRef.current += 1;
    setItems(value);
  };
  // Automation-run context (§ owner ask 2026-07-04): which task an open __run__ session belongs
  // to, driving the banner + "Back to runs". Best-effort — a run session without context still
  // shows a generic banner (detected by its __run__ id).
  const [runContext, setRunContext] = useState<RunSessionContext | null>(null);
  // Which automation the Automations surface opens on (set by the banner's Back link
  // or a sidebar Scheduled-band click). Cleared on leaving the surface: a remembered
  // id going stale (e.g. the automation was deleted) reopened a dead detail —
  // "Loading…" forever (owner-hit 2026-07-20). Nav re-entry should land on the list.
  const [scheduledOpenId, setScheduledOpenId] = useState<string | null>(null);
  const [gateCreate, setGateCreate] = useState(false);
  // Which Settings section the full-page Settings surface opens on (§ Settings-as-page).
  const [settingsTab, setSettingsTab] = useState<"appearance" | "models" | "voice" | "personas">(
    "appearance",
  );
  const openSettings = (tab: "appearance" | "models" | "voice" | "personas" = "appearance") => {
    setSettingsTab(tab);
    setSurface("settings");
  };
  // Whether the default model's provider is actually configured (any provider). Drives the
  // composer's "No model connected" chip. Default true so we don't flash the chip before settings
  // load; corrected by loadSettings.
  const [modelReady, setModelReady] = useState(true);
  const [surface, setSurface] = useState<
    "session" | "project" | "apps" | "agents" | "runs" | "scheduled" | "integrations" | "memory" | "audit" | "inbox" | "persona" | "settings"
  >("session");
  const [projectViewId, setProjectViewId] = useState<string | null>(null);
  const [appViewId, setAppViewId] = useState<string | null>(null);
  const activeRunContext = activeRunContextForSession(sessionId, runContext);
  // A remembered Scheduled-detail target must not outlive the surface (see the
  // scheduledOpenId comment above): nav re-entry lands on the list, never a
  // possibly-deleted automation's dead detail.
  useEffect(() => {
    if (surface !== "scheduled") setScheduledOpenId(null);
  }, [surface]);
  // The persona whose detail page is showing (surface === "persona"); empty falls back to the
  // active session's persona. Phase 5 wires the grouped-nav gear + "Manage personas…" entry points.
  const [personaViewId, setPersonaViewId] = useState<string>("");
  // Where the persona page returns on "back": the active session, or Settings ▸ Personas when it
  // was opened from there (persona config now lives in Settings).
  const [personaViewReturn, setPersonaViewReturn] = useState<"session" | "settings">("session");
  const openPersona = (id: string, from: "session" | "settings" = "session") => {
    setPersonaViewReturn(from);
    setPersonaViewId(id);
    setSurface("persona");
  };
  const [browserRefreshKey, setBrowserRefreshKey] = useState(0);
  const [railHidden, setRailHidden] = useState(false);
  // Left-nav collapse (⌘B): the full sidebar becomes a stable compact action rail.
  const [navCollapsed, setNavCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem(NAV_COLLAPSED_KEY) === "1"; } catch { return false; }
  });
  // While an artifact preview is open we auto-collapse the nav (#3). Remember the pre-preview
  // collapse state so we can restore it on close — unless the user re-opened the nav meanwhile.
  const navBeforePreview = useRef<boolean | null>(null);
  const setNavCollapsedPersist = useCallback((v: boolean) => {
    setNavCollapsed(v);
    try { localStorage.setItem(NAV_COLLAPSED_KEY, v ? "1" : "0"); } catch { /* best effort */ }
  }, []);
  const toggleNav = useCallback(() => {
    navBeforePreview.current = null; // a manual toggle takes control from the artifact auto-collapse
    setNavCollapsedPersist(!navCollapsed);
  }, [navCollapsed, setNavCollapsedPersist]);
  // #3: collapse the nav while a full artifact preview is open, restore it on close (unless the
  // user manually toggled meanwhile). The collapse is transient — it never overwrites the pref.
  const onArtifactPreview = useCallback((open: boolean) => {
    if (open) {
      if (navBeforePreview.current === null) navBeforePreview.current = navCollapsed;
      setNavCollapsed(true);
    } else if (navBeforePreview.current !== null) {
      setNavCollapsed(navBeforePreview.current);
      navBeforePreview.current = null;
    }
  }, [navCollapsed]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggleNav();
      }
      // ⌘, — the platform Settings shortcut (advertised in the account menu, §26).
      if ((e.metaKey || e.ctrlKey) && e.key === ",") {
        e.preventDefault();
        setSurface("settings");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleNav]);
  // Count of files this Link conversation has produced — surfaces an "Artifacts (N)" button in
  // the topbar when the side panel is hidden, so produced files are never buried.
  const [artifactCount, setArtifactCount] = useState(0);
  // §32 deep link into the rail's Access section (the former Session-settings drawer): bumping
  // the key expands the section and scrolls it into view. Callers also un-hide the rail.
  const [accessKey, setAccessKey] = useState(0);
  const openAccess = () => {
    setRailHidden(false);
    setAccessKey((k) => k + 1);
  };
  // §34 (UX-016): clicking an artifact chip in the transcript must land somewhere visible —
  // RightRail opens the viewer; this just makes sure the rail isn't hidden.
  useEffect(() => {
    const show = () => setRailHidden(false);
    window.addEventListener("link-open-artifact", show);
    return () => window.removeEventListener("link-open-artifact", show);
  }, []);
  // The command-palette search, openable from the collapsed-sidebar topbar cluster (§22). The
  // expanded sidebar owns its own instance; this one exists so search never disappears with it.
  const [searchOpen, setSearchOpen] = useState(false);
  // A pending composer prefill (text + attachments) pushed from the session start panel.
  const [composerPrefill, setComposerPrefill] = useState<{ text: string; attachments?: Attachment[]; nonce: number }>();

  // Persona metadata drives workspace behavior by FAMILY, not by hardcoded id (so a DevOps/SecOps
  // code-family persona gates a folder like Code, and a knowledge persona starts orphan like Link).
  const [personas, setPersonas] = useState<Persona[] | null>(null);
  const [sidebarPrefs, setSidebarPrefs] = useState<{
    navLayout?: "flat" | "grouped";
    sessionsPeek?: number;
  }>({});
  const personaOf = (a: string) => personas?.find((p) => p.id === a);

  // Pending Inbox items for the ACTIVE session — surfaced inline above the composer so an
  // unattended session's blocking question/approval can be answered in context (resolving the
  // same item the Inbox shows; first responder wins).
  const [sessionInbox, setSessionInbox] = useState<InboxItem[]>([]);
  // Whether the active session is Unattended — when true, the agent's prompts route to the Inbox,
  // so we suppress the inline live cards (the Inbox / answer-in-context path shows them instead).
  // A ref too, because the WS event handler closes over stale state.
  const [unattended, setUnattendedState] = useState(false);
  const unattendedRef = useRef(false);
  const markUnattended = useCallback((on: boolean) => {
    unattendedRef.current = on;
    setUnattendedState(on);
  }, []);
  const activateSession = (
    nextSessionId: string,
    loadingHistory = false,
    nextRunContext: RunSessionContext | null = null,
  ) => {
    activeSessionIdRef.current = nextSessionId;
    transcriptRevisionRef.current += 1;
    sessionRef.current?.close();
    sessionRef.current = null;
    lifecycleActions.reset();
    setRunContext(nextRunContext);
    setSessionInbox([]);
    setItems([]);
    setTodo([]);
    setHistoryLoading(loadingHistory);
    setSessionId(nextSessionId);
  };
  const loadSessionHistory = async (targetSessionId: string, ignoreEmpty = false) => {
    const revision = transcriptRevisionRef.current;
    try {
      const messages = await getSessionMessages(targetSessionId);
      if (
        activeSessionIdRef.current !== targetSessionId ||
        transcriptRevisionRef.current !== revision ||
        (ignoreEmpty && messages.length === 0)
      ) {
        return;
      }
      transcriptRevisionRef.current += 1;
      setItems(itemsFromMessages(messages));
    } catch {
      if (
        activeSessionIdRef.current === targetSessionId &&
        transcriptRevisionRef.current === revision &&
        !ignoreEmpty
      ) {
        transcriptRevisionRef.current += 1;
        setItems([]);
      }
    } finally {
      if (activeSessionIdRef.current === targetSessionId) setHistoryLoading(false);
    }
  };
  // The Mode menu's "Send approvals to Inbox" toggle (§22 — the old InboxControl, folded in).
  const toggleUnattended = async (on: boolean) => {
    const targetSessionId = sessionId;
    await setUnattended(targetSessionId, on);
    if (activeSessionIdRef.current !== targetSessionId) return;
    markUnattended(on);
    // First Unattended enable = Inbox machinery engaged → the account row's chip unlocks (§26).
    if (on) announceInboxUnlock();
  };
  const resolveSessionInbox = async (id: string, resolution: string) => {
    const targetSessionId = sessionId;
    await resolveInboxItem(id, resolution);
    if (activeSessionIdRef.current !== targetSessionId) return;
    getInbox(targetSessionId, "pending")
      .then((items) => {
        if (activeSessionIdRef.current === targetSessionId) setSessionInbox(items);
      })
      .catch(() => {
        if (activeSessionIdRef.current === targetSessionId) setSessionInbox([]);
      });
    refreshSessions(); // attention badge should drop right away
  };
  // Shows a working-area chip / project grouping. Persona's needs_workspace; fallback before load.
  const needsWorkspace = (a: string) => personaOf(a)?.needs_workspace ?? needsWorkspaceFallback(a);
  // MUST pick a folder before starting — project-scoped personas (git-bound Code, project-bound
  // Ops). Scratch/deliverable personas start orphan: the server auto-provisions a per-conversation
  // scratch dir and reports it in the `ready` event.
  const gatesWorkspace = (a: string) => {
    const p = personaOf(a);
    return p ? isProjectScoped(p) : gatesWorkspaceFallback(a);
  };

  // The desktop tray's "Settings" item dispatches this on the window.
  useEffect(() => {
    const open = () => openSettings("appearance");
    window.addEventListener("link:open-settings", open);
    return () => window.removeEventListener("link:open-settings", open);
  }, []);

  // "Run setup again" (from Settings) re-opens the wizard.
  useEffect(() => {
    const open = () => {
      setOnboarding(true);
    };
    window.addEventListener("link:open-onboarding", open);
    return () => window.removeEventListener("link:open-onboarding", open);
  }, []);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  // A prompt to auto-send once the next session connects (used by "Run now").
  const pendingPromptRef = useRef<PendingSessionPrompts>({});
  // The in-flight manual run to finalize after its first turn ({taskId, runId, sessionId}).

  // Fetch ALL sessions + known projects so the sidebar can group them.
  const refreshSessionsInFlight = useRef<Promise<void> | null>(null);
  const refreshSessions = useCallback(() => {
    if (refreshSessionsInFlight.current) return refreshSessionsInFlight.current;
    const request = Promise.all([getSessions(), getProjects()])
      .then(([nextSessions, nextProjects]) => {
        setSessions((current) => samePayload(current, nextSessions) ? current : nextSessions);
        setProjects((current) => samePayload(current, nextProjects) ? current : nextProjects);
      })
      .catch(() => {})
      .finally(() => {
        if (refreshSessionsInFlight.current === request) refreshSessionsInFlight.current = null;
      });
    refreshSessionsInFlight.current = request;
    return request;
  }, []);

  // initial: adopt the server's seed workspace if any, else force the gate.
  // Retry health for a while: the desktop shell starts its sidecar in parallel, so the
  // server may not answer for a second or two. Only fall back to the gate once it's truly up.
  const [booting, setBooting] = useState(true);
  const [bootPhase, setBootPhase] = useState<"service" | "data" | "session">("service");
  const [bootError, setBootError] = useState<string | null>(null);
  const [bootAttempt, setBootAttempt] = useState(0);
  const [onboarding, setOnboarding] = useState(false);
  // Latched: keep the boot splash up until the restored session is actually CONNECTED (not just
  // until `booting` clears), so an early click can't land on a session that's still settling.
  const [uiReady, setUiReady] = useState(false);

  // On boot with no seeded workspace, reopen the last thing the user had — most recent
  // conversation (restores its folder + agent + transcript), else the most recent project
  // folder. Only a true first run (nothing to resume) falls through to the folder gate.
  const resumeLastOrGate = async (
    bootSessions?: SessionInfo[],
    bootProjects?: Project[],
  ) => {
    let loadedSessions: SessionInfo[] = bootSessions ?? [];
    try {
      if (!bootSessions) loadedSessions = await getSessions();
      loadedSessions = loadedSessions.filter((s) => s.session_id && !s.session_id.startsWith("__"));
      setSessions(loadedSessions);
      const sess = loadedSessions;
      const ts = (s: SessionInfo) => Date.parse(s.updated_at || "") || Number(s.updated_at) || 0;
      const last = [...sess].sort((a, b) => ts(b) - ts(a))[0];
      if (last) {
        if (last.agent) setAgent(last.agent);
        if (last.workspace) {
          setWorkspace(last.workspace);
          setBranch(null);
        }
        activateSession(last.session_id, true);
        await loadSessionHistory(last.session_id);
        setShowGate(false);
        return;
      }
    } catch {
      /* fall through */
    }
    try {
      const [recents, projs] = await Promise.all([
        getRecentWorkspaces(),
        bootProjects ? Promise.resolve(bootProjects) : getProjects().catch(() => []),
      ]);
      setProjects(projs);
      if (gatesWorkspace(agent)) {
        const ws = recents.find((w) => w.exists) || recents[0];
        if (ws) {
          setWorkspace(ws.path);
          setShowGate(false);
          return;
        }
      }
    } catch {
      /* fall through */
    }
    setShowGate(gatesWorkspace(agent)); // only Code forces a first-run folder gate
  };

  useEffect(() => {
    let cancelled = false;
    setBootError(null);
    setBootPhase("service");
    const attempt = (tries: number) => {
      getHealth()
        .then(async (h) => {
          if (cancelled) return;
          setModel(h.model);
          setBootPhase("data");
          // One coordinated startup read replaces the old mount effects, which requested the
          // same settings/persona/session payloads two or three times during a cold launch.
          const [bootSessions, bootProjects, settings, bootPersonas] = await Promise.all([
            getSessions().catch(() => []),
            getProjects().catch(() => []),
            getSettings().catch(() => null),
            getPersonas().catch(() => []),
          ]);
          if (cancelled) return;
          setSessions(bootSessions);
          setProjects(bootProjects);
          setPersonas(bootPersonas);
          if (settings) {
            applySettings(settings);
            if (isTauri() && !settings.onboarded) setOnboarding(true);
          }
          setBootPhase("session");
          // Settle the active session BEFORE clearing `booting` (which unblocks the connection
          // effect). resumeLastOrGate is async — if we cleared `booting` first, the throwaway
          // initial sessionId would connect against an empty/stale workspace and the server
          // would provision a junk per-conversation scratch dir for it before resume could
          // flip to the real session. Link ignores default_workspace (a Code concept).
          if (h.default_workspace && gatesWorkspace(agent)) setWorkspace(h.default_workspace);
          else await resumeLastOrGate(bootSessions, bootProjects);
          if (!cancelled) setBooting(false);
        })
        .catch((error) => {
          if (cancelled) return;
          if (tries <= 0) {
            setBooting(false);
            setUiReady(true);
            setBootError(error instanceof Error ? error.message : tr("Smallink service is unavailable"));
          } else {
            setTimeout(() => attempt(tries - 1), 500);
          }
        });
    };
    attempt(40); // ~20s of 500ms retries
    return () => {
      cancelled = true;
    };
  }, [bootAttempt]);

  // Once boot finishes, preload all lazy sub-view chunks in the background so subsequent
  // navigation never flashes the Suspense fallback.
  useEffect(() => {
    if (booting) return;
    void import("./components/ScheduledView");
    void import("./components/RunsView");
    void import("./components/IntegrationsView");
    void import("./components/MemoryView");
    void import("./components/AgentsView");
    void import("./components/SettingsView");
    void import("./components/PersonaView");
    void import("./components/AuditView");
    void import("./components/InboxView");
  }, [booting]);

  // Reveal the UI once boot has settled AND the restored session is connected (or we're showing
  // the folder gate). Latched, so later reconnects never flash the splash again.
  useEffect(() => {
    if (uiReady || booting) return;
    if (connected || showGate) setUiReady(true);
  }, [uiReady, booting, connected, showGate]);
  // Safety net: if the restored session never reports connected (backend slow/unreachable), reveal
  // the UI anyway. Boot already passed the health check, so a live connect is sub-second; this only
  // bites in the failure case, so keep it short.
  useEffect(() => {
    if (uiReady || booting) return;
    const t = setTimeout(() => setUiReady(true), 1500);
    return () => clearTimeout(t);
  }, [uiReady, booting]);

  const applySettings = (s: ModelSettings) => {
    setModels(s.models || []);
    setModelLabels(s.model_labels || {});
    setModelReady(s.model_ready);
    if (s.surfaces) setSurfaces(s.surfaces);
    setSidebarPrefs({ navLayout: s.nav_layout, sessionsPeek: s.sessions_peek });
  };

  const loadSettings = () =>
    getSettings()
      .then(applySettings)
      .catch(() => {});

  // Open Settings → Configure Models (from the composer's "No model connected" chip).
  const openModelSetup = () => openSettings("models");

  // Leaving Settings picks up model/surface changes for the composer. Track the previous surface:
  // the old `surface !== settings` check reloaded settings on every ordinary page change.
  const previousSurfaceRef = useRef(surface);
  useEffect(() => {
    const previous = previousSurfaceRef.current;
    previousSurfaceRef.current = surface;
    if (previous === "settings" && surface !== "settings") loadSettings();
  }, [surface]);

  // Session events refresh immediately; this is only a low-frequency fallback for work created
  // outside this window. Hidden windows do no polling, and refocusing catches up once.
  useEffect(() => {
    if (booting) return;
    let lastRefresh = Date.now();
    const refreshVisible = () => {
      if (document.visibilityState === "hidden") return;
      lastRefresh = Date.now();
      void refreshSessions();
    };
    const onFocus = () => {
      if (Date.now() - lastRefresh > 10_000) refreshVisible();
    };
    const t = window.setInterval(refreshVisible, 30_000);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.clearInterval(t);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [booting, refreshSessions]);

  // Persona toggles can archive sessions server-side (disable-archives, §18): refetch on the
  // personas-changed event so the sidebar section disappears immediately, not on the next poll.
  useEffect(() => {
    const onPersonas = () => refreshSessions();
    window.addEventListener(PERSONAS_CHANGED, onPersonas);
    return () => window.removeEventListener(PERSONAS_CHANGED, onPersonas);
  }, [refreshSessions]);

  // If the active surface isn't visible (hidden in Settings, or a resumed session landed on a
  // hidden surface), fall back to Link (always visible). Watches both agent and surfaces so it
  // corrects regardless of which settled last.
  useEffect(() => {
    if ((agent === "chat" && !surfaces.chat) || (agent === "code" && !surfaces.code)) {
      switchAgent("link");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent, surfaces]);

  useEffect(() => {
    if (surface === "session") rememberLastSession(agent, sessionId, workspace);
  }, [surface, agent, sessionId, workspace]);

  // (re)connect when workspace, session, or agent changes
  useEffect(() => {
    if (booting) return; // wait until boot/resume settles the session before connecting
    if (gatesWorkspace(agent) && !workspace) return; // Code needs a folder (gate handles it)
    const connectedSessionId = sessionId;
    const handleEvent = (ev: WsEvent) => {
      if (activeSessionIdRef.current !== connectedSessionId) return;
      // Project from the pre-event buffers: terminal lifecycle events clear them, while
      // interrupted/error transcript entries must preserve any partial answer first.
      const projection = projectSessionEvent(ev, {
        unattended: unattendedRef.current,
        streamBuffer: lifecycleActions.getStreamBuffer(),
        reasoningBuffer: lifecycleActions.getReasoningBuffer(),
        now: () => Date.now() / 1000,
        newId,
        tr,
      });
      lifecycleActions.handleEvent(ev);
      if (projection.updateItems) updateItems(projection.updateItems);
      if (projection.todo) setTodo(projection.todo);

      const effects = projection.effects;
      if (effects.model) setModel(effects.model);
      if (effects.mode) setMode(effects.mode);
      if (effects.workspaceTrust) setWorkspaceTrustRequest(effects.workspaceTrust);
      // Link adopts the server-provisioned scratch dir only when it has no workspace yet.
      if (effects.workspace) setWorkspace((current) => current || effects.workspace!);
      if (effects.refreshBrowser) setBrowserRefreshKey((key) => key + 1);
      if (effects.refreshSessions) refreshSessions();
    };

    const session = new Session(sessionId, workspace || "", agent, {
      onEvent: handleEvent,
      onOpen: () => {
        if (activeSessionIdRef.current !== connectedSessionId) return;
        lifecycleActions.onConnected();
        // Auto-send the task prompt once a "Run now" session connects.
        const { nextPendingPrompts, prompt } = consumePendingSessionPrompt(
          connectedSessionId,
          pendingPromptRef.current,
        );
        pendingPromptRef.current = nextPendingPrompts;
        if (prompt) {
          updateItems((prev) => [...prev, { kind: "user", text: prompt, ts: Date.now() / 1000 }]);
          lifecycleActions.onTurnRequested();
          sessionRef.current?.userMessage(prompt);
        }
      },
      onReconnect: () => {
        if (activeSessionIdRef.current !== connectedSessionId) return;
        lifecycleActions.onConnected();
        window.setTimeout(() => {
          if (activeSessionIdRef.current === connectedSessionId) {
            void loadSessionHistory(connectedSessionId, true);
          }
        }, 250);
      },
      onClose: () => {
        if (activeSessionIdRef.current === connectedSessionId) {
          lifecycleActions.onDisconnected();
        }
      },
    });
    sessionRef.current = session;
    return () => session.close();
    // NOTE: `workspace` is intentionally NOT a dependency. Every real workspace change
    // (pick folder, select/switch session, new session) is paired with a `sessionId`
    // change, so the socket still reconnects when it should. The one workspace-only change
    // is the `ready` handler adopting the server's provisioned Link scratch dir — listing
    // `workspace` here made that adoption tear down and rebuild the socket immediately after
    // first connect, dropping the user's first message (the "send twice" bug). The scratch
    // dir is deterministic from `sessionId` server-side, so skipping that reconnect is safe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [booting, sessionId, agent, refreshSessions]);

  // Stream-following (FB-004): auto-scroll only while the user is AT the bottom, so scrolling
  // up to read during a streaming turn sticks. `atBottomRef` is the live truth (per scroll
  // event, no re-render); `following` mirrors it into state for the jump-to-latest pill.
  // Programmatic smooth-scrolls fire scroll events of their own — while one is in flight
  // (`autoScrollingRef`) they must not read as "the user scrolled up", or every stream tick
  // would disengage its OWN follow. The animation only moves down, so a decreasing scrollTop
  // mid-flight can only be the user taking over.
  const atBottomRef = useRef(true);
  const autoScrollingRef = useRef(false);
  const lastScrollTopRef = useRef(0);
  const [following, setFollowing] = useState(true);
  const scrollToBottom = () => {
    const el = scrollRef.current;
    if (!el) return;
    autoScrollingRef.current = true;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };
  const followLatest = () => {
    atBottomRef.current = true;
    setFollowing(true);
    scrollToBottom();
  };
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const top = el.scrollTop;
    const atBottom = el.scrollHeight - top - el.clientHeight < 48;
    if (autoScrollingRef.current) {
      if (atBottom) autoScrollingRef.current = false; // landed
      else if (top >= lastScrollTopRef.current) {
        lastScrollTopRef.current = top; // still animating down — not the user
        return;
      } else autoScrollingRef.current = false; // moved UP mid-flight — user takeover
    }
    lastScrollTopRef.current = top;
    atBottomRef.current = atBottom;
    setFollowing(atBottom);
  };
  // A different session is a fresh viewport — never inherit a scrolled-up state. Declared
  // BEFORE the auto-scroll effect: when a session switch and its hydrated items land in one
  // commit, the reset must run first or the stale ref would skip the initial bottom-scroll.
  useEffect(() => {
    atBottomRef.current = true;
    setFollowing(true);
  }, [sessionId]);
  useEffect(() => {
    if (atBottomRef.current) scrollToBottom();
  }, [items, streaming]);

  // Track produced-file count for the topbar "Artifacts" affordance (works even when the rail is
  // hidden, where the rail itself doesn't fetch). Link only; refreshes on file writes/turn end.
  useEffect(() => {
    if (agent !== "link" || surface !== "session") {
      setArtifactCount(0);
      return;
    }
    // The visible rail owns this read and reports the count back. Only fetch here when the rail is
    // hidden, where the compact topbar affordance is the user's sole path to produced files.
    if (!railHidden) return;
    const targetSessionId = sessionId;
    getArtifacts(targetSessionId)
      .then((artifacts) => {
        if (activeSessionIdRef.current === targetSessionId) setArtifactCount(artifacts.length);
      })
      .catch(() => {
        if (activeSessionIdRef.current === targetSessionId) setArtifactCount(0);
      });
  }, [agent, surface, sessionId, browserRefreshKey, railHidden]);

  // Keep the active session's pending Inbox items fresh (answer-in-context card). Loads on session
  // change + after each turn, plus a slow poll so an unattended agent's new question surfaces.
  useEffect(() => {
    if (surface !== "session") return;
    const targetSessionId = sessionId;
    let lastLoad = 0;
    const load = () => {
      lastLoad = Date.now();
      getInbox(targetSessionId, "pending")
        .then((items) => {
          if (activeSessionIdRef.current === targetSessionId) setSessionInbox(items);
        })
        .catch(() => {
          if (activeSessionIdRef.current === targetSessionId) setSessionInbox([]);
        });
      getUnattended(targetSessionId)
        .then((on) => {
          if (activeSessionIdRef.current === targetSessionId) markUnattended(on);
        })
        .catch(() => {
          if (activeSessionIdRef.current === targetSessionId) markUnattended(false);
        });
    };
    load();
    const refreshVisible = () => {
      if (document.visibilityState !== "hidden" && Date.now() - lastLoad > 10_000) load();
    };
    const t = window.setInterval(refreshVisible, 15_000);
    window.addEventListener("focus", refreshVisible);
    return () => {
      window.clearInterval(t);
      window.removeEventListener("focus", refreshVisible);
    };
  }, [surface, sessionId, browserRefreshKey, markUnattended]);

  const send = (text: string, attachments?: Attachment[]) => {
    updateItems((p) => [...p, { kind: "user", text, attachments, ts: Date.now() / 1000 }]);
    // The visible model rides along with the message (single source of truth per turn).
    sessionRef.current?.userMessage(text, attachments, model);
    lifecycleActions.onTurnRequested();
    followLatest(); // sending always re-engages stream-following, wherever the user had scrolled
  };
  // Resolving a LIVE prompt also resolves its parked Inbox mirror server-side, but the polled
  // `sessionInbox` copy stays "pending" for up to a poll cycle — long enough for the docked
  // answer-in-context card to flash the SAME request again right after the user answered it
  // (tester catch 2026-07-12: a Slack send "asked twice"). Drop the mirror optimistically;
  // the background poll restores anything genuinely still pending.
  const dropSessionInbox = (kind: string) =>
    setSessionInbox((cur) => cur.filter((it) => it.kind !== kind));
  const approve = (decision: ApprovalDecision) => {
    updateItems((p) => resolveLastApproval(p, decision));
    dropSessionInbox("approval");
    sessionRef.current?.approve(decision, pendingApproval?.promptId);
  };
  const respondPlan = (approved: boolean, mode?: string, feedback?: string) => {
    updateItems((p) => resolveLastPlan(p, approved ? "approved" : "rejected"));
    dropSessionInbox("plan");
    sessionRef.current?.respondPlan(approved, mode, feedback, pendingPlan?.promptId);
    if (approved && mode) setMode(mode); // the server flips the live engine to this mode
  };
  const respondDirectory = (granted: boolean, path?: string, writable?: boolean) => {
    updateItems((p) => resolveLastDirReq(p, granted ? "granted" : "denied"));
    dropSessionInbox("directory");
    sessionRef.current?.respondDirectory(granted, path, writable, pendingDirReq?.promptId);
  };
  const answerQuestion = (answer: string) => {
    updateItems((p) => resolveLastQuestion(p, answer));
    dropSessionInbox("question");
    sessionRef.current?.respondQuestion(answer, pendingQuestion?.promptId);
  };
  const prefillComposer = (text: string, attachments?: Attachment[]) =>
    setComposerPrefill((p) => ({ text, attachments, nonce: (p?.nonce ?? 0) + 1 }));
  const interrupt = () => sessionRef.current?.interrupt();
  const retry = () => {
    // Optimistic running: turn_start confirms; a rejected retry still ends in turn_done.
    sessionRef.current?.retry();
    lifecycleActions.onTurnRequested();
  };
  const changeMode = (m: string) => {
    setMode(m);
    sessionRef.current?.setMode(m);
  };
  const changeModel = (m: string) => {
    if (running) return; // the server refuses mid-turn rebinds — don't let the header lie
    setModel(m);
    sessionRef.current?.setModel(m);
  };

  const startNewSession = (forAgent?: string) => {
    const target = forAgent || agent;
    setSurface("session"); // return to the conversation view if we were on a sub-view
    // "New session" under a browsed persona switches to it (expand≠switch: the header alone
    // doesn't switch; this explicit action does).
    if (target !== agent) {
      setAgent(target);
      if (gatesWorkspace(target)) {
        // Never inherit the previous persona's folder — it may be a scratch dir. Clearing it
        // also blocks the connection effect, so nothing can chat behind the open gate.
        setWorkspace(null);
        setBranch(null);
        setShowGate(true);
      } else setShowGate(false);
    }
    // Knowledge family: a new conversation starts fresh (orphan) — clear the workspace so the
    // server provisions a NEW scratch dir for the new session id. Code keeps its repo.
    if (!gatesWorkspace(target)) setWorkspace(null);
    activateSession(newId());
  };
  // Inbox → session: the item carries its session's workspace/agent, so open it directly.
  // UX-026: 5s top-right toast when a SCHEDULED automation run starts (never for
  // manual Run-now — the user is already watching). Rides the app-wide /ws/events
  // stream; View run opens the run's live session.
  const [runToast, setRunToast] = useState<{
    title: string; sessionId: string; workspace: string; agent: string; time: string; taskId: string | null;
  } | null>(null);
  useEffect(() => {
    const stop = connectEvents((msg) => {
      if (msg.type !== "automation_run_started") return;
      const d = (msg.data ?? {}) as Record<string, string>;
      setRunToast({
        title: d.task_title || tr("Automation"),
        sessionId: d.session_id || "",
        workspace: d.workspace || "",
        agent: d.agent || "link",
        time: new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }),
        taskId: d.task_id || null,
      });
      announceAutomationsChanged(); // the Scheduled band's badge is now stale
    });
    return stop;
  }, []);
  useEffect(() => {
    if (!runToast) return;
    const t = window.setTimeout(() => setRunToast(null), 5000);
    return () => window.clearTimeout(t);
  }, [runToast]);

  const openSessionFromInbox = (sid: string, ws: string, ag: string) => selectSession(sid, ws, ag);
  const selectSession = async (
    id: string,
    ws: string,
    ag: string,
    nextRunTask?: { id: string; title: string } | null,
  ) => {
    setSurface("session"); // selecting a conversation always returns to the conversation view
    if (ag) setAgent(ag);
    if (!gatesWorkspace(ag)) setShowGate(false);
    if (ws && ws !== workspace) {
      setWorkspace(ws); // switch project to the session's folder
      setBranch(null);
    }
    activateSession(id, true, bindRunContext(id, nextRunTask));
    await loadSessionHistory(id);
  };
  const switchAgent = async (name: string) => {
    setSurface("session");
    if (name === agent) return;
    rememberLastSession(agent, sessionId, workspace);
    const knownSessions = sessions.length ? sessions : await getSessions().catch(() => []);
    const knownProjects = projects.length ? projects : await getProjects().catch(() => []);
    const target = resumeTargetForAgent(name, knownSessions);

    setAgent(name);
    // The live workspace is only a valid fallback for a gated persona if it came from
    // another gated persona — a knowledge persona's workspace is a scratch dir, and a
    // code-family session must never adopt one. (`agent` is still the previous persona here.)
    const inheritable = gatesWorkspace(agent) ? workspace : null;

    if (target) {
      // Code falls back to a recent folder; Link resumes its scratch (target.workspace) or
      // starts orphan ("" → server provisions). Chat has no workspace.
      const targetWorkspace = gatesWorkspace(name)
        ? target.workspace || fallbackWorkspace(inheritable, knownProjects)
        : needsWorkspace(name)
          ? target.workspace || ""
          : "";
      if (targetWorkspace && targetWorkspace !== workspace) {
        setWorkspace(targetWorkspace);
        setBranch(null);
      } else if (!targetWorkspace) {
        setWorkspace(null); // orphan link: clear so the next `ready` adopts a fresh scratch
      }
      if (!gatesWorkspace(name)) setShowGate(false);
      else if (targetWorkspace) setShowGate(false);
      else setShowGate(true);
      activateSession(target.sessionId, true);
      await loadSessionHistory(target.sessionId);
      return;
    }

    const id = newId();
    const fallback = gatesWorkspace(name) ? fallbackWorkspace(inheritable, knownProjects) : "";
    if (fallback && fallback !== workspace) {
      setWorkspace(fallback);
      setBranch(null);
    } else if (!fallback && needsWorkspace(name)) {
      setWorkspace(null); // orphan link: server provisions a fresh scratch on connect
    }
    activateSession(id);
    rememberLastSession(name, id, fallback);
    if (!gatesWorkspace(name)) setShowGate(false);
    else setShowGate(!fallback);
  };
  const chooseWorkspace = (path: string, b?: string | null) => {
    setWorkspace(path);
    setBranch(b ?? null);
    setShowGate(false);
    setGateCreate(false);
    activateSession(newId());
    createProject({ workspace_path: path }).then(() => getProjects().then(setProjects)).catch(() => {});
  };
  // "New project" lives under a project-scoped persona's accordion. Switch to that persona, start a
  // fresh session with no folder yet, and open the gate in create mode — so the gate's
  // surface==="session" && gatesWorkspace(agent) guard passes even if the active session was Chat/Link.
  const newProject = (_forAgent?: string) => {
    setShowCreateProject(true);
  };
  const confirmCreateProject = async (name: string, workspacePath: string) => {
    setShowCreateProject(false);
    await createProject({ workspace_path: workspacePath, name }).catch(() => {});
    const updated = await getProjects().catch(() => []);
    if (Array.isArray(updated)) setProjects(updated);
  };
  const newSessionInProject = (projectId: string) => {
    const proj = projects.find((p) => p.project_id === projectId);
    if (!proj) return;
    setSurface("session");
    setWorkspace(proj.workspace_path);
    setBranch(null);
    activateSession(newId());
    setShowGate(false);
    setGateCreate(false);
  };
  const renameConversation = async (id: string, title: string) => {
    const res = await renameSession(id, title);
    if (res.ok) refreshSessions();
  };
  const togglePinned = async (id: string, pinned: boolean) => {
    await setSessionFlags(id, { pinned });
    refreshSessions();
  };
  const toggleArchived = async (id: string, archived: boolean) => {
    await setSessionFlags(id, { archived });
    refreshSessions();
    // Archiving the open chat: leave it and start fresh (it moves to the Archived section).
    if (archived && id === sessionId) {
      activateSession(newId());
    }
  };
  const deleteConversation = async (id: string) => {
    const res = await deleteSession(id);
    if (!res.ok) return;
    refreshSessions();
    if (id === sessionId) {
      activateSession(newId());
    }
  };

  // "Run now": prepare a manual run, open its session, and auto-send the task so the agent
  // runs LIVE in the main view. The backend finalizes history from the durable runtime outcome.
  const openRunSession = (
    sessionId: string,
    ws: string,
    ag: string,
    task?: { id: string; title: string },
  ) => {
    setSurface("session");
    setShowGate(false);
    void selectSession(sessionId, ws, ag, task);
  };
  const runTaskNow = async (taskId: string, title?: string) => {
    const r = await runAutomation(taskId);
    if (!r || !r.ok) return;
    pendingPromptRef.current = bindPendingSessionPrompt(
      pendingPromptRef.current,
      r.session_id,
      r.prompt,
    );
    openRunSession(r.session_id, r.workspace, r.agent, { id: taskId, title: title || "" });
  };

  const idle = items.length === 0 && !streaming;
  const pendingApproval = [...items].reverse().find(
    (i): i is Extract<Item, { kind: "approval" }> => i.kind === "approval" && !i.resolved,
  );
  const pendingDirReq = [...items].reverse().find(
    (i): i is Extract<Item, { kind: "dirreq" }> => i.kind === "dirreq" && !i.resolved,
  );
  const pendingPlan = [...items].reverse().find(
    (i): i is Extract<Item, { kind: "planreq" }> => i.kind === "planreq" && !i.resolved,
  );
  const pendingQuestion = [...items].reverse().find(
    (i): i is Extract<Item, { kind: "question" }> => i.kind === "question" && !i.resolved,
  );
  // Facts subtitle (§22): the session's FIXED facts, not controls — model (+ the
  // workspace folder for project-scoped sessions). Renders only once the session has history;
  // until then the model is still choosable in the composer, so there's no locked fact to state.
  const hasHistory = items.length > 0;
  // Curated labels read "Claude Opus 4.8 · Anthropic" — the provider suffix is dropdown context,
  // noise in a facts line. Fall back to the raw id without its provider prefix.
  const modelDisplay =
    modelLabels[model]?.split(" · ")[0] ||
    (model.includes(":") ? model.split(":").slice(1).join(":") : model);
  // Persona name dropped for this release (owner ask 2026-07-22): personas are hidden,
  // so "Agent" read as noise. The model (+ project folder) are the real fixed facts.
  const subtitleParts = [modelDisplay];
  if (isProjectScoped(personaOf(agent)) && workspace) subtitleParts.push(baseName(workspace));
  const activeInfo = sessions.find((s) => s.session_id === sessionId);
  const activeProject = activeInfo?.project_id
    ? projects.find((p) => p.project_id === activeInfo.project_id)
    : null;
  const activeTitle = activeInfo?.title || tr("New session");

  const desktop = isTauri();
  // Dev-only: `?overlay=1` simulates the desktop overlay layout in the browser (adds the
  // tauri-overlay class + draws fake traffic lights at the real position) so the top-left can be
  // tuned in the preview without a DMG build. Never active in the real app (isTauri() short-circuits).
  const simOverlay = !desktop && new URLSearchParams(window.location.search).has("overlay");
  // Overlay layout is macOS-ONLY: Windows/Linux keep the native title bar, so the mac
  // compensations (traffic-light insets, lowered top strips) must not apply there —
  // they rendered as misalignments under Windows' native bar (caught 2026-07-21).
  const overlay = (desktop && platformOS() === "macos") || simOverlay;
  const beginWindowDrag = (event: PointerEvent) => {
    if (!desktop || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    void startWindowDrag();
  };
  const beginTopStripWindowDrag = (event: PointerEvent) => {
    if (!desktop || !shouldStartWindowDrag(event)) return;
    event.preventDefault();
    void startWindowDrag();
  };

  if (bootError) {
    return (
      <main className="app bg-paper flex items-center justify-center px-6">
        <section className="w-full max-w-[460px] rounded-2xl border border-line bg-panel p-6 shadow-lg">
          <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-accentSoft text-accent">
            <Icon name="logo" size={22} />
          </div>
          <h1 className="text-[20px] font-semibold text-heading">{tr("Smallink service is unavailable")}</h1>
          <p className="mt-2 text-[13px] leading-relaxed text-muted">
            {tr("The local service did not finish starting. Check the error and try again.")}
          </p>
          <div className="mt-4 rounded-lg border border-line bg-paper px-3 py-2 font-mono text-[11px] text-muted break-words">
            {bootError}
          </div>
          <button
            className="mt-5 inline-flex h-9 items-center justify-center rounded-lg bg-accent px-4 text-[13px] font-medium text-white"
            onClick={() => {
              setBooting(true);
              setUiReady(false);
              setShowGate(false);
              setBootAttempt((value) => value + 1);
            }}
          >
            {tr("Try again")}
          </button>
        </section>
      </main>
    );
  }

  if (booting || !uiReady) {
    return (
      <div className={"app boot-splash" + (overlay ? " tauri-overlay" : "")}>
        {/* overlay (not desktop): ?overlay=1 previews the splash's top-left in the browser
            too — the wordmark/traffic-light alignment is exactly what it exists to tune. */}
        {overlay && (
          <div className="titlebar-drag" data-tauri-drag-region>
            <span className="titlebar-brand brand-wordmark">
              <Icon name="logo" size={13} className="mark" /> Smallink<span className="beta-tag">{tr("BETA")}</span>
            </span>
          </div>
        )}
        {simOverlay && (
          <div className="sim-traffic-lights" aria-hidden="true">
            <span /><span /><span />
          </div>
        )}
        {/* The Smallink mark is shared with the app bundle and tray icon. */}
        <div className="boot-mark">
          <Icon name="logo" size={38} />
        </div>
        <div className="boot-text">
          {bootPhase === "service"
            ? t("app.starting")
            : bootPhase === "data"
              ? t("app.loadingData")
              : t("app.restoring")}
          <span className="beta-tag">{tr("BETA")}</span>
        </div>
        <div className="boot-progress" aria-hidden="true"><span /></div>
        <div className="boot-detail">{t(`app.${bootPhase}`)}</div>
        <BootTimeout onRetry={() => {
          setBootError(null);
          setBooting(true);
          setUiReady(false);
          setBootAttempt((v) => v + 1);
        }} />
      </div>
    );
  }

  return (
    <div
      className={
        "app" +
        (overlay ? " tauri-overlay" : "") +
        (navCollapsed ? " nav-collapsed" : "")
      }
      data-phase={lifecycle.phase}
      onPointerDown={beginTopStripWindowDrag}
    >
      {/* Dev-only fake traffic lights so ?overlay=1 previews the real desktop top-left. */}
      {simOverlay && (
        <div className="sim-traffic-lights" aria-hidden="true">
          <span /><span /><span />
        </div>
      )}
      {/* UX-026: automation-start toast — quiet panel, neutral dot/drain, accent only
          on the action (rev 2); auto-dismisses with the 5s drain bar. */}
      {runToast && (
        <div
          className="fixed top-3 right-3 z-[45] w-[290px] bg-panel border border-line rounded-xl shadow-lg px-3.5 pt-3 pb-2.5"
          data-testid="automation-toast"
        >
          <div className="flex items-center gap-2 text-[12.5px] font-semibold">
            <span className="w-[7px] h-[7px] rounded-full bg-faint toast-pulse" />
            {tr("Automation started")}
          </div>
          <div className="text-[12.5px] text-muted mt-0.5 ml-[15px] truncate">
            {tr("{title} · {time} run", { title: runToast.title, time: runToast.time })}
          </div>
          <div className="flex items-center justify-between ml-[15px] mt-1.5">
            <button
              className="text-[12.5px] text-accent font-medium"
              data-testid="toast-view-run"
              onClick={() => {
                selectSession(
                  runToast.sessionId,
                  runToast.workspace,
                  runToast.agent,
                  runTaskOrNull(runToast.taskId, runToast.title),
                );
                setRunToast(null);
              }}
            >
              {tr("View run")} ›
            </button>
            <button
              className="text-[12px] text-faint px-0.5"
              data-testid="toast-dismiss"
              title={tr("Dismiss")}
              aria-label={tr("Dismiss")}
              onClick={() => setRunToast(null)}
            >
              ✕
            </button>
          </div>
          <div className="absolute left-3 right-3 bottom-1 h-[2px] rounded bg-line overflow-hidden">
            <span className="block h-full bg-faint toast-drain" />
          </div>
        </div>
      )}
      {onboarding && (
        <Suspense fallback={null}>
          <Onboarding
            onDone={(next) => {
              setOnboarding(false);
              getHealth().then((h) => setModel(h.model)).catch(() => {});
              loadSettings(); // pick up a model connected during setup (clears the composer chip)
              if (next === "gallery") {
                // The specialists tip: land on Settings ▸ Personas, where the Gallery link lives.
                openSettings("personas");
              } else if (next === "automations") {
                // "Create your first automation" (§29) lands on the Automations quickstart.
                setSurface("scheduled");
              } else if (next === "work") {
                // "Start working" teaches by landing (§24, §32): a fresh session with the rail's
                // Access section expanded. Bump after the session switch settles.
                startNewSession();
                setTimeout(openAccess, 80);
              }
            }}
          />
        </Suspense>
      )}
      {navCollapsed ? (
        <CompactSidebar
          surface={surface}
          onExpand={toggleNav}
          onNewSession={() => startNewSession()}
          onSearch={() => setSearchOpen(true)}
          onGoHome={() => setSurface("session")}
          onOpenApps={() => { setAppViewId(null); setSurface("apps"); }}
          onOpenMemory={() => setSurface("memory")}
          onOpenAgents={() => setSurface("agents")}
          onOpenRuns={() => setSurface("runs")}
          onOpenScheduled={() => setSurface("scheduled")}
          onOpenIntegrations={() => setSurface("integrations")}
          onOpenInbox={() => setSurface("inbox")}
          onOpenAudit={() => setSurface("audit")}
          onOpenSettings={() => openSettings("appearance")}
        />
      ) : (
      <Sidebar
        agent={agent}
        workspace={workspace || ""}
        surfaces={surfaces}
        sessions={sessions}
        projects={projects}
        personas={personas}
        navLayout={sidebarPrefs.navLayout}
        sessionsPeek={sidebarPrefs.sessionsPeek}
        activeSession={sessionId}
        onSwitchAgent={switchAgent}
        onNewSession={startNewSession}
        onSelectSession={selectSession}
        onNewProject={newProject}
        onNewSessionInProject={newSessionInProject}
        onRenameSession={renameConversation}
        onDeleteSession={deleteConversation}
        onArchiveSession={toggleArchived}
        onTogglePin={togglePinned}
        onManage={() => openSettings("appearance")}
        onOpenPersona={(id) => {
          openPersona(id, "session");
        }}
        onManagePersonas={() => openSettings("personas")}
        onOpenScheduled={() => setSurface("scheduled")}
        onOpenRuns={() => setSurface("runs")}
        onOpenAutomation={(id) => {
          setScheduledOpenId(id);
          setSurface("scheduled");
        }}
        onOpenIntegrations={() => setSurface("integrations")}
        onOpenApps={() => { setAppViewId(null); setSurface("apps"); }}
        onOpenMemory={() => setSurface("memory")}
        onOpenAgents={() => setSurface("agents")}
        onOpenAudit={() => setSurface("audit")}
        onOpenInbox={() => setSurface("inbox")}
        onGoHome={() => setSurface("session")}
        onOpenProject={(projectId) => {
          setProjectViewId(projectId);
          setSurface("project");
        }}
        scheduledActive={surface === "scheduled"}
        runsActive={surface === "runs"}
        integrationsActive={surface === "integrations"}
        appsActive={surface === "apps"}
        memoryActive={surface === "memory"}
        agentsActive={surface === "agents"}
        auditActive={surface === "audit"}
        inboxActive={surface === "inbox"}
        onCollapse={toggleNav}
      />
      )}
      <Suspense
        fallback={
          <main className="flex-1 min-w-0 bg-paper p-6">
            <PageState
              icon="diamond"
              title={tr("Loading page…")}
              body={tr("Preparing this Smallink workspace.")}
            />
          </main>
        }
      >
      {surface === "runs" ? (
        <RunsView
          onOpenSession={(id) => {
            const info = sessions.find((item) => item.session_id === id);
            if (info) selectSession(id, info.workspace, info.agent);
          }}
        />
      ) : surface === "agents" ? (
        <AgentsView
          onOpenSession={(id) => {
            const info = sessions.find((item) => item.session_id === id);
            if (info) selectSession(id, info.workspace, info.agent);
          }}
        />
      ) : surface === "scheduled" ? (
        <ScheduledView
          onOpenRun={openRunSession}
          onRunNow={runTaskNow}
          onOpenConnectors={() => setSurface("integrations")}
          initialOpenId={scheduledOpenId}
        />
      ) : surface === "project" && projectViewId ? (
        <ProjectView
          projectId={projectViewId}
          onBack={() => setSurface("session")}
          onNewSession={newSessionInProject}
          onOpenSession={(info) => selectSession(info.session_id, info.workspace, info.agent)}
          onOpenApplication={(appId) => {
            setAppViewId(appId);
            setSurface("apps");
          }}
        />
      ) : surface === "apps" ? (
        <AppsView initialAppId={appViewId} onNewProjectSession={newSessionInProject} />
      ) : surface === "integrations" ? (
        <IntegrationsView
          workspace={workspace || undefined}
          onOpenMemory={() => setSurface("memory")}
          onCreateSkillWithAgent={() => {
            startNewSession("link");
            setTimeout(
              () => prefillComposer(tr("Help me create a new Skill. First ask about the problem it solves, trigger situations, concrete examples, reusable resources, constraints, and expected output. When the information is sufficient, show me a preview and call create_skill only after I confirm.")),
              0,
            );
          }}
        />
      ) : surface === "memory" ? (
        <MemoryView />
      ) : surface === "settings" ? (
        <SettingsView
          key={settingsTab}
          initialTab={settingsTab}
          onOpenPersona={(id) => openPersona(id, "settings")}
        />
      ) : surface === "audit" ? (
        <AuditView />
      ) : surface === "inbox" ? (
        <InboxView onOpenSession={openSessionFromInbox} />
      ) : surface === "persona" ? (
        <PersonaView
          personaId={personaViewId || agent}
          onBack={() =>
            personaViewReturn === "settings" ? openSettings("personas") : setSurface("session")
          }
          onOpenIntegrations={() => setSurface("integrations")}
        />
      ) : (
      <div className={"main" + (surface === "session" && agent !== "chat" && !railHidden ? " rail-open" : "")}>
        <div className="main-topbar">
          <div className="main-topbar-side" onPointerDown={beginWindowDrag}>
            {/* §32: no session-settings row up here anymore — the §23 rest/hover/click glance
                machinery retired with the drawer. "What can this touch" lives permanently on
                the rail's Access section header; the panel toggle is the one entry. */}
          </div>
          {/* Center: title + facts subtitle (§22, amended: the ⋯ menu removed — the nav row's
              hover cluster owns pin/rename/archive/delete). The title stays: with the sidebar
              collapsed it is the only session identifier, and it anchors the subtitle. */}
          <div className="main-title" onPointerDown={beginWindowDrag}>
            <span
              className={"main-title-text" + (activeInfo ? "" : " title-ghost")}
              title={activeTitle}
            >
              {activeTitle}
            </span>
            {/* Plain facts, no affordance: the persona page it used to open is hidden for
                this release (owner ask 2026-07-22). */}
            {hasHistory && (
              <span className="title-sub" data-testid="session-subtitle">
                {activeProject && (
                  <button
                    className="inline-flex items-center gap-1 text-accent hover:underline cursor-pointer mr-1"
                    onClick={() => {
                      setProjectViewId(activeProject.project_id);
                      setSurface("project");
                    }}
                  >
                    <Icon name="folder" size={11} />
                    {activeProject.name}
                    <span className="text-faint">·</span>
                  </button>
                )}
                {subtitleParts.join(" · ")}
              </span>
            )}
          </div>
          {/* Right: session-settings icon (§23) + panel toggle. Model/mode/persona chrome is
              gone — the facts live in the subtitle, the controls in the composer (§22). */}
          <div className="main-topbar-side main-topbar-actions" onPointerDown={beginWindowDrag}>
            {agent === "link" && railHidden && artifactCount > 0 && (
              <button
                className="topbar-artifacts-btn"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => setRailHidden(false)}
                title={tr("Show files this conversation produced")}
              >
                <Icon name="file" size={14} />
                <span>{tr("Artifacts")}</span>
                <span className="topbar-artifacts-count">{artifactCount}</span>
              </button>
            )}
            {/* §32: the panel toggle is the ONE session-panel entry, for every non-chat persona
                (the rail now carries Access, so code-family gets it too). */}
            {agent !== "chat" && (
              <button
                className="topbar-icon-btn"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => setRailHidden((h) => !h)}
                aria-label={tr(railHidden ? "Show side panel" : "Hide side panel")}
                title={tr(railHidden ? "Show side panel" : "Hide side panel")}
              >
                <Icon name="sidebarRight" size={16} />
              </button>
            )}
          </div>
        </div>
        <div className={"main-workspace" + (railHidden ? " rail-hidden" : "")}>
          <div className="main-chat">
            {/* Automation-run context (owner ask 2026-07-04): a __run__ session looked like any
                other chat with no way back to the runs list. Lives INSIDE the chat column (which
                is padded to clear the absolute glass topbar — rendering above .main-workspace put
                it underneath the topbar; owner-reported CSS bug). */}
            {sessionId.startsWith("__run__") && (
              <div
                className="flex items-center gap-2 px-4 py-2 mb-1 rounded-lg text-[12.5px] border border-line bg-accentSoft/40"
                data-testid="run-banner"
              >
                <Icon name="clock" size={14} className="text-accent shrink-0" />
                <span className="truncate text-muted">
                  {tr("Scheduled run")}
                  {activeRunContext?.title ? (
                    <>
                      {" — "}
                      <span className="text-ink font-medium">{activeRunContext.title}</span>
                    </>
                  ) : null}{" "}
                  · {tr("started by an automation")}
                </span>
                <button
                  className="ml-auto shrink-0 text-accent font-medium hover:underline"
                  onClick={() => {
                    if (activeRunContext) setScheduledOpenId(activeRunContext.id);
                    setSurface("scheduled");
                  }}
                >
                  ← {tr("Back to automation")}
                </button>
              </div>
            )}
            <div className="main-scroll" ref={scrollRef} onScroll={handleScroll}>
              {historyLoading ? (
                <ConversationSkeleton />
              ) : idle && !running ? (
                agent === "link" ? (
                  <SessionIntro
                    sessionId={sessionId}
                    onOpenSessionSettings={openAccess}
                    onPrefill={prefillComposer}
                  />
                ) : (
                  <div className="hero">
                    <h1 className="greeting">
                      <span className="mark">✦</span>
                      {tr(agent === "chat" ? "How can I help?" : "Let's build something.")}
                    </h1>
                    {needsWorkspace(agent) && (
                      <div className="suggestions">
                        <div className="suggest-head">{tr("Try a task")}</div>
                        {SUGGESTIONS.map((s, i) => (
                          <div className="suggest" key={i} onClick={() => workspace && send(tr(s.text))}>
                            <span className="ico">{s.ico}</span>
                            {tr(s.text)}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              ) : (
                <>
                  <Transcript
                    items={items}
                    onApprove={approve}
                    running={running}
                    onRetry={retry}
                    // §33 ref #3: sub-threshold streamed text renders INSIDE the live turn
                    // group (header when collapsed, quiet line when expanded) — never as a
                    // floating paragraph.
                    streamingText={streamMode(streaming, items, running) === "quiet" ? streaming : undefined}
                  />
                  {/* Live thinking (reasoning models): a quiet collapsed block that streams the
                      trace for anyone who expands it; folds into the answer's disclosure when
                      the message finalizes. */}
                  {running && reasoningStream && !streaming && (
                    <div className="transcript">
                      <ThinkingBlock text={reasoningStream} live />
                    </div>
                  )}
                  {running &&
                    !reasoningStream &&
                    (!streaming || streamMode(streaming, items, running) === "hold") &&
                    !lastItemIsAssistant(items) && <WaitingForAgent />}
                  <ExecutionProgress items={items} running={running} />
                  {streaming && streamMode(streaming, items, running) === "answer" && (
                    <div className="transcript">
                      <div className="bubble-assistant">
                        <div className="who">Smallink</div>
                        <Markdown text={streaming} />
                        <span className="stream-cursor">▍</span>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Scrolled up while the transcript is still growing → offer the way back down.
                Zero-height strip keeps the pill floating over the scroll area, above the
                composer, without reserving layout space. */}
            {!following && (running || !!streaming) && (
              <div className="relative h-0 z-10">
                <button
                  className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-line bg-panel shadow-md text-[12px] text-muted hover:text-ink cursor-pointer whitespace-nowrap"
                  data-testid="jump-to-latest"
                  onClick={followLatest}
                >
                  <Icon name="chevronDown" size={13} />
                  {tr("Jump to latest")}
                </button>
              </div>
            )}

            <Composer
              mode={mode}
              model={model}
              models={models}
              modelLabels={modelLabels}
              running={running}
              connected={connected}
              modelReady={modelReady}
              onConnectModel={openModelSetup}
              onConfigureVoiceInput={() => openSettings("voice")}
              onSend={send}
              onInterrupt={interrupt}
              onModeChange={changeMode}
              onModelChange={changeModel}
              workspace={needsWorkspace(agent) ? workspace || "" : undefined}
              unattended={unattended}
              onUnattendedChange={agent !== "chat" ? toggleUnattended : undefined}
              prefill={composerPrefill}
              resetKey={sessionId}
              projectName={workspace ? (projects.find((p) => p.workspace_path === workspace)?.name ?? null) : null}
              projectIcon={workspace ? (projects.find((p) => p.workspace_path === workspace)?.icon ?? null) : null}
              placeholder={
                agent === "code"
                  ? tr("Ask the coder to build, fix, or explain…  (drop or paste files)")
                  : agent === "chat"
                    ? tr("Ask anything…  (drop or paste files)")
                    : tr("Ask the agent…  (drop or paste files)")
              }
              approvalSlot={
                // Live inline cards are for ATTENDED sessions only; when Unattended the prompt is
                // parked in the Inbox and surfaced via the answer-in-context card below.
                !unattended && pendingPlan?.kind === "planreq" ? (
                  <PlanCard item={pendingPlan} onRespond={respondPlan} />
                ) : !unattended && pendingDirReq?.kind === "dirreq" ? (
                  <DirectoryRequestCard item={pendingDirReq} onRespond={respondDirectory} />
                ) : !unattended && pendingApproval?.kind === "approval" ? (
                  <ApprovalCard item={pendingApproval} onApprove={approve} runTask={activeRunContext} compact />
                ) : !unattended && pendingQuestion?.kind === "question" ? (
                  // Live ask_user in an attended session — answer inline (reuses the Inbox card UI).
                  <InboxItemCard
                    item={{
                      id: "live-question",
                      session_id: sessionId,
                      kind: "question",
                      title: pendingQuestion.question,
                      body: "",
                      state: "pending",
                      resolution: null,
                      inbox: "default",
                      created_at: "",
                      resolved_at: null,
                      options: pendingQuestion.options,
                      allow_text: pendingQuestion.allow_text,
                      multi: pendingQuestion.multi,
                    }}
                    onResolve={(_id, answer) => answerQuestion(answer)}
                    compact
                  />
                ) : sessionInbox[0] ? (
                  // Unattended session blocked on an Inbox item — answer it in context.
                  <InboxItemCard item={sessionInbox[0]} onResolve={resolveSessionInbox} compact />
                ) : undefined
              }
            />
                  </div>
          <RightRail
            active={surface === "session" && agent !== "chat" && !railHidden}
            sessionId={sessionId}
            refreshKey={browserRefreshKey}
            toolNames={items.filter((i) => i.kind === "tool").map((i: any) => i.name)}
            todo={todo}
            running={running}
            onPreviewChange={onArtifactPreview}
            onArtifactCount={setArtifactCount}
            showArtifacts={agent === "link"}
            personaId={agent}
            projectScoped={isProjectScoped(personaOf(agent))}
            workspace={workspace || undefined}
            branch={branch}
            scratchPrimary={agent === "link"}
            openAccessKey={accessKey}
            onOpenIntegrations={() => setSurface("integrations")}
          />
        </div>
      </div>
      )}
      </Suspense>

      {/* Search from the compact navigation rail. */}
      {searchOpen && (
        <SearchModal
          sessions={sessions}
          personas={personas ?? undefined}
          onSelect={(id, ws, ag) => {
            setSearchOpen(false);
            selectSession(id, ws, ag);
          }}
          onClose={() => setSearchOpen(false)}
        />
      )}

      {showGate && surface === "session" && gatesWorkspace(agent) && (
        <FolderGate
          create={gateCreate}
          onChoose={chooseWorkspace}
          onCancel={
            workspace
              ? () => {
                  setShowGate(false);
                  setGateCreate(false);
                }
              : undefined
          }
        />
      )}
      {workspaceTrustRequest && (
        <WorkspaceTrustPrompt
          request={workspaceTrustRequest}
          onClose={() => setWorkspaceTrustRequest(null)}
        />
      )}
      {showCreateProject && (
        <CreateProjectModal
          onConfirm={confirmCreateProject}
          onCancel={() => setShowCreateProject(false)}
        />
      )}
    </div>
  );
}

function lastItemIsAssistant(items: Item[]): boolean {
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item.kind === "notice") continue;
    return item.kind === "assistant";
  }
  return false;
}

function WaitingForAgent() {
  const { tr } = useI18n();
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const t0 = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="waiting-transcript">
      <div className="waiting-row" aria-live="polite">
        <span className="waiting-spinner" />
        <span>
          {elapsed < 15
            ? tr("Waiting for agent…")
            : elapsed < 45
              ? tr("Still working… ({seconds}s)", { seconds: elapsed })
              : tr("Taking longer than usual… ({seconds}s)", { seconds: elapsed })}
        </span>
      </div>
    </div>
  );
}

function ExecutionProgress({ items, running }: { items: Item[]; running: boolean }) {
  const { tr } = useI18n();
  if (!running) return null;
  const tools = items.filter((it): it is Extract<Item, { kind: "tool" }> => it.kind === "tool");
  const total = tools.length;
  const completed = tools.filter((t) => t.status !== "…").length;
  const activeTool = tools.find((t) => t.status === "…");
  if (total === 0) return null;
  const progress = total > 0 ? Math.round((completed / total) * 100) : 0;
  return (
    <div className="flex items-center gap-2.5 px-4 py-1.5 text-[11.5px] text-muted" data-testid="execution-progress">
      <div className="flex-1 h-1 rounded-full bg-line overflow-hidden">
        <div
          className="h-full bg-accent rounded-full transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>
      <span className="shrink-0 tabular-nums">
        {activeTool
          ? tr("Running {tool} ({done}/{total})", { tool: activeTool.name.replace(/_/g, " "), done: completed, total })
          : tr("{done}/{total} steps", { done: completed, total })}
      </span>
    </div>
  );
}

function resolveLastApproval(items: Item[], decision: ApprovalDecision): Item[] {
  const copy = [...items];
  for (let i = copy.length - 1; i >= 0; i--) {
    const it = copy[i];
    if (it.kind === "approval" && !it.resolved) {
      copy[i] = { ...it, resolved: decision };
      break;
    }
  }
  return copy;
}

function resolveLastDirReq(items: Item[], resolved: "granted" | "denied"): Item[] {
  const copy = [...items];
  for (let i = copy.length - 1; i >= 0; i--) {
    const it = copy[i];
    if (it.kind === "dirreq" && !it.resolved) {
      copy[i] = { ...it, resolved };
      break;
    }
  }
  return copy;
}

function resolveLastPlan(items: Item[], resolved: "approved" | "rejected"): Item[] {
  const copy = [...items];
  for (let i = copy.length - 1; i >= 0; i--) {
    const it = copy[i];
    if (it.kind === "planreq" && !it.resolved) {
      copy[i] = { ...it, resolved };
      break;
    }
  }
  return copy;
}

function resolveLastQuestion(items: Item[], answer: string): Item[] {
  const copy = [...items];
  for (let i = copy.length - 1; i >= 0; i--) {
    const it = copy[i];
    if (it.kind === "question" && !it.resolved) {
      copy[i] = { ...it, resolved: answer };
      break;
    }
  }
  return copy;
}

function BootTimeout({ onRetry }: { onRetry: () => void }) {
  const { tr } = useI18n();
  const [showRetry, setShowRetry] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setShowRetry(true), 15000);
    return () => clearTimeout(id);
  }, []);
  if (!showRetry) return null;
  return (
    <div className="boot-retry mt-4 text-center">
      <p className="text-[12px] text-muted mb-2">{tr("Taking longer than expected…")}</p>
      <button
        className="inline-flex h-8 items-center justify-center rounded-lg border border-line bg-panel px-3 text-[12px] font-medium text-ink hover:border-lineStrong"
        onClick={onRetry}
      >
        {tr("Retry")}
      </button>
    </div>
  );
}
