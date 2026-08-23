import { useEffect, useState } from "react";
import { getPrompts, type PromptLayer, type PromptsResponse } from "../api";
import { useI18n } from "../i18n";
import { Icon } from "./Icon";
import { PageState } from "./AsyncFeedback";

const SAFETY_COLORS: Record<string, string> = {
  safe: "bg-okSoft text-ok",
  caution: "bg-warnSoft text-warn",
  system: "bg-dangerSoft text-danger",
};

const SAFETY_LABELS: Record<string, string> = {
  safe: "Safe to edit",
  caution: "Edit with care",
  system: "System-generated",
};

export function PromptsView({ onBack }: { onBack: () => void }) {
  const { tr } = useI18n();
  const [data, setData] = useState<PromptsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getPrompts()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load prompts"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Shell onBack={onBack}>
        <PageState
          icon="code"
          title={tr("Loading system prompts…")}
          body={tr("Reading prompt layers and safety annotations.")}
        />
      </Shell>
    );
  }

  if (error || !data) {
    return (
      <Shell onBack={onBack}>
        <PageState
          icon="code"
          title={tr("Could not load prompts")}
          body={error || tr("Unknown error")}
          action={tr("Retry")}
          onAction={() => window.location.reload()}
        />
      </Shell>
    );
  }

  return (
    <Shell onBack={onBack}>
      <div className="mb-5">
        <h1 className="text-[24px] font-semibold text-heading">{tr("System Prompts")}</h1>
        <p className="text-[12.5px] text-muted mt-0.5">
          {tr("All prompt layers that compose the agent's system instructions. Click to expand full text.")}
        </p>
      </div>

      {/* Assembly order */}
      <div className="rounded-lg border border-line bg-panel p-4 mb-5">
        <div className="text-[13px] font-medium text-ink mb-2">{tr("Assembly Order")}</div>
        <div className="text-[12px] text-muted space-y-1">
          {data.assembly_order.map((step, i) => (
            <div key={i} className="flex gap-2">
              <span className="text-accent font-mono shrink-0">{i + 1}.</span>
              <span>{step}</span>
            </div>
          ))}
        </div>
        <div className="mt-3 pt-3 border-t border-line text-[11px] text-muted">
          {tr("Source")}: <code className="bg-paper px-1 py-0.5 rounded">{data.assembly_source}</code>
        </div>
      </div>

      {/* Safety legend */}
      <div className="flex items-center gap-4 mb-4 text-[11.5px]">
        {Object.entries(SAFETY_LABELS).map(([key, label]) => (
          <span key={key} className={"inline-flex items-center gap-1.5 px-2 py-1 rounded-full " + SAFETY_COLORS[key]}>
            {label}
          </span>
        ))}
      </div>

      {/* Prompt layers */}
      <div className="space-y-3">
        {data.layers.map((layer) => (
          <PromptCard
            key={layer.id}
            layer={layer}
            expanded={expandedId === layer.id}
            onToggle={() => setExpandedId(expandedId === layer.id ? null : layer.id)}
          />
        ))}
      </div>

      {/* Notes about non-static layers */}
      <div className="mt-6 rounded-lg border border-line bg-panel p-4">
        <div className="text-[13px] font-medium text-ink mb-2">{tr("Additional Layers (Dynamic)")}</div>
        <div className="space-y-2">
          {Object.entries(data.notes).map(([key, note]) => (
            <div key={key} className="text-[12px] text-muted">
              <span className="font-medium text-ink">{key.replace(/_/g, " ")}:</span>{" "}
              {note}
            </div>
          ))}
        </div>
      </div>
    </Shell>
  );
}

function Shell({ onBack, children }: { onBack: () => void; children: React.ReactNode }) {
  const { tr } = useI18n();
  return (
    <main className="flex-1 min-w-0 min-h-0 overflow-y-auto hairline-scroll bg-paper" data-testid="prompts-view">
      <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6">
        <button
          className="inline-flex items-center gap-1.5 text-[12px] text-muted hover:text-ink mb-4"
          onClick={onBack}
        >
          <Icon name="arrowLeft" size={14} /> {tr("Back to memory")}
        </button>
        {children}
      </div>
    </main>
  );
}

function PromptCard({
  layer,
  expanded,
  onToggle,
}: {
  layer: PromptLayer;
  expanded: boolean;
  onToggle: () => void;
}) {
  const safetyColor = SAFETY_COLORS[layer.safety] || SAFETY_COLORS.safe;
  const safetyLabel = SAFETY_LABELS[layer.safety] || "Unknown";

  return (
    <div className="rounded-lg border border-line bg-panel overflow-hidden">
      <button
        className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-paper/50"
        onClick={onToggle}
      >
        <span className="w-6 h-6 grid place-items-center rounded-md bg-accentSoft text-accent text-[11px] font-bold shrink-0">
          {layer.layer}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-medium text-ink">{layer.name}</div>
          <div className="text-[11.5px] text-muted mt-0.5 line-clamp-1">{layer.description}</div>
        </div>
        <span className={"text-[10.5px] px-2 py-0.5 rounded-full shrink-0 " + safetyColor}>
          {safetyLabel}
        </span>
        <Icon name={expanded ? "chevronDown" : "chevronRight"} size={14} className="text-muted shrink-0" />
      </button>

      {expanded && (
        <div className="border-t border-line">
          {/* Safety note */}
          <div className="px-4 py-2.5 bg-paper/30 border-b border-line">
            <div className="text-[11.5px] text-muted">
              <span className="font-medium text-ink">Impact: </span>
              {layer.safety_note}
            </div>
            <div className="text-[11px] text-muted mt-1">
              <span className="font-medium text-ink">Source: </span>
              <code className="bg-paper px-1 py-0.5 rounded text-[10.5px]">{layer.source}</code>
              <span className="ml-2">Scope: {layer.scope}</span>
            </div>
          </div>

          {/* Full prompt text */}
          <div className="px-4 py-3 max-h-[500px] overflow-y-auto hairline-scroll">
            <pre className="text-[12px] leading-relaxed text-ink whitespace-pre-wrap font-mono break-words">
              {layer.text}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
