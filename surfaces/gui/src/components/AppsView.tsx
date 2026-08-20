import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  changeAppState,
  getAppActivity,
  getAppAssets,
  getApps,
  invokeAppCapability,
  pickAppImportFile,
  type AppAsset,
  type SmallinkApp,
} from "../api";
import { openExternal } from "../tauri";
import { useI18n } from "../i18n";
import { ConnectorIcon } from "../connectors/ConnectorIcon";
import { Icon } from "./Icon";
import { ConfirmDialog } from "./ConfirmDialog";
import { InlineFeedback, PageState } from "./AsyncFeedback";

type View = "catalog" | "detail" | "workspace";
type WorkspaceTab = "all" | "report" | "page" | "resource" | "tasks" | "activity";

const typeOf = (asset: AppAsset) => String(asset.type || asset.assetType || "asset").toLowerCase();
const titleOf = (asset: AppAsset) => String(asset.title || asset.name || asset.code || asset.id || "Untitled");
const referenceOf = (asset: AppAsset) => String(asset.code || asset.id || "");
const previewOf = (asset?: AppAsset | null) => String(asset?.previewUrl || asset?.preview || asset?.url || "");

function errorText(value: any): string {
  if (!value) return "Application command failed";
  if (typeof value === "string") return value;
  return String(value.message || value.code || "Application command failed");
}

function resultRows(result: any): any[] {
  const data = result?.data;
  for (const value of [result?.items, result?.tasks, data?.items, data?.tasks, data, result?.rows]) {
    if (Array.isArray(value)) return value;
  }
  return [];
}

