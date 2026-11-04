// Optional real browser regression against a disposable fake-bus runtime.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {mkdtempSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const http = require('node:http');
const ROOT = path.resolve(__dirname, '../..');
const key = name => `[data-mkey="${name}"]`;

async function proxy(url) {
    const base = new URL(url), streams = new Set();
    const server = http.createServer((request, response) => {
        const headers = {...request.headers, host: base.host};
        if (headers.origin) headers.origin = base.origin;
        const upstream = http.request(new URL(request.url, base), {method: request.method, headers}, incoming => {
            response.writeHead(incoming.statusCode, incoming.headers);
            if (request.url === '/events') streams.add(response);
            incoming.pipe(response);
        });
        upstream.on('error', () => response.destroy());
        response.on('close', () => {streams.delete(response); upstream.destroy();});
        request.pipe(upstream);
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    return {url: `http://127.0.0.1:${server.address().port}`,
        drop: () => {for (const stream of streams) stream.destroy();},
        close: async () => {server.closeAllConnections(); await new Promise(resolve => server.close(resolve));}};
}

(async () => {
    const temporary = mkdtempSync(path.join(tmpdir(), 'puppybot-dashboard-browser-'));
    const env = {...process.env}; delete env.PUPPYBOT_STSERVO_PORT;
    const runtime = spawn(path.join(ROOT, 'build/flex/puppybot-runtime'), ['--fake', '--bind', '127.0.0.1:0', '--config', path.join(temporary, 'calibration.json')], {cwd: ROOT, env});
    let browser, bridge;
    try {
        const port = await new Promise((resolve, reject) => {
            let text = '';
            const timeout = setTimeout(() => reject(new Error('Runtime startup timeout')), 5000);
            runtime.stdout.on('data', chunk => {text += chunk; const match = /port (\d+)/.exec(text); if (match) {clearTimeout(timeout); resolve(match[1]);}});
            runtime.once('exit', code => {clearTimeout(timeout); reject(new Error(`Runtime exited ${code}`));});
        });
        const url = `http://127.0.0.1:${port}`;
        const state = async () => (await (await fetch(`${url}/api/state`)).json());
        browser = await chromium.launch({executablePath: process.env.CHROMIUM || '/usr/bin/chromium', headless: true, args: ['--no-sandbox']});
        const context = await browser.newContext({viewport: {width: 1440, height: 1100}});
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        const wait = async predicate => {const until = Date.now()+3000; while (!(await predicate())) {if (Date.now()>until) throw new Error('State wait timed out'); await page.waitForTimeout(30);}};
        await page.goto(url);
        await page.waitForFunction(() => document.querySelector('#connection').textContent === 'Live');
        await page.locator('#speed').fill('315');
        await page.locator(key('speed-submit')).click();
        await wait(async () => (await state()).ui.armSpeed === 315);
        const second = await context.newPage(); await second.goto(url);
        await second.waitForFunction(() => document.querySelector('#connection').textContent === 'Live');
        await page.bringToFront();
        await page.locator('#speed').fill('999');
        await page.locator('#speed').focus();
        await second.locator('#speed').fill('320'); await second.locator(key('speed-submit')).click();
        await wait(async () => (await state()).ui.armSpeed === 320);
        assert.equal(await page.locator('#speed').inputValue(), '999');
        assert.equal(await page.locator('#speed').evaluate(node => node === document.activeElement), true);
        const forward = page.locator('#drive-forward');
        await forward.hover(); await page.mouse.down();
        await wait(async () => (await state()).drive.active);
        await page.waitForTimeout(850);
        assert.equal((await state()).drive.active, true);
        await page.mouse.up(); await wait(async () => !(await state()).drive.active);
        await forward.focus(); await page.keyboard.down('Space');
        await wait(async () => (await state()).drive.active);
        await page.keyboard.up('Space'); await wait(async () => !(await state()).drive.active);
        await forward.hover(); await page.mouse.down(); await wait(async () => (await state()).drive.active);
        await page.evaluate(() => window.dispatchEvent(new Event('blur')));
        await wait(async () => !(await state()).drive.active); await page.mouse.up();
        await forward.hover(); await page.mouse.down(); await wait(async () => (await state()).drive.active);
        await page.keyboard.press('Escape'); await wait(async () => !(await state()).drive.active); await page.mouse.up();
        await page.locator('#joint-0-plus').hover(); await page.mouse.down();
        await wait(async () => (await state()).arm.joints[0].speed !== 0);
        await page.mouse.up(); await wait(async () => (await state()).arm.joints.every(joint => joint.speed === 0));
        await page.locator('#frame').selectOption('tool'); await wait(async () => (await state()).ui.tcpFrame === 'Tool');
        await page.locator(key('targets-heading')).click();
        await page.locator('#yaw').fill('0'); await page.locator('#shoulder').fill('90'); await page.locator('#elbow').fill('0'); await page.locator('#wrist').fill('0');
        await page.locator(key('angles-submit')).click(); await wait(async () => (await state()).ui.lastCommand === '/api/arm/goto-angles');
        await page.locator('#stop-all').click();
        await page.waitForTimeout(300);
        assert.equal(await page.locator(key('action-error')).innerText(), '');
        await page.locator(key('joint-0-summary')).click();
        await page.locator('#joint-0-min').fill('5');
        await page.locator(key('joint-0-limits-submit')).click();
        await wait(async () => (await state()).arm.joints[0].minTick === 5);
        await page.locator(key('save')).click();
        await wait(async () => (await (await fetch(`${url}/api/config.json`)).json()).dirty === false);
        await page.locator(key('joint-0-summary')).click();
        await page.locator(key('targets-heading')).click();
        await page.screenshot({path: path.join(ROOT, 'build/flex/dashboard-desktop.png'), fullPage: true});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        // Interrupt just this tab's SSE. Motion must stop, and reconnect must not resume it.
        bridge = await proxy(url);
        const reconnect = await context.newPage(); await reconnect.goto(bridge.url);
        await reconnect.waitForFunction(() => document.querySelector('#connection').textContent === 'Live');
        await reconnect.locator('#drive-forward').hover(); await reconnect.mouse.down(); await wait(async () => (await state()).drive.active);
        bridge.drop(); await wait(async () => !(await state()).drive.active); await reconnect.mouse.up();
        await reconnect.waitForFunction(() => document.querySelector('#connection').textContent === 'Live');
        await page.waitForTimeout(600); assert.equal((await state()).drive.active, false);
        await reconnect.close(); await bridge.close(); bridge = null;
        const mobile = await browser.newContext({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
        const phone = await mobile.newPage(); await phone.goto(url);
        await phone.waitForFunction(() => document.querySelector('#connection').textContent === 'Live');
        assert.equal(await phone.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        const touch = await mobile.newCDPSession(phone);
        const box = await phone.locator('#drive-forward').boundingBox();
        await touch.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: box.x+box.width/2, y: box.y+box.height/2}]});
        await wait(async () => (await state()).drive.active);
        await touch.send('Input.dispatchTouchEvent', {type: 'touchCancel', touchPoints: []});
        await wait(async () => !(await state()).drive.active);
        await touch.detach();
        await phone.screenshot({path: path.join(ROOT, 'build/flex/dashboard-mobile.png'), fullPage: true});
        assert.deepEqual(errors, []);
        console.log('Monolith dashboard browser: rendering/SSE, two tabs, input drafts/focus, hold/release, keyboard/Escape, blur, joint jog, targets, calibration/save, reconnect, desktop/mobile passed');
    } finally {
        if (bridge) await bridge.close();
        if (browser) await browser.close();
        runtime.kill('SIGTERM');
        await new Promise(resolve => {if (runtime.exitCode !== null) resolve(); else runtime.once('exit', resolve);});
        rmSync(temporary, {recursive: true, force: true});
    }
})().catch(error => {console.error(error); process.exit(1);});
