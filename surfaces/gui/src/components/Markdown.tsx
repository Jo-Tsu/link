import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Icon } from "./Icon";
import { useI18n } from "../i18n";
import { openExternal } from "../tauri";

// §34 (UX-016): the agent ends a deliverable turn with plain markdown —
// [Title](artifact:relative/path) — and the renderer turns it into a chip that opens the
// artifact viewer in place. Plumbing is a window event (the viewer lives in RightRail;
// this component renders deep inside the transcript): RightRail resolves the path against
// the session's artifact list, App un-hides the rail.
export const OPEN_ARTIFACT_EVENT = "link-open-artifact";

const ARTIFACT_FILE_RE = /\.(?:md|markdown|html?|txt|json|csv|tsv|py|jsx?|tsx?|css|png|jpe?g|webp|gif|pdf|xlsx?|pptx?|pptm|docx?|docm)$/i;

/** ReactMarkdown URL-encodes non-ASCII link destinations. Decode defensively so the artifact
 * identifier remains the real workspace path. Two passes also recover links that arrived already
 * encoded before Markdown parsed them; malformed percent escapes remain untouched. */
export function normalizeArtifactPath(raw: string): string {
  let path = String(raw || "").trim();
  if (path.startsWith("file://")) {
    try {
      path = new URL(path).pathname;
    } catch {
      path = path.slice("file://".length);
    }
  }
  for (let pass = 0; pass < 2; pass += 1) {
    try {
      const decoded = decodeURIComponent(path);
      if (decoded === path) break;
      path = decoded;
    } catch {
      break;
    }
  }
  return path.replace(/\\/g, "/").replace(/^\.\/+/, "");
}

/** Models occasionally omit the artifact: scheme and emit a plain relative file link. Treat only
 * known deliverable extensions as artifacts; web/mail/anchor links keep their normal behavior. */
export function artifactPathFromHref(href?: string): string | null {
  if (!href) return null;
  if (href.startsWith("artifact:")) {
    return normalizeArtifactPath(href.slice("artifact:".length));
  }
  const windowsPath = /^[a-zA-Z]:[\\/]/.test(href);
  if (!windowsPath && /^[a-zA-Z][a-zA-Z\d+.-]*:/.test(href) && !href.startsWith("file://")) {
    return null;
  }
  if (href.startsWith("#")) return null;
  const path = normalizeArtifactPath(href).split(/[?#]/, 1)[0];
  return ARTIFACT_FILE_RE.test(path) ? path : null;
}

function ArtifactChip({ path, title }: { path: string; title: string }) {
  const { tr } = useI18n();
  const normalizedPath = normalizeArtifactPath(path);
  const file = normalizedPath.split("/").pop() || normalizedPath;
  return (
    <button
      className="art-chip"
      data-testid="artifact-chip"
      title={normalizedPath}
      onClick={() =>
        window.dispatchEvent(new CustomEvent(OPEN_ARTIFACT_EVENT, { detail: { path: normalizedPath } }))
      }
    >
      <span className="art-chip-ico">
        <Icon name="file" size={14} />
      </span>
      <span className="art-chip-meta">
        <b>{title || file}</b>
        {title && title !== file && <span>{file}</span>}
      </span>
      <span className="art-chip-open">{tr("Open ›")}</span>
    </button>
  );
}

// Assistant messages rendered as GitHub-flavored markdown (headings, lists, tables, code,
// links). Links open externally — never navigate the app shell — except artifact: links,
// which open the session's artifact viewer.
export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        // artifact: is ours — keep it through the sanitizer (everything else gets the default
        // http/https/mailto policy).
        urlTransform={(url) =>
          url.startsWith("artifact:") || url.startsWith("file://")
            ? url
            : defaultUrlTransform(url)
        }
        components={{
          a: ({ node: _n, href, children, ...props }) => {
            const artifactPath = artifactPathFromHref(href);
            if (artifactPath) {
              const title = Array.isArray(children) ? children.join("") : String(children ?? "");
              return <ArtifactChip path={artifactPath} title={title} />;
            }
            return (
              <a
                href={href}
                {...props}
                target="_blank"
                rel="noreferrer"
                onClick={(event) => {
                  event.preventDefault();
                  if (href) openExternal(href);
                }}
              >
                {children}
              </a>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
