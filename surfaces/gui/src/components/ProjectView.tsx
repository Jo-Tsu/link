import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  getProjectOverview,
  getSensoryProvenance,
  indexProjectKnowledge,
  searchKnowledge,
  setKnowledgeArchived,
  type KnowledgeItem,
  type KnowledgeSearchResult,
  type MemoryRecord,
  type ProjectAssetRef,
  type ProjectOverview,
  type SensoryProvenance,
  type SensoryRecord,
} from "../api";
import { useI18n } from "../i18n";
import type { SessionInfo } from "../types";
import { InlineFeedback, PageState } from "./AsyncFeedback";
import { Icon, type IconName } from "./Icon";

type ProjectTab = "overview" | "conversations" | "sources" | "knowledge" | "memory" | "assets";

function parseSourceContent(record: SensoryRecord): unknown {
  try {
    return JSON.parse(record.normalized_content || record.raw_content);
  } catch {
    return record.normalized_content || record.raw_content;
  }
}

function readableContent(value: unknown): string {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return String(value ?? "");
  const object = value as Record<string, any>;
  for (const key of ["text", "content", "message", "title", "summary", "result", "output"]) {
    const found = object[key];
    if (typeof found === "string" && found.trim()) return found;
  }
  return JSON.stringify(value, null, 2);
}

function shortText(value: string, limit = 150): string {
  const clean = value.replace(/\s+/g, " ").trim();
  return clean.length > limit ? `${clean.slice(0, limit)}...` : clean;
}

function sourceTitle(record: SensoryRecord): string {
  const content = readableContent(parseSourceContent(record));
  return shortText(content, 110) || record.content_type;
}

