import { expect, test } from "@playwright/test";

test.describe("CareerOS navigation polish", () => {
  test("command palette supports keyboard navigation and restores focus", async ({ page }) => {
    await page.goto("/dashboard");

    const trigger = page.locator(".app-topbar-search");
    await page.keyboard.press("Control+K");

    const dialog = page.getByRole("dialog", { name: "Search CareerOS" });
    const combobox = page.getByRole("combobox", { name: "Search CareerOS" });
    await expect(dialog).toBeVisible();
    await expect(combobox).toBeFocused();
    await expect(combobox).toHaveAttribute("aria-activedescendant", "global-command-option-0");

    await page.keyboard.press("ArrowDown");
    await expect(combobox).toHaveAttribute("aria-activedescendant", "global-command-option-1");

    await page.getByRole("option").last().focus();
    await page.keyboard.press("Tab");
    await expect(combobox).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("mobile navigation is a focus-managed dialog", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/dashboard");

    const openButton = page.getByRole("button", { name: "Open CareerOS navigation" });
    const sidebar = page.locator("#careeros-primary-navigation");
    await expect(openButton).toBeVisible();
    await expect(sidebar).toHaveAttribute("aria-hidden", "true");

    await openButton.click();
    await expect(sidebar).toHaveAttribute("role", "dialog");
    await expect(sidebar).toHaveAttribute("aria-modal", "true");
    await expect(page.getByRole("button", { name: "Close CareerOS navigation" }).last()).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(sidebar).toHaveAttribute("aria-hidden", "true");
    await expect(openButton).toBeFocused();
  });

  test("reduced-motion mode preserves readable, overflow-free content", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");

    const animatedHero = page.locator(".landing-fade-in").first();
    await expect(animatedHero).toBeVisible();
    const motion = await animatedHero.evaluate((element) => {
      const styles = getComputedStyle(element);
      return { animationName: styles.animationName, opacity: styles.opacity };
    });
    expect(motion.animationName).toBe("none");
    expect(motion.opacity).toBe("1");

    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(hasHorizontalOverflow).toBe(false);
  });
});
