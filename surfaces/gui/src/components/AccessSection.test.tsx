import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getConnectors, getSessionConnections } from "../api";
import { LanguageProvider } from "../i18n";
import { AccessSection } from "./AccessSection";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    getConnectors: vi.fn(),
    getSessionConnections: vi.fn(),
    getSubscriptions: vi.fn().mockResolvedValue([]),
    getRecentChannels: vi.fn().mockResolvedValue([]),
  };
});

vi.mock("../useRoots", () => ({
  useRoots: () => ({
    roots: [],
    busy: false,
    error: "",
    addRoot: vi.fn(),
    toggleAccess: vi.fn(),
    removeRoot: vi.fn(),
  }),
}));

describe("AccessSection connector rollout", () => {
  beforeEach(() => {
    vi.mocked(getSessionConnections).mockResolvedValue({
      connected: [
        { connector: "minem", enabled: true, detail: "local" },
        { connector: "slack", enabled: true, detail: "workspace" },
      ],
      recommended: [
        { connector: "github", reason: "repositories", tier: "core", connected: false },
      ],
      attention: 1,
    });
    vi.mocked(getConnectors).mockResolvedValue([
      { name: "minem", title: "MineM", available: true },
      { name: "slack", title: "Slack", available: true },
      { name: "github", title: "GitHub", available: true },
    ] as never);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows only connectors enabled for the current rollout", async () => {
    render(
      <LanguageProvider>
        <AccessSection sessionId="session-1" />
      </LanguageProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("access-summary").textContent).toContain("MineM"));
    expect(screen.getByTestId("access-summary").textContent).not.toContain("Slack");

    fireEvent.click(screen.getByTestId("access-toggle"));
    await waitFor(() => expect(screen.getAllByText("MineM").length).toBeGreaterThan(1));
    expect(screen.queryByText("Slack")).toBeNull();
    expect(screen.queryByText("GitHub")).toBeNull();
  });
});
