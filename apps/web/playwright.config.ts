import { defineConfig } from "@playwright/test";

const baseURL =
  process.env.AI_FDE_PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
const usesExternalServer =
  process.env.AI_FDE_PLAYWRIGHT_EXTERNAL_SERVER === "true";
const usesMockApi = process.env.AI_FDE_PLAYWRIGHT_MOCK_API === "true";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    colorScheme: "light",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: usesExternalServer
    ? undefined
    : {
        command: usesMockApi
          ? "NEXT_PUBLIC_AI_FDE_HOSTED_DEMO=false NEXT_PUBLIC_MISSION_CONTROL_URL=https://mission-control.example pnpm dev --hostname 127.0.0.1 --port 3001"
          : "pnpm --dir ../.. dev",
        reuseExistingServer: true,
        timeout: 120_000,
        url: baseURL,
      },
});
