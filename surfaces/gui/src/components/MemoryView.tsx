import { useEffect, useMemo, useState } from "react";
import {
  decideMemoryCandidate,
  deleteSensoryRecords,
  getMemory,
  getMemoryCandidate,
  getMemoryCandidates,
  getSensoryRecord,
  getSensoryRecords,
  getSensoryStats,
  runMemoryPipeline,
  type MemoryCandidate,
  type MemoryRecord,
  type SensoryRecord,
  type SensoryStats,
} from "../api";
import { baseName } from "../paths";
import { useI18n } from "../i18n";
import { InlineFeedback, PageState } from "./AsyncFeedback";
import { Icon } from "./Icon";

const MEMORY_TYPES = [
  ["user_preference", "User preferences", "Stable choices about tools, style and interaction."],
  ["project_context", "Project context", "Goals, scope, constraints and current project stage."],
  ["product_decision", "Product decisions", "Confirmed product choices and their reasoning."],
  ["reasoning_process", "Reasoning process", "How you evaluate options and reach conclusions."],
  ["open_question", "Open questions", "Important questions that still need an answer."],
  ["reusable_pattern", "Reusable patterns", "Methods and approaches worth using again."],
  ["work_habit", "Work habits", "Recurring ways you plan, review and execute work."],
  ["artifact_summary", "Artifact summaries", "Durable summaries of reports, code and deliverables."],
  ["document_insight", "Document insights", "Important conclusions extracted from documents."],
  ["life_memory", "Life memories", "Long-term personal context outside project work."],
] as const;

type MemoryType = (typeof MEMORY_TYPES)[number][0];
const KNOWN_TYPES = new Set<string>(MEMORY_TYPES.map(([key]) => key));
type MemorySurface = "home" | "pending" | "sources" | "type";

