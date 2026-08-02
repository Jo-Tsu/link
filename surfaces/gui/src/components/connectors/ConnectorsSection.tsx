import { useEffect, useState } from "react";
import {
  disconnectConnector,
  getCloudStatus,
  getConnectors,
  getSlackStatus,
  syncCodex,
  syncTraex,
  type CloudStatus,
  type Connector,
  type SlackStatus,
} from "../../api";
import { ConnectorBadge } from "../../connectors/ConnectorIcon";
import { AllowlistBlock, ConnectorTools, ListeningSessionsBlock, UnauthorizedBlock } from "../ManageTabs";
import { AccountsDetail } from "./AccountsDetail";
import { AvailableDetail } from "./AvailableDetail";
import { CalendarDetail } from "./CalendarDetail";
import { ConnectorsList } from "./ConnectorsList";
import { GithubDetail } from "./GithubDetail";
import { GmailDetail } from "./GmailDetail";
import { HubSpotDetail } from "./HubSpotDetail";
import { SlackDetail } from "./SlackDetail";
import { GRP } from "./ui";
import { visibleConnectors } from "./visibility";
import { useI18n } from "../../i18n";

// Connectors surface = LIST ⇄ per-connector DETAIL SUBPAGE (UX-DECISIONS §21). The
// Integrations sub-nav never grows per-connector items; detail pages live behind a
// `‹ Connectors` breadcrumb. Connectors without a bespoke page get GenericDetail so
// every connected row navigates from day one.

export interface DetailProps {
  c: Connector;
  cloud: CloudStatus | null;
  slack: SlackStatus | null; // live Slack health (relay/sign-in/tokens); null elsewhere
  onChanged: () => void;
}

// Bespoke pages register here; everything else gets GenericDetail below.
const DETAIL_PAGES: Record<string, (p: DetailProps) => JSX.Element> = {
  slack: (p) => <SlackDetail {...p} />,
  gmail: (p) => <GmailDetail {...p} />,
  google_calendar: (p) => <CalendarDetail {...p} />,
  hubspot: (p) => <HubSpotDetail {...p} />,
  github: (p) => <GithubDetail {...p} />,
  // Generic multi-account connectors (accounts.py layer) share one page.
  notion: (p) => <AccountsDetail {...p} />,
  attio: (p) => <AccountsDetail {...p} />,
  posthog: (p) => <AccountsDetail {...p} />,
  mixpanel: (p) => <AccountsDetail {...p} />,
  amplitude: (p) => <AccountsDetail {...p} />,
  apollo: (p) => <AccountsDetail {...p} />,
  hunter: (p) => <AccountsDetail {...p} />,
};

