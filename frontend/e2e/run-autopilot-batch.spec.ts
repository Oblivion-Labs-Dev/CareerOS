import { test } from "@playwright/test";

// Kept as a discoverable pointer for existing scripts. The old batch runner
// could pass without submitting anything and could launch concurrent work.
test.skip("Use run-single-ui-applications.spec.ts with explicit approved job IDs", () => {});
