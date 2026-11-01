import { describe, expect, it } from "vitest";
import { ApiError, getAuthLoginUrl } from "../../lib/api";

describe("getAuthLoginUrl", () => {
  it("builds a login URL carrying the return_to query param", () => {
    const url = getAuthLoginUrl("/engagements/123");
    const parsed = new URL(url);
    expect(parsed.pathname.endsWith("/auth/login")).toBe(true);
    expect(parsed.searchParams.get("return_to")).toBe("/engagements/123");
  });

  it("URL-encodes a return_to value that itself carries query params", () => {
    const url = getAuthLoginUrl("/engagements/123?tab=evidence");
    const parsed = new URL(url);
    expect(parsed.searchParams.get("return_to")).toBe(
      "/engagements/123?tab=evidence",
    );
  });
});

describe("ApiError", () => {
  it("carries the HTTP status alongside the message", () => {
    const error = new ApiError("The operator service is unavailable.", 0);
    expect(error.message).toBe("The operator service is unavailable.");
    expect(error.status).toBe(0);
    expect(error).toBeInstanceOf(Error);
  });
});