export function ConnectorsSection() {
  const { tr } = useI18n();
  const [detail, setDetail] = useState<string | null>(null);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [cloud, setCloud] = useState<CloudStatus | null>(null);
  const [slack, setSlack] = useState<SlackStatus | null>(null);

  const refresh = () => {
    getConnectors()
      .then((rows) => setConnectors(visibleConnectors(rows)))
      .catch(() => setConnectors([]));
    getCloudStatus().then(setCloud).catch(() => setCloud(null));
    getSlackStatus().then(setSlack).catch(() => setSlack(null));
  };
  useEffect(() => {
    refresh();
    // Poll: recent senders/parked arrive over time; sign-in + managed connects finish
    // in the system browser and surface on the next tick.
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  if (detail) {
    const c = connectors.find((x) => x.name === detail);
    const Page = DETAIL_PAGES[detail];
    return (
      <div>
        <button
          className="text-[13px] text-accent mb-3"
          data-testid="connectors-breadcrumb"
          onClick={() => setDetail(null)}
        >
          ‹ {tr("Connectors")}
        </button>
        {!c ? (
          <div className="text-[13px] text-muted">{tr("Loading…")}</div>
        ) : !c.connected ? (
          /* Pre-connect page (§38). When a connect completes, the poll flips
             c.connected and this same route re-renders as the connected page. */
          <AvailableDetail c={c} cloud={cloud} onChanged={refresh} />
        ) : Page ? (
          <Page c={c} cloud={cloud} slack={slack} onChanged={refresh} />
        ) : (
          <GenericDetail
            c={c}
            cloud={cloud}
            slack={slack}
            onChanged={refresh}
            onGone={() => setDetail(null)}
          />
        )}
      </div>
    );
  }

  return (
    <ConnectorsList
      connectors={connectors}
      cloud={cloud}
      slack={slack}
      onOpen={setDetail}
      onChanged={refresh}
    />
  );
}

// Fallback detail page: status header + the connector's existing config blocks
// (tools; allow-list/parked/listening for two-way) + Disconnect. Bespoke pages
// (Slack/Gmail/HubSpot) replace this one connector at a time.
function LocalConversationImportBlock({ source }: { source: "codex" | "traex" }) {
  const { tr } = useI18n();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isTraex = source === "traex";

  const run = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = isTraex ? await syncTraex() : await syncCodex();
      setResult(
        tr("Imported {records} conversation records from {sessions} sessions.", {
          records: r.records_ingested,
          sessions: r.sessions_read,
        }),
      );
    } catch {
      setError(
        tr(isTraex ? "Could not import TRAE conversations." : "Could not import Codex conversations."),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={GRP + " mb-4"}>
      <div className="flex items-center justify-between gap-3 px-3.5 py-3">
        <div className="min-w-0">
          <div className="text-[13px] font-medium text-ink">{tr("Import conversations")}</div>
          <div className="text-[12px] text-muted mt-0.5">
            {tr(
              isTraex
                ? "Read your local TRAE CLI user sessions into memory source data. Internal subagent sessions are excluded."
                : "Read your local Codex sessions into memory source data. Safe to run again — only new conversations are added.",
            )}
          </div>
        </div>
        <button
          className="shrink-0 text-[12.5px] px-3 py-1.5 rounded-lg border border-accent/40 bg-accentSoft/25 text-accent hover:bg-accentSoft/40 disabled:opacity-60"
          onClick={run}
          disabled={busy}
          data-testid={`${source}-import`}
        >
          {busy ? tr("Importing…") : tr("Import conversations")}
        </button>
      </div>
      {result && <div className="px-3.5 pb-3 text-[12px] text-ok">{result}</div>}
      {error && <div className="px-3.5 pb-3 text-[12px] text-danger">{error}</div>}
    </div>
  );
}

function GenericDetail({
  c,
  cloud: _cloud,
  slack: _slack,
  onChanged,
  onGone,
}: DetailProps & { onGone: () => void }) {
  const { tr } = useI18n();
  return (
    <div>
      <div className="flex items-center gap-3.5 mb-5">
        <ConnectorBadge connector={c} size={44} title={c.title} />
        <div className="min-w-0 flex-1">
          <h2 className="text-[20px] font-semibold tracking-tight leading-tight">{c.title}</h2>
          <div className="text-[12.5px] text-muted flex items-center gap-1.5">
            <span className={"w-2 h-2 rounded-full " + (
              c.auth === "local_app" &&
              c.name !== "codex" &&
              c.name !== "traex" &&
              c.health !== "running"
                ? "bg-warnInk"
                : "bg-ok"
            )} />
            {c.auth === "local_app"
              ? (c.name === "codex" || c.name === "traex"
                  ? tr(c.name === "traex" ? "TRAE folder connected" : "Codex folder connected")
                  : tr(c.health === "running" ? "MineM is running" : "MineM will start when an agent needs it"))
              : c.account || tr(c.auth === "none" ? "Built in" : "Connected")}
          </div>
        </div>
        {c.auth !== "none" && (
          <button
            className="text-[12.5px] text-danger/80 hover:text-danger shrink-0"
            onClick={async () => {
              await disconnectConnector(c.name);
              onChanged();
              onGone();
            }}
          >
            {tr("Disconnect")}
          </button>
        )}
      </div>

      {(c.name === "codex" || c.name === "traex") && (
        <LocalConversationImportBlock source={c.name} />
      )}

      <div className={GRP}>
        <ConnectorTools c={c} onChanged={onChanged} />
      </div>

      {c.two_way && (
        <div className={GRP + " mt-4"}>
          <AllowlistBlock c={c} onChanged={onChanged} />
          <UnauthorizedBlock c={c} onChanged={onChanged} />
          {/* Channel subscriptions are a chat-platform concept — GitHub is two_way via the
              relay (inbound mentions) but has no channels. */}
          {c.channels && <ListeningSessionsBlock c={c} />}
        </div>
      )}
    </div>
  );
}