export function ProjectView({
  projectId,
  onBack,
  onNewSession,
  onOpenSession,
  onOpenApplication,
}: {
  projectId: string;
  onBack: () => void;
  onNewSession: (projectId: string) => void;
  onOpenSession: (session: SessionInfo) => void;
  onOpenApplication: (appId: string) => void;
}) {
  const { locale, tr } = useI18n();
  const [data, setData] = useState<ProjectOverview | null>(null);
  const [tab, setTab] = useState<ProjectTab>("overview");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [provenance, setProvenance] = useState<SensoryProvenance | null>(null);
  const [provenanceLoading, setProvenanceLoading] = useState(false);
  const [knowledgeQuery, setKnowledgeQuery] = useState("");
  const [knowledgeResults, setKnowledgeResults] = useState<KnowledgeSearchResult[]>([]);
  const [knowledgeSearching, setKnowledgeSearching] = useState(false);
  const [knowledgeIndexing, setKnowledgeIndexing] = useState(false);
  const [knowledgeNotice, setKnowledgeNotice] = useState("");

  const formatter = useMemo(
    () => new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
    [locale],
  );
  const date = (value?: string | null) => {
    if (!value) return "";
    const parsed = new Date(value);
    return Number.isNaN(parsed.valueOf()) ? value : formatter.format(parsed);
  };

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      setData(await getProjectOverview(projectId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Could not load project"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setTab("overview");
    setProvenance(null);
    setKnowledgeQuery("");
    setKnowledgeResults([]);
    setKnowledgeNotice("");
    void load();
  }, [projectId]);

  const openSource = async (recordId: string | null | undefined) => {
    if (!recordId) return;
    setProvenanceLoading(true);
    setError("");
    try {
      setProvenance(await getSensoryProvenance(recordId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Could not load source provenance"));
    } finally {
      setProvenanceLoading(false);
    }
  };

  const runKnowledgeSearch = async () => {
    const query = knowledgeQuery.trim();
    if (!query) return;
    setKnowledgeSearching(true);
    setKnowledgeNotice("");
    try {
      const result = await searchKnowledge(query, { projectId, limit: 20 });
      setKnowledgeResults(result.results);
      if (!result.results.length) setKnowledgeNotice(tr("No matching knowledge found."));
    } catch (reason) {
      setKnowledgeNotice(reason instanceof Error ? reason.message : tr("Could not search project knowledge."));
    } finally {
      setKnowledgeSearching(false);
    }
  };

  const indexKnowledge = async () => {
    setKnowledgeIndexing(true);
    setKnowledgeNotice("");
    try {
      const result = await indexProjectKnowledge(projectId);
      setKnowledgeNotice(tr("Indexed {count} source records; skipped {skipped}.", { count: result.indexed, skipped: result.skipped }));
      await load();
    } catch (reason) {
      setKnowledgeNotice(reason instanceof Error ? reason.message : tr("Could not index project knowledge."));
    } finally {
      setKnowledgeIndexing(false);
    }
  };

  const archiveKnowledge = async (item: KnowledgeItem) => {
    setKnowledgeNotice("");
    try {
      await setKnowledgeArchived(item.item_id, true);
      setData((current) => current ? {
        ...current,
        metrics: { ...current.metrics, knowledge: Math.max(0, current.metrics.knowledge - 1) },
        knowledge: current.knowledge.filter((entry) => entry.item_id !== item.item_id),
      } : current);
      setKnowledgeResults((current) => current.filter((entry) => entry.item_id !== item.item_id));
    } catch (reason) {
      setKnowledgeNotice(reason instanceof Error ? reason.message : tr("Could not archive knowledge."));
    }
  };

  if (loading) {
    return <main className="flex-1 min-w-0 bg-paper p-6"><PageState icon="folder" title={tr("Loading project...")} body={tr("Collecting conversations, source records, tasks, assets, and memory.")} /></main>;
  }

  if (!data) {
    return (
      <main className="flex-1 min-w-0 bg-paper p-6">
        <PageState icon="folder" title={tr("Project unavailable")} body={error || tr("This project could not be loaded.")} action={tr("Back")} onAction={onBack} />
      </main>
    );
  }

  const tabs: Array<[ProjectTab, string, number]> = [
    ["overview", "Overview", 0],
    ["conversations", "Conversations", data.metrics.sessions],
    ["sources", "Source records", data.metrics.source_records],
    ["knowledge", "Knowledge", data.metrics.knowledge],
    ["memory", "Memory", data.metrics.memories],
    ["assets", "Assets", data.metrics.app_assets],
  ];

  return (
    <main className="flex-1 min-w-0 bg-paper flex flex-col overflow-hidden">
      <header className="shrink-0 border-b border-line bg-panel/55 px-7 pt-5">
        <div className="flex items-start gap-3 max-w-7xl w-full mx-auto">
          <button className="w-8 h-8 grid place-items-center rounded-lg text-muted hover:text-ink hover:bg-paper" title={tr("Back")} onClick={onBack}><Icon name="arrowLeft" size={16} /></button>
          <span className="w-9 h-9 rounded-full bg-accentSoft text-accent grid place-items-center shrink-0"><Icon name="folder" size={17} /></span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h1 className="text-[20px] font-semibold text-heading truncate">{data.project.name}</h1>
              {data.project.project_type === "system_app" && <span className="rounded-full border border-accent/25 bg-accentSoft/30 px-2 py-0.5 text-[10px] text-accent">{tr("Application project")}</span>}
            </div>
            <p className="text-[11.5px] text-muted mt-0.5 truncate">{data.project.description || data.project.workspace_path}</p>
          </div>
          {data.project.owner_app_id && (
            <button className="h-9 px-3.5 rounded-lg border border-line bg-panel text-[12px] text-ink" onClick={() => onOpenApplication(data.project.owner_app_id || "")}>{tr("Open application")}</button>
          )}
          <button className="h-9 px-3.5 rounded-lg bg-accent text-onAccent text-[12px] font-medium" onClick={() => onNewSession(projectId)}>{tr("New conversation")}</button>
        </div>
        <div className="max-w-7xl w-full mx-auto flex gap-1 mt-4 overflow-x-auto" role="tablist">
          {tabs.map(([key, label, count]) => (
            <button key={key} role="tab" aria-selected={tab === key} className={`px-3 py-2 border-b-2 text-[12px] whitespace-nowrap ${tab === key ? "border-accent text-accent font-medium" : "border-transparent text-muted hover:text-ink"}`} onClick={() => setTab(key)}>
              {tr(label)}{key !== "overview" ? ` ${count}` : ""}
            </button>
          ))}
        </div>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto px-7 py-6">
        <div className="max-w-7xl w-full mx-auto">
          {error && <div className="mb-5"><InlineFeedback tone="danger" title={tr("Project request failed")} body={error} action={tr("Retry")} onAction={() => void load()} /></div>}
          {tab === "overview" && <Overview data={data} date={date} onOpenSource={openSource} onOpenSession={onOpenSession} />}
          {tab === "conversations" && <ConversationRows rows={data.sessions} date={date} onOpen={onOpenSession} />}
          {tab === "sources" && <SourceRows rows={data.source_records} date={date} onOpen={openSource} />}
          {tab === "knowledge" && <KnowledgePanel items={data.knowledge} query={knowledgeQuery} results={knowledgeResults} searching={knowledgeSearching} indexing={knowledgeIndexing} notice={knowledgeNotice} date={date} onQueryChange={setKnowledgeQuery} onSearch={runKnowledgeSearch} onIndex={indexKnowledge} onArchive={archiveKnowledge} onOpenSource={openSource} />}
          {tab === "memory" && <MemoryRows rows={data.memories} date={date} onOpenSource={openSource} />}
          {tab === "assets" && <AssetRows rows={data.app_assets} date={date} onOpenSource={openSource} />}
        </div>
      </div>

      {provenanceLoading && <div className="fixed inset-0 z-[95] bg-ink/20 grid place-items-center"><div className="rounded-lg border border-line bg-panel px-5 py-4 text-[12px] text-muted shadow-xl">{tr("Loading source provenance...")}</div></div>}
      {provenance && <ProvenanceDialog value={provenance} date={date} onClose={() => setProvenance(null)} />}
    </main>
  );
}

function Overview({ data, date, onOpenSource, onOpenSession }: { data: ProjectOverview; date: (value?: string | null) => string; onOpenSource: (id: string) => void; onOpenSession: (session: SessionInfo) => void }) {
  const { tr } = useI18n();
  const metrics: Array<[IconName, string, number]> = [
    ["chat", "Conversations", data.metrics.sessions],
    ["branch", "Tasks", data.metrics.tasks],
    ["file", "Source records", data.metrics.source_records],
    ["search", "Knowledge", data.metrics.knowledge],
    ["clock", "Pending governance", data.metrics.pending_governance],
    ["sparkle", "Memory candidates", data.metrics.memory_candidates],
    ["diamond", "Confirmed memory", data.metrics.memories],
  ];
  return (
    <>
      <section className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 border-y border-line divide-x divide-line bg-panel/35">
        {metrics.map(([icon, label, value]) => <div key={label} className="px-4 py-4 min-w-0"><div className="flex items-center gap-1.5 text-[11px] text-muted"><Icon name={icon} size={13} /> <span className="truncate">{tr(label)}</span></div><div className="text-[22px] font-semibold text-heading mt-1">{value}</div></div>)}
      </section>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-8 mt-7">
        <section>
          <SectionHeading title={tr("Recent conversations")} />
          <ConversationRows rows={data.sessions.slice(0, 6)} date={date} onOpen={onOpenSession} compact />
        </section>
        <section>
          <SectionHeading title={tr("Recent source records")} />
          <SourceRows rows={data.source_records.slice(0, 6)} date={date} onOpen={onOpenSource} compact />
        </section>
      </div>
      <section className="mt-8">
        <SectionHeading title={tr("Data flow status")} />
        <div className="grid grid-cols-1 sm:grid-cols-5 border-y border-line divide-y sm:divide-y-0 sm:divide-x divide-line">
          {(["pending", "processing", "processed", "skipped", "failed"] as const).map((status) => <div key={status} className="px-4 py-3"><div className="text-[11px] text-muted">{tr(status)}</div><div className="text-[17px] text-heading font-semibold mt-0.5">{data.source_statuses[status] || 0}</div></div>)}
        </div>
      </section>
    </>
  );
}

function KnowledgePanel({
  items,
  query,
  results,
  searching,
  indexing,
  notice,
  date,
  onQueryChange,
  onSearch,
  onIndex,
  onArchive,
  onOpenSource,
}: {
  items: KnowledgeItem[];
  query: string;
  results: KnowledgeSearchResult[];
  searching: boolean;
  indexing: boolean;
  notice: string;
  date: (value?: string | null) => string;
  onQueryChange: (value: string) => void;
  onSearch: () => void;
  onIndex: () => void;
  onArchive: (item: KnowledgeItem) => void;
  onOpenSource: (id: string) => void;
}) {
  const { tr } = useI18n();
  return (
    <div className="space-y-8">
      <section>
        <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-line">
          <div>
            <h2 className="text-[13px] font-semibold text-heading">{tr("Project knowledge retrieval")}</h2>
            <p className="text-[10.5px] text-muted mt-0.5">{tr("Search indexed project content with explainable relevance and source citations.")}</p>
          </div>
          <button type="button" className="h-8 px-3 rounded-lg border border-line bg-panel text-[11.5px] text-ink hover:border-accent/40 disabled:opacity-50" disabled={indexing} onClick={() => void onIndex()}>
            {indexing ? tr("Indexing...") : tr("Index source records")}
          </button>
        </div>
        <form className="mt-4 flex gap-2" onSubmit={(event) => { event.preventDefault(); void onSearch(); }}>
          <label className="flex-1 min-w-0 h-10 rounded-lg border border-line bg-panel flex items-center gap-2 px-3 focus-within:border-accent/60">
            <Icon name="search" size={15} className="text-muted shrink-0" />
            <input className="w-full bg-transparent outline-none text-[12.5px] text-ink placeholder:text-faint" value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={tr("Search project documents and application materials")} aria-label={tr("Search project knowledge")} />
          </label>
          <button type="submit" className="h-10 px-4 rounded-lg bg-accent text-onAccent text-[12px] font-medium disabled:opacity-50" disabled={!query.trim() || searching}>{searching ? tr("Searching...") : tr("Search")}</button>
        </form>
        {notice && <p className="mt-2 text-[11px] text-muted">{notice}</p>}
      </section>

      {results.length > 0 && (
        <section>
          <SectionHeading title={tr("Search results")} />
          <div className="divide-y divide-line">
            {results.map((result) => (
              <article key={result.chunk_id} className="py-4">
                <div className="flex items-start gap-4">
                  <div className="min-w-0 flex-1">
                    <h3 className="text-[12.5px] font-medium text-heading">{result.title}</h3>
                    <p className="text-[12px] text-ink leading-relaxed mt-1.5 whitespace-pre-wrap">{shortText(result.content, 420)}</p>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-[10px] text-muted">
                      <span>{tr("Relevance")}: {Math.round(result.score * 100)}%</span>
                      <span>{tr("Term coverage")}: {Math.round(result.score_components.term_coverage * 100)}%</span>
                      {result.score_components.exact_phrase > 0 && <span>{tr("Exact phrase match")}</span>}
                      <span>{tr("Source")}: {result.citation.source_type}</span>
                    </div>
                  </div>
                  {result.citation.source_record_id && <button type="button" className="h-8 px-2.5 rounded-lg border border-line text-[10.5px] text-accent hover:bg-accentSoft/30 shrink-0" onClick={() => onOpenSource(result.citation.source_record_id || "")}>{tr("View source")}</button>}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      <section>
        <SectionHeading title={tr("Indexed knowledge")} />
        {!items.length ? (
          <PageState icon="search" title={tr("No indexed knowledge yet")} body={tr("Index the project's source records or sync application materials first.")} />
        ) : (
          <div className="divide-y divide-line">
            {items.map((item) => (
              <article key={item.item_id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 py-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-[12.5px] font-medium text-heading truncate">{item.title}</h3>
                    <span className="text-[9.5px] text-accent">v{item.current_version}</span>
                  </div>
                  <p className="text-[11.5px] text-ink leading-relaxed mt-1.5">{shortText(item.content, 320)}</p>
                  <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2 text-[10px] text-muted">
                    <span>{item.source_type}</span><span>{tr("{count} chunks", { count: item.chunk_count })}</span><span>{date(item.updated_at)}</span>
                    {item.source_record_id && <button type="button" className="text-accent hover:underline" onClick={() => onOpenSource(item.source_record_id || "")}>{tr("View source")}</button>}
                  </div>
                </div>
                <button type="button" className="w-8 h-8 grid place-items-center rounded-lg text-muted hover:text-ink hover:bg-paper" title={tr("Archive knowledge")} onClick={() => void onArchive(item)}><Icon name="archive" size={14} /></button>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function SectionHeading({ title }: { title: string }) {
  return <h2 className="text-[13px] font-semibold text-heading pb-2 border-b border-line">{title}</h2>;
}

function ConversationRows({ rows, date, onOpen, compact = false }: { rows: SessionInfo[]; date: (value?: string | null) => string; onOpen: (session: SessionInfo) => void; compact?: boolean }) {
  const { tr } = useI18n();
  if (!rows.length) return <EmptyLine text={tr("No conversations in this project yet.")} />;
  return <div className="divide-y divide-line">{rows.map((session) => <button key={session.session_id} className={`w-full text-left grid grid-cols-[minmax(0,1fr)_110px_18px] gap-3 items-center hover:bg-panel/60 ${compact ? "py-2.5" : "px-3 py-3"}`} onClick={() => onOpen(session)}><span className="min-w-0"><span className="block text-[12.5px] text-ink truncate">{session.title || tr("Untitled conversation")}</span><span className="block text-[10.5px] text-faint mt-0.5">{session.agent}</span></span><span className="text-[10.5px] text-muted text-right">{date(session.updated_at)}</span><Icon name="chevronRight" size={13} className="text-faint" /></button>)}</div>;
}

function SourceRows({ rows, date, onOpen, compact = false }: { rows: SensoryRecord[]; date: (value?: string | null) => string; onOpen: (id: string) => void; compact?: boolean }) {
  const { tr } = useI18n();
  if (!rows.length) return <EmptyLine text={tr("No source records in this project yet.")} />;
  return <div className="divide-y divide-line">{rows.map((record) => <button key={record.record_id} className={`w-full text-left grid grid-cols-[92px_minmax(0,1fr)_115px_18px] gap-3 items-center hover:bg-panel/60 ${compact ? "py-2.5" : "px-3 py-3"}`} onClick={() => onOpen(record.record_id)}><span className="text-[10px] text-accent font-semibold uppercase truncate">{tr(record.content_type)}</span><span className="min-w-0"><span className="block text-[12.5px] text-ink truncate">{sourceTitle(record)}</span><span className="block text-[10.5px] text-faint mt-0.5">{record.source_type} · {tr(record.governance_status)}</span></span><span className="text-[10.5px] text-muted text-right">{date(record.occurred_at)}</span><Icon name="chevronRight" size={13} className="text-faint" /></button>)}</div>;
}

function MemoryRows({ rows, date, onOpenSource }: { rows: MemoryRecord[]; date: (value?: string | null) => string; onOpenSource: (id: string) => void }) {
  const { tr } = useI18n();
  if (!rows.length) return <PageState icon="diamond" title={tr("No confirmed memory yet")} body={tr("AI-generated candidates appear here after you confirm them.")} />;
  return <div className="border-y border-line divide-y divide-line">{rows.map((memory) => <button key={memory.id} className="w-full text-left grid grid-cols-[140px_minmax(0,1fr)_120px_18px] gap-3 items-start px-3 py-4 hover:bg-panel/60 disabled:cursor-default" disabled={!memory.source_record_id} onClick={() => memory.source_record_id && onOpenSource(memory.source_record_id)}><span className="text-[10.5px] text-accent font-medium">{tr(memory.key || "untyped")}</span><span className="text-[12.5px] text-ink leading-relaxed">{memory.content}</span><span className="text-[10.5px] text-muted text-right">{date(memory.updated_at || memory.created_at)}</span>{memory.source_record_id ? <Icon name="chevronRight" size={13} className="text-faint mt-0.5" /> : <span />}</button>)}</div>;
}

function AssetRows({ rows, date, onOpenSource }: { rows: ProjectAssetRef[]; date: (value?: string | null) => string; onOpenSource: (id: string) => void }) {
  const { tr } = useI18n();
  if (!rows.length) return <PageState icon="file" title={tr("No tracked application assets")} body={tr("Assets appear after the application lists, reads, imports, or changes them.")} />;
  return <div className="border-y border-line divide-y divide-line">{rows.map((asset) => <button key={asset.asset_ref_id} className="w-full text-left grid grid-cols-[100px_minmax(0,1fr)_130px_18px] gap-3 items-center px-3 py-3 hover:bg-panel/60 disabled:cursor-default" disabled={!asset.sensory_record_id} onClick={() => asset.sensory_record_id && onOpenSource(asset.sensory_record_id)}><span className="text-[10.5px] text-accent font-medium uppercase">{tr(asset.asset_type || "asset")}</span><span className="min-w-0"><span className="block text-[12.5px] text-ink truncate">{asset.title || asset.external_code || asset.external_asset_id}</span><span className="block text-[10.5px] text-faint mt-0.5 truncate">{asset.external_code || asset.external_asset_id}</span></span><span className="text-[10.5px] text-muted text-right">{date(asset.last_seen_at)}</span>{asset.sensory_record_id ? <Icon name="chevronRight" size={13} className="text-faint" /> : <span />}</button>)}</div>;
}

function EmptyLine({ text }: { text: string }) {
  return <div className="py-8 text-center text-[12px] text-faint border-b border-line">{text}</div>;
}

function ProvenanceDialog({ value, date, onClose }: { value: SensoryProvenance; date: (value?: string | null) => string; onClose: () => void }) {
  const { tr } = useI18n();
  const source = value.source;
  const stages = [
    ["Source", 1],
    ["AI candidates", value.candidates.length],
    ["Human decisions", value.decisions.length],
    ["Formal memory", value.memories.length],
    ["Memory uses", value.usages.length],
  ] as const;
  return (
    <div className="fixed inset-0 z-[90] bg-ink/30 flex justify-end" role="dialog" aria-modal="true" aria-label={tr("Source provenance")} onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="w-full max-w-[680px] h-full bg-panel border-l border-line shadow-2xl flex flex-col">
        <header className="p-5 border-b border-line flex items-start gap-3"><span className="w-9 h-9 rounded-full bg-accentSoft text-accent grid place-items-center shrink-0"><Icon name="branch" size={17} /></span><div className="min-w-0 flex-1"><h2 className="text-[17px] font-semibold text-heading">{tr("Source provenance")}</h2><p className="text-[11px] text-muted mt-0.5">{source.source_type} · {source.content_type} · {date(source.occurred_at)}</p></div><button className="w-8 h-8 grid place-items-center rounded-lg text-muted hover:bg-paper" title={tr("Close")} onClick={onClose}><Icon name="x" size={15} /></button></header>
        <div className="flex-1 overflow-y-auto p-5">
          <div className="grid grid-cols-5 border-y border-line divide-x divide-line mb-6">{stages.map(([label, count], index) => <div key={label} className="relative px-2 py-3 text-center"><div className={`w-6 h-6 rounded-full mx-auto grid place-items-center text-[10px] font-semibold ${count ? "bg-accentSoft text-accent" : "bg-paper text-faint"}`}>{count}</div><div className="text-[10px] text-muted mt-1.5">{tr(label)}</div>{index < stages.length - 1 && <Icon name="chevronRight" size={12} className="absolute -right-[7px] top-[19px] z-10 text-faint bg-panel" />}</div>)}</div>
          <ProvenanceSection title={tr("Original source")}><div className="text-[12.5px] text-ink whitespace-pre-wrap leading-relaxed">{readableContent(parseSourceContent(source))}</div><dl className="grid grid-cols-2 gap-x-5 gap-y-2 mt-4 text-[11px]"><Meta label={tr("Governance status")} value={tr(source.governance_status)} /><Meta label={tr("Sensitivity")} value={tr(source.sensitivity)} /><Meta label={tr("Conversation")} value={source.conversation_id || tr("None")} /><Meta label={tr("Source locator")} value={source.source_locator || tr("None")} /></dl></ProvenanceSection>
          <ProvenanceSection title={tr("AI candidates")} empty={!value.candidates.length}>{value.candidates.map((candidate) => <div key={candidate.candidate_id} className="border-b border-line py-3 last:border-0"><div className="flex items-center gap-2 text-[10.5px] text-muted"><span className="text-accent">{tr(candidate.memory_type || "untyped")}</span><span>{tr(candidate.status)}</span>{candidate.confidence != null && <span>{Math.round(Number(candidate.confidence) * 100)}%</span>}</div><div className="text-[12.5px] text-ink leading-relaxed mt-1">{candidate.content}</div><div className="text-[10px] text-faint mt-1">{tr("Model")}: {candidate.model} · {candidate.prompt_version}</div></div>)}</ProvenanceSection>
          <ProvenanceSection title={tr("Human decisions")} empty={!value.decisions.length}>{value.decisions.map((decision) => <div key={decision.decision_id} className="flex items-start justify-between gap-4 border-b border-line py-3 last:border-0"><div><div className="text-[12px] text-ink">{tr(decision.action)}</div>{decision.final_content && <div className="text-[11.5px] text-muted mt-1 leading-relaxed">{decision.final_content}</div>}</div><span className="text-[10px] text-faint shrink-0">{date(decision.created_at)}</span></div>)}</ProvenanceSection>
          <ProvenanceSection title={tr("Formal memory")} empty={!value.memories.length}>{value.memories.map((memory) => <div key={memory.id} className="border-b border-line py-3 last:border-0"><div className="text-[10.5px] text-accent">{tr(memory.key || "untyped")}</div><div className="text-[12.5px] text-ink leading-relaxed mt-1">{memory.content}</div></div>)}</ProvenanceSection>
          <details className="mt-6 border-t border-line pt-4"><summary className="text-[11px] text-muted cursor-pointer">{tr("Technical source data")}</summary><pre className="mt-3 max-h-[300px] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-line bg-paper p-3 text-[10.5px] text-muted">{JSON.stringify(value, null, 2)}</pre></details>
        </div>
      </aside>
    </div>
  );
}

function ProvenanceSection({ title, empty = false, children }: { title: string; empty?: boolean; children: ReactNode }) {
  const { tr } = useI18n();
  return <section className="mt-6"><h3 className="text-[12px] font-semibold text-heading pb-2 border-b border-line">{title}</h3>{empty ? <div className="py-4 text-[11.5px] text-faint">{tr("No result at this stage yet.")}</div> : children}</section>;
}

function Meta({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="text-faint">{label}</dt><dd className="text-muted truncate mt-0.5" title={value}>{value}</dd></div>;
}
