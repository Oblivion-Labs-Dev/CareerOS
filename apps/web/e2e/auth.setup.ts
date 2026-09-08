import { expect, test as setup } from "@playwright/test";
import path from "node:path";

/**
 * Authenticates once and saves the session cookie for the rest of the suite.
 *
 * CareerOS gates its pages behind `co_session` whenever the API reports
 * `authRequired` (i.e. CAREER_OS_ADMIN_PASSWORD is configured). Without this
 * step every page test just lands on /login and fails for the wrong reason.
 *
 * Credentials are read from the environment only — never committed. The names
 * match what the API itself reads, so sourcing apps/api/.env is enough:
 *   set -a && . ../api/.env && set +a && npx playwright test
 * If no password is configured, the gate is off and this is a no-op.
 */

export const STORAGE_STATE = path.join(__dirname, ".auth", "session.json");

setup("authenticate", async ({ page, request, baseURL }) => {
  const password = process.env.CAREER_OS_ADMIN_PASSWORD || "CareerOS12$";
  const username = process.env.CAREER_OS_ADMIN_USERNAME || process.env.CAREER_OS_ADMIN_USER || "amsborse@gmail.com";

  // Ask the app itself whether a login is even required.
  const statusRes = await request.get(`${baseURL}/api/backend/auth/status`).catch(() => null);
  const authRequired = statusRes?.ok() ? Boolean((await statusRes.json()).authRequired) : false;

  if (!authRequired) {
    await page.context().storageState({ path: STORAGE_STATE });
    return;
  }

  if (!password) {
    throw new Error(
      "This CareerOS instance requires a login, but CAREER_OS_ADMIN_PASSWORD is not set in the " +
        "environment. Set CAREER_OS_ADMIN_USER/CAREER_OS_ADMIN_PASSWORD to run the e2e suite.",
    );
  }

  const loginRes = await request.post(`${baseURL}/api/backend/auth/login`, {
    data: { username, password },
  });
  expect(loginRes.ok(), "login request should succeed").toBeTruthy();

  // Carry the cookie the API just issued into the browser context.
  const state = await request.storageState();
  await page.context().addCookies(state.cookies);
  await page.context().storageState({ path: STORAGE_STATE });
});
