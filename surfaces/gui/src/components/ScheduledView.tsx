import { useEffect, useState } from "react";
import {
  createAutomation,
  deleteAutomation,
  getAutomation,
  getAutomations,
  markAutomationSeen,
  announceAutomationsChanged,
  updateAutomation,
  type Automation,
  type AutomationRun,
} from "../api";
import { Icon } from "./Icon";
import { PanelHead } from "./IntegrationsView";
import { AutomationQuickstart } from "./AutomationQuickstart";
import { InlineFeedback, PageState } from "./AsyncFeedback";
import { useI18n, type TranslationParams } from "../i18n";

// Shared utility strings (the §28 page shell — mirrors IntegrationsView's constants).
const CARD = "rounded-lg border border-line bg-panel";

// Parse a simple "min hour * * dow" cron back into the time + frequency the editor uses.
// Falls back to 09:00 / daily for anything it doesn't recognize (e.g. agent-written crons).
function fromCron(cron?: string | null): { time: string; freq: string } {
  const parts = (cron || "").trim().split(/\s+/);
  if (parts.length !== 5) return { time: "09:00", freq: "daily" };
  const [m, h, , , dow] = parts;
  const hh = String(Math.min(23, Math.max(0, parseInt(h, 10) || 9))).padStart(2, "0");
  const mm = String(Math.min(59, Math.max(0, parseInt(m, 10) || 0))).padStart(2, "0");
  const freq = dow === "1-5" ? "weekdays" : dow === "0,6" || dow === "6,0" ? "weekends" : "daily";
  return { time: `${hh}:${mm}`, freq };
}

type Translator = (english: string, params?: TranslationParams) => string;

const fmt = (t: number | null, locale: string) =>
  t ? new Date(t * 1000).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" }) : "—";

function scheduleLabel(task: Automation, tr: Translator): string {
  const raw = task.schedule_raw?.cron;
  if (!raw) return tr(task.schedule);
  const { time, freq } = fromCron(raw);
  if (freq === "weekdays") return tr("Weekdays at {time}", { time });
  if (freq === "weekends") return tr("Weekends at {time}", { time });
  return tr("Daily at {time}", { time });
}

// Map a simple time-of-day + frequency selection to a 5-field cron string.
function toCron(time: string, freq: string): string {
  const [h, m] = (time || "09:00").split(":").map((x) => parseInt(x, 10) || 0);
  const dow = freq === "weekdays" ? "1-5" : freq === "weekends" ? "0,6" : "*";
  return `${m} ${h} * * ${dow}`;
}

// The §28 page shell: full-bleed main, centered ≤4xl column — same as Connectors/Activity/Inbox.
function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-4xl mx-auto px-7 py-6">{children}</div>
      </div>
    </main>
  );
}

interface Props {
  // `task` gives the opened run session its context (banner + "Back to runs"; owner ask 2026-07-04).
  onOpenRun: (
    sessionId: string,
    workspace: string,
    agent: string,
    task?: { id: string; title: string },
  ) => void;
  onRunNow: (taskId: string, title?: string) => void;
  onOpenConnectors: () => void;
  // Open directly on a task's detail (set by the run banner's "Back to runs").
  initialOpenId?: string | null;
}

