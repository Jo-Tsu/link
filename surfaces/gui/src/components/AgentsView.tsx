import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type WheelEvent as ReactWheelEvent,
} from "react";
import {
  getAgentCollaborations,
  getPersonas,
  getRuntimeAgentEvents,
  getRuntimeTaskRun,
  type AgentCollaboration,
  type Persona,
  type RuntimeAgentRun,
  type RuntimeRunEvent,
  type RuntimeStatus,
} from "../api";
import { baseName } from "../paths";
import { useI18n, type TranslationKey } from "../i18n";
import { Icon } from "./Icon";
import { PersonaGlyph } from "./personaIcon";

type AgentsTab = "architecture" | "collaborations";

type AgentMember = {
  id: string;
  name: string;
  tagline: string;
  icon: string;
  family: string;
  group: "primary" | "specialist" | "system";
  enabled: boolean;
  builtin: boolean;
  tools: string[];
  workspace: string;
  permission: string;
  relationship: string;
  delegation: string;
  parentId?: string;
};

const EXPLORER: AgentMember = {
  id: "explorer",
  name: "Explorer",
  tagline: "Read-only code research in an isolated context.",
  icon: "search",
  family: "code",
  group: "system",
  enabled: true,
  builtin: true,
  tools: ["grep", "read_file", "list_files", "git_log", "git_status", "git_diff"],
  workspace: "project",
  permission: "Read-only",
  relationship: "Called automatically by Code when broad repository research is useful.",
  delegation: "Cannot delegate another agent.",
  parentId: "code",
};

const RUNTIME_SPECIALISTS: AgentMember[] = [
  {
    id: "researcher",
    name: "Researcher",
    tagline: "Collect cited evidence across project knowledge, files, and the web.",
    icon: "search",
    family: "knowledge",
    group: "system",
    enabled: true,
    builtin: true,
    tools: ["knowledge_search", "web_search", "web_fetch", "grep", "read_file", "list_files"],
    workspace: "project",
    permission: "Read-only",
    relationship: "Started by a workspace agent when a task needs a separate evidence-gathering context.",
    delegation: "Returns one cited report to its parent and cannot delegate another agent.",
    parentId: "link",
  },
  {
    id: "analyst",
    name: "Analyst",
    tagline: "Compare evidence, reveal patterns, and prepare decision-ready synthesis.",
    icon: "chart",
    family: "knowledge",
    group: "system",
    enabled: true,
    builtin: true,
    tools: ["knowledge_search", "web_search", "web_fetch", "grep", "read_file", "list_files"],
    workspace: "project",
    permission: "Read-only",
    relationship: "Started by a workspace agent when evidence needs independent synthesis or tradeoff analysis.",
    delegation: "Returns one analysis report to its parent and cannot delegate another agent.",
    parentId: "link",
  },
  {
    id: "reviewer",
    name: "Reviewer",
    tagline: "Find defects, risks, missing evidence, and validation gaps.",
    icon: "shield",
    family: "knowledge",
    group: "system",
    enabled: true,
    builtin: true,
    tools: ["knowledge_search", "web_search", "web_fetch", "grep", "read_file", "list_files"],
    workspace: "project",
    permission: "Read-only",
    relationship: "Started by a workspace agent for an independent quality and risk review.",
    delegation: "Returns one review report to its parent and cannot delegate another agent.",
    parentId: "link",
  },
];

