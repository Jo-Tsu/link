import { test, expect } from "./fixtures";

const openMemory = async (page: import("@playwright/test").Page) => {
  await page.goto("/");
  await page.getByTestId("nav-memory").click();
};

test("source data generates candidates and accepted candidates become memory", async ({
  page,
}) => {
  await openMemory(page);
  await expect(page.getByText("1 source records collected")).toBeVisible();
  await page.getByRole("button", { name: "Generate candidates" }).click();

  await expect(page.getByText("Candidate memory drafts")).toBeVisible();
  await page.getByText("Prefers concise product reports.").click();
  await expect(page.getByText("Candidate details")).toBeVisible();
  await page.getByRole("button", { name: "Accept", exact: true }).click();
  await expect(page.getByText("Personal memory")).toBeVisible();
  await expect(page.getByText("Confirmed memories").locator("..")).toContainText("1");
});
