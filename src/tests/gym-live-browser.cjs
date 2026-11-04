// Real browser camera -> Gym -> resident native Pup -> labeled image boxes.
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.GYM_URL || 'http://127.0.0.1:8091';
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || '/usr/bin/chromium', headless: true,
    args: ['--no-sandbox', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
      `--use-file-for-fake-video-capture=${path.resolve('build/flex/vision/camera.y4m')}`] });
  const context = await browser.newContext({ permissions: ['camera'], viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [], responses = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', async response => { if (response.url().endsWith('/vision/frame') && response.status() === 200) responses.push(await response.json()); });
  try {
    await page.goto(base); await page.waitForFunction(() => document.querySelector('[data-mono-status]').textContent === 'Live');
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      const button = page.locator('#navigation-toggle'); const box = await button.boundingBox();
      assert(Math.abs(box.x + box.width / 2 - width / 2) < 2, 'navigation trigger is centered');
      await button.click(); await page.waitForFunction(() => document.querySelector('#site-navigation').matches(':popover-open'));
      await page.waitForFunction(() => {
        const button = document.querySelector('#navigation-toggle').getBoundingClientRect();
        const menu = document.querySelector('#site-navigation').getBoundingClientRect();
        return Math.abs(menu.top - button.bottom - 6) < 1 && Math.abs(menu.x + menu.width / 2 - button.x - button.width / 2) < 1;
      });
      const menu = await page.locator('#site-navigation').boundingBox(); assert(menu.x >= 0 && menu.x + menu.width <= width, 'menu stays in viewport');
      await page.keyboard.press('Escape'); await page.waitForFunction(() => !document.querySelector('#site-navigation').matches(':popover-open'));
      await button.focus(); await page.keyboard.press('Enter'); await page.waitForFunction(() => document.querySelector('#site-navigation').matches(':popover-open'));
      await page.locator('[data-mkey="brand"]').click(); await page.waitForFunction(() => !document.querySelector('#site-navigation').matches(':popover-open'));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'no horizontal overflow');
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('#navigation-toggle').click(); await page.locator('#nav-live').click(); await page.waitForURL('**/live');
    await page.waitForFunction(() => document.querySelector('[data-mono-status]').textContent === 'Live');
    assert(await page.locator('#live-workspace').isVisible()); assert(!await page.locator('#workspace').isVisible());
    await page.locator('#live-start').click(); await page.waitForFunction(() => document.querySelector('#live-status').textContent === 'Detecting', { timeout: 25000 });
    await page.waitForFunction(() => document.querySelector('#live-detections').textContent.includes('bus'), { timeout: 15000 });
    while (responses.length < 3) await page.waitForTimeout(100);
    assert.equal(responses[0].runtime, 'pup'); assert(['sass', 'cuda', 'hip', 'cpu'].includes(responses[0].backend));
    if (process.env.PUPPYBOT_TEST_BACKEND) assert.equal(responses[0].backend, process.env.PUPPYBOT_TEST_BACKEND);
    assert(responses[0].detections.some(d => d.label === 'person'));
    assert(responses[1].frame.id > responses[0].frame.id, 'worker processes successive live frames');
    assert.equal(await page.locator('#live-error').textContent(), '');
    await page.screenshot({ path: 'build/flex/gym-live-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 900 }); await page.waitForTimeout(200);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: 'build/flex/gym-live-mobile.png', fullPage: true });
    await page.locator('#live-stop').click(); await page.waitForFunction(() => document.querySelector('#live-video').srcObject === null);
    const stopped = responses.length; await page.waitForTimeout(500); assert(responses.length <= stopped + 1, 'stop ends frame submissions');
    assert.equal(await page.locator('#live-status').textContent(), 'Camera off');
    assert(await page.locator('#live-start').isEnabled());
    await page.locator('#live-start').click(); await page.waitForFunction(() => document.querySelector('#live-status').textContent === 'Detecting');
    await page.locator('#live-stop').click();
    await page.locator('#navigation-toggle').click(); await page.locator('#nav-rollouts').click(); await page.waitForURL(base + '/');
    await page.waitForFunction(() => document.body.dataset.page === 'rollouts');
    assert(await page.locator('#workspace').isVisible());
    // Check the permission-denied path independently of the real positive path.
    await page.goto(base + '/live');
    await page.evaluate(() => { navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Denied', 'NotAllowedError')); });
    await page.locator('#live-start').click(); await page.waitForFunction(() => document.querySelector('#live-error').textContent.includes('permission was denied'));
    assert(await page.locator('#live-start').isEnabled()); assert(await page.locator('#live-stop').isDisabled());
    assert.deepEqual(errors, []);
    console.log('Gym Live: centered menu/keyboard/dismiss/mobile; real camera/Pup boxes; stop/restart/permission errors passed');
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
