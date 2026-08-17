import { useEffect, useMemo, useState } from "react";
import {
  createSkill,
  getSkillDetail,
  getSkills,
  importSkill,
  type SkillCatalogItem,
  type SkillCatalogResponse,
  type SkillDetail,
} from "../api";
import { chooseFolder, chooseSkillArchive } from "../tauri";
import { useI18n } from "../i18n";
import { Icon } from "./Icon";
import { PanelHead } from "./IntegrationsView";

type StatusFilter = "all" | "active" | "shadowed" | "issues";

const EMPTY_SUMMARY: SkillCatalogResponse["summary"] = {
  total: 0,
  active: 0,
  issues: 0,
  sources: 0,
};

function statusOf(skill: SkillCatalogItem): Exclude<StatusFilter, "all"> {
  if (!skill.valid || skill.warnings.length > 0) return "issues";
  return skill.active ? "active" : "shadowed";
}

export function SkillHub({
  workspace,
  onCreateWithAgent,
}: {
  workspace?: string;
  onCreateWithAgent?: () => void;
}) {
  const { tr } = useI18n();
  const [catalog, setCatalog] = useState<SkillCatalogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [createMode, setCreateMode] = useState<"manual" | "import" | null>(null);

  const load = () => {
    setLoading(true);
    setError("");
    getSkills(workspace)
      .then((next) => {
        setCatalog(next);
        if (selected && !next.skills.some((skill) => skill.id === selected)) {
          setSelected(null);
          setDetail(null);
        }
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : tr("Could not load Skill Hub."));
      })
      .finally(() => setLoading(false));
  };

  useEffect(load, [workspace]); // eslint-disable-line react-hooks/exhaustive-deps

  const openDetail = (skill: SkillCatalogItem) => {
    setSelected(skill.id);
    setDetail(null);
    setDetailError("");
    setDetailLoading(true);
    getSkillDetail(skill.id, workspace)
      .then(setDetail)
      .catch((reason) => {
        setDetailError(
          reason instanceof Error ? reason.message : tr("Could not load this Skill."),
        );
      })
      .finally(() => setDetailLoading(false));
  };

  const sources = useMemo(() => {
    const items = new Map<string, string>();
    for (const skill of catalog?.skills || []) {
      items.set(skill.source, skill.source_label);
    }
    return [...items.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [catalog]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return (catalog?.skills || []).filter((skill) => {
      if (source !== "all" && skill.source !== source) return false;
      if (status !== "all" && statusOf(skill) !== status) return false;
      if (!needle) return true;
      return [
        skill.display_name,
        skill.name,
        skill.description,
        skill.short_description,
        skill.category,
        ...skill.tags,
      ]
        .join(" ")
        .toLocaleLowerCase()
        .includes(needle);
    });
  }, [catalog, query, source, status]);

  useEffect(() => {
    if (selected && !filtered.some((skill) => skill.id === selected)) {
      setSelected(null);
      setDetail(null);
    }
  }, [filtered, selected]);

  const summary = catalog?.summary || EMPTY_SUMMARY;

  return (
    <section>
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <PanelHead
            title={tr("Skill Hub")}
            sub={tr(
              "Browse, create, and import reusable workflows for every Smallink agent.",
            )}
          />
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setCreateMode("import")}
            className="h-9 px-3 rounded-lg border border-line bg-panel text-[12px] text-ink inline-flex items-center gap-1.5 hover:border-accent hover:text-accent"
          >
            <Icon name="folderPlus" size={15} /> {tr("Import")}
          </button>
          <button
            onClick={() => setCreateMode("manual")}
            className="h-9 px-3 rounded-lg border border-line bg-panel text-[12px] text-ink inline-flex items-center gap-1.5 hover:border-accent hover:text-accent"
          >
            <Icon name="pencil" size={15} /> {tr("New Skill")}
          </button>
          <button
            onClick={onCreateWithAgent}
            disabled={!onCreateWithAgent}
            className="h-9 px-3 rounded-lg bg-gradient-to-r from-primary to-accent text-onAccent text-[12px] font-medium inline-flex items-center gap-1.5 shadow-sm hover:brightness-105 disabled:opacity-40"
          >
            <Icon name="sparkle" size={15} /> {tr("Create with Agent")}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3 mb-4">
        <Summary label={tr("Discovered")} value={summary.total} />
        <Summary label={tr("Effective")} value={summary.active} accent />
        <Summary label={tr("Skill sources")} value={summary.sources} />
        <Summary label={tr("Needs attention")} value={summary.issues} warn={summary.issues > 0} />
      </div>

      <div className="rounded-xl border border-line bg-panel/80 p-3 mb-4 flex gap-2 items-center">
        <label className="flex-1 min-w-[220px] flex items-center gap-2 rounded-lg border border-line bg-paper px-3 h-10 focus-within:border-accent focus-within:ring-2 focus-within:ring-accentSoft">
          <Icon name="search" size={16} className="text-muted" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={tr("Search Skills by name, purpose, or tag")}
            className="min-w-0 flex-1 bg-transparent outline-none text-[13px] placeholder:text-faint"
          />
        </label>
        <select
          value={source}
          onChange={(event) => setSource(event.target.value)}
          aria-label={tr("Filter by source")}
          className="h-10 min-w-[150px] rounded-lg border border-line bg-paper px-3 text-[12.5px] outline-none focus:border-accent"
        >
          <option value="all">{tr("All sources")}</option>
          {sources.map(([value, label]) => (
            <option key={value} value={value}>{tr(label)}</option>
          ))}
        </select>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value as StatusFilter)}
          aria-label={tr("Filter by status")}
          className="h-10 min-w-[140px] rounded-lg border border-line bg-paper px-3 text-[12.5px] outline-none focus:border-accent"
        >
          <option value="all">{tr("All statuses")}</option>
          <option value="active">{tr("Effective")}</option>
          <option value="shadowed">{tr("Overridden")}</option>
          <option value="issues">{tr("Needs attention")}</option>
        </select>
        <button
          onClick={load}
          className="w-10 h-10 rounded-lg border border-line bg-paper grid place-items-center text-muted hover:text-accent hover:border-accent"
          aria-label={tr("Refresh Skill catalog")}
          title={tr("Refresh Skill catalog")}
        >
          <Icon name="refresh" size={16} />
        </button>
      </div>

      {loading ? (
        <Message title={tr("Scanning Skill sources…")} body={tr("Checking local and project Skill directories.")} />
      ) : error ? (
        <Message title={tr("Skill Hub is unavailable")} body={error} action={tr("Try again")} onAction={load} />
      ) : summary.total === 0 ? (
        <Message
          title={tr("No Skills found")}
          body={tr("Add a SKILL.md folder to a Smallink, Codex, shared agent, or project Skill directory.")}
        />
      ) : filtered.length === 0 ? (
        <Message title={tr("No matching Skills")} body={tr("Change the search or filters to see more results.")} />
      ) : (
        <div className={selected ? "grid grid-cols-[minmax(0,1fr)_360px] gap-4 items-start" : ""}>
          <div className={selected ? "grid grid-cols-1 gap-3" : "grid grid-cols-2 gap-3"}>
            {filtered.map((skill) => (
              <SkillCard
                key={skill.id}
                skill={skill}
                selected={selected === skill.id}
                onClick={() => openDetail(skill)}
              />
            ))}
          </div>
          {selected && (
            <SkillDetailPanel
              detail={detail}
              loading={detailLoading}
              error={detailError}
              onClose={() => {
                setSelected(null);
                setDetail(null);
              }}
            />
          )}
        </div>
      )}
      {createMode && (
        <SkillCreateModal
          mode={createMode}
          workspace={workspace}
          onClose={() => setCreateMode(null)}
          onCreated={(skill) => {
            setCreateMode(null);
            setSelected(skill.id);
            setDetail(skill);
            load();
          }}
        />
      )}
    </section>
  );
}

