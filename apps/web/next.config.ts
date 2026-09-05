import path from "node:path";

import type { NextConfig } from "next";

const usesPlatformRuntime = process.env.VERCEL === "1";
const hostedDemoEnabled = process.env.NEXT_PUBLIC_AI_FDE_HOSTED_DEMO === "true";
const hostedDemoFallbackUrl = "https://api.ai-fde.invalid/api";
const configuredApiUrl =
  process.env.NEXT_PUBLIC_AI_FDE_API_URL ?? "http://localhost:8000/api";

function apiConnectSource(): string | null {
  if (configuredApiUrl.startsWith("/")) return null;
  const url = new URL(configuredApiUrl);
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error(
      "NEXT_PUBLIC_AI_FDE_API_URL must use HTTP, HTTPS, or a relative path.",
    );
  }
  return url.origin;
}

const connectSources = new Set(["'self'"]);
const configuredApiOrigin = apiConnectSource();
if (configuredApiOrigin) connectSources.add(configuredApiOrigin);

const scriptSources = ["'self'", "'unsafe-inline'"];
if (process.env.NODE_ENV !== "production") scriptSources.push("'unsafe-eval'");

const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src ${scriptSources.join(" ")}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src ${[...connectSources].join(" ")}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-XSS-Protection", value: "0" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=()",
  },
  ...(process.env.NODE_ENV === "production"
    ? [
        {
          key: "Strict-Transport-Security",
          value: "max-age=31536000; includeSubDomains",
        },
      ]
    : []),
];

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
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
  ...(usesPlatformRuntime
    ? {}
    : {
        output: "standalone",
        outputFileTracingRoot: path.join(__dirname, "../.."),
      }),
};

export default nextConfig;
