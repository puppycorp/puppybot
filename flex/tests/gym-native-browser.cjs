// Exercise native scene lifecycle and actual video decoding in Gym's browser UI.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
    const browser = await chromium.launch({executablePath: process.env.CHROMIUM || '/usr/bin/chromium', headless: true, args: ['--no-sandbox']});
    const url = process.env.GYM_URL || 'http://127.0.0.1:8090';
    let runId;
    try {
        const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.goto(url);
        await page.waitForFunction(() => document.querySelector('[data-mono-status]')?.textContent === 'Live');
        await page.getByLabel('Case', {exact: true}).selectOption('discover-house-blocks-into-box');
        await page.getByLabel('Seed', {exact: true}).fill('42');
        await page.getByRole('button', {name: 'Start rollout'}).click();
        await page.waitForFunction(() => document.querySelector('#packets')?.textContent === '0 / 6' && !document.querySelector('#pause').disabled);
        runId = await page.locator('#runs tr.selected').getAttribute('data-run');
        assert.equal(await page.locator('#joints tr').count(), 4);
        await page.getByRole('button', {name: 'Pause', exact: true}).click();
        await page.waitForFunction(() => document.querySelector('#runs tr.selected .badge')?.textContent === 'paused' && document.querySelector('#reason')?.textContent === 'simulation time is frozen');
        const paused = await page.locator('#time').textContent();
        await page.waitForTimeout(400);
        assert.equal(await page.locator('#time').textContent(), paused);
        await page.getByRole('button', {name: 'Resume', exact: true}).click();
        await page.waitForFunction(time => document.querySelector('#time')?.textContent !== time, paused);
        await page.getByRole('button', {name: 'Stop', exact: true}).click();
        await page.waitForFunction(() => document.querySelector('#runs tr.selected .badge')?.textContent === 'cancelled');
        const video = page.locator('#mission-video');
        await video.waitFor();
        await page.waitForFunction(() => document.querySelector('#mission-video')?.readyState >= 1);
        assert.equal(await video.evaluate(v => v.videoWidth), 1280);
        await video.evaluate(v => v.play());
        await page.waitForFunction(() => document.querySelector('#mission-video').currentTime > .05);
        await video.evaluate(v => v.pause());
        await page.waitForFunction(() => {
            const image = document.querySelector('img[data-mkey="outcome-image"]');
            return image?.complete && image.naturalWidth === 1280;
        });
        const stem = process.env.GYM_NATIVE_SCREENSHOT || 'build/flex/gym-native';
        await page.screenshot({path: path.resolve(stem+'-desktop.png'), fullPage: true});
        await page.setViewportSize({width: 390, height: 844});
        await page.screenshot({path: path.resolve(stem+'-mobile.png'), fullPage: true});
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
        await page.reload();
        await page.waitForFunction(() => document.querySelector('#mission-video')?.readyState >= 1);
        assert.equal(await page.locator('#packets').textContent(), '0 / 6');
        assert.deepEqual(errors, []);
        console.log('Native Gym browser passed: launch/pause/resume/stop, actual H.264 playback, final TCP image, saved rollout reopening, desktop/mobile');
    } finally {
        if (runId) await fetch(`${url}/api/gym/runs/${runId}/stop`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
