/**
 * Real-product showcase media (§4.9.8): genuinely RECORDED (Playwright
 * recordVideo, never AI-generated) walk-through of the RUNNING app against the
 * REAL engine + real seeded data — never mock mode.
 *
 * Captures the current Omni Steroid Daylight UI (wordmark, Home IA, Meetings,
 * Ask, Settings, Naomi, onboarding). Outputs PNGs under media/screenshots/
 * and a recorded video under .e2e-run/videos/ (post-processed to mp4/gif).
 */
import { mkdirSync } from "node:fs";
import { test, expect } from "../harness/fixtures";
import { SCREENSHOTS_DIR } from "../harness/e2e-env";
import { setOnboardingComplete } from "../harness/engine-command";

mkdirSync(SCREENSHOTS_DIR, { recursive: true });

/** Screenshot the current viewport at the media dir (crisp @2x from config). */
async function shot(page: import("@playwright/test").Page, name: string): Promise<void> {
  await page.screenshot({ path: `${SCREENSHOTS_DIR}/${name}.png` });
}

test("real product tour — home, meetings, ask, settings, naomi", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav).toBeVisible({ timeout: 30_000 });
  // Daylight wordmark — proves we are capturing Omni Steroid, not legacy Omni.
  await expect(nav.getByText("Omni Steroid")).toBeVisible();

  // 1) Home — default shell after onboarding (redesign brief v2).
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(700);
  await shot(page, "00-home");

  // 2) Meetings library — real seeded meetings.
  await nav.getByRole("button", { name: "Meetings" }).click();
  await expect(page.getByRole("heading", { name: "Meetings", level: 1 })).toBeVisible();
  const firstMeeting = page.getByRole("button", { name: "Open Northwind Renewal" });
  await expect(firstMeeting).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(600);
  await shot(page, "01-library");

  // 3) Meeting detail — real enhanced notes + transcript.
  await firstMeeting.click();
  const pane = page.getByRole("complementary", { name: "Meeting detail" });
  await expect(pane.getByText(/24-month term/)).toBeVisible();
  const segments = pane.getByText(/\d+ segments — click to expand/);
  if (await segments.isVisible().catch(() => false)) {
    await segments.click();
    await expect(pane.getByText(/twelve percent uplift/i)).toBeVisible();
  }
  await page.waitForTimeout(400);
  await shot(page, "02-meeting-detail");
  await page.getByRole("button", { name: "Close meeting detail" }).click();

  // 4) Ask — prefer a REAL answer when Gemini is configured; otherwise capture
  // the empty Ask canvas with Omni Steroid chrome (honest offline path).
  await nav.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByRole("heading", { name: "Ask about your meetings" })).toBeVisible();
  const askBox = page.getByRole("textbox", { name: "Ask" });
  await askBox.fill("What did we agree on the Northwind renewal?");
  await page.keyboard.press("Enter");
  const answer = page.getByRole("article", { name: "Answer" });
  const answered = await answer
    .waitFor({ state: "visible", timeout: 40_000 })
    .then(() => true)
    .catch(() => false);
  if (answered) {
    await expect(page.getByRole("button", { name: /\.md · L\d+/ }).first()).toBeVisible();
  } else {
    // Offline / no-key capture: leave the question + shell visible.
    await expect(askBox).toBeVisible();
  }
  await page.waitForTimeout(500);
  await shot(page, "03-ask-answer");

  // 5) Settings — router matrix when present; otherwise the Settings shell.
  await nav.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible({
    timeout: 20_000,
  });
  // Advanced tier often holds the router matrix.
  const advanced = page.getByRole("tab", { name: /Advanced/i });
  if (await advanced.isVisible().catch(() => false)) {
    await advanced.click();
    await page.waitForTimeout(300);
  }
  await page.waitForTimeout(400);
  await shot(page, "04-settings-router");
  await page.getByRole("heading", { name: "Settings", level: 1 }).evaluate((h) => {
    const scroller = h.closest(".overflow-y-auto");
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  });
  await page.waitForTimeout(500);
  await shot(page, "05-settings-ledger-keys");

  // 6) Naomi — living-water pool (WebGL). May be hidden if Cartesia voice id
  // is unset; fall back to Voice notes if Naomi is gated off.
  const naomi = nav.getByRole("button", { name: "Naomi" });
  if (await naomi.isVisible().catch(() => false)) {
    await naomi.click();
    await expect(page.getByTestId("naomi-pool-canvas")).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(1200);
    await shot(page, "06-naomi-pool");
  } else {
    await nav.getByRole("button", { name: "Voice notes" }).click();
    await page.waitForTimeout(600);
    await shot(page, "06-naomi-pool");
  }
});

test("real onboarding walk-through — first-run steps", async ({ page }) => {
  await setOnboardingComplete(false);
  try {
    await page.goto("/");
    await expect(page.getByText("Omni Steroid").first()).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(500);
    await shot(page, "07-onboarding-welcome");

    // Step 1 → 2: features tour
    await page.getByRole("button", { name: /Get started|Begin/i }).click();
    await page.waitForTimeout(400);
    // Skip features tour if present
    const tourContinue = page.getByRole("button", { name: /Continue|Next|Skip/i }).first();
    if (await tourContinue.isVisible().catch(() => false)) {
      await tourContinue.click();
      await page.waitForTimeout(300);
    }
    // Speaker identity (optional skip)
    const skipOrContinue = page.getByRole("button", { name: /Continue|Skip|Next/i }).first();
    if (await skipOrContinue.isVisible().catch(() => false)) {
      await skipOrContinue.click();
      await page.waitForTimeout(300);
    }

    // Vault step
    await page.waitForTimeout(300);
    await shot(page, "08-onboarding-vault");
    const browse = page.getByRole("button", { name: /Browse|Choose folder/i });
    if (await browse.isVisible().catch(() => false)) {
      await browse.click();
      const useFolder = page.getByRole("button", { name: /Use this folder|Folder set/i });
      if (await useFolder.isVisible().catch(() => false)) {
        await useFolder.click();
      }
    }
    const vaultContinue = page.getByRole("button", { name: /Continue|Next/i }).first();
    if (await vaultContinue.isVisible().catch(() => false) && (await vaultContinue.isEnabled())) {
      await vaultContinue.click();
    }

    await page.waitForTimeout(400);
    await shot(page, "09-onboarding-keys");
    const keysContinue = page.getByRole("button", { name: /Continue|Skip|Next/i }).first();
    if (await keysContinue.isVisible().catch(() => false) && (await keysContinue.isEnabled())) {
      await keysContinue.click();
    }

    await page.waitForTimeout(400);
    await shot(page, "10-onboarding-models");
  } finally {
    await setOnboardingComplete(true);
  }
});
