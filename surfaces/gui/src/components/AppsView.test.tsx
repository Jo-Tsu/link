import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  changeAppState,
  getAppActivity,
  getAppAssets,
  getApps,
  invokeAppCapability,
  pickAppImportFile,
  type SmallinkApp,
} from "../api";
import { LanguageProvider } from "../i18n";
import { AppsView } from "./AppsView";

vi.mock("../api", () => ({
  changeAppState: vi.fn(),
  getAppActivity: vi.fn(),
  getAppAssets: vi.fn(),
  getApps: vi.fn(),
  invokeAppCapability: vi.fn(),
  pickAppImportFile: vi.fn(),
}));

vi.mock("../tauri", () => ({
  openExternal: vi.fn(),
  setAppLanguage: vi.fn(),
}));

const APP: SmallinkApp = {
  schema_version: "smallink.app/v1",
  app_id: "minem",
  name: "MineM",
  description: "Search, organize, create, and reuse materials through the local MineM app.",
  icon: "minem",
  runtime_kind: "hybrid_local_app",
  connector_id: "minem",
  system_project_id: "system:minem",
  system_project_name: "MineM",
  default_agent: "link",
  capabilities: ["asset.list", "asset.get", "asset.search"],
  memory_types: ["artifact_summary", "document_insight"],
  instance: {
    app_id: "minem",
    enabled: true,
    install_state: "installed",
    runtime_state: "available",
    status: {},
  },
  runtime: { health: "running", cli_available: true, app_version: "1.0.0" },
  project: {
    project_id: "system:minem",
    name: "MineM",
    icon: "folder",
    workspace_path: "/tmp/smallink/apps/minem",
    description: "MineM material library",
    status: "active",
    pinned: true,
    sort_order: -100,
    project_type: "system_app",
    owner_app_id: "minem",
    system_key: "system:minem",
    session_count: 2,
    created_at: "2026-08-20T10:00:00Z",
    updated_at: "2026-08-20T10:00:00Z",
  },
};

describe("AppsView", () => {
  beforeEach(() => {
    vi.mocked(getApps).mockResolvedValue([APP]);
    vi.mocked(getAppAssets).mockResolvedValue({
      ok: true,
      project_id: "system:minem",
      items: [{ id: "asset-1", code: "Q3-PLAN", type: "report", title: "Quarterly plan" }],
    });
    vi.mocked(getAppActivity).mockResolvedValue([]);
    vi.mocked(invokeAppCapability).mockResolvedValue({ ok: true });
    vi.mocked(changeAppState).mockResolvedValue({ ok: true, app: APP });
    vi.mocked(pickAppImportFile).mockResolvedValue(null);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("opens the MineM system workspace and starts a project-scoped conversation", async () => {
    const onNewProjectSession = vi.fn();
    render(
      <LanguageProvider>
        <AppsView onNewProjectSession={onNewProjectSession} />
      </LanguageProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Applications" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /MineM/ }));
    fireEvent.click(screen.getByRole("button", { name: "Open material library" }));

    expect(await screen.findByText("Quarterly plan")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "New MineM conversation" }));
    expect(onNewProjectSession).toHaveBeenCalledWith("system:minem");
  });

  it("searches through the app contract and opens the returned source snapshot", async () => {
    vi.mocked(invokeAppCapability).mockResolvedValue({
      ok: true,
      resource: { id: "asset-1", code: "Q3-PLAN", type: "report", title: "Quarterly plan", source: "MineM CLI" },
    });
    render(
      <LanguageProvider>
        <AppsView onNewProjectSession={vi.fn()} />
      </LanguageProvider>,
    );

    await screen.findByRole("heading", { name: "Applications" });
    fireEvent.click(screen.getByRole("button", { name: /MineM/ }));
    fireEvent.click(screen.getByRole("button", { name: "Open material library" }));
    await screen.findByText("Quarterly plan");

    fireEvent.change(screen.getByPlaceholderText("Search titles, codes, and material content"), {
      target: { value: "strategy" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(getAppAssets).toHaveBeenLastCalledWith("minem", {
      query: "strategy",
      assetType: "all",
      limit: 100,
    }));

    fireEvent.click(screen.getByRole("button", { name: /Quarterly plan/ }));
    await waitFor(() => expect(invokeAppCapability).toHaveBeenCalledWith(
      "minem",
      "asset.get",
      { reference: "Q3-PLAN" },
    ));
    expect(await screen.findByText("Source snapshot")).toBeTruthy();
    expect(screen.getByText(/MineM CLI/)).toBeTruthy();
  });
});