export function AppsView({
  initialAppId = null,
  onNewProjectSession,
}: {
  initialAppId?: string | null;
  onNewProjectSession: (projectId: string) => void;
}) {
  const { tr } = useI18n();
  const [apps, setApps] = useState<SmallinkApp[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<View>("catalog");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const app = useMemo(() => apps.find((item) => item.app_id === selectedId) || null, [apps, selectedId]);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      setApps(await getApps());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Could not load applications"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!initialAppId || !apps.some((item) => item.app_id === initialAppId)) return;
    setSelectedId(initialAppId);
    setView("detail");
  }, [apps, initialAppId]);

  const changeState = async (action: "enable" | "check" | "disable") => {
    if (!app) return;
    setBusy(true);
    setError("");
    try {
      const result = await changeAppState(app.app_id, action);
      setApps((current) => current.map((item) => item.app_id === result.app.app_id ? result.app : item));
      if (!result.ok) setError(errorText(result.result?.error));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Application action failed"));
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return <main className="flex-1 min-w-0 bg-paper p-6"><PageState title={tr("Loading applications…")} body={tr("Checking local application contracts and projects.")} /></main>;
  }

  if (view === "workspace" && app) {
    return (
      <MineMWorkspace
        app={app}
        onBack={() => setView("detail")}
        onNewConversation={() => onNewProjectSession(app.project.project_id)}
      />
    );
  }

  if (view === "detail" && app) {
    const available = app.instance.enabled && app.runtime.health === "running";
    return (
      <main className="flex-1 min-w-0 bg-paper overflow-y-auto">
        <div className="max-w-5xl mx-auto px-7 py-6">
          <button className="inline-flex items-center gap-1.5 text-[12px] text-muted hover:text-ink" onClick={() => setView("catalog")}>
            <Icon name="arrowLeft" size={14} /> {tr("Applications")}
          </button>
          <div className="mt-6 flex items-start gap-4 border-b border-line pb-6">
            <ConnectorIcon connector={{ logo: app.icon, brand_color: "#00529B" }} size={42} />
            <div className="min-w-0 flex-1">
              <h1 className="text-[24px] font-semibold text-heading">{app.name}</h1>
              <p className="text-[13px] text-muted mt-1 max-w-2xl">{tr(app.description)}</p>
            </div>
            <StatusPill app={app} />
          </div>

          {error && <div className="mt-5"><InlineFeedback tone="danger" title={tr("Application action failed")} body={error} /></div>}

          <section className="py-6 border-b border-line grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_280px] gap-8">
            <div>
              <h2 className="text-[16px] font-semibold text-heading">{tr("MineM material library")}</h2>
              <p className="text-[12.5px] text-muted leading-relaxed mt-1.5">
                {tr("Search, inspect, import, rename, organize, and reuse MineM assets without leaving Smallink.")}
              </p>
              <div className="flex flex-wrap gap-2 mt-5">
                <button
                  className="h-9 px-4 rounded-lg bg-accent text-onAccent text-[12.5px] font-medium disabled:opacity-45"
                  disabled={!available || busy}
                  onClick={() => setView("workspace")}
                >
                  {tr("Open material library")}
                </button>
                <button
                  className="h-9 px-4 rounded-lg border border-line bg-panel text-[12.5px] text-ink disabled:opacity-45"
                  disabled={busy}
                  onClick={() => void changeState(available ? "check" : "enable")}
                >
                  {tr(available ? "Check connection" : "Enable and start")}
                </button>
              </div>
            </div>
            <dl className="text-[12px] divide-y divide-line border-y border-line">
              <Fact label={tr("System project")} value={app.project.name} />
              <Fact label={tr("CLI")} value={app.runtime.cli_available ? tr("Available") : tr("Not found")} />
              <Fact label={tr("Version")} value={String(app.instance.app_version || app.runtime.app_version || "—")} />
              <Fact label={tr("Capabilities")} value={String(app.capabilities.length)} />
            </dl>
          </section>

          <section className="py-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-[16px] font-semibold text-heading">{tr("Data and memory")}</h2>
                <p className="text-[12.5px] text-muted mt-1">{tr("Every semantic MineM operation is stored as source evidence before AI governance.")}</p>
              </div>
              {app.instance.enabled && (
                <button className="text-[12px] text-muted hover:text-danger" disabled={busy} onClick={() => void changeState("disable")}>{tr("Disable application")}</button>
              )}
            </div>
            <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-px bg-line border border-line rounded-lg overflow-hidden">
              <Metric label={tr("Memory types")} value={app.memory_types.length} />
              <Metric label={tr("Project conversations")} value={app.project.session_count} />
              <Metric label={tr("Runtime state")} value={tr(app.instance.runtime_state)} />
            </div>
          </section>
        </div>
      </main>
    );
  }

  return (
    <main className="flex-1 min-w-0 bg-paper overflow-y-auto">
      <div className="max-w-6xl mx-auto px-7 py-7">
        <div className="flex items-end justify-between border-b border-line pb-5">
          <div>
            <h1 className="text-[24px] font-semibold text-heading">{tr("Applications")}</h1>
            <p className="text-[13px] text-muted mt-1">{tr("Domain products connected to Smallink tasks, projects, data, and memory.")}</p>
          </div>
          <button className="w-9 h-9 grid place-items-center rounded-lg border border-line bg-panel text-muted hover:text-ink" title={tr("Refresh")} onClick={() => void load()}>
            <Icon name="refresh" size={15} />
          </button>
        </div>
        {error && <div className="mt-5"><InlineFeedback tone="danger" title={tr("Could not load applications")} body={error} action={tr("Retry")} onAction={() => void load()} /></div>}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-5">
          {apps.map((item) => (
            <button
              key={item.app_id}
              data-testid={`app-${item.app_id}`}
              className="text-left rounded-lg border border-line bg-panel p-4 hover:border-accent/45 hover:bg-accentSoft/10 transition-colors"
              onClick={() => { setSelectedId(item.app_id); setView("detail"); setError(""); }}
            >
              <div className="flex items-start gap-3">
                <ConnectorIcon connector={{ logo: item.icon, brand_color: "#00529B" }} size={34} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[15px] font-semibold text-heading">{item.name}</span>
                    <StatusPill app={item} compact />
                  </div>
                  <div className="text-[12px] text-muted leading-relaxed mt-1 line-clamp-2">{tr(item.description)}</div>
                  <div className="text-[11px] text-faint mt-3">{item.system_project_name} · {item.capabilities.length} {tr("capabilities")}</div>
                </div>
                <Icon name="chevronRight" size={15} className="text-faint mt-2" />
              </div>
            </button>
          ))}
        </div>
      </div>
    </main>
  );
}

