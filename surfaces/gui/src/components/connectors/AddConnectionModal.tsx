import { useEffect, useState } from "react";
import {
  connectConnector,
  connectManaged,
  connectMcpBacked,
  getConnectors,
  syncCodex,
  syncTraex,
  type CloudStatus,
  type Connector,
} from "../../api";
import { ConnectorBadge } from "../../connectors/ConnectorIcon";
import { ConnectSetup } from "../ManageTabs";
import { InlineFeedback } from "../AsyncFeedback";
import { Icon } from "../Icon";
import { chooseFolder } from "../../tauri";
import { CloudSignInInline, CloudStatusPending } from "./CloudSignIn";
import { PILL_ACCENT, PILL_LINE, TAG_ACCENT } from "./ui";
import { useI18n } from "../../i18n";

// The ONE place a connection gets added (UX-DECISIONS §21): the detail page's header
// button (or the list's Connect pill) opens this sheet. Connectors with two connect
// modes get a One click | Manual pill switcher; single-mode connectors render their
// existing ConnectSetup directly (Gmail's managed flow skips the modal entirely).

const INPUT =
  "w-full px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";

export function AddConnectionModal({
  c,
  cloud,
  title,
  onClose,
  onChanged,
  onOpenMemory,
}: {
  c: Connector;
  cloud: CloudStatus | null;
  title?: string; // e.g. "Add a workspace" — defaults to "Connect {title}"
  onClose: () => void;
  onChanged: () => void;
  onOpenMemory?: () => void;
}) {
  const { tr } = useI18n();
  const [locked, setLocked] = useState(false);
  const localApp = c.auth === "local_app";
  // MCP-backed one-click (§42): local OAuth against the vendor's hosted MCP server —
  // with manual fields alongside (jira, asana) it's a second mode; alone (monday)
  // it IS the connect flow.
  const mcpBacked = !!c.mcp;
  const cloudManaged = cloud?.available === true;
  const twoModes =
    (cloudManaged &&
      (c.name === "slack" ||
        c.name === "hubspot" ||
        c.name === "github" ||
        c.name === "notion" ||
        c.name === "attio")) ||
    (mcpBacked && c.fields.length > 0);
  const [pane, setPane] = useState<"one" | "manual">(
    cloudManaged || mcpBacked ? "one" : "manual",
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !locked && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [locked, onClose]);

  return (
    <div className="fixed inset-0 z-40" data-testid="add-connection-modal">
      <div className="absolute inset-0 bg-black/30" onClick={() => !locked && onClose()} />
      <div
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[480px] max-w-[calc(100vw-2rem)] max-h-[calc(100vh-2rem)] overflow-y-auto hairline-scroll bg-panel rounded-lg border border-line shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label={title || tr("Connect {name}", { name: c.title })}
      >
        <div className="flex items-center gap-3 px-5 pt-5">
          <ConnectorBadge connector={c} size={34} title={c.title} />
          <div className="flex-1 font-semibold text-[16px] tracking-tight">
            {title || tr("Connect {name}", { name: c.title })}
          </div>
          <button
            className="grid h-8 w-8 place-items-center text-faint hover:text-ink"
            onClick={onClose}
            disabled={locked}
            title={tr("Close")}
            aria-label={tr("Close")}
          >
            <Icon name="x" size={16} />
          </button>
        </div>

        {localApp ? (
          <LocalAppConnect
            c={c}
            onChanged={onChanged}
            onClose={onClose}
            onBusyChange={setLocked}
            onOpenMemory={onOpenMemory}
          />
        ) : twoModes ? (
          <>
            <div className="px-5 pt-4">
              <div className="inline-flex rounded-full p-0.5 bg-paper text-[12.5px] font-medium">
                {(["one", "manual"] as const).map((p) => (
                  <button
                    key={p}
                    data-testid={`modal-pane-${p}`}
                    className={
                      "px-3.5 py-1 rounded-full " +
                      (pane === p ? "bg-panel shadow-sm text-ink border border-line" : "text-muted")
                    }
                    onClick={() => setPane(p)}
                  >
                    {tr(p === "one" ? "One click" : "Manual")}
                  </button>
                ))}
              </div>
            </div>
            {pane === "one" ? (
              mcpBacked ? (
                <McpOneClick c={c} onConnected={() => { onChanged(); onClose(); }} />
              ) : c.name === "hubspot" ? (
                <HubSpotOneClick c={c} cloud={cloud} />
              ) : c.name === "github" ? (
                <GithubOneClick c={c} cloud={cloud} />
              ) : c.name === "slack" ? (
                <SlackOneClick c={c} cloud={cloud} />
              ) : (
                <GenericOneClick c={c} cloud={cloud} />
              )
            ) : c.name === "slack" ? (
              <SlackManual onConnected={() => { onChanged(); onClose(); }} />
            ) : (
              <div className="px-1.5 pb-2">
                <ConnectSetup c={c} cloud={cloud} onConnected={() => { onChanged(); onClose(); }} manualOnly />
              </div>
            )}
          </>
        ) : mcpBacked ? (
          /* MCP-backed with no manual fields (monday): one-click IS the flow. */
          <McpOneClick c={c} onConnected={() => { onChanged(); onClose(); }} />
        ) : (
          <div className="px-1.5 pb-2">
            {/* Existing combined setup (managed button + manual fields) for everything else. */}
            <ConnectSetup
              c={c}
              cloud={cloud}
              onConnected={() => { onChanged(); onClose(); }}
              manualOnly={!cloudManaged}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function LocalAppConnect({
  c,
  onChanged,
  onClose,
  onBusyChange,
  onOpenMemory,
}: {
  c: Connector;
  onChanged: () => void;
  onClose: () => void;
  onBusyChange: (busy: boolean) => void;
  onOpenMemory?: () => void;
}) {
  // Conversation sources aren't launchable apps — they are local folders the user grants.
  if (c.name === "codex" || c.name === "traex") {
    return (
      <LocalConversationConnect
        c={c}
        onChanged={onChanged}
        onClose={onClose}
        onBusyChange={onBusyChange}
        onOpenMemory={onOpenMemory}
      />
    );
  }

  const { tr } = useI18n();
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const go = async () => {
    setWaiting(true);
    onBusyChange(true);
    setError(null);
    try {
      const result = await connectConnector(c.name, {});
      if (!result.ok) {
        setError(result.error || tr("Could not launch or connect {name}.", { name: c.title }));
        return;
      }
      onChanged();
      onClose();
    } catch {
      setError(tr("Could not launch or connect {name}.", { name: c.title }));
    } finally {
      setWaiting(false);
      onBusyChange(false);
    }
  };

  return (
    <div className="px-5 py-4 space-y-3">
      <p className="text-[13px] text-muted leading-relaxed">
        {tr("Smallink will launch the installed {name} app and verify its local CLI. No token or cloud account is required.", {
          name: c.title,
        })}
      </p>
      <button
        className={PILL_ACCENT + " w-full !py-2"}
        data-testid="modal-local-app-connect"
        onClick={go}
        disabled={waiting}
      >
        {waiting ? tr("Launching {name}…", { name: c.title }) : tr("Launch and connect {name}", { name: c.title })}
      </button>
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-faint text-center">
        {tr("Smallink uses {name}'s public CLI. It does not read the app database directly.", {
          name: c.title,
        })}
      </p>
    </div>
  );
}

// Local conversation import: folder selection grants macOS access, then Smallink persists the
// normalized session path and imports user-owned conversation turns.
type LocalConversationPhase = "idle" | "choosing" | "authorizing" | "importing" | "complete" | "partial";

function LocalConversationConnect({
  c,
  onChanged,
  onClose,
  onBusyChange,
  onOpenMemory,
}: {
  c: Connector;
  onChanged: () => void;
  onClose: () => void;
  onBusyChange: (busy: boolean) => void;
  onOpenMemory?: () => void;
}) {
  const { tr } = useI18n();
  const [phase, setPhase] = useState<LocalConversationPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ sessions: number; records: number } | null>(null);
  const isTraex = c.name === "traex";

  const setBusy = (busy: boolean) => {
    onBusyChange(busy);
  };

  const importConversations = async () => {
    setPhase("importing");
    setBusy(true);
    setError(null);
    try {
      const imported = isTraex ? await syncTraex() : await syncCodex();
      setResult({ sessions: imported.sessions_read, records: imported.records_ingested });
      setPhase("complete");
      onChanged();
    } catch {
      setPhase("partial");
      setError(
        tr(isTraex ? "Could not import TRAE conversations." : "Could not import Codex conversations."),
      );
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const go = async () => {
    let authorized = false;
    setError(null);
    setResult(null);
    setPhase("choosing");
    setBusy(true);
    try {
      const picked = await chooseFolder();
      if (!picked) {
        setPhase("idle");
        return;
      }
      setPhase("authorizing");
      const result = await connectConnector(c.name, { sessions_path: picked });
      if (!result.ok) {
        setError(result.error || tr("Could not connect {name}.", { name: c.title }));
        setPhase("idle");
        return;
      }
      authorized = true;
    } catch {
      setError(tr("Could not connect {name}.", { name: c.title }));
      setPhase("idle");
    } finally {
      if (!authorized) setBusy(false);
    }
    if (authorized) {
      await importConversations();
    }
  };

  const waiting = phase === "choosing" || phase === "authorizing" || phase === "importing";
  const progress =
    phase === "choosing"
      ? tr("Waiting for folder selection…")
      : phase === "authorizing"
        ? tr(isTraex ? "Authorizing TRAE folder…" : "Authorizing Codex folder…")
        : phase === "importing"
          ? tr(isTraex ? "Importing TRAE conversations…" : "Importing Codex conversations…")
          : "";

  return (
    <div className="px-5 py-4 space-y-3">
      <p className="text-[13px] text-muted leading-relaxed">
        {tr(
          isTraex
            ? "Choose your TRAE folder (usually ~/.trae). Smallink imports user conversations and excludes internal subagent sessions. Nothing is uploaded."
            : "Choose your Codex folder (usually ~/.codex). Smallink reads its local session files to import your conversation history. Nothing is uploaded.",
        )}
      </p>
      <button
        className={PILL_ACCENT + " w-full !py-2"}
        data-testid={`modal-${c.name}-connect`}
        onClick={go}
        disabled={waiting || phase === "complete" || phase === "partial"}
      >
        {waiting ? tr("Connecting and importing…") : tr(isTraex ? "Authorize and import TRAE" : "Authorize and import Codex")}
      </button>
      {progress && (
        <InlineFeedback tone="info" title={progress} body={tr("Keep this window open until the step finishes.")} />
      )}
      {phase === "complete" && result && (
        <InlineFeedback
          tone="success"
          title={result.records > 0 ? tr("Import complete") : tr("Already up to date")}
          body={tr("Imported {records} conversation records from {sessions} sessions.", {
            records: result.records,
            sessions: result.sessions,
          })}
        />
      )}
      {phase === "partial" && (
        <InlineFeedback
          tone="warning"
          title={tr("{name} is connected, but import did not finish.", { name: c.title })}
          body={error || tr("Could not import conversations")}
          action={tr("Retry import")}
          onAction={() => void importConversations()}
        />
      )}
      {error && phase === "idle" && (
        <InlineFeedback tone="danger" title={tr("Could not connect {name}.", { name: c.title })} body={error} />
      )}
      <p className="text-[12px] text-faint text-center">
        {tr("One action grants folder access, connects {name}, and imports new conversations.", {
          name: c.title,
        })}
      </p>
      {(phase === "complete" || phase === "partial") && (
        <div className="flex items-center justify-end gap-2 pt-1">
          {phase === "complete" && onOpenMemory && (
            <button
              type="button"
              className={PILL_LINE}
              onClick={() => {
                onClose();
                onOpenMemory();
              }}
            >
              {tr("View memory data")}
            </button>
          )}
          <button type="button" className={PILL_ACCENT} onClick={onClose}>
            {tr("Done")}
          </button>
        </div>
      )}
    </div>
  );
}

// One-click pane for MCP-BACKED connectors (monday, asana, jira — §42): the sidecar
// runs a fully LOCAL OAuth flow against the vendor's hosted MCP server (DCR — no
// client secret, no broker, no Link sign-in required). Poll until the card
// flips to connected, then close.
function McpOneClick({ c, onConnected }: { c: Connector; onConnected: () => void }) {
  const { tr } = useI18n();
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(async () => {
      try {
        const list = await getConnectors();
        if (list.find((x) => x.name === c.name)?.connected) onConnected();
      } catch {
        /* keep polling */
      }
    }, 2000);
    return () => clearInterval(t);
  }, [waiting, c.name, onConnected]);
  const go = async () => {
    setError(null);
    const res = await connectMcpBacked(c.name);
    if (res.ok) setWaiting(true);
    else setError(res.error || tr("Could not start the connection."));
  };
  return (
    <div className="px-5 py-4 space-y-3">
      <p className="text-[13px] text-muted">
        {tr("Open {name} in your browser, then sign in and approve access. No token entry or Link account is required; the sign-in runs on this computer.", {
          name: c.title,
        })}
      </p>
      <button
        className={PILL_ACCENT + " w-full !py-2"}
        data-testid="modal-mcp-one-click"
        onClick={go}
        disabled={waiting}
      >
        {waiting ? tr("Check your browser…") : tr("Connect {name}", { name: c.title })}
      </button>
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-faint text-center flex items-center justify-center gap-1.5">
        <span className={TAG_ACCENT}>{tr("Recommended")}</span>{" "}
        {tr("Agents receive a curated set of {name} tools. Tokens stay on this computer.", { name: c.title })}
      </p>
    </div>
  );
}

// One-click pane for generic managed connectors (Notion, Attio, …): sign in
// with the service in the browser; each consent lands as its own account.
function GenericOneClick({ c, cloud }: { c: Connector; cloud: CloudStatus | null }) {
  const { tr } = useI18n();
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setError(null);
    const res = await connectManaged(c.name);
    if (res.ok) setWaiting(true);
    else setError(res.error || tr("Could not start the connection."));
  };
  return (
    <div className="px-5 py-4 space-y-3">
      <p className="text-[13px] text-muted">
        {tr("Open {name} in your browser and approve access. No token entry is required; connect again to add another account.", {
          name: c.title,
        })}
      </p>
      {cloud?.signed_in ? (
        <button
          className={PILL_ACCENT + " w-full !py-2"}
          data-testid="modal-generic-one-click"
          onClick={go}
          disabled={waiting}
        >
          {waiting ? tr("Check your browser…") : tr("Connect {name}", { name: c.title })}
        </button>
      ) : cloud ? (
        <CloudSignInInline />
      ) : (
        <CloudStatusPending />
      )}
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-faint text-center flex items-center justify-center gap-1.5">
        <span className={TAG_ACCENT}>{tr("Recommended")}</span> {tr("Tokens stay on this computer.")}
      </p>
    </div>
  );
}

function SlackOneClick({ c, cloud }: { c: Connector; cloud: CloudStatus | null }) {
  const { tr } = useI18n();
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setError(null);
    const res = await connectManaged(c.name);
    if (res.ok) setWaiting(true);
    else setError(res.error || tr("Could not start the installation."));
  };
  return (
    <div className="px-5 py-4 space-y-3">
      <p className="text-[13px] text-muted">
        {tr("Open Slack in your browser and approve @Link for the workspace. No token entry is required, and you can connect multiple workspaces.")}
      </p>
      {cloud?.signed_in ? (
        <button className={PILL_ACCENT + " w-full !py-2"} data-testid="modal-add-to-slack" onClick={go} disabled={waiting}>
          {waiting ? tr("Check your browser…") : tr("Add to Slack")}
        </button>
      ) : cloud ? (
        <CloudSignInInline />
      ) : (
        <CloudStatusPending />
      )}
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-faint text-center flex items-center justify-center gap-1.5">
        <span className={TAG_ACCENT}>{tr("Recommended")}</span> {tr("Relay mode · tokens stay on this computer")}
      </p>
    </div>
  );
}

function GithubOneClick({ c, cloud }: { c: Connector; cloud: CloudStatus | null }) {
  const { tr } = useI18n();
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setError(null);
    const res = await connectManaged(c.name);
    if (res.ok) setWaiting(true);
    else setError(res.error || tr("Could not start the installation."));
  };
  return (
    <div className="px-5 py-4 space-y-3">
      <p className="text-[13px] text-muted">
        {tr("Open GitHub in your browser and approve Link. Choose the account and repositories to connect; no token entry is required.")}
      </p>
      {cloud?.signed_in ? (
        /* One button: the broker is authorize-first — it links an existing installation or
           redirects the same tab on to the install page (the old "Already installed? Link
           it" question and the Configure dead-end are gone). */
        <button className={PILL_ACCENT + " w-full !py-2"} data-testid="modal-install-github-app" onClick={() => go()} disabled={waiting}>
          {waiting ? tr("Check your browser…") : tr("Connect GitHub")}
        </button>
      ) : cloud ? (
        <CloudSignInInline />
      ) : (
        <CloudStatusPending />
      )}
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-faint text-center flex items-center justify-center gap-1.5">
        <span className={TAG_ACCENT}>{tr("Recommended")}</span> {tr("Relay mode · short-lived tokens are never stored")}
      </p>
    </div>
  );
}

