import { test, expect } from "./fixtures";

test("a fresh Smallink session streams a persisted-style response", async ({ page }) => {
  await page.goto("/");

  const composer = page.getByPlaceholder(/Ask the agent/);
  await expect(composer).toBeVisible({ timeout: 10_000 });
  await composer.fill("Audit this product");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("Audit this product", { exact: true })).toBeVisible();
  await expect(page.getByText("Echo: Audit this product", { exact: true })).toBeVisible();
});

test("current connector catalog exposes only MineM", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("nav-connectors").click();

  await expect(page.getByText("MineM", { exact: true })).toBeVisible();
  await expect(page.getByText("Codex", { exact: true })).toHaveCount(0);
  await expect(page.getByText("TRAE CLI", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Notion", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Slack", { exact: true })).toHaveCount(0);
});