export function MemoryView() {
  const { tr } = useI18n();
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [pending, setPending] = useState<MemoryCandidate[]>([]);
  const [surface, setSurface] = useState<MemorySurface>("home");
  const [selectedType, setSelectedType] = useState<MemoryType | null>(null);
  const [selectedMemory, setSelectedMemory] = useState<MemoryRecord | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<MemoryCandidate | null>(null);
  const [sourceStats, setSourceStats] = useState<SensoryStats | null>(null);
  const [statsError, setStatsError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generateResult, setGenerateResult] = useState<{
    tone: "success" | "warning";
    body: string;
  } | null>(null);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [active, awaiting] = await Promise.all([getMemory(), getMemoryCandidates()]);
      setMemories(active);
      setPending(awaiting);
      try {
        setSourceStats(await getSensoryStats());
        setStatsError(false);
      } catch {
        setSourceStats(null);
        setStatsError(true);
      }
      return awaiting;
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("Could not load memories"));
      return null;
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const typed = useMemo(
    () => memories.filter((item) => selectedType && item.key === selectedType),
    [memories, selectedType],
  );
  const legacyCount = memories.filter((item) => !item.key || !KNOWN_TYPES.has(item.key)).length;

  const openHome = () => {
    setSurface("home");
    setSelectedType(null);
    setSelectedMemory(null);
    setSelectedCandidate(null);
  };

  const generateCandidates = async (retryFailed = false) => {
    setGenerating(true);
    setGenerateResult(null);
    try {
      const result = await runMemoryPipeline({ retry_failed: retryFailed });
      setGenerateResult({
        tone: result.failed_records > 0 ? "warning" : "success",
        body: tr("Created {created} candidates, skipped {skipped}, failed {failed}.", {
          created: result.candidates_created,
          skipped: result.skipped_records,
          failed: result.failed_records,
        }),
      });
      await load();
      if (result.candidates_created > 0) setSurface("pending");
    } catch (reason) {
      setGenerateResult({
        tone: "warning",
        body: reason instanceof Error
          ? reason.message
          : tr("Could not generate memory candidates"),
      });
    } finally {
      setGenerating(false);
    }
  };

  if (loading && surface === "home") {
    return (
      <MemoryShell>
        <PageState
          icon="diamond"
          title={tr("Loading memories…")}
          body={tr("Reading confirmed memories, candidate drafts, and source statistics.")}
        />
      </MemoryShell>
    );
  }

  if (error && surface === "home") {
    return (
      <MemoryShell>
        <PageState
          icon="diamond"
          title={tr("Memory is unavailable")}
          body={error}
          action={tr("Try again")}
          onAction={() => void load()}
        />
      </MemoryShell>
    );
  }

  if (surface === "sources") {
    return <SourceRecordsView onBack={openHome} />;
  }

  if (surface === "pending") {
    return (
      <main className="flex-1 min-w-0 min-h-0 overflow-y-auto hairline-scroll bg-paper" data-testid="memory-view">
        <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6">
          <button className="inline-flex items-center gap-1.5 text-[12px] text-muted hover:text-ink mb-4" onClick={openHome}>
            <Icon name="arrowLeft" size={14} /> {tr("Back to memory types")}
          </button>
          <div className="mb-5">
            <h1 className="text-[24px] font-semibold text-heading">{tr("Candidate memory drafts")}</h1>
            <p className="text-[12.5px] text-muted mt-0.5">{tr("AI-extracted drafts that are not used as confirmed memory.")}</p>
          </div>
          <div className="mb-4">
            <InlineFeedback
              tone="info"
              title={tr("Review before Smallink uses it")}
              body={tr("Accept, edit, merge, or ignore each candidate. Only accepted memories are available to agents.")}
            />
          </div>
          <div className="grid grid-cols-1 min-[1080px]:grid-cols-[minmax(0,1fr)_360px] gap-4 items-start">
            <section className="border border-line rounded-lg bg-panel overflow-hidden min-w-0" data-testid="memory-pending-list">
              {pending.length === 0 ? (
                <div className="px-4 py-10 text-center">
                  <div className="text-[13px] font-medium text-ink">{tr("Nothing awaiting confirmation")}</div>
                  <div className="text-[12px] text-muted mt-1">{tr("Extracted candidate memories will appear here.")}</div>
                </div>
              ) : pending.map((item) => (
                <button
                  key={item.candidate_id}
                  className={`w-full text-left px-4 py-3 border-b border-line last:border-b-0 hover:bg-paper/70 ${
                    selectedCandidate?.candidate_id === item.candidate_id ? "bg-accentSoft/35" : ""
                  }`}
                  onClick={() => {
                    setSelectedCandidate(item);
                    void getMemoryCandidate(item.candidate_id)
                      .then(setSelectedCandidate)
                      .catch(() => undefined);
                  }}
                >
                  <div className="text-[13px] text-ink line-clamp-2">{item.content}</div>
                  <div className="text-[11px] text-muted mt-1.5">
                    {candidateTypeLabel(item, tr)} · {candidateScopeLabel(item, tr)} · {formatTime(item.created_at, tr)}
                  </div>
                </button>
              ))}
            </section>
            <section className="border border-line rounded-lg bg-panel min-w-0 min-[1080px]:sticky min-[1080px]:top-6">
              {selectedCandidate ? (
                <CandidateDetail
                  candidate={selectedCandidate}
                  memories={memories}
                  onChanged={async () => {
                    setSelectedCandidate(null);
                    const remaining = await load();
                    if (remaining?.length === 0) openHome();
                  }}
                />
              ) : <div className="px-4 py-8 text-[12.5px] text-muted">{tr("Select a candidate to review its details.")}</div>}
            </section>
          </div>
        </div>
      </main>
    );
  }

  if (surface === "type" && selectedType) {
    const type = MEMORY_TYPES.find(([key]) => key === selectedType)!;
    return (
      <main className="flex-1 min-w-0 min-h-0 overflow-y-auto hairline-scroll bg-paper" data-testid="memory-view">
        <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6">
          <button className="inline-flex items-center gap-1.5 text-[12px] text-muted hover:text-ink mb-4" onClick={openHome}>
            <Icon name="arrowLeft" size={14} /> {tr("Back to memory types")}
          </button>
          <div className="mb-5">
            <h1 className="text-[24px] font-semibold text-heading">{tr(type[1])}</h1>
            <p className="text-[12.5px] text-muted mt-0.5">{tr(type[2])}</p>
          </div>
          <div className="grid grid-cols-1 min-[1080px]:grid-cols-[minmax(0,1fr)_360px] gap-4 items-start">
            <section className="border border-line rounded-lg bg-panel overflow-hidden min-w-0">
              {typed.length === 0 ? (
                <div className="px-4 py-10 text-center">
                  <div className="text-[13px] font-medium text-ink">{tr("No confirmed memories in this type")}</div>
                  <div className="text-[12px] text-muted mt-1">{tr("Memories appear here after governance and confirmation.")}</div>
                </div>
              ) : typed.map((item) => (
                <button key={item.id} className={`w-full text-left px-4 py-3 border-b border-line last:border-b-0 hover:bg-paper/70 ${selectedMemory?.id === item.id ? "bg-accentSoft/35" : ""}`} onClick={() => setSelectedMemory(item)}>
                  <div className="text-[13px] text-ink line-clamp-2">{item.content}</div>
                  <div className="text-[11px] text-muted mt-1.5">{scopeLabel(item, tr)} · {formatTime(item.created_at, tr)}</div>
                </button>
              ))}
            </section>
            <section className="border border-line rounded-lg bg-panel min-w-0 min-[1080px]:sticky min-[1080px]:top-6">
              {selectedMemory ? <MemoryDetail memory={selectedMemory} /> : <div className="px-4 py-8 text-[12.5px] text-muted">{tr("Select a memory to view its details.")}</div>}
            </section>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="flex-1 min-w-0 min-h-0 overflow-y-auto hairline-scroll bg-paper" data-testid="memory-view">
      <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6">
        <div className="flex items-start justify-between gap-4 mb-5">
          <div>
            <h1 className="text-[24px] font-semibold text-heading">{tr("Personal memory")}</h1>
            <p className="text-[12.5px] text-muted mt-0.5">{tr("Long-term conclusions Smallink can reuse in future work.")}</p>
          </div>
          <button className="w-8 h-8 grid place-items-center rounded-lg border border-line bg-panel hover:border-lineStrong" onClick={() => void load()} title={tr("Refresh")} aria-label={tr("Refresh")}>
            <Icon name="refresh" size={15} />
          </button>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          <SummaryCard label={tr("Confirmed memories")} value={memories.length} />
          <SummaryCard label={tr("Global memories")} value={memories.filter((m) => m.scope === "global").length} />
          <SummaryCard label={tr("Project memories")} value={memories.filter((m) => m.scope === "workspace").length} />
          <SummaryCard
            label={tr("Source records")}
            value={sourceStats?.total ?? "—"}
            action={tr("Browse sources")}
            onClick={() => setSurface("sources")}
          />
        </div>

        {statsError && (
          <div className="mb-4">
            <InlineFeedback
              tone="warning"
              title={tr("Source statistics are unavailable")}
              body={tr("Confirmed memories are still available. Retry to refresh source counts.")}
              action={tr("Retry")}
              onAction={() => void load()}
            />
          </div>
        )}

        {sourceStats && sourceStats.total > 0 && memories.length === 0 && pending.length === 0 && (
          <div className="mb-4">
            <InlineFeedback
              tone="info"
              title={tr("{count} source records collected", { count: sourceStats.total })}
              body={tr("Generate candidates from source data, then review them before they become memory.")}
              action={tr(generating ? "Generating…" : "Generate candidates")}
              onAction={generating ? undefined : () => void generateCandidates(false)}
            />
          </div>
        )}

        {generateResult && (
          <div className="mb-4">
            <InlineFeedback
              tone={generateResult.tone}
              title={tr("Memory governance result")}
              body={generateResult.body}
              action={tr("Retry failed")}
              onAction={generating ? undefined : () => void generateCandidates(true)}
            />
          </div>
        )}

        {pending.length > 0 && (
          <button
            className="w-full mb-5 flex items-center justify-between gap-3 rounded-lg border border-accent/40 bg-accentSoft/20 px-3.5 py-3 text-left hover:bg-accentSoft/30"
            onClick={() => { setSurface("pending"); setSelectedCandidate(null); }}
            data-testid="memory-pending-banner"
          >
            <span className="flex items-center gap-2 text-[12.5px] text-ink">
              <Icon name="sparkle" size={14} className="text-accent" />
              {tr("{count} candidate memory drafts", { count: pending.length })}
            </span>
            <span className="flex items-center gap-1 text-[12px] text-accent">{tr("Inspect")} <Icon name="chevronRight" size={14} /></span>
          </button>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {MEMORY_TYPES.map(([key, label, description]) => {
            const items = memories.filter((item) => item.key === key);
            return (
              <button
                key={key}
                className="group min-h-[132px] text-left bg-panel border border-line rounded-xl p-4 hover:border-accent/50 hover:bg-accentSoft/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accentSoft transition-colors"
                onClick={() => { setSelectedType(key); setSelectedMemory(null); setSurface("type"); }}
                aria-label={tr("Open {type} memories", { type: tr(label) })}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="w-7 h-7 grid place-items-center rounded-full bg-accentSoft text-accent"><Icon name="diamond" size={14} /></span>
                  <span className="text-[20px] font-semibold text-heading">{items.length}</span>
                </div>
                <div className="text-[14px] font-semibold text-heading mt-3">{tr(label)}</div>
                <div className="text-[11.5px] leading-relaxed text-muted mt-1">{tr(description)}</div>
              </button>
            );
          })}
        </div>

        {!loading && memories.length === 0 && <div className="mt-5 border-t border-line pt-4 text-[12px] text-muted">{tr("There are no confirmed memories yet. Candidate memories must be reviewed before they appear here.")}</div>}
        {!loading && legacyCount > 0 && <div className="mt-5 rounded-lg border border-warnLine bg-warnSoft px-3.5 py-3 text-[12px] text-muted">{tr("{count} earlier memories need a standard memory type before they appear in the cards.", { count: legacyCount })}</div>}
      </div>
    </main>
  );
}

function MemoryShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex-1 min-w-0 min-h-0 overflow-y-auto hairline-scroll bg-paper" data-testid="memory-view">
      <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6">{children}</div>
    </main>
  );
}

