import { expect, test, type Page } from "@playwright/test";

type Profile = {
  company: string;
  workflow: string;
  accepted: string[];
  rejected: string[];
  contradiction?: string;
};

const profiles: Profile[] = [
  {
    company: "Acme Manufacturing",
    workflow: "Accounts Payable",
    accepted: [
      "Exception: Strategic vendors with an approved annual contract may be approved by Controller.",
      "Sarah Jones owns Accounts Payable.",
      "Invoices over $50,000 require CFO approval.",
      "Accounts Payable uses NetSuite.",
    ],
    rejected: [
      "Sarah Jones is identified as a person.",
      "Invoice approval is identified as a process.",
    ],
    contradiction:
      "Approval evidence names both CFO and Controller. Confirm whether this is a conflict, exception, or change over time.",
  },
  {
    company: "Northstar Health",
    workflow: "Employee Access Onboarding",
    accepted: [
      "Priya Shah owns Employee Access Onboarding.",
      "Employee Access Onboarding uses Workday.",
      "Identity record creation precedes Account provisioning.",
      "Requests for privileged systems require Security approval.",
      "People Operations hands off to IT Service Desk.",
      "Account Provisioning uses Okta.",
    ],
    rejected: [
      "Employee Access Onboarding is identified as a process.",
      "Priya Shah is identified as a person.",
      "Security is identified as a role.",
      "Workday is identified as a system.",
      "People Operations is identified as a role.",
      "IT Service Desk is identified as a role.",
      "Okta is identified as a system.",
    ],
  },
  {
    company: "Beacon Logistics",
    workflow: "Customer Support Triage",
    accepted: [
      "Jordan Lee owns Customer Support Triage.",
      "Customer Support Triage uses Zendesk.",
      "Classify inbound request precedes Route standard request.",
      "Customer Support Triage is governed by Service Response Policy.",
    ],
    rejected: [
      "Customer Support Triage is identified as a process.",
      "Jordan Lee is identified as a person.",
      "Zendesk is identified as a system.",
    ],
  },
];

async function reviewClaim(
  page: Page,
  summary: string,
  decision: "Accept" | "Reject",
) {
  const heading = page.getByRole("heading", { level: 3, name: summary });
  const card = page.getByRole("article").filter({ has: heading });
  await expect(card.getByText("Exact source evidence")).toBeVisible();
  await card
    .getByRole("textbox", { name: "Decision note for: " + summary })
    .fill(
      decision === "Accept"
        ? "Verified against exact synthetic evidence for the internal alpha."
        : "Entity-only context is not required in the actionable operating model.",
    );
  await card.getByRole("button", { name: decision }).click();
  await expect(heading).toBeHidden();
}

async function completeProfile(page: Page, profile: Profile) {
  await page.goto("/");
  await expect(page.getByText("Loading engagements…")).toBeHidden();
  await page
    .getByRole("link", {
      name: new RegExp(profile.company + " " + profile.workflow),
    })
    .first()
    .click();

  await expect(
    page.getByRole("heading", { level: 1, name: profile.company }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { level: 2, name: "Candidate claim review" }),
  ).toBeVisible({ timeout: 45_000 });

  for (const summary of profile.accepted) {
    await reviewClaim(page, summary, "Accept");
  }
  for (const summary of profile.rejected) {
    await reviewClaim(page, summary, "Reject");
  }
  await expect(page.getByText("Review queue is clear.")).toBeVisible();

  if (profile.contradiction) {
    await page
      .getByRole("textbox", {
        name: "Operator reason for contradiction: " + profile.contradiction,
      })
      .fill(
        "The lower approval path is a documented exception to the standard rule.",
      );
    await page.getByRole("button", { name: "Resolve blocker" }).click();
    await expect(page.getByText("Resolved contradiction")).toBeVisible();
  }

  await page
    .getByRole("button", { name: "Construct current workflow" })
    .click();
  await page.getByRole("button", { name: "Approve current workflow" }).click();
  await expect(
    page.getByRole("button", { name: "Approve current workflow" }),
  ).toBeHidden();

  await page.getByRole("button", { name: "Design target workflow" }).click();
  await page.getByRole("button", { name: "Approve target workflow" }).click();
  await expect(
    page.getByRole("button", { name: "Approve target workflow" }),
  ).toBeHidden();

  await page.getByRole("button", { name: "Calculate case" }).click();
  await expect(page.getByText("Low scenario", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Approve economic case" }).click();
  await expect(
    page.getByRole("button", { name: "Approve economic case" }),
  ).toBeHidden();

  await page.getByRole("button", { name: "Generate artifact packet" }).click();
  await expect(page.getByRole("tab")).toHaveCount(7);
  await expect(
    page.getByText("Packet complete", { exact: true }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Record assessment" }).click();
  await expect(page.getByText(/Assessment saved/)).toBeVisible();
  await expect(
    page.getByText("Factory Engineer · operator · completed", { exact: true }),
  ).toBeVisible();
}

test("three synthetic workflows complete an internal alpha rehearsal", async ({
  page,
}, testInfo) => {
  test.setTimeout(300_000);
  await page.setViewportSize({ width: 1440, height: 960 });

  const consoleErrors: string[] = [];
  const apiRequests: string[] = [];
  const failedApiResponses: string[] = [];
  const failedApiRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/") && response.status() >= 400) {
      failedApiResponses.push(String(response.status()) + " " + response.url());
    }
  });
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiRequests.push(request.url());
  });
  page.on("requestfailed", (request) => {
    if (request.url().includes("/api/")) {
      failedApiRequests.push(
        (request.failure()?.errorText ?? "request failed") +
          " " +
          request.url(),
      );
    }
  });

  for (const profile of profiles) {
    await completeProfile(page, profile);
  }

  await page.getByRole("link", { name: "Factory Engineer home" }).click();
  await expect(
    page.getByRole("heading", {
      level: 2,
      name: "Delivery proof before production claims.",
    }),
  ).toBeVisible();
  await expect(page.getByText("3/3", { exact: true })).toBeVisible();
  await expect(
    page.getByText(/Factory Engineer completed operator cohort: 3\/3/),
  ).toBeVisible();
  await expect(page.getByText(/Conventional baseline: 0\/3/)).toBeVisible();
  await expect(
    page.getByText(/Collect at least three completed operator assessments/),
  ).toBeVisible();

  const screenshotPath =
    process.env.AI_FDE_ALPHA_SCREENSHOT ??
    testInfo.outputPath("internal-alpha-scorecard.png");
  await page.screenshot({ fullPage: true, path: screenshotPath });

  expect(apiRequests, "hosted demo API requests").toEqual([]);
  expect(failedApiResponses, "Factory Engineer API responses").toEqual([]);
  expect(failedApiRequests, "Factory Engineer API request failures").toEqual(
    [],
  );
  expect(consoleErrors, "browser console errors").toEqual([]);
});
