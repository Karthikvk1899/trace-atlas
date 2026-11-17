import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const credentials = JSON.parse(
  readFileSync(
    process.env.ATLAS_TEST_CREDENTIALS || "/tmp/atlas-browser-credentials.json",
    "utf8",
  ),
);
async function login(page: any, role = "investigator") {
  await page.goto("/");
  await page.getByLabel("Workspace credential").fill(credentials[role]);
  await page.getByRole("button", { name: "Connect to workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Executions", exact: true }),
  ).toBeVisible();
}
test("investigate, compare, export and replay a failed checkout", async ({
  page,
}) => {
  await login(page);
  await page
    .getByRole("button", { name: /Checkout · payment unavailable/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "Checkout · payment unavailable" }),
  ).toBeVisible();
  await expect(page.getByText("SPAN WATERFALL")).toBeVisible();
  await page.screenshot({
    path: "test-results/trace-atlas-desktop.png",
    fullPage: true,
  });
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export evidence" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^execution-.*json$/);
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page
    .getByLabel("Baseline execution")
    .selectOption({ label: credentials.baseline_label });
  await page.getByRole("button", { name: "Compare evidence" }).click();
  await expect(page.getByText("200 → 503")).toBeVisible();
  await page.getByRole("button", { name: "Replay setup" }).click();
  await page.getByLabel("Payment response override").selectOption("200");
  await page.getByLabel("Expected checkout status").selectOption("201");
  await page.getByRole("button", { name: "Queue replay" }).click();
  await expect(page.getByText("ASSERTION PASSED")).toBeVisible({
    timeout: 30000,
  });
  await page.screenshot({
    path: "test-results/trace-atlas-replay.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/trace-atlas-mobile.png",
    fullPage: true,
  });
  await page.reload();
  await expect(page.getByLabel("Workspace credential")).toBeVisible();
});
test("reader can investigate but cannot queue or import", async ({ page }) => {
  await login(page, "reader");
  await expect(
    page.getByRole("button", { name: "Import evidence" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: /Checkout · payment unavailable/ })
    .click();
  await page.getByRole("button", { name: "Replay setup" }).click();
  await expect(
    page.getByRole("button", { name: "Queue replay" }),
  ).toBeDisabled();
});
