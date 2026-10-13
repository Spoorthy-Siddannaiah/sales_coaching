// Only run against the isolated mocked backend described in README.
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const sourceFixture = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/external/kapibala_record.json", import.meta.url)));
const browser = await chromium.launch({
  executablePath:
    process.env.BROWSER_PATH ||
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [],
  starts = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("request", (r) => {
  if (r.method() === "POST" && /\/analyses$/.test(r.url()))
    starts.push(r.postDataJSON());
});
// Test the paid authorization UI with a mock backend that NEVER calls OpenAI.
await page.route("**/api/runtime", (route) =>
  route.fulfill({
    json: {
      provider: "openai",
      model: "gpt-4.1-mini",
      paid_approval_required: true,
    },
  }),
);
const tab = (name) => page.locator(`#tab-${name.toLowerCase()}`);
async function importDialog() {
  await page.locator(".import-trigger").click();
  await page.getByRole("dialog").waitFor();
}
async function authorizeAndStart(name = "Start analysis") {
  const button = page.getByRole("button", { name, exact: true });
  assert.equal(await button.isEnabled(), false);
  await page
    .getByLabel("Authorize one paid OpenAI request.", { exact: false })
    .check();
  await button.click();
  await page
    .getByText("Validated report saved in SQLite.", { exact: true })
    .waitFor();
  assert.equal(await tab("Coaching").getAttribute("aria-selected"), "true");
}
try {
  await page.goto(process.env.SMOKE_URL || "http://127.0.0.1:5175");
  await importDialog();
  assert.equal(
    await page
      .getByLabel("Notion page URL or ID")
      .evaluate((el) => el === document.activeElement),
    true,
  );
  await page.keyboard.press("Escape");
  assert.equal(await page.getByRole("dialog").count(), 0);
  assert.equal(
    await page
      .locator(".import-trigger")
      .evaluate((el) => el === document.activeElement),
    true,
  );
  await importDialog();
  await page.route("**/api/imports/notion", (route) =>
    route.fulfill({
      status: 404,
      json: {
        detail: { message: "Test page unavailable. Check connection access." },
      },
    }),
  );
  await page
    .getByLabel("Notion page URL or ID")
    .fill("11111111-1111-4111-8111-111111111111");
  await page
    .getByRole("button", { name: "Import transcript", exact: true })
    .click();
  await page
    .getByText("Test page unavailable. Check connection access.")
    .waitFor();
  await page.unroute("**/api/imports/notion");
  await page
    .getByRole("button", { name: "Import transcript", exact: true })
    .click();
  await page
    .getByRole("heading", {
      name: "Mocked native meeting - UI acceptance test",
    })
    .waitFor();
  assert.equal(starts.length, 0);
  await page
    .getByLabel("Company", { exact: true })
    .fill("Fictional Support Team");
  await page
    .getByLabel("Meeting objective", { exact: true })
    .fill("Qualify support workflow");
  await page
    .getByLabel("Relevant needs", { exact: true })
    .fill("Reduce peak-season ticket delays");
  await page
    .getByLabel("Previous interactions", { exact: true })
    .fill("None known");
  await page.getByText("Unsaved changes", { exact: true }).waitFor();
  await tab("Transcript").click();
  const nativeText = await page.locator(".transcript-text").textContent();
  assert.match(nativeText, /Security review is a prerequisite/);
  await tab("Transcript").focus();
  await page.keyboard.press("ArrowRight");
  assert.equal(await tab("Coaching").getAttribute("aria-selected"), "true");
  await page
    .getByRole("button", { name: "Analyze conversation", exact: true })
    .click();
  assert.equal(
    await page.getByLabel("Meeting objective", { exact: true }).inputValue(),
    "Qualify support workflow",
  );
  await page.getByRole("button", { name: "Save context", exact: true }).click();
  await page.getByText("Context saved.", { exact: true }).waitFor();
  await authorizeAndStart();
  assert.equal(
    await page
      .locator(".dimension .score")
      .filter({ hasText: "Unknown" })
      .count(),
    5,
  );
  assert.match(
    await page.locator(".analysis-panel").innerText(),
    /Insufficient evidence/,
  );
  assert.equal(starts[0].allow_paid, true);
  await page.screenshot({ path: "../tmp/pdfs/ui-limited.png", fullPage: true });
  await importDialog();
  await page
    .getByRole("button", { name: "Load offline demo", exact: true })
    .click();
  await page
    .getByRole("heading", {
      name: "Offline synthetic sales demo: OmniSupport AI",
    })
    .waitFor();
  await page.getByText(/Synthetic offline demo/).waitFor();
  assert.equal(starts.length, 1);
  await authorizeAndStart();
  assert.equal(await page.locator(".improvement").count(), 2);
  assert.equal(await page.locator(".dimension").count(), 5);
  await page.getByRole("heading", {name: "Sales Coaching Report", exact: true}).waitFor();
  await page.getByRole("heading", {name: "Outstanding actions", exact: true}).waitFor();
  await page.getByRole("heading", {name: "Pending questions / confirmations", exact: true}).waitFor();
  await page.getByRole("heading", {name: "Questions discussed", exact: true}).waitFor();
  assert.equal(await page.locator("#panel-coaching .workspace-transcript").count(), 0);
  assert.equal(await page.locator(".supporting-details, .transcript-evidence").count(), 0);
  const sourceButton = page.locator(".scorecard").filter({ hasText: "Discovery questions" }).locator(".evidence-links button").first();
  const sourceId = (await sourceButton.innerText()).trim();
  await sourceButton.click();
  assert.equal(await tab("Transcript").getAttribute("aria-selected"), "true");
  assert.equal(await page.locator(".source-highlight").getAttribute("data-source-id"), sourceId);
  assert.ok((await page.locator(".source-highlight mark").innerText()).trim());
  assert.equal(await page.locator(".source-highlight").evaluate(el => el === document.activeElement), true);
  for (const quote of await page.locator("#panel-transcript .source-turn-text").all()) {
    assert.ok((await quote.innerText()).trim().length > 0);
  }
  await tab("Coaching").click();
  const firstSummary = await page.locator(".report-summary").innerText();
  await tab("Overview").click();
  assert.equal(
    await page
      .getByLabel("Authorize one paid OpenAI request.", { exact: false })
      .isChecked(),
    false,
  );
  await page.getByRole("button", { name: "Edit context", exact: true }).click();
  await page
    .getByLabel("Meeting objective", { exact: true })
    .fill("Review security prerequisites");
  await tab("Transcript").click();
  const fixtureText = await page.locator(".transcript-text").textContent();
  assert.match(fixtureText, /OmniSupport/);
  await tab("Overview").click();
  assert.equal(
    await page.getByLabel("Meeting objective", { exact: true }).inputValue(),
    "Review security prerequisites",
  );
  await page.getByRole("button", { name: "Save context", exact: true }).click();
  await page.getByText("Context saved.", { exact: true }).waitFor();
  await authorizeAndStart("Run a new analysis");
  await page.waitForFunction(
    (previous) =>
      document.querySelector(".report-summary")?.textContent !== previous,
    firstSummary,
  );
  await page.waitForFunction(() => document.querySelectorAll(".history-label option").length === 2);
  await tab("History").click();
  await page.locator(".history-label select").selectOption({ index: 1 });
  await page
    .getByText(/This attempt uses a previous context snapshot/)
    .waitFor();
  await page.getByText("Input used for this attempt", { exact: true }).click();
  assert.match(
    await page.locator(".snapshot").innerText(),
    /Qualify enterprise helpdesk fit/,
  );
  await page.locator(".history-label select").selectOption({ index: 0 });
  await tab("Coaching").click();
  await page.screenshot({ path: "../tmp/pdfs/ui-full.png", fullPage: true });
  // Exercise persisted processing/failure UI by supplying contract-shaped mocked status responses.
  let polls = 0,
    failedAttempt;
  await page.route("**/api/analyses/*", async (route) => {
    const response = await route.fetch();
    const analysis = await response.json();
    failedAttempt = {
      ...analysis,
      status: "failed",
      report: null,
      error_message: "Model report failed validation; test rejection.",
    };
    await route.fulfill({
      json:
        ++polls === 1
          ? { ...analysis, status: "analyzing", report: null }
          : failedAttempt,
    });
  });
  // A genuine mocked-backend job provides IDs/state; delay detail refresh long enough to see polling.
  await tab("Overview").click();
  await page
    .getByLabel("Authorize one paid OpenAI request.", { exact: false })
    .check();
  await page.route("**/api/conversations/*", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const record = await response.json();
    if (record.analyses?.length === 3)
      record.analyses[0] = {
        ...record.analyses[0],
        status: "analyzing",
        report: null,
      };
    await route.fulfill({ json: record });
  });
  await page
    .getByRole("button", { name: "Run a new analysis", exact: true })
    .click();
  await page.getByText("Analysis in progress", { exact: true }).waitFor();
  await page.unroute("**/api/conversations/*");
  // Preserve the mocked rejection on terminal refresh, just as a saved failed job would return.
  await page.route("**/api/conversations/*", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const record = await response.json();
    if (failedAttempt && record.analyses?.length === 3)
      record.analyses[0] = failedAttempt;
    await route.fulfill({ json: record });
  });
  await page
    .getByText("Report did not pass evidence checks", { exact: true })
    .waitFor();
  await tab("Transcript").click();
  assert.equal(
    await page.locator(".transcript-text").textContent(),
    fixtureText,
  );
  await tab("Overview").click();
  await page.screenshot({
    path: "../tmp/pdfs/ui-overview.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Show list", exact: true }).click();
  await page
    .getByRole("button", {
      name: /Native Notion meeting.*Mocked native meeting/,
    })
    .click();
  assert.equal(
    await page
      .getByRole("button", { name: "Show list", exact: true })
      .getAttribute("aria-expanded"),
    "false",
  );
  await tab("Transcript").click();
  assert.equal(
    await page.locator(".transcript-text").textContent(),
    nativeText,
  );
  await page.screenshot({ path: "../tmp/pdfs/ui-mobile.png", fullPage: true });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
    false,
  );
  await page.unroute("**/api/analyses/*");
  await page.unroute("**/api/conversations/*");
  await page.reload();
  await page.getByRole("button", { name: "Show list", exact: true }).click();
  await page
    .getByRole("button", {
      name: /Offline synthetic fixture.*Offline synthetic sales demo/,
    })
    .click();
  await tab("Coaching").click();
  await page
    .getByText("Validated report saved in SQLite.", { exact: true })
    .waitFor();
  await page.waitForFunction(() => document.querySelectorAll(".history-label option").length === 3);
  // Rendering-only contract fixture; no saved report is changed.
  await page.route("**/api/conversations/*", async route => {
    const response = await route.fetch();
    const record = await response.json();
    const report = record.analyses?.[0]?.report;
    if (report) {
      report.questions_asked = [
        { text: "Salesperson asks about current systems.", evidence: [{ quote: sourceFixture.messages[1].content, role: "salesperson" }] },
        { text: "Customer asks about handoff and security.", evidence: [{ quote: sourceFixture.messages[4].content, role: "customer" }] },
      ];
      report.improvements.push({ ...report.improvements[0], suggestion: "Additional rendering detail" });
    }
    await route.fulfill({ json: record });
  });
  await page.reload();
  await page.getByRole("button", { name: "Show list", exact: true }).click();
  await page.getByRole("button", { name: /Offline synthetic fixture.*Offline synthetic sales demo/ }).click();
  await tab("Coaching").click();
  await page.locator(".question-inventory").waitFor({ state: "attached" });
  assert.equal(await page.locator(".improvement:visible").count(), 3);
  assert.equal(await page.getByRole("heading", { name: /Additional rendering detail/ }).isVisible(), true);


  assert.deepEqual(await page.locator(".question-asker").allTextContents(), ["salesperson question", "customer question"]);
  await page.locator(".report details").evaluateAll(items => items.forEach(el => { el.open = true; }));
  for (const quote of await page.locator("#panel-transcript .source-turn-text").all()) {
    assert.ok((await quote.innerText()).trim(), "Expanded evidence must remain nonblank");
  }
  await page.unroute("**/api/conversations/*");
  await tab("Coaching").click();
  await page.screenshot({ path: "../tmp/pdfs/ui-mobile-report.png", fullPage: true });
  await page.locator(".scorecard").filter({ hasText: "Discovery questions" }).locator(".evidence-links button").first().click();
  assert.equal(await tab("Transcript").getAttribute("aria-selected"), "true");
  assert.equal(await page.locator(".source-highlight").isVisible(), true);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.equal(starts.length, 4);
  assert.ok(starts.every((s) => s.allow_paid === true));
  assert.deepEqual(errors, []);
  console.log(
    "PASS: import dialog/error/focus, native and offline labels, selection, context edits across tabs, exact transcript, explicit authorization/reset, full/limited reports, processing/failure, history snapshots, mobile navigation, reload persistence; no real provider calls.",
  );
} finally {
  await browser.close();
}
