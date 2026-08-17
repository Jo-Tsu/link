import { useState } from "react";
import { type CloudStatus, type Connector, type SlackStatus } from "../../api";
import { ConnectorBadge } from "../../connectors/ConnectorIcon";
import { AddConnectionModal } from "./AddConnectionModal";
import { CHIP_OK, CHIP_OFF, CHIP_WARN, GRP, GRP_H, FOOT, PILL_QUIET, ROW } from "./ui";
import { useI18n, type TranslationParams } from "../../i18n";

// The Connectors LIST (UX-DECISIONS §21): connected first in their own inset group —
// rows navigate to the connector's detail subpage; problems surface as a chip in the
// list, never one click deep. Available connectors below with a Connect pill.

const AVAILABLE_FOLD = 8; // rows shown before "show all"

export function ConnectorsList({
  connectors,
  cloud,
  slack,
  onOpen,
  onChanged,
  onOpenMemory,
}: {
  connectors: Connector[];
  cloud: CloudStatus | null;
  slack: SlackStatus | null;
  onOpen: (name: string) => void;
  onChanged: () => void;
  onOpenMemory?: () => void;
}) {
  const { tr } = useI18n();
  const [filter, setFilter] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [connecting, setConnecting] = useState<string | null>(null);

  const q = filter.trim().toLowerCase();
  const match = (c: Connector) => !q || c.title.toLowerCase().includes(q) || c.name.includes(q);
  const connected = connectors.filter((c) => c.connected && match(c));
  const available = connectors.filter((c) => !c.connected && c.available && match(c));
  const shown = showAll || q ? available : available.slice(0, AVAILABLE_FOLD);
  const connectingC = connecting ? connectors.find((c) => c.name === connecting) : null;

  return (
    <div>
      <div className="flex items-center justify-end mb-4">
        <label className="w-56 h-9 px-3 rounded-full border border-line bg-panel flex items-center gap-2 focus-within:border-accent focus-within:ring-2 focus-within:ring-accentSoft">
          <span className="text-faint" aria-hidden="true">⌕</span>
          <input
            placeholder={tr("Search")}
            aria-label={tr("Search connectors")}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="min-w-0 flex-1 bg-transparent text-[13px] outline-none"
          />
        </label>
      </div>

      {/* No cloud strip here anymore (§26): the sidebar's account row is the permanent
          sign-in home, and the connect modals keep their inline sign-in panes. */}
      {connected.length > 0 && (
        <>
          <div className={GRP_H + " !mt-0"}>{tr("Connected")} · {connected.length}</div>
          <div className={GRP}>
            {connected.map((c) => (
              <button
                key={c.name}
                data-testid={`connector-${c.name}`}
                className={ROW + " w-full text-left hover:bg-paper/60"}
                onClick={() => onOpen(c.name)}
              >
                <ConnectorBadge connector={c} size={34} title={c.title} />
                <span className="min-w-0 flex-1">
                  <span className="font-medium text-[13.5px]">{c.title}</span>
                  <span className="block text-[12px] text-muted">{statusLine(c, tr)}</span>
                </span>
                {healthChip(c, slack, tr)}
                <span className="text-faint text-[15px] shrink-0">›</span>
              </button>
            ))}
          </div>
        </>
      )}

      <div className={GRP_H}>{tr("Available")}</div>
      <div className={GRP}>
        {shown.map((c) => (
          <div key={c.name} className={ROW + " !p-0"}>
            <button
              type="button"
              data-testid={`connector-${c.name}`}
              className="min-w-0 flex-1 flex items-center gap-3 px-4 py-2.5 text-left hover:bg-paper/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accentSoft"
              onClick={() => onOpen(c.name)}
            >
              <ConnectorBadge connector={c} size={34} title={c.title} />
              <span className="min-w-0 flex-1">
                <span className="font-medium text-[13.5px]">{c.title}</span>
                <span className="block text-[12px] text-muted truncate">{tr(c.blurb)}</span>
              </span>
              <span className="text-faint text-[15px] shrink-0">›</span>
            </button>
            <button
              type="button"
              className={PILL_QUIET + " mr-4"}
              onClick={() => setConnecting(c.name)}
              aria-label={tr("Connect {name}", { name: c.title })}
            >
              {tr("Connect")}
            </button>
          </div>
        ))}
        {shown.length === 0 && (
          <div className={ROW + " text-[12.5px] text-muted"}>{tr("Nothing matches.")}</div>
        )}
      </div>
      {!showAll && !q && available.length > AVAILABLE_FOLD && (
        <div className={FOOT}>
          {tr("{count} more", { count: available.length - AVAILABLE_FOLD })} ·{" "}
          <button className="text-muted hover:text-ink" onClick={() => setShowAll(true)}>
            {tr("show all")}
          </button>
        </div>
      )}

      {connectingC && (
        <AddConnectionModal
          c={connectingC}
          cloud={cloud}
          onClose={() => setConnecting(null)}
          onChanged={onChanged}
          onOpenMemory={onOpenMemory}
        />
      )}
    </div>
  );
}

type Translator = (english: string, params?: TranslationParams) => string;

function statusLine(c: Connector, tr: Translator): string {
  if (c.name === "slack" && c.mode === "relay") {
    const n = c.workspaces?.length ?? 0;
    return `${tr(n === 1 ? "{count} workspace" : "{count} workspaces", { count: n })} · ${tr("relay")}`;
  }
  if ((c.accounts?.length ?? 0) > 1) return tr("{count} accounts", { count: c.accounts!.length });
  if ((c.portals?.length ?? 0) > 1) return tr("{count} portals", { count: c.portals!.length });
  if (c.auth === "local_app") {
    if (c.name === "codex" || c.name === "traex") {
      return c.account || tr("Local folder");
    }
    const version = c.app_version || c.account?.replace(/^MineM\s*/i, "");
    return version ? tr("Local app · {version}", { version }) : tr("Local app");
  }
  if (c.auth === "none") return tr("Built in");
  return c.account || tr("Connected");
}

function healthChip(c: Connector, slack: SlackStatus | null, tr: Translator) {
  // Slack relay gets a LIVE chip from /v1/connectors/slack/status — problems
  // surface in the list, never one click deep. Named honestly per layer; we
  // never claim "Slack↔cloud down" (the desktop can't see that leg).
  if (c.name === "slack" && c.mode === "relay" && slack) {
    if (!slack.signed_in) return <span className={CHIP_WARN}>{tr("● Sign-in needed")}</span>;
    if (slack.relay.state === "offline") return <span className={CHIP_OFF}>{tr("● Offline")}</span>;
    if (slack.relay.state === "reconnecting")
      return <span className={CHIP_WARN}>{tr("● Reconnecting")}</span>;
    if (Object.values(slack.teams).some((t) => !t.token_ok))
      return <span className={CHIP_WARN}>{tr("⚠ Token")}</span>;
    return <span className={CHIP_OK}>{tr("● Live")}</span>;
  }
  if (c.auth === "local_app") {
    if (c.name === "codex" || c.name === "traex") {
      return c.connected
        ? <span className={CHIP_OK}>{tr("● Ready")}</span>
        : <span className={CHIP_OFF}>{tr("● Not connected")}</span>;
    }
    return c.health === "running"
      ? <span className={CHIP_OK}>{tr("● Running")}</span>
      : <span className={CHIP_OFF}>{tr("● Stopped")}</span>;
  }
  if (c.two_way && c.connected) return <span className={CHIP_OK}>{tr("● Live")}</span>;
  return <span className={CHIP_OK}>{tr("● Ready")}</span>;
}
