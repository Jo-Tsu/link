import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getRuntimeAgentEvents,
  getRuntimeTask,
  getRuntimeTaskRun,
  getRuntimeTasks,
} from "../api";
import { LanguageProvider } from "../i18n";
import { RunsView } from "./RunsView";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    getRuntimeTasks: vi.fn(),
    getRuntimeTask: vi.fn(),
    getRuntimeTaskRun: vi.fn(),
    getRuntimeAgentEvents: vi.fn(),
  };
});

const task = {
  task_id: "task-1",
  session_id: "session-1",
  title: "Design Link",
  status: "completed" as const,
  project_id: "/work/link",
  created_at: "2026-07-27T01:00:00Z",
  updated_at: "2026-07-27T01:02:00Z",
};

const root = {
  agent_run_id: "agent-root",
  task_run_id: "run-1",
  parent_agent_run_id: null,
  root_agent_run_id: "agent-root",
  agent_role: "link",
  status: "completed" as const,
  model: "gpt-test",
  input: "design",
  output: { text: "Root result" },
  started_at: "2026-07-27T01:00:00Z",
  finished_at: "2026-07-27T01:00:02Z",
  error: null,
};

const child = {
  ...root,
  agent_run_id: "agent-child",
  parent_agent_run_id: "agent-root",
  agent_role: "explorer",
  output: { report: "Child report" },
};

beforeEach(() => {
  localStorage.setItem("link:language:v1", "en");
  vi.mocked(getRuntimeTasks).mockResolvedValue([task]);
  vi.mocked(getRuntimeTask).mockResolvedValue({
    ...task,
    runs: [
      {
        task_run_id: "run-1",
        task_id: "task-1",
        trigger: "user",
        status: "completed",
        model: "gpt-test",
        mode: "interactive",
        started_at: "2026-07-27T01:00:00Z",
        finished_at: "2026-07-27T01:00:02Z",
        error: null,
      },
    ],
  });
  vi.mocked(getRuntimeTaskRun).mockResolvedValue({
    task_run_id: "run-1",
    task_id: "task-1",
    trigger: "user",
    status: "completed",
    model: "gpt-test",
    mode: "interactive",
    started_at: "2026-07-27T01:00:00Z",
    finished_at: "2026-07-27T01:00:02Z",
    error: null,
    agent_runs: [root, child],
  });
  vi.mocked(getRuntimeAgentEvents).mockResolvedValue([
    {
      event_id: "event-1",
      agent_run_id: "agent-root",
      sequence: 1,
      event_type: "turn_start",
      data: { input: "design" },
      created_at: "2026-07-27T01:00:00Z",
    },
  ]);
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
});

describe("RunsView", () => {
  it("renders the task, parent-child agent tree, events and opens the source session", async () => {
    const open = vi.fn();
    render(
      <LanguageProvider>
        <RunsView onOpenSession={open} />
      </LanguageProvider>,
    );

    expect(await screen.findByText("Design Link")).toBeTruthy();
    expect(await screen.findByText("Agent tree")).toBeTruthy();
    expect(screen.getByText("Smallink")).toBeTruthy();
    expect(screen.getByText("explorer")).toBeTruthy();
    expect(await screen.findByText("turn_start")).toBeTruthy();

    fireEvent.click(screen.getByText("explorer"));
    await waitFor(() =>
      expect(getRuntimeAgentEvents).toHaveBeenLastCalledWith("agent-child"),
    );

    fireEvent.click(screen.getByRole("button", { name: "Open conversation" }));
    expect(open).toHaveBeenCalledWith("session-1");
  });

  it("renders the same run surface in Chinese", async () => {
    localStorage.setItem("link:language:v1", "zh-CN");
    render(
      <LanguageProvider>
        <RunsView />
      </LanguageProvider>,
    );
    expect(await screen.findByText("智能体树")).toBeTruthy();
    expect(screen.getByText("事件时间线")).toBeTruthy();
    expect(screen.getAllByText("已完成").length).toBeGreaterThan(0);
  });

  it("lets the user inspect an earlier attempt", async () => {
    vi.mocked(getRuntimeTask).mockResolvedValue({
      ...task,
      runs: [
        {
          task_run_id: "run-2",
          task_id: "task-1",
          trigger: "retry",
          status: "completed",
          model: "gpt-test",
          mode: "interactive",
          started_at: "2026-07-27T01:10:00Z",
          finished_at: "2026-07-27T01:10:02Z",
          error: null,
        },
        {
          task_run_id: "run-1",
          task_id: "task-1",
          trigger: "user",
          status: "failed",
          model: "gpt-test",
          mode: "interactive",
          started_at: "2026-07-27T01:00:00Z",
          finished_at: "2026-07-27T01:00:02Z",
          error: "provider unavailable",
        },
      ],
    });
    vi.mocked(getRuntimeTaskRun).mockImplementation(async (id) => ({
      task_run_id: id,
      task_id: "task-1",
      trigger: id === "run-1" ? "user" : "retry",
      status: id === "run-1" ? "failed" : "completed",
      model: "gpt-test",
      mode: "interactive",
      started_at: "2026-07-27T01:00:00Z",
      finished_at: "2026-07-27T01:00:02Z",
      error: id === "run-1" ? "provider unavailable" : null,
      agent_runs: [{ ...root, task_run_id: id, status: id === "run-1" ? "failed" : "completed" }],
    }));

    render(
      <LanguageProvider>
        <RunsView />
      </LanguageProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /#1/ }));
    await waitFor(() => expect(getRuntimeTaskRun).toHaveBeenLastCalledWith("run-1"));
    expect(await screen.findByText("provider unavailable")).toBeTruthy();
  });
});
