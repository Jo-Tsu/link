import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { connectConnector, syncCodex, syncTraex, type Connector } from "../../api";
import { LanguageProvider } from "../../i18n";
import { chooseFolder } from "../../tauri";
import { AddConnectionModal } from "./AddConnectionModal";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return {
    ...actual,
    connectConnector: vi.fn(),
    connectManaged: vi.fn(),
    connectMcpBacked: vi.fn(),
    getConnectors: vi.fn(),
    syncCodex: vi.fn(),
    syncTraex: vi.fn(),
  };
});

vi.mock("../../tauri", async () => {
  const actual = await vi.importActual<typeof import("../../tauri")>("../../tauri");
  return { ...actual, chooseFolder: vi.fn() };
});

const minem: Connector = {
  name: "minem",
  title: "MineM",
  icon: "M",
  blurb: "Search and read your local MineM reports, pages, and resources.",
  auth: "local_app",
  two_way: false,
  channels: false,
  available: true,
  fields: [],
  instructions: [],
  connected: false,
  account: null,
  enabled: false,
  brand_color: "#00529b",
  logo: "minem",
  allowed_users: [],
  tools: [],
  managed: false,
  managed_profile: false,
};

const codex: Connector = {
  ...minem,
  name: "codex",
  title: "Codex",
  icon: "⌘",
  blurb: "Import local Codex conversations.",
  account: null,
  brand_color: "#000000",
  logo: "codex",
};

const traex: Connector = {
  ...codex,
  name: "traex",
  title: "TRAE CLI",
  icon: "T",
  blurb: "Import local TRAE CLI conversations.",
  brand_color: "#0052d9",
  logo: "traex",
};

describe("MineM local connector", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("launches MineM through the normal connector endpoint", async () => {
    vi.mocked(connectConnector).mockResolvedValue({ ok: true, account: "MineM 0.5.0" });
    const onChanged = vi.fn();
    const onClose = vi.fn();

    render(
      <LanguageProvider>
        <AddConnectionModal
          c={minem}
          cloud={null}
          onChanged={onChanged}
          onClose={onClose}
        />
      </LanguageProvider>,
    );

    fireEvent.click(screen.getByTestId("modal-local-app-connect"));
    await waitFor(() => expect(connectConnector).toHaveBeenCalledWith("minem", {}));
    expect(onChanged).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("keeps the dialog open and shows a CLI launch failure", async () => {
    vi.mocked(connectConnector).mockResolvedValue({ ok: false, error: "MineM CLI not found" });

    render(
      <LanguageProvider>
        <AddConnectionModal
          c={minem}
          cloud={null}
          onChanged={vi.fn()}
          onClose={vi.fn()}
        />
      </LanguageProvider>,
    );

    fireEvent.click(screen.getByTestId("modal-local-app-connect"));
    expect(await screen.findByText("MineM CLI not found")).toBeTruthy();
  });
});

describe("Codex one-click connector", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("authorizes a folder, connects, and imports in one action", async () => {
    vi.mocked(chooseFolder).mockResolvedValue("/Users/me/.codex");
    vi.mocked(connectConnector).mockResolvedValue({ ok: true, account: "Codex local" });
    vi.mocked(syncCodex).mockResolvedValue({
      sessions_read: 4,
      turns_seen: 12,
      records_ingested: 12,
    });
    const onChanged = vi.fn();
    const onClose = vi.fn();

    render(
      <LanguageProvider>
        <AddConnectionModal
          c={codex}
          cloud={null}
          onChanged={onChanged}
          onClose={onClose}
        />
      </LanguageProvider>,
    );

    fireEvent.click(screen.getByTestId("modal-codex-connect"));
    await waitFor(() => expect(chooseFolder).toHaveBeenCalledOnce());
    expect(connectConnector).toHaveBeenCalledWith("codex", {
      sessions_path: "/Users/me/.codex",
    });
    await waitFor(() => expect(syncCodex).toHaveBeenCalledOnce());
    expect(onChanged).toHaveBeenCalledOnce();
    expect(onClose).not.toHaveBeenCalled();
    expect(await screen.findByText("Import complete")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("stops before connecting when folder selection is cancelled", async () => {
    vi.mocked(chooseFolder).mockResolvedValue(null);

    render(
      <LanguageProvider>
        <AddConnectionModal
          c={codex}
          cloud={null}
          onChanged={vi.fn()}
          onClose={vi.fn()}
        />
      </LanguageProvider>,
    );

    fireEvent.click(screen.getByTestId("modal-codex-connect"));
    await waitFor(() => expect(chooseFolder).toHaveBeenCalledOnce());
    expect(connectConnector).not.toHaveBeenCalled();
    expect(syncCodex).not.toHaveBeenCalled();
  });
});

describe("TRAE CLI one-click connector", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("authorizes the TRAE folder and imports user sessions", async () => {
    vi.mocked(chooseFolder).mockResolvedValue("/Users/me/.trae");
    vi.mocked(connectConnector).mockResolvedValue({ ok: true, account: "TRAE CLI local" });
    vi.mocked(syncTraex).mockResolvedValue({
      sessions_read: 3,
      turns_seen: 10,
      records_ingested: 10,
    });
    const onChanged = vi.fn();
    const onClose = vi.fn();

    render(
      <LanguageProvider>
        <AddConnectionModal
          c={traex}
          cloud={null}
          onChanged={onChanged}
          onClose={onClose}
        />
      </LanguageProvider>,
    );

    fireEvent.click(screen.getByTestId("modal-traex-connect"));
    await waitFor(() =>
      expect(connectConnector).toHaveBeenCalledWith("traex", {
        sessions_path: "/Users/me/.trae",
      }),
    );
    await waitFor(() => expect(syncTraex).toHaveBeenCalledOnce());
    expect(syncCodex).not.toHaveBeenCalled();
    expect(onChanged).toHaveBeenCalledOnce();
    expect(onClose).not.toHaveBeenCalled();
    expect(await screen.findByText("Import complete")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("keeps the successful connection and offers an import retry", async () => {
    vi.mocked(chooseFolder).mockResolvedValue("/Users/me/.trae");
    vi.mocked(connectConnector).mockResolvedValue({ ok: true, account: "TRAE CLI local" });
    vi.mocked(syncTraex)
      .mockRejectedValueOnce(new Error("scan failed"))
      .mockResolvedValueOnce({
        sessions_read: 2,
        turns_seen: 5,
        records_ingested: 5,
      });
    const onChanged = vi.fn();

    render(
      <LanguageProvider>
        <AddConnectionModal
          c={traex}
          cloud={null}
          onChanged={onChanged}
          onClose={vi.fn()}
        />
      </LanguageProvider>,
    );

    fireEvent.click(screen.getByTestId("modal-traex-connect"));
    expect(await screen.findByText("TRAE CLI is connected, but import did not finish.")).toBeTruthy();
    expect(onChanged).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: "Retry import" }));
    expect(await screen.findByText("Import complete")).toBeTruthy();
    expect(syncTraex).toHaveBeenCalledTimes(2);
  });
});
