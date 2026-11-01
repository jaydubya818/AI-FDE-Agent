import { defineConfig } from "vitest/config";

// Unit tests only. The Playwright specs under tests/e2e/ need a browser
// install and a running API, which is why apps/web had no runner that
// executes during a normal (non-e2e) check cycle -- see
// docs/NIGHTLY-BACKLOG.md "The JavaScript half has no unit test runner".
export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/unit/**/*.test.ts"],
  },
});
