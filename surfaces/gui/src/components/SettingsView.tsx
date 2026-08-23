import { useEffect, useState } from "react";
import {
  getSettings,
  getConnectors,
  getSensoryStats,
  deleteSensoryRecords,
  getMemory,
  archiveMemory,
  getTrustedWorkspaces,
  setOnboarded,
  setPdfSettings,
  setScratchBase,
  setSessionsPeek,
  setWorkspaceTrusted,
  type ModelSettings,
  type PdfSettings,
  type WorkspaceCommandTrust,
} from "../api";
import {
  cancelDictationModelDownload,
  deleteDictationModel,
  downloadDictationModel,
  getAutostart,
  getDictationStatus,
  getKeepAwake,
  isTauri,
  listenDictationDownloadProgress,
  markDictationTestPassed,
  pickFolder,
  setAutostart,
  setKeepAwake,
  startDictation,
  stopDictation,
  verifyDictationModel,
  type DictationDownloadProgress,
  type DictationStatus,
} from "../tauri";
import { useThemePref } from "../theme";
import { Icon } from "./Icon";
import { PanelHead } from "./IntegrationsView";
import { ModelsTab } from "./ManageTabs";
import { GalleryModal } from "./GalleryModal";
import { PersonasTab } from "./PersonasTab";
import { showPersonas } from "../flags";
import { useI18n } from "../i18n";
import { ConfirmDialog } from "./ConfirmDialog";

// Settings, restructured (Option 2) into a full-page surface that mirrors IntegrationsView's shell:
// a left sub-nav (Appearance · Files · Models · Personas) + centered panel, replacing the old
// top-tab ManageModal. Local/app concerns live here; anything external (Connectors, Messaging, MCP,
// Activity) stays under Integrations. Appearance + Files are re-skinned to the mock's Tailwind idiom;
// Models + Personas host the existing tab components inside the page shell (field re-skin to follow).
// "appearance" is the General tab's stable key — callers deep-link with it, so the
// rename (UX-021) changed only the label. "files" folded into General as a card.
type SetTab = "appearance" | "models" | "voice" | "personas" | "privacy";

const CARD = "rounded-lg border border-line bg-panel";
const FIELD_LABEL = "text-[12.5px] font-medium text-ink";
const FIELD_HELP = "text-[12px] text-muted mt-1.5 leading-relaxed";
const INPUT =
  "flex-1 min-w-0 px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";
const BTN_ACCENT = "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-onAccent shrink-0 disabled:opacity-40";
const BTN_BORDERED =
  "text-[12.5px] px-3 py-2 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0";

const SET_TABS: { key: SetTab; label: string; icon: "sliders" | "code" | "mic" | "sparkle" | "shield" }[] = [
  { key: "appearance", label: "General", icon: "sliders" },
  { key: "models", label: "Models", icon: "code" },
  { key: "voice", label: "Voice input", icon: "mic" },
  { key: "personas", label: "Personas", icon: "sparkle" },
  { key: "privacy", label: "Privacy", icon: "shield" },
];

export function SettingsView({
  initialTab,
  onOpenPersona,
}: {
  initialTab?: SetTab;
  onOpenPersona?: (id: string) => void;
}) {
  const { t, tr } = useI18n();
  // Personas is flag-gated (hidden for launch) — filter the tab AND coerce a stale
  // deep-link to it (openSettings("personas") callers) so the page never opens on a
  // section with no nav entry.
  const personas = showPersonas();
  const tabs = personas ? SET_TABS : SET_TABS.filter((t) => t.key !== "personas");
  const wanted = initialTab && (personas || initialTab !== "personas") ? initialTab : "appearance";
  const [tab, setTab] = useState<SetTab>(wanted);

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <nav className="page-subnav w-[208px] shrink-0 border-r border-line bg-panel/40 px-3 py-4">
        <div className="px-2 text-[13.5px] font-semibold mb-3 flex items-center gap-2">
          <Icon name="gear" size={16} /> {t("settings.title")}
        </div>
        {tabs.map((item) => {
          const active = tab === item.key;
          return (
            <button
              key={item.key}
              className={
                "w-full text-left px-2.5 py-2 rounded-lg text-[13px] flex items-center gap-2 " +
                (active ? "bg-paper text-accent font-medium" : "text-muted hover:bg-paper hover:text-ink")
              }
              onClick={() => setTab(item.key)}
            >
              <Icon name={item.icon} size={15} />{" "}
              {item.key === "appearance"
                ? t("settings.general")
                : item.key === "models"
                  ? t("settings.models")
                  : item.key === "voice"
                    ? t("settings.voice")
                    : item.key === "privacy"
                      ? t("settings.privacy")
                      : t("settings.personas")}
            </button>
          );
        })}
      </nav>

      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-3xl mx-auto px-7 py-6">
          {tab === "appearance" ? (
            <AppearanceSection />
          ) : tab === "models" ? (
            <section>
              <PanelHead
                title={tr("Models")}
                sub={tr("Configure the AI providers and models available to Smallink. API keys stay on this computer.")}
              />
              <ModelsTab />
              {/* Token savings is model-spend behavior, so it lives here (UX-021),
                  not under General. */}
              <div className="mt-6">
                <TokenSavingsCard />
              </div>
            </section>
          ) : tab === "voice" ? (
            <VoiceInputSection />
          ) : tab === "privacy" ? (
            <PrivacySection />
          ) : (
            <PersonasSection onOpenPersona={onOpenPersona} />
          )}
        </div>
      </div>
    </main>
  );
}

