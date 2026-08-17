import { Icon, type IconName } from "./Icon";

type Tone = "info" | "success" | "warning" | "danger";

const TONE_CLASS: Record<Tone, string> = {
  info: "border-accent/25 bg-accentSoft/35 text-ink",
  success: "border-okLine bg-okSoft text-ink",
  warning: "border-warnInk/25 bg-warnSoft text-ink",
  danger: "border-danger/30 bg-dangerSoft text-danger",
};

const TONE_ICON: Record<Tone, IconName> = {
  info: "diamond",
  success: "shield",
  warning: "clock",
  danger: "x",
};

export function InlineFeedback({
  tone,
  title,
  body,
  action,
  onAction,
  role,
}: {
  tone: Tone;
  title: string;
  body?: string;
  action?: string;
  onAction?: () => void;
  role?: "alert" | "status";
}) {
  return (
    <div
      className={`rounded-xl border px-3.5 py-3 flex items-start gap-3 ${TONE_CLASS[tone]}`}
      role={role ?? (tone === "danger" ? "alert" : "status")}
    >
      <span className="mt-0.5 shrink-0">
        <Icon name={TONE_ICON[tone]} size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[12.5px] font-medium">{title}</div>
        {body && <div className="text-[11.5px] leading-relaxed opacity-75 mt-0.5">{body}</div>}
      </div>
      {action && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="shrink-0 text-[12px] font-medium text-accent hover:underline underline-offset-2"
        >
          {action}
        </button>
      )}
    </div>
  );
}

export function PageState({
  icon = "diamond",
  title,
  body,
  action,
  onAction,
}: {
  icon?: IconName;
  title: string;
  body: string;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <div className="min-h-[220px] rounded-xl border border-line bg-panel/80 px-6 py-10 text-center grid place-items-center">
      <div className="max-w-md">
        <span className="w-10 h-10 rounded-full bg-accentSoft text-accent grid place-items-center mx-auto mb-3">
          <Icon name={icon} size={18} />
        </span>
        <div className="text-[14px] font-semibold text-heading">{title}</div>
        <div className="text-[12px] text-muted leading-relaxed mt-1">{body}</div>
        {action && onAction && (
          <button
            type="button"
            onClick={onAction}
            className="mt-4 h-9 px-4 rounded-lg border border-accent/35 bg-accentSoft/35 text-[12px] font-medium text-accent hover:bg-accentSoft/60"
          >
            {action}
          </button>
        )}
      </div>
    </div>
  );
}
