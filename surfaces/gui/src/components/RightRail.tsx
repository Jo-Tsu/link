import { useEffect, useRef, useState, type ReactNode } from "react";
// Emits the asset URL only; the worker itself loads lazily with the pdfjs chunk.
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import {
  getArtifacts,
  readArtifact,
  revealArtifact,
  type ArtifactContent,
  type ArtifactInfo,
} from "../api";
import type { TodoItem } from "../types";
import { AccessSection } from "./AccessSection";
import { Icon } from "./Icon";
import { Markdown, normalizeArtifactPath, OPEN_ARTIFACT_EVENT } from "./Markdown";
import { useI18n } from "../i18n";

type Panel = "progress" | "artifacts";

// Quiet file-type icons for the artifact list (the colored kind pills read as noisy).
function kindIcon(kind: string): "file" | "fileCode" | "image" | "table" {
  if (kind === "image") return "image";
  if (kind === "html" || kind === "code") return "fileCode";
  if (kind === "csv" || kind === "sheet") return "table";
  return "file"; // markdown, text, pdf, everything else
}

// Fallback kind for an artifact: link whose path isn't in the list (yet) — mirrors the
// server's extension mapping closely enough for the viewer to pick a renderer.
function kindFromPath(path: string): string {
  const ext = (path.split(".").pop() || "").toLowerCase();
  if (["png", "jpg", "jpeg", "gif", "svg", "webp"].includes(ext)) return "image";
  if (["html", "htm"].includes(ext)) return "html";
  if (ext === "md") return "markdown";
  if (ext === "csv") return "csv";
  if (ext === "pdf") return "pdf";
  if (["py", "js", "ts", "tsx", "jsx", "json", "sh", "css"].includes(ext)) return "code";
  return "text";
}

interface Props {
  active: boolean;
  sessionId: string;
  refreshKey: number;
  toolNames: string[];
  todo: TodoItem[];
  running: boolean;
  // Fires when a full artifact preview opens/closes, so the app can auto-collapse the left nav
  // to give the preview (PDF/webpage/sheet) more room (#3).
  onPreviewChange?: (open: boolean) => void;
  onArtifactCount?: (count: number) => void;
  // §32: the rail is the ONE session panel for every non-chat persona. Artifacts stays
  // link-only (deliverables; code-family gets "Files" later — slot reserved); the Access
  // section (the former Session-settings drawer) renders for all.
  showArtifacts?: boolean;
  personaId?: string;
  projectScoped?: boolean;
  workspace?: string;
  branch?: string | null;
  scratchPrimary?: boolean;
  openAccessKey?: number;
  onOpenIntegrations?: () => void;
}

