import { test, expect } from "./fixtures";

test("rapid switching between two projects never lets the older chat replace the active one", async ({
  page,
  productState,
}) => {
  const now = new Date().toISOString();
  productState.projects = [
    {
      project_id: "project-a",
      name: "Project Alpha",
      icon: "📁",
      workspace_path: "/mock/alpha",
      description: "",
      status: "active",
      default_agent: "link",
      default_model: "gpt-test",
      pinned: false,
      sort_order: 0,
      session_count: 1,
      created_at: now,
      updated_at: now,
    },
    {
      project_id: "project-b",
      name: "Project Beta",
      icon: "📁",
      workspace_path: "/mock/beta",
      description: "",
      status: "active",
      default_agent: "link",
      default_model: "gpt-test",
      pinned: false,
      sort_order: 1,
      session_count: 1,
      created_at: now,
      updated_at: now,
    },
  ];
  productState.sessions = [
    {
      session_id: "session-a",
      title: "Alpha chat",
      workspace: "/mock/alpha",
      agent: "link",
      model: "gpt-test",
      mode: "interactive",
      updated_at: "2026-08-08T10:00:00Z",
      messages: 2,
      project_id: "project-a",
    },
    {
      session_id: "session-b",
      title: "Beta chat",
      workspace: "/mock/beta",
      agent: "link",
      model: "gpt-test",
      mode: "interactive",
      updated_at: "2026-08-08T09:00:00Z",
      messages: 2,
      project_id: "project-b",
    },
  ];
  productState.sessionMessages = {
    "session-a": [
      { role: "user", content: "Alpha-only question" },
      { role: "assistant", content: "Alpha-only answer" },
    ],
    "session-b": [
      { role: "user", content: "Beta-only question" },
      { role: "assistant", content: "Beta-only answer" },
    ],
  };
  productState.sessionMessageDelay = {
    "session-a": 500,
    "session-b": 30,
  };

  await page.goto("/");
  const projectsBand = page.getByTestId("projects-band");
  const alphaChat = projectsBand.getByText("Alpha chat", { exact: true });
  await expect(alphaChat).toBeVisible({ timeout: 10_000 });
  await projectsBand.getByRole("button", { name: "Expand project" }).click();
  const betaChat = projectsBand.getByText("Beta chat", { exact: true });
  await expect(betaChat).toBeVisible();

  await alphaChat.click();
  await betaChat.click();

  await expect(page.getByText("Beta-only answer", { exact: true })).toBeVisible();
  await page.waitForTimeout(650);
  await expect(page.getByText("Beta-only answer", { exact: true })).toBeVisible();
  await expect(page.getByText("Alpha-only answer", { exact: true })).toHaveCount(0);
  await expect(page.locator(".main-title-text")).toHaveText("Beta chat");
});
