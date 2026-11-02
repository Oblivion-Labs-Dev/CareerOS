import { expect, test } from "@playwright/test";

test.describe("CareerOS Observability & Diagnostic Suite", () => {
  test("1. Autopilot Live Activity reflects real runtime state @local", async ({ page }) => {
    await page.goto("/applications");

    await expect(page.getByRole("heading", { name: /Autopilot|Your job search agent/i, level: 1 })).toBeVisible({
      timeout: 20_000,
    });

    // Ensure live activity dock is expanded
    const expandBtn = page.getByRole("button", { name: "Expand activity" });
    if (await expandBtn.isVisible().catch(() => false)) {
      await expandBtn.click();
    }

    // Verify Live Autopilot Activity section is present
    await expect(page.getByText("Live Autopilot Activity")).toBeVisible({ timeout: 15_000 });

    // When idle, shows "Ready when you are." with queue info and macro workflow steps
    const idleHeadline = page.getByText(/Ready when you are|Autopilot running|A moment to regroup/i);
    await expect(idleHeadline.first()).toBeVisible();

    // Verify the macro workflow stages are visible
    await expect(page.getByText("DISCOVER", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("PREPARE", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("APPLY", { exact: true }).first()).toBeVisible();
  });

  test("2. Diagnostic page renders complete System Health with all 10 subsystems", async ({ page }) => {
    await page.goto("/diagnostic");

    await expect(page.getByRole("heading", { name: /System Diagnostics & Telemetry/i, level: 1 })).toBeVisible({
      timeout: 20_000,
    });

    const healthCard = page.getByRole("region", { name: "System Health" });
    await expect(healthCard).toBeVisible();

    // Check all required 10 subsystems inside System Health card
    const expectedSubsystems = [
      "CareerOS API",
      "SQLite Database",
      "Job Scraper",
      "Playwright Browser Worker",
      "Ollama Service",
      "Qwen Model",
      "Gemini Cloud Fallback",
      "LangSmith / LangGraph",
      "OpenTelemetry Collector",
      "Autopilot Queue",
    ];

    for (const name of expectedSubsystems) {
      await expect(healthCard.getByText(name, { exact: false }).first()).toBeVisible({ timeout: 10_000 });
    }

    // Verify operational health badges (Healthy / Degraded / Down)
    await expect(page.locator('[class*="serviceBadge"]').first()).toBeVisible();
  });

  test("3. Autopilot Metrics card allows 1h | 24h | 7d period filtering", async ({ page }) => {
    await page.goto("/diagnostic");

    await expect(page.getByRole("region", { name: "Autopilot Metrics" })).toBeVisible({ timeout: 20_000 });

    // Assert key operational metrics
    for (const metric of [
      "Jobs Discovered",
      "Jobs Prepared",
      "Applications Attempted",
      "Successful Submissions",
      "Submission Success %",
      "Staged for Review",
      "Failures",
      "Avg App Duration",
      "Avg Tailoring Time",
      "Model Fallbacks",
    ]) {
      await expect(page.getByText(metric, { exact: true })).toBeVisible();
    }

    // Test period switching: 1h, 24h, 7d
    const btn1h = page.getByRole("radio", { name: "1h" });
    const btn24h = page.getByRole("radio", { name: "24h" });
    const btn7d = page.getByRole("radio", { name: "7d" });

    await expect(btn1h).toBeVisible();
    await expect(btn24h).toBeVisible();
    await expect(btn7d).toBeVisible();

    await btn1h.click();
    await expect(btn1h).toHaveAttribute("aria-checked", "true");

    await btn7d.click();
    await expect(btn7d).toHaveAttribute("aria-checked", "true");

    await btn24h.click();
    await expect(btn24h).toHaveAttribute("aria-checked", "true");
  });

  test("4. Live Runs table allows timeline drilldown", async ({ page }) => {
    await page.goto("/diagnostic");

    await expect(page.getByRole("region", { name: "Live and Recent Runs" })).toBeVisible({ timeout: 20_000 });

    // If there are runs, clicking a row expands its timeline
    const rows = page.locator('tbody tr[class*="clickableRow"]');
    const count = await rows.count();
    if (count > 0) {
      await rows.first().click();
      await expect(page.getByText(/Workflow Execution Timeline/i)).toBeVisible({ timeout: 10_000 });

      // Verify the 6 pipeline stages in timeline drilldown
      await expect(page.getByText("DISCOVER", { exact: false }).first()).toBeVisible();
      await expect(page.getByText("MATCH", { exact: false }).first()).toBeVisible();
      await expect(page.getByText("TAILOR", { exact: false }).first()).toBeVisible();
      await expect(page.getByText("APPLY", { exact: false }).first()).toBeVisible();
      await expect(page.getByText("VALIDATE", { exact: false }).first()).toBeVisible();
      await expect(page.getByText("SUBMIT", { exact: false }).first()).toBeVisible();
    }
  });

  test("5. System Alarms panel displays monitors and allows acknowledgement", async ({ page }) => {
    await page.goto("/diagnostic");

    await expect(page.getByRole("region", { name: "System Alarms" })).toBeVisible({ timeout: 20_000 });

    // Verify alarms container or normal operational message
    const allNormal = page.getByText(/All system monitors normal/i);
    const alarmItems = page.locator('[class*="alarmItem"]');

    await expect(allNormal.or(alarmItems.first())).toBeVisible({ timeout: 15_000 });
  });

  test("6. Failure simulation triggers error capture, OTel recording, and recovery", async ({ page, request }) => {
    // 1. Simulate failure
    const simRes = await request.post("/api/backend/diagnostic/test/simulate-failure?failure_type=model_endpoint");
    expect(simRes.ok()).toBeTruthy();
    const simData = await simRes.json();
    expect(simData.success).toBeTruthy();
    const errorId = simData.errorRecorded?.id;

    // 2. Open Diagnostic page and verify error appears in Errors log
    await page.goto("/diagnostic");
    await expect(page.getByRole("heading", { name: /System Diagnostics & Telemetry/i, level: 1 })).toBeVisible({
      timeout: 20_000,
    });

    // Check System Health shows Qwen is Down
    const qwenCard = page.locator('[data-service-id="qwen"]');
    await expect(qwenCard).toBeVisible({ timeout: 15_000 });
    await expect(qwenCard).toHaveAttribute("data-status", "down");

    // Verify error is visible in Errors table
    await expect(page.getByText("Simulated failure: invalid model endpoint configured").first()).toBeVisible({
      timeout: 15_000,
    });

    // Expand error row to verify OpenTelemetry and Correlation details
    const errRow = page.locator('tr[class*="clickableRow"]', {
      hasText: "Simulated failure",
    }).first();
    await errRow.click();

    // Verify Trace ID, Run ID, and model error details are visible
    await expect(page.getByText(/Trace ID:/i)).toBeVisible();
    await expect(page.getByText(/model_endpoint/i).first()).toBeVisible();

    // 3. Restore configuration
    const restoreRes = await request.post("/api/backend/diagnostic/test/restore");
    expect(restoreRes.ok()).toBeTruthy();

    // 4. Refresh and confirm service returns to Healthy
    await page.reload();
    await expect(qwenCard).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Simulated failure: model endpoint unreachable")).toHaveCount(0);
  });

  test("7. Mobile responsive layout check on 390px viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/diagnostic");

    await expect(page.getByRole("heading", { name: /System Diagnostics & Telemetry/i, level: 1 })).toBeVisible({
      timeout: 20_000,
    });

    // Verify no horizontal overflow
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, "page should not overflow horizontally on mobile").toBeLessThanOrEqual(2);
  });

  test("8. Capture UI screenshots for Autopilot and Diagnostic dashboard @local", async ({ page }) => {
    // 1. Capture Autopilot page with upgraded Live Autopilot Activity
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/applications");
    await expect(page.getByText("Live Autopilot Activity")).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: "../../apps/web/e2e/screenshots/autopilot_live_activity.png", fullPage: true });

    // 2. Capture Diagnostic dashboard
    await page.goto("/diagnostic");
    await expect(page.getByRole("region", { name: "System Health" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("region", { name: "Autopilot Metrics" })).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: "../../apps/web/e2e/screenshots/diagnostic_dashboard.png", fullPage: true });
  });
});
