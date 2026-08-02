import { useState } from "react";
import {
  connectManaged,
  disconnectGcalAccount,
  setGcalDefaultAccount,
  type GmailAccount,
} from "../../api";
import { ConnectorBadge } from "../../connectors/ConnectorIcon";
import type { DetailProps } from "./ConnectorsSection";
import { ToolsDisclosure } from "./ToolsDisclosure";
import { FOOT, GRP, GRP_H, PILL_ACCENT, ROW, TAG_ACCENT, TAG_WARN, XBTN } from "./ui";
import { useI18n } from "../../i18n";

// The Google Calendar detail page: connected accounts (multi-account, Default
// badge, per-account disconnect) — Gmail's page minus the privacy filters.
// Adding an account launches managed OAuth DIRECTLY (one connect mode, no modal).

export function CalendarDetail({ c, cloud, slack: _slack, onChanged }: DetailProps) {
  const { tr } = useI18n();
  const [busy, setBusy] = useState(false);
  const accounts = (c.accounts ?? []) as GmailAccount[]; // email-keyed (pre-generic-layer shape)

  const addAccount = async () => {
    setBusy(true);
    await connectManaged("google_calendar"); // completes in the system browser; the poll picks it up
    setTimeout(() => setBusy(false), 2500);
  };

  return (
    <div data-testid="gcal-detail">
      <div className="flex items-center gap-3.5 mb-5">
        <ConnectorBadge connector={c} size={44} title="Google Calendar" />
        <div className="min-w-0 flex-1">
          <h2 className="text-[20px] font-semibold tracking-tight leading-tight">
            Google Calendar
          </h2>
          <div className="text-[12.5px] text-muted flex items-center gap-1.5">
            {c.connected ? (
              <>
                <span className="w-2 h-2 rounded-full bg-ok" />
                <span data-testid="gcal-status">
                  {tr(accounts.length === 1 ? "{count} account" : "{count} accounts", { count: accounts.length })}
                </span>
              </>
            ) : (
              <span>{tr("Not connected")}</span>
            )}
          </div>
        </div>
        <button
          className={PILL_ACCENT + (c.managed_paused ? " opacity-50" : "")}
          data-testid="add-account-btn"
          onClick={addAccount}
          disabled={busy || !cloud?.signed_in || c.managed_paused}
          title={
            c.managed_paused
              ? tr("One-click Google sign-in is coming soon")
              : cloud?.signed_in
                ? ""
                : tr("Sign in to Link Cloud first")
          }
        >
          {c.managed_paused ? `＋ ${tr("Add account")} · ${tr("Coming soon")}` : busy ? tr("Check your browser…") : `＋ ${tr("Add account")}`}
        </button>
      </div>

      {!c.connected && (
        <div className={GRP}>
          <div className={ROW + " text-[12.5px] text-muted"}>
            {tr("Sign in with Google. Each account stays separate, and agents identify which one they use.")}
            {cloud?.signed_in ? "" : ` ${tr("Link Cloud sign-in is required.")}`}
          </div>
        </div>
      )}

      {accounts.length > 0 && (
        <>
          <div className={GRP_H + " !mt-0"}>{tr("Accounts")}</div>
          <div className={GRP} data-testid="gcal-accounts">
            {accounts.map((a) => (
              <AccountRow key={a.email} a={a} onChanged={onChanged} />
            ))}
          </div>
        </>
      )}

      <ToolsDisclosure c={c} onChanged={onChanged} />
      <div className={FOOT + " mt-2"}>
        {tr("Creating, changing, or deleting events always asks for approval and identifies the account.")}
      </div>
    </div>
  );
}

function AccountRow({ a, onChanged }: { a: GmailAccount; onChanged: () => void }) {
  const { tr } = useI18n();
  const [busy, setBusy] = useState(false);
  return (
    <div className={ROW} data-testid={`gcal-account-${a.email}`}>
      <span className="min-w-0 flex-1 flex items-center gap-2">
        <span className="text-[13px] font-medium truncate">{a.email}</span>
        {a.default && <span className={TAG_ACCENT}>{tr("Default")}</span>}
        {a.needs_reauth && <span className={TAG_WARN}>⚠ {tr("Sign in again")}</span>}
      </span>
      {!a.default && (
        <button
          className="text-[12px] text-muted hover:text-ink shrink-0"
          data-testid={`gcal-make-default-${a.email}`}
          onClick={async () => {
            await setGcalDefaultAccount(a.email);
            onChanged();
          }}
        >
          {tr("Make default")}
        </button>
      )}
      <button
        className={XBTN}
        title={tr("Disconnect this account")}
        data-testid={`gcal-disconnect-${a.email}`}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await disconnectGcalAccount(a.email);
          setBusy(false);
          onChanged();
        }}
      >
        ×
      </button>
    </div>
  );
}
