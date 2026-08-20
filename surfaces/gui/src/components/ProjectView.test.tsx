import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getProjectOverview,
  getSensoryProvenance,
  indexProjectKnowledge,
  searchKnowledge,
  setKnowledgeArchived,
  type ProjectOverview,
} from "../api";
import { LanguageProvider } from "../i18n";
import { ProjectView } from "./ProjectView";

vi.mock("../api", () => ({
  getProjectOverview: vi.fn(),
  getSensoryProvenance: vi.fn(),
  indexProjectKnowledge: vi.fn(),
  searchKnowledge: vi.fn(),
  setKnowledgeArchived: vi.fn(),
}));

const SOURCE = {
  record_id: "sensory-1",
  source_type: "minem",
  connector_id: "minem",
  account_id: null,
  external_id: "asset.list:1",
  content_type: "app_capability_result",
  raw_content: JSON.stringify({ text: "User asked for a reusable architecture page." }),
  normalized_content: JSON.stringify({ text: "User asked for a reusable architecture page." }),
  occurred_at: "2026-08-20T10:00:00Z",
  ingested_at: "2026-08-20T10:00:00Z",
  project_path: "/tmp/minem",
  conversation_id: "session-1",
  content_hash: "abc",
  sensitivity: "normal",
  governance_status: "processed",
  metadata: { project_id: "system:minem" },
  source_locator: "/v1/apps/minem/assets",
};

const OVERVIEW: ProjectOverview = {
  project: {
    project_id: "system:minem",
    name: "MineM",
    icon: "folder",
    workspace_path: "/tmp/minem",
    description: "MineM material library",
    status: "active",
    pinned: true,
    sort_order: -100,
    project_type: "system_app",
    owner_app_id: "minem",
    system_key: "system:minem",
    session_count: 1,
    created_at: "2026-08-20T10:00:00Z",
    updated_at: "2026-08-20T10:00:00Z",
  },
  metrics: {
    sessions: 1,
    tasks: 1,
    source_records: 1,
    pending_governance: 0,
    memory_candidates: 1,
    memories: 1,
    app_assets: 1,
    knowledge: 1,
  },
  sessions: [{
    session_id: "session-1",
    title: "Project kickoff",
    workspace: "/tmp/minem",
    project_id: "system:minem",
    agent: "link",
    model: "test-model",
    mode: "interactive",
    updated_at: "2026-08-20T10:00:00Z",
    messages: 2,
  }],
  tasks: [{
    task_id: "task-1",
    session_id: "session-1",
    title: "Project kickoff",
    status: "completed",
    project_id: "system:minem",
    created_at: "2026-08-20T10:00:00Z",
    updated_at: "2026-08-20T10:00:00Z",
  }],
  source_records: [SOURCE],
  source_statuses: { pending: 0, processing: 0, processed: 1, skipped: 0, failed: 0 },
  candidates: [],
  memories: [{
    id: 1,
    scope: "workspace",
    key: "artifact_summary",
    content: "MineM stores the reusable architecture page.",
    workspace: "/tmp/minem",
    session_id: null,
    status: "active",
    source_record_id: "sensory-1",
    created_at: "2026-08-20T10:00:00Z",
  }],
  memory_types: { artifact_summary: 1 },
  app_assets: [{
    asset_ref_id: "asset-ref-1",
    app_id: "minem",
    project_id: "system:minem",
    external_asset_id: "page-1",
    external_code: "PAGE-1",
    asset_type: "page",
    version_id: "",
    title: "Architecture page",
    preview_ref: null,
    sensory_record_id: "sensory-1",
    first_seen_at: "2026-08-20T10:00:00Z",
    last_seen_at: "2026-08-20T10:00:00Z",
  }],
  knowledge: [{
    item_id: "knowledge-1",
    project_id: "system:minem",
    source_record_id: "sensory-1",
    source_type: "minem_asset",
    external_id: "page-1",
    title: "Architecture page",
    content: "MineM keeps a cited architecture page in the project knowledge repository.",
    content_hash: "hash-1",
    status: "active",
    current_version: 1,
    chunk_count: 1,
    metadata: {},
    created_at: "2026-08-20T10:00:00Z",
    updated_at: "2026-08-20T10:00:00Z",
  }],
};