function HubSpotOneClick({ c, cloud }: { c: Connector; cloud: CloudStatus | null }) {
  const { tr } = useI18n();
  const [access, setAccess] = useState<"read" | "write">("read");
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setError(null);
    const res = await connectManaged(c.name, { access });
    if (res.ok) setWaiting(true);
    else setError(res.error || tr("Could not start the connection."));
  };
  return (
    <div className="px-5 py-4 space-y-3">
      <p className="text-[13px] text-muted">
        {tr("Open HubSpot in your browser and choose a portal. Select what agents may do before granting access:")}
      </p>
      <div className="space-y-1.5" data-testid="hubspot-access">
        {(
          [
            ["read", "Read-only", "search and read contacts, companies, deals, tickets"],
            ["write", "Read & write", "adds: log notes and tasks, update records, create contacts — never delete"],
          ] as const
        ).map(([value, label, blurb]) => (
          <label key={value} className="flex items-start gap-2 text-[13px] cursor-pointer">
            <input
              type="radio"
              name="hubspot-access"
              className="mt-0.5"
              checked={access === value}
              data-testid={`hubspot-access-${value}`}
              onChange={() => setAccess(value)}
            />
            <span>
              <span className="font-medium">{tr(label)}</span>
              <span className="block text-[12px] text-muted">{tr(blurb)}</span>
            </span>
          </label>
        ))}
      </div>
      {cloud?.signed_in ? (
        <button className={PILL_ACCENT + " w-full !py-2"} data-testid="modal-connect-hubspot" onClick={go} disabled={waiting}>
          {waiting ? tr("Check your browser…") : tr("Connect HubSpot")}
        </button>
      ) : cloud ? (
        <CloudSignInInline />
      ) : (
        <CloudStatusPending />
      )}
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-faint text-center">
        {tr("Connect multiple portals · tokens stay on this computer")}
      </p>
    </div>
  );
}