export function ScheduledView({ onOpenRun, onRunNow, onOpenConnectors, initialOpenId }: Props) {
  const { tr, locale } = useI18n();
  const [tasks, setTasks] = useState<Automation[]>([]);
  const [openId, setOpenId] = useState<string | null>(initialOpenId ?? null);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  // The sidebar's Scheduled band can retarget an ALREADY-open Automations surface —
  // initial state alone would ignore the change (UX-023).
  useEffect(() => {
    if (initialOpenId) setOpenId(initialOpenId);
  }, [initialOpenId]);

  const refresh = () => {
    setLoadError("");
    return getAutomations()
      .then(setTasks)
      .catch((reason) => {
        setLoadError(
          reason instanceof Error ? reason.message : tr("Could not load automations"),
        );
      })
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    refresh();
    const h = setInterval(refresh, 5000);
    return () => clearInterval(h);
  }, []);

  // Create from a payload, refresh the list, and open the new task's detail. `permissions`
  // rides through for quickstart recipes (§25 write grants).
  const create = async (payload: {
    title: string;
    instructions: string;
    cron?: string;
    permissions?: { tool: string; target: string; access: "read" | "write" }[];
  }) => {
    setError("");
    setBusy(payload.title);
    try {
      const res = await createAutomation(payload);
      announceAutomationsChanged(); // new entry shows in the sidebar band right away
      await refresh();
      if (res.ok && res.task) {
        setShowForm(false);
        setOpenId(res.task.id);
      } else if (res.error) {
        setError(res.error);
      }
    } finally {
      setBusy(null);
    }
  };

  if (openId) {
    return (
      <TaskDetail
        id={openId}
        onBack={() => { setOpenId(null); refresh(); }}
        onOpenRun={onOpenRun}
        onRunNow={onRunNow}
      />
    );
  }

  const empty = tasks.length === 0;

  if (loading) {
    return (
      <Shell>
        <PageState
          icon="clock"
          title={tr("Loading automations…")}
          body={tr("Reading schedules and recent run history.")}
        />
      </Shell>
    );
  }

  if (loadError && tasks.length === 0) {
    return (
      <Shell>
        <PageState
          icon="clock"
          title={tr("Automations are unavailable")}
          body={loadError}
          action={tr("Try again")}
          onAction={() => void refresh()}
        />
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <PanelHead title={tr("Automations")} sub={tr("Recurring tasks Smallink runs on a schedule.")} />
        </div>
        <button
          className="inline-flex items-center gap-1.5 text-[12.5px] px-3 py-1.5 rounded-lg border border-lineStrong bg-panel hover:border-accent hover:text-accent shrink-0"
          onClick={() => setShowForm((v) => !v)}
        >
          <Icon name="plus" size={14} /> {tr("New automation")}
        </button>
      </div>

      <div className="text-[12px] text-faint flex gap-1.5 mb-4">
        <span aria-hidden>ⓘ</span>
        <span>
          {tr("Smallink needs to be running when a task is due. If this Mac was asleep, the task catches up once after Smallink starts again.")}
        </span>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-danger/30 bg-dangerSoft px-3 py-2 text-[12.5px] text-danger" role="alert">
          {error}
        </div>
      )}
      {loadError && (
        <div className="mb-4">
          <InlineFeedback
            tone="warning"
            title={tr("Automation status may be out of date")}
            body={loadError}
            action={tr("Retry")}
            onAction={() => void refresh()}
          />
        </div>
      )}

      {showForm && (
        <NewAutomationForm
          busy={busy !== null}
          onCancel={() => setShowForm(false)}
          onCreate={create}
        />
      )}

      {/* The quickstart (§29): ONE template system — role recipes + generic templates, each
          card with §27 connector dots; picking one expands the configure card. */}
      {(empty || showForm) && (
        <AutomationQuickstart
          busy={busy !== null}
          onCreate={create}
          onOpenConnectors={onOpenConnectors}
        />
      )}

      {empty ? (
        !showForm && (
          <div className={CARD + " p-4 text-[12.5px] text-muted"}>
            {tr("No scheduled tasks yet — choose a template above, create one manually, or ask Smallink in a conversation.")}
          </div>
        )
      ) : (
        <div className="flex flex-col gap-2.5">
          {tasks.map((t) => (
            <div
              className={CARD + " sched-card px-4 py-3 cursor-pointer hover:border-lineStrong transition-colors"}
              key={t.id}
              onClick={() => setOpenId(t.id)}
            >
              <div className="flex items-center justify-between gap-2.5 mb-1">
                <span className="text-[13.5px] font-semibold truncate">{t.title}</span>
                <Icon name="chevronRight" size={14} className="text-faint shrink-0" />
              </div>
              <div className="flex items-center gap-1.5 text-[12px] text-muted">
                <Icon name="clock" size={13} className="text-faint shrink-0" />
                {t.enabled ? scheduleLabel(t, tr) : tr("Paused")} ·{" "}
                {tr("next {time}", { time: fmt(t.next_run, locale) })} ·{" "}
                {tr(t.run_count === 1 ? "{count} run" : "{count} runs", { count: t.run_count })}
                {t.last_status ? ` · ${tr("last {status}", { status: tr(t.last_status) })}` : ""}
              </div>
            </div>
          ))}
        </div>
      )}
    </Shell>
  );
}

