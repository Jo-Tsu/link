import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getConnectors, type Connector } from "../api";
import { LanguageProvider } from "../i18n";
import { IntegrationsView } from "./IntegrationsView";

vi.mock("../api", () => ({
  getConnectors: vi.fn(),
}));

vi.mock("./connectors/ConnectorsSection", () => ({
  ConnectorsSection: () => <div>Connector catalog</div>,
}));

vi.mock("./SkillHub", () => ({
  SkillHub: ({ workspace }: { workspace?: string }) => (
    <div data-testid="skill-hub-workspace">{workspace}</div>
  ),
}));

describe("IntegrationsView", () => {
  beforeEach(() => {
    vi.mocked(getConnectors).mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("places Skill Hub inside the connector module and preserves workspace scope", async () => {
    render(
      <LanguageProvider>
        <IntegrationsView workspace="/tmp/smallink-project" />
      </LanguageProvider>,
    );

    expect(screen.getByText("Connector catalog")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "MCP servers" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Skill Hub" }));
    expect(screen.getByTestId("skill-hub-workspace").textContent).toBe("/tmp/smallink-project");
  });

  it("counts only connectors exposed by the current product rollout", async () => {
    vi.mocked(getConnectors).mockResolvedValue([
      { name: "minem" },
      { name: "browser" },
      { name: "slack" },
    ] as Connector[]);

    render(
      <LanguageProvider>
        <IntegrationsView workspace="/tmp/smallink-project" />
      </LanguageProvider>,
    );

    expect(await screen.findByRole("button", { name: "Connectors 1" })).toBeTruthy();
  });
});
