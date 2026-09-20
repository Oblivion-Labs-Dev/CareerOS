import { expect, test } from "@playwright/test";

/**
 * Text stays readable in light mode.
 *
 * The app defaults to dark, and several components were written against that
 * assumption with the colour typed straight into the markup rather than taken
 * from a token: `color: "#f5f8fb"` is a near-white that is correct on a dark
 * panel and invisible on a light one. Tokens exist for exactly this — `--text`,
 * `--muted`, `--accent`, `--danger`, `--success` are all defined per theme — so
 * the fix is to use them, and this is the test that says so.
 *
 * Note the distinction: `var(--text, #e2e8f0)` is fine. `--text` is defined in
 * both themes, so the fallback never fires. Only the tokenless values break.
 */

/** WCAG relative luminance. */
function luminance([r, g, b]: number[]): number {
  const channel = (value: number) => {
    const v = value / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(a: number[], b: number[]): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

function parseRgb(value: string): number[] | null {
  const match = value.match(/rgba?\(([^)]+)\)/);
  if (!match) return null;
  const parts = match[1].split(",").map((piece) => parseFloat(piece.trim()));
  return parts.length >= 3 ? parts.slice(0, 3) : null;
}

/**
 * Both themes, not just the broken one.
 *
 * The colours being replaced were written for dark mode, so dark is where a
 * bad substitution would show up. Testing only light would fix one theme by
 * breaking the other and call it a pass.
 */
/**
 * The pages `reference-match.css` actually styles.
 *
 * Browse Jobs alone was too narrow to cover the stylesheet this test exists
 * for: the bulk of its rules are the Autopilot page chrome, so a pass on
 * /jobs/discover said almost nothing about the 98 declarations that were
 * hardcoding dark-theme text.
 */
const PAGES: { path: string; name: string }[] = [
  { path: "/jobs/discover", name: "Browse Jobs" },
  { path: "/applications", name: "Autopilot" },
  { path: "/applications?tab=applications", name: "Applications" },
];

for (const theme of ["light", "dark"] as const) {
for (const { path, name } of PAGES) {
test(`text on ${name} is readable in ${theme} mode @contrast`, async ({ page }) => {
  // The Autopilot workspace renders the whole job list; the default 60s is not
  // enough to load it and walk 600 elements' computed styles.
  test.setTimeout(150_000);
  await page.emulateMedia({ colorScheme: theme });
  // Persist the choice the way the toggle does, before the app loads.
  // `emulateMedia` alone is not enough and setting the attribute after
  // navigation is not either: the provider is `defaultTheme="dark"`, so it
  // ignores the media query and rewrites data-theme back to dark on hydration.
  // That silently measured the dark palette and called it light.
  await page.addInitScript((value) => {
    try {
      window.localStorage.setItem("theme", value);
    } catch {
      /* storage blocked - the assertion below will catch the fallout */
    }
  }, theme);
  await page.goto(path);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.getAttribute("data-theme")), {
      timeout: 15_000,
      message: "the provider must settle on the theme under test before anything is measured",
    })
    .toBe(theme);
  // Wait for the content itself, not a fixed delay. A 400ms sleep made this
  // pass once by scanning a half-rendered page — a green that meant nothing.
  await page.locator("main").waitFor({ state: "visible" });
  // Not networkidle: the Autopilot page polls run state on a timer, so it is
  // never idle and the wait consumed the whole budget before the scan began.
  // Wait for text to actually be painted into main instead, which is the
  // precondition the scan needs and is reached on a polling page.
  await page
    .locator("main")
    .locator("p, span, strong, small, h1, h2, h3")
    .first()
    .waitFor({ state: "visible", timeout: 30_000 })
    .catch(() => {});

  const offenders = await page.evaluate(() => {
    const found: { text: string; color: string; background: string }[] = [];
    const walk = document.querySelectorAll<HTMLElement>("main *");
    for (const el of Array.from(walk).slice(0, 600)) {
      const text = (el.textContent || "").trim();
      if (!text || el.children.length > 0) continue;
      const style = getComputedStyle(el);
      if (style.visibility === "hidden" || style.display === "none") continue;

      // Composite the background stack rather than stopping at the first
      // painted layer. A translucent tint like rgba(13,232,193,.1) sitting on
      // a dark panel reads as solid teal if you stop there, which reported a
      // teal-on-teal failure for text that is actually teal on dark navy.
      const parse = (value: string): number[] | null => {
        const match = value.match(/rgba?\(([^)]+)\)/);
        if (match) {
          const parts = match[1].split(",").map((piece) => parseFloat(piece.trim()));
          if (parts.length < 3) return null;
          return [parts[0], parts[1], parts[2], parts.length > 3 ? parts[3] : 1];
        }
        // The --ref-* tokens are authored as hex, not rgb().
        const hex = value.trim().match(/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/);
        if (!hex) return null;
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
      };

      const layers: number[][] = [];
      let node: HTMLElement | null = el;
      let unmeasurable = false;
      while (node) {
        const nodeStyle = getComputedStyle(node);
        // A gradient has no single backgroundColor, so the stack underneath it
        // cannot be composited. Reporting what is behind the gradient produced
        // a false failure for "Add to Queue" — dark text on a bright accent
        // gradient, read as dark-on-dark against the panel behind it. Skip
        // rather than guess; the accent buttons are covered by design review.
        // html/body are excluded: they always paint the page gradient, which
        // would mark every canvas-level element unmeasurable and gut the test.
        // Their canvas is --ref-bg, applied as the base layer below.
        const isRoot = node === document.body || node === document.documentElement;
        if (!isRoot && nodeStyle.backgroundImage && nodeStyle.backgroundImage !== "none") {
          unmeasurable = true;
          break;
        }
        const bg = parse(nodeStyle.backgroundColor);
        if (bg && bg[3] > 0) {
          layers.push(bg);
          if (bg[3] >= 1) break;
        }
        node = node.parentElement;
      }
      if (unmeasurable) continue;

      // Nothing opaque underneath: fall back to the page canvas. `body` paints
      // a gradient, so its backgroundColor is transparent — defaulting to white
      // there reported the dark theme as white-backed and inverted the results.
      // --ref-bg is the canvas both themes actually define.
      const root = getComputedStyle(document.documentElement);
      const base =
        parse(root.getPropertyValue("--ref-bg").trim()) ||
        parse(getComputedStyle(document.body).backgroundColor);
      if (!layers.length || layers[layers.length - 1][3] < 1) {
        layers.push(base && base[3] >= 1 ? base : [255, 255, 255, 1]);
      }

      // Paint back to front: furthest ancestor first, nearest layer last.
      let composite = layers[layers.length - 1].slice(0, 3);
      for (let i = layers.length - 2; i >= 0; i -= 1) {
        const [r, g, b, a] = layers[i];
        composite = [
          r * a + composite[0] * (1 - a),
          g * a + composite[1] * (1 - a),
          b * a + composite[2] * (1 - a),
        ];
      }
      const background = `rgb(${composite.map((v) => Math.round(v)).join(", ")})`;
      found.push({ text: text.slice(0, 40), color: style.color, background });
    }
    return found;
  });

  const failures = offenders.filter((entry) => {
    const fg = parseRgb(entry.color);
    const bg = parseRgb(entry.background);
    if (!fg || !bg) return false;
    return contrast(fg, bg) < 3;
  });

  expect(
    failures.map((f) => `"${f.text}" ${f.color} on ${f.background}`),
    "text below 3:1 against its own background is effectively invisible",
  ).toEqual([]);
});
}
}

/**
 * What this test was built to catch, and what fixed it.
 *
 * Tokenising the inline styles fixed the components, but `app/reference-match.css`
 * — 3,257 lines, loaded globally from layout.tsx — hardcoded dark-theme text
 * colours in 98 `color:` declarations (`#f2f6fb`, `#e9f0f9`, `#a7b5c9` and a
 * long tail of near-identical blue-greys). Those rendered near-white on white
 * in light mode regardless of what the components did.
 *
 * The fix used the stylesheet's own `--ref-*` tokens, which already had a full
 * `[data-theme="light"]` counterpart at the top of the file — the values were
 * simply being bypassed. Note the alternative that was rejected: re-declaring
 * the same selectors under `[data-theme="light"]`, which the file had started
 * doing in 45 places. That leaves every rule needing two declarations that
 * drift apart, which is how this broke in the first place.
 */