function SummaryCard({
  label,
  value,
  action,
  onClick,
}: {
  label: string;
  value: number | string;
  action?: string;
  onClick?: () => void;
}) {
  const content = (
    <>
      <div className="text-[22px] font-semibold text-heading">{value}</div>
      <div className="text-[11.5px] text-muted mt-0.5">{label}</div>
      {action && <div className="text-[11px] text-accent mt-2">{action} ›</div>}
    </>
  );
  return onClick ? (
    <button
      type="button"
      onClick={onClick}
      aria-label={action ? `${label}: ${value}. ${action}` : `${label}: ${value}`}
      className="rounded-xl border border-line bg-panel px-4 py-3 text-left hover:border-accent/50 hover:bg-accentSoft/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accentSoft"
    >
      {content}
    </button>
  ) : (
    <div className="rounded-xl border border-line bg-panel px-4 py-3">{content}</div>
  );
}

function SourceRecordsView({ onBack }: { onBack: () => void }) {
  const { tr } = useI18n();
  const [records, setRecords] = useState<SensoryRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("all");
  const [governance, setGovernance] = useState("all");
  const [selected, setSelected] = useState<SensoryRecord | null>(null);
  const [offset, setOffset] = useState(0);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const pageSize = 50;

  const load = () => {
    setLoading(true);
    setError("");
    getSensoryRecords({
      limit: pageSize,
      offset,
      source_type: source === "all" ? undefined : source,
      governance_status: governance === "all" ? undefined : governance,
      query: query.trim() || undefined,
    })
      .then((next) => {
        setRecords(next.records);
        setTotal(next.total);
        if (selected && !next.records.some((item) => item.record_id === selected.record_id)) {
          setSelected(null);
        }
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : tr("Could not load source records"));
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    const timer = window.setTimeout(load, query ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [source, governance, offset, query]); // eslint-disable-line react-hooks/exhaustive-deps

  const sources = [...new Set(records.map((record) => record.source_type))].sort();

  const openDetail = (record: SensoryRecord) => {
    setSelected(record);
    setDetailError("");
    setDetailLoading(true);
    getSensoryRecord(record.record_id)
      .then(setSelected)
      .catch((reason) => {
        setDetailError(reason instanceof Error ? reason.message : tr("Could not load source record"));
      })
      .finally(() => setDetailLoading(false));
  };

  const removeSelected = async () => {
    if (!selected) return;
    setDeleteError("");
    try {
      await deleteSensoryRecords({ record_ids: [selected.record_id] });
      setSelected(null);
      setDeleteArmed(false);
      load();
    } catch (reason) {
      setDeleteError(
        reason instanceof Error ? reason.message : tr("Could not delete source record"),
      );
    }
  };

  return (
    <MemoryShell>
      <button className="inline-flex items-center gap-1.5 text-[12px] text-muted hover:text-ink mb-4" onClick={onBack}>
        <Icon name="arrowLeft" size={14} /> {tr("Back to memory types")}
      </button>
      <div className="flex items-start justify-between gap-4 mb-5">
        <div>
          <h1 className="text-[24px] font-semibold text-heading">{tr("Data sources")}</h1>
          <p className="text-[12.5px] text-muted mt-0.5">{tr("Immutable inputs, outputs and tool activity captured before governance.")}</p>
        </div>
        <button
          className="w-9 h-9 grid place-items-center rounded-lg border border-line bg-panel text-muted hover:text-accent hover:border-accent"
          onClick={load}
          title={tr("Refresh")}
          aria-label={tr("Refresh")}
        >
          <Icon name="refresh" size={15} />
        </button>
      </div>

      <div className="rounded-xl border border-line bg-panel/80 p-3 mb-4 flex flex-wrap gap-2 items-center">
        <label className="flex-1 min-w-[240px] flex items-center gap-2 rounded-lg border border-line bg-paper px-3 h-10 focus-within:border-accent focus-within:ring-2 focus-within:ring-accentSoft">
          <Icon name="search" size={15} className="text-muted" />
          <input
            value={query}
            onChange={(event) => { setQuery(event.target.value); setOffset(0); }}
            placeholder={tr("Search content, project or conversation")}
            className="min-w-0 flex-1 bg-transparent outline-none text-[13px] placeholder:text-faint"
          />
        </label>
        <select
          value={source}
          onChange={(event) => { setSource(event.target.value); setOffset(0); }}
          aria-label={tr("Data sources")}
          className="h-10 min-w-[140px] rounded-lg border border-line bg-paper px-3 text-[12.5px] outline-none focus:border-accent"
        >
          <option value="all">{tr("All sources")}</option>
          {sources.map((item) => <option key={item} value={item}>{sourceLabel(item)}</option>)}
        </select>
        <select
          value={governance}
          onChange={(event) => { setGovernance(event.target.value); setOffset(0); }}
          aria-label={tr("Governance status")}
          className="h-10 min-w-[160px] rounded-lg border border-line bg-paper px-3 text-[12.5px] outline-none focus:border-accent"
        >
          <option value="all">{tr("All governance states")}</option>
          <option value="pending">{tr("Awaiting governance")}</option>
        </select>
      </div>

      <div className="mb-3 text-[11.5px] text-muted">
        {tr("Showing {shown} of {total} source records", { shown: records.length, total })}
      </div>

      {loading ? (
        <PageState icon="diamond" title={tr("Loading source records…")} body={tr("Reading imported conversations and runtime records.")} />
      ) : error ? (
        <PageState icon="diamond" title={tr("Source records are unavailable")} body={error} action={tr("Try again")} onAction={load} />
      ) : records.length === 0 ? (
        <PageState icon="diamond" title={tr("No source records yet")} body={tr("Connect Codex or TRAE CLI, or start a Smallink conversation to collect source data.")} />
      ) : records.length === 0 ? (
        <PageState icon="search" title={tr("No source records match these filters.")} body={tr("Change the search or filters to see more records.")} />
      ) : (
        <div className="grid grid-cols-1 min-[1080px]:grid-cols-[minmax(0,1fr)_380px] gap-4 items-start">
          <section className="rounded-xl border border-line bg-panel overflow-hidden min-w-0">
            {records.map((record) => (
              <button
                key={record.record_id}
                type="button"
                onClick={() => openDetail(record)}
                aria-pressed={selected?.record_id === record.record_id}
                className={`w-full px-4 py-3 text-left border-b border-line last:border-b-0 hover:bg-paper/70 ${
                  selected?.record_id === record.record_id ? "bg-accentSoft/35" : ""
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-[10.5px] px-1.5 py-0.5 rounded bg-accentSoft text-accent font-medium">{sourceLabel(record.source_type)}</span>
                  <span className="text-[10.5px] text-muted">{contentTypeLabel(record.content_type, tr)}</span>
                  <span className="ml-auto text-[10.5px] text-faint">{formatTime(record.occurred_at, tr)}</span>
                </div>
                <div className="text-[13px] text-ink line-clamp-2 leading-relaxed mt-1.5">{record.raw_content}</div>
                <div className="text-[11px] text-muted mt-1.5 truncate">
                  {record.project_path ? `${tr("Project")} · ${baseName(record.project_path)}` : tr("Global")}
                  {record.conversation_id ? ` · ${tr("Conversation")} ${shortId(record.conversation_id)}` : ""}
                </div>
              </button>
            ))}
          </section>
          <section className="rounded-xl border border-line bg-panel min-w-0 min-[1080px]:sticky min-[1080px]:top-6 overflow-hidden">
            {detailLoading ? (
              <div className="px-4 py-8 text-[12.5px] text-muted">{tr("Loading…")}</div>
            ) : detailError ? (
              <div className="p-4"><InlineFeedback tone="danger" title={tr("Could not load source record")} body={detailError} /></div>
            ) : selected ? (
              <>
                <SourceRecordDetail record={selected} />
                <div className="border-t border-line px-4 py-3">
                  {!deleteArmed ? (
                    <button
                      className="text-[12px] text-danger"
                      onClick={() => setDeleteArmed(true)}
                    >
                      {tr("Delete this source record")}
                    </button>
                  ) : (
                    <div className="flex items-center gap-2">
                      <button
                        className="text-[12px] text-danger font-medium"
                        onClick={() => void removeSelected()}
                      >
                        {tr("Confirm delete")}
                      </button>
                      <button
                        className="text-[12px] text-muted"
                        onClick={() => setDeleteArmed(false)}
                      >
                        {tr("Cancel")}
                      </button>
                    </div>
                  )}
                  {deleteError && (
                    <div className="text-[11.5px] text-danger mt-2">{deleteError}</div>
                  )}
                </div>
              </>
            ) : (
              <div className="px-4 py-8 text-[12.5px] text-muted">{tr("Select a record to inspect its source and raw content.")}</div>
            )}
          </section>
        </div>
      )}
      {total > pageSize && (
        <div className="mt-4 flex items-center justify-between text-[12px]">
          <button
            className="text-accent disabled:text-faint"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - pageSize))}
          >
            {tr("Previous")}
          </button>
          <span className="text-muted">
            {offset + 1}–{Math.min(offset + records.length, total)} / {total}
          </span>
          <button
            className="text-accent disabled:text-faint"
            disabled={offset + records.length >= total}
            onClick={() => setOffset(offset + pageSize)}
          >
            {tr("Next")}
          </button>
        </div>
      )}
    </MemoryShell>
  );
}

function SourceRecordDetail({ record }: { record: SensoryRecord }) {
  const { tr } = useI18n();
  return (
    <div>
      <div className="px-4 py-3 border-b border-line">
        <div className="text-[13px] font-semibold text-ink">{tr("Record details")}</div>
        <div className="text-[10.5px] text-faint mt-0.5">#{shortId(record.record_id)}</div>
      </div>
      <dl className="grid grid-cols-[104px_minmax(0,1fr)] gap-x-3 gap-y-2 px-4 py-3 text-[11.5px]">
        <dt className="text-faint">{tr("Data sources")}</dt><dd className="text-ink">{sourceLabel(record.source_type)}</dd>
        <dt className="text-faint">{tr("Type")}</dt><dd className="text-ink">{contentTypeLabel(record.content_type, tr)}</dd>
        <dt className="text-faint">{tr("Governance status")}</dt><dd className="text-ink">{tr(record.governance_status === "pending" ? "Awaiting governance" : record.governance_status)}</dd>
        <dt className="text-faint">{tr("Created")}</dt><dd className="text-ink">{formatTime(record.occurred_at, tr)}</dd>
        {record.project_path && <><dt className="text-faint">{tr("Project")}</dt><dd className="text-ink break-all">{record.project_path}</dd></>}
        {record.conversation_id && <><dt className="text-faint">{tr("Conversation")}</dt><dd className="text-ink break-all">{record.conversation_id}</dd></>}
        {record.source_locator && <><dt className="text-faint">{tr("Source location")}</dt><dd className="text-ink break-all">{record.source_locator}</dd></>}
      </dl>
      <div className="border-t border-line px-4 py-3">
        <div className="text-[11px] font-medium text-muted mb-2">{tr("Raw content")}</div>
        <div className="max-h-[360px] overflow-y-auto hairline-scroll whitespace-pre-wrap break-words rounded-lg bg-paper px-3 py-2.5 text-[12px] leading-relaxed text-ink">
          {record.raw_content}
        </div>
      </div>
    </div>
  );
}

function CandidateDetail({
  candidate,
  memories,
  onChanged,
}: {
  candidate: MemoryCandidate;
  memories: MemoryRecord[];
  onChanged: () => Promise<void>;
}) {
  const { tr } = useI18n();
  const [content, setContent] = useState(candidate.content);
  const [mergeId, setMergeId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setContent(candidate.content);
    setMergeId("");
    setError("");
  }, [candidate.candidate_id, candidate.content]);

  const decide = async (
    action: "accept" | "edit_accept" | "ignore" | "merge",
  ) => {
    setBusy(true);
    setError("");
    try {
      await decideMemoryCandidate(candidate.candidate_id, {
        action,
        ...(action === "edit_accept" || action === "merge" ? { content: content.trim() } : {}),
        ...(action === "merge" ? { merge_memory_id: Number(mergeId) } : {}),
      });
      await onChanged();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : tr("Could not save memory decision"),
      );
    } finally {
      setBusy(false);
    }
  };

  const changed = content.trim() !== candidate.content;
  return (
    <div>
      <div className="px-4 py-3 border-b border-line">
        <div className="text-[13px] font-semibold text-ink">{tr("Candidate details")}</div>
        <div className="text-[10.5px] text-faint mt-0.5">#{shortId(candidate.candidate_id)}</div>
      </div>
      <div className="px-4 py-3">
        <label className="block text-[11px] font-medium text-muted mb-1.5">
          {tr("Memory content")}
        </label>
        <textarea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          rows={6}
          disabled={busy}
          className="w-full resize-y rounded-lg border border-line bg-paper px-3 py-2 text-[12.5px] leading-relaxed outline-none focus:border-accent"
        />
      </div>
      <dl className="grid grid-cols-[92px_minmax(0,1fr)] gap-x-3 gap-y-2 px-4 py-3 border-t border-line text-[11.5px]">
        <dt className="text-faint">{tr("Type")}</dt>
        <dd className="text-ink">{candidateTypeLabel(candidate, tr)}</dd>
        <dt className="text-faint">{tr("Scope")}</dt>
        <dd className="text-ink">{candidateScopeLabel(candidate, tr)}</dd>
        <dt className="text-faint">{tr("Model")}</dt>
        <dd className="text-ink break-all">{candidate.model}</dd>
        <dt className="text-faint">{tr("Sources")}</dt>
        <dd className="text-ink">{candidate.sources.length}</dd>
      </dl>
      {(candidate.source_records?.length ?? 0) > 0 && (
        <div className="border-t border-line px-4 py-3">
          <div className="text-[11px] font-medium text-muted mb-2">{tr("Source evidence")}</div>
          <div className="space-y-2 max-h-44 overflow-y-auto hairline-scroll">
            {candidate.source_records!.map((source) => (
              <div key={source.record_id} className="rounded-lg bg-paper px-2.5 py-2">
                <div className="text-[10.5px] text-faint">
                  {sourceLabel(source.source_type)} · {formatTime(source.occurred_at, tr)}
                </div>
                <div className="text-[11.5px] text-ink line-clamp-3 mt-1">
                  {source.raw_content}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {memories.length > 0 && (
        <div className="border-t border-line px-4 py-3">
          <label className="block text-[11px] font-medium text-muted mb-1.5">
            {tr("Merge into existing memory")}
          </label>
          <select
            value={mergeId}
            onChange={(event) => setMergeId(event.target.value)}
            disabled={busy}
            className="w-full h-9 rounded-lg border border-line bg-paper px-2.5 text-[12px] outline-none focus:border-accent"
          >
            <option value="">{tr("Select a confirmed memory")}</option>
            {memories.map((memory) => (
              <option key={memory.id} value={memory.id}>
                #{memory.id} · {memory.content.slice(0, 64)}
              </option>
            ))}
          </select>
        </div>
      )}
      {error && (
        <div className="px-4 pb-3">
          <InlineFeedback tone="danger" title={tr("Decision failed")} body={error} />
        </div>
      )}
      <div className="border-t border-line px-4 py-3 flex flex-wrap gap-2">
        <button
          disabled={busy || !content.trim()}
          onClick={() => void decide(changed ? "edit_accept" : "accept")}
          className="rounded-full bg-ink text-panel px-3.5 py-1.5 text-[12px] disabled:opacity-50"
        >
          {tr(changed ? "Save and accept" : "Accept")}
        </button>
        {memories.length > 0 && (
          <button
            disabled={busy || !mergeId || !content.trim()}
            onClick={() => void decide("merge")}
            className="rounded-full border border-line px-3.5 py-1.5 text-[12px] text-ink disabled:opacity-50"
          >
            {tr("Merge")}
          </button>
        )}
        <button
          disabled={busy}
          onClick={() => void decide("ignore")}
          className="rounded-full border border-line px-3.5 py-1.5 text-[12px] text-muted disabled:opacity-50"
        >
          {tr("Ignore")}
        </button>
      </div>
    </div>
  );
}

function MemoryDetail({ memory }: { memory: MemoryRecord }) {
  const { tr } = useI18n();
  return <div>
    <div className="px-4 py-3 border-b border-line"><div className="text-[13px] font-semibold text-ink">{tr("Memory details")}</div><div className="text-[10.5px] text-faint mt-0.5">#{memory.id}</div></div>
    <div className="px-4 py-4 text-[13px] leading-relaxed text-ink whitespace-pre-wrap">{memory.content}</div>
    <dl className="grid grid-cols-[92px_minmax(0,1fr)] gap-x-3 gap-y-2 px-4 py-3 border-t border-line text-[11.5px]">
      <dt className="text-faint">{tr("Type")}</dt><dd className="text-ink">{typeLabel(memory, tr)}</dd>
      <dt className="text-faint">{tr("Scope")}</dt><dd className="text-ink">{scopeLabel(memory, tr)}</dd>
      {memory.status === "pending" && <><dt className="text-faint">{tr("Status")}</dt><dd className="text-ink">{tr("Awaiting confirmation")}</dd></>}
      <dt className="text-faint">{tr("Created")}</dt><dd className="text-ink">{formatTime(memory.created_at, tr)}</dd>
    </dl>
  </div>;
}

function typeLabel(item: MemoryRecord, tr: (text: string) => string): string {
  const match = MEMORY_TYPES.find(([key]) => key === item.key);
  return match ? tr(match[1]) : tr("Uncategorized");
}

function scopeLabel(item: MemoryRecord, tr: (text: string) => string): string {
  if (item.scope === "global") return tr("Global");
  if (item.scope === "session") return tr("Session");
  return item.workspace ? `${tr("Project")} · ${baseName(item.workspace)}` : tr("Project");
}

function candidateTypeLabel(
  item: MemoryCandidate,
  tr: (text: string) => string,
): string {
  const match = MEMORY_TYPES.find(([key]) => key === item.memory_type);
  return match ? tr(match[1]) : tr("Uncategorized");
}

function candidateScopeLabel(
  item: MemoryCandidate,
  tr: (text: string) => string,
): string {
  if (item.scope === "global") return tr("Global");
  if (item.scope === "session") return tr("Session");
  return item.workspace ? `${tr("Project")} · ${baseName(item.workspace)}` : tr("Project");
}

function formatTime(value: string | null, tr: (text: string) => string): string {
  if (!value) return tr("Unknown time");
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function sourceLabel(source: string): string {
  if (source === "traex") return "TRAE CLI";
  if (source === "codex") return "Codex";
  if (source === "smallink") return "Smallink";
  return source;
}

function contentTypeLabel(value: string, tr: (text: string) => string): string {
  const labels: Record<string, string> = {
    user_input: "User input",
    connector_input: "Connector input",
    assistant_output: "AI output",
    tool_call: "Tool call",
    tool_result: "Tool result",
    runtime_error: "Runtime error",
    codex_turn: "Conversation",
    traex_turn: "Conversation",
  };
  return tr(labels[value] || value.replace(/_/g, " "));
}

function shortId(value: string): string {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value;
}
