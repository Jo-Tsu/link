import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getConnectors,
  type Connector,
} from "../../api";
import { LanguageProvider } from "../../i18n";
import { ConnectorsSection } from "./ConnectorsSection";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return {
    ...actual,
    getConnectors: vi.fn(),
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

    render(
      <LanguageProvider>
        <ConnectorsSection />
      </LanguageProvider>,
    );

    expect(await screen.findByText("MineM")).toBeTruthy();
    expect(screen.queryByText("Codex")).toBeNull();
    expect(screen.queryByText("TRAE CLI")).toBeNull();
    expect(screen.queryByText("Browser")).toBeNull();
    expect(screen.queryByText("Slack")).toBeNull();
  });

  it("shows a retry state instead of an empty catalog when loading fails", async () => {
    vi.mocked(getConnectors)
      .mockRejectedValueOnce(new Error("service offline"))
      .mockResolvedValueOnce([connector("minem", "MineM")]);

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
