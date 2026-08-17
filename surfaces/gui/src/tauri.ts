// Thin bridge to the Tauri desktop shell. In the browser these are inert (isTauri() === false),
// so the SPA stays a single codebase. We use the injected `window.__TAURI__` global (the shell
// sets `withGlobalTauri`) instead of the @tauri-apps npm packages, so the browser build needs
// no Tauri dependencies.

export const isTauri = (): boolean =>
  typeof (globalThis as any).__TAURI__ !== "undefined";

// "macos" | "windows" | "linux" — injected by the shell (std::env::consts::OS) before the
// SPA loads; userAgent fallback covers browser dev. The macOS overlay-titlebar layout (and
// its traffic-light compensations) must NEVER apply on Windows, which keeps its native
// title bar (alignment bug, caught on Windows 2026-07-21).
export const platformOS = (): string => {
  const injected = (globalThis as any).__LINK_PLATFORM__;
  if (typeof injected === "string" && injected) return injected;
  return /mac/i.test(navigator.userAgent) ? "macos" : /win/i.test(navigator.userAgent) ? "windows" : "linux";
};

export type DictationStatus = {
  recording: boolean;
  model_installed: boolean;
  model_verified: boolean;
  test_passed: boolean;
  download_in_progress: boolean;
  model_name: string;
  model_bytes: number;
  supported: boolean;
  device_summary: string;
  compatibility_reason: string | null;
};

export type DictationDownloadProgress = {
  downloaded_bytes: number;
  total_bytes: number;
};

const invoke = async <T>(cmd: string, args?: Record<string, unknown>): Promise<T | null> => {
  const tauri = (globalThis as any).__TAURI__;
  if (!tauri?.core?.invoke) return null;
  try {
    return (await tauri.core.invoke(cmd, args)) as T;
  } catch {
    return null;
  }
};

const invokeStrict = async <T>(cmd: string, args?: Record<string, unknown>): Promise<T> => {
  const tauri = (globalThis as any).__TAURI__;
  if (!tauri?.core?.invoke) throw new Error("This feature is available in the desktop app.");
  return (await tauri.core.invoke(cmd, args)) as T;
};

/** Open the native macOS folder picker (Tauri only). Returns the chosen path, or null. */
export async function pickFolder(): Promise<string | null> {
  const path = await invoke<string>("pick_folder");
  return typeof path === "string" && path ? path : null;
}

/** The folder picker that works EVERYWHERE: Tauri's native dialog in the desktop shell, else the
 * sidecar-opened OS dialog (the sidecar is local, so the browser GUI still gets a real picker —
 * owner report 2026-07-04: "Browse" was desktop-only and the browser had paste-a-path only). */
export async function chooseFolder(): Promise<string | null> {
  if (isTauri()) return pickFolder();
  const { pickFolderViaServer } = await import("./localPickerApi");
  return pickFolderViaServer();
}

/** Choose a complete Skill .zip package in either the desktop shell or browser development UI. */
export async function chooseSkillArchive(): Promise<string | null> {
  if (isTauri()) {
    const path = await invoke<string>("pick_skill_archive");
    return typeof path === "string" && path ? path : null;
  }
  const { pickSkillArchiveViaServer } = await import("./localPickerApi");
  return pickSkillArchiveViaServer();
}

/** Open-at-login (macOS LaunchAgent). */
export const getAutostart = () => invoke<boolean>("get_autostart");
export const setAutostart = (enabled: boolean) => invoke<boolean>("set_autostart", { enabled });

/** Keep this system awake so scheduled tasks fire while idle (caffeinate on macOS,
 * SetThreadExecutionState on Windows). Persists across restarts. */
export const getKeepAwake = () => invoke<boolean>("get_keep_awake");
export const setKeepAwake = (enabled: boolean) => invoke<boolean>("set_keep_awake", { enabled });

/** Begin native window dragging from a custom title/header region. */
export const startWindowDrag = () => invoke<boolean>("start_window_drag");

/** Keep the native macOS/Windows tray menu in sync with the in-app language. */
export const setAppLanguage = (language: "zh-CN" | "en") =>
  invoke<boolean>("set_app_language", { language });

// Local dictation is native-only. The browser build deliberately keeps this unavailable rather
// than silently sending microphone audio to a server.
export const getDictationStatus = () => invoke<DictationStatus>("get_dictation_status");
/** Instantaneous mic loudness 0..1 while recording (0 otherwise) — drives the composer's
 * live waveform. Cheap; poll at ~10Hz. */
export const getDictationLevel = () => invoke<number>("dictation_level");
export const startDictation = () => invokeStrict<DictationStatus>("start_dictation");
export const stopDictation = () => invokeStrict<string>("stop_dictation");
export const cancelDictation = () => invokeStrict<void>("cancel_dictation");
export const downloadDictationModel = () => invokeStrict<DictationStatus>("download_dictation_model");
export const cancelDictationModelDownload = () => invokeStrict<void>("cancel_dictation_model_download");
export const verifyDictationModel = () => invokeStrict<DictationStatus>("verify_dictation_model");
export const markDictationTestPassed = () => invokeStrict<DictationStatus>("mark_dictation_test_passed");
export const deleteDictationModel = () => invokeStrict<DictationStatus>("delete_dictation_model");

export async function listenDictationDownloadProgress(
  handler: (progress: DictationDownloadProgress) => void,
): Promise<() => void> {
  const listen = (globalThis as any).__TAURI__?.event?.listen;
  if (!listen) return () => {};
  return (await listen("dictation-download-progress", (event: { payload: DictationDownloadProgress }) => {
    handler(event.payload);
  })) as () => void;
}

/** Open a safe external URL in the system browser. Desktop builds use Tauri's opener plugin;
 * browser development falls back to a new tab. Other protocols never reach the OS. */
export function openExternal(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (!["http:", "https:", "mailto:"].includes(parsed.protocol)) return false;
  const opener = (globalThis as any).__TAURI__?.opener;
  if (opener?.openUrl) {
    opener.openUrl(parsed.href).catch(() => {});
    return true;
  }
  window.open(parsed.href, "_blank", "noopener,noreferrer");
  return true;
}
