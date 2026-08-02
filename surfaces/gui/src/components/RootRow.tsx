import type { RootInfo } from "../api";
import { Icon } from "./Icon";
import { baseName } from "../paths";
import { useI18n } from "../i18n";

// One directory row, shared by the composer popover and the session start panel. The primary is the
// session's bound workspace — the repo/folder for Code/Ops (shown by name), or a throwaway scratch
// for Link (shown as "Temporary space"). It's always read-write and can't be removed.
export function RootRow({
  root,
  busy,
  scratchPrimary,
  branch,
  onToggle,
  onRemove,
}: {
  root: RootInfo;
  busy?: boolean;
  scratchPrimary?: boolean;
  // The workspace's git branch — shown on the primary row (drawer's Working directories, §23).
  branch?: string | null;
  onToggle: (r: RootInfo) => void;
  onRemove: (path: string) => void;
}) {
  const { tr } = useI18n();
  const label = root.primary
    ? scratchPrimary
      ? tr("Temporary space")
      : baseName(root.path)
    : root.label;
  return (
    <div className={"root-row" + (root.exists ? "" : " missing")}>
      <Icon name="folder" size={14} className="root-ico" />
      <span className="root-text" title={root.path}>
        <span className="root-label">
          {label}
          {root.primary && !scratchPrimary && <span className="root-tag"> {tr("main")}</span>}
          {branch && (
            <span className="root-tag root-branch">
              {" "}
              <Icon name="branch" size={11} /> {branch}
            </span>
          )}
        </span>
        <span className="root-path">{root.path}</span>
      </span>
      {!root.exists && <span className="root-tag warn">{tr("missing")}</span>}
      <button
        className={"root-access" + (root.writable ? " rw" : " ro")}
        onClick={() => onToggle(root)}
        disabled={busy || root.primary}
        title={tr(root.primary ? "The main workspace is always read-write" : "Toggle read-only / read-write")}
      >
        {tr(root.writable ? "Read-write" : "Read-only")}
      </button>
      {!root.primary && (
        <button className="root-x" onClick={() => onRemove(root.path)} disabled={busy} title={tr("Remove")}>
          ×
        </button>
      )}
    </div>
  );
}