function SlackManual({ onConnected }: { onConnected: () => void }) {
  const { tr } = useI18n();
  const [bot, setBot] = useState("");
  const [app, setApp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    const res = await connectConnector("slack", { bot_token: bot.trim(), app_token: app.trim() });
    setBusy(false);
    if (res.ok) onConnected();
    else setError(res.error || tr("Could not connect."));
  };
  return (
    <div className="px-5 py-4 space-y-3">
      <ol className="list-decimal pl-4 text-[13px] text-muted space-y-1">
        <li>{tr("Create an app at api.slack.com/apps")}</li>
        <li>{tr("Enable Socket Mode, add bot scopes, and install it to your workspace")}</li>
        <li>{tr("Paste both tokens below")}</li>
      </ol>
      <input
        className={INPUT}
        type="password"
        placeholder={tr("Bot token · xoxb-…")}
        value={bot}
        spellCheck={false}
        onChange={(e) => setBot(e.target.value)}
      />
      <input
        className={INPUT}
        type="password"
        placeholder={tr("App token · xapp-…")}
        value={app}
        spellCheck={false}
        onChange={(e) => setApp(e.target.value)}
      />
      <button className={PILL_LINE + " w-full !py-2"} onClick={submit} disabled={busy || !bot.trim() || !app.trim()}>
        {busy ? tr("Validating…") : tr("Connect")}
      </button>
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
      <p className="text-[12px] text-warnInk text-center">
        {tr("Only one Slack mode can run at a time. Manual mode pauses relay workspaces.")}
      </p>
    </div>
  );
}
