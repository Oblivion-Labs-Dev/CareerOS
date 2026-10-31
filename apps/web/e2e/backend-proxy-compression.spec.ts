import { expect, test } from "@playwright/test";

// The /api/backend proxy dropped the API's encoding and sent every JSON
// payload raw: 4.1 MB of insight rows and ~500 KB per jobs-list page. JSON is
// now gzipped on the way out; the SSE event stream must not be, because a gzip
// stream buffers and would hold live events back.
test("backend proxy gzips JSON but leaves the event stream alone @local", async ({ page }) => {
  const json = await page.request.get("/api/backend/application-assistant/autopilot/jobs?limit=5", {
    headers: { "accept-encoding": "gzip" },
  });
  expect(json.status()).toBe(200);
  expect(json.headers()["content-encoding"]).toBe("gzip");
  expect((await json.json()).jobs.length).toBeGreaterThan(0);

  await page.goto("/login");
  const sse = await page.evaluate(async () => {
    const controller = new AbortController();
    const response = await fetch("/api/backend/application-assistant/autopilot/events", { signal: controller.signal });
    const result = { type: response.headers.get("content-type"), encoding: response.headers.get("content-encoding") };
    controller.abort();
    return result;
  });
  expect(sse.type).toContain("text/event-stream");
  expect(sse.encoding).toBeNull();
});
