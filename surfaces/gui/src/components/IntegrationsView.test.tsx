import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LanguageProvider } from "../i18n";
import { IntegrationsView } from "./IntegrationsView";

vi.mock("./connectors/ConnectorsSection", () => ({
  ConnectorsSection: ({ onCountChange }: { onCountChange?: (count: number) => void }) => {
    if (onCountChange) setTimeout(() => onCountChange(1), 0);
    return <div>Connector catalog</div>;
  },
}));

vi.mock("./SkillHub", () => ({
  SkillHub: ({ workspace }: { workspace?: string }) => (
    <div data-testid="skill-hub-workspace">{workspace}</div>
  ),
}));

describe("IntegrationsView", () => {
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
    render(
      <LanguageProvider>
        <IntegrationsView workspace="/tmp/smallink-project" />
      </LanguageProvider>,
    );

    expect(await screen.findByRole("button", { name: "Connectors 1" })).toBeTruthy();
  });
});
