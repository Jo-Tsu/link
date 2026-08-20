import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  decideMemoryCandidate,
  decideMemoryCandidates,
  getMemory,
  getMemoryCandidate,
  getMemoryCandidates,
  getSensoryRecord,
  getSensoryRecords,
  getSensoryStats,
  runMemoryPipeline,
} from "../api";
import { LanguageProvider } from "../i18n";
import { MemoryView } from "./MemoryView";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    decideMemoryCandidate: vi.fn(),
    decideMemoryCandidates: vi.fn(),
    getMemory: vi.fn(),
    getMemoryCandidate: vi.fn(),
    getMemoryCandidates: vi.fn(),
    getSensoryRecord: vi.fn(),
    getSensoryRecords: vi.fn(),
    getSensoryStats: vi.fn(),
    runMemoryPipeline: vi.fn(),
  };
});

beforeEach(() => {
  localStorage.setItem("link:language:v1", "en");
  vi.mocked(getMemory).mockResolvedValue([
    {
      id: 7,
      scope: "global",
      content: "Prefers concise product interfaces.",
      key: "user_preference",
      workspace: null,
      session_id: null,
      created_at: "2026-07-29T09:00:00Z",
    },
  ]);
  vi.mocked(getMemoryCandidates).mockResolvedValue([]);
  vi.mocked(decideMemoryCandidate).mockResolvedValue({ ok: true, memory_id: 8 });
  vi.mocked(decideMemoryCandidates).mockResolvedValue({
    ok: true,
    action: "accept",
    requested: 1,
    processed: [{ candidate_id: "candidate-42", memory_id: 8 }],
    failed: [],
  });
  vi.mocked(runMemoryPipeline).mockResolvedValue({
    task_id: "governance-1",
    status: "completed",
    processed_records: 1,
    candidates_created: 1,
    skipped_records: 0,
    failed_records: 0,
  });
  vi.mocked(getSensoryStats).mockResolvedValue({
    total: 12,
    pending: 12,
    sources: { traex: 9, codex: 3 },
  });
  vi.mocked(getSensoryRecords).mockResolvedValue({
    records: [],
    total: 0,
    limit: 100,
    offset: 0,
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
    expect(screen.getByText("Source records").parentElement?.textContent).toContain("12");

    fireEvent.click(preferenceCard);
    await waitFor(() => expect(screen.getByText("Prefers concise product interfaces.")).toBeTruthy());
    fireEvent.click(screen.getByText("Prefers concise product interfaces."));
    expect(screen.getByText("Memory details")).toBeTruthy();
  });

  it("surfaces the pending queue and opens the review view", async () => {
    const candidate = {
      candidate_id: "candidate-42",
      task_id: "governance-1",
      scope: "workspace" as const,
      content: "Deploys with pnpm, never npm.",
      memory_type: "user_preference",
      workspace: "/proj",
      session_id: null,
      created_at: "2026-07-31T09:00:00Z",
      updated_at: "2026-07-31T09:00:00Z",
      status: "pending" as const,
      confidence: 0.9,
      model: "test",
      prompt_version: "v2",
      sources: ["sensory-abc"],
    };
    vi.mocked(getMemory).mockResolvedValue([]);
    vi.mocked(getMemoryCandidates)
      .mockResolvedValueOnce([candidate])
      .mockResolvedValue([]);
    vi.mocked(getMemoryCandidate).mockResolvedValue({
      ...candidate,
      source_records: [],
    });

    render(<LanguageProvider><MemoryView /></LanguageProvider>);

    const banner = await screen.findByTestId("memory-pending-banner");
    expect(banner.textContent).toContain("1");
    fireEvent.click(banner);

    await screen.findByText("Candidate memory drafts");
    expect(screen.getByText("Review before Smallink uses it")).toBeTruthy();
    fireEvent.click(screen.getByText("Deploys with pnpm, never npm."));
    expect(await screen.findByText("Candidate details")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() =>
      expect(decideMemoryCandidate).toHaveBeenCalledWith("candidate-42", {
        action: "accept",
      }),
    );
  });

  it("hides the pending banner when the queue is empty", async () => {
    render(<LanguageProvider><MemoryView /></LanguageProvider>);
    await screen.findByText("Personal memory");
    expect(screen.queryByTestId("memory-pending-banner")).toBeNull();
  });

  it("accepts selected candidate memories in one batch", async () => {
    const candidate = {
      candidate_id: "candidate-42",
      task_id: "governance-1",
      scope: "global" as const,
      content: "Keep product decisions concise.",
      memory_type: "user_preference",
      workspace: null,
      session_id: null,
      created_at: "2026-07-31T09:00:00Z",
      updated_at: "2026-07-31T09:00:00Z",
      status: "pending" as const,
      confidence: 0.9,
      model: "test",
      prompt_version: "v2",
      sources: ["sensory-abc"],
    };
    vi.mocked(getMemory).mockResolvedValue([]);
    vi.mocked(getMemoryCandidates)
      .mockResolvedValueOnce([candidate])
      .mockResolvedValue([]);

    render(<LanguageProvider><MemoryView /></LanguageProvider>);
    fireEvent.click(await screen.findByTestId("memory-pending-banner"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all candidates" }));
    fireEvent.click(screen.getByRole("button", { name: "Accept selected" }));

    await waitFor(() => expect(decideMemoryCandidates).toHaveBeenCalledWith(
      ["candidate-42"],
      "accept",
    ));
  });

  it("opens imported source data and shows record details", async () => {
    const record = {
      record_id: "sensory-1",
      source_type: "traex",
      connector_id: "traex",
      account_id: null,
      external_id: "session-1:0",
      content_type: "traex_turn",
      raw_content: "User: Audit the project.\n\nAssistant: Done.",
      normalized_content: "User: Audit the project.\n\nAssistant: Done.",
      occurred_at: "2026-08-01T09:00:00Z",
      ingested_at: "2026-08-01T09:01:00Z",
      project_path: "/proj",
      conversation_id: "session-1",
      content_hash: "hash",
      sensitivity: "unknown",
      governance_status: "pending",
      metadata: {},
      source_locator: "/tmp/rollout.jsonl",
    };
    vi.mocked(getSensoryRecords).mockResolvedValue({
      records: [record],
      total: 1,
      limit: 100,
      offset: 0,
    });
    vi.mocked(getSensoryRecord).mockResolvedValue(record);

    render(<LanguageProvider><MemoryView /></LanguageProvider>);

    fireEvent.click(await screen.findByRole("button", { name: /Source records: 12.*Browse sources/ }));
    await screen.findByText("Data sources");
    fireEvent.click(screen.getByText(/User: Audit the project/));
    expect(await screen.findByText("Record details")).toBeTruthy();
    expect(screen.getByText("/tmp/rollout.jsonl")).toBeTruthy();
  });

  it("shows the filtered empty state instead of the first-use empty state", async () => {
    render(<LanguageProvider><MemoryView /></LanguageProvider>);

    fireEvent.click(await screen.findByRole("button", { name: /Source records: 12.*Browse sources/ }));
    await screen.findByText("Data sources");
    fireEvent.change(screen.getByPlaceholderText("Search content, project or conversation"), {
      target: { value: "no matching record" },
    });

    expect(await screen.findByText("No source records match these filters.")).toBeTruthy();
    expect(screen.queryByText("No source records yet")).toBeNull();
  });

  it("shows a retry action when memory loading fails", async () => {
    vi.mocked(getMemory).mockRejectedValueOnce(new Error("Backend unavailable"));

    render(<LanguageProvider><MemoryView /></LanguageProvider>);

    expect(await screen.findByText("Memory is unavailable")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Personal memory")).toBeTruthy();
  });

  it("generates candidates when source data exists without candidates", async () => {
    vi.mocked(getMemory).mockResolvedValue([]);
    vi.mocked(getMemoryCandidates).mockResolvedValue([]);

    render(<LanguageProvider><MemoryView /></LanguageProvider>);

    fireEvent.click(await screen.findByRole("button", { name: "Generate candidates" }));
    await waitFor(() => expect(runMemoryPipeline).toHaveBeenCalledWith({ retry_failed: false }));
  });
});