export function AgentsView({ onOpenSession }: { onOpenSession?: (sessionId: string) => void }) {
  const { tr } = useI18n();
  const [tab, setTab] = useState<AgentsTab>("architecture");
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [collaborations, setCollaborations] = useState<AgentCollaboration[]>([]);
  const [selectedMember, setSelectedMember] = useState<AgentMember | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [run, setRun] = useState<Awaited<ReturnType<typeof getRuntimeTaskRun>> | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [events, setEvents] = useState<RuntimeRunEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextPersonas, nextCollaborations] = await Promise.all([
        getPersonas(),
        getAgentCollaborations(),
      ]);
      setPersonas(nextPersonas);
      setCollaborations(nextCollaborations);
      setSelectedRunId((current) =>
        current && nextCollaborations.some((item) => item.task_run_id === current)
          ? current
          : nextCollaborations[0]?.task_run_id ?? null,
      );
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load agents");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!selectedRunId) {
      setRun(null);
      setSelectedAgentId(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    getRuntimeTaskRun(selectedRunId)
      .then((next) => {
        if (!active) return;
        setRun(next);
        const root = next.agent_runs.find((item) => !item.parent_agent_run_id);
        setSelectedAgentId(root?.agent_run_id ?? next.agent_runs[0]?.agent_run_id ?? null);
      })
      .catch((err) => active && setError(err instanceof Error ? err.message : "Could not load collaboration"))
      .finally(() => active && setDetailLoading(false));
    return () => { active = false; };
  }, [selectedRunId]);

  useEffect(() => {
    if (!selectedAgentId) {
      setEvents([]);
      return;
    }
    let active = true;
    getRuntimeAgentEvents(selectedAgentId)
      .then((next) => active && setEvents(next))
      .catch(() => active && setEvents([]));
    return () => { active = false; };
  }, [selectedAgentId]);

  const members = useMemo<AgentMember[]>(() => {
    const personaMembers = personas.map(personaToMember);
    const codeEnabled = personaMembers.some((member) => member.id === "code" && member.enabled);
    const workspaceAgentEnabled = personaMembers.some(
      (member) => member.enabled && member.workspace !== "none",
    );
    return [
      ...personaMembers,
      { ...EXPLORER, enabled: codeEnabled },
      ...RUNTIME_SPECIALISTS.map((member) => ({ ...member, enabled: workspaceAgentEnabled })),
    ];
  }, [personas]);
  const selectedCollaboration = collaborations.find((item) => item.task_run_id === selectedRunId) ?? null;
  const selectedAgent = run?.agent_runs.find((item) => item.agent_run_id === selectedAgentId) ?? null;

  return (
    <main className="flex-1 min-w-0 min-h-0 overflow-y-auto hairline-scroll bg-paper" data-testid="agents-view">
      <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6">
        <div className="flex items-start justify-between gap-4 mb-5">
          <div>
            <h1 className="text-[24px] font-semibold text-heading">{tr("Agents")}</h1>
            <p className="text-[12.5px] text-muted mt-0.5">
              {tr("See who can work, and how agents collaborated on real tasks.")}
            </p>
          </div>
          <button
            className="w-8 h-8 grid place-items-center rounded-lg border border-line bg-panel hover:border-lineStrong"
            onClick={() => void load()}
            title={tr("Refresh")}
            aria-label={tr("Refresh")}
          >
            <Icon name="refresh" size={15} />
          </button>
        </div>

        <div className="inline-flex items-center gap-1 rounded-lg border border-line bg-panel p-1 mb-5" role="tablist">
          <TabButton active={tab === "architecture"} onClick={() => setTab("architecture")}>
            {tr("Agent architecture")} <Count value={members.length} />
          </TabButton>
          <TabButton active={tab === "collaborations"} onClick={() => setTab("collaborations")}>
            {tr("Collaboration history")} <Count value={collaborations.length} />
          </TabButton>
        </div>

        {error && (
          <div role="alert" className="mb-4 rounded-lg border border-danger/30 bg-dangerSoft px-3 py-2.5 text-[12px] text-danger">
            {tr(error)}
          </div>
        )}

        {tab === "architecture" ? (
          <AgentArchitecturePanel members={members} loading={loading} onSelect={setSelectedMember} />
        ) : (
          <CollaborationsPanel
            collaborations={collaborations}
            selected={selectedCollaboration}
            selectedRunId={selectedRunId}
            onSelectRun={setSelectedRunId}
            run={run}
            detailLoading={detailLoading}
            selectedAgent={selectedAgent}
            selectedAgentId={selectedAgentId}
            onSelectAgent={setSelectedAgentId}
            events={events}
            onOpenSession={onOpenSession}
          />
        )}
      </div>

      {selectedMember && (
        <MemberDialog member={selectedMember} onClose={() => setSelectedMember(null)} />
      )}
    </main>
  );
}

const ARCHITECTURE_NODE_WIDTH = 190;
const ARCHITECTURE_NODE_HEIGHT = 122;
const ARCHITECTURE_MIN_ZOOM = 0.3;
const ARCHITECTURE_MAX_ZOOM = 1.2;

type ArchitecturePosition = {
  member: AgentMember;
  x: number;
  y: number;
};