export function RightRail({
  active,
  sessionId,
  refreshKey,
  toolNames,
  todo,
  running,
  onPreviewChange,
  onArtifactCount,
  showArtifacts = true,
  personaId,
  projectScoped,
  workspace,
  branch,
  scratchPrimary,
  openAccessKey = 0,
  onOpenIntegrations,
}: Props) {
  const { tr, locale } = useI18n();
  const [open, setOpen] = useState<Record<Panel, boolean>>({
    progress: true,
    artifacts: true,
  });
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const [selected, setSelected] = useState<ArtifactInfo | null>(null);
  const [content, setContent] = useState<ArtifactContent | null>(null);
  const artifactRequestRef = useRef(0);
  const contentRequestRef = useRef(0);

  const refreshArtifacts = () => {
    const requestId = ++artifactRequestRef.current;
    const targetSessionId = sessionId;
    return getArtifacts(targetSessionId)
      .then((list) => {
        if (artifactRequestRef.current === requestId) {
          setArtifacts(list);
          onArtifactCount?.(list.length);
        }
        return list;
      })
      .catch(() => {
        if (artifactRequestRef.current === requestId) {
          setArtifacts([]);
          onArtifactCount?.(0);
        }
        return [];
      });
  };

  useEffect(() => {
    if (!active) return;
    if (showArtifacts) refreshArtifacts();
    return () => {
      artifactRequestRef.current += 1;
    };
  }, [active, sessionId, refreshKey, showArtifacts]);

  // Switching conversations closes any open artifact — it belongs to the previous session's
  // workspace, which the new session can't (and shouldn't) read.
  useEffect(() => {
    setSelected(null);
    setContent(null);
    setArtifacts([]);
    contentRequestRef.current += 1;
  }, [sessionId]);

  useEffect(() => {
    const requestId = ++contentRequestRef.current;
    setContent(null);
    if (!selected) return;
    readArtifact(sessionId, selected.path)
      .then((next) => {
        if (contentRequestRef.current === requestId) setContent(next);
      })
      .catch(() => {
        if (contentRequestRef.current === requestId) {
          setContent({ ok: false, path: selected.path, kind: selected.kind, error: tr("Could not load this artifact.") });
        }
      });
  }, [selected?.path, sessionId]);

  // Notify the app when a preview opens/closes (drives the left-nav auto-collapse).
  useEffect(() => {
    onPreviewChange?.(!!selected);
  }, [!!selected, onPreviewChange]);

  const reloadSelected = () => {
    if (!selected) return Promise.resolve();
    const targetSessionId = sessionId;
    const targetPath = selected.path;
    const requestId = ++contentRequestRef.current;
    setContent(null);
    return readArtifact(targetSessionId, targetPath)
      .then((next) => {
        if (contentRequestRef.current === requestId) setContent(next);
      })
      .catch(() => {
        if (contentRequestRef.current === requestId) {
          setContent({ ok: false, path: targetPath, kind: selected.kind, error: tr("Could not load this artifact.") });
        }
      });
  };

  // §34 (UX-016): [Title](artifact:path) chips in the transcript open the viewer directly.
  // Resolve against the loaded list first; on a miss, refresh once (the file may be
  // seconds old), then fall back to a minimal record — readArtifact validates the path.
  useEffect(() => {
    const minimal = (rawPath: string): ArtifactInfo => {
      const path = normalizeArtifactPath(rawPath);
      return ({
      path,
      name: path.split("/").pop() || path,
      kind: kindFromPath(path),
      size: 0,
      modified_at: 0,
    });
    };
    const match = (list: ArtifactInfo[], rawPath: string) => {
      const path = normalizeArtifactPath(rawPath);
      return list.find((artifact) => {
        const relative = normalizeArtifactPath(artifact.path);
        const absolute = normalizeArtifactPath(artifact.abs_path || "");
        const name = normalizeArtifactPath(artifact.name);
        return path === relative || path === absolute || path === name ||
          path.endsWith("/" + relative) || relative.endsWith("/" + path);
      });
    };
    const onOpen = (e: Event) => {
      const path = normalizeArtifactPath(String((e as CustomEvent).detail?.path || ""));
      if (!path) return;
      const found = match(artifacts, path);
      if (found) {
        setSelected(found);
        return;
      }
      const fallback = minimal(path);
      setSelected(fallback); // immediate visual response while the fresh artifact list arrives
      const requestId = ++artifactRequestRef.current;
      getArtifacts(sessionId)
        .then((list) => {
          if (artifactRequestRef.current !== requestId) return;
          setArtifacts(list);
          setSelected(match(list, path) ?? fallback);
        })
        .catch(() => {
          if (artifactRequestRef.current === requestId) setSelected(fallback);
        });
    };
    window.addEventListener(OPEN_ARTIFACT_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_ARTIFACT_EVENT, onOpen);
  }, [sessionId, artifacts]);

  if (!active) return null;

  return (
    <aside className={"right-rail" + (selected ? " artifact-mode" : "")}>
      {selected ? (
        <ArtifactViewer
          sessionId={sessionId}
          artifact={selected}
          content={content}
          onReload={reloadSelected}
          onBack={() => setSelected(null)}
        />
      ) : (
        <>
          <RailSection title={tr("Progress")} open={open.progress} onToggle={() => setOpen({ ...open, progress: !open.progress })}>
            <ProgressSummary running={running} toolNames={toolNames} todo={todo} />
          </RailSection>

          {showArtifacts && (
          <RailSection
            title={`${tr("Artifacts")}${artifacts.length ? ` (${artifacts.length})` : ""}`}
            open={open.artifacts}
            onToggle={() => setOpen({ ...open, artifacts: !open.artifacts })}
            action={
              <>
                {artifacts.length > 0 && (
                  <button
                    className="rail-mini-btn"
                    onClick={(e) => { e.stopPropagation(); revealArtifact(sessionId, artifacts[0].path, "reveal"); }}
                    title={tr("Show the folder where these files are saved")}
                  >
                    <Icon name="folder" size={13} />
                  </button>
                )}
                <button className="rail-mini-btn" onClick={(e) => { e.stopPropagation(); refreshArtifacts(); }} title={tr("Refresh artifacts")}><Icon name="refresh" size={13} /></button>
              </>
            }
          >
            {artifacts.length === 0 ? (
              <div className="rail-muted">{tr("No previewable files yet.")}</div>
            ) : (
              <div className="artifact-list">
                {artifacts.slice(0, 16).map((a) => (
                  <button className="artifact-row" key={a.path} onClick={() => setSelected(a)}>
                    <span className="artifact-ico" title={a.kind}>
                      <Icon name={kindIcon(a.kind)} size={17} />
                    </span>
                    <span className="artifact-name">
                      {a.name}
                      <span className="artifact-row-meta">{formatBytes(a.size)} · {formatTime(a.modified_at, locale)}</span>
                    </span>
                    <span className="artifact-open">{tr("Open")}</span>
                  </button>
                ))}
              </div>
            )}
          </RailSection>
          )}

          {/* §32: Access — the former Session-settings drawer, one section among peers.
              key: its data ownership resets with the conversation, like the old row did. */}
          <AccessSection
            key={sessionId}
            sessionId={sessionId}
            personaId={personaId}
            projectScoped={projectScoped}
            workspace={workspace}
            branch={branch}
            scratchPrimary={scratchPrimary}
            openKey={openAccessKey}
            onOpenIntegrations={onOpenIntegrations}
          />
        </>
      )}
    </aside>
  );
}

