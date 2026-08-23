import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CompactSidebar } from "./CompactSidebar";

describe("CompactSidebar", () => {
  afterEach(cleanup);

  it("keeps primary navigation available while collapsed", () => {
    const handlers = {
      onExpand: vi.fn(),
      onNewSession: vi.fn(),
      onSearch: vi.fn(),
      onGoHome: vi.fn(),
      onOpenApps: vi.fn(),
      onOpenMemory: vi.fn(),
      onOpenAgents: vi.fn(),
      onOpenRuns: vi.fn(),
      onOpenScheduled: vi.fn(),
      onOpenIntegrations: vi.fn(),
      onOpenInbox: vi.fn(),
      onOpenAudit: vi.fn(),
      onOpenSettings: vi.fn(),
    };
    render(<CompactSidebar surface="apps" {...handlers} />);

    expect(screen.getByRole("button", { name: "Applications" }).getAttribute("aria-current")).toBe("page");
    fireEvent.click(screen.getByRole("button", { name: "New session" }));
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.click(screen.getByRole("button", { name: "Show sidebar (⌘B)" }));

    expect(handlers.onNewSession).toHaveBeenCalledOnce();
    expect(handlers.onSearch).toHaveBeenCalledOnce();
    expect(handlers.onExpand).toHaveBeenCalledOnce();
  });
});