function AgentArchitecturePanel({
  members,
  loading,
  onSelect,
}: {
  members: AgentMember[];
  loading: boolean;
  onSelect: (member: AgentMember) => void;
}) {
  const { tr } = useI18n();
  const [zoom, setZoom] = useState(1);
  const [panning, setPanning] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  const panRef = useRef<{
    pointerId: number;
    clientX: number;
    clientY: number;
    scrollLeft: number;
    scrollTop: number;
  } | null>(null);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!loading && viewport) {
      viewport.scrollLeft = Math.max(0, (viewport.scrollWidth - viewport.clientWidth) / 2);
    }
  }, [loading, members.length]);

  if (loading) return <div className="py-10 text-[12.5px] text-muted">{tr("Loading agents…")}</div>;

  const selectable = members.filter((member) => member.group !== "system");
  const systemMembers = members.filter((member) => member.group === "system");
  const rowWidth = selectable.length * ARCHITECTURE_NODE_WIDTH + Math.max(0, selectable.length - 1) * 54;
  const canvasWidth = Math.max(1080, rowWidth + 160);
  const canvasHeight = systemMembers.length ? 740 : 570;
  const centerX = canvasWidth / 2;
  const selectableStartX = (canvasWidth - rowWidth) / 2;
  const selectableNodes: ArchitecturePosition[] = selectable.map((member, index) => ({
    member,
    x: selectableStartX + index * (ARCHITECTURE_NODE_WIDTH + 54),
    y: 356,
  }));
  const firstSelectableCenter = selectableNodes.length
    ? selectableNodes[0].x + ARCHITECTURE_NODE_WIDTH / 2
    : centerX;
  const lastSelectableCenter = selectableNodes.length
    ? selectableNodes[selectableNodes.length - 1].x + ARCHITECTURE_NODE_WIDTH / 2
    : centerX;
  const codeNode = selectableNodes.find((node) => node.member.id === "code");
  const systemRowWidth = systemMembers.length * ARCHITECTURE_NODE_WIDTH + Math.max(0, systemMembers.length - 1) * 54;
  const systemStartX = codeNode && systemMembers.length === 1
    ? codeNode.x
    : (canvasWidth - systemRowWidth) / 2;
  const systemNodes: ArchitecturePosition[] = systemMembers.map((member, index) => ({
    member,
    x: systemStartX + index * (ARCHITECTURE_NODE_WIDTH + 54),
    y: 574,
  }));
  const stageStyle = {
    width: `${canvasWidth}px`,
    height: `${canvasHeight}px`,
    transform: `scale(${zoom})`,
  } satisfies CSSProperties;
  const scaledStageStyle = {
    width: `${canvasWidth * zoom}px`,
    height: `${canvasHeight * zoom}px`,
  } satisfies CSSProperties;

  const boundedZoom = (next: number) => Math.min(
    ARCHITECTURE_MAX_ZOOM,
    Math.max(ARCHITECTURE_MIN_ZOOM, Number(next.toFixed(2))),
  );
  const applyZoom = (next: number) => {
    const viewport = viewportRef.current;
    const bounded = boundedZoom(next);
    if (!viewport || bounded === zoom) return;
    const anchorX = (viewport.scrollLeft + viewport.clientWidth / 2) / zoom;
    const anchorY = (viewport.scrollTop + viewport.clientHeight / 2) / zoom;
    setZoom(bounded);
    window.requestAnimationFrame(() => {
      viewport.scrollLeft = Math.max(0, anchorX * bounded - viewport.clientWidth / 2);
      viewport.scrollTop = Math.max(0, anchorY * bounded - viewport.clientHeight / 2);
    });
  };
  const fitCanvas = () => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const fitted = boundedZoom(Math.min(
      (viewport.clientWidth - 32) / canvasWidth,
      (viewport.clientHeight - 32) / canvasHeight,
    ));
    setZoom(fitted);
    window.requestAnimationFrame(() => {
      viewport.scrollLeft = Math.max(0, (canvasWidth * fitted - viewport.clientWidth) / 2);
      viewport.scrollTop = Math.max(0, (canvasHeight * fitted - viewport.clientHeight) / 2);
    });
  };
  const startPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || (event.target as Element).closest("button")) return;
    const viewport = event.currentTarget;
    panRef.current = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
    };
    viewport.setPointerCapture(event.pointerId);
    setPanning(true);
  };
  const movePan = (event: ReactPointerEvent<HTMLDivElement>) => {
    const pan = panRef.current;
    if (!pan || pan.pointerId !== event.pointerId) return;
    event.currentTarget.scrollLeft = pan.scrollLeft - (event.clientX - pan.clientX);
    event.currentTarget.scrollTop = pan.scrollTop - (event.clientY - pan.clientY);
  };
  const endPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (panRef.current?.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    panRef.current = null;
    setPanning(false);
  };
  const zoomWithWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    if (!event.metaKey && !event.ctrlKey) return;
    event.preventDefault();
    applyZoom(zoom + (event.deltaY < 0 ? 0.1 : -0.1));
  };

  return (
    <section className="agent-architecture-shell rounded-lg border border-line bg-panel overflow-hidden" aria-label={tr("Smallink multi-agent architecture")}>
      <div className="agent-architecture-header">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-[14px] font-semibold text-heading">{tr("Smallink multi-agent architecture")}</h2>
            <span className="agent-architecture-count">{tr("{count} agents", { count: members.length })}</span>
          </div>
          <p className="text-[11px] text-muted mt-0.5">
            {tr("This diagram shows available roles and supported delegation paths, not a fabricated run history.")}
          </p>
        </div>
        <div className="agent-architecture-controls" aria-label={tr("Canvas controls")}>
          <button onClick={() => applyZoom(zoom - 0.1)} aria-label={tr("Zoom out")} title={tr("Zoom out")} disabled={zoom <= ARCHITECTURE_MIN_ZOOM}>
            <Icon name="minus" size={14} />
          </button>
          <button className="agent-zoom-value" onClick={() => applyZoom(1)} aria-label={tr("Reset zoom")} title={tr("Reset zoom")}>
            {Math.round(zoom * 100)}%
          </button>
          <button onClick={() => applyZoom(zoom + 0.1)} aria-label={tr("Zoom in")} title={tr("Zoom in")} disabled={zoom >= ARCHITECTURE_MAX_ZOOM}>
            <Icon name="plus" size={14} />
          </button>
          <button onClick={fitCanvas} aria-label={tr("Fit canvas")} title={tr("Fit canvas")}>
            <Icon name="maximize" size={13} />
          </button>
        </div>
      </div>
      <div className="agent-architecture-legend" aria-label={tr("Relationship legend")}>
        <span><i className="agent-legend-line route" />{tr("Selectable role")}</span>
        <span><i className="agent-legend-line delegation" />{tr("Runtime delegation")}</span>
        <span><i className="agent-legend-node disabled" />{tr("Disabled role")}</span>
      </div>
      <div
        className={`agent-architecture-viewport hairline-scroll ${panning ? "is-panning" : ""}`}
        ref={viewportRef}
        onPointerDown={startPan}
        onPointerMove={movePan}
        onPointerUp={endPan}
        onPointerCancel={endPan}
        onWheel={zoomWithWheel}
      >
        <div className="agent-architecture-stage-size" style={scaledStageStyle}>
          <div className="agent-architecture-stage" style={stageStyle}>
            <svg className="agent-architecture-lines" width={canvasWidth} height={canvasHeight} aria-hidden="true">
              <defs>
                <marker id="agent-route-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 8 4 L 0 8 z" className="agent-route-arrow" />
                </marker>
                <marker id="agent-delegation-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 8 4 L 0 8 z" className="agent-delegation-arrow" />
                </marker>
              </defs>
              <path className="agent-architecture-edge route" d={`M ${centerX} 122 V 178`} markerEnd="url(#agent-route-arrow)" />
              <path className="agent-architecture-edge route" d={`M ${centerX} 300 V 326 M ${firstSelectableCenter} 326 H ${lastSelectableCenter}`} />
              {selectableNodes.map((node) => (
                <path
                  key={`route-${node.member.id}`}
                  className={`agent-architecture-edge route ${node.member.enabled ? "" : "muted"}`}
                  d={`M ${node.x + ARCHITECTURE_NODE_WIDTH / 2} 326 V ${node.y}`}
                  markerEnd="url(#agent-route-arrow)"
                />
              ))}
              {systemNodes.map((node) => {
                const parent = selectableNodes.find(
                  (candidate) => candidate.member.id === node.member.parentId,
                );
                const startX = parent ? parent.x + ARCHITECTURE_NODE_WIDTH / 2 : centerX;
                const startY = parent ? parent.y + ARCHITECTURE_NODE_HEIGHT : 300;
                return (
                  <path
                    key={`delegate-${node.member.id}`}
                    className={`agent-architecture-edge delegation ${node.member.enabled ? "" : "muted"}`}
                    d={`M ${startX} ${startY} V ${node.y - 24} H ${node.x + ARCHITECTURE_NODE_WIDTH / 2} V ${node.y}`}
                    markerEnd="url(#agent-delegation-arrow)"
                  />
                );
              })}
              <text className="agent-architecture-edge-label" x={centerX + 12} y={153}>{tr("submit")}</text>
              <text className="agent-architecture-edge-label" x={centerX + 12} y={320}>{tr("select role")}</text>
              {systemNodes.length > 0 && (
                <text className="agent-architecture-edge-label delegation" x={centerX + 12} y={532}>{tr("delegate")}</text>
              )}
            </svg>

            <ArchitectureStaticNode
              className="user"
              x={centerX - 90}
              y={24}
              icon="chat"
              title={tr("User task")}
              subtitle={tr("Goal, context and constraints")}
            />
            <ArchitectureStaticNode
              className="runtime"
              x={centerX - 112}
              y={178}
              icon="logo"
              title="Smallink Agent Runtime"
              subtitle={tr("Session, model, tools, policy and execution")}
            />
            {selectableNodes.map((node) => (
              <ArchitectureAgentNode key={node.member.id} {...node} onSelect={onSelect} />
            ))}
            {systemNodes.map((node) => (
              <ArchitectureAgentNode key={node.member.id} {...node} onSelect={onSelect} delegated />
            ))}
          </div>
        </div>
      </div>
      <div className="agent-architecture-footer">
        <Icon name="branch" size={13} />
        <span>{tr("Solid lines show a role the runtime can start. Dashed lines show supported agent-to-agent delegation.")}</span>
      </div>
    </section>
  );
}

