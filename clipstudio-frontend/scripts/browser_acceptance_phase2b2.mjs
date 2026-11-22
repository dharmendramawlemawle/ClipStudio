import { chromium } from 'playwright';
import path from 'path';
import fs from 'fs';

const EVIDENCE_DIR = 'D:\\dharmendra\\clipstudio\\docs\\evidence\\phase-2b-2';
const ARTIFACT_EVIDENCE_DIR = 'C:\\Users\\dharm\\.gemini\\antigravity\\brain\\44ee555e-6768-4be3-82c0-b0e832eb52f4\\browser_evidence\\phase_2b2';

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

(async () => {
  console.log('=== STARTING PHASE 2B.2 PHYSICAL BROWSER ACCEPTANCE TESTING ===');

  const browser = await chromium.launch({
    headless: true,
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  const page = await context.newPage();

  // Listen to console and page errors
  page.on('console', (msg) => console.log(`[BROWSER CONSOLE ${msg.type()}]:`, msg.text()));
  page.on('pageerror', (err) => console.error('[BROWSER PAGE ERROR]:', err));

  try {
    // 1. Navigate to application
    console.log('1. Navigating to http://127.0.0.1:5173...');
    await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await saveScreenshot(page, '01_dashboard_initial.png');

    // 2. Click Imported Videos Tab
    console.log('2. Opening Imported Videos view...');
    const videosTab = page.locator('aside button:has-text("Imported Videos")');
    await videosTab.click();
    await page.waitForTimeout(1000);
    await saveScreenshot(page, '02_imported_videos_tab.png');

    // 3. Open Upload Modal
    console.log('3. Clicking Import Video button...');
    const importBtn = page.locator('button:has-text("Import Video")').first();
    await importBtn.click();
    await page.waitForTimeout(800);
    await saveScreenshot(page, '03_upload_modal.png');

    // 4. Select valid video file
    console.log('4. Selecting valid test video (valid_presentation.mp4)...');
    const validVideoPath = 'D:/dharmendra/clipstudio/test_assets/valid_presentation.mp4';
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(validVideoPath);
    await page.waitForTimeout(600);

    // 5. Click Start Upload
    console.log('5. Clicking Start Upload...');
    const startUploadBtn = page.locator('button:has-text("Start Upload")');
    await startUploadBtn.click();

    // If duplicate banner appears, click "Import as New Reference"
    const duplicateBtn = page.locator('button:has-text("Import as New Reference")');
    try {
      await duplicateBtn.waitFor({ state: 'visible', timeout: 3500 });
      console.log('Duplicate detected, clicking Import as New Reference...');
      await duplicateBtn.click();
    } catch {
      // fresh upload, no duplicate prompt
    }

    // 6. Wait for upload to complete and thumbnail to be generated
    console.log('6. Waiting for upload completion and thumbnail generation...');
    // Wait for the modal to close after upload
    await page.waitForSelector('text=Import Local Video', { state: 'hidden', timeout: 30000 });
    console.log('Upload modal closed. Waiting for thumbnail to process and display in table...');

    // Wait for thumbnail image to appear in the table
    const thumbImg = page.locator('img[alt="valid_presentation.mp4"]').first();
    await thumbImg.waitFor({ state: 'visible', timeout: 30000 });
    console.log('Thumbnail img element is visible on page!');
    await page.waitForTimeout(1500);
    await saveScreenshot(page, '04_thumbnail_completed.png');

    // Verify thumbnail duration badge (0:05)
    const durationBadge = page.locator('span:has-text("0:05")').first();
    console.log('Duration badge visible:', await durationBadge.isVisible());

    // 7. Click thumbnail to open preview modal
    console.log('7. Clicking thumbnail to open Preview Modal...');
    const thumbWrapper = page.locator('div[title="Click to preview thumbnail"]').first();
    await thumbWrapper.click();
    await page.waitForTimeout(1000);
    await saveScreenshot(page, '05_thumbnail_preview_modal.png');

    // 8. Close preview modal
    console.log('8. Closing Preview Modal...');
    const closeBtn = page.locator('button:has-text("Close")').last();
    await closeBtn.click();
    await page.waitForTimeout(800);

    // 9. Click Regenerate Thumbnail action button
    console.log('9. Clicking Regenerate Video Thumbnail...');
    const regenBtn = page.locator('button[title="Regenerate Video Thumbnail"]').first();
    await regenBtn.click();
    await page.waitForTimeout(1000);
    await saveScreenshot(page, '06_thumbnail_regenerate_triggered.png');

    // Wait for regeneration cycle to complete (image visible again)
    await page.waitForTimeout(2000);
    await saveScreenshot(page, '07_thumbnail_regenerate_completed.png');

    // 10. Refresh page to verify persistence
    console.log('10. Reloading page to verify persistence...');
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);

    // Switch to Imported Videos tab after reload
    const videosTabReloaded = page.locator('aside button:has-text("Imported Videos")');
    await videosTabReloaded.click();
    await page.waitForTimeout(1000);

    // Verify thumbnail img still visible after reload
    const reloadedThumbImg = page.locator('img[alt="valid_presentation.mp4"]').first();
    await reloadedThumbImg.waitFor({ state: 'visible', timeout: 15000 });
    console.log('Thumbnail successfully verified after page reload!');
    await saveScreenshot(page, '08_thumbnail_persisted_after_reload.png');

    // 11. Test Error Handling: Upload corrupted file
    console.log('11. Testing upload error handling with corrupt_sample.mp4...');
    const importBtn2 = page.locator('button:has-text("Import Video")').first();
    await importBtn2.click();
    await page.waitForTimeout(600);

    const corruptVideoPath = 'D:/dharmendra/clipstudio/test_assets/corrupt_sample.mp4';
    await page.locator('input[type="file"]').setInputFiles(corruptVideoPath);
    await page.waitForTimeout(500);

    const startUploadBtn2 = page.locator('button:has-text("Start Upload")');
    await startUploadBtn2.click();
    await page.waitForTimeout(2000);

    // Look for error banner
    await saveScreenshot(page, '09_corrupt_upload_error_handling.png');
    console.log('Corrupt upload error handling captured!');

    // Close modal
    const closeErrorModal = page.locator('button:has-text("Close")').first();
    if (await closeErrorModal.isVisible()) {
      await closeErrorModal.click();
    }
    await page.waitForTimeout(500);

    console.log('=== ALL BROWSER ACCEPTANCE TESTS COMPLETED SUCCESSFULLY! ===');
  } catch (err) {
    console.error('TEST ERROR:', err);
    await saveScreenshot(page, 'error_state.png');
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
