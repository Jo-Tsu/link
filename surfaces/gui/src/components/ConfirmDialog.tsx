import { useEffect, useRef } from "react";
import { useI18n } from "../i18n";

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  body?: string;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { tr } = useI18n();
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
      if (event.key === "Tab") {
        const el = dialogRef.current;
        if (!el) return;
        const focusable = el.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  return (
    <div className="fixed inset-0 z-[90] bg-ink/35 grid place-items-center px-4">
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        className="w-full max-w-sm rounded-xl border border-line bg-panel shadow-2xl p-5"
      >
        <h2 id="confirm-dialog-title" className="text-[15px] font-semibold text-heading">
          {title}
        </h2>
        {body && <p className="text-[12.5px] text-muted leading-relaxed mt-1.5">{body}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="h-9 px-4 rounded-lg border border-line text-[12.5px] text-muted disabled:opacity-50"
          >
            {tr("Cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            autoFocus
            className={`h-9 px-4 rounded-lg text-[12.5px] font-medium disabled:opacity-50 ${
              danger ? "bg-danger text-white" : "bg-ink text-panel"
            }`}
          >
            {busy ? tr("Working…") : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
