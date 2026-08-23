import { useEffect, useMemo, useState } from "react";
import {
  autoAcceptHighConfidence,
  decideMemoryCandidate,
  decideMemoryCandidates,
  deleteSensoryRecords,
  getConfidenceSummary,
  getGovernanceTask,
  getGovernanceSchedule,
  getGovernanceTasks,
  getMemory,
  getMemoryCandidate,
  getMemoryCandidates,
  getMemoryUsageHistory,
  getSensoryRecord,
  getSensoryRecords,
  getSensoryStats,
  retypeMemoryCandidates,
  runMemoryPipeline,
  setMemoryArchived,
  updateGovernanceSchedule,
  type ConfidenceSummary,
  type GovernanceSchedule,
  type GovernanceTask,
  type MemoryCandidate,
  type MemoryRecord,
  type MemoryUsageRecord,
  type SensoryRecord,
  type SensoryStats,
} from "../api";
import { baseName } from "../paths";
import { useI18n } from "../i18n";
import { InlineFeedback, PageState } from "./AsyncFeedback";
import { Icon } from "./Icon";
import { PromptsView } from "./PromptsView";

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
type MemorySurface = "home" | "pending" | "sources" | "type" | "prompts" | "tasks" | "archived" | "personality";

export function MemoryView() {
  const { tr } = useI18n();
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [archivedMemories, setArchivedMemories] = useState<MemoryRecord[]>([]);
  const [pending, setPending] = useState<MemoryCandidate[]>([]);
  const [governanceTasks, setGovernanceTasks] = useState<GovernanceTask[]>([]);
  const [governanceSchedule, setGovernanceSchedule] = useState<GovernanceSchedule | null>(null);
  const [surface, setSurface] = useState<MemorySurface>("home");
  const [selectedType, setSelectedType] = useState<MemoryType | null>(null);
  const [selectedMemory, setSelectedMemory] = useState<MemoryRecord | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<MemoryCandidate | null>(null);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchType, setBatchType] = useState<MemoryType>("project_context");
  const [batchFeedback, setBatchFeedback] = useState<{
    tone: "success" | "warning";
    body: string;
  } | null>(null);
  const [sourceStats, setSourceStats] = useState<SensoryStats | null>(null);
  const [confidenceSummary, setConfidenceSummary] = useState<ConfidenceSummary | null>(null);
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
      const [active, archived, awaiting, tasks, schedule] = await Promise.all([
        getMemory(),
        getMemory("archived"),
        getMemoryCandidates(),
        getGovernanceTasks(),
        getGovernanceSchedule(),
      ]);
      setMemories(active);
      setArchivedMemories(archived);
      setPending(awaiting);
      setGovernanceTasks(tasks);
      setGovernanceSchedule(schedule);
      const pendingIds = new Set(awaiting.map((candidate) => candidate.candidate_id));
      setSelectedCandidateIds((current) =>
        new Set([...current].filter((candidateId) => pendingIds.has(candidateId))),
      );
      try {
        setSourceStats(await getSensoryStats());
        setConfidenceSummary(await getConfidenceSummary());
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
    setSelectedCandidateIds(new Set());
    setBatchFeedback(null);
  };

  const retypeSelected = async () => {
    const candidateIds = [...selectedCandidateIds];
    if (!candidateIds.length) return;
    setBatchBusy(true);
    setBatchFeedback(null);
    try {
      const result = await retypeMemoryCandidates(candidateIds, batchType);
      setBatchFeedback({
        tone: result.failed.length ? "warning" : "success",
        body: tr("Updated {processed} candidates; {failed} failed.", {
          processed: result.processed.length,
          failed: result.failed.length,
        }),
      });
      const currentCandidateId = selectedCandidate?.candidate_id;
      await load();
      if (currentCandidateId) {
        void getMemoryCandidate(currentCandidateId).then(setSelectedCandidate).catch(() => undefined);
      }
    } catch (reason) {
      setBatchFeedback({
        tone: "warning",
        body: reason instanceof Error ? reason.message : tr("Could not update candidate types"),
      });
    } finally {
      setBatchBusy(false);
    }
  };

  const decideSelected = async (action: "accept" | "ignore") => {
    const candidateIds = [...selectedCandidateIds];
    if (!candidateIds.length) return;
    setBatchBusy(true);
    setBatchFeedback(null);
    try {
      const result = await decideMemoryCandidates(candidateIds, action);
      setSelectedCandidate(null);
      setSelectedCandidateIds(new Set());
      setBatchFeedback({
        tone: result.failed.length ? "warning" : "success",
        body: tr("Processed {processed} candidates; {failed} failed.", {
          processed: result.processed.length,
          failed: result.failed.length,
        }),
      });
      const remaining = await load();
      if (remaining?.length === 0) openHome();
    } catch (reason) {
      setBatchFeedback({
        tone: "warning",
        body: reason instanceof Error ? reason.message : tr("Could not save memory decisions"),
      });
    } finally {
      setBatchBusy(false);
    }
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

  if (surface === "prompts") {
    return <PromptsView onBack={openHome} />;
  }

  if (surface === "personality") {
    return <PersonalityDashboard memories={memories} onBack={openHome} />;
  }

  if (surface === "sources") {
    return <SourceRecordsView onBack={openHome} />;
  }

  if (surface === "tasks") {
    return (
      <GovernanceTasksView
        tasks={governanceTasks}
        schedule={governanceSchedule}
        onScheduleChange={async (changes) => {
          const updated = await updateGovernanceSchedule(changes);
          setGovernanceSchedule(updated);
        }}
        onBack={openHome}
        onReview={() => {
          setSurface("pending");
          setSelectedCandidate(null);
        }}
      />
    );
  }

  if (surface === "archived") {
    return (
      <main className="flex-1 min-w-0 min-h-0 overflow-y-auto hairline-scroll bg-paper" data-testid="memory-view">
        <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6">
          <button className="inline-flex items-center gap-1.5 text-[12px] text-muted hover:text-ink mb-4" onClick={openHome}>
            <Icon name="arrowLeft" size={14} /> {tr("Back to memory types")}
          </button>
          <div className="mb-5">
            <h1 className="text-[24px] font-semibold text-heading">{tr("Archived memories")}</h1>
            <p className="text-[12.5px] text-muted mt-0.5">{tr("Kept for history and provenance, but excluded from agent context.")}</p>
          </div>
          <div className="grid grid-cols-1 min-[1080px]:grid-cols-[minmax(0,1fr)_360px] gap-4 items-start">
            <section className="border border-line rounded-lg bg-panel overflow-hidden min-w-0">
              {archivedMemories.length === 0 ? (
                <div className="px-4 py-10 text-center"><div className="text-[13px] font-medium text-ink">{tr("No archived memories")}</div></div>
              ) : archivedMemories.map((item) => (
                <button key={item.id} className={`w-full text-left px-4 py-3 border-b border-line last:border-b-0 hover:bg-paper/70 ${selectedMemory?.id === item.id ? "bg-accentSoft/35" : ""}`} onClick={() => setSelectedMemory(item)}>
                  <div className="text-[13px] text-ink line-clamp-2">{item.content}</div>
                  <div className="text-[11px] text-muted mt-1.5">{typeLabel(item, tr)} · {scopeLabel(item, tr)} · {formatTime(item.updated_at || item.created_at, tr)}</div>
                </button>
              ))}
            </section>
            <section className="border border-line rounded-lg bg-panel min-w-0 min-[1080px]:sticky min-[1080px]:top-6">
              {selectedMemory ? <MemoryDetail memory={selectedMemory} archived onChanged={async () => { setSelectedMemory(null); await load(); }} /> : <div className="px-4 py-8 text-[12.5px] text-muted">{tr("Select a memory to view its details.")}</div>}
            </section>
          </div>
        </div>
      </main>
    );
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
          {confidenceSummary && confidenceSummary.tiers.high > 0 && (
            <div className="mb-4 flex items-center gap-3 rounded-lg border border-accent/30 bg-accentSoft/20 px-4 py-3">
              <Icon name="sparkle" size={16} className="text-accent" />
              <span className="flex-1 text-[12.5px] text-ink">
                {tr("{count} high-confidence memories ready for auto-accept", { count: confidenceSummary.tiers.high })}
              </span>
              <button
                type="button"
                disabled={batchBusy}
                onClick={async () => {
                  setBatchBusy(true);
                  try {
                    const result = await autoAcceptHighConfidence(0.9);
                    setBatchFeedback({
                      tone: "success",
                      body: tr("Auto-accepted {count} high-confidence memories.", { count: result.auto_accepted }),
                    });
                    await load();
                  } catch {
                    setBatchFeedback({ tone: "warning", body: tr("Could not auto-accept memories") });
                  } finally {
                    setBatchBusy(false);
                  }
                }}
                className="rounded-lg bg-accent px-3 py-1.5 text-[12px] text-onAccent disabled:opacity-40"
              >
                {tr("Auto-accept all")}
              </button>
            </div>
          )}
          {batchFeedback && (
            <div className="mb-4">
              <InlineFeedback tone={batchFeedback.tone} title={tr("Batch decision")} body={batchFeedback.body} />
            </div>
          )}
          {pending.length > 0 && (
            <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2">
              <label className="inline-flex items-center gap-2 text-[12px] text-muted">
                <input
                  type="checkbox"
                  aria-label={tr("Select all candidates")}
                  checked={selectedCandidateIds.size === pending.length}
                  onChange={(event) => setSelectedCandidateIds(
                    event.target.checked
                      ? new Set(pending.map((candidate) => candidate.candidate_id))
                      : new Set(),
                  )}
                />
                {tr("{count} selected", { count: selectedCandidateIds.size })}
              </label>
              <span className="flex-1" />
              <button
                type="button"
                disabled={batchBusy || selectedCandidateIds.size === 0}
                onClick={() => void decideSelected("ignore")}
                className="rounded-lg border border-line px-3 py-1.5 text-[12px] text-muted disabled:opacity-40"
              >
                {tr("Ignore selected")}
              </button>
              <button
                type="button"
                disabled={batchBusy || selectedCandidateIds.size === 0}
                onClick={() => void decideSelected("accept")}
                className="rounded-lg bg-accent px-3 py-1.5 text-[12px] text-onAccent disabled:opacity-40"
              >
                {tr(batchBusy ? "Processing…" : "Accept selected")}
              </button>
              <select
                value={batchType}
                onChange={(event) => setBatchType(event.target.value as MemoryType)}
                disabled={batchBusy || selectedCandidateIds.size === 0}
                aria-label={tr("Memory type for selected candidates")}
                className="h-8 rounded-lg border border-line bg-paper px-2 text-[11.5px] text-ink disabled:opacity-40"
              >
                {MEMORY_TYPES.map(([key, label]) => <option key={key} value={key}>{tr(label)}</option>)}
              </select>
              <button
                type="button"
                disabled={batchBusy || selectedCandidateIds.size === 0}
                onClick={() => void retypeSelected()}
                className="rounded-lg border border-line px-3 py-1.5 text-[12px] text-ink disabled:opacity-40"
              >
                {tr("Apply type")}
              </button>
            </div>
          )}
          <div className="grid grid-cols-1 min-[1080px]:grid-cols-[minmax(0,1fr)_360px] gap-4 items-start">
            <section className="border border-line rounded-lg bg-panel overflow-hidden min-w-0" data-testid="memory-pending-list">
              {pending.length === 0 ? (
                <div className="px-4 py-10 text-center">
                  <div className="text-[13px] font-medium text-ink">{tr("Nothing awaiting confirmation")}</div>
                  <div className="text-[12px] text-muted mt-1">{tr("Extracted candidate memories will appear here.")}</div>
                </div>
              ) : pending.map((item) => (
                <div
                  key={item.candidate_id}
                  className={`flex items-start border-b border-line last:border-b-0 hover:bg-paper/70 ${
                    selectedCandidate?.candidate_id === item.candidate_id ? "bg-accentSoft/35" : ""
                  }`}
                >
                  <label className="grid place-items-center self-stretch px-3 cursor-pointer">
                    <input
                      type="checkbox"
                      aria-label={tr("Select candidate: {content}", { content: item.content })}
                      checked={selectedCandidateIds.has(item.candidate_id)}
                      onChange={(event) => setSelectedCandidateIds((current) => {
                        const next = new Set(current);
                        if (event.target.checked) next.add(item.candidate_id);
                        else next.delete(item.candidate_id);
                        return next;
                      })}
                    />
                  </label>
                  <button
                    className="min-w-0 flex-1 text-left py-3 pr-4"
                    onClick={() => {
                      setSelectedCandidate(item);
                      void getMemoryCandidate(item.candidate_id)
                        .then(setSelectedCandidate)
                        .catch(() => undefined);
                    }}
                  >
                    <div className="text-[13px] text-ink line-clamp-2">{item.content}</div>
                    <div className="flex items-center gap-1.5 text-[11px] text-muted mt-1.5">
                      {item.confidence != null && <ConfidenceBadge confidence={item.confidence} />}
                      {candidateTypeLabel(item, tr)} · {candidateScopeLabel(item, tr)} · {formatTime(item.created_at, tr)}
                    </div>
                  </button>
                </div>
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
              {selectedMemory ? <MemoryDetail memory={selectedMemory} onChanged={async () => { setSelectedMemory(null); await load(); }} /> : <div className="px-4 py-8 text-[12.5px] text-muted">{tr("Select a memory to view its details.")}</div>}
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

        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-5">
          <SummaryCard label={tr("Confirmed memories")} value={memories.length} />
          <SummaryCard label={tr("Global memories")} value={memories.filter((m) => m.scope === "global").length} />
          <SummaryCard label={tr("Project memories")} value={memories.filter((m) => m.scope === "workspace").length} />
          <SummaryCard label={tr("Governance tasks")} value={governanceTasks.length} action={tr("View tasks")} onClick={() => setSurface("tasks")} />
          <SummaryCard label={tr("Archived memories")} value={archivedMemories.length} action={tr("View archive")} onClick={() => { setSelectedMemory(null); setSurface("archived"); }} />
          <SummaryCard
            label={tr("Source records")}
            value={sourceStats?.total ?? "—"}
            action={tr("Browse sources")}
            onClick={() => setSurface("sources")}
          />
        </div>

        {/* System Prompts config entry */}
        <button
          className="w-full mb-5 flex items-center justify-between gap-3 rounded-lg border border-line bg-panel px-3.5 py-3 text-left hover:border-accent/50 hover:bg-accentSoft/10"
          onClick={() => setSurface("prompts")}
          data-testid="memory-prompts-entry"
        >
          <span className="flex items-center gap-2.5">
            <Icon name="code" size={15} className="text-accent shrink-0" />
            <span className="min-w-0">
              <span className="block text-[13px] font-medium text-ink">{tr("System Prompts")}</span>
              <span className="block text-[11.5px] text-muted mt-0.5">{tr("View all prompt layers that shape the agent's personality and behavior.")}</span>
            </span>
          </span>
          <span className="flex items-center gap-1 text-[12px] text-accent shrink-0">{tr("View")} <Icon name="chevronRight" size={14} /></span>
        </button>

        {/* Personality dashboard entry */}
        <button
          className="w-full mb-5 flex items-center justify-between gap-3 rounded-lg border border-line bg-panel px-3.5 py-3 text-left hover:border-accent/50 hover:bg-accentSoft/10"
          onClick={() => setSurface("personality")}
          data-testid="memory-personality-entry"
        >
          <span className="flex items-center gap-2.5">
            <Icon name="memory" size={15} className="text-accent shrink-0" />
            <span className="min-w-0">
              <span className="block text-[13px] font-medium text-ink">{tr("Personality & Usage")}</span>
              <span className="block text-[11.5px] text-muted mt-0.5">{tr("See how your memories shape the agent's behavior and which are used most.")}</span>
            </span>
          </span>
          <span className="flex items-center gap-1 text-[12px] text-accent shrink-0">{tr("View")} <Icon name="chevronRight" size={14} /></span>
        </button>

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

function GovernanceTasksView({
  tasks,
  schedule,
  onScheduleChange,
  onBack,
  onReview,
}: {
  tasks: GovernanceTask[];
  schedule: GovernanceSchedule | null;
  onScheduleChange: (changes: Partial<Pick<GovernanceSchedule, "enabled" | "interval_minutes" | "batch_limit">>) => Promise<void>;
  onBack: () => void;
  onReview: () => void;
}) {
  const { tr } = useI18n();
  const [selected, setSelected] = useState<GovernanceTask | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [scheduleError, setScheduleError] = useState("");

  const changeSchedule = async (
    changes: Partial<Pick<GovernanceSchedule, "enabled" | "interval_minutes" | "batch_limit">>,
  ) => {
    setScheduleBusy(true);
    setScheduleError("");
    try {
      await onScheduleChange(changes);
    } catch (reason) {
      setScheduleError(reason instanceof Error ? reason.message : tr("Could not update governance schedule"));
    } finally {
      setScheduleBusy(false);
    }
  };

  const openTask = async (task: GovernanceTask) => {
    setSelected(task);
    setLoadingDetail(true);
    setDetailError("");
    try {
      setSelected(await getGovernanceTask(task.task_id));
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : tr("Could not load governance task"));
    } finally {
      setLoadingDetail(false);
    }
  };

  return (
    <main className="flex-1 min-w-0 min-h-0 overflow-y-auto hairline-scroll bg-paper" data-testid="memory-view">
      <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6">
        <button className="inline-flex items-center gap-1.5 text-[12px] text-muted hover:text-ink mb-4" onClick={onBack}>
          <Icon name="arrowLeft" size={14} /> {tr("Back to memory types")}
        </button>
        <div className="mb-5">
          <h1 className="text-[24px] font-semibold text-heading">{tr("Governance tasks")}</h1>
          <p className="text-[12.5px] text-muted mt-0.5">{tr("Each AI analysis run has a fixed source range and remains in review until every candidate is handled.")}</p>
        </div>
        {schedule && (
          <section className="mb-5 flex flex-wrap items-center gap-3 border-y border-line bg-panel/35 px-3 py-3">
            <span className="min-w-0 flex-1"><span className="block text-[12px] font-medium text-ink">{tr("Automatic AI governance")}</span><span className="block text-[10.5px] text-muted mt-0.5">{schedule.enabled ? tr("Only newly pending source records are processed on this schedule.") : tr("Manual mode: source records wait until you generate candidates.")}</span></span>
            <select aria-label={tr("Governance interval")} value={schedule.interval_minutes} disabled={!schedule.enabled || scheduleBusy} onChange={(event) => void changeSchedule({ interval_minutes: Number(event.target.value) })} className="h-8 rounded-lg border border-line bg-panel px-2.5 text-[11.5px] text-ink disabled:opacity-50">
              <option value={60}>{tr("Every hour")}</option>
              <option value={1440}>{tr("Every day")}</option>
              <option value={10080}>{tr("Every week")}</option>
            </select>
            <button type="button" disabled={scheduleBusy} className={`h-8 px-3 rounded-lg text-[11.5px] disabled:opacity-50 ${schedule.enabled ? "border border-line text-ink" : "bg-accent text-onAccent"}`} onClick={() => void changeSchedule({ enabled: !schedule.enabled })}>{tr(schedule.enabled ? "Use manual mode" : "Enable automatic governance")}</button>
          </section>
        )}
        {scheduleError && <div className="mb-4"><InlineFeedback tone="danger" title={tr("Schedule update failed")} body={scheduleError} /></div>}
        {tasks.length === 0 ? (
          <PageState icon="branch" title={tr("No governance tasks yet")} body={tr("A task is created when AI analyzes new source records.")} />
        ) : (
          <div className="grid grid-cols-1 min-[1080px]:grid-cols-[minmax(0,1fr)_420px] gap-4 items-start">
            <section className="border border-line rounded-lg bg-panel overflow-hidden min-w-0">
              {tasks.map((task) => (
                <button key={task.task_id} className={`w-full text-left grid grid-cols-[minmax(0,1fr)_110px_18px] items-center gap-3 px-4 py-3 border-b border-line last:border-b-0 hover:bg-paper/70 ${selected?.task_id === task.task_id ? "bg-accentSoft/35" : ""}`} onClick={() => void openTask(task)}>
                  <span className="min-w-0">
                    <span className="block text-[12.5px] font-medium text-ink">{tr("Governance task")} #{shortId(task.task_id)}</span>
                    <span className="block text-[10.5px] text-muted mt-1">{tr("{records} records · {candidates} candidates", { records: task.total_records, candidates: task.candidate_total })}</span>
                  </span>
                  <span className={`text-[10.5px] text-right ${task.status === "reviewing" ? "text-accent" : "text-muted"}`}>{tr(task.status)}</span>
                  <Icon name="chevronRight" size={13} className="text-faint" />
                </button>
              ))}
            </section>
            <section className="border border-line rounded-lg bg-panel min-w-0 min-[1080px]:sticky min-[1080px]:top-6">
              {!selected ? <div className="px-4 py-8 text-[12.5px] text-muted">{tr("Select a governance task to view its details.")}</div> : (
                <div>
                  <div className="px-4 py-3 border-b border-line flex items-start justify-between gap-3">
                    <div><div className="text-[13px] font-semibold text-ink">{tr("Governance task details")}</div><div className="text-[10.5px] text-faint mt-0.5">#{shortId(selected.task_id)}</div></div>
                    <span className="text-[10.5px] text-accent">{tr(selected.status)}</span>
                  </div>
                  {loadingDetail ? <div className="px-4 py-8 text-[12px] text-muted">{tr("Loading task details...")}</div> : (
                    <>
                      <dl className="grid grid-cols-[120px_minmax(0,1fr)] gap-x-3 gap-y-2 px-4 py-3 text-[11.5px]">
                        <dt className="text-faint">{tr("Source records")}</dt><dd className="text-ink">{selected.total_records}</dd>
                        <dt className="text-faint">{tr("Pending candidates")}</dt><dd className="text-ink">{selected.pending_candidates}</dd>
                        <dt className="text-faint">{tr("Accepted")}</dt><dd className="text-ink">{selected.accepted_candidates}</dd>
                        <dt className="text-faint">{tr("Ignored")}</dt><dd className="text-ink">{selected.ignored_candidates}</dd>
                        <dt className="text-faint">{tr("Model")}</dt><dd className="text-ink break-all">{selected.model}</dd>
                        <dt className="text-faint">{tr("Prompt version")}</dt><dd className="text-ink">{selected.prompt_version}</dd>
                        <dt className="text-faint">{tr("Created")}</dt><dd className="text-ink">{formatTime(selected.created_at, tr)}</dd>
                      </dl>
                      {(selected.candidates?.length ?? 0) > 0 && <div className="border-t border-line px-4 py-3"><div className="text-[11px] font-medium text-muted mb-2">{tr("Candidate results")}</div><div className="space-y-2 max-h-56 overflow-y-auto hairline-scroll">{selected.candidates!.map((candidate) => <div key={candidate.candidate_id} className="bg-paper px-2.5 py-2 rounded-lg"><div className="text-[10px] text-muted">{candidateTypeLabel(candidate, tr)} · {tr(candidate.status)}</div><div className="text-[11.5px] text-ink mt-1 line-clamp-3">{candidate.content}</div></div>)}</div></div>}
                      {selected.pending_candidates > 0 && <div className="border-t border-line px-4 py-3"><button type="button" className="h-8 px-3 rounded-lg bg-accent text-onAccent text-[11.5px]" onClick={onReview}>{tr("Review pending candidates")}</button></div>}
                    </>
                  )}
                  {detailError && <div className="px-4 pb-3"><InlineFeedback tone="danger" title={tr("Task details unavailable")} body={detailError} /></div>}
                </div>
              )}
            </section>
          </div>
        )}
      </div>
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

function PersonalityDashboard({ memories, onBack }: { memories: MemoryRecord[]; onBack: () => void }) {
  const { tr } = useI18n();
  const [usageRecords, setUsageRecords] = useState<MemoryUsageRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [usageError, setUsageError] = useState(false);

  useEffect(() => {
    setLoading(true);
    setUsageError(false);
    getMemoryUsageHistory(100)
      .then((res) => setUsageRecords(res.records))
      .catch(() => setUsageError(true))
      .finally(() => setLoading(false));
  }, []);

  const typeDistribution = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const m of memories) {
      const key = m.key || "untyped";
      counts[key] = (counts[key] || 0) + 1;
    }
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([key, count]) => ({ key, count, pct: memories.length ? Math.round((count / memories.length) * 100) : 0 }));
  }, [memories]);

  const topUsed = useMemo(() => {
    const freq: Record<number, { count: number; content: string; key: string | null }> = {};
    for (const r of usageRecords) {
      if (!freq[r.memory_id]) freq[r.memory_id] = { count: 0, content: r.content, key: r.key };
      freq[r.memory_id].count++;
    }
    return Object.entries(freq)
      .map(([id, v]) => ({ memory_id: Number(id), ...v }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 10);
  }, [usageRecords]);

  const typeLabel = (key: string) => {
    const found = MEMORY_TYPES.find(([k]) => k === key);
    return found ? found[1] : key;
  };

  return (
    <main className="flex-1 min-w-0 min-h-0 overflow-y-auto hairline-scroll bg-paper" data-testid="personality-dashboard">
      <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6">
        <button className="inline-flex items-center gap-1.5 text-[12px] text-muted hover:text-ink mb-4" onClick={onBack}>
          <Icon name="arrowLeft" size={14} /> {tr("Back to memory")}
        </button>
        <div className="mb-6">
          <h1 className="text-[24px] font-semibold text-heading">{tr("Personality & Usage")}</h1>
          <p className="text-[12.5px] text-muted mt-0.5">{tr("Your memories shape the agent's personality. Here's a summary of what it knows and uses most.")}</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Type Distribution */}
          <section className="border border-line rounded-xl bg-panel p-5">
            <h2 className="text-[14px] font-semibold text-heading mb-3">{tr("Memory type distribution")}</h2>
            {typeDistribution.length === 0 ? (
              <p className="text-[12px] text-muted">{tr("No confirmed memories yet.")}</p>
            ) : (
              <div className="space-y-2">
                {typeDistribution.map(({ key, count, pct }) => (
                  <div key={key} className="flex items-center gap-3">
                    <span className="w-32 text-[12px] text-muted truncate">{tr(typeLabel(key))}</span>
                    <div className="flex-1 h-5 rounded-full bg-surfaceAlt overflow-hidden">
                      <div className="h-full rounded-full bg-accent/70" style={{ width: `${Math.max(pct, 3)}%` }} />
                    </div>
                    <span className="text-[11px] text-ink w-10 text-right">{count} ({pct}%)</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Most Used Memories */}
          <section className="border border-line rounded-xl bg-panel p-5">
            <h2 className="text-[14px] font-semibold text-heading mb-3">{tr("Most-used memories")}</h2>
            {loading ? (
              <p className="text-[12px] text-muted">{tr("Loading usage data...")}</p>
            ) : usageError ? (
              <p className="text-[12px] text-danger">{tr("Could not load usage data.")}</p>
            ) : topUsed.length === 0 ? (
              <p className="text-[12px] text-muted">{tr("No usage records yet. Memories are tracked each time they are cited in a conversation.")}</p>
            ) : (
              <div className="space-y-2">
                {topUsed.map((item) => (
                  <div key={item.memory_id} className="flex items-start gap-2 px-2 py-1.5 rounded-lg hover:bg-paper">
                    <span className="shrink-0 mt-0.5 w-6 h-6 rounded-full bg-accentSoft text-accent grid place-items-center text-[11px] font-semibold">{item.count}</span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[12px] text-ink line-clamp-2">{item.content}</div>
                      {item.key && <span className="text-[10px] text-muted">{tr(typeLabel(item.key))}</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* Recent Usage Timeline */}
        <section className="mt-6 border border-line rounded-xl bg-panel p-5">
          <h2 className="text-[14px] font-semibold text-heading mb-3">{tr("Recent memory usage")}</h2>
          {loading ? (
            <p className="text-[12px] text-muted">{tr("Loading...")}</p>
          ) : usageRecords.length === 0 ? (
            <p className="text-[12px] text-muted">{tr("No usage history yet.")}</p>
          ) : (
            <div className="max-h-72 overflow-y-auto space-y-1">
              {usageRecords.slice(0, 30).map((r) => (
                <div key={r.usage_id} className="flex items-center gap-3 px-2 py-1.5 rounded-lg hover:bg-paper text-[12px]">
                  <span className="text-muted shrink-0 w-28">{new Date(r.used_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
                  <span className="text-ink flex-1 truncate">{r.content}</span>
                  {r.key && <span className="shrink-0 px-1.5 rounded bg-surfaceAlt text-[10px] text-muted">{r.key}</span>}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
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
  const [availableSources, setAvailableSources] = useState<string[]>([]);
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

  useEffect(() => {
    getSensoryStats()
      .then((stats) => setAvailableSources(Object.keys(stats.sources).sort()))
      .catch(() => setAvailableSources([]));
  }, []);

  const sources = availableSources.length
    ? availableSources
    : [...new Set(records.map((record) => record.source_type))].sort();
  const hasFilters = Boolean(query.trim() || source !== "all" || governance !== "all");

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
          <option value="processing">{tr("Governance in progress")}</option>
          <option value="processed">{tr("Governed")}</option>
          <option value="skipped">{tr("Skipped by governance")}</option>
          <option value="failed">{tr("Governance failed")}</option>
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
        <PageState
          icon={hasFilters ? "search" : "diamond"}
          title={tr(hasFilters ? "No source records match these filters." : "No source records yet")}
          body={tr(hasFilters
            ? "Change the search or filters to see more records."
            : "Connect Codex or TRAE CLI, or start a Smallink conversation to collect source data.")}
        />
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

function MemoryDetail({
  memory,
  archived = false,
  onChanged,
}: {
  memory: MemoryRecord;
  archived?: boolean;
  onChanged: () => Promise<void>;
}) {
  const { tr } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const changeStatus = async () => {
    setBusy(true);
    setError("");
    try {
      await setMemoryArchived(memory.id, !archived);
      await onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Could not update memory status"));
    } finally {
      setBusy(false);
    }
  };
  return <div>
    <div className="px-4 py-3 border-b border-line"><div className="text-[13px] font-semibold text-ink">{tr("Memory details")}</div><div className="text-[10.5px] text-faint mt-0.5">#{memory.id}</div></div>
    <div className="px-4 py-4 text-[13px] leading-relaxed text-ink whitespace-pre-wrap">{memory.content}</div>
    <dl className="grid grid-cols-[92px_minmax(0,1fr)] gap-x-3 gap-y-2 px-4 py-3 border-t border-line text-[11.5px]">
      <dt className="text-faint">{tr("Type")}</dt><dd className="text-ink">{typeLabel(memory, tr)}</dd>
      <dt className="text-faint">{tr("Scope")}</dt><dd className="text-ink">{scopeLabel(memory, tr)}</dd>
      <dt className="text-faint">{tr("Status")}</dt><dd className="text-ink">{tr(archived ? "archived" : "active")}</dd>
      <dt className="text-faint">{tr("Created")}</dt><dd className="text-ink">{formatTime(memory.created_at, tr)}</dd>
    </dl>
    {error && <div className="px-4 pb-3"><InlineFeedback tone="danger" title={tr("Memory update failed")} body={error} /></div>}
    <div className="border-t border-line px-4 py-3">
      <button type="button" disabled={busy} onClick={() => void changeStatus()} className="h-8 px-3 rounded-lg border border-line text-[11.5px] text-ink hover:border-accent/40 disabled:opacity-50">{tr(archived ? "Restore memory" : "Archive memory")}</button>
    </div>
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

function ConfidenceBadge({ confidence }: { confidence: number }) {
  let color: string;
  let label: string;
  if (confidence >= 0.8) {
    color = "bg-green-100 text-green-700 border-green-200";
    label = "High";
  } else if (confidence >= 0.5) {
    color = "bg-amber-50 text-amber-700 border-amber-200";
    label = "Med";
  } else {
    color = "bg-red-50 text-red-600 border-red-200";
    label = "Low";
  }
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[9.5px] font-medium border ${color}`}>
      {label} {Math.round(confidence * 100)}%
    </span>
  );
}
