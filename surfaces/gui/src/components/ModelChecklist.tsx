import { useEffect, useState } from "react";
import { addModel, getSettings, removeModel, setDefaultModel, setModelPurposes } from "../api";
import { useI18n } from "../i18n";
import { InlineFeedback } from "./AsyncFeedback";

// One provider's models as a checklist: tick = shown in the composer's model picker (the
// curated list), the black "default" badge marks the model new sessions use, and hovering any
// other row reveals "Make default". A free-type row below adds models by hand, so brand-new
// releases work without an app update. Shared by Onboarding and Manage → Configure Models.
export function ModelChecklist({
  provider,
  knownProviders,
  suggested,
  curated,
  defaultModel,
  labels,
  purposes,
  modelPurposes,
  onChanged,
}: {
  provider: string; // decides the id prefix; OpenAI models stay bare
  knownProviders: string[]; // all provider names, to parse prefixes in curated ids
  suggested: string[]; // bare model names suggested by the provider
  curated: string[]; // the full curated list (all providers, full ids)
  defaultModel: string;
  labels?: Record<string, string>; // curated display names (full id → label); raw id when absent
  purposes?: string[]; // available purpose options (chat/memory/title)
  modelPurposes?: Record<string, string[]>; // model id → its tagged purposes
  onChanged: (next: { models: string[]; model: string }) => void;
}) {
  const { tr } = useI18n();
  const [draft, setDraft] = useState("");
  const [tags, setTags] = useState<Record<string, string[]>>(modelPurposes || {});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  useEffect(() => setTags(modelPurposes || {}), [modelPurposes]);

  const provOf = (id: string) => {
    const i = id.indexOf(":");
    return i > 0 && knownProviders.includes(id.slice(0, i)) ? id.slice(0, i) : "openai";
  };
  const prefixed = (m: string) => (provider === "openai" || provOf(m) !== "openai" ? m : `${provider}:${m}`);
  const bare = (id: string) => (id.startsWith(`${provider}:`) ? id.slice(provider.length + 1) : id);

  const rows = [
    ...suggested.map(prefixed),
    ...curated.filter((id) => provOf(id) === provider),
  ].filter((id, i, a) => a.indexOf(id) === i);
  // Only memory is wired to runtime today. Hiding chat/title avoids controls that save but
  // do not affect behavior; they can return when their runtime routes exist.
  const effectivePurposes = (purposes || []).filter((purpose) => purpose === "memory");

  const checked = (id: string) => curated.includes(id);
  const refresh = async () => {
    const s = await getSettings();
    onChanged({ models: s.models, model: s.model });
  };

  const tick = async (id: string, on: boolean) => {
    setBusy(`model:${id}`);
    setError("");
    setSaved("");
    try {
      const res = on ? await addModel(id) : await removeModel(id);
      if (!res.ok) throw new Error(res.error || tr("Could not update this model."));
      if (!on) {
        if ((tags[id] || []).length > 0) {
          const purposeResult = await setModelPurposes(id, []);
          if (!purposeResult.ok) {
            throw new Error(purposeResult.error || tr("Could not update model use."));
          }
        }
        setTags((prev) => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
      }
      onChanged({ models: res.models, model: res.model });
      setSaved(tr("Model selection saved."));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Could not update this model."));
    } finally {
      setBusy(null);
    }
  };
  const makeDefault = async (id: string) => {
    setBusy(`default:${id}`);
    setError("");
    setSaved("");
    try {
      if (!checked(id)) {
        const added = await addModel(id);
        if (!added.ok) throw new Error(added.error || tr("Could not update this model."));
      }
      const result = await setDefaultModel(id);
      if (!result.ok) throw new Error(result.error || tr("Could not set the default model."));
      await refresh();
      setSaved(tr("Default model updated."));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Could not set the default model."));
    } finally {
      setBusy(null);
    }
  };
  const togglePurpose = async (id: string, purpose: string) => {
    const current = tags[id] || [];
    const next = current.includes(purpose)
      ? current.filter((p) => p !== purpose)
      : [...current, purpose];
    const previous = tags;
    setBusy(`purpose:${id}:${purpose}`);
    setError("");
    setSaved("");
    setTags((prev) => ({ ...prev, [id]: next }));
    try {
      const res = await setModelPurposes(id, next);
      if (!res.ok) throw new Error(res.error || tr("Could not update model use."));
      if (res.model_purposes) setTags(res.model_purposes);
      setSaved(tr("Memory model setting saved."));
    } catch (reason) {
      setTags(previous);
      setError(reason instanceof Error ? reason.message : tr("Could not update model use."));
    } finally {
      setBusy(null);
    }
  };
  const purposeLabel = (p: string) =>
    ({ chat: tr("For chat"), memory: tr("For memory"), title: tr("For titles") } as Record<string, string>)[p] || p;
  const add = async () => {
    const typed = draft.trim();
    if (!typed) return;
    setBusy("add");
    setError("");
    setSaved("");
    try {
      const res = await addModel(prefixed(typed));
      if (!res.ok) throw new Error(res.error || tr("Could not add this model."));
      setDraft("");
      onChanged({ models: res.models, model: res.model });
      setSaved(tr("Model added."));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Could not add this model."));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mlist">
      {rows.map((id) => {
        const isDefault = id === defaultModel;
        return (
          <div className={"mlist-row" + (checked(id) ? "" : " off")} key={id}>
            <label className="mlist-main">
              <input
                type="checkbox"
                checked={checked(id)}
                  disabled={isDefault || busy !== null}
                title={isDefault ? tr("The default model is always shown. Make another model the default first.") : undefined}
                onChange={(e) => tick(id, e.target.checked)}
              />
              <span className="mlist-name" title={id}>
                {labels?.[id] || bare(id)}
              </span>
            </label>
            {effectivePurposes.length > 0 && checked(id) && (
              <div className="mlist-purposes" title={tr("Use this model for")}>
                {effectivePurposes.map((p) => {
                  const on = (tags[id] || []).includes(p);
                  const pending = busy === `purpose:${id}:${p}`;
                  return (
                    <button
                      key={p}
                      type="button"
                      className={"mlist-purpose" + (on ? " on" : "")}
                      aria-pressed={on}
                      aria-label={`${labels?.[id] || bare(id)} · ${purposeLabel(p)}`}
                      onClick={() => togglePurpose(id, p)}
                      disabled={busy !== null}
                    >
                      {pending ? tr("Saving…") : purposeLabel(p)}
                    </button>
                  );
                })}
              </div>
            )}
            {isDefault ? (
              <span className="mlist-default">{tr("default")}</span>
            ) : (
              <button className="mlist-make" onClick={() => makeDefault(id)} disabled={busy !== null}>
                {busy === `default:${id}` ? tr("Saving…") : tr("Make default")}
              </button>
            )}
          </div>
        );
      })}
      <div className="mlist-add">
        <input
          placeholder={tr("Add another model…")}
          value={draft}
          spellCheck={false}
          autoComplete="off"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && busy === null && add()}
          disabled={busy !== null}
        />
        <button className="btn-primary sm" onClick={add} disabled={!draft.trim() || busy !== null}>
          {busy === "add" ? tr("Saving…") : tr("Add")}
        </button>
      </div>
      {(error || saved) && (
        <div className="mt-2">
          <InlineFeedback
            tone={error ? "danger" : "success"}
            title={error || saved}
            body={error ? tr("Your previous setting is still in effect.") : undefined}
          />
        </div>
      )}
    </div>
  );
}
