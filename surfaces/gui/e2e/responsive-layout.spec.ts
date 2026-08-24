import { test, expect } from "./fixtures";

const viewports = [
  { width: 1360, height: 900 },
  { width: 1024, height: 768 },
  { width: 980, height: 640 },
];

for (const viewport of viewports) {
  test(`core surfaces fit ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page.getByPlaceholder(/Ask the agent/)).toBeVisible({ timeout: 10_000 });

    const assertFits = async () => {
      const metrics = await page.evaluate(() => ({
        bodyWidth: document.body.scrollWidth,
        viewportWidth: document.documentElement.clientWidth,
        bodyHeight: document.body.scrollHeight,
        viewportHeight: document.documentElement.clientHeight,
      }));
      expect(metrics.bodyWidth).toBeLessThanOrEqual(metrics.viewportWidth + 1);
      expect(metrics.bodyHeight).toBeLessThanOrEqual(metrics.viewportHeight + 1);
    };

    await assertFits();
    await page.getByTestId("nav-memory").click();
    await expect(page.getByTestId("memory-view")).toBeVisible();
    await assertFits();
    await page.getByTestId("nav-automations").click();
    await expect(page.getByRole("heading", { name: /Automations/i })).toBeVisible();
    await assertFits();
  });
}
