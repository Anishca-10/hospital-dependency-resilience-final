/* Hospital Dependency Resilience Platform - front end (vanilla JS). All data comes from the Flask API. */
const PARTNERS = ['laboratory', 'pharmacy', 'insurance', 'telemedicine'];
const perms = (document.body.dataset.perms || '').split(',');
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (v, suffix = '') => (v === null || v === undefined) ? '-' : `${v}${suffix}`;

async function api(path, opts = {}) {
  const o = { headers: { 'Content-Type': 'application/json' }, ...opts };
  if (o.body && typeof o.body !== 'string') o.body = JSON.stringify(o.body);
  const r = await fetch(path, o);
  if (r.status === 401) { location.href = '/login'; throw new Error('auth'); }
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) { const err = new Error(data.error || r.statusText); err.details = data.details; err.status = r.status; throw err; }
  return data;
}

function chipClass(status) {
  return ({ SUCCESS: 'green', RECOVERED: 'green', HEALTHY: 'green', COMPLETED: 'green', CLOSED: 'green',
    DEGRADED: 'yellow', TIMEOUT: 'yellow', RETRYING: 'yellow', FALLBACK_ACTIVE: 'yellow', HALF_OPEN: 'yellow', REJECTED: 'yellow',
    COMPLETED_DEGRADED: 'yellow', TEMPORARILY_UNAVAILABLE: 'red', UNAVAILABLE: 'red', ERROR: 'red', FAILED: 'red',
    CIRCUIT_OPEN: 'gray', OPEN: 'gray', UNKNOWN: 'blue' })[status] || 'blue';
}
const chip = (s) => `<span class="chip chip-${chipClass(s)}">${esc(s)}</span>`;
const tm = (ts) => (ts || '').replace('T', ' ').slice(0, 19);

/* ------------------------------------------------------------------ navigation */
let currentPage = null, pollTimer = null;
function show(page) {
  currentPage = page;
  document.querySelectorAll('.tab-content').forEach(s => s.classList.toggle('active', s.id === 'page-' + page));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  location.hash = page;
  refresh();
}
function refresh() {
  const fn = { dashboard: loadDashboard, patients: loadPatientsPage, health: loadHealth, depmap: loadDepMap,
    simulation: loadSimulation, experiments: loadExperiments, logs: loadLogs, config: loadConfig,
    validation: loadValidation, reports: loadReports }[currentPage];
  if (fn) fn().catch(e => console.error(currentPage, e));
}

/* ------------------------------------------------------------------ partner cards */
function partnerCard(p, detailed) {
  const circ = p.circuit || { state: p.circuit_state };
  let extra = '';
  if (detailed) {
    extra = `<div class="kv">
      <span>Circuit</span><span>${chip(circ.state)} ${circ.state === 'OPEN' ? esc(circ.remaining_open_seconds) + 's until test' : ''}</span>
      <span>Failures in a row</span><span>${esc(circ.failure_count)} / ${esc(circ.failure_threshold)}</span>
      <span>Times opened</span><span>${esc(circ.open_count)}</span>
      <span>Recent calls</span><span>${esc(p.recent_calls)} (failure ratio ${esc(p.failure_ratio)})</span>
      <span>Avg latency</span><span>${fmt(p.avg_latency_ms, ' ms')}</span>
      <span>Timeout setting</span><span>${esc(p.timeout_seconds)} s</span>
      <span>Last observed</span><span>${esc(tm(p.last_checked)) || '-'}</span>
      <span>Simulation</span><span>${esc(p.simulation.mode)}${p.simulation.remaining_seconds != null ? ' (' + p.simulation.remaining_seconds + 's left)' : ''}</span></div>`;
  }
  return `<div class="partner-card"><div class="partner-header"><span class="partner-name"><i class="dot dot-${p.color}"></i>${esc(p.display_name)}</span>${chip(p.status)}</div>
    <div class="small" style="margin-top:.4rem">${esc(p.message)}</div>${extra}</div>`;
}