function ArchitectureStaticNode({
  className,
  x,
  y,
  icon,
  title,
  subtitle,
}: {
  className: string;
  x: number;
  y: number;
  icon: "chat" | "logo";
  title: string;
  subtitle: string;
}) {
  return (
    <div className={`agent-architecture-node static ${className}`} style={{ left: x, top: y }}>
      <span className="agent-architecture-avatar"><Icon name={icon} size={19} /></span>
      <strong>{title}</strong>
      <span>{subtitle}</span>
    </div>
  );
}

function ArchitectureAgentNode({
  member,
  x,
  y,
  onSelect,
  delegated = false,
}: ArchitecturePosition & {
  onSelect: (member: AgentMember) => void;
  delegated?: boolean;
}) {
  const { tr } = useI18n();
  return (
    <button
      className={`agent-architecture-node agent ${member.enabled ? "enabled" : "disabled"} ${delegated ? "delegated" : ""}`}
      style={{ left: x, top: y }}
      onClick={() => onSelect(member)}
      aria-label={tr("Open {name} details", { name: tr(member.name) })}
    >
      <span className="agent-architecture-avatar">
        <PersonaGlyph icon={member.icon} family={member.family} size={18} />
        <i className={member.enabled ? "online" : "offline"} />
      </span>
      <strong>{tr(member.name)}</strong>
      <span className="agent-architecture-role">
        {tr(groupLabel(member.group))} · {member.enabled ? tr("Enabled") : tr("Disabled")}
      </span>
      <span className="agent-architecture-summary">{tr(member.tagline)}</span>
      <span className="agent-architecture-node-action">{tr("View details")} <Icon name="chevronRight" size={11} /></span>
    </button>
  );
}