function NewAutomationForm({
  busy,
  onCancel,
  onCreate,
}: {
  busy: boolean;
  onCancel: () => void;
  onCreate: (p: { title: string; instructions: string; cron?: string }) => void;
}) {
  const { tr } = useI18n();
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [time, setTime] = useState("09:00");
  const [freq, setFreq] = useState("daily");

  const valid = title.trim() && instructions.trim();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className={CARD + " tmpl-form p-4 mb-4"}>
      <div className="text-[11px] uppercase tracking-[0.05em] text-faint mb-2.5">
        {tr("New automation")}
      </div>
      <input
        className="tmpl-input"
        placeholder={tr("Title (e.g. Daily standup notes)")}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <textarea
        className="tmpl-input tmpl-textarea"
        placeholder={tr("What should it do each run? (e.g. Summarize today's calendar and open tasks.)")}
        value={instructions}
        onChange={(e) => setInstructions(e.target.value)}
      />
      <div className="tmpl-sched">
        <label className="tmpl-field">
          <span>{tr("At")}</span>
          <input
            type="time"
            className="tmpl-input tmpl-time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
          />
        </label>
        <label className="tmpl-field">
          <span>{tr("Repeat")}</span>
          <select
            className="tmpl-input tmpl-select"
            value={freq}
            onChange={(e) => setFreq(e.target.value)}
          >
            <option value="daily">{tr("Every day")}</option>
            <option value="weekdays">{tr("Weekdays")}</option>
            <option value="weekends">{tr("Weekends")}</option>
          </select>
        </label>
      </div>
      <div className="tmpl-form-actions">
        <button
          className="btn-primary sm"
          disabled={!valid || busy}
          onClick={() =>
            onCreate({
              title: title.trim(),
              instructions: instructions.trim(),
              cron: toCron(time, freq),
            })
          }
        >
          {tr(busy ? "Creating…" : "Create automation")}
        </button>
        <button className="link" onClick={onCancel}>{tr("Cancel")}</button>
      </div>
    </div>
  );
}