/* ------------------------------------------------------------------ dashboard */
async function loadDashboard() {
  const d = await api('/api/status');
  const m = d.metrics;
  const card = (label, value, cls = '') => `<div class="metric-card ${cls}"><div class="metric-label">${label}</div><div class="metric-value">${value}</div></div>`;
  $('dash-metrics').innerHTML =
    card('Core availability', fmt(m.core_availability_pct, '%'), 'success') + card('Partner request success', fmt(m.request_success_rate_pct, '%')) +
    card('Avg latency', fmt(m.avg_latency_ms, ' ms')) + card('P95 latency', fmt(m.p95_latency_ms, ' ms'), 'warning') +
    card('Timeouts', m.timeout_count) + card('Retries', m.retry_count) + card('Fallbacks', m.fallback_count, 'danger') +
    card('Circuit opens', m.circuit_open_count) + card('Pending sync', d.pending_actions) + card('Total requests', m.total_requests);
  $('dash-partners').innerHTML = PARTNERS.map(p => partnerCard(d.partners[p], true)).join('');
  $('dash-calls').innerHTML = d.recent_calls.map(c => `<tr><td>${esc(tm(c.timestamp).slice(11))}</td><td>${esc(c.mode)}</td><td>${esc(c.partner)}</td>
    <td>${chip(c.status)}</td><td>${esc(c.latency_ms)} ms</td><td>${esc(c.retry_count)}</td><td>${esc(c.circuit_state)}</td></tr>`).join('') || '<tr><td colspan="7" class="small">No requests yet - use Failure Simulation &rarr; Send test traffic.</td></tr>';
  $('dash-events').innerHTML = d.circuit_events.map(e => `<tr><td>${esc(tm(e.timestamp).slice(11))}</td><td>${esc(e.partner)}</td>
    <td>${chip(e.old_state)} &rarr; ${chip(e.new_state)}</td><td>${esc(e.reason)}</td></tr>`).join('') || '<tr><td colspan="4" class="small">No circuit transitions yet.</td></tr>';
}

/* ------------------------------------------------------------------ patients (clinical) */
let selPatient = null;
async function loadPatientsPage() {
  const pr = await api('/api/partners');
  $('pt-partners').innerHTML = PARTNERS.map(p => partnerCard(pr.partners[p], false)).join('');
  const d = await api('/api/patients');
  $('pt-list').innerHTML = d.patients.map(p => `<div data-id="${esc(p.patient_id)}" class="${p.patient_id === selPatient ? 'sel' : ''}">${esc(p.patient_id)} - ${esc(p.patient_name)}</div>`).join('');
  $('pt-list').querySelectorAll('div').forEach(el => el.onclick = () => { selPatient = el.dataset.id; loadPatientsPage(); });
  if (selPatient) {
    const x = await api('/api/patients/' + selPatient);
    const p = x.patient;
    $('pt-info').innerHTML = `<div class="kv"><span>ID</span><span>${esc(p.patient_id)}</span><span>Name</span><span>${esc(p.patient_name)}</span>
      <span>Age / Gender</span><span>${esc(p.age)} / ${esc(p.gender)}</span><span>Department</span><span>${esc(p.department)}</span>
      <span>Registered</span><span>${esc(p.registration_date)}</span></div>
      <div class="small" style="margin-top:.6rem"><b>Appointments</b></div>` +
      (x.appointments.map(a => `<div class="small">${esc(a.appointment_id)} - ${esc(a.doctor)} - ${esc(a.appointment_date)} - ${esc(a.status)}</div>`).join('') || '<div class="small">None</div>') +
      (x.pending_actions.length ? `<div class="small" style="margin-top:.6rem"><b>Deferred partner requests</b></div>` +
        x.pending_actions.map(a => `<div class="small">${esc(a.partner)} / ${esc(a.operation)} - ${chip(a.status)}</div>`).join('') : '');
  }
}
const OPS = { laboratory: ['/api/laboratory/request', { test_type: 'Complete Blood Count (CBC)' }], pharmacy: ['/api/pharmacy/check', { medication: 'Synthetic Medication 500mg' }],
  insurance: ['/api/insurance/verify', {}], telemedicine: ['/api/telemedicine/book', {}] };
