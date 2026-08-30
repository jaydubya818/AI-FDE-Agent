import path from "node:path";

import type { NextConfig } from "next";

const usesPlatformRuntime = process.env.VERCEL === "1";

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