// -- Voice input: deliberate model provisioning + compatibility + microphone test (§37) --------
const voiceError = (error: unknown) =>
  error instanceof Error ? error.message : typeof error === "string" ? error : "Voice Input could not complete that action.";

const formatBytes = (bytes: number) => {
  if (!bytes) return "0 MiB";
  return `${Math.round(bytes / 1024 / 1024)} MiB`;
};

function VoiceInputSection() {
  const { tr } = useI18n();
  const [status, setStatus] = useState<DictationStatus | null>(null);
  const [progress, setProgress] = useState<DictationDownloadProgress | null>(null);
  const [phase, setPhase] = useState<"idle" | "downloading" | "verifying" | "testing" | "transcribing">("idle");
  const [error, setError] = useState<string | null>(null);
  const [testTranscript, setTestTranscript] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const desktop = isTauri();

  const publish = (next: DictationStatus) => {
    setStatus(next);
    window.dispatchEvent(new CustomEvent("link:voice-input-changed", { detail: next }));
  };

  useEffect(() => {
    if (!desktop) return;
    let active = true;
    let unlisten = () => {};
    void listenDictationDownloadProgress((next) => {
      if (active) setProgress(next);
    }).then((stop) => {
      unlisten = stop;
    });
    void getDictationStatus().then(async (initial) => {
      if (!active || !initial) return;
      publish(initial);
      // One-time migration for models installed by the first STT cut, before verification markers.
      if (initial.model_installed && !initial.model_verified) {
        setPhase("verifying");
        try {
          const verified = await verifyDictationModel();
          if (active) publish(verified);
        } catch (verifyError) {
          if (active) setError(voiceError(verifyError));
        } finally {
          if (active) setPhase("idle");
        }
      }
    });
    return () => {
      active = false;
      unlisten();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktop]);

  const download = async () => {
    setError(null);
    setProgress({ downloaded_bytes: 0, total_bytes: status?.model_bytes || 0 });
    setPhase("downloading");
    try {
      publish(await downloadDictationModel());
    } catch (downloadError) {
      setError(voiceError(downloadError));
      const latest = await getDictationStatus();
      if (latest) publish(latest);
    } finally {
      setPhase("idle");
    }
  };

  const cancelDownload = async () => {
    await cancelDictationModelDownload().catch(() => undefined);
  };

  const repair = async () => {
    setError(null);
    try {
      publish(await deleteDictationModel());
      await download();
    } catch (repairError) {
      setError(voiceError(repairError));
    }
  };

  const remove = async () => {
    setError(null);
    try {
      publish(await deleteDictationModel());
      setTestTranscript("");
      setProgress(null);
    } catch (deleteError) {
      setError(voiceError(deleteError));
    } finally {
      setConfirmRemove(false);
    }
  };

  const toggleTest = async () => {
    if (!status?.supported || !status.model_verified) return;
    setError(null);
    try {
      if (status.recording) {
        setPhase("transcribing");
        const transcript = (await stopDictation()).trim();
        setTestTranscript(transcript);
        if (!transcript) throw new Error(tr("No speech was detected. Try again and speak for a little longer."));
        publish(await markDictationTestPassed());
      } else {
        setTestTranscript("");
        setPhase("testing");
        publish(await startDictation());
      }
    } catch (testError) {
      setError(voiceError(testError));
      const latest = await getDictationStatus();
      if (latest) publish(latest);
    } finally {
      setPhase("idle");
    }
  };

  const downloading = phase === "downloading" || !!status?.download_in_progress;
  const progressTotal = progress?.total_bytes || status?.model_bytes || 1;
  const progressPercent = Math.min(100, Math.round(((progress?.downloaded_bytes || 0) / progressTotal) * 100));
  const ready = !!status?.supported && !!status?.model_verified && !!status?.test_passed;

  return (
    <section>
      <PanelHead
        title={tr("Voice input")}
        sub={tr("Speak naturally in the composer. Recordings and transcripts stay on this device.")}
      />

      {!desktop ? (
        <div className={CARD + " p-4 text-[13px] text-muted"}>{tr("Voice input setup is available in the Smallink desktop app.")}</div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-lg border border-okLine bg-okSoft px-4 py-3 text-[12.5px] text-ok">
            <span className="font-medium">{tr("Private by design.")}</span>{" "}
            {tr("Audio is held in memory only while you record and is transcribed locally.")}
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-start gap-3">
              <Icon name="code" size={18} className="text-accent mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium">{tr("This device")}</div>
                <div className="text-[12px] text-muted mt-1">{status?.device_summary || tr("Checking compatibility…")}</div>
                {status?.compatibility_reason && <div className="text-[12px] text-danger mt-1.5">{status.compatibility_reason}</div>}
              </div>
              {status && (
                <span className={"text-[11.5px] px-2 py-1 rounded-full " + (status.supported ? "bg-okSoft text-ok" : "bg-dangerSoft text-danger")}>
                  {status.supported ? tr("● Compatible") : tr("Unsupported")}
                </span>
              )}
            </div>
            <div className="border-t border-line bg-paper/50 px-4 py-3 grid grid-cols-2 gap-3 text-[12px] text-muted">
              <div><span className="block text-ink font-medium">Mac</span>macOS 12+ · Apple Silicon M1+</div>
              <div><span className="block text-ink font-medium">Windows</span>Windows 10 22H2/11 · x64</div>
              <div><span className="block text-ink font-medium">{tr("Memory")}</span>{tr("8 GB recommended")}</div>
              <div><span className="block text-ink font-medium">{tr("Processor")}</span>{tr("4 CPU cores recommended")}</div>
            </div>
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-accentSoft text-accent grid place-items-center font-semibold">W</div>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium">{tr("Whisper Base · English")}</div>
                <div className="text-[12px] text-muted mt-0.5">
                  {status?.model_verified
                    ? tr("Installed and verified · {size}", { size: formatBytes(status.model_bytes) })
                    : tr("Local voice model · {size}", { size: formatBytes(status?.model_bytes || 147_964_211) })}
                </div>
              </div>
              {status?.model_verified ? (
                <>
                  <span className="text-[11.5px] px-2 py-1 rounded-full bg-okSoft text-ok">{tr("Verified")}</span>
                  <button className={BTN_BORDERED} onClick={() => void repair()}>{tr("Repair")}</button>
                  <button className="text-[12px] text-danger px-2 py-2" onClick={() => setConfirmRemove(true)}>{tr("Delete")}</button>
                </>
              ) : downloading ? (
                <button className={BTN_BORDERED} onClick={() => void cancelDownload()}>{tr("Cancel")}</button>
              ) : phase === "verifying" ? (
                <span className="text-[12px] text-muted">{tr("Verifying…")}</span>
              ) : (
                <button className={BTN_ACCENT} disabled={!status?.supported} onClick={() => void download()}>{tr("Download model")}</button>
              )}
            </div>
            {downloading && (
              <div className="border-t border-line px-4 py-3">
                <div className="h-1.5 rounded-full bg-line overflow-hidden"><div className="h-full bg-accent transition-all" style={{ width: `${progressPercent}%` }} /></div>
                <div className="mt-1.5 text-[11.5px] text-muted flex"><span>{tr("{current} of {total}", { current: formatBytes(progress?.downloaded_bytes || 0), total: formatBytes(progressTotal) })}</span><span className="ml-auto">{progressPercent}%</span></div>
              </div>
            )}
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-center gap-3">
              <Icon name="mic" size={18} className={ready ? "text-ok" : "text-muted"} />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium">{tr("Microphone test")}</div>
                <div className="text-[12px] text-muted mt-0.5">
                  {ready
                    ? tr("Your microphone and local transcription engine are working.")
                    : tr("Record a short phrase to enable the composer microphone.")}
                </div>
              </div>
              {ready && <span className="text-[11.5px] px-2 py-1 rounded-full bg-okSoft text-ok">{tr("● Ready")}</span>}
              <button className={BTN_BORDERED} disabled={!status?.supported || !status?.model_verified || phase === "transcribing"} onClick={() => void toggleTest()}>
                {status?.recording
                  ? tr("Stop and check")
                  : phase === "transcribing"
                    ? tr("Transcribing…")
                    : ready
                      ? tr("Test again")
                      : tr("Test microphone")}
              </button>
            </div>
            {status?.recording && <div className="border-t border-line px-4 py-3 text-[12px] text-accent" role="status">{tr("● Listening… speak a short phrase, then stop.")}</div>}
            {testTranscript && <div className="border-t border-line bg-paper/50 px-4 py-3 text-[13px]">“{testTranscript}”</div>}
          </div>

          {error && <div role="alert" className="rounded-lg border border-danger/30 bg-dangerSoft px-3 py-2.5 text-[12px] text-danger">{error}</div>}
          {confirmRemove && (
            <ConfirmDialog
              title={tr("Delete the local Whisper model and disable voice input?")}
              body={tr("You can download and verify the model again later.")}
              confirmLabel={tr("Delete")}
              danger
              busy={phase !== "idle"}
              onCancel={() => setConfirmRemove(false)}
              onConfirm={() => void remove()}
            />
          )}
        </div>
      )}
    </section>
  );
}

// -- Personas: installed/enabled/delete management, the dir/Git importer, and the
// entry point to the Persona Gallery (a screen-sized modal — installs finish back
// here, disabled pending consent; a gallery install re-mounts the list in place).
function PersonasSection({ onOpenPersona }: { onOpenPersona?: (id: string) => void }) {
  const { tr } = useI18n();
  const [galleryBump, setGalleryBump] = useState(0);
  const [galleryOpen, setGalleryOpen] = useState(false);

  return (
    <section>
      <PanelHead
        title={tr("Agents")}
        sub={tr("Manage the agents shown in the picker and install new agent bundles.")}
      />
      <PersonasTab key={galleryBump} onOpenPersona={onOpenPersona} />
      <button
        className="mt-6 w-full rounded-lg border border-line bg-panel px-4 py-3.5 flex items-center gap-3 text-left hover:border-lineStrong"
        data-testid="gallery-link"
        onClick={() => setGalleryOpen(true)}
      >
        <Icon name="sparkle" size={16} className="text-accent shrink-0" />
        <span className="min-w-0 flex-1">
          <span className="block text-[13.5px] font-medium">{tr("Browse the Agent Gallery")}</span>
          <span className="block text-[12px] text-muted">
            {tr("Curated agents from the Smallink team — see what each can do before installing.")}
          </span>
        </span>
        <span className="text-[12.5px] text-accent shrink-0">{tr("Open")} →</span>
      </button>
      {galleryOpen && (
        <GalleryModal
          onClose={() => setGalleryOpen(false)}
          onInstalled={() => setGalleryBump((b) => b + 1)}
        />
      )}
    </section>
  );
}

// -- Appearance + app behaviour ------------------------------------------------
function AppearanceSection() {
  const { language, setLanguage, t } = useI18n();
  const [theme, setTheme] = useThemePref();
  const [autostart, setAuto] = useState(false);
  const [keepAwake, setKeep] = useState(false);
  const desktop = isTauri();

  useEffect(() => {
    if (isTauri()) {
      getAutostart().then((v) => setAuto(!!v));
      getKeepAwake().then((v) => setKeep(!!v));
    }
  }, []);

  const toggleAuto = async (v: boolean) => setAuto(!!(await setAutostart(v)));
  const toggleKeep = async (v: boolean) => setKeep(!!(await setKeepAwake(v)));
  const runSetupAgain = async () => {
    await setOnboarded(false);
    window.dispatchEvent(new CustomEvent("link:open-onboarding"));
  };

  return (
    <section>
      <PanelHead title={t("settings.general")} sub={t("settings.generalSub")} />

      <div className={CARD + " p-4 mb-4"} data-testid="language-setting">
        <div className={FIELD_LABEL}>{t("language.name")}</div>
        <div className="seg mt-2.5" role="radiogroup" aria-label={t("language.name")}>
          <button
            className={language === "zh-CN" ? "active" : ""}
            onClick={() => setLanguage("zh-CN")}
          >
            {t("language.chinese")}
          </button>
          <button
            className={language === "en" ? "active" : ""}
            onClick={() => setLanguage("en")}
          >
            {t("language.english")}
          </button>
        </div>
        <div className={FIELD_HELP}>{t("language.help")}</div>
      </div>

      <div className={CARD + " p-4 mb-4"}>
        <div className={FIELD_LABEL}>{t("settings.theme")}</div>
        <div className="seg mt-2.5" role="radiogroup" aria-label={t("settings.theme")}>
          {(["light", "dark", "auto"] as const).map((p) => (
            <button key={p} className={p === theme ? "active" : ""} onClick={() => setTheme(p)}>
              {p === "light"
                ? t("settings.light")
                : p === "dark"
                  ? t("settings.dark")
                  : t("settings.auto")}
            </button>
          ))}
        </div>
        <div className={FIELD_HELP}>{t("settings.themeHelp")}</div>
      </div>

      <SidebarCard />

      <FilesCard />

      <TrustedWorkspacesCard />

      {desktop && (
        <div className={CARD + " p-4"}>
          <div className={FIELD_LABEL + " mb-2.5"}>{t("settings.alwaysOn")}</div>
          <label className="flex items-start gap-3 py-2">
            <input type="checkbox" className="mt-0.5" checked={autostart} onChange={(e) => toggleAuto(e.target.checked)} />
            <span>
              <span className="block text-[13px] text-ink">{t("settings.openAtLogin")}</span>
              <span className="block text-[12px] text-muted">{t("settings.openAtLoginHelp")}</span>
            </span>
          </label>
          <label className="flex items-start gap-3 py-2">
            <input type="checkbox" className="mt-0.5" checked={keepAwake} onChange={(e) => toggleKeep(e.target.checked)} />
            <span>
              <span className="block text-[13px] text-ink">{t("settings.keepAwake")}</span>
              <span className="block text-[12px] text-muted">{t("settings.keepAwakeHelp")}</span>
            </span>
          </label>
        </div>
      )}

      {/* App lifecycle actions available in every build. */}
      <div className={CARD + " p-4 mt-4"}>
        <div className={FIELD_LABEL + " mb-2"}>{t("settings.setup")}</div>
        <div className="flex items-center gap-2">
          <button className={BTN_BORDERED} onClick={runSetupAgain}>
            {t("settings.runSetup")}
          </button>
        </div>
        <div className={FIELD_HELP}>{t("settings.runSetupHelp")}</div>
      </div>
    </section>
  );
}

function TrustedWorkspacesCard() {
  const { tr } = useI18n();
  const [workspaces, setWorkspaces] = useState<WorkspaceCommandTrust[] | null>(null);
  const [revokePath, setRevokePath] = useState<string | null>(null);
  const [revoking, setRevoking] = useState(false);

  const refresh = () =>
    getTrustedWorkspaces()
      .then(setWorkspaces)
      .catch(() => setWorkspaces([]));

  useEffect(() => {
    refresh();
  }, []);

  const revoke = async (path: string) => {
    setRevoking(true);
    try {
      await setWorkspaceTrusted(path, false);
      refresh();
    } finally {
      setRevoking(false);
      setRevokePath(null);
    }
  };

  return (
    <div className={CARD + " p-4 mb-4"} data-testid="trusted-workspaces-card">
      <div className={FIELD_LABEL}>{tr("Trusted workspaces")}</div>
      <div className={FIELD_HELP}>
        {tr("Trusted projects may manage their command allowances in .link/config.toml.")}
      </div>
      {workspaces === null ? (
        <div className="text-[12px] text-muted mt-3">{tr("Loading…")}</div>
      ) : workspaces.length === 0 ? (
        <div className="text-[12px] text-muted mt-3">{tr("No workspaces are trusted.")}</div>
      ) : (
        <div className="mt-3 divide-y divide-line">
          {workspaces.map((workspace) => (
            <div key={workspace.workspace} className="py-2.5 flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] text-ink break-all">{workspace.workspace}</div>
                <div className="text-[11.5px] text-muted mt-0.5">
                  {workspace.requested_commands.length
                    ? tr(
                        workspace.requested_commands.length === 1
                          ? "{count} project command allowance"
                          : "{count} project command allowances",
                        { count: workspace.requested_commands.length },
                      )
                    : tr("No project command allowances currently declared")}
                  {!workspace.exists ? ` · ${tr("Folder unavailable")}` : ""}
                </div>
              </div>
              <button
                className="text-[12px] text-danger px-2 py-1"
                onClick={() => setRevokePath(workspace.workspace)}
              >
                {tr("Revoke")}
              </button>
            </div>
          ))}
        </div>
      )}
      {revokePath && (
        <ConfirmDialog
          title={tr("Revoke command trust for {path}?", { path: revokePath })}
          body={tr("Project command allowances will require confirmation again.")}
          confirmLabel={tr("Revoke")}
          danger
          busy={revoking}
          onCancel={() => setRevokePath(null)}
          onConfirm={() => void revoke(revokePath)}
        />
      )}
    </div>
  );
}

// Telemetry/Privacy card removed for this release (owner ask 2026-07-22); the
// setCloudTelemetry API stays for a future opt-out surface.

// -- Sidebar density -------------------------------------------------------------
// -- Token savings (PDF attachments; owner ask, 2026-07-17) ---------------------
// Attachments replay with EVERY turn, so a big PDF quietly multiplies token spend.
// Auto-compaction of long histories is a planned follow-up (punchlist §7) — until
// then this card is the user's dial: attach thresholds + the fallback for models
// without native PDF support.
function TokenSavingsCard() {
  const { tr } = useI18n();
  const [pdf, setPdf] = useState<PdfSettings | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) =>
        setPdf({
          pdf_fallback: s.pdf_fallback || "text",
          pdf_max_pages: s.pdf_max_pages || 20,
          pdf_max_mb: s.pdf_max_mb || 10,
        }),
      )
      .catch(() => setPdf({ pdf_fallback: "text", pdf_max_pages: 20, pdf_max_mb: 10 }));
  }, []);

  const save = async (patch: Partial<PdfSettings>) => {
    setPdf((p) => (p ? { ...p, ...patch } : p));
    await setPdfSettings(patch);
  };

  if (!pdf) return null;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="token-savings-card">
      <div className={FIELD_LABEL}>{tr("Token savings")}</div>
      <div className={FIELD_HELP}>
        {tr("PDF attachments travel with every turn of a conversation, so large documents multiply token usage.")}
      </div>

      <div className="mt-3 text-[13px] text-ink">{tr("PDFs on models without native PDF support")}</div>
      <div className="seg mt-2" role="radiogroup" aria-label={tr("PDF fallback")} data-testid="pdf-fallback">
        <button
          className={pdf.pdf_fallback === "text" ? "active" : ""}
          onClick={() => save({ pdf_fallback: "text" })}
        >
          {tr("Extract text")}
        </button>
        <button
          className={pdf.pdf_fallback === "images" ? "active" : ""}
          onClick={() => save({ pdf_fallback: "images" })}
        >
          {tr("Send page images")}
        </button>
      </div>
      <div className={FIELD_HELP}>
        {tr("Claude, GPT and Gemini read PDFs natively. For other models, text extraction uses fewer tokens; page images require vision support.")}
      </div>

      <div className="mt-3 flex items-center gap-5">
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">{tr("Max pages")}</span>
          <input
            type="number"
            min={1}
            max={100}
            value={pdf.pdf_max_pages}
            data-testid="pdf-max-pages"
            className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) => save({ pdf_max_pages: Math.max(1, Math.min(Number(e.target.value) || 20, 100)) })}
          />
        </label>
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">{tr("Max size")}</span>
          <input
            type="number"
            min={1}
            max={10}
            value={pdf.pdf_max_mb}
            data-testid="pdf-max-mb"
            className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) => save({ pdf_max_mb: Math.max(1, Math.min(Number(e.target.value) || 10, 10)) })}
          />
          <span className="text-[12.5px] text-muted">MB</span>
        </label>
      </div>
      <div className={FIELD_HELP}>
        {tr("PDFs over these limits are not attached. Smallink will show a notice in the composer instead.")}
      </div>
    </div>
  );
}