function resultCard(r) {
  const att = (r.attempts || []).map(a => `#${a.attempt} ${esc(a.result)}`).join(' &rarr; ');
  return `<div class="result-card"><b>${esc(r.partner)}</b> ${chip(r.status)} ${r.fallback_used ? chip('FALLBACK_ACTIVE') : ''}
    <div class="msg">${esc(r.message)}</div>
    <div class="meta">attempts: ${att || '-'} &middot; retries ${esc(r.retry_count)} &middot; ${esc(r.latency_ms)} ms &middot; circuit ${esc(r.circuit_state)} &middot; ${esc(r.request_id)}</div></div>`;
}
function wirePatients() {
  if (!$('pt-results')) return;
  document.querySelectorAll('[data-op]').forEach(b => b.onclick = async () => {
    if (!selPatient) return alert('Select a patient first.');
    b.disabled = true; $('pt-results').insertAdjacentHTML('afterbegin', '<div class="small" id="pt-wait">Contacting partner...</div>');
    try { const [path, extra] = OPS[b.dataset.op]; const r = await api(path, { method: 'POST', body: { patient_id: selPatient, ...extra } });
      $('pt-results').insertAdjacentHTML('afterbegin', resultCard(r)); } catch (e) { alert(e.message); }
    $('pt-wait')?.remove(); b.disabled = false; loadPatientsPage();
  });
  $('pt-visit').onclick = async () => {
    if (!selPatient) return alert('Select a patient first.');
    $('pt-visit').disabled = true;
    try { const v = await api(`/api/patients/${selPatient}/visit`, { method: 'POST', body: {} });
      $('pt-results').insertAdjacentHTML('afterbegin', `<div class="result-card"><b>Visit ${esc(v.visit_id)}</b> ${chip(v.status)}
        <div class="msg">Core workflow ${v.core_ok ? 'completed' : 'FAILED'} in ${esc(v.duration_ms)} ms.
        ${v.degraded_steps.length ? 'Degraded steps: ' + esc(v.degraded_steps.join(', ')) + '.' : ''}</div>
        <div class="meta">${v.steps.map(s => esc(s.step) + ': ' + esc(s.status)).join(' &rarr; ')}</div></div>`);
    } catch (e) { alert(e.message); }
    $('pt-visit').disabled = false; loadPatientsPage();
  };
  $('pt-register').onclick = async () => {
    try { const r = await api('/api/patients', { method: 'POST', body: { patient_name: $('pt-new-name').value, age: $('pt-new-age').value } });
      selPatient = r.patient.patient_id; $('pt-new-name').value = ''; loadPatientsPage(); } catch (e) { alert(e.message); }
  };
  $('ap-create').onclick = async () => {
    if (!selPatient) return alert('Select a patient first.');
    try { await api('/api/appointments', { method: 'POST', body: { patient_id: selPatient, doctor: $('ap-doctor').value, appointment_date: $('ap-date').value } }); loadPatientsPage(); }
    catch (e) { alert(e.message); }
  };
}

