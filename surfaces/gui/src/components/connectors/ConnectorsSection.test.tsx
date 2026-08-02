import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getCloudStatus,
  getConnectors,
  getSlackStatus,
  type Connector,
} from "../../api";
import { LanguageProvider } from "../../i18n";
import { ConnectorsSection } from "./ConnectorsSection";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return {
    ...actual,
    getConnectors: vi.fn(),
    getCloudStatus: vi.fn(),
    getSlackStatus: vi.fn(),
  };
});

function connector(name: string, title: string): Connector {
  return {
    name,
    title,
    icon: title.slice(0, 1),
    blurb: `${title} connector`,
    auth: name === "minem" ? "local_app" : "none",
    two_way: false,
    channels: false,
    available: true,
    fields: [],
    instructions: [],
    connected: false,
    account: null,
    enabled: false,
    brand_color: "#00529b",
    logo: name,
    allowed_users: [],
    tools: [],
    managed: false,
    managed_profile: false,
  };
}

describe("ConnectorsSection visibility", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows MineM and hides every other connector card", async () => {
    vi.mocked(getConnectors).mockResolvedValue([
      connector("minem", "MineM"),
      connector("codex", "Codex"),
      connector("traex", "TRAE CLI"),
      connector("browser", "Browser"),
      connector("slack", "Slack"),
    ]);
    vi.mocked(getCloudStatus).mockResolvedValue({
      available: false,
      signed_in: false,
      account: "",
      user_id: "",
    });
    vi.mocked(getSlackStatus).mockResolvedValue({
      mode: "",
      relay: {
        state: "offline",
        reconnects: 0,
        last_event_at: null,
        last_error: "",
      },
      signed_in: false,
      teams: {},
    });

    render(
      <LanguageProvider>
        <ConnectorsSection />
      </LanguageProvider>,
    );

    expect(await screen.findByText("MineM")).toBeTruthy();
    expect(screen.getByText("Codex")).toBeTruthy();
    expect(screen.getByText("TRAE CLI")).toBeTruthy();
    expect(screen.queryByText("Browser")).toBeNull();
    expect(screen.queryByText("Slack")).toBeNull();
  });

  it("shows a retry state instead of an empty catalog when loading fails", async () => {
    vi.mocked(getConnectors)
      .mockRejectedValueOnce(new Error("service offline"))
      .mockResolvedValueOnce([connector("minem", "MineM")]);
    vi.mocked(getCloudStatus).mockRejectedValue(new Error("offline"));
    vi.mocked(getSlackStatus).mockRejectedValue(new Error("offline"));

    render(
      <LanguageProvider>
        <ConnectorsSection />
      </LanguageProvider>,
    );

    expect(await screen.findByText("Connectors are unavailable")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("MineM")).toBeTruthy();
  });
});