function ProgressSummary({ running, toolNames, todo }: { running: boolean; toolNames: string[]; todo: TodoItem[] }) {
  const { tr } = useI18n();
  if (todo.length) {
    return (
      <div className="rail-todo-list">
        {todo.map((item, index) => (
          <div className={"rail-todo " + item.status} key={index}>
            <span className="rail-todo-mark" />
            <span>{item.content}</span>
          </div>
        ))}
        {running && (
          <div className="rail-muted">
            {toolNames.length
              ? tr(toolNames.length === 1 ? "{count} tool call so far." : "{count} tool calls so far.", { count: toolNames.length })
              : tr("Working…")}
          </div>
        )}
      </div>
    );
  }
  if (running) {
    return (
      <div className="rail-muted">
        {toolNames.length
          ? tr(
              toolNames.length === 1
                ? "Working on this task with {count} tool call so far."
                : "Working on this task with {count} tool calls so far.",
              { count: toolNames.length },
            )
          : tr("Working on this task.")}
      </div>
    );
  }
  return (
    <div className="rail-muted">
      {tr("For longer tasks, progress appears here while Smallink plans, uses tools, waits for approval, and produces artifacts.")}
    </div>
  );
}

function RailSection({
  title,
  open,
  onToggle,
  children,
  action,
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="rail-section">
      <div className="rail-section-head">
        <button className="rail-section-toggle" onClick={onToggle}>
          <Icon name={open ? "chevronDown" : "chevronRight"} size={14} className="rail-chev" />
          <span>{title}</span>
        </button>
        {action}
      </div>
      {open && <div className="rail-section-body">{children}</div>}
    </section>
  );
}

