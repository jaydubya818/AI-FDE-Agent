import { expect, test, type Page } from "@playwright/test";

const acceptedClaims = [
  "Exception: Strategic vendors with an approved annual contract may be approved by Controller.",
  "Sarah Jones owns Accounts Payable.",
  "Invoices over $50,000 require CFO approval.",
  "Accounts Payable uses NetSuite.",
];

const rejectedClaims = [
  "Sarah Jones is identified as a person.",
  "Invoice approval is identified as a process.",
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
    .getByRole("textbox", { name: `Decision note for: ${summary}` })
    .fill(
      decision === "Accept"
        ? "Verified against exact synthetic evidence for the end-to-end rehearsal."
        : "Redundant entity-only claim; the material relationship remains separately reviewed.",
    );
  await card.getByRole("button", { name: decision }).click();
  await expect(heading).toBeHidden();
}

test("synthetic Acme reaches an approved implementation packet", async ({
  page,
}, testInfo) => {
  test.setTimeout(150_000);
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
      failedApiResponses.push(`${response.status()} ${response.url()}`);
    }
  });
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiRequests.push(request.url());
  });
  page.on("requestfailed", (request) => {
    if (request.url().includes("/api/")) {
      failedApiRequests.push(
        `${request.failure()?.errorText ?? "request failed"} ${request.url()}`,
      );
    }
  });

  await page.goto("/");
  await expect(page.getByText("Checking operator session")).toBeHidden();
  await expect(page.getByText("Loading engagements…")).toBeHidden();
  await expect(page).toHaveTitle("Factory Engineer · FDLC");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Turn enterprise reality into a deployable software factory.",
    }),
  ).toBeVisible();
  const ecosystemNavigation = page.getByRole("navigation", {
    name: "FDLC ecosystem",
  });
  await expect(
    ecosystemNavigation.getByRole("link", { name: /Framework/ }),
  ).toHaveAttribute("href", "https://fdlc.ai/framework");
  await expect(
    ecosystemNavigation.getByRole("link", { name: /^Guide/ }),
  ).toHaveAttribute("href", "https://ai-software-factory-mastery.vercel.app");
  await expect(
    ecosystemNavigation.getByRole("link", { name: /Mission Control/ }),
  ).toHaveAttribute("href", "https://fdlc.ai/mission-control");

  const engagementLink = page
    .getByRole("link", {
      name: /Acme Manufacturing Accounts Payable/,
    })
    .last();
  await expect(engagementLink).toContainText("synthetic");
  await engagementLink.click();

  await expect(
    page.getByRole("heading", { level: 1, name: "Acme Manufacturing" }),
  ).toBeVisible();
  await expect(page.getByText("Synthetic workspace")).toBeVisible();
  await expect(page.getByText("6", { exact: true })).toBeVisible({
    timeout: 45_000,
  });
  await expect(
    page.getByRole("heading", { level: 2, name: "Candidate claim review" }),
  ).toBeVisible();

  for (const summary of acceptedClaims) {
    await reviewClaim(page, summary, "Accept");
  }
  for (const summary of rejectedClaims) {
    await reviewClaim(page, summary, "Reject");
  }

  await expect(page.getByText("Review queue is clear.")).toBeVisible();
  await expect(page.getByText("4", { exact: true }).first()).toBeVisible();

  const contradictionSummary =
    "Approval evidence names both CFO and Controller. Confirm whether this is a conflict, exception, or change over time.";
  await page
    .getByRole("textbox", {
      name: `Operator reason for contradiction: ${contradictionSummary}`,
    })
    .fill(
      "Controller approval is the documented strategic-vendor exception to the standard CFO rule.",
    );
  await page.getByRole("button", { name: "Resolve blocker" }).click();
  await expect(page.getByText("Resolved contradiction")).toBeVisible();
  await expect(
    page.getByText("accepted exception", { exact: true }),
  ).toBeVisible();

  await page
    .getByRole("button", { name: "Construct current workflow" })
    .click();
  await expect(
    page.getByRole("heading", {
      level: 3,
      name: "Accounts Payable — Current State",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Approve current workflow" }).click();
  await expect(
    page.getByRole("button", { name: "Approve current workflow" }),
  ).toBeHidden();
  await expect(
    page.getByText("approved", { exact: true }).first(),
  ).toBeVisible();

  await page.getByRole("button", { name: "Design target workflow" }).click();
  await expect(
    page.getByRole("heading", {
      level: 3,
      name: "Accounts Payable — Target State",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Allocation for Approve over $50,000" }),
  ).toHaveValue("human");
  await expect(
    page.getByRole("combobox", {
      name: "Allocation for Process work in NetSuite",
    }),
  ).toHaveValue("software");
  await page.getByRole("button", { name: "Approve target workflow" }).click();

  await page.getByRole("button", { name: "Calculate case" }).click();
  await expect(page.getByText("Low scenario", { exact: true })).toBeVisible();
  await expect(page.getByText("Base scenario", { exact: true })).toBeVisible();
  await expect(page.getByText("High scenario", { exact: true })).toBeVisible();
  await expect(page.getByText("$150,000").first()).toBeVisible();
  await page.getByRole("button", { name: "Approve economic case" }).click();

  await page.getByRole("button", { name: "Generate artifact packet" }).click();
  const artifactTabs = page.getByRole("tab");
  await expect(artifactTabs).toHaveCount(7);
  await expect(
    page.getByRole("tab", { name: "implementation spec" }),
  ).toHaveAttribute("aria-selected", "true");

  const implementationSpec = page.getByLabel(
    "Generated implementation spec Markdown",
  );
  await expect(implementationSpec).toContainText("## Version pins");
  await expect(implementationSpec).toContainText(
    "Invoices over $50,000 require CFO approval.",
  );
  await expect(implementationSpec).toContainText("annual_net_benefit");
  await expect(implementationSpec).toContainText("No production deployment");

  const screenshotPath =
    process.env.AI_FDE_DEMO_SCREENSHOT ??
    testInfo.outputPath("demo-complete.png");
  await page.screenshot({ path: screenshotPath });

  expect(apiRequests, "hosted demo API requests").toEqual([]);
  expect(failedApiResponses, "Factory Engineer API responses").toEqual([]);
  expect(failedApiRequests, "Factory Engineer API request failures").toEqual(
    [],
  );
  expect(consoleErrors, "browser console errors").toEqual([]);
});
