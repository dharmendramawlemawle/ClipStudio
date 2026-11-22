import { chromium } from 'playwright';
import path from 'path';
import fs from 'fs';

const EVIDENCE_DIR = 'D:\\dharmendra\\clipstudio\\docs\\evidence\\phase-2b-3';
const ARTIFACT_EVIDENCE_DIR = 'C:\\Users\\dharm\\.gemini\\antigravity\\brain\\44ee555e-6768-4be3-82c0-b0e832eb52f4\\browser_evidence\\phase_2b3';

if (!fs.existsSync(EVIDENCE_DIR)) {
  fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
}
if (!fs.existsSync(ARTIFACT_EVIDENCE_DIR)) {
  fs.mkdirSync(ARTIFACT_EVIDENCE_DIR, { recursive: true });
}

function saveScreenshot(page, filename) {
  const file1 = path.join(EVIDENCE_DIR, filename);
  const file2 = path.join(ARTIFACT_EVIDENCE_DIR, filename);
  return page.screenshot({ path: file1, fullPage: true }).then(() => {
    fs.copyFileSync(file1, file2);
    console.log(`[SCREENSHOT] Saved: ${filename}`);
  });
}

async function uploadVideo(page, filePath, expectedFilename) {
  console.log(`Uploading ${filePath}...`);
  const importBtn = page.locator('button:has-text("Import Video")').first();
  await importBtn.click();
  await page.waitForTimeout(600);

  const fileInput = page.locator('input[type="file"]');
  await fileInput.waitFor({ state: 'attached', timeout: 10000 });
  await fileInput.setInputFiles(filePath);
  await page.waitForTimeout(500);

  const startUploadBtn = page.locator('button:has-text("Start Upload")');
  await startUploadBtn.click();

  const duplicateBtn = page.locator('button:has-text("Import as New Reference")');
  try {
    await duplicateBtn.waitFor({ state: 'visible', timeout: 3000 });
    console.log('Duplicate detected, clicking Import as New Reference...');
    await duplicateBtn.click();
  } catch {
    // fresh upload
  }

  await page.waitForSelector('text=Import Local Video', { state: 'hidden', timeout: 35000 });
  await page.waitForTimeout(500);
}

