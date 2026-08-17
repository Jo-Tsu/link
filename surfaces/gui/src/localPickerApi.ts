declare const __LINK_DEV_TOKEN__: string;

const httpBase = (): string =>
  typeof (globalThis as any).__LINK_API_BASE__ === "string"
    ? (globalThis as any).__LINK_API_BASE__
    : "http://127.0.0.1:42871";

const token = (): string =>
  String((globalThis as any).__LINK_API_TOKEN__ || __LINK_DEV_TOKEN__ || "");

async function postPicker(path: string): Promise<string | null> {
  const headers = new Headers();
  const launchToken = token();
  if (launchToken) headers.set("X-Link-Token", launchToken);
  const response = await fetch(`${httpBase()}${path}`, { method: "POST", headers });
  if (!response.ok) return null;
  const payload = await response.json();
  return typeof payload.path === "string" && payload.path ? payload.path : null;
}

export const pickFolderViaServer = () => postPicker("/v1/workspaces/pick");
export const pickSkillArchiveViaServer = () => postPicker("/v1/skills/pick-archive");
