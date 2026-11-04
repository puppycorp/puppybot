// Read-only browser for Gym rollouts and indexed visual-control recordings.
(() => {
  if (location.pathname !== '/cases') return;
  const root = document.getElementById('catalog-content');
  const pageSize = 18;
  let cases = [], gym = [], history = [], selected = 'all', query = '', page = 0;
  let loading = true, problem = '', generation = 0, truncated = false;
  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  function card(row) {
    const node = el('article', null, 'catalog-card');
    const gymRun = row.source === 'Gym';
    const result = row.result;
    const teacher = row.teacherAssisted || /oracle|teacher/i.test(result?.controller || '');
    const type = gymRun ? 'Gym rollout' : teacher ? 'Teacher-assisted' : result?.controller ? 'Recorded controller' : 'Recorded episode';
    node.append(el('span', type, 'eyebrow'));
    const parts = gymRun ? [] : row.path.split('/');
    node.append(el('h3', gymRun ? (cases.find(c => c.id === row.case)?.name || row.case) : parts[parts.length - 1]));
    let outcome = gymRun ? row.status : result ? result.success === true ? 'Task success' : result.success === false ? 'Task not completed' : result.status || 'Outcome unavailable' : 'No saved result';
    node.append(el('span', outcome, `badge ${/success|passed/.test(outcome) ? 'passed' : /failed|not completed/.test(outcome) ? 'failed' : ''}`));
    const details = gymRun ? `Run #${row.id} · seed ${row.seed}` : [result?.seed != null && `Seed ${result.seed}`, result?.steps != null && `${result.steps} steps`, result?.simulationSeconds != null && `${Number(result.simulationSeconds).toFixed(1)} s simulated`].filter(Boolean).join(' · ');
    node.append(el('p', details || 'Result details unavailable', 'catalog-meta'));
    if (!gymRun && typeof result?.found === 'boolean') node.append(el('p', result.found ? 'Brick found' : 'Brick not found', 'catalog-meta'));
    if (!gymRun && row.caseId) node.append(el('p', `Case ${row.caseId}`, 'catalog-meta'));
    if (!gymRun && result?.controller) node.append(el('p', result.controller, 'catalog-meta'));
    node.append(el('code', gymRun ? row.directory : `${row.source}/${row.path}`));
    const actions = el('div', null, 'actions');
    if (gymRun) {
      const open = el('button', 'Inspect rollout'); open.type = 'button';
      open.addEventListener('click', async () => {
        open.disabled = true;
        try {
          const body = new URLSearchParams({ action: 'select', id: row.id, token: document.querySelector('meta[name="monolith-token"]').content });
          const response = await fetch('/action', { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/x-www-form-urlencoded' }, body });
          if (!response.ok) throw new Error(`Could not select rollout (${response.status})`);
          location.href = '/';
        } catch (error) { problem = error.message; open.disabled = false; render(); }
      });
      actions.append(open);
    } else {
      for (const [available, leaf, label] of [[row.video, 'mission.mp4', 'Watch video'], [row.image, 'outcome.png', 'Final image']]) {
        if (available) { const link = el('a', label); link.href = `/api/gym/history/${row.id}/artifacts/${leaf}`; actions.append(link); }
      }
      if (!row.video && !row.image) actions.append(el('span', 'No recording available', 'catalog-meta'));
    }
    node.append(actions); return node;
  }
  function render() {
    const focusedSearch = document.activeElement?.id === 'catalog-search';
    const cursor = focusedSearch ? document.activeElement.selectionStart : null;
    root.replaceChildren();
    const summary = el('div', null, 'catalog-summary');
    for (const [count, label] of [[cases.length, 'AVAILABLE CASES'], [gym.length, 'GYM ROLLOUTS'], [history.length, loading ? 'SAVED EPISODES · INDEXING' : 'SAVED EPISODES']]) {
      const metric = el('div', null, 'metric'); metric.append(el('small', label), el('b', String(count))); summary.append(metric);
    }
    root.append(summary);
    const heading = el('div', null, 'toolbar'); heading.append(el('h2', 'Recorded attempts'));
    const refresh = el('button', 'Refresh catalog'); refresh.type = 'button'; refresh.addEventListener('click', () => load(true)); heading.append(refresh); root.append(heading);
    const note = el('p', problem || (truncated ? 'Some paths could not be indexed; shorten long paths or reduce the number of episodes.' : loading ? 'Finding saved episodes in the background. Results appear as they are indexed.' : 'Results reflect the saved episode files. Teacher-assisted runs may use information unavailable to the model.'), 'muted catalog-note'); note.setAttribute('role', 'status'); root.append(note);
    const controls = el('div', null, 'catalog-controls');
    const label = el('label', 'Search cases, paths, controllers or seeds'); label.htmlFor = 'catalog-search';
    const input = el('input'); input.id = 'catalog-search'; input.type = 'search'; input.placeholder = 'Search recordings'; input.value = query;
    input.addEventListener('input', () => { query = input.value; page = 0; render(); const next = document.getElementById('catalog-search'); next.focus(); next.setSelectionRange(query.length, query.length); }); label.append(input);
    const filter = el('select'); filter.setAttribute('aria-label', 'Filter source');
    for (const [value, name] of [['all', 'All attempts'], ['gym', 'Gym rollouts'], ['policy', 'Other recordings'], ['teacher', 'Teacher-assisted']]) { const option = el('option', name); option.value = value; filter.append(option); }
    filter.value = selected; filter.addEventListener('change', () => { selected = filter.value; page = 0; render(); }); controls.append(label, filter); root.append(controls);
    const items = [...gym, ...history].filter(row => {
      const teacher = row.teacherAssisted || /oracle|teacher/i.test(row.result?.controller || '');
      if (selected === 'gym' && row.source !== 'Gym') return false;
      if (selected === 'teacher' && (row.source === 'Gym' || !teacher)) return false;
      if (selected === 'policy' && (row.source === 'Gym' || teacher)) return false;
      return JSON.stringify(row).toLowerCase().includes(query.toLowerCase());
    });
    page = Math.min(page, Math.max(0, Math.ceil(items.length / pageSize) - 1));
    const grid = el('div', null, 'catalog-grid'); for (const row of items.slice(page * pageSize, (page + 1) * pageSize)) grid.append(card(row));
    if (!items.length) grid.append(el('p', loading ? 'Looking for attempts…' : 'No attempts match this filter.', 'catalog-empty'));
    root.append(grid);
    const pagination = el('div', null, 'catalog-pagination');
    const previous = el('button', '← Previous'); previous.disabled = page === 0; previous.addEventListener('click', () => { page--; render(); });
    const next = el('button', 'Next →'); next.disabled = (page + 1) * pageSize >= items.length; next.addEventListener('click', () => { page++; render(); });
    pagination.append(previous, el('span', `${items.length} matching attempts · page ${page + 1} of ${Math.max(1, Math.ceil(items.length / pageSize))}`, 'muted'), next); root.append(pagination);
    const available = el('section', null, 'panel'); available.style.marginTop = '36px'; available.append(el('h2', 'Available Gym cases'));
    available.append(el('p', 'These are the cases Gym can launch. The counts show attempts in its own database.', 'muted catalog-note'));
    const list = el('div', null, 'catalog-cases');
    for (const entry of cases) { const item = el('article', null, 'catalog-card'); item.append(el('h3', entry.name), el('p', entry.description, 'muted'), el('span', `${gym.filter(run => run.case === entry.id).length} Gym attempts`, 'badge')); list.append(item); }
    available.append(list); root.append(available);
    if (focusedSearch) { input.focus(); input.setSelectionRange(cursor, cursor); }
  }
  async function fetchRows(kind, version) {
    let offset = 0;
    while (version === generation) {
      const response = await fetch(`/api/gym/catalog/${kind}/${offset}`, { cache: 'no-store' });
      if (!response.ok) throw new Error(`Could not load catalog (${response.status}).`);
      const batch = await response.json(); truncated ||= batch.truncated;
      const target = kind === 'gym' ? gym : history;
      target.push(...batch.items.map(row => kind === 'gym' ? { ...row, source: 'Gym' } : row)); offset += batch.items.length;
      if (batch.items.length && (offset % 400 === 0 || offset >= batch.total)) render();
      if (offset >= batch.total) { if (batch.done) break; await new Promise(resolve => setTimeout(resolve, 500)); }
    }
  }
  async function load(refresh = false) {
    const version = ++generation; loading = true; problem = ''; truncated = false; gym = []; history = []; page = 0; render();
    try {
      if (refresh) { const response = await fetch('/api/gym/catalog/refresh', { cache: 'no-store' }); if (!response.ok) throw new Error('Could not refresh the catalog.'); }
      const response = await fetch('/api/gym/cases'); if (!response.ok) throw new Error('Could not load available cases.'); cases = await response.json();
      await Promise.all([fetchRows('gym', version), fetchRows('history', version)]);
    } catch (error) { if (version === generation) problem = error.message; }
    finally { if (version === generation) { loading = false; render(); } }
  }
  // Monolith may reconcile a fresh snapshot after reconnecting.
  new MutationObserver(() => { if (!root.children.length) render(); }).observe(root, { childList: true });
  load();
})();
