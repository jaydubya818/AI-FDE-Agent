import path from "node:path";

import type { NextConfig } from "next";

const usesPlatformRuntime = process.env.VERCEL === "1";
const hostedDemoEnabled = process.env.NEXT_PUBLIC_AI_FDE_HOSTED_DEMO === "true";
const hostedDemoFallbackUrl = "https://api.ai-fde.invalid/api";

if (
  usesPlatformRuntime &&
  (!hostedDemoEnabled ||
    process.env.NEXT_PUBLIC_AI_FDE_API_URL !== hostedDemoFallbackUrl)
) {
  throw new Error(
    "Vercel is reserved for the browser-local Factory Engineer demo. Set " +
      "NEXT_PUBLIC_AI_FDE_HOSTED_DEMO=true and " +
      `NEXT_PUBLIC_AI_FDE_API_URL=${hostedDemoFallbackUrl} before building.`,
  );
}

const nextConfig: NextConfig = {
  poweredByHeader: false,
  ...(usesPlatformRuntime
    ? {}
    : {
        output: "standalone",
        outputFileTracingRoot: path.join(__dirname, "../.."),
      }),
};

export default nextConfig;