function SkillCreateModal({
  mode,
  workspace,
  onClose,
  onCreated,
}: {
  mode: "manual" | "import";
  workspace?: string;
  onClose: () => void;
  onCreated: (skill: SkillDetail) => void;
}) {
  const { tr } = useI18n();
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [scope, setScope] = useState<"user" | "project">("user");
  const [sourcePath, setSourcePath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const skill = mode === "manual"
        ? await createSkill({
            name,
            display_name: displayName,
            description,
            short_description: description,
            instructions,
            scope,
            workspace,
          })
        : await importSkill({ path: sourcePath, scope, workspace });
      onCreated(skill);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Could not save this Skill."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50" data-testid="skill-create-modal">
      <div className="absolute inset-0 bg-ink/25" onClick={() => !busy && onClose()} />
      <form
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-label={tr(mode === "manual" ? "Create a Skill" : "Import a Skill")}
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[540px] max-w-[calc(100vw-2rem)] max-h-[calc(100vh-2rem)] overflow-y-auto hairline-scroll rounded-xl border border-line bg-panel shadow-2xl"
      >
        <div className="sticky top-0 z-10 flex items-start gap-3 border-b border-line bg-panel/95 px-5 py-4">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-accentSoft to-paper text-accent grid place-items-center shrink-0">
            <Icon name={mode === "manual" ? "pencil" : "folderPlus"} size={17} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-[16px] font-semibold text-heading">
              {tr(mode === "manual" ? "Create a Skill" : "Import a Skill")}
            </h3>
            <p className="text-[11.5px] text-muted mt-0.5">
              {tr(mode === "manual"
                ? "Define a reusable workflow that agents can load when it matches a task."
                : "Choose a Skill folder or .zip package. Its complete file structure is copied into Smallink.")}
            </p>
          </div>
          <button type="button" onClick={onClose} className="w-8 h-8 grid place-items-center rounded-lg text-muted hover:bg-paper hover:text-ink" aria-label={tr("Close")}>
            <Icon name="x" size={16} />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {mode === "manual" ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Field label={tr("Skill name")} hint={tr("Lowercase letters, numbers, and hyphens") }>
                  <input required value={name} onChange={(event) => setName(event.target.value.toLowerCase().replace(/\s+/g, "-"))} placeholder="meeting-followup" className="skill-form-input font-mono" />
                </Field>
                <Field label={tr("Display name")}>
                  <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder={tr("Meeting follow-up")} className="skill-form-input" />
                </Field>
              </div>
              <Field label={tr("When should agents use it?")}>
                <textarea required value={description} onChange={(event) => setDescription(event.target.value)} rows={3} placeholder={tr("Describe the task, trigger, and expected outcome.")} className="skill-form-input resize-none" />
              </Field>
              <Field label={tr("Instructions")} hint={tr("Write the reusable steps, constraints, and output format.")}>
                <textarea required value={instructions} onChange={(event) => setInstructions(event.target.value)} rows={8} placeholder={tr("1. Gather the required context…")} className="skill-form-input resize-y font-mono text-[11.5px] leading-5" />
              </Field>
            </>
          ) : (
            <Field label={tr("Skill package")} hint={tr("The folder or archive must contain one valid SKILL.md file.")}>
              <div className="space-y-2">
                <div className="skill-form-input min-h-10 text-[11.5px] text-muted truncate flex items-center gap-2">
                  {sourcePath && (
                    <span className="shrink-0 rounded bg-accentSoft px-1.5 py-0.5 text-[9.5px] font-medium text-accent">
                      {tr(sourcePath.toLowerCase().endsWith(".zip") ? "ZIP package" : "Folder")}
                    </span>
                  )}
                  <span className="truncate">{sourcePath || tr("No Skill package selected")}</span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    aria-label={tr("Choose folder")}
                    onClick={async () => {
                      const chosen = await chooseFolder();
                      if (chosen) setSourcePath(chosen);
                    }}
                    className="h-10 px-3 inline-flex items-center justify-center gap-2 rounded-lg border border-line bg-paper text-[12px] text-ink hover:border-accent hover:text-accent"
                  >
                    <Icon name="folder" size={15} />
                    {tr("Choose folder")}
                  </button>
                  <button
                    type="button"
                    aria-label={tr("Choose ZIP")}
                    onClick={async () => {
                      const chosen = await chooseSkillArchive();
                      if (chosen) setSourcePath(chosen);
                    }}
                    className="h-10 px-3 inline-flex items-center justify-center gap-2 rounded-lg border border-line bg-paper text-[12px] text-ink hover:border-accent hover:text-accent"
                  >
                    <Icon name="archive" size={15} />
                    {tr("Choose ZIP")}
                  </button>
                </div>
              </div>
            </Field>
          )}

          <Field label={tr("Save to") }>
            <div className="grid grid-cols-2 gap-2">
              <ScopeChoice active={scope === "user"} title={tr("My Skills")} body={tr("Available in every workspace on this Mac.")} onClick={() => setScope("user")} />
              <ScopeChoice active={scope === "project"} disabled={!workspace} title={tr("Current project")} body={workspace ? tr("Available only in the open workspace.") : tr("Open a workspace to use project scope.")} onClick={() => workspace && setScope("project")} />
            </div>
          </Field>

          {error && <div className="rounded-lg bg-dangerSoft px-3 py-2 text-[11.5px] text-danger">{error}</div>}
        </div>

        <div className="sticky bottom-0 flex items-center justify-end gap-2 border-t border-line bg-panel/95 px-5 py-3">
          <button type="button" onClick={onClose} disabled={busy} className="h-9 px-3 rounded-lg text-[12px] text-muted hover:bg-paper">{tr("Cancel")}</button>
          <button type="submit" disabled={busy || (mode === "import" ? !sourcePath : !name || !description || !instructions)} className="h-9 px-4 rounded-lg bg-gradient-to-r from-primary to-accent text-onAccent text-[12px] font-medium disabled:opacity-40">
            {busy ? tr("Saving…") : tr(mode === "manual" ? "Create Skill" : "Import Skill")}
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[11.5px] font-medium text-heading">{label}</span>
      {hint && <span className="ml-2 text-[10.5px] text-faint">{hint}</span>}
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

function ScopeChoice({ active, disabled, title, body, onClick }: { active: boolean; disabled?: boolean; title: string; body: string; onClick: () => void }) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} className={`text-left rounded-lg border px-3 py-2.5 ${active ? "border-accent bg-accentSoft/70 ring-1 ring-accentSoft" : "border-line bg-paper hover:border-accent"} disabled:opacity-45 disabled:hover:border-line`}>
      <div className="text-[12px] font-medium text-heading">{title}</div>
      <div className="text-[10.5px] text-muted mt-0.5 leading-4">{body}</div>
    </button>
  );
}

