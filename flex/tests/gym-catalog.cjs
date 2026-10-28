// Run against an isolated native manager and temporary recording roots.
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const gym = process.env.GYM_BINARY || path.join(root, 'build/flex/puppybotgym');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
    const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'puppybot-catalog-'));
    const sim = path.join(temp, 'sim'), data = path.join(temp, 'datasets'), runs = path.join(temp, 'gym');
    const episode = path.join(sim, 'trial'), datasetEpisode = path.join(data, 'demonstrations', 'expert');
    await Promise.all([fs.mkdir(episode, {recursive: true}), fs.mkdir(datasetEpisode, {recursive: true}), fs.mkdir(runs)]);
    async function fixture(dir, teacher) {
        await fs.mkdir(path.join(dir, 'scene'));
        await Promise.all([
            fs.writeFile(path.join(dir, 'scene/case.json'), JSON.stringify({id: 'test-room'})),
            fs.writeFile(path.join(dir, 'initial.json'), '{}'), fs.writeFile(path.join(dir, 'decisions.jsonl'), '{}\n'),
            fs.writeFile(path.join(dir, 'result.json'), JSON.stringify({seed: 123, success: true, found: true, steps: 10, simulationSeconds: 2, controller: teacher ? 'training-only oracle' : 'native neural policy'})),
            fs.writeFile(path.join(dir, 'mission.mp4'), '0123456789'),
            ...(teacher ? [fs.writeFile(path.join(dir, 'supervision.json'), '{}')] : [])
        ]);
    }
    await fixture(episode, false); await fixture(datasetEpisode, true);
    await fs.symlink(datasetEpisode, path.join(sim, 'linked-episode'));
    const child = spawn(gym, ['serve', '--data', runs, '--bind', '127.0.0.1:0', '--catalog-sim', sim, '--catalog-datasets', data], {cwd: root});
    let output = ''; child.stdout.on('data', chunk => { output += chunk; }); child.stderr.on('data', chunk => { output += chunk; });
    try {
        for (let i = 0; i < 500 && !/listening on port (\d+)/.test(output); i++) { if (child.exitCode != null) throw new Error(`Gym exited: ${output}`); await wait(10); }
        const port = output.match(/listening on port (\d+)/)?.[1]; assert(port, output);
        const base = `http://127.0.0.1:${port}`;
        async function json(url, options) { const response = await fetch(base + url, options); assert.equal(response.status, 200, url); return response.json(); }
        async function indexed() { for (let i = 0; i < 500; i++) { const result = await json('/api/gym/catalog/history/0'); if (result.done) return result; await wait(10); } throw new Error('Index did not finish'); }
        const first = await indexed(); assert.equal(first.total, 2); assert(!first.truncated);
        const trial = first.items.find(item => item.path === 'trial'); const expert = first.items.find(item => item.path.endsWith('expert'));
        assert(trial && expert); assert.equal(trial.caseId, 'test-room'); assert.equal(trial.result.seed, 123); assert.equal(trial.result.success, true); assert.equal(trial.teacherAssisted, false);
        assert.equal(expert.teacherAssisted, true); assert.equal(expert.source, data);
        let response = await fetch(`${base}/api/gym/history/${trial.id}/artifacts/mission.mp4`, {headers: {Range: 'bytes=2-5'}});
        assert.equal(response.status, 206); assert.equal(await response.text(), '2345');
        assert.equal((await fetch(`${base}/api/gym/history/${trial.id}/artifacts/../result.json`)).status, 404);
        await fs.rename(episode, episode + '-moved'); await fs.symlink(episode + '-moved', episode);
        assert.equal((await fetch(`${base}/api/gym/history/${trial.id}/artifacts/mission.mp4`)).status, 404, 'do not follow a replaced directory symlink');
        await fs.unlink(episode); await fs.rename(episode + '-moved', episode);
        await fs.unlink(path.join(episode, 'mission.mp4')); await fs.symlink(path.join(datasetEpisode, 'mission.mp4'), path.join(episode, 'mission.mp4'));
        assert.equal((await fetch(`${base}/api/gym/history/${trial.id}/artifacts/mission.mp4`)).status, 404, 'do not follow artifact symlinks');
        await fs.unlink(path.join(episode, 'mission.mp4')); await fs.writeFile(path.join(episode, 'mission.mp4'), '0123456789');
        const later = path.join(sim, 'later'); await fs.mkdir(later); await fixture(later, false);
        await json('/api/gym/catalog/refresh'); const refreshed = await indexed(); assert.equal(refreshed.total, 3); assert(refreshed.items.some(item => item.id === trial.id));
        const started = await json('/api/gym/runs', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({case: 'arm-reach', seed: 42})});
        const gymRows = await json('/api/gym/catalog/gym/0'); assert.equal(gymRows.total, 1); assert.equal(gymRows.items[0].id, started.id);
        assert.equal((await fetch(`${base}/cases`)).status, 200);
        console.log('Gym catalog: cases, both roots, outcomes, teacher provenance, refresh, Gym rollout, video ranges and symlink boundaries passed');
    } finally {
        child.kill('SIGTERM'); await new Promise(resolve => { if (child.exitCode != null) resolve(); else child.once('exit', resolve); });
        await fs.rm(temp, {recursive: true, force: true});
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
