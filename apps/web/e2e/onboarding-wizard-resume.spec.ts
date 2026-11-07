import { expect, test, type Page } from "@playwright/test";

/**
 * The setup wizard a new account sees: required questions are marked, a
 * resume upload fills the blank answers it can read, keeps what the user
 * already typed, and a resume that cannot be read says so instead of failing
 * silently. Every API call is a local fixture; the parser itself is covered by
 * apps/api/tests/test_resume_formats.py.
 */
const QUESTIONS = {
  sections: [
    {
      title: "Basics",
      questions: [
        { key: "resume", label: "Resume", type: "resume", required: true },
        { key: "fullName", label: "Full name", type: "text", required: true },
        { key: "email", label: "Email", type: "text", required: true },
        { key: "phone", label: "Phone", type: "text", required: false },
      ],
    },
  ],
  currentValues: { email: "typed.by.user@example.com" },
};

async function openWizard(page: Page, baseURL: string, parse: "ok" | "fail") {
  const posted: unknown[] = [];
  await page.context().addCookies([{ name: "co_session", value: "isolated-ui-fixture", url: baseURL }]);
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith("/auth/status")) return route.fulfill({ json: { authRequired: false } });
    if (path.endsWith("/api/onboarding/questions")) return route.fulfill({ json: QUESTIONS });
    if (path.endsWith("/documents/resume") && route.request().method() === "POST") {
      posted.push(route.request().postDataJSON());
      return route.fulfill({ json: { success: true, resume: { name: "jordan-lee.txt" } } });
    }
    if (path.endsWith("/api/parse-resume")) {
      if (parse === "fail") {
        return route.fulfill({ status: 422, json: { detail: "This PDF looks like a scan with no text. Upload a DOCX or a text PDF." } });
      }
      return route.fulfill({
        json: {
          profile: { fullName: "Jordan Lee", email: "jordan.lee@example.com", phone: "(512) 555-0199" },
          extracted: { fullName: "Jordan Lee", email: "jordan.lee@example.com", phone: "(512) 555-0199" },
        },
      });
    }
    return route.fulfill({ json: { success: true, state: { status: "IDLE", workers: [] }, jobs: [], items: [], events: [], settings: {}, profile: {}, preferences: {}, total: 0, hasMore: false, statusCounts: {} } });
  });
  await page.goto("/profile?onboard=1");
  await expect(page.getByRole("dialog")).toBeVisible();
  return posted;
}

const RESUME = { name: "jordan-lee.txt", mimeType: "text/plain", buffer: Buffer.from("Jordan Lee\njordan.lee@example.com\n(512) 555-0199\n") };

test("required questions are marked and a resume fills only the blank answers", async ({ page, baseURL }) => {
  const posted = await openWizard(page, baseURL!, "ok");
  const dialog = page.getByRole("dialog");
  for (const label of ["Resume", "Full name", "Email"]) {
    await expect(dialog.locator("label", { hasText: label }).first()).toContainText("*");
  }
  await expect(dialog.locator("label", { hasText: "Phone" })).not.toContainText("*");

  await dialog.getByLabel("Resume").setInputFiles(RESUME);
  await expect(dialog.getByRole("status")).toContainText("Read from your resume: fullName, email, phone");
  await expect(dialog.getByPlaceholder("Full name")).toHaveValue("Jordan Lee");
  await expect(dialog.getByPlaceholder("Phone")).toHaveValue("(512) 555-0199");
  // An answer the user already gave is never overwritten by the parse.
  await expect(dialog.getByPlaceholder("Email")).toHaveValue("typed.by.user@example.com");
  expect(posted).toHaveLength(1);
  expect(JSON.stringify(posted[0])).toContain("jordan-lee.txt");
});

test("a resume that cannot be read shows the reason and leaves the answers blank", async ({ page, baseURL }) => {
  await openWizard(page, baseURL!, "fail");
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Resume").setInputFiles(RESUME);
  await expect(dialog.getByRole("alert")).toContainText("scan");
  await expect(dialog.getByPlaceholder("Full name")).toHaveValue("");
});

test("in light mode the wizard's buttons, titles and answers stay readable", async ({ page, baseURL }) => {
  await page.addInitScript(() => localStorage.setItem("theme", "light"));
  await openWizard(page, baseURL!, "ok");
  const dialog = page.getByRole("dialog");
  await dialog.getByPlaceholder("Full name").fill("Jordan Lee");
  const luminance = (rgb: string) => {
    const [r, g, b] = rgb.match(/\d+(\.\d+)?/g)!.map(Number);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  for (const target of [dialog.getByPlaceholder("Full name"), dialog.getByRole("heading", { name: "Basics" })]) {
    expect(luminance(await target.evaluate((el) => getComputedStyle(el).color))).toBeLessThan(110);
  }
  // Plain buttons inside .main kept a dark navy fill in light mode, so the
  // close button's dark label was invisible.
  const close = dialog.getByRole("button", { name: "Close setup wizard" });
  const style = await close.evaluate((el) => {
    const s = getComputedStyle(el);
    return { color: s.color, background: s.backgroundColor, image: s.backgroundImage };
  });
  expect(style.image).toBe("none");
  expect(luminance(style.background)).toBeGreaterThan(200);
  expect(luminance(style.color)).toBeLessThan(110);
});