/* ------------------------------------------------------------------ health / dependency map */
async function loadHealth() {
  const d = await api('/api/partners');
  $('health-cards').innerHTML = PARTNERS.map(p => partnerCard(d.partners[p], true)).join('');
}
function wireHealth() {
  if ($('probe-all')) $('probe-all').onclick = async () => { for (const p of PARTNERS) await api(`/api/partners/${p}/health?probe=1`); loadHealth(); };
}
const COLORMAP = { green: '#22c55e', yellow: '#f59e0b', red: '#ef4444', gray: '#94a3b8', blue: '#38bdf8' };
async function loadDepMap() {
  const d = await api('/api/dependencies');
  const core = d.nodes[0], parts = d.nodes.slice(1), W = 860, H = 340;
  let svg = `<svg viewBox="0 0 ${W} ${H}" class="dep-map-svg" style="width:100%;max-height:360px">`;
  const cx = W / 2, cy = 70;
  parts.forEach((n, i) => { const x = 110 + i * ((W - 220) / 3), y = 250;
    svg += `<line x1="${cx}" y1="${cy + 30}" x2="${x}" y2="${y - 38}" stroke="${COLORMAP[n.color]}" stroke-width="3" ${n.color === 'gray' ? 'stroke-dasharray="7 6"' : ''}/>`; });
  svg += `<g><rect x="${cx - 100}" y="${cy - 32}" width="200" height="64" rx="14" fill="#0f172a" stroke="${COLORMAP[core.color]}" stroke-width="4"/>
    <text x="${cx}" y="${cy - 4}" text-anchor="middle" fill="#f8fafc" font-size="17" font-weight="700">Hospital Core</text>
    <text x="${cx}" y="${cy + 18}" text-anchor="middle" fill="${COLORMAP[core.color]}" font-size="13">${esc(core.status)}</text></g>`;
  parts.forEach((n, i) => { const x = 110 + i * ((W - 220) / 3), y = 250;
    svg += `<g class="dep-node" data-id="${n.id}" style="cursor:pointer"><rect x="${x - 88}" y="${y - 38}" width="176" height="76" rx="14" fill="#0f172a" stroke="${COLORMAP[n.color]}" stroke-width="4"/>
      <text x="${x}" y="${y - 8}" text-anchor="middle" fill="#f8fafc" font-size="16" font-weight="600">${esc(n.label)}</text>
      <text x="${x}" y="${y + 12}" text-anchor="middle" fill="${COLORMAP[n.color]}" font-size="12.5">${esc(n.status)}</text>
      <text x="${x}" y="${y + 29}" text-anchor="middle" fill="#94a3b8" font-size="11">circuit ${esc(n.circuit_state)}</text></g>`; });
  svg += '</svg>';
  $('depmap').innerHTML = svg;
  const showDetail = (n) => { $('depmap-detail').innerHTML = `<b>${esc(n.label)}</b>: ${chip(n.status)} &middot; avg latency ${fmt(n.avg_latency_ms, ' ms')} &middot; ${esc(n.impact || '')}`; };
  document.querySelectorAll('.dep-node').forEach(g => g.onclick = () => showDetail(parts.find(p => p.id === g.dataset.id)));
  $('depmap-detail').innerHTML = parts.map(n => `<div>${chip(n.status)} <b>${esc(n.label)}</b> - ${esc(n.impact)}</div>`).join('');
}

/* ------------------------------------------------------------------ simulation */
async function loadSimulation() {
  const d = await api('/api/partners');
  $('sim-state').innerHTML = PARTNERS.map(p => { const s = d.partners[p];
    return `<div class="partner-card" style="margin-bottom:.5rem"><div class="partner-header"><span class="partner-name"><i class="dot dot-${s.color}"></i>${esc(s.display_name)}</span>${chip(s.status)}</div>
      <div class="small">Simulation: <b>${esc(s.simulation.mode)}</b>${s.simulation.remaining_seconds != null ? ' (' + s.simulation.remaining_seconds + 's left)' : ''} &middot; circuit ${chip(s.circuit.state)}
      ${s.circuit.state === 'OPEN' ? ' &middot; test in ' + esc(s.circuit.remaining_open_seconds) + 's' : ''}</div></div>`; }).join('');
}
function wireSimulation() {
  if (!$('sim-start')) return;
  const send = async (path, body, label) => { try { const r = await api(path, { method: 'POST', body });
      $('sim-msg').innerHTML = `<span class="chip chip-green">OK</span> ${esc(label)}`; loadSimulation(); return r; }
    catch (e) { $('sim-msg').innerHTML = `<span class="chip chip-red">Error</span> ${esc(e.message)}`; } };
  const part = () => $('sim-partner').value;
  $('sim-start').onclick = () => { const err = $('sim-error').value;
    send(`/api/partners/${part()}/simulate`, { mode: $('sim-mode').value, latency_ms: $('sim-latency').value || null,
      error_rate: err === '' ? null : Number(err) / 100, duration_seconds: $('sim-duration').value || null }, `Simulation started on ${part()} (${$('sim-mode').value})`); };
  $('sim-stop').onclick = () => send(`/api/partners/${part()}/simulate`, { mode: 'NORMAL' }, `Simulation stopped on ${part()}`);
  $('sim-recover').onclick = () => send(`/api/partners/${part()}/recover`, {}, `${part()} recovered - circuit breaker will test it with the next requests`);
  $('tc-send').onclick = async () => { $('tc-send').disabled = true;
    try { const r = await api(`/api/partners/${part()}/test-call`, { method: 'POST', body: { count: Number($('tc-count').value), mode: $('tc-mode').value } });
      $('tc-results').innerHTML = r.results.map(x => `<tr><td>${esc(x.partner)}</td><td>${chip(x.status)}</td><td>${(x.attempts || []).map(a => esc(a.result)).join(' &rarr; ') || 'none (fail-fast)'}</td>
        <td>${esc(x.retry_count)}</td><td>${esc(x.latency_ms)} ms</td><td>${esc(x.circuit_state)}</td></tr>`).join('') + $('tc-results').innerHTML; } catch (e) { alert(e.message); }
    $('tc-send').disabled = false; loadSimulation(); };
}

