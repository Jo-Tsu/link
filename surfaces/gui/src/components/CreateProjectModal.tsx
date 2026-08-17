import { useState } from "react";
import { chooseFolder } from "../tauri";
import { Icon } from "./Icon";
import { baseName } from "../paths";
import { useI18n } from "../i18n";

interface Props {
  onConfirm: (name: string, workspacePath: string) => void;
  onCancel: () => void;
}

export function CreateProjectModal({ onConfirm, onCancel }: Props) {
  const { tr } = useI18n();
  const [name, setName] = useState("");
  const [folder, setFolder] = useState("");
  const [error, setError] = useState("");

  const browse = async () => {
    const picked = await chooseFolder();
    if (picked) {
      setFolder(picked);
      if (!name) setName(baseName(picked));
    }
  };

  const submit = () => {
    const trimName = name.trim();
    const trimFolder = folder.trim();
    if (!trimFolder) {
      setError(tr("Please select a folder"));
      return;
    }
    onConfirm(trimName || baseName(trimFolder), trimFolder);
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onCancel()}
    >
      <div className="w-[480px] bg-panel rounded-2xl shadow-2xl border border-line overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-3">
          <h2 className="text-[18px] font-semibold text-ink">
            {tr("Create Project")}
          </h2>
          <button
            className="w-7 h-7 grid place-items-center rounded-lg text-muted hover:text-ink hover:bg-paper"
            onClick={onCancel}
            aria-label={tr("Close")}
          >
            <Icon name="x" size={16} />
          </button>
        </div>

        {/* Name input */}
        <div className="px-6 pb-4">
          <div className="flex items-center gap-3 border border-line rounded-xl px-3 py-2.5 focus-within:border-accent">
            <Icon name="folder" size={18} className="text-muted shrink-0" />
            <input
              className="flex-1 bg-transparent text-[14px] text-ink placeholder-faint outline-none"
              placeholder={tr("Project name")}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              autoFocus
            />
          </div>
        </div>

        {/* Folder picker */}
        <div className="px-6 pb-5">
          <div className="text-[13px] text-muted font-medium mb-2">
            {tr("Source folder")}
          </div>
          <div
            className="border border-line rounded-xl px-4 py-6 flex flex-col items-center justify-center gap-2 cursor-pointer hover:bg-paper/50 transition-colors"
            onClick={browse}
          >
            {folder ? (
              <>
                <Icon name="folder" size={24} className="text-ink" />
                <span className="text-[14px] text-ink font-medium">{baseName(folder)}</span>
                <span className="text-[12px] text-faint">{folder}</span>
              </>
            ) : (
              <>
                <Icon name="folderPlus" size={24} className="text-muted" />
                <span className="text-[13px] text-muted">
                  {tr("Add a folder that Smallink can read and edit")}
                </span>
              </>
            )}
          </div>
          {error && <div className="text-[12px] text-danger mt-2">{error}</div>}
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 px-6 pb-5">
          <button
            className="px-4 py-2 text-[13px] text-muted hover:text-ink rounded-lg"
            onClick={onCancel}
          >
            {tr("Cancel")}
          </button>
          <button
            className="px-5 py-2 text-[13px] font-medium text-onAccent bg-ink rounded-lg hover:opacity-90 disabled:opacity-40"
            onClick={submit}
            disabled={!folder.trim()}
          >
            {tr("Create project")}
          </button>
        </div>
      </div>
    </div>
  );
}