function Summary({
  label,
  value,
  accent,
  warn,
}: {
  label: string;
  value: number;
  accent?: boolean;
  warn?: boolean;
}) {
  return (
    <div className="rounded-xl border border-line bg-gradient-to-br from-panel to-paper px-4 py-3">
      <div className="text-[11.5px] text-muted">{label}</div>
      <div className={"text-[23px] font-semibold mt-0.5 " + (warn ? "text-danger" : accent ? "text-accent" : "text-heading")}>
        {value}
      </div>
    </div>
  );
}

function SkillCard({
  skill,
  selected,
  onClick,
}: {
  skill: SkillCatalogItem;
  selected: boolean;
  onClick: () => void;
}) {
  const { tr } = useI18n();
  const state = statusOf(skill);
  const resources = Object.values(skill.resources).reduce((total, count) => total + count, 0);
  return (
    <button
      onClick={onClick}
      aria-pressed={selected}
      aria-label={tr("Open {name} Skill details", { name: skill.display_name })}
      className={
        "text-left min-h-[166px] rounded-xl border p-4 transition-all bg-gradient-to-br from-panel to-paper hover:border-accent hover:-translate-y-px " +
        (selected ? "border-accent ring-2 ring-accentSoft shadow-sm" : "border-line")
      }
    >
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-accentSoft to-paper text-accent grid place-items-center shrink-0">
          <Icon name="sparkle" size={17} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <h3 className="text-[14px] font-semibold text-heading leading-5 truncate">{skill.display_name}</h3>
            <StatusChip state={state} />
          </div>
          <div className="text-[11px] font-mono text-faint mt-0.5 truncate">{skill.name}</div>
        </div>
        <Icon name="chevronRight" size={15} className="text-faint shrink-0 mt-1" />
      </div>
      <p className="mt-3 text-[12.5px] leading-5 text-muted line-clamp-2">
        {skill.short_description || skill.description || tr("No description provided.")}
      </p>
      <div className="mt-3 pt-3 border-t border-line flex items-center gap-2 text-[11px] text-faint">
        <span className="truncate">{tr(skill.source_label)}</span>
        <span>·</span>
        <span>{tr(skill.scope === "project" ? "Project" : skill.scope === "builtin" ? "Built in" : "User")}</span>
        <span className="ml-auto shrink-0">{skill.allowed_tools.length} {tr("tools")} · {resources} {tr("resources")}</span>
      </div>
    </button>
  );
}

