import { useEffect, useMemo, useState } from "react";
import { getMemory, getSensoryStats, type MemoryRecord, type SensoryStats } from "../api";
import { baseName } from "../paths";
import { useI18n } from "../i18n";
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

export function MemoryView() {
  const { tr } = useI18n();
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [pending, setPending] = useState<MemoryRecord[]>([]);
  const [selectedType, setSelectedType] = useState<MemoryType | null>(null);
  const [selectedMemory, setSelectedMemory] = useState<MemoryRecord | null>(null);
  const [pendingView, setPendingView] = useState(false);
  const [sourceStats, setSourceStats] = useState<SensoryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      // Confirmed (active) and the pipeline's pending queue load together; pending is
      // read-only this phase — the confirm/edit flow is a later phase.
      const [active, awaiting, stats] = await Promise.all([
        getMemory(),
        getMemory("pending"),
        getSensoryStats().catch(() => null),
      ]);
      setMemories(active);
      setPending(awaiting);
      setSourceStats(stats);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load memories");
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

  if (pendingView) {
    return (
      <main className="flex-1 min-w-0 min-h-0 overflow-y-auto hairline-scroll bg-paper" data-testid="memory-view">
        <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6">
          <button className="inline-flex items-center gap-1.5 text-[12px] text-muted hover:text-ink mb-4" onClick={() => { setPendingView(false); setSelectedMemory(null); }}>
            <Icon name="arrowLeft" size={14} /> {tr("Back to memory types")}
          </button>
          <div className="mb-5">
            <h1 className="text-[24px] font-semibold text-heading">{tr("Awaiting confirmation")}</h1>
            <p className="text-[12.5px] text-muted mt-0.5">{tr("Memories the pipeline extracted from collected data. They are not used until you confirm them.")}</p>
          </div>
          <div className="grid grid-cols-1 min-[1080px]:grid-cols-[minmax(0,1fr)_360px] gap-4 items-start">
            <section className="border border-line rounded-lg bg-panel overflow-hidden min-w-0" data-testid="memory-pending-list">
              {pending.length === 0 ? (
                <div className="px-4 py-10 text-center">
                  <div className="text-[13px] font-medium text-ink">{tr("Nothing awaiting confirmation")}</div>
                  <div className="text-[12px] text-muted mt-1">{tr("Extracted candidate memories will appear here.")}</div>
                </div>
              ) : pending.map((item) => (
                <button key={item.id} className={`w-full text-left px-4 py-3 border-b border-line last:border-b-0 hover:bg-paper/70 ${selectedMemory?.id === item.id ? "bg-accentSoft/35" : ""}`} onClick={() => setSelectedMemory(item)}>
                  <div className="text-[13px] text-ink line-clamp-2">{item.content}</div>
                  <div className="text-[11px] text-muted mt-1.5">{typeLabel(item, tr)} · {scopeLabel(item, tr)} · {formatTime(item.created_at, tr)}</div>
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

  if (selectedType) {
    const type = MEMORY_TYPES.find(([key]) => key === selectedType)!;
    return (
      <main className="flex-1 min-w-0 min-h-0 overflow-y-auto hairline-scroll bg-paper" data-testid="memory-view">
        <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6">
          <button className="inline-flex items-center gap-1.5 text-[12px] text-muted hover:text-ink mb-4" onClick={() => { setSelectedType(null); setSelectedMemory(null); }}>
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

        <div className="flex flex-wrap gap-x-6 gap-y-2 border-y border-line py-3 mb-5 text-[12px] text-muted">
          <span><b className="text-[18px] text-heading mr-1.5">{memories.length}</b>{tr("Confirmed memories")}</span>
          <span><b className="text-[18px] text-heading mr-1.5">{memories.filter((m) => m.scope === "global").length}</b>{tr("Global memories")}</span>
          <span><b className="text-[18px] text-heading mr-1.5">{memories.filter((m) => m.scope === "workspace").length}</b>{tr("Project memories")}</span>
          {sourceStats && (
            <>
              <span><b className="text-[18px] text-heading mr-1.5">{sourceStats.total}</b>{tr("Source records")}</span>
              {(sourceStats.sources.traex || 0) > 0 && (
                <span><b className="text-[18px] text-heading mr-1.5">{sourceStats.sources.traex}</b>{tr("TRAE records")}</span>
              )}
              {(sourceStats.sources.codex || 0) > 0 && (
                <span><b className="text-[18px] text-heading mr-1.5">{sourceStats.sources.codex}</b>{tr("Codex records")}</span>
              )}
            </>
          )}
        </div>

        {pending.length > 0 && (
          <button
            className="w-full mb-5 flex items-center justify-between gap-3 rounded-lg border border-accent/40 bg-accentSoft/20 px-3.5 py-3 text-left hover:bg-accentSoft/30"
            onClick={() => { setPendingView(true); setSelectedMemory(null); }}
            data-testid="memory-pending-banner"
          >
            <span className="flex items-center gap-2 text-[12.5px] text-ink">
              <Icon name="sparkle" size={14} className="text-accent" />
              {tr("{count} memories awaiting confirmation", { count: pending.length })}
            </span>
            <span className="flex items-center gap-1 text-[12px] text-accent">{tr("Review")} <Icon name="chevronRight" size={14} /></span>
          </button>
        )}

        {error && <div role="alert" className="mb-4 rounded-lg border border-danger/30 bg-dangerSoft px-3 py-2 text-[12px] text-danger">{error}</div>}
        {loading ? <div className="py-10 text-[12.5px] text-muted">{tr("Loading memories…")}</div> : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {MEMORY_TYPES.map(([key, label, description]) => {
              const items = memories.filter((item) => item.key === key);
              return (
                <button key={key} className="group min-h-[132px] text-left bg-panel border border-line rounded-lg p-4 hover:border-accent/50 hover:bg-accentSoft/15 transition-colors" onClick={() => setSelectedType(key)} aria-label={tr("Open {type} memories", { type: tr(label) })}>
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
        )}

        {!loading && memories.length === 0 && <div className="mt-5 border-t border-line pt-4 text-[12px] text-muted">{tr("There are no confirmed memories yet. Candidate memories must be reviewed before they appear here.")}</div>}
        {!loading && legacyCount > 0 && <div className="mt-5 rounded-lg border border-warnLine bg-warnSoft px-3.5 py-3 text-[12px] text-muted">{tr("{count} earlier memories need a standard memory type before they appear in the cards.", { count: legacyCount })}</div>}
      </div>
    </main>
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

function formatTime(value: string | null, tr: (text: string) => string): string {
  if (!value) return tr("Unknown time");
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
