import { test, expect } from "./fixtures";

test("MineM is the only application and opens its material workspace", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("nav-apps").click();

  await page.getByTestId("app-minem").click();
  await expect(page.getByRole("heading", { name: "MineM material library" })).toBeVisible();
  await page.getByRole("button", { name: "Open material library" }).click();
  await expect(page.getByRole("tab", { name: "All assets" })).toBeVisible();
  await expect(page.getByText("Smallink architecture", { exact: true })).toBeVisible();
  await expect(page.getByText("Codex", { exact: true })).toHaveCount(0);
  await expect(page.getByText("TRAE CLI", { exact: true })).toHaveCount(0);
});

test("application center never advertises hidden connector catalog entries", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("nav-apps").click();

  await expect(page.getByTestId("app-minem")).toBeVisible();
  await expect(page.locator("[data-testid^='app-']")).toHaveCount(1);
  await expect(page.getByText(/30\+ more tools/)).toHaveCount(0);
  await expect(page.getByText("Notion", { exact: true })).toHaveCount(0);
});