function CollaborationsPanel({
  collaborations,
  selected,
  selectedRunId,
  onSelectRun,
  run,
  detailLoading,
  selectedAgent,
  selectedAgentId,
  onSelectAgent,
  events,
  onOpenSession,
}: {
  collaborations: AgentCollaboration[];
  selected: AgentCollaboration | null;
  selectedRunId: string | null;
  onSelectRun: (id: string) => void;
  run: Awaited<ReturnType<typeof getRuntimeTaskRun>> | null;
  detailLoading: boolean;
  selectedAgent: RuntimeAgentRun | null;
  selectedAgentId: string | null;
  onSelectAgent: (id: string) => void;
  events: RuntimeRunEvent[];
  onOpenSession?: (sessionId: string) => void;
}) {
  const { t, tr } = useI18n();
  if (!collaborations.length) {
    return (
      <div className="rounded-lg border border-line bg-panel px-6 py-12 text-center">
        <span className="w-11 h-11 rounded-full grid place-items-center bg-accentSoft text-accent mx-auto">
          <Icon name="branch" size={20} />
        </span>
        <h2 className="text-[15px] font-semibold text-heading mt-4">{tr("No multi-agent collaboration yet")}</h2>
        <p className="text-[12px] leading-relaxed text-muted mt-1 max-w-md mx-auto">
          {tr("When a workspace agent delegates research, analysis, or review, the real collaboration will appear here.")}
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 min-[1080px]:grid-cols-[300px_minmax(0,1fr)] gap-4 items-start">
      <section className="rounded-lg border border-line bg-panel overflow-hidden min-[1080px]:sticky min-[1080px]:top-6">
        <div className="px-4 py-3 border-b border-line">
          <h2 className="text-[13px] font-semibold text-ink">{tr("Real collaboration runs")}</h2>
          <p className="text-[10.5px] text-muted mt-0.5">{tr("Only runs with delegated child agents are listed.")}</p>
        </div>
        <div className="max-h-[calc(100vh-250px)] overflow-y-auto hairline-scroll">
          {collaborations.map((item) => (
            <button
              key={item.task_run_id}
              className={`w-full text-left px-4 py-3 border-b border-line last:border-b-0 hover:bg-paper/70 ${selectedRunId === item.task_run_id ? "bg-accentSoft/30" : ""}`}
              onClick={() => onSelectRun(item.task_run_id)}
            >
              <div className="flex items-start gap-2">
                <StatusDot status={item.status} />
                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px] font-medium text-ink line-clamp-2">{item.title}</div>
                  <div className="text-[10.5px] text-muted mt-1">
                    {item.project_id ? baseName(item.project_id) : tr("No project")} · {formatTime(item.started_at)}
                  </div>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {item.agent_roles.map((role) => <AgentChip key={role}>{tr(roleName(role))}</AgentChip>)}
                    <AgentChip>{tr("{count} delegations", { count: item.child_agent_count })}</AgentChip>
                  </div>
                </div>
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="min-w-0">
        {detailLoading ? (
          <div className="rounded-lg border border-line bg-panel px-5 py-12 text-[12px] text-muted">{tr("Loading collaboration…")}</div>
        ) : selected && run ? (
          <>
            <div className="flex items-start justify-between gap-4 mb-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h2 className="text-[20px] font-semibold text-heading">{selected.title}</h2>
                  <StatusBadge status={selected.status} label={t(statusKey(selected.status))} />
                </div>
                <p className="text-[11.5px] text-muted mt-1">
                  {tr("{agents} agents · {delegations} delegations · {duration}", {
                    agents: selected.agent_count,
                    delegations: selected.child_agent_count,
                    duration: formatDuration(selected.started_at, selected.finished_at, tr),
                  })}
                </p>
              </div>
              <button
                className="shrink-0 text-[12px] text-accent hover:underline disabled:text-faint"
                disabled={!onOpenSession}
                onClick={() => onOpenSession?.(selected.session_id)}
              >
                {tr("Open conversation")}
              </button>
            </div>

            <div className="rounded-lg border border-line bg-panel overflow-hidden mb-4">
              <div className="px-4 py-3 border-b border-line flex items-center justify-between gap-3">
                <div>
                  <h3 className="text-[13px] font-semibold text-ink">{tr("Collaboration graph")}</h3>
                  <p className="text-[10.5px] text-muted mt-0.5">{tr("Select an agent to inspect its assigned work and result.")}</p>
                </div>
                <span className="text-[10.5px] text-faint">{tr("Root → delegated child")}</span>
              </div>
              <div className="agent-graph-canvas overflow-auto hairline-scroll">
                <div className="agent-tree">
                  {rootRuns(run.agent_runs).map((root) => (
                    <AgentTreeNode
                      key={root.agent_run_id}
                      node={root}
                      runs={run.agent_runs}
                      selectedId={selectedAgentId}
                      onSelect={onSelectAgent}
                    />
                  ))}
                </div>
              </div>
            </div>

            {selectedAgent && (
              <AgentRunDetail run={selectedAgent} events={events} />
            )}
          </>
        ) : null}
      </section>
    </div>
  );
}

function AgentTreeNode({
  node,
  runs,
  selectedId,
  onSelect,
}: {
  node: RuntimeAgentRun;
  runs: RuntimeAgentRun[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { t, tr } = useI18n();
  const children = runs.filter((item) => item.parent_agent_run_id === node.agent_run_id);
  return (
    <div className="agent-tree-branch">
      <button
        className={`agent-run-node rounded-lg border bg-panel text-left ${selectedId === node.agent_run_id ? "selected" : "border-line"}`}
        onClick={() => onSelect(node.agent_run_id)}
        aria-label={tr("Inspect {name} run", { name: tr(roleName(node.agent_role)) })}
      >
        <div className="flex items-start gap-2.5">
          <span className="w-8 h-8 rounded-full grid place-items-center bg-accentSoft text-accent shrink-0">
            <PersonaGlyph icon={roleIcon(node.agent_role)} family={node.agent_role === "explorer" ? "code" : "knowledge"} size={15} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-semibold text-heading truncate">{tr(roleName(node.agent_role))}</div>
            <div className="text-[10.5px] text-muted mt-0.5">
              {node.parent_agent_run_id ? tr("Delegated child") : tr("Root agent")}
            </div>
          </div>
          <StatusDot status={node.status} />
        </div>
        <div className="text-[10.5px] text-muted mt-3 truncate">{node.model || tr("Default model")}</div>
        <div className="flex items-center justify-between gap-2 mt-2 text-[10.5px]">
          <span className="text-faint">{formatDuration(node.started_at, node.finished_at, tr)}</span>
          <span className="text-muted">{t(statusKey(node.status))}</span>
        </div>
      </button>
      {children.length > 0 && (
        <>
          <div className="agent-tree-link"><span>{tr("delegated")}</span></div>
          <div className="agent-tree-children">
            {children.map((child) => (
              <div className="agent-tree-child" key={child.agent_run_id}>
                <AgentTreeNode
                  node={child}
                  runs={runs}
                  selectedId={selectedId}
                  onSelect={onSelect}
                />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function AgentRunDetail({ run, events }: { run: RuntimeAgentRun; events: RuntimeRunEvent[] }) {
  const { t, tr } = useI18n();
  return (
    <section className="rounded-lg border border-line bg-panel overflow-hidden">
      <div className="px-4 py-3 border-b border-line flex items-center justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-semibold text-ink">{tr(roleName(run.agent_role))}</h3>
          <p className="text-[10.5px] text-muted mt-0.5">
            {run.parent_agent_run_id
              ? tr("This sub-agent received a bounded task from its parent agent.")
              : tr("This root agent received the user task and owns the final result.")}
          </p>
        </div>
        <StatusBadge status={run.status} label={t(statusKey(run.status))} />
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-px bg-line">
        <ValuePanel label={tr("Assigned input")} value={run.input} />
        <ValuePanel label={tr("Returned result")} value={run.output} error={run.error} />
      </div>
      <div className="border-t border-line">
        <div className="px-4 py-2.5 text-[11px] font-semibold text-ink">{tr("Execution events")}</div>
        {events.length === 0 ? (
          <div className="px-4 pb-4 text-[11.5px] text-muted">{tr("No events recorded.")}</div>
        ) : (
          <div className="border-t border-line">
            {events.map((event) => (
              <details key={event.event_id} className="group border-b border-line last:border-b-0">
                <summary className="list-none cursor-pointer min-h-[40px] flex items-center gap-2 px-4 py-2 hover:bg-paper/70">
                  <Icon name="chevronRight" size={12} className="text-faint group-open:rotate-90 transition-transform" />
                  <span className="text-[11px] font-mono text-ink">{event.event_type}</span>
                  <span className="text-[10.5px] text-muted truncate flex-1">{eventSummary(event)}</span>
                  <span className="text-[10px] text-faint shrink-0">{formatClock(event.created_at)}</span>
                </summary>
                <pre className="m-0 px-8 pb-3 whitespace-pre-wrap break-words text-[10.5px] leading-relaxed text-muted font-mono">
                  {formatValue(event.data)}
                </pre>
              </details>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function MemberDialog({ member, onClose }: { member: AgentMember; onClose: () => void }) {
  const { tr } = useI18n();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[80] bg-[var(--scrim)] grid place-items-center p-5" role="dialog" aria-modal="true" aria-label={tr("Agent details")} onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="w-full max-w-[620px] max-h-[min(720px,90vh)] overflow-y-auto hairline-scroll rounded-[16px] border border-line bg-panel shadow-2xl">
        <div className="px-5 py-4 border-b border-line flex items-start gap-3">
          <span className="w-10 h-10 rounded-full grid place-items-center bg-accentSoft text-accent shrink-0">
            <PersonaGlyph icon={member.icon} family={member.family} size={19} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="text-[18px] font-semibold text-heading">{tr(member.name)}</h2>
              <span className={`text-[10.5px] px-2 py-0.5 rounded-full ${member.enabled ? "bg-okSoft text-ok" : "bg-paper text-muted"}`}>
                {member.enabled ? tr("Enabled") : tr("Disabled")}
              </span>
            </div>
            <p className="text-[12px] text-muted mt-0.5">{tr(member.tagline)}</p>
          </div>
          <button className="w-8 h-8 grid place-items-center rounded-lg text-muted hover:bg-paper hover:text-ink" onClick={onClose} aria-label={tr("Close")}>
            <Icon name="x" size={16} />
          </button>
        </div>
        <dl className="grid grid-cols-[132px_minmax(0,1fr)] gap-x-4 gap-y-3 px-5 py-5 text-[12px]">
          <dt className="text-faint">{tr("Agent type")}</dt><dd className="text-ink">{tr(groupLabel(member.group))}</dd>
          <dt className="text-faint">{tr("Relationship")}</dt><dd className="text-ink leading-relaxed">{tr(member.relationship)}</dd>
          <dt className="text-faint">{tr("Permission scope")}</dt><dd className="text-ink">{tr(member.permission)}</dd>
          <dt className="text-faint">{tr("Workspace scope")}</dt><dd className="text-ink">{tr(workspaceLabel(member.workspace))}</dd>
          <dt className="text-faint">{tr("Delegation")}</dt><dd className="text-ink leading-relaxed">{tr(member.delegation)}</dd>
          <dt className="text-faint">{tr("Source")}</dt><dd className="text-ink">{member.builtin ? tr("Built in") : tr("Installed package")}</dd>
        </dl>
        <div className="px-5 py-4 border-t border-line">
          <div className="text-[11px] font-semibold text-ink mb-2">{tr("Available tools")}</div>
          {member.tools.length ? (
            <div className="flex flex-wrap gap-1.5">{member.tools.map((tool) => <AgentChip key={tool}>{tool}</AgentChip>)}</div>
          ) : (
            <div className="text-[11.5px] text-muted">{tr("No tools declared.")}</div>
          )}
        </div>
      </section>
    </div>
  );
}

function ValuePanel({ label, value, error }: { label: string; value: unknown; error?: string | null }) {
  const { tr } = useI18n();
  return (
    <div className="bg-panel px-4 py-3 min-w-0">
      <div className="text-[10.5px] uppercase font-semibold text-faint mb-2">{label}</div>
      {error && <div className="text-[11px] text-danger mb-2">{error}</div>}
      <pre className="m-0 whitespace-pre-wrap break-words text-[11px] leading-relaxed text-muted font-mono max-h-[260px] overflow-auto hairline-scroll">
        {formatValue(value) || tr("No data recorded.")}
      </pre>
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return <button role="tab" aria-selected={active} className={`h-8 px-3 rounded-md text-[12px] flex items-center gap-2 ${active ? "bg-accentSoft text-heading font-medium" : "text-muted hover:bg-paper hover:text-ink"}`} onClick={onClick}>{children}</button>;
}

function Count({ value }: { value: number }) {
  return <span className="min-w-5 h-5 px-1.5 rounded-full bg-panel/80 text-[10.5px] grid place-items-center text-muted">{value}</span>;
}

function AgentChip({ children }: { children: ReactNode }) {
  return <span className="inline-flex items-center h-5 rounded-full border border-line bg-paper/70 px-2 text-[10px] text-muted">{children}</span>;
}

function StatusDot({ status }: { status: RuntimeStatus }) {
  const color = status === "completed" ? "bg-ok" : status === "failed" ? "bg-danger" : status === "running" ? "bg-accent animate-pulse" : status === "waiting_approval" ? "bg-warnInk" : "bg-faint";
  return <span className={`w-2 h-2 rounded-full shrink-0 mt-1 ${color}`} />;
}

function StatusBadge({ status, label }: { status: RuntimeStatus; label: string }) {
  const color = status === "completed" ? "bg-okSoft text-ok" : status === "failed" ? "bg-dangerSoft text-danger" : status === "waiting_approval" ? "bg-warnSoft text-warnInk" : status === "running" ? "bg-accentSoft text-accent" : "bg-paper text-muted";
  return <span className={`text-[10.5px] px-2 py-1 rounded-full shrink-0 ${color}`}>{label}</span>;
}

function personaToMember(persona: Persona): AgentMember {
  const primary = persona.id === "link" || persona.id === "code";
  return {
    id: persona.id,
    name: persona.id === "link" ? "Smallink" : persona.name,
    tagline: persona.tagline,
    icon: persona.icon,
    family: persona.family,
    group: primary ? "primary" : "specialist",
    enabled: persona.enabled,
    builtin: persona.builtin,
    tools: persona.tools,
    workspace: persona.workspace,
    permission: "Controlled by the current session mode",
    relationship: primary
      ? "Receives a user task directly and owns its final answer."
      : "Runs as an independent specialist selected by the user.",
    delegation: persona.id === "code"
      ? "Can delegate repository exploration, research, analysis, and review."
      : persona.workspace !== "none"
        ? "Can delegate read-only research, analysis, and review."
        : "This role does not own a workspace, so specialist delegation is unavailable.",
  };
}

function groupLabel(group: AgentMember["group"]): string {
  return group === "primary" ? "Primary agent" : group === "system" ? "System sub-agent" : "Specialist agent";
}

function workspaceLabel(workspace: string): string {
  if (workspace === "none") return "No workspace required";
  if (workspace === "project") return "Project workspace";
  if (workspace === "git") return "Git repository";
  if (workspace === "deliverable") return "Deliverable workspace";
  return workspace || "Current workspace";
}

function roleName(role: string): string {
  if (role === "link") return "Smallink";
  if (role === "code") return "Code";
  if (role === "explorer") return "Explorer";
  if (role === "researcher") return "Researcher";
  if (role === "analyst") return "Analyst";
  if (role === "reviewer") return "Reviewer";
  return role ? role.charAt(0).toUpperCase() + role.slice(1) : "Agent";
}

function roleIcon(role: string): string {
  if (role === "explorer" || role === "researcher") return "search";
  if (role === "analyst") return "chart";
  if (role === "reviewer") return "shield";
  return role;
}

function rootRuns(runs: RuntimeAgentRun[]): RuntimeAgentRun[] {
  const ids = new Set(runs.map((item) => item.agent_run_id));
  return runs.filter((item) => !item.parent_agent_run_id || !ids.has(item.parent_agent_run_id));
}

function statusKey(status: RuntimeStatus): TranslationKey {
  return `status.${status}` as TranslationKey;
}

function formatValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function eventSummary(event: RuntimeRunEvent): string {
  const data = event.data ?? {};
  return String(data.name ?? data.tool ?? data.status ?? data.error ?? data.text ?? data.input ?? "").replace(/\s+/g, " ").slice(0, 100);
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatClock(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDuration(
  startValue: string,
  endValue: string | null,
  tr: (text: string) => string,
): string {
  if (!endValue) return tr("in progress");
  const start = new Date(startValue).getTime();
  const end = new Date(endValue).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return tr("finished");
  const ms = Math.max(0, end - start);
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.floor((ms % 60_000) / 1000)}s`;
}
