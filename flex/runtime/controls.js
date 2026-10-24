// Only press/hold lifecycle lives here. Monolith owns views, forms and SSE.
(() => {
  let held = null;
  let connected = false;
  let chain = Promise.resolve();
  const status = () => document.querySelector('[data-mono-status]');
  const showError = message => document.querySelectorAll('[data-mono-error]').forEach(node => { node.textContent = message; });
  const token = () => document.querySelector('meta[name="monolith-token"]').content;
  async function send(action, hold, keepalive = false) {
    const body = new URLSearchParams({token: token(), action, id: hold.id, lease: hold.lease});
    const response = await fetch('/action', {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json'}, body, keepalive, signal: keepalive ? undefined : AbortSignal.timeout(400)});
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.error || `Action rejected (${response.status}).`);
    }
  }
  function stop() {
    const previous = held;
    held = null;
    if (!previous) return;
    clearTimeout(previous.timer);
    previous.button.classList.remove('pressed');
    chain = chain.catch(() => {}).then(() => send('release', previous, true)).catch(() => {});
  }
  function renew(hold) {
    if (held !== hold) return;
    hold.timer = setTimeout(() => {
      if (held !== hold) return;
      chain = chain.then(async () => {
        if (held !== hold) return;
        await send('renew', hold);
        renew(hold);
      }).catch(error => { showError(error.message); stop(); });
    }, 120);
  }
  function start(button) {
    if (held || !connected || document.hidden || button.disabled) return;
    if (document.querySelector('#dashboard').dataset.ready !== '1') return;
    const random = new Uint32Array(1); crypto.getRandomValues(random);
    const hold = {button, id: button.dataset.hold, lease: String(random[0] || 1)};
    held = hold;
    button.classList.add('pressed');
    showError('');
    chain = chain.catch(() => {}).then(async () => {
      if (held !== hold) return;
      await send('jog', hold);
      renew(hold);
    }).catch(error => { showError(error.message); stop(); });
  }
  document.addEventListener('pointerdown', event => {
    const button = event.target.closest('button[data-hold]');
    if (!button || event.button !== 0) return;
    event.preventDefault();
    button.focus();
    button.setPointerCapture(event.pointerId);
    start(button);
  });
  for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) document.addEventListener(event, stop);
  document.addEventListener('keydown', event => {
    if (event.code === 'Escape') { stop(); document.querySelector('#stop-all').click(); return; }
    const button = event.target.closest('button[data-hold]');
    if (button && ['Space', 'Enter'].includes(event.code)) { event.preventDefault(); if (!event.repeat) start(button); }
  });
  document.addEventListener('keyup', event => { if (['Space', 'Enter'].includes(event.code)) stop(); });
  document.addEventListener('click', event => { if (event.target.closest('[data-action]')) stop(); }, true);
  document.addEventListener('submit', stop, true);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  window.addEventListener('blur', stop);
  window.addEventListener('pagehide', stop);
  new MutationObserver(() => {
    connected = status()?.textContent === 'Live';
    if (!connected || document.querySelector('#dashboard')?.dataset.ready !== '1' || held?.button.disabled) stop();
  }).observe(document.querySelector('#dashboard'), {subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['data-ready', 'disabled']});
})();
