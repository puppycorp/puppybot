// Browser media bridge only. Monolith owns navigation markup, forms and SSE.
// Detection runs in the native Pup worker; camera frames are never persisted.
(() => {
  const live = location.pathname === '/live';
  document.body.dataset.page = live ? 'live' : 'rollouts';
  const byId = id => document.getElementById(id);
  const navigation = byId('site-navigation');
  const toggle = byId('navigation-toggle');
  // Native anchor positioning follows the button through layout/scroll changes.
  // Older browsers retain the same placement using the button's actual bounds.
  if (!CSS.supports('top', 'anchor(--workspace-menu bottom)')) {
    const positionNavigation = () => {
      const button = toggle.getBoundingClientRect();
      navigation.style.top = `${button.bottom + 6}px`;
      navigation.style.left = `${button.left + button.width / 2}px`;
    };
    navigation.addEventListener('beforetoggle', event => { if (event.newState === 'open') positionNavigation(); });
    addEventListener('resize', positionNavigation);
    addEventListener('scroll', positionNavigation, { passive: true });
  }
  navigation.addEventListener('toggle', event => toggle.setAttribute('aria-expanded', String(event.newState === 'open')));
  navigation.addEventListener('click', event => { if (event.target.closest('a')) navigation.hidePopover(); });
  if (!live) return;

  const video = byId('live-video'), canvas = byId('live-canvas');
  const start = byId('live-start'), stop = byId('live-stop'), device = byId('live-device');
  const status = byId('live-status'), error = byId('live-error'), metrics = byId('live-metrics');
  const detections = byId('live-detections'), empty = byId('live-empty');
  const capture = document.createElement('canvas');
  let stream = null, generation = 0, active = false, request = null;
  const token = () => document.querySelector('meta[name="monolith-token"]').content;
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  function controls() {
    if (start.disabled !== active) start.disabled = active;
    if (stop.disabled === active) stop.disabled = !active;
    if (device.disabled !== active) device.disabled = active;
  }
  // Reconnect snapshots retain the media elements. Restore local button state
  // if the server snapshot resets their initial disabled attributes.
  new MutationObserver(controls).observe(byId('live-workspace'), { subtree: true, attributes: true, attributeFilter: ['disabled'] });
  function end(message = 'Camera off') {
    generation++; active = false; request?.abort(); request = null;
    stream?.getTracks().forEach(track => track.stop()); stream = null; video.srcObject = null;
    controls(); status.textContent = message; empty.hidden = false;
    canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
    detections.replaceChildren(); metrics.textContent = 'Each set of boxes belongs to the frame shown above.';
  }
  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { 'X-Monolith-Token': token(), ...options.headers } });
    const result = await response.json();
    if (!response.ok) throw Object.assign(new Error(result.error || `Detector request failed (${response.status})`), { status: response.status });
    return result;
  }
  async function ready(version) {
    await api('/api/gym/vision/start', { method: 'POST' });
    for (let attempt = 0; attempt < 75 && version === generation; attempt++) {
      const info = await api('/api/gym/vision');
      if (info.state === 'ready' || info.state === 'busy') return;
      if (info.state === 'error' || info.state === 'unavailable') throw new Error('The model could not start. Check the Gym vision worker log.');
      await delay(200);
    }
    if (version === generation) throw new Error('The detector took too long to start.');
  }
  async function frameBlob() {
    let width = Math.min(video.videoWidth, 640);
    for (let attempt = 0; attempt < 5; attempt++) {
      capture.width = width; capture.height = Math.max(1, Math.round(width * video.videoHeight / video.videoWidth));
      capture.getContext('2d').drawImage(video, 0, 0, capture.width, capture.height);
      const blob = await new Promise(resolve => capture.toBlob(resolve, 'image/jpeg', .7));
      if (blob && blob.size <= 48000) return blob;
      width = Math.max(160, Math.floor(width * .75));
    }
    throw new Error('This camera frame exceeds the 48 KB upload limit.');
  }
  function draw(result, elapsed) {
    if (result.schema !== 'puppybot.detections.v1' || result.frame.width !== capture.width || result.frame.height !== capture.height) throw new Error('Detector response does not match the captured frame.');
    canvas.width = capture.width; canvas.height = capture.height;
    const context = canvas.getContext('2d'); context.drawImage(capture, 0, 0);
    context.lineWidth = Math.max(2, canvas.width / 300); context.font = `${Math.max(13, canvas.width / 40)}px system-ui`;
    const rows = [];
    for (const detection of result.detections) {
      const [x1, y1, x2, y2] = detection.box;
      const label = `${detection.label} ${Math.round(detection.confidence * 100)}%`;
      context.strokeStyle = '#b9e39c'; context.strokeRect(x1, y1, x2 - x1, y2 - y1);
      const labelHeight = Math.max(21, canvas.width / 28), labelWidth = context.measureText(label).width + 12;
      const left = Math.min(x1, Math.max(0, canvas.width - labelWidth)), top = Math.max(labelHeight, y1);
      context.fillStyle = '#b9e39c'; context.fillRect(left, top - labelHeight, labelWidth, labelHeight);
      context.fillStyle = '#102014'; context.fillText(label, left + 6, top - 5);
      const row = document.createElement('li'); row.textContent = label; rows.push(row);
    }
    if (!rows.length) { const row = document.createElement('li'); row.textContent = 'No objects above the confidence threshold'; rows.push(row); }
    detections.replaceChildren(...rows); empty.hidden = true;
    metrics.textContent = `${result.model.id} · ${result.backend.toUpperCase()} · ${result.inferenceMs} ms inference · ${result.preprocessMs} ms preparation · ${(1000 / Math.max(elapsed, 1)).toFixed(1)} analyzed frames/s`;
    status.textContent = 'Detecting'; error.textContent = '';
  }
  async function loop(version) {
    while (active && generation === version) {
      try {
        const blob = await frameBlob(); if (generation !== version) break;
        request = new AbortController(); const began = performance.now();
        const result = await api('/api/gym/vision/frame', { method: 'POST', headers: { 'Content-Type': 'image/jpeg' }, body: blob, signal: request.signal });
        if (generation !== version) break; draw(result, performance.now() - began);
      } catch (failure) {
        if (generation !== version) break;
        if (failure.status === 409) { status.textContent = 'Waiting for detector'; await delay(150); continue; }
        end('Camera stopped'); error.textContent = failure.message; break;
      }
      await delay(30);
    }
  }
  start.addEventListener('click', async () => {
    if (active) return;
    active = true; const version = ++generation; controls(); error.textContent = ''; status.textContent = 'Loading model…';
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access needs localhost or HTTPS and a supported browser.');
      await ready(version); if (generation !== version) return;
      status.textContent = 'Requesting camera…';
      const camera = await navigator.mediaDevices.getUserMedia({ audio: false, video: { ...(device.value ? { deviceId: { exact: device.value } } : { facingMode: 'environment' }), width: { ideal: 1280 }, height: { ideal: 720 } } });
      if (generation !== version) { camera.getTracks().forEach(track => track.stop()); return; }
      stream = camera; video.srcObject = camera; await video.play();
      const current = camera.getVideoTracks()[0].getSettings().deviceId;
      const choices = (await navigator.mediaDevices.enumerateDevices()).filter(item => item.kind === 'videoinput');
      device.replaceChildren(...choices.map((item, index) => new Option(item.label || `Camera ${index + 1}`, item.deviceId))); device.value = current || '';
      camera.getVideoTracks()[0].addEventListener('ended', () => { if (active && generation === version) { end('Camera disconnected'); error.textContent = 'The camera was disconnected.'; } });
      status.textContent = 'Analyzing…'; await loop(version);
    } catch (failure) {
      if (generation !== version) return;
      end('Camera stopped'); error.textContent = failure.name === 'NotAllowedError' ? 'Camera permission was denied. Allow camera access in the browser and try again.' : failure.message;
    }
  });
  stop.addEventListener('click', () => end());
  addEventListener('pagehide', () => end());
  document.addEventListener('visibilitychange', () => { if (document.hidden && active) end('Camera stopped while tab is hidden'); });
})();