function SidebarCard() {
  const { tr } = useI18n();
  const [peek, setPeek] = useState<number | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setPeek(s.sessions_peek || 5))
      .catch(() => setPeek(5));
  }, []);

  const save = async (n: number) => {
    const clamped = Math.max(1, Math.min(n || 5, 50));
    setPeek(clamped);
    await setSessionsPeek(clamped);
  };

  if (peek === null) return null;
  return (
    <div className={CARD + " p-4 mb-4"}>
      <div className={FIELD_LABEL}>{tr("Sidebar")}</div>
      <label className="flex items-center gap-3 mt-2.5">
        <span className="text-[13px] text-ink">{tr("Conversations shown per agent")}</span>
        <input
          type="number"
          min={1}
          max={50}
          value={peek}
          className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
          onChange={(e) => save(Number(e.target.value))}
        />
      </label>
      <div className={FIELD_HELP}>
        {tr("Longer lists collapse behind “Show more”. This applies to each agent and project.")}
      </div>
    </div>
  );
}

// -- Files (scratch location) — one card inside General (UX-021: a single option
// doesn't earn its own tab) -----------------------------------------------------
function FilesCard() {
  const { tr } = useI18n();
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [scratchDraft, setScratchDraft] = useState("");
  const [scratchMsg, setScratchMsg] = useState<string | null>(null);
  const desktop = isTauri();

  const refresh = () =>
    getSettings()
      .then((s) => {
        setSettings(s);
        setScratchDraft((d) => d || s.scratch_base || "");
      })
      .catch(() => setSettings(null));
  useEffect(() => {
    refresh();
  }, []);

  const saveScratch = async () => {
    setScratchMsg(null);
    const res = await setScratchBase(scratchDraft.trim());
    if (res.ok) {
      setScratchMsg(tr("Saved. New conversations will use this location."));
      refresh();
    } else {
      setScratchMsg(res.error || tr("Could not use that location."));
    }
  };
  const browseScratch = async () => {
    const picked = await pickFolder();
    if (picked) setScratchDraft(picked);
  };

  if (!settings) return null;

  return (
    <div className={CARD + " p-4 mb-4"}>
      <div className={FIELD_LABEL}>{tr("Files")}</div>
        <div className="flex items-center gap-2 mt-2.5">
          <input
            className={INPUT}
            type="text"
            placeholder="~/Smallink"
            value={scratchDraft}
            spellCheck={false}
            autoComplete="off"
            onChange={(e) => setScratchDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && saveScratch()}
          />
          {desktop && (
            <button className={BTN_BORDERED} onClick={browseScratch} title={tr("Pick a folder")}>
              {tr("Browse")}
            </button>
          )}
          <button className={BTN_ACCENT} onClick={saveScratch} disabled={!scratchDraft.trim()}>
            {tr("Save")}
          </button>
        </div>
      <div className={FIELD_HELP}>
        {tr("Each conversation gets its own folder here. Existing conversations keep their current folder, and you can grant access to more folders from a conversation.")}
      </div>
      {scratchMsg && <div className="text-[12.5px] text-muted mt-2.5">{scratchMsg}</div>}
    </div>
  );
}

