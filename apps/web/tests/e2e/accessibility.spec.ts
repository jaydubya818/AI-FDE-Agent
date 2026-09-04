import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const wcagTags = ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"];

async function expectNoAccessibilityViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(wcagTags).analyze();
  expect(
    results.violations,
    JSON.stringify(results.violations, null, 2),
  ).toEqual([]);
}

async function openEngagementList(page: Page) {
  await page.goto("/");
  await expect(page.getByText("Checking operator session")).toBeHidden();
  await expect(page.getByText("Loading engagements…")).toBeHidden();
}

async function openAcmeEngagement(page: Page) {
  await openEngagementList(page);
  const href = await page
    .getByRole("link", { name: /Acme Manufacturing/ })
    .last()
    .getAttribute("href");
  expect(href).toBeTruthy();
  await page.goto(href!);
  await expect(
    page.getByRole("heading", { level: 1, name: "Acme Manufacturing" }),
  ).toBeVisible();
}

test("engagement list has no WCAG A or AA axe violations", async ({ page }) => {
  await openEngagementList(page);
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Turn enterprise reality into a deployable software factory.",
    }),
  ).toBeVisible();

  await expectNoAccessibilityViolations(page);
});

test("FDLC ecosystem navigation remains visible on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openEngagementList(page);

  const navigation = page.getByRole("navigation", { name: "FDLC ecosystem" });
  await expect(navigation.getByRole("link")).toHaveCount(3);
  await expect(
    navigation.getByRole("link", { name: /Framework/ }),
  ).toBeVisible();
  await expect(navigation.getByRole("link", { name: /^Guide/ })).toBeVisible();
  await expect(
    navigation.getByRole("link", { name: /Mission Control/ }),
  ).toBeVisible();
  await expectNoAccessibilityViolations(page);
});

test("engagement list preserves keyboard focus through disclosures", async ({
  page,
}) => {
  await openEngagementList(page);

  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Skip to main content" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  const createButton = page.getByRole("button", { name: "New engagement" });
  await createButton.click();
  await expect(
    page.getByRole("textbox", { name: "Company name" }),
  ).toBeFocused();

  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(createButton).toBeFocused();
  await expect(createButton).toHaveAttribute("aria-expanded", "false");
});

test("full Operator Cockpit has no WCAG A or AA axe violations", async ({
  page,
}) => {
  await openAcmeEngagement(page);
  await expectNoAccessibilityViolations(page);
});

test("cockpit landmarks, disclosures, and scroll regions are keyboard reachable", async ({
  page,
}) => {
  await openAcmeEngagement(page);

  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Skip to main content" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  const noteButton = page.getByRole("button", {
    name: "Add operator note as source evidence",
  });
  await noteButton.click();
  await expect(page.getByRole("textbox", { name: "Title" })).toBeFocused();
  await expect(
    page.getByRole("button", { name: "Close operator note" }),
  ).toHaveAttribute("aria-expanded", "true");

  const specification = page.getByLabel(/^Generated .* Markdown$/);
  if (await specification.count()) {
    await expect(specification).toHaveAttribute("tabindex", "0");
  }
});

test("reduced-motion preference disables meaningful animation", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openAcmeEngagement(page);

  await expect
    .poll(() =>
      page.evaluate(
        () => getComputedStyle(document.documentElement).scrollBehavior,
      ),
    )
    .toBe("auto");
});
