import { expect, test, type Page } from "@playwright/test";

const PREVIEW_PATH = "/resume-corpus?preview=1";

const CORPUS_AREAS = [
  { label: "Overview", view: null },
  { label: "Accomplishments", view: "accomplishments" },
  { label: "Metrics", view: "metrics" },
  { label: "Evidence", view: "evidence" },
  { label: "Interview", view: "interview" },
  { label: "Settings", view: "settings" },
] as const;

const WORKSPACE_SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "context", label: "Problem and context" },
  { id: "ownership", label: "Personal ownership" },
  { id: "challenge", label: "Technical challenge" },
  { id: "architecture", label: "Architecture" },
  { id: "tradeoffs", label: "Alternatives and tradeoffs" },
  { id: "failure", label: "Failure modes" },
  { id: "reliability", label: "Reliability" },
  { id: "security", label: "Security" },
  { id: "scale", label: "Scale" },
  { id: "business", label: "Business impact" },
  { id: "engineering", label: "Engineering impact" },
  { id: "leadership", label: "Leadership" },
  { id: "evidence", label: "Evidence" },
  { id: "concerns", label: "Reviewer concerns" },
  { id: "interview", label: "Interview questions" },
  { id: "variants", label: "Resume variants" },
  { id: "publishing", label: "LinkedIn and portfolio" },
  { id: "history", label: "Change history" },
] as const;

async function openPreview(page: Page, suffix = "") {
  await page.goto(`${PREVIEW_PATH}${suffix}`);
  await expect(page.locator("#corpus-main")).toBeAttached();
}

async function selectSegment(page: Page, groupName: string, optionName: string) {
  const group = page.getByRole("group", { name: groupName });
  await group.getByText(optionName, { exact: true }).click();
  await expect(group.getByRole("radio", { name: optionName })).toBeChecked();
}