function StatusChip({ state }: { state: Exclude<StatusFilter, "all"> }) {
  const { tr } = useI18n();
  const copy =
    state === "active" ? tr("Effective") : state === "shadowed" ? tr("Overridden") : tr("Needs attention");
  const color =
    state === "active"
      ? "bg-accentSoft text-accent"
      : state === "issues"
        ? "bg-dangerSoft text-danger"
        : "bg-paper text-muted border border-line";
  return <span className={`ml-auto shrink-0 rounded-full px-2 py-0.5 text-[10.5px] ${color}`}>{copy}</span>;
}

function SkillDetailPanel({
  detail,
  loading,
  error,
  onClose,
}: {
  detail: SkillDetail | null;
  loading: boolean;
  error: string;
  onClose: () => void;
}) {
  const { tr } = useI18n();
  return (
    <aside className="sticky top-4 rounded-xl border border-line bg-gradient-to-br from-panel to-paper shadow-sm max-h-[calc(100vh-150px)] overflow-y-auto hairline-scroll">
      <div className="sticky top-0 z-10 border-b border-line bg-panel/95 px-4 py-3 flex items-center">
        <div className="text-[13px] font-semibold text-heading">{tr("Skill details")}</div>
        <button
          onClick={onClose}
          className="ml-auto w-7 h-7 rounded-lg grid place-items-center text-muted hover:bg-accentSoft hover:text-accent"
          aria-label={tr("Close")}
          title={tr("Close")}
        >
          <Icon name="x" size={15} />
        </button>
      </div>
      {loading ? (
        <div className="p-5 text-[12.5px] text-muted">{tr("Loading Skill instructions…")}</div>
      ) : error ? (
        <div className="p-5 text-[12.5px] text-danger">{error}</div>
      ) : detail ? (
        <div className="p-4 space-y-4">
          <div>
            <h3 className="text-[17px] font-semibold text-heading">{detail.display_name}</h3>
            <div className="text-[11px] font-mono text-faint mt-0.5">{detail.name}</div>
            <p className="text-[12.5px] text-muted leading-5 mt-2">{detail.description || tr("No description provided.")}</p>
          </div>
          <DetailGroup title={tr("Source")}>
            <DetailRow label={tr("Location")} value={tr(detail.source_label)} />
            <DetailRow label={tr("Scope")} value={tr(detail.scope === "project" ? "Project" : detail.scope === "builtin" ? "Built in" : "User")} />
            <div className="mt-2 rounded-lg bg-paper px-3 py-2 text-[10.5px] leading-4 text-faint font-mono break-all">{detail.path}</div>
          </DetailGroup>
          {(detail.errors.length > 0 || detail.warnings.length > 0) && (
            <DetailGroup title={tr("Diagnostics")}>
              {[...detail.errors, ...detail.warnings].map((item) => (
                <div key={item} className="text-[11.5px] leading-5 text-danger">{item}</div>
              ))}
            </DetailGroup>
          )}
          <DetailGroup title={tr("Dependencies")}>
            <div className="text-[11.5px] text-muted">
              {detail.allowed_tools.length
                ? detail.allowed_tools.join(", ")
                : tr("No tools declared. Runtime permissions still apply.")}
            </div>
            <div className="grid grid-cols-4 gap-2 mt-3">
              {(["scripts", "references", "assets", "other"] as const).map((name) => (
                <div key={name} className="rounded-lg border border-line bg-paper px-2 py-2 text-center">
                  <div className="text-[15px] font-semibold text-heading">{detail.resources[name]}</div>
                  <div className="text-[10px] text-faint">{tr(name[0].toUpperCase() + name.slice(1))}</div>
                </div>
              ))}
            </div>
          </DetailGroup>
          <DetailGroup title={tr("Skill instructions")}>
            <pre className="whitespace-pre-wrap break-words rounded-lg border border-line bg-paper p-3 text-[11px] leading-5 text-ink font-mono">
              {detail.instructions || tr("No instructions provided.")}
            </pre>
          </DetailGroup>
        </div>
      ) : null}
    </aside>
  );
}

function DetailGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-line pt-3">
      <div className="text-[11px] font-semibold uppercase text-faint mb-2">{title}</div>
      {children}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 text-[11.5px] leading-5">
      <span className="text-faint">{label}</span>
      <span className="ml-auto text-ink text-right">{value}</span>
    </div>
  );
}

function Message({
  title,
  body,
  action,
  onAction,
}: {
  title: string;
  body: string;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <div className="rounded-xl border border-line bg-gradient-to-br from-panel to-paper px-6 py-12 text-center">
      <div className="mx-auto w-10 h-10 rounded-full bg-accentSoft text-accent grid place-items-center">
        <Icon name="sparkle" size={18} />
      </div>
      <h3 className="mt-3 text-[14px] font-semibold text-heading">{title}</h3>
      <p className="mt-1 text-[12.5px] text-muted">{body}</p>
      {action && onAction && (
        <button onClick={onAction} className="mt-4 rounded-lg bg-accent text-onAccent px-3 py-2 text-[12px]">
          {action}
        </button>
      )}
    </div>
  );
}
