import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const routes = [
  { name: "landing page", path: "/" },
  { name: "corpus overview", path: "/resume-corpus?preview=1" },
  { name: "corpus accomplishments", path: "/resume-corpus?preview=1&view=accomplishments" },
  { name: "corpus metrics", path: "/resume-corpus?preview=1&view=metrics" },
  { name: "corpus evidence", path: "/resume-corpus?preview=1&view=evidence" },
  { name: "corpus interview", path: "/resume-corpus?preview=1&view=interview" },
  { name: "corpus settings", path: "/resume-corpus?preview=1&view=settings" },
] as const;

test.describe("Accessibility @a11y", () => {
  for (const route of routes) {
    test(`${route.name} has no automated WCAG A/AA violations`, async ({ page }) => {
      await page.goto(route.path);
      await expect(page.locator("main").first()).toBeVisible();

      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const summary = results.violations
        .map((violation) => violation.id + ": " + violation.nodes.length + " affected node(s)")
        .join("\n");

      expect(results.violations, summary).toEqual([]);
    });
  }
});