function MineMWorkspace({
  app,
  onBack,
  onNewConversation,
}: {
  app: SmallinkApp;
  onBack: () => void;
  onNewConversation: () => void;
}) {
  const { tr } = useI18n();
  const [tab, setTab] = useState<WorkspaceTab>("all");
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [assets, setAssets] = useState<AppAsset[]>([]);
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<AppAsset | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const [rename, setRename] = useState("");
  const [deletePending, setDeletePending] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      if (tab === "activity") {
        setRows(await getAppActivity(app.app_id));
        setAssets([]);
      } else if (tab === "tasks") {
        const result = await invokeAppCapability(app.app_id, "task.list", {});
        if (!result.ok) throw new Error(errorText(result.error));
        setRows(resultRows(result));
        setAssets([]);
      } else {
        const result = await getAppAssets(app.app_id, {
          query: appliedQuery,
          assetType: tab,
          limit: 100,
        });
        if (!result.ok) throw new Error(errorText(result.error));
        setAssets(result.items || []);
        setRows([]);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Could not load MineM data"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [tab, appliedQuery]);

  const openAsset = async (asset: AppAsset) => {
    setSelected(asset);
    setRename(titleOf(asset));
    setDetail(asset);
    setDetailBusy(true);
    try {
      const result = await invokeAppCapability(app.app_id, "asset.get", { reference: referenceOf(asset) });
      if (result.ok) setDetail(result.resource || result.data || result);
    } finally {
      setDetailBusy(false);
    }
  };

  const renameAsset = async () => {
    if (!selected || !rename.trim()) return;
    setDetailBusy(true);
    try {
      const result = await invokeAppCapability(app.app_id, "asset.rename", {
        reference: referenceOf(selected),
        name: rename.trim(),
        type: typeOf(selected),
      });
      if (!result.ok) throw new Error(errorText(result.error));
      setSelected(null);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Could not rename this asset"));
    } finally {
      setDetailBusy(false);
    }
  };

  const deleteAsset = async () => {
    if (!selected) return;
    setDetailBusy(true);
    try {
      const result = await invokeAppCapability(app.app_id, "asset.delete", {
        reference: referenceOf(selected),
        type: typeOf(selected),
        confirm: true,
      });
      if (!result.ok) throw new Error(errorText(result.error));
      setDeletePending(false);
      setSelected(null);
      await load();
    } catch (reason) {
      setDeletePending(false);
      setError(reason instanceof Error ? reason.message : tr("Could not delete this asset"));
    } finally {
      setDetailBusy(false);
    }
  };

  const tabs: Array<[WorkspaceTab, string]> = [
    ["all", "All assets"],
    ["report", "Reports"],
    ["page", "Pages"],
    ["resource", "Resources"],
    ["tasks", "Import tasks"],
    ["activity", "Activity"],
  ];

  return (
    <main className="flex-1 min-w-0 bg-paper flex flex-col overflow-hidden">
      <header className="px-6 pt-5 pb-4 border-b border-line bg-panel/55 shrink-0">
        <div className="flex items-start gap-3">
          <button className="w-8 h-8 grid place-items-center rounded-lg text-muted hover:text-ink hover:bg-paper" title={tr("Back")} onClick={onBack}><Icon name="arrowLeft" size={16} /></button>
          <ConnectorIcon connector={{ logo: app.icon, brand_color: "#00529B" }} size={30} />
          <div className="min-w-0 flex-1">
            <h1 className="text-[18px] font-semibold text-heading">{app.project.name}</h1>
            <div className="text-[11.5px] text-muted mt-0.5">{tr("MineM assets with Smallink source evidence and memory governance")}</div>
          </div>
          <button className="h-9 px-3.5 rounded-lg border border-line bg-panel text-[12px] text-ink" onClick={() => setImportOpen(true)}>{tr("Import")}</button>
          <button className="h-9 px-3.5 rounded-lg bg-accent text-onAccent text-[12px] font-medium" onClick={onNewConversation}>{tr("New MineM conversation")}</button>
        </div>
        <div className="flex items-center gap-1 mt-4 overflow-x-auto" role="tablist">
          {tabs.map(([key, label]) => (
            <button key={key} role="tab" aria-selected={tab === key} className={`px-3 py-1.5 rounded-lg text-[12px] whitespace-nowrap ${tab === key ? "bg-accentSoft text-accent font-medium" : "text-muted hover:text-ink"}`} onClick={() => { setTab(key); setSelected(null); }}>
              {tr(label)}
            </button>
          ))}
        </div>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5">
        {!["tasks", "activity"].includes(tab) && (
          <form className="flex gap-2 mb-4" onSubmit={(event: FormEvent) => { event.preventDefault(); setAppliedQuery(query.trim()); }}>
            <div className="relative flex-1 max-w-2xl">
              <Icon name="search" size={15} className="absolute left-3 top-2.5 text-faint" />
              <input className="w-full h-9 rounded-lg border border-line bg-panel pl-9 pr-3 text-[12.5px] text-ink outline-none focus:border-accent" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tr("Search titles, codes, and material content")} />
            </div>
            <button className="h-9 px-4 rounded-lg border border-line bg-panel text-[12px] text-ink">{tr("Search")}</button>
            {appliedQuery && <button type="button" className="h-9 px-3 text-[12px] text-muted" onClick={() => { setQuery(""); setAppliedQuery(""); }}>{tr("Clear")}</button>}
          </form>
        )}
        {error && <div className="mb-4"><InlineFeedback tone="danger" title={tr("MineM request failed")} body={error} action={tr("Retry")} onAction={() => void load()} /></div>}

        {loading ? (
          <PageState title={tr("Loading MineM data…")} body={tr("Reading the current MineM library through its public CLI contract.")} />
        ) : tab === "activity" ? (
          <ActivityTable rows={rows} />
        ) : tab === "tasks" ? (
          <TaskTable rows={rows} />
        ) : assets.length === 0 ? (
          <PageState icon="search" title={tr("No matching assets")} body={tr("Try another keyword or asset type.")} />
        ) : (
          <div className="border-y border-line divide-y divide-line bg-panel/35">
            {assets.map((asset, index) => (
              <button key={`${referenceOf(asset)}-${index}`} className="w-full text-left grid grid-cols-[90px_minmax(0,1fr)_150px_20px] gap-3 items-center px-3 py-3 hover:bg-panel" onClick={() => void openAsset(asset)}>
                <span className="text-[10.5px] uppercase text-accent font-semibold">{tr(typeOf(asset))}</span>
                <span className="min-w-0"><span className="block text-[13px] text-ink truncate">{titleOf(asset)}</span><span className="block text-[11px] text-faint truncate mt-0.5">{referenceOf(asset)}</span></span>
                <span className="text-[11px] text-muted truncate">{String(asset.updatedAt || asset.createdAt || "")}</span>
                <Icon name="chevronRight" size={14} className="text-faint" />
              </button>
            ))}
          </div>
        )}
      </div>

      {selected && (
        <div className="fixed inset-0 z-[80] bg-ink/30 flex justify-end" role="dialog" aria-modal="true" aria-label={tr("Asset details")} onMouseDown={(event) => event.target === event.currentTarget && setSelected(null)}>
          <aside className="w-full max-w-[520px] h-full bg-panel border-l border-line shadow-2xl flex flex-col">
            <div className="p-5 border-b border-line flex items-start gap-3">
              <div className="min-w-0 flex-1"><div className="text-[11px] text-accent uppercase font-semibold">{tr(typeOf(selected))}</div><h2 className="text-[17px] font-semibold text-heading mt-1">{titleOf(selected)}</h2><div className="text-[11px] text-faint mt-1">{referenceOf(selected)}</div></div>
              <button className="w-8 h-8 grid place-items-center rounded-lg text-muted hover:bg-paper" title={tr("Close")} onClick={() => setSelected(null)}><Icon name="x" size={15} /></button>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
              {detailBusy && <div className="text-[12px] text-muted mb-3">{tr("Loading details…")}</div>}
              <label className="text-[11px] text-muted">{tr("Title")}</label>
              <div className="flex gap-2 mt-1">
                <input className="h-9 flex-1 rounded-lg border border-line bg-paper px-3 text-[12.5px] text-ink outline-none focus:border-accent" value={rename} onChange={(event) => setRename(event.target.value)} />
                <button className="h-9 px-3 rounded-lg border border-line text-[12px] text-ink disabled:opacity-45" disabled={detailBusy || !rename.trim()} onClick={() => void renameAsset()}>{tr("Rename")}</button>
              </div>
              {previewOf(detail || selected) && (
                <button className="mt-4 h-9 px-3.5 rounded-lg bg-accent text-onAccent text-[12px]" onClick={() => openExternal(previewOf(detail || selected))}>{tr("Open preview")}</button>
              )}
              <div className="mt-5 border-t border-line pt-4">
                <div className="text-[11px] uppercase text-faint font-semibold mb-2">{tr("Source snapshot")}</div>
                <pre className="whitespace-pre-wrap break-words rounded-lg bg-paper border border-line p-3 text-[11px] leading-relaxed text-muted max-h-[360px] overflow-auto">{JSON.stringify(detail || selected, null, 2)}</pre>
              </div>
            </div>
            <div className="p-4 border-t border-line flex justify-between">
              <button className="h-9 px-3 text-[12px] text-danger" onClick={() => setDeletePending(true)}>{tr("Delete asset")}</button>
              <button className="h-9 px-3 text-[12px] text-muted" onClick={() => setSelected(null)}>{tr("Done")}</button>
            </div>
          </aside>
        </div>
      )}

      {deletePending && selected && (
        <ConfirmDialog title={tr("Delete this MineM asset?")} body={tr("This changes MineM's formal material library. Existing Smallink source evidence remains for audit.")} confirmLabel={tr("Delete asset")} danger busy={detailBusy} onCancel={() => setDeletePending(false)} onConfirm={() => void deleteAsset()} />
      )}
      {importOpen && <ImportDialog appId={app.app_id} onClose={() => setImportOpen(false)} onImported={() => { setImportOpen(false); void load(); }} />}
    </main>
  );
}

