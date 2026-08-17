import { Icon, type IconName } from "./Icon";
import { useI18n } from "../i18n";

type SurfaceKey = "session" | "integrations" | "memory" | "agents" | "runs" | "scheduled" | "settings" | string;

export function CompactSidebar({
  surface,
  onExpand,
  onNewSession,
  onSearch,
  onGoHome,
  onOpenIntegrations,
  onOpenMemory,
  onOpenAgents,
  onOpenRuns,
  onOpenScheduled,
  onOpenSettings,
}: {
  surface: SurfaceKey;
  onExpand: () => void;
  onNewSession: () => void;
  onSearch: () => void;
  onGoHome: () => void;
  onOpenIntegrations: () => void;
  onOpenMemory: () => void;
  onOpenAgents: () => void;
  onOpenRuns: () => void;
  onOpenScheduled: () => void;
  onOpenSettings: () => void;
}) {
  const { t, tr } = useI18n();
  return (
    <aside className="compact-sidebar" aria-label={tr("Collapsed navigation") }>
      <RailButton icon="sidebar" label={tr("Show sidebar (⌘B)")} onClick={onExpand} />
      <button
        className={`compact-brand${surface === "session" ? " active" : ""}`}
        onClick={onGoHome}
        title={tr("Back to conversation")}
        aria-label={tr("Back to conversation")}
      >
        <Icon name="logo" size={23} />
      </button>
      <div className="compact-divider" />
      <RailButton icon="plus" label={t("nav.newSession")} onClick={onNewSession} emphasized />
      <RailButton icon="search" label={t("nav.search")} onClick={onSearch} />
      <div className="compact-divider" />
      <RailButton icon="plug" label={t("nav.connectors")} active={surface === "integrations"} onClick={onOpenIntegrations} />
      <RailButton icon="diamond" label={t("nav.memory")} active={surface === "memory"} onClick={onOpenMemory} />
      <RailButton icon="sparkle" label={t("nav.agents")} active={surface === "agents"} onClick={onOpenAgents} />
      <RailButton icon="branch" label={tr("Run center")} active={surface === "runs"} onClick={onOpenRuns} />
      <RailButton icon="clock" label={tr("Automations")} active={surface === "scheduled"} onClick={onOpenScheduled} />
      <div className="flex-1" />
      <RailButton icon="gear" label={tr("Settings")} active={surface === "settings"} onClick={onOpenSettings} />
    </aside>
  );
}

function RailButton({
  icon,
  label,
  active,
  emphasized,
  onClick,
}: {
  icon: IconName;
  label: string;
  active?: boolean;
  emphasized?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={`compact-nav-btn${active ? " active" : ""}${emphasized ? " emphasized" : ""}`}
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-current={active ? "page" : undefined}
    >
      <Icon name={icon} size={17} />
    </button>
  );
}