test.describe("Resume Corpus redesign", () => {
  test("loads the deterministic preview overview", async ({ page }) => {
    await openPreview(page);

    await expect(page.getByRole("heading", { level: 1, name: "Resume Corpus" })).toBeVisible();
    await expect(page.getByText(/Alex Morgan's source of truth/i)).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Corpus areas" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Resume corpus overview" })).toBeVisible();
    await expect(page.getByText("Preview data · local edits", { exact: true })).toBeVisible();
  });

  test("keeps URL state across all Phase 1 corpus areas", async ({ page }) => {
    await openPreview(page);
    const areaNavigation = page.getByRole("navigation", { name: "Corpus areas" });

    for (const area of CORPUS_AREAS) {
      const areaButton = areaNavigation.getByRole("button", {
        name: new RegExp(`^${area.label}(?:\\s|$)`, "i"),
      });
      await areaButton.click();
      await expect(areaButton).toHaveAttribute("aria-current", "page");
      await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe(area.view);
    }
  });

  test("supports keyboard navigation in the corpus rail", async ({ page }) => {
    await openPreview(page);
    const areaNavigation = page.getByRole("navigation", { name: "Corpus areas" });
    const overview = areaNavigation.getByRole("button", { name: /^Overview(?:\s|$)/i });
    const accomplishments = areaNavigation.getByRole("button", { name: /^Accomplishments(?:\s|$)/i });

    await overview.focus();
    await page.keyboard.press("ArrowDown");
    await expect(accomplishments).toBeFocused();
  });

  test("searches across the corpus and opens the source record", async ({ page }) => {
    await openPreview(page);

    await page.getByRole("button", { name: /Search accomplishments, metrics, evidence/i }).click();
    const dialog = page.getByRole("dialog", { name: "Search the Resume Corpus" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Close search" }).click();
    await expect(dialog).toBeHidden();

    await page.keyboard.press("Control+K");
    await expect(dialog).toBeVisible();
    await dialog.getByPlaceholder("Search the entire career corpus...").fill("Northstar");
    await dialog.getByRole("combobox", { name: "Filter search category" }).selectOption("Accomplishments");

    const result = dialog.getByRole("option", { name: /Regional event-routing platform/i });
    await expect(result).toBeVisible();
    await result.click();

    await expect(page.getByRole("heading", { level: 1, name: "Regional event-routing platform" })).toBeVisible();
    await expect.poll(() => new URL(page.url()).searchParams.get("record")).toBe("preview-routing");
  });

  test("switches explorer views and autosaves the complete accomplishment workspace", async ({ page }) => {
    await openPreview(page, "&view=accomplishments");
    await expect(page.getByRole("heading", { level: 1, name: "Engineering knowledge base" })).toBeVisible();

    await selectSegment(page, "Explorer layout", "List");
    const routingRecord = page.getByRole("button", { name: /Open Regional event-routing platform at Northstar Cloud/i });
    await expect(routingRecord).toBeVisible();
    await routingRecord.click();

    const main = page.getByRole("main");
    for (const section of WORKSPACE_SECTIONS) {
      await expect(
        main.locator(`#corpus-section-${section.id}`).getByRole("button", { name: new RegExp(`^${section.label}(?:\\s|$)`, "i") }),
      ).toHaveCount(1);
    }

    const context = main.getByRole("textbox", { name: "Problem and context" });
    await context.fill("Northstar context refined in the corpus workspace.");
    await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible();
    await expect(page.getByText("Saved in preview", { exact: true })).toBeVisible({ timeout: 5_000 });

    await page.getByRole("button", { name: "Back to explorer" }).click();
    await page.getByRole("button", { name: /Open Regional event-routing platform at Northstar Cloud/i }).click();
    await expect(page.getByRole("textbox", { name: "Problem and context" })).toHaveValue(
      "Northstar context refined in the corpus workspace.",
    );
  });

  test("shows roadmap previews for gated generators", async ({ page }) => {
    await openPreview(page, "&view=builder");
    await expect(page.getByRole("heading", { level: 1, name: "Resume Generator" })).toBeVisible();
    await expect(page.getByTestId("coming-soon-preview")).toContainText("planned but not yet available");

    await openPreview(page, "&view=match");
    await expect(page.getByRole("heading", { level: 1, name: "Job Description Matching" })).toBeVisible();
    await expect(page.getByTestId("coming-soon-preview")).toContainText("planned but not yet available");
  });

  test("supports study, practice, mock, and rapid interview modes with persistent notes", async ({ page }) => {
    await openPreview(page, "&view=interview");
    await expect(page.getByRole("heading", { level: 1, name: "Defend the work, not a memorized script" })).toBeVisible();

    await selectSegment(page, "Preparation mode", "Practice");
    await expect(page.getByRole("region", { name: "Practice workspace" })).toBeVisible();

    await selectSegment(page, "Preparation mode", "Mock");
    const notes = page.getByRole("textbox", { name: "Session notes" });
    await notes.fill("Explain ordering guarantees before discussing failover.");
    await page.getByRole("button", { name: "Start timer" }).click();
    await expect(page.getByRole("button", { name: "Pause timer" })).toBeVisible();

    await page.reload();
    await selectSegment(page, "Preparation mode", "Mock");
    await expect(page.getByRole("textbox", { name: "Session notes" })).toHaveValue(
      "Explain ordering guarantees before discussing failover.",
    );
    await selectSegment(page, "Preparation mode", "Rapid review");
    await expect(page.getByRole("region", { name: "Rapid review workspace" })).toBeVisible();
  });

  test("fits the redesigned workspace at a 390px mobile viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openPreview(page);

    await expect(page.getByRole("heading", { level: 1, name: "Resume Corpus" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open CareerOS navigation" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Quick corpus navigation" })).toBeVisible();

    await page.getByRole("button", { name: "Open all corpus areas" }).click();
    const corpusNavigation = page.getByRole("dialog", { name: "Resume Corpus navigation" });
    await expect(corpusNavigation).toBeVisible();
    await corpusNavigation.getByRole("button", { name: "Close navigation" }).click();
    await expect(corpusNavigation).toBeHidden();
    await expect(page.getByRole("dialog", { name: "CareerOS navigation" })).toHaveCount(0);

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
