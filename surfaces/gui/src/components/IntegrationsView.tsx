import { useState } from "react";
import { ConnectorsSection } from "./connectors/ConnectorsSection";
import { Icon } from "./Icon";
import { SkillHub } from "./SkillHub";
import { useI18n } from "../i18n";

// The Connectors surface keeps a compact client-visible sub-nav. MCP remains available in the
// engine and persisted configuration, but is intentionally not projected into the current UI.
type IntTab = "connectors" | "skills";

// Fixed sub-nav (UX-DECISIONS §21): connector detail lives as a SUBPAGE under
// Connectors, never as a nav item — the nav must not grow per connector.
const INT_TABS: { key: IntTab; label: string; icon: "plug" | "wrench" }[] = [
  { key: "connectors", label: "Connectors", icon: "plug" },
  { key: "skills", label: "Skill Hub", icon: "wrench" },
];

export function IntegrationsView({
  workspace,
  onCreateSkillWithAgent,
  onOpenMemory,
}: {
  workspace?: string;
  onCreateSkillWithAgent?: () => void;
  onOpenMemory?: () => void;
}) {
  const { tr } = useI18n();
  const [tab, setTab] = useState<IntTab>("connectors");
  // The catalog reports its visible count from the same refresh that renders the list.
  const [connCount, setConnCount] = useState<number | null>(null);

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <nav className="page-subnav w-[208px] shrink-0 border-r border-line bg-panel/40 px-3 py-4">
        <div className="px-2 text-[13.5px] font-semibold mb-3 flex items-center gap-2">
          <Icon name="plug" size={16} /> {tr("Connectors")}
        </div>
        {INT_TABS.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              className={
                "w-full text-left px-2.5 py-2 rounded-lg text-[13px] flex items-center justify-between " +
                (active
                  ? "bg-paper text-accent font-medium"
                  : "text-muted hover:bg-paper hover:text-ink")
              }
              onClick={() => setTab(t.key)}
            >
              <span className="flex items-center gap-2 min-w-0">
                <Icon name={t.icon} size={15} /> {tr(t.label)}
              </span>
              {t.key === "connectors" && connCount != null && (
                <span className={"text-[11px] shrink-0 " + (active ? "text-accent" : "text-faint")}>
                  {connCount}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className={(tab === "skills" ? "max-w-6xl" : "max-w-4xl") + " mx-auto px-7 py-6"}>
          {tab === "connectors" ? (
            <section>
              <PanelHead
                title={tr("Connectors")}
                sub={tr("Manage the data sources and tools Smallink can use. Connected items appear first.")}
              />
              <ConnectorsSection onOpenMemory={onOpenMemory} onCountChange={setConnCount} />
            </section>
          ) : (
            <SkillHub workspace={workspace} onCreateWithAgent={onCreateSkillWithAgent} />
          )}
        </div>
      </div>
    </main>
  );
}

export function PanelHead({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-[24px] font-semibold text-heading">{title}</h2>
      <p className="text-[12.5px] text-muted mt-0.5">{sub}</p>
    </div>
  );
}