function ImportDialog({ appId, onClose, onImported }: { appId: string; onClose: () => void; onImported: () => void }) {
  const { tr } = useI18n();
  const [kind, setKind] = useState<"page" | "report" | "case">("page");
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pick = async () => {
    const selected = await pickAppImportFile(appId);
    if (selected) setPath(selected);
  };
  const submit = async () => {
    if (!path) return;
    setBusy(true);
    setError("");
    try {
      const capability = kind === "case" ? "case.import" : `import.${kind}`;
      const result = await invokeAppCapability(appId, capability, { source: path, name, wait: true });
      if (!result.ok) throw new Error(errorText(result.error));
      onImported();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Import failed"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="fixed inset-0 z-[90] bg-ink/35 grid place-items-center p-4" role="dialog" aria-modal="true" aria-label={tr("Import into MineM")}>
      <div className="w-full max-w-lg rounded-lg border border-line bg-panel shadow-2xl p-5">
        <div className="flex items-start"><div className="flex-1"><h2 className="text-[16px] font-semibold text-heading">{tr("Import into MineM")}</h2><p className="text-[12px] text-muted mt-1">{tr("The source is imported by MineM; Smallink stores the operation and resulting asset reference.")}</p></div><button className="w-8 h-8 grid place-items-center text-muted" onClick={onClose}><Icon name="x" size={15} /></button></div>
        {error && <div className="mt-4"><InlineFeedback tone="danger" title={tr("Import failed")} body={error} /></div>}
        <div className="mt-5">
          <label className="text-[11px] text-muted">{tr("Material type")}</label>
          <div className="flex gap-1 mt-1">{(["page", "report", "case"] as const).map((item) => <button key={item} className={`px-3 py-1.5 rounded-lg text-[12px] ${kind === item ? "bg-accentSoft text-accent" : "text-muted hover:bg-paper"}`} onClick={() => setKind(item)}>{tr(item)}</button>)}</div>
        </div>
        <div className="mt-4"><label className="text-[11px] text-muted">{tr("Source file")}</label><div className="flex gap-2 mt-1"><input readOnly className="h-9 flex-1 rounded-lg border border-line bg-paper px-3 text-[12px] text-muted truncate" value={path} placeholder={tr("No file selected")} /><button className="h-9 px-3 rounded-lg border border-line text-[12px] text-ink" onClick={() => void pick()}>{tr("Choose file")}</button></div></div>
        <div className="mt-4"><label className="text-[11px] text-muted">{tr("Name (optional)")}</label><input className="mt-1 h-9 w-full rounded-lg border border-line bg-paper px-3 text-[12px] text-ink outline-none focus:border-accent" value={name} onChange={(event) => setName(event.target.value)} /></div>
        <div className="mt-6 flex justify-end gap-2"><button className="h-9 px-4 rounded-lg border border-line text-[12px] text-muted" disabled={busy} onClick={onClose}>{tr("Cancel")}</button><button className="h-9 px-4 rounded-lg bg-accent text-onAccent text-[12px] disabled:opacity-45" disabled={busy || !path} onClick={() => void submit()}>{tr(busy ? "Importing…" : "Import")}</button></div>
      </div>
    </div>
  );
}

function StatusPill({ app, compact = false }: { app: SmallinkApp; compact?: boolean }) {
  const { tr } = useI18n();
  const running = app.instance.enabled && app.runtime.health === "running";
  const label = running ? "Available" : app.runtime.cli_available ? "Offline" : "Not installed";
  return <span className={`${compact ? "text-[10px] px-1.5 py-0.5" : "text-[11px] px-2 py-1"} rounded-full border ${running ? "border-okLine bg-okSoft text-okInk" : "border-line bg-paper text-muted"}`}>{tr(label)}</span>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between gap-3 py-2.5"><dt className="text-muted">{label}</dt><dd className="text-ink text-right truncate">{value}</dd></div>;
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="bg-panel px-4 py-4"><div className="text-[11px] text-muted">{label}</div><div className="text-[20px] text-heading font-semibold mt-1">{value}</div></div>;
}

function ActivityTable({ rows }: { rows: any[] }) {
  const { tr } = useI18n();
  if (!rows.length) return <PageState title={tr("No application activity yet")} body={tr("MineM operations will appear here with their source evidence.")} />;
  return <div className="border-y border-line divide-y divide-line">{rows.map((row, index) => <div key={row.capability_run_id || index} className="grid grid-cols-[180px_110px_minmax(0,1fr)] gap-3 px-3 py-3 text-[12px]"><span className="text-ink">{row.capability}</span><span className={row.status === "completed" ? "text-okInk" : "text-danger"}>{tr(row.status)}</span><span className="text-muted truncate">{row.started_at}</span></div>)}</div>;
}

function TaskTable({ rows }: { rows: any[] }) {
  const { tr } = useI18n();
  if (!rows.length) return <PageState title={tr("No MineM tasks")} body={tr("Imports and exports will appear here while MineM processes them.")} />;
  return <div className="border-y border-line divide-y divide-line">{rows.map((row, index) => <div key={row.id || index} className="grid grid-cols-[minmax(0,1fr)_120px_180px] gap-3 px-3 py-3 text-[12px]"><span className="text-ink truncate">{row.title || row.filename || row.id}</span><span className="text-muted">{tr(String(row.status || "unknown"))}</span><span className="text-faint truncate">{row.updatedAt || row.createdAt || ""}</span></div>)}</div>;
}
