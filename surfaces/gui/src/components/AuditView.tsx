import { useEffect, useState } from "react";
import { getAudit, type AuditEvent } from "../api";
import { PanelHead } from "./IntegrationsView";
import { useI18n } from "../i18n";
import { InlineFeedback, PageState } from "./AsyncFeedback";

// Activity — connector/browser tool history, restructured onto the IntegrationsView page shell
// (centered panel + PanelHead + cards), replacing the legacy `page-view` layout. Read-only:
// filterable, with sanitized arguments.
const CARD = "rounded-lg border border-line bg-panel";
const INPUT = "px-3 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";
const BTN_ACCENT = "text-[12.5px] px-3 py-1.5 rounded-lg bg-accent text-onAccent shrink-0";

export function AuditView() {
  const { tr } = useI18n();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [sessionFilter, setSessionFilter] = useState("");
  const [connectorFilter, setConnectorFilter] = useState("");
  const [toolFilter, setToolFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = () => {
    setError("");
    return getAudit({
      limit: 150,
      session_id: sessionFilter.trim() || undefined,
      connector: connectorFilter.trim() || undefined,
      tool: toolFilter.trim() || undefined,
    })
      .then(setEvents)
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : tr("Could not load activity"));
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    void refresh();
  }, []);

  if (loading) {
    return (
      <main className="flex-1 min-w-0 flex bg-paper">
        <div className="max-w-4xl mx-auto w-full px-7 py-6">
          <PageState
            icon="branch"
            title={tr("Loading activity…")}
            body={tr("Reading recent tool and connector events.")}
          />
        </div>
      </main>
    );
  }

  if (error && events.length === 0) {
    return (
      <main className="flex-1 min-w-0 flex bg-paper">
        <div className="max-w-4xl mx-auto w-full px-7 py-6">
          <PageState
            icon="branch"
            title={tr("Activity is unavailable")}
            body={error}
            action={tr("Try again")}
            onAction={() => void refresh()}
          />
        </div>
      </main>
    );
  }

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-4xl mx-auto px-7 py-6">
          <PanelHead
            title={tr("Activity")}
            sub={tr("Review recent connector and browser tool activity. Sensitive arguments are sanitized before storage.")}
          />

          <div className="flex items-center gap-2 flex-wrap mb-4">
            <input className={INPUT} placeholder={tr("Session ID")} aria-label={tr("Session ID")} value={sessionFilter} onChange={(e) => setSessionFilter(e.target.value)} />
            <input className={INPUT} placeholder={tr("Connector")} aria-label={tr("Connector")} value={connectorFilter} onChange={(e) => setConnectorFilter(e.target.value)} />
            <input className={INPUT} placeholder={tr("Tool")} aria-label={tr("Tool")} value={toolFilter} onChange={(e) => setToolFilter(e.target.value)} />
            <button className={BTN_ACCENT} onClick={refresh}>
              {tr("Filter")}
            </button>
          </div>
          {error && (
            <div className="mb-4">
              <InlineFeedback
                tone="warning"
                title={tr("Activity may be out of date")}
                body={error}
                action={tr("Retry")}
                onAction={() => void refresh()}
              />
            </div>
          )}

          {events.length === 0 ? (
            <div className={CARD + " p-4 text-[13px] text-muted"}>{tr("No activity recorded yet.")}</div>
          ) : (
            <div className="space-y-2">
              {events.map((ev) => (
                <AuditRow ev={ev} key={ev.id} />
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

function AuditRow({ ev }: { ev: AuditEvent }) {
  const { tr } = useI18n();
  return (
    <div className={CARD + " p-3.5"}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-[12.5px] font-medium text-ink">{ev.tool}</span>
        <span className="text-[11.5px] text-faint">
          {ev.connector || tr("Tool")} · {ev.stage || ev.status || tr("Event")} · {ev.timestamp}
        </span>
      </div>
      <div className="text-[11.5px] text-muted mt-0.5">
        {tr("Session")} {ev.session_id || "-"} {ev.approval ? `· ${ev.approval}` : ""} {ev.status ? `· ${ev.status}` : ""}
      </div>
      {ev.resource && <div className="text-[11.5px] text-faint mt-0.5">{tr("Resource")}: {ev.resource}</div>}
      {ev.args && Object.keys(ev.args).length > 0 && (
        <div className="font-mono text-[11.5px] text-muted mt-1.5 break-words">{formatAuditArgs(ev.args)}</div>
      )}
      {(ev.reason || ev.result_preview) && (
        <div className="text-[11.5px] text-faint mt-1">{ev.reason || ev.result_preview}</div>
      )}
    </div>
  );
}

function formatAuditArgs(args: Record<string, any>) {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("  ");
}
