import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getAgentCollaborations,
  getPersonas,
  getRuntimeAgentEvents,
  getRuntimeTaskRun,
} from "../api";
import { LanguageProvider } from "../i18n";
import { AgentsView } from "./AgentsView";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    getPersonas: vi.fn(),
    getAgentCollaborations: vi.fn(),
    getRuntimeTaskRun: vi.fn(),
    getRuntimeAgentEvents: vi.fn(),
  };
});

const personas = [
  {
    id: "link", name: "Link", icon: "link", tagline: "General coordinator",
    needs_workspace: false, builtin: true, family: "knowledge", workspace: "none",
    tools: ["memory"], enabled: true, surfaced: true, default: true,
  },
  {
    id: "code", name: "Code", icon: "code", tagline: "Repository work",
    needs_workspace: true, builtin: true, family: "code", workspace: "project",
    tools: ["read_file", "write_file", "explore"], enabled: true, surfaced: true, default: false,
  },
];

const collaboration = {
  task_id: "task-1", session_id: "session-1", title: "Map the Smallink architecture",
  project_id: "/work/Smallink", task_run_id: "run-1", trigger: "user",
  status: "completed" as const, model: "gpt-test", mode: "interactive",
  started_at: "2026-07-29T01:00:00Z", finished_at: "2026-07-29T01:00:04Z",
  error: null, agent_count: 2, child_agent_count: 1, agent_roles: ["code", "explorer"],
};

const root = {
  agent_run_id: "root", task_run_id: "run-1", parent_agent_run_id: null,
  root_agent_run_id: "root", agent_role: "code", status: "completed" as const,
  model: "gpt-test", input: { text: "map it" }, output: { text: "done" },
  started_at: "2026-07-29T01:00:00Z", finished_at: "2026-07-29T01:00:04Z", error: null,
};

const child = {
  ...root,
  agent_run_id: "child",
  parent_agent_run_id: "root",
  agent_role: "explorer",
  input: { task: "find the runtime" },
  output: { report: "runtime map" },
};

beforeEach(() => {
  localStorage.setItem("link:language:v1", "en");
  vi.mocked(getPersonas).mockResolvedValue(personas);
  vi.mocked(getAgentCollaborations).mockResolvedValue([collaboration]);
  vi.mocked(getRuntimeTaskRun).mockResolvedValue({
    task_run_id: "run-1", task_id: "task-1", trigger: "user", status: "completed",
    model: "gpt-test", mode: "interactive", started_at: collaboration.started_at,
    finished_at: collaboration.finished_at, error: null, agent_runs: [root, child],
  });
  vi.mocked(getRuntimeAgentEvents).mockResolvedValue([
    { event_id: "event-1", agent_run_id: "root", sequence: 1, event_type: "turn_start", data: { input: "map it" }, created_at: collaboration.started_at },
  ]);
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
});

describe("AgentsView", () => {
  it("shows registered members as an architecture and explains the real Explorer system sub-agent", async () => {
    render(<LanguageProvider><AgentsView /></LanguageProvider>);
    expect(await screen.findByText("Smallink multi-agent architecture")).toBeTruthy();
    expect(screen.getByText("Selectable role")).toBeTruthy();
    expect(screen.getByText("Runtime delegation")).toBeTruthy();
    expect(screen.getByText("Explorer")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open Explorer details" }));
    expect(await screen.findByRole("dialog", { name: "Agent details" })).toBeTruthy();
    expect(screen.getByText("Cannot delegate another agent.")).toBeTruthy();
  });

  it("supports zoom controls without changing the architecture data", async () => {
    render(<LanguageProvider><AgentsView /></LanguageProvider>);
    expect(await screen.findByText("100%")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fit canvas" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByText("110%")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Reset zoom" })[0]);
    expect(screen.getByText("100%")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Open Code details" })).toBeTruthy();
  });

  it("marks Explorer unavailable when its Code parent is disabled", async () => {
    vi.mocked(getPersonas).mockResolvedValue(
      personas.map((persona) => persona.id === "code" ? { ...persona, enabled: false } : persona),
    );
    render(<LanguageProvider><AgentsView /></LanguageProvider>);
    const explorer = await screen.findByRole("button", { name: "Open Explorer details" });
    expect(explorer.textContent).toContain("Disabled");
  });

  it("renders only real collaboration runs and lets users inspect a child run", async () => {
    const open = vi.fn();
    render(<LanguageProvider><AgentsView onOpenSession={open} /></LanguageProvider>);
    fireEvent.click(await screen.findByRole("tab", { name: /Collaboration history/ }));

    expect((await screen.findAllByText("Map the Smallink architecture")).length).toBeGreaterThan(0);
    expect(screen.getByText("Collaboration graph")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Inspect Explorer run" }));
    await waitFor(() => expect(getRuntimeAgentEvents).toHaveBeenLastCalledWith("child"));
    expect(screen.getByText(/runtime map/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open conversation" }));
    expect(open).toHaveBeenCalledWith("session-1");
  });

  it("renders the product surface in Chinese", async () => {
    localStorage.setItem("link:language:v1", "zh-CN");
    render(<LanguageProvider><AgentsView /></LanguageProvider>);
    expect(await screen.findByText("Smallink 多智能体架构")).toBeTruthy();
    expect(screen.getByRole("tab", { name: /智能体架构/ })).toBeTruthy();
    expect(screen.getByText("运行时委派")).toBeTruthy();
    expect(screen.getByRole("tab", { name: /协作记录/ })).toBeTruthy();
  });
});
