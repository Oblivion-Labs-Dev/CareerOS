import { expect, test } from "@playwright/test";

/**
 * A card must be visibly a card, in both themes.
 *
 * This exists because of a specific mistake: the surfaces were moved from
 * "1px border on everything" to "elevation only". That is right for light
 * mode and wrong for dark, where the canvas is already near-black and a soft
 * shadow lands on it invisibly. The cards ended up the same colour as the page
 * with no boundary at all.
 *
 * So the rule this enforces is not "has a border" or "has a shadow" — it is
 * that a card is *separable from its background by some means*: a measurable
 * lightness difference, or a visible edge. Either satisfies it, which leaves
 * the design free to use borders in dark and shadows in light, as the better
 * implementations on the web do.
 */

/**
 * Firefox reports color-mix() results as `color(srgb r g b)` with 0-1 floats,
 * and tokens are authored as hex. A parser that only understood `rgb()`
 * silently returned null for both, which made every ratio compute as exactly
 * 1.000 — a number that looked like a finding but was just a parse failure.
 */
function parse(value: string): number[] | null {
  const v = value.trim();

  const srgb = v.match(/^color\(srgb\s+([^)]+)\)/);
  if (srgb) {
    const p = srgb[1].split(/[\s/]+/).filter(Boolean).map(parseFloat);
    if (p.length >= 3) return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1];
  }

  const rgb = v.match(/rgba?\(([^)]+)\)/);
  if (rgb) {
    const p = rgb[1].split(/[,\s/]+/).filter(Boolean).map(parseFloat);
    if (p.length >= 3) return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  }

  const hex = v.match(/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/);
  if (hex) {
    const h =
      hex[1].length === 3
        ? hex[1]
            .split("")
            .map((c) => c + c)
            .join("")
        : hex[1];
    return [
      parseInt(h.slice(0, 2), 16),
      parseInt(h.slice(2, 4), 16),
      parseInt(h.slice(4, 6), 16),
      1,
    ];
  }
  return null;
}

function lum([r, g, b]: number[]): number {
  const ch = (v: number) => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b);
}

/**
 * One row per surface that renders cards, because they are styled in separate
 * stylesheets and a pass on one says nothing about the others.
 */
const SURFACES: { path: string; name: string; card: string }[] = [
  { path: "/applications?tab=applications", name: "autopilot", card: "article[data-job-id]" },
  { path: "/dashboard", name: "dashboard", card: "main article, main [class*='matchCard']" },
  { path: "/applications?tab=inbox", name: "inbox", card: "main [class*='inbox']" },
  { path: "/applications?tab=pipeline", name: "pipeline", card: "main [class*='opportunity'], main [class*='column']" },
  // The quest board renders inside the dashboard, not a route of its own.
  // button.quest is the card; div.quests (the grid wrapper) also matches a
  // loose [class*='quest'] substring and is transparent, so this has to name
  // the element precisely rather than substring-match.
  { path: "/dashboard", name: "progress", card: "main button[class*='quest']" },
];

for (const theme of ["dark", "light"] as const) {
for (const surface of SURFACES) {
  test(`${surface.name} cards are separable from the page in ${theme} mode @separation`, async ({ page }) => {
    test.setTimeout(150_000);
    await page.emulateMedia({ colorScheme: theme });
    await page.addInitScript((value) => {
      try {
        window.localStorage.setItem("theme", value);
      } catch {
        /* storage blocked */
      }
    }, theme);
    await page.goto(surface.path);
    await expect
      .poll(() => page.evaluate(() => document.documentElement.getAttribute("data-theme")), {
        timeout: 15_000,
      })
      .toBe(theme);

    const card = page.locator(surface.card).first();
    // Wait *before* deciding there is nothing here: these pages fetch after
    // mount, so an immediate count() is always zero and every surface skipped
    // itself — which reads as a pass and checks nothing.
    const appeared = await card
      .waitFor({ state: "visible", timeout: 45_000 })
      .then(() => true)
      .catch(() => false);
    if (!appeared) {
      // A genuinely empty surface cannot be judged, and failing here would
      // report an empty queue as a styling bug.
      test.skip(true, `no cards rendered on ${surface.path}`);
      return;
    }

    const probe = await card.evaluate((el) => {
      const style = getComputedStyle(el);
      // Nearest painted ancestor background — what the card actually sits on.
      let node: HTMLElement | null = el.parentElement;
      let behind = "";
      while (node) {
        const bg = getComputedStyle(node).backgroundColor;
        if (bg && !bg.includes("rgba(0, 0, 0, 0)")) {
          behind = bg;
          break;
        }
        node = node.parentElement;
      }
      if (!behind) {
        behind =
          getComputedStyle(document.documentElement).getPropertyValue("--ref-bg").trim() ||
          getComputedStyle(document.body).backgroundColor;
      }
      return {
        card: style.backgroundColor,
        behind,
        borderTopWidth: style.borderTopWidth,
        borderLeftWidth: style.borderLeftWidth,
        borderLeftColor: style.borderLeftColor,
        boxShadow: style.boxShadow,
      };
    });

    const cardRgb = parse(probe.card);
    const behindRgb = parse(probe.behind);

    // How different is the card's own fill from what it sits on?
    let ratio = 1;
    if (cardRgb && behindRgb) {
      const [a, b] = [lum(cardRgb), lum(behindRgb)].sort((x, y) => y - x);
      ratio = (a + 0.05) / (b + 0.05);
    }

    // A visible edge counts too: a side border with real width and real alpha.
    const edge = parse(probe.borderLeftColor);
    const hasEdge =
      parseFloat(probe.borderLeftWidth) > 0 && !!edge && edge[3] > 0.04;

    // Kept for eyeballing the result; the assertion below is what gates it.
    await page.screenshot({ path: `test-results/cards-${surface.name}-${theme}.png`, fullPage: false });

    const separated = ratio >= 1.12 || hasEdge;

    /**
     * Form controls must belong to the theme.
     *
     * `.main :is(select, input, textarea)` painted a hardcoded dark-navy
     * gradient with no light-mode counterpart, so every control in the app was
     * a black box on a white page — and because that selector outranks a
     * component's own class, fixing it locally did nothing. Asserted by
     * lightness against the page rather than by colour, so it holds in both
     * themes: a control must not be wildly darker than its surroundings in
     * light mode, nor wildly lighter in dark.
     */
    const control = page.locator("main select, main input[type='text'], main textarea").first();
    if (await control.count()) {
      const fill = await control.evaluate((el) => getComputedStyle(el).backgroundColor);
      const fillRgb = parse(fill);
      if (fillRgb && fillRgb[3] > 0 && behindRgb) {
        const controlLum = lum(fillRgb);
        const pageLum = lum(behindRgb);
        const wrongWay =
          theme === "light" ? controlLum < pageLum - 0.3 : controlLum > pageLum + 0.3;
        expect(
          wrongWay,
          `a form control must not be inverted against the ${theme} page.\n` +
            `  control ${fill} (luminance ${controlLum.toFixed(3)})\n` +
            `  page    ${probe.behind} (luminance ${pageLum.toFixed(3)})`,
        ).toBe(false);
      }
    }

    expect(
      separated,
      `a card must be distinguishable from the page behind it.\n` +
        `  card       ${probe.card}\n` +
        `  behind     ${probe.behind}\n` +
        `  lightness  ${ratio.toFixed(3)}x (needs >= 1.12, or a visible edge)\n` +
        `  border     ${probe.borderLeftWidth} ${probe.borderLeftColor}\n` +
        `  shadow     ${probe.boxShadow}`,
    ).toBe(true);
  });
}
}