function ArtifactViewer({
  sessionId,
  artifact,
  content,
  onReload,
  onBack,
}: {
  sessionId: string;
  artifact: ArtifactInfo;
  content: ArtifactContent | null;
  onReload: () => Promise<void>;
  onBack: () => void;
}) {
  const { tr } = useI18n();
  const [reloadKey, setReloadKey] = useState(0);
  const isHtml = content?.kind === "html" && !content.error;
  // Best viewed in a real app: spreadsheets, PDFs, and Office docs (pptx/docx can't preview inline)
  const isApp = content?.kind === "sheet" || content?.kind === "pdf" || content?.kind === "office";

  return (
    <div className="artifact-viewer">
      <div className="artifact-head">
        <button className="artifact-icon-btn" onClick={onBack} aria-label={tr("Back to artifacts")} title={tr("Back")}>
          <Icon name="arrowLeft" size={16} />
        </button>
        <div className="artifact-heading">
          <div className="artifact-title"><span>{tr("Artifacts")}</span><span className="artifact-sep">/</span><span>{artifact.name}</span></div>
          <div className="artifact-path">{artifact.path}</div>
        </div>
        <div className="rail-actions">
          {isHtml && (
            <button
              className="artifact-icon-btn"
              onClick={async () => {
                await onReload();
                setReloadKey((k) => k + 1);
              }}
              aria-label={tr("Reload preview")}
              title={tr("Reload")}
            >
              <Icon name="refresh" size={16} />
            </button>
          )}
          {isApp && (
            <button
              className="artifact-icon-btn"
              onClick={() => revealArtifact(sessionId, artifact.path, "open")}
              aria-label={tr("Open in default app")}
              title={tr("Open in default app")}
            >
              <Icon name="panelOpen" size={16} />
            </button>
          )}
          {/* Copy the ABSOLUTE path — the workspace-relative one is useless outside the app
              (tester catch 2026-07-12: it copied just "slack-connector-debug.md"). */}
          <button
            className="artifact-icon-btn"
            onClick={() => navigator.clipboard?.writeText(artifact.abs_path || artifact.path)}
            aria-label={tr("Copy path")}
            title={tr("Copy full path")}
          >
            <Icon name="copy" size={16} />
          </button>
          <button
            className="artifact-icon-btn"
            onClick={() => revealArtifact(sessionId, artifact.path, "reveal")}
            aria-label={tr("Show in folder")}
            title={tr("Show in folder")}
          >
            <Icon name="folder" size={16} />
          </button>
        </div>
      </div>
      <div className="artifact-preview">
        {!content ? (
          <div className="rail-muted">{tr("Loading…")}</div>
        ) : content.error ? (
          <div className="rail-error">{content.error}</div>
        ) : content.kind === "html" ? (
          <iframe
            key={`${artifact.path}-${reloadKey}`}
            sandbox="allow-scripts allow-same-origin"
            className="artifact-frame"
            srcDoc={content.content || ""}
          />
        ) : content.kind === "markdown" ? (
          <div className="artifact-md">
            <Markdown text={content.content || ""} />
          </div>
        ) : content.kind === "image" ? (
          <img className="artifact-image" src={content.data_url} />
        ) : content.kind === "pdf" ? (
          <PdfViewer dataUrl={content.data_url || ""} />
        ) : content.kind === "csv" ? (
          <CsvTable text={content.content || ""} />
        ) : content.kind === "sheet" ? (
          <SheetViewer dataUrl={content.data_url || ""} />
        ) : content.kind === "office" ? (
          <div className="artifact-open-prompt">
            <Icon name="panelOpen" size={28} />
            <p>{tr("This {type} file can’t be previewed here.", { type: /\.pptx?$/i.test(artifact.name) ? "PowerPoint" : "Word" })}</p>
            <button className="btn sm" onClick={() => revealArtifact(sessionId, artifact.path, "open")}>
              {tr("Open in default app")}
            </button>
          </div>
        ) : (
          <pre className="artifact-code">{content.content}</pre>
        )}
      </div>
    </div>
  );
}

const MAX_TABLE_ROWS = 500;

function GridTable({ rows, note }: { rows: unknown[][]; note?: string }) {
  const { tr } = useI18n();
  const [head, ...body] = rows;
  return (
    <div className="artifact-tablewrap">
      <table className="artifact-table">
        {head && (
          <thead>
            <tr>{head.map((c, i) => <th key={i}>{String(c ?? "")}</th>)}</tr>
          </thead>
        )}
        <tbody>
          {body.slice(0, MAX_TABLE_ROWS).map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j}>{String(c ?? "")}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {(note || body.length > MAX_TABLE_ROWS) && (
        <div className="rail-muted artifact-table-note">
          {note}
          {body.length > MAX_TABLE_ROWS
            ? ` ${tr("Showing first {shown} of {total} rows.", { shown: MAX_TABLE_ROWS, total: body.length })}`
            : ""}
        </div>
      )}
    </div>
  );
}

// Minimal RFC-4180-ish CSV parsing: quoted fields, escaped quotes, CRLF. TSV via tab sniffing.
function parseCsv(text: string): string[][] {
  const delim = text.includes("\t") && !text.split("\n")[0]?.includes(",") ? "\t" : ",";
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else quoted = false;
      } else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === delim) {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      cell = "";
      rows.push(row);
      row = [];
    } else cell += ch;
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((r) => r.some((c) => c !== ""));
}

