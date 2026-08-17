import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createSkill,
  getSkillDetail,
  getSkills,
  importSkill,
  type SkillCatalogResponse,
} from "../api";
import { chooseFolder, chooseSkillArchive } from "../tauri";
import { SkillHub } from "./SkillHub";

vi.mock("../api", () => ({
  getSkills: vi.fn(),
  getSkillDetail: vi.fn(),
  createSkill: vi.fn(),
  importSkill: vi.fn(),
}));

vi.mock("../tauri", () => ({
  chooseFolder: vi.fn(),
  chooseSkillArchive: vi.fn(),
}));

const catalog: SkillCatalogResponse = {
  summary: { total: 1, active: 1, issues: 0, sources: 1 },
  skills: [
    {
      id: "skill_1",
      name: "review-code",
      display_name: "Review Code",
      description: "Review code changes",
      short_description: "Review code changes",
      path: "/tmp/review-code",
      allowed_tools: ["read_file"],
      source: "project",
      source_label: "Project skills",
      scope: "project",
      category: "Development",
      tags: ["review"],
      active: true,
      shadowed_by: null,
      valid: true,
      errors: [],
      warnings: [],
      resources: { scripts: 1, references: 2, assets: 0, other: 0 },
    },
  ],
};

describe("SkillHub", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(getSkills).mockResolvedValue(catalog);
    vi.mocked(getSkillDetail).mockResolvedValue({
      ...catalog.skills[0],
      instructions: "Inspect the diff and report findings.",
    });
    vi.mocked(createSkill).mockResolvedValue({
      ...catalog.skills[0],
      id: "skill_2",
      name: "meeting-followup",
      display_name: "Meeting Follow-up",
      instructions: "Extract owners and deadlines.",
    });
    vi.mocked(importSkill).mockResolvedValue({
      ...catalog.skills[0],
      id: "skill_3",
      name: "follow-builders",
      display_name: "Follow Builders",
      instructions: "Build the digest.",
    });
    vi.mocked(chooseFolder).mockReset();
    vi.mocked(chooseSkillArchive).mockReset();
  });

  it("loads the real catalog and fetches instructions only after a card opens", async () => {
    render(<SkillHub workspace="/tmp/project" />);

    const card = await screen.findByRole("button", {
      name: "Open Review Code Skill details",
    });
    expect(getSkills).toHaveBeenCalledWith("/tmp/project");
    expect(getSkillDetail).not.toHaveBeenCalled();

    fireEvent.click(card);

    expect(await screen.findByText("Inspect the diff and report findings.")).toBeTruthy();
    expect(getSkillDetail).toHaveBeenCalledWith("skill_1", "/tmp/project");
  });

  it("closes a detail when filtering removes its card", async () => {
    render(<SkillHub />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open Review Code Skill details",
      }),
    );
    expect(await screen.findByText("Inspect the diff and report findings.")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("Search Skills by name, purpose, or tag"), {
      target: { value: "calendar" },
    });

    await waitFor(() => {
      expect(screen.queryByText("Skill details")).toBeNull();
    });
  });

  it("creates a Skill through the real mutation entry", async () => {
    render(<SkillHub workspace="/tmp/project" />);
    await screen.findByText("Review Code");

    fireEvent.click(screen.getByRole("button", { name: "New Skill" }));
    fireEvent.change(screen.getByPlaceholderText("meeting-followup"), {
      target: { value: "meeting-followup" },
    });
    fireEvent.change(screen.getByPlaceholderText("Meeting follow-up"), {
      target: { value: "Meeting Follow-up" },
    });
    fireEvent.change(screen.getByPlaceholderText("Describe the task, trigger, and expected outcome."), {
      target: { value: "Use after meetings to create owned actions." },
    });
    fireEvent.change(screen.getByPlaceholderText("1. Gather the required context…"), {
      target: { value: "Extract owners and deadlines." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Skill" }));

    await waitFor(() => expect(createSkill).toHaveBeenCalledWith(expect.objectContaining({
      name: "meeting-followup",
      workspace: "/tmp/project",
      scope: "user",
    })));
  });

  it("imports a complete Skill from a folder or ZIP package", async () => {
    vi.mocked(chooseSkillArchive).mockResolvedValue("/tmp/follow-builders.zip");
    render(<SkillHub workspace="/tmp/project" />);
    await screen.findByText("Review Code");

    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(screen.getByRole("button", { name: "Choose folder" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Choose ZIP" }));

    expect(await screen.findByText("/tmp/follow-builders.zip")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Import Skill" }));

    await waitFor(() => expect(importSkill).toHaveBeenCalledWith({
      path: "/tmp/follow-builders.zip",
      scope: "user",
      workspace: "/tmp/project",
    }));
  });

  it("hands conversational creation back to the Link agent", async () => {
    const onCreate = vi.fn();
    render(<SkillHub onCreateWithAgent={onCreate} />);
    await screen.findByText("Review Code");

    fireEvent.click(screen.getByRole("button", { name: "Create with Agent" }));
    expect(onCreate).toHaveBeenCalledOnce();
  });
});
