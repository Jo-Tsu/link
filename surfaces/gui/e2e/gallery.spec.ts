import { test, expect } from "./fixtures";

test("MineM is the only connector entry and opens its local-app flow", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("nav-connectors").click();

  await page.getByRole("button", { name: "Connect MineM" }).click();
  await expect(page.getByTestId("add-connection-modal")).toBeVisible();
  await expect(page.getByTestId("modal-local-app-connect")).toContainText("MineM");
  await expect(page.getByText("Codex", { exact: true })).toHaveCount(0);
  await expect(page.getByText("TRAE CLI", { exact: true })).toHaveCount(0);
});

test("connector page never advertises hidden cloud catalog entries", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("nav-connectors").click();

  await expect(page.getByTestId("connector-minem")).toBeVisible();
  await expect(page.getByTestId("connector-traex")).toHaveCount(0);
  await expect(page.getByTestId("connector-codex")).toHaveCount(0);
  await expect(page.getByText(/30\+ more tools/)).toHaveCount(0);
  await expect(page.getByText("Notion", { exact: true })).toHaveCount(0);
});