/* ------------------------------------------------------------------ experiments */
async function loadExperiments() {
  const d = await api('/api/experiments');
  if (!d.available) { $('exp-summary').innerHTML = 'No results yet. Run <code>python scripts/run_all_experiments.py</code> or use the button above.'; return; }
  const s = d.summary;
  $('exp-summary').innerHTML = `<div class="metrics-grid">
    <div class="metric-card danger"><div class="metric-label">Baseline core availability</div><div class="metric-value">${s.baseline_core_availability_pct.toFixed(2)}%</div></div>
    <div class="metric-card warning"><div class="metric-label">Target</div><div class="metric-value">${s.target_core_availability_pct.toFixed(2)}%</div></div>
    <div class="metric-card success"><div class="metric-label">Resilient core availability</div><div class="metric-value">${s.resilient_core_availability_pct.toFixed(2)}%</div></div>
    <div class="metric-card"><div class="metric-label">Improvement</div><div class="metric-value">+${s.improvement_pp.toFixed(2)} pp</div></div>
    <div class="metric-card"><div class="metric-label">Target</div><div class="metric-value">${s.target_achieved ? 'Achieved' : 'Not achieved'}</div></div></div>
    <div class="small">Run ${esc(s.timestamp)} &middot; ${esc(s.n_scenarios)} scenarios &times; ${esc(s.n_seeds)} seeds &times; ${esc(s.visits_per_scenario)} visits per mode. Virtual-clock simulation, identical workload and partner behaviour for both modes.</div>`;
  const cols = [['scenario', 'Scenario'], ['baseline_core_availability_pct', 'Baseline avail %'], ['resilient_core_availability_pct', 'Resilient avail %'], ['baseline_avg_latency_ms', 'Base avg ms'], ['resilient_avg_latency_ms', 'Res avg ms'],
    ['baseline_p95_latency_ms', 'Base p95 ms'], ['resilient_p95_latency_ms', 'Res p95 ms'], ['resilient_retry_count', 'Retries'], ['resilient_fallback_count', 'Fallbacks'], ['resilient_circuit_open_count', 'Circuit opens'], ['resilient_recovery_time_s', 'Recovery s']];
  $('exp-table').innerHTML = `<table><thead><tr>${cols.map(c => `<th>${c[1]}</th>`).join('')}</tr></thead><tbody>` +
    (d.comparison || []).map(r => `<tr>${cols.map(c => `<td>${esc(r[c[0]] === null ? '-' : r[c[0]])}</td>`).join('')}</tr>`).join('') + '</tbody></table>';
  $('exp-figs').innerHTML = d.figures.map(f => `<div><img src="/outputs/figures/${esc(f)}?t=${Date.now()}" alt="${esc(f)}"><div class="small">${esc(f)}</div></div>`).join('');
}
function wireExperiments() {
  if (!$('exp-run')) return;
  $('exp-run').onclick = async () => { $('exp-run').disabled = true; $('exp-summary').textContent = 'Running all scenarios (virtual clock)...';
    try { await api('/api/experiments/run', { method: 'POST', body: {} }); } catch (e) { alert(e.message); }
    $('exp-run').disabled = false; loadExperiments(); };
}

