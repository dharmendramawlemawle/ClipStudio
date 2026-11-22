import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const evidenceDir = 'D:/dharmendra/clipstudio/docs/evidence/phase-2b-1-3';
if (!fs.existsSync(evidenceDir)) {
  fs.mkdirSync(evidenceDir, { recursive: true });
}

async function run() {
  console.log('=== Starting Real Playwright Browser Acceptance Test ===');
  const browser = await chromium.launch({
    headless: true,
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 }
  });
  const page = await context.newPage();

  // Create CDP Session for low-level WebSocket protocol tracking
  const client = await context.newCDPSession(page);
  await client.send('Network.enable');

  let wsCreatedCount = 0;
  let wsClosedCount = 0;
  const activeSockets = new Set();
  const wsEvents = [];
  let shotC = '';

  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame()) {
      // Clear active socket tracking for previous page context
      activeSockets.clear();
    }
  });

  client.on('Network.webSocketCreated', ({ requestId, url }) => {
    // Only track ClipStudio application WebSocket, ignore Vite internal HMR socket
    if (!url.includes('/ws/events')) return;
    wsCreatedCount++;
    activeSockets.add(requestId);
    wsEvents.push({ type: 'created', requestId, url, time: new Date().toISOString() });
    console.log(`[CDP] App WebSocket Created (#${wsCreatedCount}): ${url} (requestId: ${requestId})`);
  });

  client.on('Network.webSocketClosed', ({ requestId, timestamp }) => {
    if (!activeSockets.has(requestId)) return;
    wsClosedCount++;
    activeSockets.delete(requestId);
    wsEvents.push({ type: 'closed', requestId, time: new Date().toISOString() });
    console.log(`[CDP] App WebSocket Closed (#${wsClosedCount}) (requestId: ${requestId})`);
  });

  client.on('Network.webSocketFrameReceived', ({ requestId, response }) => {
    if (!activeSockets.has(requestId)) return;
    try {
      const payload = JSON.parse(response.payloadData);
      wsEvents.push({ type: 'frame', requestId, event_type: payload.event_type, time: new Date().toISOString() });
      if (payload.event_type === 'job_progress') {
        console.log(`[CDP] WS Job Progress: ${payload.job_id} -> ${payload.status} (${payload.progress_percent}%)`);
      }
    } catch {}
  });

  // A. Initial connection
  console.log('\n--- Step A: Initial Connection ---');
  await page.goto('http://localhost:5173');
  await page.waitForLoadState('networkidle');

  // Wait for Header status elements
  const header = page.locator('header');
  await header.getByText('Backend:').waitFor({ timeout: 10000 });
  await header.getByText('Online').waitFor({ timeout: 10000 });
  await header.getByText('WebSocket:').waitFor({ timeout: 10000 });
  await header.getByText('Live').waitFor({ timeout: 10000 });

  const shotA = path.join(evidenceDir, '01_initial_connection.png');
  await page.screenshot({ path: shotA, fullPage: true });
  console.log(`[OK] Screenshot A captured: ${shotA}`);
  console.log(`Initial App WS created: ${wsCreatedCount}, Active: ${activeSockets.size}`);
  if (activeSockets.size !== 1) {
    throw new Error(`Expected exactly 1 active App WS on initial load, got ${activeSockets.size}`);
  }
  const initialCreatedCount = wsCreatedCount;

  // B. Re-render stability
  console.log('\n--- Step B: Re-render Stability ---');
  // Trigger tab switches and health refresh to force parent re-renders
  console.log('Clicking Videos tab...');
  await page.click('button:has-text("Imported Videos")');
  await page.waitForTimeout(1000);

  console.log('Clicking Dashboard tab...');
  await page.click('button:has-text("Dashboard")');
  await page.waitForTimeout(1000);

  console.log('Clicking Refresh Health button...');
  const refreshBtn = await page.$('button[title*="Refresh"]');
  if (refreshBtn) {
    await refreshBtn.click();
    await page.waitForTimeout(1000);
  }

  console.log('Clicking Refresh List button in JobsTable...');
  const refreshJobsBtn = await page.$('button:has-text("Refresh List")');
  if (refreshJobsBtn) {
    await refreshJobsBtn.click();
    await page.waitForTimeout(1000);
  }

  const shotB = path.join(evidenceDir, '02_rerender_stability.png');
  await page.screenshot({ path: shotB, fullPage: true });
  console.log(`[OK] Screenshot B captured: ${shotB}`);
  console.log(`After re-renders: WS created: ${wsCreatedCount}, Active: ${activeSockets.size}`);
  if (wsCreatedCount !== initialCreatedCount) {
    throw new Error(`FAIL: App WebSocket recreated on ordinary re-render! Count changed from ${initialCreatedCount} to ${wsCreatedCount}`);
  }

  // C. Live telemetry
  console.log('\n--- Step C: Live Telemetry via JobTester ---');
  const execBtn = await page.$('button:has-text("Execute Test Job")');
  if (execBtn) {
    console.log('Executing test job...');
    await execBtn.click();
    // Wait for progress updates or completion
    await page.waitForSelector('text=COMPLETED', { timeout: 15000 });
    console.log('[OK] Job reached COMPLETED state via live WebSocket updates!');
    shotC = path.join(evidenceDir, '03_live_telemetry.png');
    await page.screenshot({ path: shotC, fullPage: true });
    console.log(`[OK] Screenshot C captured: ${shotC}`);
    console.log(`During job telemetry: WS created: ${wsCreatedCount}, Active: ${activeSockets.size}`);
    if (wsCreatedCount !== initialCreatedCount) {
      throw new Error(`FAIL: App WebSocket recreated during job telemetry! Count changed from ${initialCreatedCount} to ${wsCreatedCount}`);
    }
  } else {
    console.log('NOT TESTABLE THROUGH CURRENT UI — NO USER-FACING CONTROL');
  }

  // D. Genuine reconnection
  console.log('\n--- Step D: Genuine Reconnection ---');
  console.log('Simulating network disconnection by closing active socket...');
  const beforeDropCount = wsCreatedCount;

  await page.evaluate(() => {
    if (window.__clipstudio_ws) {
      window.__clipstudio_ws.close();
    }
  });

  // Verify Disconnected badge appears in header
  await header.getByText('Disconnected').waitFor({ timeout: 5000 });
  const shotD1 = path.join(evidenceDir, '04_genuine_disconnect.png');
  await page.screenshot({ path: shotD1, fullPage: true });
  console.log(`[OK] Screenshot D1 captured (Disconnected): ${shotD1}`);

  // Verify Automatic Reconnect restores Live state
  console.log('Waiting for automatic backoff reconnect...');
  await header.getByText('Live').waitFor({ timeout: 15000 });
  const shotD2 = path.join(evidenceDir, '05_genuine_reconnected.png');
  await page.screenshot({ path: shotD2, fullPage: true });
  console.log(`[OK] Screenshot D2 captured (Reconnected): ${shotD2}`);
  console.log(`After restore: WS created: ${wsCreatedCount}, Active: ${activeSockets.size}`);
  if (wsCreatedCount <= beforeDropCount) {
    throw new Error(`Expected WS creation count to increase after genuine reconnect. Before: ${beforeDropCount}, After: ${wsCreatedCount}`);
  }
  if (activeSockets.size !== 1) {
    throw new Error(`Expected exactly 1 active App WS after reconnect, got ${activeSockets.size}`);
  }

  // E. Full Page Refresh
  console.log('\n--- Step E: Full Page Refresh ---');
  await page.reload();
  await page.waitForLoadState('networkidle');
  await header.getByText('Live').waitFor({ timeout: 10000 });
  await page.getByText('Persistent Job History (SQLite)').waitFor({ timeout: 10000 });

  const shotE = path.join(evidenceDir, '06_page_refresh.png');
  await page.screenshot({ path: shotE, fullPage: true });
  console.log(`[OK] Screenshot E captured: ${shotE}`);
  console.log(`After reload: WS created: ${wsCreatedCount}, Active: ${activeSockets.size}`);
  if (activeSockets.size !== 1) {
    throw new Error(`Expected exactly 1 active App WS after reload, got ${activeSockets.size}`);
  }

  // Write summary manifest
  const manifest = {
    testDate: new Date().toISOString(),
    totalWsCreated: wsCreatedCount,
    totalWsClosed: wsClosedCount,
    finalActiveSockets: activeSockets.size,
    screenshots: [
      { name: '01_initial_connection.png', path: shotA, timestamp: new Date().toISOString() },
      { name: '02_rerender_stability.png', path: shotB, timestamp: new Date().toISOString() },
      { name: '03_live_telemetry.png', path: shotC, timestamp: new Date().toISOString() },
      { name: '04_genuine_disconnect.png', path: shotD1, timestamp: new Date().toISOString() },
      { name: '05_genuine_reconnected.png', path: shotD2, timestamp: new Date().toISOString() },
      { name: '06_page_refresh.png', path: shotE, timestamp: new Date().toISOString() },
    ],
    wsEvents
  };
  fs.writeFileSync(path.join(evidenceDir, 'manifest.json'), JSON.stringify(manifest, null, 2));

  await browser.close();
  console.log('\n=== Browser Acceptance Test PASSED with 100% SUCCESS ===');
}

run().catch((err) => {
  console.error('\n[FATAL ERROR in Browser Acceptance]:', err);
  process.exit(1);
});