function CsvTable({ text }: { text: string }) {
  const { tr } = useI18n();
  const rows = parseCsv(text);
  if (!rows.length) return <div className="rail-muted artifact-table-note">{tr("Empty file.")}</div>;
  return <GridTable rows={rows} />;
}

// xlsx preview via a small read-only parser (loaded on demand): sheet tabs + a capped
// grid. Real spreadsheet work belongs in Numbers/Excel via "Open in default app".
// WKWebView has no inline PDF plugin (<embed> shows a gray pane in the Tauri shell), so we
// rasterize pages with pdf.js onto stacked canvases — same lazy-chunk pattern as SheetViewer.
function PdfViewer({ dataUrl }: { dataUrl: string }) {
  const { tr } = useI18n();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const holder = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError("");
    setLoading(true);
    const base64 = dataUrl.split(",")[1] || "";
    import("pdfjs-dist")
      .then(async (pdfjs) => {
        pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
        const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
        const doc = await pdfjs.getDocument({ data: bytes }).promise;
        const el = holder.current;
        if (cancelled || !el) return;
        el.innerHTML = "";
        const width = el.clientWidth || 640;
        const dpr = window.devicePixelRatio || 1;
        for (let i = 1; i <= doc.numPages; i++) {
          const page = await doc.getPage(i);
          const base = page.getViewport({ scale: 1 });
          const viewport = page.getViewport({ scale: (width / base.width) * dpr });
          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.className = "artifact-pdf-page";
          await page.render({ canvasContext: canvas.getContext("2d")!, viewport }).promise;
          if (cancelled) return;
          el.appendChild(canvas);
        }
        setLoading(false);
      })
      .catch((e) => !cancelled && setError(String(e?.message || e)));
    return () => {
      cancelled = true;
    };
  }, [dataUrl]);

  if (error) return <div className="rail-error artifact-table-note">{tr("Could not render PDF: {error}", { error })}</div>;
  return (
    <div className="artifact-pdfjs">
      {loading && <div className="rail-muted artifact-table-note">{tr("Rendering PDF…")}</div>}
      <div ref={holder} />
    </div>
  );
}

function SheetViewer({ dataUrl }: { dataUrl: string }) {
  const { tr } = useI18n();
  const [sheets, setSheets] = useState<{ name: string; rows: unknown[][] }[] | null>(null);
  const [error, setError] = useState("");
  const [active, setActive] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setSheets(null);
    setError("");
    setActive(0);
    const base64 = dataUrl.split(",")[1] || "";
    import("read-excel-file")
      .then(async ({ default: readXlsxFile, readSheetNames }) => {
        if (cancelled) return;
        const bytes = Uint8Array.from(atob(base64), (character) => character.charCodeAt(0));
        const blob = new Blob([bytes], {
          type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        });
        const names = await readSheetNames(blob);
        const parsed: { name: string; rows: unknown[][] }[] = [];
        for (const name of names) {
          const rows = await readXlsxFile(blob, { sheet: name });
          parsed.push({ name, rows });
        }
        if (cancelled) return;
        setSheets(parsed);
      })
      .catch((e) => !cancelled && setError(String(e?.message || e)));
    return () => {
      cancelled = true;
    };
  }, [dataUrl]);

  if (error) return <div className="rail-error artifact-table-note">{tr("Could not parse spreadsheet: {error}", { error })}</div>;
  if (!sheets) return <div className="rail-muted artifact-table-note">{tr("Parsing spreadsheet…")}</div>;
  const sheet = sheets[active];
  return (
    <div className="sheet-viewer">
      {sheets.length > 1 && (
        <div className="sheet-tabs">
          {sheets.map((s, i) => (
            <button key={s.name} className={"sheet-tab" + (i === active ? " active" : "")} onClick={() => setActive(i)}>
              {s.name}
            </button>
          ))}
        </div>
      )}
      {sheet.rows.length ? <GridTable rows={sheet.rows} /> : <div className="rail-muted artifact-table-note">{tr("Empty sheet.")}</div>}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(epochSeconds: number, locale: string): string {
  if (!epochSeconds) return "";
  return new Date(epochSeconds * 1000).toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
}
