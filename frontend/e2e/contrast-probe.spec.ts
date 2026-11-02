import { test } from "@playwright/test";

test.skip(process.env.VISUAL_QA !== "1", "diagnostic probe");

test("light theme computed styles", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("theme", "light"));
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);

  const report = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    const tokens = ["--card", "--bg", "--text", "--muted", "--border", "--bg-elevated"];
    const sel = [
      ".career-workspace-chip--active",
      ".career-workspace-chip--active strong",
      '[class*="todayCard"]',
      '[class*="todayTitle"]',
      '[class*="todayCopy"]',
    ];
    return {
      theme: document.documentElement.getAttribute("data-theme"),
      tokens: Object.fromEntries(tokens.map((t) => [t, root.getPropertyValue(t).trim()])),
      nodes: sel.map((s) => {
        const el = document.querySelector(s) as HTMLElement | null;
        if (!el) return { sel: s, missing: true };
        const cs = getComputedStyle(el);
        return { sel: s, color: cs.color, bg: cs.backgroundColor, bgImage: cs.backgroundImage.slice(0, 60) };
      }),
    };
  });
  console.log(JSON.stringify(report, null, 2));
});