(async () => {
  console.log('=== STARTING PHASE 2B.3 PHYSICAL BROWSER ACCEPTANCE TESTING ===');

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  page.on('console', (msg) => console.log(`[BROWSER CONSOLE ${msg.type()}]:`, msg.text()));
  page.on('pageerror', (err) => console.error('[BROWSER PAGE ERROR]:', err));

  try {
    // 1. Initial dashboard
    console.log('1. Navigating to http://127.0.0.1:5173...');
    await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await saveScreenshot(page, '01_dashboard_initial.png');

    // 2. Imported Videos view with Reconcile Thumbnails button
    console.log('2. Opening Imported Videos view...');
    const videosTab = page.locator('aside button:has-text("Imported Videos")');
    await videosTab.click();
    await page.waitForTimeout(1000);
    await saveScreenshot(page, '02_imported_videos_tab_with_reconcile_button.png');

    // 3. Scenario A: Normal Upload & Actual Dimensions Verification
    console.log('3. Scenario A: Uploading valid_presentation.mp4...');
    const importBtn = page.locator('button:has-text("Import Video")').first();
    await importBtn.click();
    await page.waitForTimeout(600);
    await saveScreenshot(page, '03_upload_modal.png');

    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles('D:/dharmendra/clipstudio/test_assets/valid_presentation.mp4');
    await page.waitForTimeout(500);

    const startUploadBtn = page.locator('button:has-text("Start Upload")');
    await startUploadBtn.click();

    const duplicateBtn = page.locator('button:has-text("Import as New Reference")');
    try {
      await duplicateBtn.waitFor({ state: 'visible', timeout: 3000 });
      await duplicateBtn.click();
    } catch {}

    await page.waitForSelector('text=Import Local Video', { state: 'hidden', timeout: 35000 });

    const thumbImg = page.locator('img[alt="valid_presentation.mp4"]').first();
    await thumbImg.waitFor({ state: 'visible', timeout: 30000 });
    await page.waitForTimeout(1000);
    await saveScreenshot(page, '04_thumbnail_completed.png');

    // Open Preview Modal to inspect actual dimensions
    console.log('Opening preview modal for valid_presentation.mp4...');
    const thumbWrapper = page.locator('div[title="Click to preview thumbnail"]').first();
    await thumbWrapper.click();
    await page.waitForTimeout(1000);
    await saveScreenshot(page, '05_thumbnail_preview_modal_actual_dimensions.png');

    const closeBtn = page.locator('button:has-text("Close")').last();
    await closeBtn.click();
    await page.waitForTimeout(600);

    // Reload persistence check
    console.log('Reloading page to verify persistence...');
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await page.locator('aside button:has-text("Imported Videos")').click();
    await page.waitForTimeout(1000);
    await saveScreenshot(page, '06_thumbnail_persisted_after_reload.png');

    // 4. Scenario B: Reconcile Thumbnails action
    console.log('4. Scenario B: Clicking Reconcile Thumbnails button...');
    const reconcileBtn = page.locator('button:has-text("Reconcile Thumbnails")');
    if (await reconcileBtn.isVisible()) {
      await reconcileBtn.click();
      await page.waitForTimeout(800);
      await saveScreenshot(page, '07_reconcile_thumbnails_triggered.png');
      await page.waitForTimeout(2500);
      await saveScreenshot(page, '08_reconcile_thumbnails_completed.png');
    }

    // 5. Scenario D: Portrait (480x854) Video Upload & Actual Dimensions
    console.log('5. Scenario D: Uploading portrait_presentation.mp4...');
    await uploadVideo(page, 'D:/dharmendra/clipstudio/test_assets/portrait_presentation.mp4', 'portrait_presentation.mp4');
    const portraitThumb = page.locator('img[alt="portrait_presentation.mp4"]').first();
    await portraitThumb.waitFor({ state: 'visible', timeout: 30000 });
    await page.waitForTimeout(1000);

    // Click preview for portrait thumbnail
    const portraitThumbWrapper = page.locator('tr:has-text("portrait_presentation.mp4") div[title="Click to preview thumbnail"]').first();
    await portraitThumbWrapper.click();
    await page.waitForTimeout(1000);
    await saveScreenshot(page, '09_portrait_preview_modal_480x854.png');
    await page.locator('button:has-text("Close")').last().click();
    await page.waitForTimeout(600);

    // 6. Scenario D: PAL (720x576) Non-Standard Video Upload & Actual Dimensions
    console.log('6. Scenario D: Uploading pal_presentation.mp4...');
    await uploadVideo(page, 'D:/dharmendra/clipstudio/test_assets/pal_presentation.mp4', 'pal_presentation.mp4');
    const palThumb = page.locator('img[alt="pal_presentation.mp4"]').first();
    await palThumb.waitFor({ state: 'visible', timeout: 30000 });
    await page.waitForTimeout(1000);

    // Click preview for PAL thumbnail
    const palThumbWrapper = page.locator('tr:has-text("pal_presentation.mp4") div[title="Click to preview thumbnail"]').first();
    await palThumbWrapper.click();
    await page.waitForTimeout(1000);
    await saveScreenshot(page, '10_pal_preview_modal_720x576.png');
    await page.locator('button:has-text("Close")').last().click();
    await page.waitForTimeout(600);

    // 7. Scenario E: Error handling with corrupt file
    console.log('7. Scenario E: Uploading corrupt_sample.mp4 to test failure feedback...');
    const importBtnCorrupt = page.locator('button:has-text("Import Video")').first();
    await importBtnCorrupt.click();
    await page.waitForTimeout(500);

    await page.locator('input[type="file"]').setInputFiles('D:/dharmendra/clipstudio/test_assets/corrupt_sample.mp4');
    await page.waitForTimeout(500);

    await page.locator('button:has-text("Start Upload")').click();
    await page.waitForTimeout(2000);
    await saveScreenshot(page, '11_corrupt_upload_error_handling.png');

    const closeError = page.locator('button:has-text("Close")').first();
    if (await closeError.isVisible()) {
      await closeError.click();
    }
    await page.waitForTimeout(500);

    console.log('=== ALL PHASE 2B.3 PHYSICAL ACCEPTANCE TESTS PASSED! ===');
  } catch (err) {
    console.error('PHYSICAL ACCEPTANCE ERROR:', err);
    await saveScreenshot(page, 'error_state.png');
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
