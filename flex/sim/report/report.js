(() => {
    'use strict';
    const names = {control: 'Clear control', distractors: 'Coloured distractors', touching: 'Touching bricks', occlusion: 'Occluded bricks'};
    const variants = {
        control: ['Separated, rotated bricks'],
        distractors: ['', 'Oversized red slab', 'Near-camera red decoy', 'Three coloured decoys'],
        touching: ['', '15 mm gap', '3 mm gap', 'Touching · 0 mm gap'],
        occlusion: ['', 'Small divider coverage', 'Medium divider coverage', 'Full initial coverage']
    };
    const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
    const title = run => names[run.challenge] || run.challenge;
    const variant = run => variants[run.challenge]?.[run.level] || `Level ${run.level}`;
    const filterRuns = (runs, filter) => runs.filter(run =>
        (filter.status === 'all' || (filter.status === 'passed' ? run.passed : !run.passed)) &&
        (filter.challenge === 'all' || run.challenge === filter.challenge) &&
        (filter.seed === 'all' || String(run.seed) === String(filter.seed)));
    const totals = runs => ({total: runs.length, passed: runs.filter(run => run.passed).length,
        failed: runs.filter(run => !run.passed && run.outcome !== 'execution-error').length,
        errors: runs.filter(run => run.outcome === 'execution-error').length});
    const matrix = runs => {
        const rows = new Map();
        for (const run of runs) {
            const key = `${run.challenge}-${run.level}`;
            if (!rows.has(key)) rows.set(key, {challenge: run.challenge, level: run.level, runs: []});
            rows.get(key).runs.push(run);
        }
        return [...rows.values()];
    };
    const explanation = run => {
        if (run.outcome === 'execution-error') return 'This run encountered an execution error. It is separate from a collection-task failure.';
        if (run.challenge === 'control') return 'The original six-brick layout completed without added scenery. All six bricks were released and settled inside the box.';
        if (run.challenge === 'distractors' && run.level === 3) return 'The RGB detector selected the plain red decoy as a brick. A finger collided with the fixed decoy, so the collision guard stopped the attempted pickup.';
        if (run.challenge === 'distractors' && run.level === 2) return 'The near-camera decoy restricted progress. The robot recorded blocked drive steps and timed out while searching; it did not collect all six target bricks.';
        if (run.challenge === 'distractors') return 'The oversized red slab did not prevent collection. All six target bricks ended up inside the box.';
        if (run.challenge === 'touching') return `The same-colour pair, with ${run.level === 3 ? 'no gap' : run.level === 2 ? 'a 3 mm gap' : 'a 15 mm gap'}, was successfully collected along with the other four bricks. Boxes covering multiple target centres occurred, but the collection task still passed.`;
        if (run.passed) return 'The robot collected every brick despite the divider and its initial occlusion. The changed layout allowed it to complete the task.';
        return 'The grey divider blocked drive progress and the robot timed out while searching. The camera still detected bricks, so this is a navigation/search failure rather than evidence of detector failure alone.';
    };
    const model = {names, title, variant, filterRuns, totals, matrix, explanation, escape};
    if (typeof module !== 'undefined' && module.exports) { module.exports = model; return; }

    const savedPage = '<!doctype html>\n' + document.documentElement.outerHTML;
    const payload = JSON.parse(document.getElementById('report-data').textContent);
    const {report, images, sensor, fixtures, checks} = payload;
    const runs = report.runs;
    const byId = new Map(runs.map(run => [run.directory, run]));
    const $ = id => document.getElementById(id);
    const image = (run, view = 'outcome') => images[`${run.directory}/${view}.png`];
    const badge = run => `<span class="badge ${run.passed ? 'pass' : 'fail'}">${run.passed ? '✓ PASSED' : '↗ FAILED'}</span>`;
    const find = (challenge, level, seed) => runs.find(run => run.challenge === challenge && run.level === level && run.seed === seed);
    const summary = totals(runs);
    $('nav-count').textContent = summary.total;
    $('setup-seeds').textContent = `${report.seeds.length} SEEDED LAYOUTS`;
    $('pass-fraction').innerHTML = `${summary.passed}<span> / ${summary.total}</span>`;
    $('total-runs').textContent = summary.total;
    $('failed-runs').textContent = summary.failed;
    $('execution-errors').textContent = summary.errors;
    $('score-bars').innerHTML = Array.from({length: summary.total}, (_, index) => `<i class="${index >= summary.passed ? 'failed' : ''}"></i>`).join('');
    const hero = find('distractors', 3, 42) || runs.find(run => !run.passed) || runs[0];
    $('hero-image').src = image(hero);
    $('hero-inspect').dataset.run = hero.directory;
    $('hero-inspect').dataset.openView = 'sensor';

    const findings = [
        {number: '01', run: hero, label: 'FALSE TARGET', status: 'fail', count: '2 / 2 fooled', heading: 'Colour is not identity.',
            copy: 'A plain red cuboid looked enough like a brick to be selected on both layouts. The collision guard stopped the pickup.', link: 'See the selected decoy', view: 'sensor'},
        {number: '02', run: find('touching', 3, 42), label: 'SURPRISING SUCCESS', status: 'pass', count: '6 / 6 runs passed', heading: 'Touching still worked.',
            copy: 'The same-colour pair passed with 15 mm, 3 mm and zero gap. A box covering multiple bricks did not automatically break collection.', link: 'Inspect the touching pair', view: 'initial'},
        {number: '03', run: find('occlusion', 3, 42), label: 'LAYOUT MATTERS', status: 'fail', count: '3 / 6 runs passed', heading: 'A route can be the limit.',
            copy: 'Dividers stopped the search on layout 42. The same difficulty levels completed on layout 43. Detection is only one part of the task.', link: 'Inspect the blocked search', view: 'outcome'}
    ];
    $('finding-grid').innerHTML = findings.filter(item => item.run).map(item => `<article class="finding-card"><button class="finding-image" data-run="${escape(item.run.directory)}" data-open-view="${item.view}" aria-label="${escape(item.link)}"><img src="${image(item.run)}" loading="lazy" alt="${escape(item.heading)} Actual simulation outcome."><span class="image-arrow" aria-hidden="true">↗</span></button><div class="finding-body"><div class="finding-meta"><span>${item.number} / ${item.label}</span></div><h3>${item.heading}</h3><p>${item.copy}</p><div class="finding-meta"><span class="badge ${item.status}">${item.count}</span></div><button class="text-link" data-run="${escape(item.run.directory)}" data-open-view="${item.view}">${item.link} ↗</button></div></article>`).join('');
    $('story-pair').innerHTML = [42, 43].map(seed => find('occlusion', 3, seed)).filter(Boolean).map(run => `<article class="story-shot"><button data-run="${escape(run.directory)}" aria-label="Inspect full occlusion on layout ${run.seed}"><img src="${image(run)}" loading="lazy" alt="${run.passed ? 'Six bricks collected' : 'Search blocked by a grey divider'} on layout ${run.seed}."></button><div class="story-label"><span>LAYOUT ${run.seed}</span>${badge(run)}</div></article>`).join('');

    let previousChallenge = '';
    $('matrix-body').innerHTML = matrix(runs).map(row => {
        const first = row.runs[0];
        const start = previousChallenge !== row.challenge;
        previousChallenge = row.challenge;
        const cells = [42, 43].map(seed => {
            const run = row.runs.find(item => item.seed === seed);
            return run ? `<td><button class="badge matrix-result ${run.passed ? 'pass' : 'fail'}" data-run="${escape(run.directory)}" aria-label="${escape(title(run))}, ${escape(variant(run))}, layout ${run.seed}: ${run.passed ? 'passed' : 'failed'}, ${run.inside} of ${run.required} inside"><span>${run.passed ? '✓ PASS' : '↗ FAIL'}</span><span>${run.inside}/${run.required}</span></button></td>` : '<td>Not run</td>';
        }).join('');
        return `<tr class="${start ? 'group-start' : ''}"><td>${start ? escape(title(first)) : ''}</td><td>${escape(variant(first))}</td>${cells}</tr>`;
    }).join('');
    const controls = runs.filter(run => run.challenge === 'control');
    $('control-note').textContent = `${controls.filter(run => run.passed).length}/${controls.length} clear controls passed. A stress failure is a measured result; execution errors are counted separately.`;

    let filter = {status: 'all', challenge: 'all', seed: 'all'};
    function renderGrid() {
        const selected = filterRuns(runs, filter);
        $('result-count').textContent = `Showing ${selected.length} of ${runs.length} runs`;
        $('empty-results').hidden = selected.length !== 0;
        $('run-grid').innerHTML = selected.map(run => `<button class="run-card" data-run="${escape(run.directory)}" aria-label="Inspect ${escape(title(run))}, ${escape(variant(run))}, layout ${run.seed}"><img src="${image(run)}" loading="lazy" alt="Actual ${run.passed ? 'successful' : 'failed'} simulation outcome."><div class="run-card-content"><div class="run-card-top"><span>LAYOUT ${run.seed}</span><span>${run.level ? 'LEVEL '+run.level : 'CONTROL'}</span></div><h3>${escape(title(run))}</h3><p>${escape(variant(run))}</p><div class="run-card-bottom">${badge(run)}<span>${run.inside}/${run.required} inside ↗</span></div></div></button>`).join('');
    }
    renderGrid();
    document.querySelectorAll('[data-status]').forEach(button => button.addEventListener('click', () => {
        filter.status = button.dataset.status;
        document.querySelectorAll('[data-status]').forEach(item => { const active = item === button; item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active)); });
        renderGrid();
    }));
    $('challenge-filter').addEventListener('change', event => { filter.challenge = event.target.value; renderGrid(); });
    $('seed-filter').addEventListener('change', event => { filter.seed = event.target.value; renderGrid(); });

    const dialog = $('run-dialog');
    let current = null;
    let currentView = 'outcome';
    let restoreFocus = null;
    function showView(view) {
        if (!current) return;
        const observation = sensor[current.directory];
        currentView = view === 'sensor' && !observation ? 'outcome' : view;
        $('dialog-image').src = image(current, currentView);
        const sensorView = currentView === 'sensor';
        $('dialog-image').alt = sensorView ? `Actual ${observation.view === 'rover' ? 'front' : 'TCP'} camera observation, frame ${observation.frame}.` : `${currentView === 'initial' ? 'Starting scene' : 'Final outcome'} for ${title(current)}, layout ${current.seed}.`;
        $('sensor-overlay').hidden = !sensorView;
        $('sensor-legend').hidden = !sensorView;
        $('sensor-overlay').innerHTML = sensorView ? observation.detections.map((detection, index) => {
            const [x1, y1, x2, y2] = detection.box;
            return `<rect x="${x1}" y="${y1}" width="${x2-x1}" height="${y2-y1}" stroke="${index === observation.chosen ? '#58ff8c' : '#ffdb70'}" stroke-width="2" fill="none"/>`;
        }).join('') : '';
        $('image-caption').textContent = sensorView ? `${observation.view === 'rover' ? 'Front' : 'TCP'} camera · frame ${observation.frame} · actual RGB pixels with offline detection overlays.` : currentView === 'initial' ? 'Original scene before collection. World observer view.' : `Final world view, with the last observed camera frame in the inset. ${current.inside}/${current.required} target bricks inside the box.`;
        document.querySelectorAll('[data-view]').forEach(button => {
            const active = button.dataset.view === currentView;
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', String(active));
            button.disabled = button.dataset.view === 'sensor' && !observation;
        });
    }
    function openRun(id, view = 'outcome') {
        const run = byId.get(id);
        if (!run) return;
        restoreFocus = document.activeElement;
        current = run;
        $('dialog-meta').textContent = `LAYOUT ${run.seed} / ${run.level ? 'LEVEL '+run.level : 'CONTROL'} / ${variant(run)}`;
        $('dialog-title').textContent = title(run);
        $('dialog-badge').className = `badge ${run.passed ? 'pass' : 'fail'}`;
        $('dialog-badge').textContent = run.passed ? '✓ COLLECTION PASSED' : '↗ COLLECTION FAILED';
        $('dialog-explanation').textContent = explanation(run);
        const failure = run.events.failure;
        const metrics = [['Bricks inside', `${run.inside}/${run.required}`], ['Simulation steps', run.steps.toLocaleString()],
            ['Camera frames', run.metrics.cameraFrames || 0], ['Physical grasps', run.metrics.physicalGrasps || 0],
            ['Non-target selections', run.metrics.nonTargetSelections || 0], ['Blocked drive steps', run.metrics.blockedDriveSteps || 0]];
        if (failure) metrics.push(['Failed during', failure.phase], ['Collision object', failure.obstacle || run.events.driveBlocked?.object || '—']);
        $('dialog-metrics').innerHTML = metrics.map(([label, value]) => `<div><dt>${escape(label)}</dt><dd style="${String(value).length > 14 ? 'font-size:13px' : ''}">${escape(value)}</dd></div>`).join('');
        $('replay-command').textContent = run.replay;
        $('copy-status').textContent = '';
        $('copy-replay').textContent = 'Copy replay command';
        showView(view);
        if (!dialog.open) dialog.showModal();
    }
    document.addEventListener('click', event => {
        const trigger = event.target.closest('[data-run]');
        if (trigger) openRun(trigger.dataset.run, trigger.dataset.openView || 'outcome');
    });
    document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));
    $('close-dialog').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
        if (event.target !== dialog) return;
        const bounds = dialog.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    });
    dialog.addEventListener('close', () => { current = null; if (restoreFocus?.isConnected) restoreFocus.focus({preventScroll:true}); });
    $('copy-replay').addEventListener('click', async () => {
        if (!current) return;
        try {
            await navigator.clipboard.writeText(current.replay);
            $('copy-replay').textContent = 'Copied ✓';
            $('copy-status').textContent = 'Paste into a terminal on the PuppyBot machine to open this saved scene.';
        } catch {
            $('copy-status').textContent = 'Copy is unavailable here. Select the command shown below.';
            dialog.querySelector('.replay-details').open = true;
        }
    });
    function download(name, text, type = 'application/json') {
        const url = URL.createObjectURL(new Blob([text], {type}));
        const link = document.createElement('a');
        link.href = url; link.download = name; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    $('download-report').addEventListener('click', () => download('puppybot-test-results.json', JSON.stringify(report, null, 2)));
    $('download-case').addEventListener('click', () => { if (current) download(current.directory+'-scene.json', JSON.stringify(fixtures[current.directory], null, 2)); });
    $('download-run').addEventListener('click', () => { if (current) download(current.directory+'-result.json', JSON.stringify(current, null, 2)); });
    $('save-page').addEventListener('click', () => download('puppybot-test-highlights.html', savedPage, 'text/html'));
    $('verification-list').innerHTML = checks.map(check => `<li><span aria-hidden="true">✓</span><div>${escape(check.name)}<small>${escape(check.detail)}</small></div><span class="badge pass">PASS</span></li>`).join('');
    $('provenance').innerHTML = [['Executable SHA-256', report.binarySha256], ['Model SHA-256', report.modelSha256], ['Layout seeds', report.seeds.join(', ')], ['Run limit', `${report.steps.toLocaleString()} simulation steps`], ['Verification', report.validExperiment ? 'Controls passed; no execution errors' : 'Review the control or execution errors']].map(([key, value]) => `<dt>${escape(key)}</dt><dd>${escape(value)}</dd>`).join('');
})();