// -- Privacy & data management ------------------------------------------------
function PrivacySection() {
  const { tr } = useI18n();
  const [sensoryStats, setSensoryStats] = useState<{ total: number; sources: Record<string, number> } | null>(null);
  const [memoryCount, setMemoryCount] = useState<number | null>(null);
  const [connectors, setConnectors] = useState<{ name: string; connected: boolean }[]>([]);
  const [deleting, setDeleting] = useState(false);
  const [deleteResult, setDeleteResult] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<"sensory" | "memory" | null>(null);
  const [retentionDays, setRetentionDays] = useState(90);

  useEffect(() => {
    getSensoryStats()
      .then((s) => setSensoryStats(s as any))
      .catch(() => setSensoryStats(null));
    getMemory("all")
      .then((m) => setMemoryCount(m.length))
      .catch(() => setMemoryCount(null));
    getConnectors()
      .then((c) => setConnectors(c.map((x: any) => ({ name: x.name || x.id, connected: !!x.connected }))))
      .catch(() => setConnectors([]));
  }, []);

  const deleteSensoryOlderThan = async () => {
    setDeleting(true);
    setDeleteResult(null);
    try {
      const before = new Date(Date.now() - retentionDays * 86400000).toISOString();
      const res = await deleteSensoryRecords({ before });
      setDeleteResult(tr("{count} source records deleted.", { count: res.deleted_records }));
      const stats = await getSensoryStats();
      setSensoryStats(stats as any);
    } catch (e: any) {
      setDeleteResult(e.message || tr("Delete failed."));
    } finally {
      setDeleting(false);
      setConfirmDelete(null);
    }
  };

  const deleteAllMemories = async () => {
    setDeleting(true);
    setDeleteResult(null);
    try {
      const memories = await getMemory("all");
      let archived = 0;
      for (const m of memories) {
        try {
          await archiveMemory(m.id);
          archived++;
        } catch { /* skip */ }
      }
      setDeleteResult(tr("{count} memories archived.", { count: archived }));
      setMemoryCount(0);
    } catch (e: any) {
      setDeleteResult(e.message || tr("Archive failed."));
    } finally {
      setDeleting(false);
      setConfirmDelete(null);
    }
  };

  return (
    <section>
      <PanelHead
        title={tr("Privacy & data")}
        sub={tr("Understand what Smallink stores and manage your data retention.")}
      />

      <div className={CARD + " p-4 mb-4"}>
        <div className={FIELD_LABEL}>{tr("Data storage")}</div>
        <div className={FIELD_HELP + " mb-3"}>
          {tr("All data stays on this computer. Nothing is sent to external servers except model API calls.")}
        </div>
        <div className="grid grid-cols-2 gap-3 text-[12.5px]">
          <div className="rounded-lg border border-line bg-paper p-3">
            <div className="text-muted">{tr("Location")}</div>
            <div className="text-ink font-mono mt-1 break-all">~/.config/link</div>
          </div>
          <div className="rounded-lg border border-line bg-paper p-3">
            <div className="text-muted">{tr("Source records")}</div>
            <div className="text-ink font-medium mt-1">{sensoryStats?.total ?? "..."}</div>
          </div>
          <div className="rounded-lg border border-line bg-paper p-3">
            <div className="text-muted">{tr("Memories")}</div>
            <div className="text-ink font-medium mt-1">{memoryCount ?? "..."}</div>
          </div>
          <div className="rounded-lg border border-line bg-paper p-3">
            <div className="text-muted">{tr("Connectors")}</div>
            <div className="text-ink font-medium mt-1">{connectors.filter((c) => c.connected).length} {tr("active")}</div>
          </div>
        </div>
      </div>

      <div className={CARD + " p-4 mb-4"}>
        <div className={FIELD_LABEL}>{tr("Source record retention")}</div>
        <div className={FIELD_HELP}>
          {tr("Delete source records (conversation snapshots, imported documents) older than a threshold.")}
        </div>
        <div className="flex items-center gap-3 mt-3">
          <span className="text-[13px] text-ink">{tr("Delete records older than")}</span>
          <input
            type="number"
            min={7}
            max={365}
            value={retentionDays}
            className="w-20 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) => setRetentionDays(Math.max(7, Math.min(365, Number(e.target.value) || 90)))}
          />
          <span className="text-[12.5px] text-muted">{tr("days")}</span>
          <button
            className={BTN_BORDERED + " text-danger border-danger/30"}
            disabled={deleting}
            onClick={() => setConfirmDelete("sensory")}
          >
            {tr("Delete")}
          </button>
        </div>
      </div>

      <div className={CARD + " p-4 mb-4"}>
        <div className={FIELD_LABEL}>{tr("Memory data")}</div>
        <div className={FIELD_HELP}>
          {tr("Archive all learned memories. Archived memories are no longer used in conversations but can be restored from the Memory view.")}
        </div>
        <div className="flex items-center gap-3 mt-3">
          <span className="text-[13px] text-ink">
            {memoryCount !== null ? tr("{count} active memories", { count: memoryCount }) : tr("Loading...")}
          </span>
          <button
            className={BTN_BORDERED + " text-danger border-danger/30"}
            disabled={deleting || !memoryCount}
            onClick={() => setConfirmDelete("memory")}
          >
            {tr("Archive all")}
          </button>
        </div>
      </div>

      <div className={CARD + " p-4"}>
        <div className={FIELD_LABEL}>{tr("Connected services")}</div>
        <div className={FIELD_HELP + " mb-3"}>
          {tr("Data synced from external services is stored locally. Disconnect a service to stop syncing.")}
        </div>
        {connectors.length === 0 ? (
          <div className="text-[12.5px] text-muted">{tr("No connectors configured.")}</div>
        ) : (
          <div className="divide-y divide-line">
            {connectors.map((c) => (
              <div key={c.name} className="py-2.5 flex items-center gap-3">
                <span className="text-[13px] text-ink capitalize">{c.name}</span>
                <span
                  className={
                    "ml-auto text-[11.5px] px-2 py-0.5 rounded-full " +
                    (c.connected ? "bg-okSoft text-ok" : "bg-paper text-muted")
                  }
                >
                  {c.connected ? tr("Connected") : tr("Disconnected")}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {deleteResult && (
        <div className="mt-4 rounded-lg border border-line bg-paper px-3 py-2.5 text-[12.5px] text-muted">
          {deleteResult}
        </div>
      )}

      {confirmDelete === "sensory" && (
        <ConfirmDialog
          title={tr("Delete source records older than {days} days?", { days: retentionDays })}
          body={tr("This cannot be undone. Memories derived from these records will remain.")}
          confirmLabel={tr("Delete")}
          danger
          busy={deleting}
          onCancel={() => setConfirmDelete(null)}
          onConfirm={() => void deleteSensoryOlderThan()}
        />
      )}
      {confirmDelete === "memory" && (
        <ConfirmDialog
          title={tr("Archive all memories?")}
          body={tr("Archived memories stop influencing conversations. You can restore them later from the Memory view.")}
          confirmLabel={tr("Archive all")}
          danger
          busy={deleting}
          onCancel={() => setConfirmDelete(null)}
          onConfirm={() => void deleteAllMemories()}
        />
      )}
    </section>
  );
}
