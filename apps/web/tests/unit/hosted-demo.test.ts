import { describe, expect, it } from "vitest";
import type { Engagement } from "../../lib/types";
import { hostedDemoRequest } from "../../lib/hosted-demo";

// hostedDemoRequest reads/writes its demo state through `window.localStorage`
// only when `window` is defined; in a plain Node test environment (no DOM)
// it falls back to a fresh, deterministic in-memory seed every call, which
// is what makes these fixtures usable without a browser.
describe("hostedDemoRequest", () => {
  it("seeds three deterministic demo engagements", async () => {
    const engagements = await hostedDemoRequest<Engagement[]>("/engagements");
    expect(engagements).toHaveLength(3);
    expect(engagements.map((item) => item.slug).sort()).toEqual([
      "acme-manufacturing",
      "beacon-logistics",
      "northstar-health",
    ]);
    expect(
      engagements.every((item) => item.data_classification === "synthetic"),
    ).toBe(true);
  });

  it("returns the fixed hosted-demo operator identity", async () => {
    const operator = await hostedDemoRequest<{
      id: string;
      display_name: string;
    }>("/auth/me");
    expect(operator.display_name).toBe("Hosted Demo FDE");
    expect(operator.id).toBe("00000000-0000-4000-8000-000000000001");
  });

  it("rejects an unknown engagement id rather than returning undefined", async () => {
    await expect(
      hostedDemoRequest("/engagements/does-not-exist"),
    ).rejects.toThrow("The synthetic engagement was not found.");
  });
});