function TaskDetail({
  id,
  onBack,
  onOpenRun,
  onRunNow,
}: {
  id: string;
  onBack: () => void;
  onOpenRun: (
    sessionId: string,
    workspace: string,
    agent: string,
    task?: { id: string; title: string },
  ) => void;
  onRunNow: (taskId: string, title?: string) => void;
}) {
  const { tr, locale } = useI18n();
  const [task, setTask] = useState<Automation | null>(null);
  const [runs, setRuns] = useState<AutomationRun[]>([]);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [time, setTime] = useState("09:00");
  const [freq, setFreq] = useState("daily");
  const [saving, setSaving] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);

  // The seen mark AS OF opening — the "new" pills compare against this frozen value
  // while mark-seen advances the stored one (badge clears; highlights survive).
  const [seenMark, setSeenMark] = useState<number | null>(null);

  const refresh = () =>
    getAutomation(id)
      .then((d) => {
        if (!d.task) {
          // Deleted (or a stale reopen target): "Loading…" forever is a trap —
          // fall back to the overview (owner-hit 2026-07-20).
          onBack();
          return;
        }
        setTask(d.task);
        setRuns(d.runs || []);
        setSeenMark((cur) => (cur === null ? d.task?.seen_runs_at ?? 0 : cur));
      })
      .catch(() => {});
  useEffect(() => {
    setSeenMark(null);
    refresh();
    // Opening the detail IS reading it: advance the seen mark and nudge the
    // sidebar so the badge clears immediately (UX-023).
    markAutomationSeen(id)
      .then(() => announceAutomationsChanged())
      .catch(() => {});
  }, [id]);

  if (!task)
    return (
      <Shell>
        <div className="text-[13px] text-muted">{tr("Loading…")}</div>
      </Shell>
    );

  const startEdit = () => {
    setTitle(task.title);
    setInstructions(task.instructions);
    const { time: t, freq: f } = fromCron(task.schedule_raw?.cron);
    setTime(t);
    setFreq(f);
    setEditing(true);
  };
  const saveEdit = async () => {
    setSaving(true);
    try {
      await updateAutomation(id, {
        title: title.trim(),
        instructions: instructions.trim(),
        cron: toCron(time, freq),
      });
      await refresh();
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };
  const toggle = async () => {
    await updateAutomation(id, { enabled: !task.enabled });
    refresh();
  };
  const remove = async () => {
    await deleteAutomation(id);
    announceAutomationsChanged(); // the sidebar band must not wait out its poll
    onBack();
  };

  return (
    <Shell>
      <button className="text-[13px] text-muted hover:text-ink mb-3" onClick={onBack}>
        <Icon name="arrowLeft" size={13} /> {tr("Back to automations")}
      </button>
      <div className="sched-detail">
        <div className="sched-detail-head">
          {editing ? (
            <input
              className="tmpl-input sched-edit-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={tr("Title")}
            />
          ) : (
            <h2 className="text-[18px] font-semibold tracking-tight">{task.title}</h2>
          )}
          <div className="sched-actions">
            {editing ? (
              <>
                <button className="btn-primary sm" disabled={saving || !title.trim() || !instructions.trim()} onClick={saveEdit}>
                  {tr(saving ? "Saving…" : "Save")}
                </button>
                <button className="link" onClick={() => setEditing(false)}>{tr("Cancel")}</button>
              </>
            ) : (
              <>
                <button className="btn-primary sm" onClick={() => onRunNow(id, task.title)}>
                  {tr("Run now")}
                </button>
                <button className="btn sm" onClick={startEdit}>{tr("Edit")}</button>
                <button
                  className={"btn sm danger-btn" + (confirmRemove ? " font-semibold" : "")}
                  onClick={() => {
                    if (confirmRemove) void remove();
                    else setConfirmRemove(true);
                  }}
                  onBlur={() => setConfirmRemove(false)}
                >
                  <Icon name="trash" size={14} /> {tr(confirmRemove ? "Confirm delete" : "Delete")}
                </button>
              </>
            )}
          </div>
        </div>

        {editing ? (
          <div className="tmpl-sched sched-edit-sched">
            <label className="tmpl-field">
              <span>{tr("At")}</span>
              <input type="time" className="tmpl-input tmpl-time" value={time} onChange={(e) => setTime(e.target.value)} />
            </label>
            <label className="tmpl-field">
              <span>{tr("Repeat")}</span>
              <select className="tmpl-input tmpl-select" value={freq} onChange={(e) => setFreq(e.target.value)}>
                <option value="daily">{tr("Every day")}</option>
                <option value="weekdays">{tr("Weekdays")}</option>
                <option value="weekends">{tr("Weekends")}</option>
              </select>
            </label>
          </div>
        ) : (
          <div className="conn-meta">
            <label className="switch">
              <input type="checkbox" checked={task.enabled} onChange={toggle} />
              <span className="slider" />
            </label>{" "}
            {task.enabled
              ? tr("Active · next {time}", { time: fmt(task.next_run, locale) })
              : tr("Paused")}{" "}
            · {scheduleLabel(task, tr)}
          </div>
        )}

        <div className="sa-sub">{tr("Instructions")}</div>
        {editing ? (
          <textarea
            className="tmpl-input tmpl-textarea sched-edit-instr"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
        ) : (
          <div className="sched-instructions">{task.instructions}</div>
        )}

        {(task.always_allowed || []).length > 0 && (
          <>
            <div className="sa-sub">{tr("Allowed without asking")}</div>
            <div className="dim" style={{ marginBottom: 8, fontSize: 12.5 }}>
              {tr("Standing approvals this automation may use — everything else still asks first.")}
            </div>
            <div className="sched-grants" data-testid="task-grants">
              {(task.always_allowed || []).map((rule) => (
                <div className="sched-grant" key={rule.entry}>
                  <span className="sched-grant-rule">
                    <code>{rule.tool}</code>
                    {rule.target && <span className="sched-grant-target"> → {rule.target}</span>}
                  </span>
                  <button
                    className="link"
                    title={tr("This automation will ask for approval again")}
                    onClick={async () => {
                      await updateAutomation(id, { revoke: rule.entry });
                      refresh();
                    }}
                  >
                    {tr("Revoke")}
                  </button>
                </div>
              ))}
            </div>
          </>
        )}

        <div className="sa-sub">{tr("Runs")}</div>
        <div className="dim" style={{ marginBottom: 8, fontSize: 12.5 }}>
          {tr("Each run is a live conversation — open one to see what the agent did and ask a follow-up.")}
        </div>
        {runs.length === 0 && <div className="dim">{tr("No runs yet.")}</div>}
        {runs.map((r) => (
          <div
            className="sched-run open"
            key={r.run_id}
            onClick={() =>
              r.session_id &&
              onOpenRun(r.session_id, task.workspace, task.agent, {
                id: task.id,
                title: task.title,
              })
            }
            title={tr("Open this run's conversation")}
          >
            <div className="sched-run-row">
              <span>
                {seenMark !== null && r.started_at > seenMark && (
                  <span className="run-new-pill" data-testid="run-new">{tr("new")}</span>
                )}
                {fmt(r.started_at, locale)} · <span className={"run-" + r.status}>{tr(r.status)}</span> · {tr(r.trigger)}
                {r.artifacts.length > 0 && (
                  <span className="dim">
                    {" · "}
                    {tr(r.artifacts.length === 1 ? "{count} file" : "{count} files", {
                      count: r.artifacts.length,
                    })}
                  </span>
                )}
              </span>
              <span className="sched-run-go" aria-hidden>
                {tr("Open run")} ›
              </span>
            </div>
            {r.result_text && <div className="sched-run-peek">{r.result_text}</div>}
            {r.error && <div className="mcp-error">{r.error}</div>}
          </div>
        ))}
      </div>
    </Shell>
  );
}
