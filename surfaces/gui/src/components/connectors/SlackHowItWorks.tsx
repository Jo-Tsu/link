import { useState } from "react";
import type { SlackWorkspace } from "../../api";
import { useI18n } from "../../i18n";
import { Icon, type IconName } from "../Icon";

const KEY = "link.slack.howitworks.collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function SlackHowItWorks({ workspaces }: { workspaces: SlackWorkspace[] }) {
  const { tr } = useI18n();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const mine = workspaces.find(
    (workspace) =>
      workspace.installer_user_id &&
      workspace.allowed_users.includes(workspace.installer_user_id),
  );
  const workspace = mine ?? workspaces[0];

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(KEY, next ? "1" : "0");
    } catch {
      // Persistence is optional; the disclosure still works for this session.
    }
  };

  const steps: Array<{ icon: IconName; title: string; body: string }> = [
    {
      icon: "chat",
      title: tr("Mention Link"),
      body: tr(
        "Mention @Link in a channel where the app is available. Link creates a session and replies in the same Slack thread.",
      ),
    },
    {
      icon: "branch",
      title: tr("Keep the context"),
      body: tr(
        "Continue in the thread to keep using the same session, history, and working context.",
      ),
    },
    {
      icon: "shield",
      title: tr("Approve teammates"),
      body: tr(
        "A teammate's first request waits for your approval. Once approved, they are added to this workspace's People list.",
      ),
    },
  ];

  return (
    <section className="mb-5" data-testid="slack-howitworks">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-ok/10 text-ok">
          <Icon name="shield" size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[13.5px] font-semibold tracking-tight">
            {tr("Slack is connected")}
          </h3>
          <p className="mt-0.5 text-[12px] text-muted">
            {tr("{workspace} is ready to send requests to Link.", {
              workspace: workspace?.account || tr("Workspace"),
            })}
            {mine ? ` ${tr("You are already in the People list.")}` : ""}
          </p>
        </div>
        <button
          className="inline-flex h-8 shrink-0 items-center gap-1.5 px-2 text-[12px] text-muted hover:text-ink"
          data-testid="hiw-collapse"
          title={collapsed ? tr("Show how it works") : tr("Collapse")}
          onClick={toggle}
        >
          {collapsed ? tr("How it works") : tr("Hide")}
          <Icon
            name={collapsed ? "chevronRight" : "chevronDown"}
            size={14}
            className={collapsed ? "" : "rotate-180"}
          />
        </button>
      </div>

      {!collapsed && (
        <div className="mt-3 grid gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-3">
          {steps.map((step, index) => (
            <div
              key={step.title}
              className="min-w-0 bg-panel p-3.5"
              data-testid={`hiw-step-${index}`}
            >
              <div className="flex items-center gap-2">
                <Icon name={step.icon} size={15} className="text-accent" />
                <span className="text-[12.5px] font-semibold">{step.title}</span>
              </div>
              <p className="mt-2 text-[12px] leading-5 text-muted">{step.body}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