/* ------------------------------------------------------------------ logs */
async function loadLogs() {
  const p = $('log-partner').value;
  const d = await api('/api/logs?limit=150' + (p ? '&partner=' + p : ''));
  $('log-calls').innerHTML = d.calls.map(c => `<tr><td>${esc(tm(c.timestamp))}</td><td>${esc(c.request_id)}</td><td>${esc(c.partner)}</td><td>${esc(c.operation)}</td><td>${esc(c.latency_ms)} ms</td>
    <td>${chip(c.status)}</td><td>${esc(c.error_type || '-')}</td><td>${esc(c.retry_count)}</td><td>${esc(c.circuit_state)}</td><td>${c.fallback_used ? 'yes' : 'no'}</td><td>${esc(c.mode)}</td></tr>`).join('');
  $('log-attempts').innerHTML = d.attempts.slice(-100).reverse().map(a => `<tr><td>${esc(a.request_id)}</td><td>${esc(a.partner)}</td><td>${esc(a.attempt)}</td><td>${esc(a.result)}</td><td>${esc(a.latency_ms)} ms</td></tr>`).join('');
  $('log-events').innerHTML = d.circuit_events.map(e => `<tr><td>${esc(tm(e.timestamp))}</td><td>${esc(e.partner)}</td><td>${chip(e.old_state)} &rarr; ${chip(e.new_state)}</td><td>${esc(e.reason)}</td></tr>`).join('') +
    d.failure_events.map(e => `<tr><td>${esc(tm(e.timestamp))}</td><td>${esc(e.partner)}</td><td>${esc(e.failure_type)} (${esc(e.severity)})</td><td>${e.resolved ? 'resolved, recovery ' + fmt(e.recovery_time, 's') : 'active'}</td></tr>`).join('');
}
function wireLogs() { if ($('log-refresh')) { $('log-refresh').onclick = loadLogs; $('log-partner').onchange = loadLogs; } }

/* ------------------------------------------------------------------ configuration */
let cfg = null;
async function loadConfig() {
  cfg = await api('/api/config');
  const canWrite = perms.includes('config_write');
  $('cfg-mode').textContent = canWrite ? 'editable' : 'read-only';
  const dis = canWrite ? '' : 'disabled';
  $('cfg-timeouts').innerHTML = PARTNERS.map(p => `<div class="form-group"><label>${p}</label><input class="form-control" data-k="timeout.${p}" type="number" step="0.1" value="${cfg.resilience.timeout[p]}" ${dis}></div>`).join('');
  $('cfg-retry-attempts').value = cfg.resilience.retry.max_attempts; $('cfg-retry-backoff').value = cfg.resilience.retry.backoff_seconds;
  $('cfg-cb-threshold').value = cfg.resilience.circuit_breaker.failure_threshold; $('cfg-cb-recovery').value = cfg.resilience.circuit_breaker.recovery_timeout_seconds;
  ['cfg-retry-attempts', 'cfg-retry-backoff', 'cfg-cb-threshold', 'cfg-cb-recovery'].forEach(i => $(i).disabled = !canWrite);
  $('cfg-partners').innerHTML = PARTNERS.map(p => `<div class="row"><div class="form-group"><label>${p} latency (ms)</label><input class="form-control" data-k="lat.${p}" type="number" value="${cfg.partners[p].latency_ms}" ${dis}></div>
    <div class="form-group"><label>${p} error rate (%)</label><input class="form-control" data-k="err.${p}" type="number" step="1" min="0" max="100" value="${Math.round(cfg.partners[p].failure_rate * 10000) / 100}" ${dis}></div></div>`).join('');
}
function wireConfig() {
  if (!$('cfg-save')) return;
  $('cfg-save').onclick = async () => {
    const timeout = {}, partners = {};
    document.querySelectorAll('[data-k]').forEach(el => { const [kind, p] = el.dataset.k.split('.');
      if (kind === 'timeout') timeout[p] = Number(el.value);
      else { partners[p] = partners[p] || {}; if (kind === 'lat') partners[p].latency_ms = Number(el.value); else partners[p].failure_rate = Number(el.value) / 100; } });
    const body = { resilience: { timeout, retry: { max_attempts: Number($('cfg-retry-attempts').value), backoff_seconds: Number($('cfg-retry-backoff').value) },
      circuit_breaker: { failure_threshold: Number($('cfg-cb-threshold').value), recovery_timeout_seconds: Number($('cfg-cb-recovery').value) } }, partners };
    try { await api('/api/config', { method: 'POST', body }); $('cfg-msg').innerHTML = '<div class="banner">Configuration saved and applied to the running simulation.</div>'; }
    catch (e) { $('cfg-msg').innerHTML = `<div class="banner err"><b>Not saved:</b><br>${(e.details || [e.message]).map(esc).join('<br>')}</div>`; }
  };
}

