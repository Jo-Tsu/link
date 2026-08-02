import { test, expect } from "./fixtures";

test("TRAE connector import completes and links to memory source data", async ({ page }) => {
  await page.addInitScript(() => {
    (window as any).__TAURI__ = {
      core: {
        invoke: async (command: string) =>
          command === "pick_folder" ? "/mock/.trae" : null,
      },
    };
  });
  await page.goto("/");
  await page.getByTestId("nav-connectors").click();

  await page.getByRole("button", { name: "Connect TRAE CLI" }).click();
  await page.getByTestId("modal-traex-connect").click();
  await expect(page.getByText("Import complete")).toBeVisible();
  await expect(page.getByText(/Imported 2 conversation records/)).toBeVisible();
  await page.getByRole("button", { name: /View memory data/ }).click();
  await expect(page.getByText("Personal memory")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Source records: 2. Browse sources" }),
  ).toBeVisible();
});

test("connector page never advertises hidden cloud catalog entries", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("nav-connectors").click();

  await expect(page.getByTestId("connector-traex")).toBeVisible();
  await expect(page.getByTestId("connector-codex")).toBeVisible();
  await expect(page.getByTestId("connector-minem")).toBeVisible();
  await expect(page.getByText(/30\+ more tools/)).toHaveCount(0);
  await expect(page.getByText("Notion", { exact: true })).toHaveCount(0);
});