describe("ProjectView", () => {
  beforeEach(() => {
    vi.mocked(getProjectOverview).mockResolvedValue(OVERVIEW);
    vi.mocked(getSensoryProvenance).mockResolvedValue({
      record_id: "sensory-1",
      source: SOURCE,
      candidates: [{
        candidate_id: "candidate-1",
        content: "MineM stores the reusable architecture page.",
        memory_type: "artifact_summary",
        status: "accepted",
        confidence: 0.92,
        model: "test-model",
        prompt_version: "memory-v1",
      }],
      decisions: [{ decision_id: "decision-1", action: "accept", created_at: "2026-08-20T10:01:00Z" }],
      memories: OVERVIEW.memories,
      usages: [],
    });
    vi.mocked(searchKnowledge).mockResolvedValue({
      query: "architecture",
      strategy: "hybrid_lexical_v1",
      results: [{
        item_id: "knowledge-1",
        chunk_id: "chunk-1",
        project_id: "system:minem",
        title: "Architecture page",
        content: "MineM keeps a cited architecture page in the project knowledge repository.",
        score: 0.85,
        score_components: { full_text: 1, term_coverage: 0.5, exact_phrase: 0 },
        matched_terms: ["architecture"],
        explanation: ["full-text rank"],
        citation: {
          source_type: "minem_asset",
          external_id: "page-1",
          source_record_id: "sensory-1",
          source_locator: "/v1/apps/minem/assets",
        },
        updated_at: "2026-08-20T10:00:00Z",
      }],
    });
    vi.mocked(indexProjectKnowledge).mockResolvedValue({ ok: true, indexed: 1, skipped: 0 });
    vi.mocked(setKnowledgeArchived).mockResolvedValue({ ...OVERVIEW.knowledge[0], status: "archived" });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("aggregates the project and opens a human-readable provenance chain", async () => {
    const onNewSession = vi.fn();
    const onOpenSession = vi.fn();
    const onOpenApplication = vi.fn();
    render(
      <LanguageProvider>
        <ProjectView
          projectId="system:minem"
          onBack={vi.fn()}
          onNewSession={onNewSession}
          onOpenSession={onOpenSession}
          onOpenApplication={onOpenApplication}
        />
      </LanguageProvider>,
    );

    expect(await screen.findByRole("heading", { name: "MineM" })).toBeTruthy();
    expect(screen.getByText("Project kickoff")).toBeTruthy();
    expect(screen.getByText("User asked for a reusable architecture page.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    fireEvent.click(screen.getByRole("button", { name: "Open application" }));
    fireEvent.click(screen.getByRole("button", { name: /Project kickoff/ }));
    expect(onNewSession).toHaveBeenCalledWith("system:minem");
    expect(onOpenApplication).toHaveBeenCalledWith("minem");
    expect(onOpenSession).toHaveBeenCalledWith(OVERVIEW.sessions[0]);

    fireEvent.click(screen.getByRole("button", { name: /User asked for a reusable architecture page/ }));
    await waitFor(() => expect(getSensoryProvenance).toHaveBeenCalledWith("sensory-1"));
    expect(await screen.findByRole("dialog", { name: "Source provenance" })).toBeTruthy();
    expect(screen.getAllByText("MineM stores the reusable architecture page.")).toHaveLength(2);
    expect(screen.getByText("92%")).toBeTruthy();
  });

  it("searches cited project knowledge and archives an indexed item", async () => {
    render(
      <LanguageProvider>
        <ProjectView
          projectId="system:minem"
          onBack={vi.fn()}
          onNewSession={vi.fn()}
          onOpenSession={vi.fn()}
          onOpenApplication={vi.fn()}
        />
      </LanguageProvider>,
    );

    await screen.findByRole("heading", { name: "MineM" });
    fireEvent.click(screen.getByRole("tab", { name: "Knowledge 1" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Search project knowledge" }), {
      target: { value: "architecture" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(searchKnowledge).toHaveBeenCalledWith(
      "architecture",
      { projectId: "system:minem", limit: 20 },
    ));
    expect(screen.getByText("Relevance: 85%")).toBeTruthy();
    fireEvent.click(screen.getByTitle("Archive knowledge"));
    await waitFor(() => expect(setKnowledgeArchived).toHaveBeenCalledWith("knowledge-1", true));
  });
});