/* ------------------------------------------------------------------ validation */
async function loadValidation() {
  if (!$('val-form').dataset.ready) {
    const q = await api('/api/validation/questions');
    $('val-form').innerHTML = q.questions.map(x => x.type === 'likert'
      ? `<div><div>${esc(x.text)}</div><div class="likert">${[1, 2, 3, 4, 5].map(n => `<label><input type="radio" name="${x.id}" value="${n}"> ${n}</label>`).join('')}<span class="small">1 = strongly disagree, 5 = strongly agree</span></div></div>`
      : `<div class="form-group"><label>${esc(x.text)}</label><textarea class="form-control" id="${x.id}"></textarea></div>`).join('');
    $('val-form').dataset.ready = '1';
  }
  if (perms.includes('validation_view') && $('val-summary')) {
    const d = await api('/api/validation'); const s = d.summary;
    if (!Object.keys(s.roles).length) { $('val-summary').innerHTML = 'No responses collected yet.'; return; }
    $('val-summary').innerHTML = Object.entries(s.roles).map(([role, r]) => `<div style="margin-bottom:.8rem"><b>${esc(role)}</b> - ${r.submissions} submission(s)
      <table><tbody>${Object.entries(r.questions).map(([q, v]) => `<tr><td>${esc(q)}</td><td>${fmt(v.mean)} (n=${v.n})</td></tr>`).join('')}</tbody></table>
      ${r.improvement_comments.map(c => `<div class="small">&ldquo;${esc(c)}&rdquo;</div>`).join('')}</div>`).join('');
  }
}
function wireValidation() {
  if (!$('val-submit')) return;
  $('val-submit').onclick = async () => {
    const answers = {}; document.querySelectorAll('#val-form input[type=radio]:checked').forEach(r => answers[r.name] = r.value);
    answers.q7 = $('q7') ? $('q7').value : '';
    try { await api('/api/validation', { method: 'POST', body: { answers } }); $('val-msg').innerHTML = '<span class="chip chip-green">Thank you</span> Feedback stored.';
      document.querySelectorAll('#val-form input[type=radio]').forEach(r => r.checked = false); if ($('q7')) $('q7').value = ''; loadValidation(); }
    catch (e) { $('val-msg').innerHTML = `<span class="chip chip-red">Error</span> ${esc(e.message)}`; }
  };
  if ($('val-regen')) $('val-regen').onclick = async () => { await api('/api/validation/summary', { method: 'POST', body: {} }); alert('docs/user_feedback_summary.md regenerated.'); };
}

/* ------------------------------------------------------------------ reports */
async function loadReports() {
  const d = await api('/api/reports');
  $('rep-list').innerHTML = d.reports.filter(r => r.exists).map(r => `<div data-k="${r.key}">${esc(r.path)}</div>`).join('');
  $('rep-list').querySelectorAll('div').forEach(el => el.onclick = async () => {
    $('rep-list').querySelectorAll('div').forEach(x => x.classList.remove('sel')); el.classList.add('sel');
    const r = await api('/api/reports/' + el.dataset.k); $('rep-body').innerHTML = r.html; });
}

/* ------------------------------------------------------------------ boot */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.tab-btn').forEach(b => b.onclick = () => show(b.dataset.page));
  wirePatients(); wireHealth(); wireSimulation(); wireExperiments(); wireLogs(); wireConfig(); wireValidation();
  const first = document.querySelector('.tab-btn'); if (!first) return;
  const wanted = (location.hash || '').slice(1);
  show(document.querySelector(`.tab-btn[data-page="${wanted}"]`) ? wanted : first.dataset.page);
  pollTimer = setInterval(() => { if (['dashboard', 'patients', 'health', 'depmap', 'simulation'].includes(currentPage) && !document.hidden) refresh(); }, 3000);
});
