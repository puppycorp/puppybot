// Optional browser check against a running local Gym. No browser dependency at runtime.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const http = require('node:http');

// Drop just this test tab's SSE stream to exercise a real reconnect without
// restarting the user's manager or interrupting any simulation worker.
async function reconnectProxy(url) {
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
        response.on('close', () => { streams.delete(response); upstream.destroy(); });
        request.pipe(upstream);
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    return {url: `http://127.0.0.1:${server.address().port}`, drop: () => { for (const stream of streams) stream.destroy(); },
        close: async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }};
}

(async () => {
    const browser = await chromium.launch({executablePath: process.env.CHROMIUM || '/usr/bin/chromium', headless: true, args: ['--no-sandbox']});
    let proxy;
    try {
        const context = await browser.newContext({viewport: {width: 1280, height: 1000}});
        const page = await context.newPage();
        const errors = [];
        const requests = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('request', request => requests.push(request));
        const url = process.env.GYM_URL || 'http://127.0.0.1:8090';
        const response = await page.goto(url);
        assert.match(response.headers()['content-security-policy'], /script-src 'self'/);
        assert.match(await page.locator('meta[name="monolith-token"]').getAttribute('content'), /^[a-f0-9]{32}$/);
        assert.deepEqual(await page.locator('script').evaluateAll(nodes => nodes.map(node => node.getAttribute('src'))), ['/client.js']);
        await page.waitForFunction(() => document.querySelector('[data-mono-status]')?.textContent === 'Live');
        await page.waitForFunction(() => [...document.querySelector('#case').options].some(option => option.value === 'discover-house-blocks-into-box'));
        const second = await page.context().newPage();
        second.on('pageerror', error => errors.push(error.message));
        proxy = await reconnectProxy(url);
        await second.goto(proxy.url);
        await second.waitForFunction(() => document.querySelector('[data-mono-status]')?.textContent === 'Live');
        await second.getByLabel('Seed').fill('456');
        await page.getByLabel('Seed').fill('123');
        await page.getByRole('button', {name: 'Start rollout'}).click();
        await page.waitForFunction(() => !document.querySelector('#pause').disabled && document.querySelectorAll('#joints tr').length === 4 && document.querySelector('#endpoint').textContent.startsWith('ws://'));
        await page.getByRole('button', {name: 'Pause', exact: true}).click();
        await page.waitForFunction(() => !document.querySelector('#resume').disabled);
        assert.equal(await page.locator('#joints tr').count(), 4);
        assert.match(await page.locator('#endpoint').textContent(), /^ws:\/\/127\.0\.0\.1:\d+\/ws$/);
        await page.getByRole('button', {name: 'Resume', exact: true}).click();
        await page.waitForFunction(() => document.querySelector('#runs tr.selected .badge')?.textContent === 'passed', {timeout: 10000});
        await second.waitForFunction(() => document.querySelector('#runs tr.selected .badge')?.textContent === 'passed');
        assert.equal(await second.getByLabel('Seed').inputValue(), '456');
        assert.equal(await second.evaluate(() => document.activeElement.id), 'seed');
        assert.equal(await page.locator('#plot polyline').count(), 4);
        assert(await page.locator('#plot polyline').evaluateAll(nodes => nodes.every(node => node.namespaceURI === 'http://www.w3.org/2000/svg' && node.getAttribute('points').length > 0)));
        assert.equal(await page.locator('#error').textContent(), '');
        await page.screenshot({path: path.resolve('build/flex/gym-desktop.png'), fullPage: true});
        await page.setViewportSize({width: 390, height: 844});
        await page.screenshot({path: path.resolve('build/flex/gym-mobile.png'), fullPage: true});
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
        await page.reload();
        await page.waitForFunction(() => document.querySelector('#plot polyline'));
        await page.waitForFunction(() => document.querySelector('[data-mono-status]')?.textContent === 'Live');
        assert.equal(await page.locator('#error').textContent(), '');
        assert.equal(requests.filter(request => {
            const pathname = new URL(request.url()).pathname;
            return pathname.startsWith('/api/gym/') && !pathname.includes('/artifacts/');
        }).length, 0);
        const actions = requests.filter(request => new URL(request.url()).pathname === '/action');
        assert(actions.length >= 3);
        assert(actions.every(request => request.headers()['content-type'] === 'application/x-www-form-urlencoded' && /^[a-f0-9]{32}$/.test(new URLSearchParams(request.postData()).get('token'))));
        proxy.drop();
        await second.waitForFunction(() => document.querySelector('[data-mono-status]')?.textContent === 'Reconnecting…');
        await second.waitForFunction(() => document.querySelector('[data-mono-status]')?.textContent === 'Live');
        assert.equal(await second.getByLabel('Seed').inputValue(), '456');
        assert.equal(await second.evaluate(() => document.activeElement.id), 'seed');
        assert.deepEqual(errors, []);
        console.log('Monolith Gym browser: actions/SSE, two-tab sync, draft/focus/reconnect, launch/pause/resume/result/reopen, desktop/mobile passed');
    } finally {
        await browser.close();
        if (proxy) await proxy.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
