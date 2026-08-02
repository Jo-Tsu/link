import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getRuntimeAgentEvents,
  getRuntimeTask,
  getRuntimeTaskRun,
  getRuntimeTasks,
  type RuntimeAgentRun,
  type RuntimeRunEvent,
  type RuntimeStatus,
  type RuntimeTask,
  type RuntimeTaskDetail,
  type RuntimeTaskRunDetail,
} from "../api";
import { baseName } from "../paths";
import { useI18n, type TranslationKey } from "../i18n";
import { Icon } from "./Icon";
import { PanelHead } from "./IntegrationsView";

const ACTIVE = new Set<RuntimeStatus>(["running", "waiting_approval"]);

export function RunsView({
  onOpenSession,
}: {
  onOpenSession?: (sessionId: string) => void;
}) {
  const { t } = useI18n();
  const [tasks, setTasks] = useState<RuntimeTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [task, setTask] = useState<RuntimeTaskDetail | null>(null);
  const [run, setRun] = useState<RuntimeTaskRunDetail | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [events, setEvents] = useState<RuntimeRunEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadTasks = useCallback(async () => {
    try {
      const next = await getRuntimeTasks();
      setTasks(next);
      setSelectedTaskId((current) =>
        current && next.some((item) => item.task_id === current)
          ? current
          : next[0]?.task_id ?? null,
      );
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load runs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTasks();
    const timer = window.setInterval(() => void loadTasks(), 5000);
    return () => window.clearInterval(timer);
  }, [loadTasks]);

  useEffect(() => {
    if (!selectedTaskId) {
      setTask(null);
      setRun(null);
      setSelectedRunId(null);
      return;
    }
    let active = true;
    getRuntimeTask(selectedTaskId)
      .then((detail) => {
        if (!active) return;
        setTask(detail);
        if (!detail.runs.length) {
          setSelectedRunId(null);
          setRun(null);
          return;
        }
        setSelectedRunId((current) =>
          current && detail.runs.some((item) => item.task_run_id === current)
            ? current
            : detail.runs[0].task_run_id,
        );
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Could not load task");
      });
    return () => {
      active = false;
    };
  }, [selectedTaskId, tasks]);

  useEffect(() => {
    if (!selectedRunId) {
      setRun(null);
      return;
    }
    let active = true;
    getRuntimeTaskRun(selectedRunId)
      .then((runDetail) => {
        if (!active) return;
        setRun(runDetail);
        setSelectedAgentId((current) =>
          current && runDetail.agent_runs.some((item) => item.agent_run_id === current)
            ? current
            : runDetail.agent_runs[0]?.agent_run_id ?? null,
        );
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Could not load run");
      });
    return () => {
      active = false;
    };
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
    return () => {
      active = false;
    };
  }, [selectedAgentId, run]);

  const selectedAgent =
    run?.agent_runs.find((item) => item.agent_run_id === selectedAgentId) ?? null;
  const tree = useMemo(() => buildTree(run?.agent_runs ?? []), [run]);

  return (
    <main className="flex-1 min-w-0 min-h-0 flex flex-col min-[1180px]:flex-row bg-paper" data-testid="runs-view">
      <section className="w-full max-h-[220px] min-[1180px]:w-[320px] min-[1180px]:max-h-none shrink-0 border-b min-[1180px]:border-b-0 min-[1180px]:border-r border-line bg-panel/40 flex flex-col min-h-0">
        <div className="px-5 pt-5 pb-3 flex items-start justify-between gap-3">
          <div>
            <h1 className="text-[24px] font-semibold text-heading">{t("runs.title")}</h1>
            <p className="text-[12px] text-muted mt-0.5">{t("runs.subtitle")}</p>
          </div>
          <button
            className="w-8 h-8 grid place-items-center rounded-lg border border-line bg-panel hover:border-lineStrong"
            onClick={() => void loadTasks()}
            aria-label={t("runs.refresh")}
            title={t("runs.refresh")}
          >
            <Icon name="refresh" size={15} />
          </button>
        </div>
        <div className="px-3 pb-4 overflow-y-auto hairline-scroll">
          {loading ? (
            <div className="px-2 py-4 text-[12.5px] text-muted">{t("runs.loading")}</div>
          ) : tasks.length === 0 ? (
            <div className="mx-2 mt-2 rounded-lg border border-line bg-panel px-3 py-4 text-[12.5px] text-muted">
              {t("runs.empty")}
            </div>
          ) : (
            <div className="space-y-1">
              {tasks.map((item) => (
                <button
                  key={item.task_id}
                  className={
                    "w-full text-left px-3 py-2.5 rounded-lg border " +
                    (item.task_id === selectedTaskId
                      ? "border-lineStrong bg-panel"
                      : "border-transparent hover:border-line hover:bg-panel/70")
                  }
                  onClick={() => {
                    setSelectedTaskId(item.task_id);
                    setSelectedRunId(null);
                  }}
                >
                  <div className="flex items-center gap-2">
                    <StatusDot status={item.status} />
                    <span className="text-[12.5px] font-medium text-ink truncate flex-1">
                      {item.title}
                    </span>
                    <span className="text-[10.5px] text-faint shrink-0">
                      {compactTime(item.updated_at)}
                    </span>
                  </div>
                  <div className="text-[11px] text-muted mt-1 truncate pl-3.5">
                    {item.project_id ? baseName(item.project_id) : t("runs.noProject")} ·{" "}
                    {t(statusKey(item.status))}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-5xl mx-auto px-4 sm:px-7 py-5 sm:py-6">
          <PanelHead
            title={task?.title ?? t("runs.details")}
            sub={
              task
                ? `${task.runs.length} ${t(task.runs.length === 1 ? "runs.attempt" : "runs.attempts")} · ${t(statusKey(task.status))}`
                : t("runs.select")
            }
          />
          {error && (
            <div role="alert" className="mb-4 rounded-lg border border-danger/30 bg-dangerSoft px-3 py-2.5 text-[12px] text-danger">
              {error}
            </div>
          )}
          {task && run ? (
            <>
              {task.runs.length > 1 && (
                <div className="flex items-center gap-2 flex-wrap mb-4" aria-label={t("runs.attempts")}>
                  <span className="text-[11.5px] text-muted mr-1">{t("runs.attempts")}</span>
                  {task.runs.map((item, index) => (
                    <button
                      key={item.task_run_id}
                      className={
                        "h-7 px-2.5 rounded-lg border text-[11.5px] flex items-center gap-1.5 " +
                        (item.task_run_id === selectedRunId
                          ? "border-accent bg-accentSoft text-accent"
                          : "border-line bg-panel text-muted hover:border-lineStrong")
                      }
                      onClick={() => setSelectedRunId(item.task_run_id)}
                    >
                      <StatusDot status={item.status} />
                      #{task.runs.length - index}
                      <span className="text-faint">{compactTime(item.started_at)}</span>
                    </button>
                  ))}
                </div>
              )}

              {run.error && (
                <div role="alert" className="mb-4 rounded-lg border border-danger/30 bg-dangerSoft px-3 py-2.5 text-[12px] text-danger">
                  {run.error}
                </div>
              )}

              <div className="grid grid-cols-2 min-[1180px]:grid-cols-4 gap-px border border-line rounded-lg overflow-hidden bg-line mb-5">
                <Fact label={t("runs.trigger")} value={run.trigger} />
                <Fact label={t("runs.mode")} value={run.mode || t("runs.default")} />
                <Fact label={t("runs.model")} value={run.model || t("runs.default")} />
                <Fact label={t("runs.started")} value={formatTime(run.started_at)} />
              </div>

              <div className="flex items-center justify-between gap-3 mb-2">
                <h2 className="text-[13px] font-semibold text-ink">{t("runs.agentTree")}</h2>
                <button
                  className="text-[12px] text-accent hover:underline"
                  onClick={() => onOpenSession?.(task.session_id)}
                >
                  {t("runs.openConversation")}
                </button>
              </div>
              <div className="border border-line rounded-lg bg-panel overflow-hidden mb-5">
                {tree.map(({ run: item, depth }) => (
                  <button
                    key={item.agent_run_id}
                    className={
                      "w-full min-h-[54px] flex items-center gap-2.5 pr-3 py-2 border-b border-line last:border-b-0 text-left " +
                      (selectedAgentId === item.agent_run_id
                        ? "bg-accentSoft/40"
                        : "hover:bg-paper")
                    }
                    style={{ paddingLeft: 12 + depth * 24 }}
                    onClick={() => setSelectedAgentId(item.agent_run_id)}
                  >
                    {depth > 0 ? (
                      <Icon name="branch" size={15} className="text-faint shrink-0" />
                    ) : (
                      <Icon name="diamond" size={15} className="text-accent shrink-0" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="text-[12.5px] font-medium text-ink">
                        {item.agent_role === "link" ? "Smallink" : item.agent_role}
                      </div>
                      <div className="text-[11px] text-muted truncate mt-0.5">
                        {item.model || t("runs.defaultModel")} · {formatDuration(item, t)}
                      </div>
                    </div>
                    <StatusBadge status={item.status} label={t(statusKey(item.status))} />
                  </button>
                ))}
              </div>

              <div className="grid grid-cols-1 min-[1280px]:grid-cols-[minmax(0,1fr)_minmax(260px,0.7fr)] gap-5">
                <section className="min-w-0">
                  <h2 className="text-[13px] font-semibold text-ink mb-2">{t("runs.eventTimeline")}</h2>
                  <div className="border border-line rounded-lg bg-panel overflow-hidden">
                    {events.length === 0 ? (
                      <div className="px-3 py-4 text-[12px] text-muted">{t("runs.noEvents")}</div>
                    ) : (
                      events.map((event) => <EventRow key={event.event_id} event={event} />)
                    )}
                  </div>
                </section>
                <section className="min-w-0">
                  <h2 className="text-[13px] font-semibold text-ink mb-2">{t("runs.agentResult")}</h2>
                  <div className="border border-line rounded-lg bg-panel p-3">
                    {selectedAgent?.error && (
                      <div className="text-[12px] text-danger mb-2">{selectedAgent.error}</div>
                    )}
                    <pre className="m-0 whitespace-pre-wrap break-words text-[11.5px] leading-relaxed text-muted font-mono max-h-[360px] overflow-auto hairline-scroll">
                      {formatValue(selectedAgent?.output) || t("runs.noOutput")}
                    </pre>
                  </div>
                </section>
              </div>
            </>
          ) : task ? (
            <div className="rounded-lg border border-line bg-panel px-4 py-5 text-[12.5px] text-muted">
              {t("runs.noAttempts")}
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-panel px-3 py-2.5 min-w-0">
      <div className="text-[10.5px] uppercase text-faint font-semibold">{label}</div>
      <div className="text-[12px] text-ink mt-0.5 truncate" title={value}>{value}</div>
    </div>
  );
}

function StatusDot({ status }: { status: RuntimeStatus }) {
  const color =
    status === "completed"
      ? "bg-ok"
      : status === "failed"
        ? "bg-danger"
        : status === "running"
          ? "bg-accent animate-pulse"
          : status === "waiting_approval"
            ? "bg-warnInk"
            : "bg-faint";
  return <span className={`w-2 h-2 rounded-full shrink-0 ${color}`} />;
}

function StatusBadge({ status, label }: { status: RuntimeStatus; label: string }) {
  const color =
    status === "completed"
      ? "bg-okSoft text-ok"
      : status === "failed"
        ? "bg-dangerSoft text-danger"
        : status === "waiting_approval"
          ? "bg-warnSoft text-warnInk"
          : status === "running"
            ? "bg-accentSoft text-accent"
            : "bg-paper text-muted";
  return (
    <span className={`text-[10.5px] px-2 py-1 rounded-full shrink-0 ${color}`}>
      {label}
    </span>
  );
}

function EventRow({ event }: { event: RuntimeRunEvent }) {
  const summary = eventSummary(event);
  return (
    <details className="group border-b border-line last:border-b-0">
      <summary className="list-none cursor-pointer min-h-[42px] flex items-center gap-2 px-3 py-2 hover:bg-paper">
        <Icon name="chevronRight" size={12} className="text-faint group-open:rotate-90 transition-transform" />
        <span className="text-[11.5px] font-mono text-ink">{event.event_type}</span>
        {summary && <span className="text-[11px] text-muted truncate flex-1">{summary}</span>}
        <span className="text-[10.5px] text-faint ml-auto shrink-0">
          {formatClock(event.created_at)}
        </span>
      </summary>
      <pre className="m-0 px-8 pb-3 whitespace-pre-wrap break-words text-[11px] leading-relaxed text-muted font-mono">
        {formatValue(event.data)}
      </pre>
    </details>
  );
}

function buildTree(runs: RuntimeAgentRun[]): { run: RuntimeAgentRun; depth: number }[] {
  const children = new Map<string | null, RuntimeAgentRun[]>();
  for (const run of runs) {
    const list = children.get(run.parent_agent_run_id) ?? [];
    list.push(run);
    children.set(run.parent_agent_run_id, list);
  }
  const result: { run: RuntimeAgentRun; depth: number }[] = [];
  const visit = (parent: string | null, depth: number) => {
    for (const run of children.get(parent) ?? []) {
      result.push({ run, depth });
      visit(run.agent_run_id, depth + 1);
    }
  };
  visit(null, 0);
  return result;
}

function eventSummary(event: RuntimeRunEvent): string {
  const data = event.data ?? {};
  return String(
    data.name ?? data.tool ?? data.status ?? data.error ?? data.text ?? data.input ?? "",
  ).replace(/\s+/g, " ").slice(0, 100);
}

function statusKey(status: RuntimeStatus): TranslationKey {
  return `status.${status}` as TranslationKey;
}

function formatValue(value: any): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatClock(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function compactTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

function formatDuration(
  run: RuntimeAgentRun,
  t: (key: TranslationKey) => string,
): string {
  if (!run.finished_at) {
    return ACTIVE.has(run.status) ? t("runs.inProgress") : t("runs.notFinished");
  }
  const start = new Date(run.started_at).getTime();
  const end = new Date(run.finished_at).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return "finished";
  const ms = Math.max(0, end - start);
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;
}
