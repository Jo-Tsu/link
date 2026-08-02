import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getMemory, getSensoryStats } from "../api";
import { LanguageProvider } from "../i18n";
import { MemoryView } from "./MemoryView";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, getMemory: vi.fn(), getSensoryStats: vi.fn() };
});

beforeEach(() => {
  localStorage.setItem("link:language:v1", "en");
  // MemoryView loads active memories with getMemory() and the pending queue with
  // getMemory("pending"). Default: one active preference, empty pending.
  vi.mocked(getMemory).mockImplementation(async (status?: string) => {
    if (status === "pending") return [];
    return [
      {
        id: 7,
        scope: "global",
        content: "Prefers concise product interfaces.",
        key: "user_preference",
        workspace: null,
        session_id: null,
        created_at: "2026-07-29T09:00:00Z",
      },
    ];
  });
  vi.mocked(getSensoryStats).mockResolvedValue({
    total: 12,
    pending: 12,
    sources: { traex: 9, codex: 3 },
  });
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
});

describe("MemoryView", () => {
  it("groups real memories by type and opens the type list", async () => {
    render(<LanguageProvider><MemoryView /></LanguageProvider>);

    await screen.findByText("Personal memory");
    const preferenceCard = screen.getByRole("button", { name: "Open User preferences memories" });
    expect(preferenceCard.textContent).toContain("1");
    expect(screen.getByText("TRAE records").parentElement?.textContent).toContain("9");

    fireEvent.click(preferenceCard);
    await waitFor(() => expect(screen.getByText("Prefers concise product interfaces.")).toBeTruthy());
    fireEvent.click(screen.getByText("Prefers concise product interfaces."));
    expect(screen.getByText("Memory details")).toBeTruthy();
  });

  it("surfaces the pending queue and opens the review view", async () => {
    vi.mocked(getMemory).mockImplementation(async (status?: string) => {
      if (status === "pending") {
        return [
          {
            id: 42,
            scope: "workspace",
            content: "Deploys with pnpm, never npm.",
            key: "user_preference",
            workspace: "/proj",
            session_id: null,
            created_at: "2026-07-31T09:00:00Z",
            status: "pending",
            source_record_id: "sensory-abc",
          },
        ];
      }
      return [];
    });

    render(<LanguageProvider><MemoryView /></LanguageProvider>);

    const banner = await screen.findByTestId("memory-pending-banner");
    expect(banner.textContent).toContain("1");
    fireEvent.click(banner);

    await screen.findByText("Awaiting confirmation");
    fireEvent.click(screen.getByText("Deploys with pnpm, never npm."));
    expect(screen.getByText("Memory details")).toBeTruthy();
  });

  it("hides the pending banner when the queue is empty", async () => {
    render(<LanguageProvider><MemoryView /></LanguageProvider>);
    await screen.findByText("Personal memory");
    expect(screen.queryByTestId("memory-pending-banner")).toBeNull();
  });
});
