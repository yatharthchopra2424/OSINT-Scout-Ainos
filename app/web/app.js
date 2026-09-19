/* OSINT Scout — operator console.
   Plain JavaScript, no build step. Every view here reads a real endpoint; nothing
   on this page is mocked. */

const api = {
  async get(path)        { const r = await fetch(path); if (!r.ok) throw new Error(await r.text()); return r.json(); },
  async text(path)       { const r = await fetch(path); return r.text(); },
  async send(path, body, method = 'POST') {
    const r = await fetch(path, {
      method, headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) throw new Error((await r.text()).slice(0, 400));
    return r.json();
  },
};

const $  = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const shortTime = (iso) => (iso ? String(iso).replace('T', ' ').slice(0, 19) : '');
const arrow = (d) => (d === 'up' ? '▲ up' : d === 'down' ? '▼ down' : '– flat');

let state = { runs: [], selectedRun: null };

/* ─────────────────────────── tabs ─────────────────────────── */
document.querySelectorAll('nav button').forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll('nav button').forEach((b) => b.classList.remove('active'));
    document.querySelectorAll('section').forEach((s) => s.classList.remove('active'));
    btn.classList.add('active');
    $(btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'deals') loadPipeline();
    if (btn.dataset.tab === 'rules') loadRules();
    if (btn.dataset.tab === 'evaluation') loadEvalResults();
    if (btn.dataset.tab === 'logs') loadLogRuns();
  };
});

/* ─────────────────────────── header ─────────────────────────── */
/* Public demo: say so, and lock what the server will refuse rather than let a
   visitor click into a 403. The server enforces all of this independently. */
function applyDemoMode(h) {
  const banner = $('demoBanner');
  if (banner) {
    banner.style.display = 'none';
    banner.innerHTML = '';
  }

  // Extractor / sources / embeddings: only the deterministic path exists here.
  for (const [id, value] of [['runExtract', 'baseline'], ['runSource', 'fixture'], ['runEmbed', 'lexical'],
                             ['evalExtract', 'baseline'], ['evalEmbed', 'lexical']]) {
    const el = $(id);
    if (!el) continue;
    el.value = value;
    el.disabled = true;
    el.classList.add('locked');
  }
  for (const id of ['rulesSave', 'evalRun', 'wlAdd']) {
    const el = $(id);
    if (!el) continue;
    el.disabled = true;
    el.classList.add('locked');
    el.title = 'Disabled on the public demo';
  }
  for (const id of ['rulesText', 'wlName', 'wlDomain', 'wlNotes', 'runDomain']) {
    const el = $(id);
    if (el) { el.readOnly = true; el.classList.add('locked'); }
  }
  const smoke = $('smokeBtn');
  if (smoke) { smoke.disabled = true; smoke.classList.add('locked'); smoke.title = 'Model calls are off on the demo'; }
}

async function loadHealth() {
  const h = await api.get('/api/health');
  state.demo = !!h.demo_mode;
  if (state.demo) applyDemoMode(h);
  $('chips').innerHTML = [
    `<span class="chip ${h.nvidia_key_present ? 'on' : 'off'}">NVIDIA key <b>${h.nvidia_key_present ? 'present' : 'missing'}</b></span>`,
    `<span class="chip">sources <b>${esc(h.source_mode)}</b></span>`,
    `<span class="chip">embeddings <b>${esc(h.embed_backend)}</b></span>`,
    `<span class="chip">vectors <b>${esc(h.vector_backend)}</b></span>`,
    `<span class="chip">k <b>${h.retrieval_k}</b></span>`,
    `<span class="chip">gate <b>${h.support_threshold}</b></span>`,
  ].join('');
  $('runSource').value = h.source_mode;
  $('runEmbed').value = h.embed_backend;
  if (!h.nvidia_key_present) { $('runExtract').value = 'baseline'; }
}

async function loadArchitecture() {
  const { nodes } = await api.get('/api/architecture');
  $('pipelineSteps').innerHTML = nodes.map((n, i) => `
    <div class="step ${n.model.startsWith('none') ? 'pure' : ''}">
      <div class="n">${i + 1}. ${esc(n.node)}</div>
      <div class="d">${esc(n.does)}</div>
      <div class="m">${esc(n.model)}</div>
    </div>`).join('');
}

$('smokeBtn').onclick = async () => {
  $('smokeStatus').textContent = 'calling the models…';
  try {
    const r = await api.get('/api/smoke');
    $('smokeOut').style.display = 'block';
    $('smokeOut').textContent = JSON.stringify(r, null, 2);
    $('smokeStatus').textContent = r.chat?.ok ? 'chat and embeddings both responded' : 'embeddings only — no usable chat model';
  } catch (e) { $('smokeStatus').textContent = 'failed: ' + e.message; }
};

/* ─────────────────────────── watchlist ─────────────────────────── */
async function loadWatchlist() {
  const rows = await api.get('/api/watchlist');
  $('wlBody').innerHTML = rows.length ? rows.map((a) => `
    <tr>
      <td>${esc(a.name)}</td>
      <td class="mono">${esc(a.domain || '')}</td>
      <td style="color:var(--muted)">${esc(a.notes || '')}</td>
      <td>
        <button class="ghost" data-run="${esc(a.name)}" data-domain="${esc(a.domain || '')}">Run</button>
        ${state.demo ? '' : `<button class="ghost" data-del="${esc(a.name)}">Remove</button>`}
      </td>
    </tr>`).join('') : '<tr><td colspan="4" class="empty">Nothing on the watchlist.</td></tr>';

  $('wlBody').querySelectorAll('[data-del]').forEach((b) => {
    b.onclick = async () => { await api.send('/api/watchlist/' + encodeURIComponent(b.dataset.del), undefined, 'DELETE'); loadWatchlist(); };
  });
  $('wlBody').querySelectorAll('[data-run]').forEach((b) => {
    b.onclick = () => { $('runName').value = b.dataset.run; $('runDomain').value = b.dataset.domain; $('runBtn').click(); };
  });
}

$('wlAdd').onclick = async () => {
  const name = $('wlName').value.trim();
  if (!name) return;
  await api.send('/api/watchlist', { name, domain: $('wlDomain').value.trim(), notes: $('wlNotes').value.trim() });
  $('wlName').value = $('wlDomain').value = $('wlNotes').value = '';
  loadWatchlist();
};

/* The eight nodes, in order, so progress can be drawn before any of them report. */
const NODE_ORDER = ['ingest', 'index', 'retrieve', 'extract', 'verify', 'score', 'diff', 'deliver'];

function renderProgress(s, account) {
  const done = new Map((s.completed_nodes || []).map((n) => [n.node, n.ms]));
  const elapsed = s.elapsed_seconds != null ? `${s.elapsed_seconds}s` : '';

  $('runProgress').innerHTML = `
    <div class="progress">
      <div class="progress-head">
        <b>${esc(account)}</b>
        <span>${s.state === 'running' ? 'running' : s.state}</span>
        <span class="mono">${elapsed}</span>
      </div>
      <div class="nodes">
        ${NODE_ORDER.map((n) => {
          const isDone = done.has(n);
          const isNow = s.current_node === n;
          return `<span class="node-chip ${isDone ? 'done' : isNow ? 'now' : ''}">${esc(n)}${
            isDone && done.get(n) != null ? ` <i>${done.get(n)}ms</i>` : ''}</span>`;
        }).join('')}
      </div>
      ${(s.warnings || []).length
        ? `<div class="progress-warn">${s.warnings.map(esc).join(' · ')}</div>` : ''}
      ${s.error ? `<div class="progress-err">${esc(s.error)}</div>` : ''}
    </div>`;
}

async function followRun(runId, account) {
  try { localStorage.setItem('osint_active_run', JSON.stringify({ runId, account })); } catch {}

  while (true) {
    let s;
    try {
      s = await api.get(`/api/runs/${runId}/status`);
    } catch (e) {
      $('runStatus').textContent = 'lost contact with the server — the run may still be going. Reload to reattach.';
      return;
    }
    renderProgress(s, account);

    if (s.state === 'done') {
      try { localStorage.removeItem('osint_active_run'); } catch {}
      const brief = await api.get(`/api/runs/${runId}`);
      $('runStatus').textContent =
        `${brief.account}: ${brief.facts.length} verified, ${brief.dropped.length} dropped, ` +
        `score ${brief.score.total} (${brief.score.band}) in ${s.elapsed_seconds ?? '?'}s.`;
      await loadRuns();
      await loadDigest();
      if (state.pipeline) loadPipeline();
      showBrief(runId);
      document.querySelector('nav button[data-tab="briefs"]').click();
      return;
    }
    if (s.state === 'error' || s.state === 'unknown') {
      try { localStorage.removeItem('osint_active_run'); } catch {}
      $('runStatus').textContent = s.error ? 'failed: ' + s.error : 'the run did not finish.';
      return;
    }

    await new Promise((r) => setTimeout(r, 1500));
  }
}

$('runBtn').onclick = async () => {
  const name = $('runName').value.trim();
  if (!name) { $('runStatus').textContent = 'Enter a company name first.'; return; }

  $('runBtn').disabled = true;
  $('runStatus').textContent =
    $('runExtract').value === 'llm'
      ? 'started — the reasoning model takes several minutes. You can leave this tab.'
      : 'started…';
  try {
    const job = await api.send('/api/runs', {
      name,
      domain: $('runDomain').value.trim(),
      source_mode: $('runSource').value,
      extract_mode: $('runExtract').value,
      embed_backend: $('runEmbed').value,
    });
    await followRun(job.run_id, job.account);
  } catch (e) {
    $('runStatus').textContent = 'failed to start: ' + e.message;
  } finally { $('runBtn').disabled = false; }
};

async function loadDigest() {
  const rows = await api.get('/api/digest');
  $('digestBody').innerHTML = rows.length ? rows.map((r) => `
    <tr>
      <td>${esc(r.account)}</td>
      <td class="num">${r.score}</td>
      <td><span class="badge ${esc(r.band)}">${esc(r.band)}</span></td>
      <td class="dir-${esc(r.direction)}">${arrow(r.direction)}</td>
      <td class="num">${(r.delta?.new_facts || []).length}</td>
      <td class="mono" style="color:var(--muted)">${shortTime(r.generated_at)}</td>
    </tr>`).join('') : '<tr><td colspan="6" class="empty">No runs yet.</td></tr>';
}

/* ─────────────────────────── pipeline ─────────────────────────── */
async function loadPipeline() {
  if (!state.stages) state.stages = await api.get('/api/stages');
  const p = await api.get('/api/pipeline');
  state.pipeline = p;

  $('stageFlow').innerHTML = p.stages.map((s) => `
    <div class="stagebox ${s.count ? '' : 'empty'} ${s.key === 'won' ? 'won' : s.key === 'lost' ? 'lost' : ''}">
      <div class="c">${s.count}</div><div class="l">${esc(s.label)}</div>
    </div>`).join('');

  $('pipeKpis').innerHTML = [
    ['accounts', p.totals.accounts, ''],
    ['open', p.totals.open, ''],
    ['needs attention', p.stale.length, p.stale.length ? 'alert' : ''],
    ['moved up', p.movers.length, p.movers.length ? 'good' : ''],
    ['high band', p.bands.High, p.bands.High ? 'good' : ''],
    ['medium band', p.bands.Medium, ''],
    ['low band', p.bands.Low, ''],
  ].map(([k, v, cls]) => `<div class="kpi ${cls}"><div class="v">${v}</div><div class="k">${esc(k)}</div></div>`).join('');

  const leadLine = (r, stale) => `
    <div class="leadrow ${stale ? 'stale' : ''}">
      <div class="n">${esc(r.account)} — <span class="badge ${esc(r.band || 'Low')}">${esc(r.band || '—')}</span></div>
      <div class="m">${esc(r.stage_label)} · idle ${r.days_idle}d${r.owner ? ' · ' + esc(r.owner) : ''}</div>
    </div>`;

  $('staleList').innerHTML = p.stale.length
    ? p.stale.map((r) => leadLine(r, true)).join('')
    : `<div class="empty">Nothing has gone quiet — no open account is more than ${p.stale_after_days} days idle.</div>`;

  $('moversList').innerHTML = p.movers.length
    ? p.movers.map((r) => leadLine(r, false)).join('')
    : '<div class="empty">No account moved up a band on its latest run.</div>';

  $('convBody').innerHTML = p.conversion.map((c) => `
    <tr>
      <td>${esc(c.from)} → ${esc(c.to)}</td>
      <td class="num">${c.to_count}</td>
      <td class="num">${c.from_count}</td>
      <td class="num">${c.rate === null ? '—' : (c.rate * 100).toFixed(0) + '%'}</td>
    </tr>`).join('') || '<tr><td colspan="4" class="empty">No accounts yet.</td></tr>';

  $('leadsBody').innerHTML = p.rows.length ? p.rows.map((r) => `
    <tr>
      <td>${esc(r.account)}</td>
      <td><select data-stage-for="${esc(r.account_id)}">
        ${state.stages.map((s) => `<option value="${esc(s.key)}" ${s.key === r.stage ? 'selected' : ''}>${esc(s.label)}</option>`).join('')}
      </select></td>
      <td><input data-owner-for="${esc(r.account_id)}" value="${esc(r.owner)}" placeholder="unassigned"></td>
      <td class="num">${r.score ?? '—'}</td>
      <td><span class="badge ${esc(r.band || 'Low')}">${esc(r.band || '—')}</span></td>
      <td class="num" style="${r.stale ? 'color:var(--warn)' : ''}">${r.days_idle}d</td>
      <td class="mono" style="color:var(--muted)">${shortTime(r.last_run)}</td>
      <td><button class="ghost" data-tl-for="${esc(r.account_id)}" data-name="${esc(r.account)}">Timeline</button></td>
    </tr>`).join('') : '<tr><td colspan="8" class="empty">No accounts tracked yet — run one from the Watchlist tab.</td></tr>';

  $('leadsBody').querySelectorAll('[data-stage-for]').forEach((sel) => {
    sel.onchange = async () => {
      await api.send(`/api/leads/${sel.dataset.stageFor}/stage`, { stage: sel.value }, 'PUT');
      loadPipeline();
    };
  });
  $('leadsBody').querySelectorAll('[data-owner-for]').forEach((inp) => {
    inp.onchange = async () => {
      await api.send(`/api/leads/${inp.dataset.ownerFor}/owner`, { owner: inp.value }, 'PUT');
    };
  });
  $('leadsBody').querySelectorAll('[data-tl-for]').forEach((btn) => {
    btn.onclick = () => showTimeline(btn.dataset.tlFor, btn.dataset.name);
  });
}

async function showTimeline(accountId, name) {
  const events = await api.get(`/api/leads/${accountId}/timeline`);
  $('leadTimeline').innerHTML = `
    <div class="panel" style="margin-top:16px">
      <h2>${esc(name)} — activity</h2>
      <p class="hint">Written automatically. Nobody typed any of this.</p>
      <div class="tl">${events.map((e) => `
        <div class="ev">
          <span class="t">${esc(String(e.ts).replace('T', ' ').slice(0, 16))}</span>
          <span class="k">${esc(e.kind)}</span>
          <span>${esc(e.detail)}</span>
        </div>`).join('') || '<div class="empty">Nothing logged yet.</div>'}</div>
    </div>`;
}

/* ─────────────────────────── briefs ─────────────────────────── */
async function loadRuns() {
  state.runs = await api.get('/api/runs');
  renderRuns();
}

/* The runs list grows fast — the eval alone writes eighteen rows. Default to the
   latest run per account so the table stays the size of the watchlist, and keep
   the full history one checkbox away. */
function visibleRuns() {
  const term = ($('runFilter').value || '').trim().toLowerCase();
  let rows = state.runs;

  if (!$('showAllRuns').checked) {
    const seen = new Set();
    rows = rows.filter((r) => (seen.has(r.account_id) ? false : seen.add(r.account_id)));
  }
  if (term) rows = rows.filter((r) => r.account.toLowerCase().includes(term));
  return rows;
}

function renderRuns() {
  const rows = visibleRuns();
  $('runCount').textContent = `${rows.length} of ${state.runs.length} run${state.runs.length === 1 ? '' : 's'}`;

  $('runsBody').innerHTML = rows.length ? rows.map((r) => `
    <tr class="clickable ${r.run_id === state.selectedRun ? 'selected' : ''}" data-run="${esc(r.run_id)}">
      <td>${esc(r.account)}</td>
      <td class="mono" style="color:var(--muted)">${esc(r.run_id)}</td>
      <td class="num">${r.facts}</td>
      <td class="num">${r.dropped}</td>
      <td class="num">${r.score}</td>
      <td><span class="badge ${esc(r.band)}">${esc(r.band)}</span></td>
      <td class="dir-${esc(r.direction)}">${arrow(r.direction)}</td>
      <td class="mono" style="color:var(--muted)">${shortTime(r.generated_at)}</td>
    </tr>`).join('')
    : `<tr><td colspan="8" class="empty">${state.runs.length
        ? 'Nothing matches that filter.'
        : 'No runs yet — go to the Watchlist tab and run an account.'}</td></tr>`;

  $('runsBody').querySelectorAll('[data-run]').forEach((tr) => {
    tr.onclick = () => showBrief(tr.dataset.run);
  });
}

$('runFilter').oninput = renderRuns;
$('showAllRuns').onchange = renderRuns;

/* Copy-to-clipboard, delegated so it works on markup rendered after load. */
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('button.copy');
  if (!btn) return;
  const source = btn.dataset.copyFrom ? $(btn.dataset.copyFrom) : null;
  const text = source ? (source.value ?? source.textContent) : (btn.dataset.copy || '');
  try {
    await navigator.clipboard.writeText(text);
    const original = btn.textContent;
    btn.textContent = 'copied'; btn.classList.add('done');
    setTimeout(() => { btn.textContent = original; btn.classList.remove('done'); }, 1400);
  } catch { btn.textContent = 'copy failed'; }
});

async function showBrief(runId) {
  state.selectedRun = runId;
  const b = await api.get('/api/runs/' + runId);
  await loadRuns();

  const fact = (f, dropped) => `
    <div class="fact ${dropped ? 'dropped' : ''}">
      <div class="meta">${esc(f.type.replace(/_/g, ' '))} · ${esc(f.event_date || 'undated')} · support ${f.support_score}${dropped ? ' · DROPPED' : ''}</div>
      <div class="statement">${esc(f.statement)}</div>
      <div class="src"><a href="${esc(f.source_url)}" target="_blank" rel="noopener">${esc(f.source_url)}</a></div>
      ${dropped ? `<div class="meta" style="margin-top:3px">reason: ${esc(f.reason)}</div>` : ''}
    </div>`;

  const delta = b.delta.is_first_run
    ? '<div class="empty">First run for this account — nothing to compare against yet.</div>'
    : `<p>Band <b>${esc(b.delta.band_before)}</b> → <b>${esc(b.delta.band_after)}</b>
         <span class="dir-${esc(b.delta.direction)}">${arrow(b.delta.direction)}</span></p>
       ${b.delta.new_facts.length ? '<p><b>New since last run</b></p><ul>' + b.delta.new_facts.map((s) => `<li>${esc(s)}</li>`).join('') + '</ul>' : ''}
       ${b.delta.dropped_facts.length ? '<p><b>No longer present</b></p><ul>' + b.delta.dropped_facts.map((s) => `<li>${esc(s)}</li>`).join('') + '</ul>' : ''}
       ${!b.delta.new_facts.length && !b.delta.dropped_facts.length ? '<div class="empty">Nothing changed since the previous run.</div>' : ''}`;

  $('briefDetail').innerHTML = `
    <div class="panel">
      <h2>${esc(b.account)} — signal ${b.score.total} <span class="badge ${esc(b.score.band)}">${esc(b.score.band)}</span></h2>
      <p class="hint">
        run <code>${esc(b.run_id)}</code> · ${esc(b.source_mode)} sources ·
        ${b.documents_used} documents · ${b.chunks_indexed} chunks indexed ·
        ${b.retries} retrieval retr${b.retries === 1 ? 'y' : 'ies'} ·
        <a href="/api/runs/${esc(b.run_id)}/markdown" target="_blank">markdown</a>
      </p>
      <p>${esc(b.summary)}</p>
      ${b.errors.length ? `<p style="color:var(--warn)">${b.errors.map(esc).join('<br>')}</p>` : ''}
    </div>

    <div class="grid2">
      <div class="panel">
        <h2>Verified facts (${b.facts.length})</h2>
        <p class="hint">Each one survived the verify gate and links to the page it was read from.</p>
        ${b.facts.length ? b.facts.map((f) => fact(f, false)).join('') : '<div class="empty">Nothing survived verification.</div>'}
      </div>
      <div class="panel">
        <h2>Why this score</h2>
        <p class="hint">Rules from <code>rules.yml</code>, not the model's opinion.</p>
        ${b.score.lines.length ? `<table><tbody>${b.score.lines.map((l) => `
          <tr><td class="mono">${esc(l.rule)}</td><td class="num">${l.points > 0 ? '+' : ''}${l.points}</td>
          <td style="color:var(--muted)">${esc(l.because)}</td></tr>`).join('')}</tbody></table>`
          : '<div class="empty">No rules fired.</div>'}
      </div>
    </div>

    <div class="grid2">
      <div class="panel"><h2>What changed</h2>${delta}</div>
      <div class="panel">
        <h2>Gaps</h2>
        <p class="hint">What it looked for and could not find. Reported rather than glossed over.</p>
        ${b.gaps.length ? '<ul>' + b.gaps.map((g) => `<li>${esc(g)}</li>`).join('') + '</ul>' : '<div class="empty">Nothing missing.</div>'}
      </div>
    </div>

    <div class="panel">
      <h2>Dropped by the verifier (${b.dropped.length})</h2>
      <p class="hint">
        Claims the sources did not support. Kept visible on purpose — knowing what was
        thrown away is what makes the rest believable.
      </p>
      ${b.dropped.length ? b.dropped.map((f) => fact(f, true)).join('') : '<div class="empty">Nothing was dropped.</div>'}
    </div>

    <div class="panel" id="outreachPanel">
      <h2>Outreach</h2>
      <p class="hint">
        Drafts an email grounded in the verified facts above — useful before anyone has
        vetted the lead, because the draft names exactly which facts it used and refuses
        to write at all when there is nothing verified to open on. Intent decides which
        fact it opens on and triggers a second, intent-shaped retrieval over the same sources.
      </p>
      <div class="row">
        <div style="max-width:220px"><label>Intent</label><select id="emIntent"></select></div>
        <div><label>Your name</label><input id="emName" placeholder="Yatharth Chopra"></div>
        <div><label>Your company</label><input id="emCompany" placeholder="AIONOS"></div>
        <div style="min-width:240px"><label>What you do (one line)</label>
          <input id="emOffer" placeholder="We build agentic AI for travel and logistics operations"></div>
        <button class="act" id="emDraft">Draft email</button>
      </div>
      <p style="color:var(--dim);font-size:12.5px;margin:-4px 0 14px" id="emIntentHint"></p>
      <div id="emOut"></div>
    </div>`;

  mountOutreach(b);
  $('briefDetail').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ─────────────────────────── outreach ─────────────────────────── */
async function mountOutreach(brief) {
  if (!state.intents) state.intents = await api.get('/api/intents');

  const sel = $('emIntent');
  sel.innerHTML = state.intents.map((i) => `<option value="${esc(i.key)}">${esc(i.label)}</option>`).join('');

  const describe = () => {
    const chosen = state.intents.find((i) => i.key === sel.value);
    $('emIntentHint').textContent = chosen ? `${chosen.description} — ${chosen.ask}` : '';
  };
  sel.onchange = describe;
  describe();

  // Remember the sender so it is not retyped for every account.
  ['emName', 'emCompany', 'emOffer'].forEach((id) => {
    try { $(id).value = localStorage.getItem('osint_' + id) || ''; } catch {}
    $(id).oninput = () => { try { localStorage.setItem('osint_' + id, $(id).value); } catch {} };
  });

  $('emDraft').onclick = () => draftEmail(brief.run_id);
}

function styleBlock(style) {
  if (style.score === null) return '';
  const cls = style.score >= 80 ? 'good' : style.score >= 55 ? 'mid' : 'bad';
  const stats = Object.entries(style.stats || {}).map(([k, v]) =>
    `<div class="stat"><div class="v">${v}</div><div class="k">${esc(k.replace(/_/g, ' '))}</div></div>`).join('');

  return `
    <div class="score-head">
      <span class="score-big ${cls}">${style.score}</span>
      <span class="score-verdict">/ 100 — ${esc(style.verdict)}</span>
    </div>
    ${style.flags.length ? `<ul class="flags">${style.flags.map((f) => `
      <li class="flag ${f.severity >= 15 ? 'big' : ''}">
        <div class="name">${esc(f.check)} −${f.severity}</div>
        <div class="what">${esc(f.message)}</div>
        ${f.evidence ? `<div class="ev">${esc(f.evidence)}</div>` : ''}
      </li>`).join('')}</ul>`
      : '<div class="empty">Nothing flagged. Reads like a person wrote it.</div>'}
    <div class="stats">${stats}</div>`;
}

function renderEmail(runId, draft) {
  if (draft.blocked) {
    $('emOut').innerHTML = `
      <div class="blocked">
        <b>Refused to draft.</b> ${esc(draft.blocked_reason)}.
        <p style="margin:8px 0 0;color:var(--muted)">${esc(draft.body)}</p>
      </div>`;
    return;
  }

  $('emOut').innerHTML = `
    <div class="email-wrap">
      <div>
        <div class="email-field">
          <label>Subject</label>
          <input id="emSubject" value="${esc(draft.subject)}">
        </div>
        <div class="email-field">
          <label>Body — edit freely, the checker re-scores as you type</label>
          <textarea id="emBody">${esc(draft.body)}</textarea>
        </div>
        <div class="row" style="margin-bottom:0">
          <button class="act" id="emRevise">Fix the flagged problems</button>
          <button class="copy" data-copy-from="emBody">copy body</button>
          <button class="copy" data-copy-from="emSubject">copy subject</button>
          <span class="status" id="emStatus">drafted by ${esc(draft.engine)}</span>
        </div>
        <div class="used">
          Grounded in: ${draft.facts_used.map((f) => `<code>${esc(f.type)}</code>`).join(' ') || 'nothing'}
          · second-hop passages retrieved: ${draft.context_passages.length}
        </div>
      </div>
      <div>
        <h2 style="font-size:13px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);margin:0 0 4px">Style check</h2>
        <p class="hint" style="margin-bottom:12px">
          Pure Python, no model. Catches stock openers, consultant filler, hedging,
          essay connectives and sentences nobody would say out loud — and whether the
          email says anything specific at all.
        </p>
        <div id="emStyle">${styleBlock(draft.style)}</div>
      </div>
    </div>`;

  let timer;
  $('emBody').oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const style = await api.send('/api/email/check', { run_id: runId, body: $('emBody').value });
      $('emStyle').innerHTML = styleBlock(style);
    }, 400);
  };

  $('emRevise').onclick = async () => {
    $('emRevise').disabled = true;
    $('emStatus').textContent = 'revising…';
    try {
      const r = await api.send('/api/email/revise', {
        run_id: runId, subject: $('emSubject').value, body: $('emBody').value,
      });
      $('emBody').value = r.body;
      $('emStyle').innerHTML = styleBlock(r.style);
      $('emStatus').textContent = r.engine === 'unchanged'
        ? 'nothing to fix'
        : `revised (${r.engine}) — now ${r.style.score}/100`;
    } catch (e) { $('emStatus').textContent = 'failed: ' + e.message; }
    finally { $('emRevise').disabled = false; }
  };
}

async function draftEmail(runId) {
  $('emDraft').disabled = true;
  $('emOut').innerHTML = '<div class="empty">Drafting…</div>';
  try {
    const draft = await api.send(`/api/runs/${runId}/email`, {
      intent: $('emIntent').value,
      sender: { name: $('emName').value, company: $('emCompany').value, offer: $('emOffer').value },
    });
    renderEmail(runId, draft);
  } catch (e) {
    $('emOut').innerHTML = `<div class="blocked">Failed: ${esc(e.message)}</div>`;
  } finally { $('emDraft').disabled = false; }
}

/* ─────────────────────────── logs ─────────────────────────── */
async function loadLogRuns() {
  if (!state.runs.length) await loadRuns();
  const current = $('logRun').value;
  $('logRun').innerHTML = state.runs.map((r) => `<option value="${esc(r.run_id)}">${esc(r.account)} — ${esc(r.run_id)}</option>`).join('');
  if (current) $('logRun').value = current;
  else if (state.selectedRun) $('logRun').value = state.selectedRun;
  loadLog();
}

async function loadLog() {
  const runId = $('logRun').value;
  if (!runId) { $('logBody').innerHTML = '<div class="empty">No runs yet.</div>'; return; }

  const lines = await api.get(`/api/runs/${runId}/log`);
  $('logBody').innerHTML = lines.map((l) => {
    const { ts, run_id, level, node, message, ...fields } = l;
    const extra = Object.entries(fields).map(([k, v]) =>
      `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join('  ');
    return `<div class="line ${esc(level)}">
      <span class="t">${esc(String(ts).slice(11, 23))}</span>
      <span class="node">${esc(node)}</span>
      <span class="msg">${esc(message)}</span>
      <span class="fields">${esc(extra)}</span>
    </div>`;
  }).join('') || '<div class="empty">This run produced no log lines.</div>';
}

$('logRun').onchange = loadLog;
$('logRefresh').onclick = loadLogRuns;

/* ─────────────────────────── rules ─────────────────────────── */
async function loadRules() {
  $('rulesText').value = await api.text('/api/rules/raw');
  $('rulesStatus').textContent = '';
}
$('rulesReload').onclick = loadRules;
$('rulesSave').onclick = async () => {
  try {
    const r = await api.send('/api/rules/raw', { yaml: $('rulesText').value }, 'PUT');
    $('rulesStatus').textContent = `saved — ${r.rules} rules active. Re-run an account to see the new score.`;
  } catch (e) { $('rulesStatus').textContent = 'rejected: ' + e.message; }
};

/* ─────────────────────────── eval ─────────────────────────── */
function evalTable(s) {
  const gates = [
    ['schema_validity', 1.0], ['fact_precision', 0.85], ['fact_recall', 0.70],
    ['citation_groundedness', 0.90], ['retrieval_hit_rate', 0.80],
    ['correct_abstention', 0.90], ['band_accuracy', 0.80], ['score_stability', 1.0],
  ];
  return `
    <p class="hint">
      <code>${esc(s.run_folder || '')}</code> · extractor <b>${esc(s.extract_mode)}</b> ·
      embeddings <b>${esc(s.embed_backend)}</b> · vectors <b>${esc(s.vector_backend)}</b> ·
      ${s.accounts} accounts · evaluated as of ${esc(s.today)} ·
      <span class="badge ${s.passed ? 'pass' : 'fail'}">${s.passed ? 'PASSED' : 'FAILED'}</span>
    </p>
    <table><thead><tr><th>Metric</th><th class="num">Score</th><th class="num">Gate</th><th>Result</th></tr></thead><tbody>
    ${gates.map(([m, gate]) => {
      const v = s[m] ?? 0;
      const ok = v >= gate;
      return `<tr><td class="mono">${esc(m)}</td><td class="num">${v.toFixed(2)}</td>
              <td class="num" style="color:var(--dim)">${gate.toFixed(2)}</td>
              <td><span class="badge ${ok ? 'pass' : 'fail'}">${ok ? 'pass' : 'fail'}</span></td></tr>`;
    }).join('')}
    <tr><td class="mono">delta_noise</td><td class="num">${s.delta_noise_accounts ?? 0}</td>
        <td class="num" style="color:var(--dim)">0</td>
        <td><span class="badge ${s.delta_noise_accounts ? 'fail' : 'pass'}">${s.delta_noise_accounts ? 'fail' : 'pass'}</span></td></tr>
    </tbody></table>
    ${(s.failures || []).length ? `<p class="note" style="color:var(--bad)">${s.failures.map(esc).join('<br>')}</p>` : ''}`;
}

async function loadEvalResults() {
  const rows = await api.get('/api/eval');
  $('evalResults').innerHTML = rows.length
    ? evalTable(rows[0]) + (rows.length > 1 ? `<p class="note">${rows.length} eval runs on record. Showing the newest.</p>` : '')
    : '<div class="empty">No eval has been run yet.</div>';
}

$('evalRun').onclick = async () => {
  $('evalRun').disabled = true;
  $('evalStatus').textContent = 'running the gold set — each account runs three times…';
  try {
    const r = await api.send('/api/eval', { extract_mode: $('evalExtract').value, embed_backend: $('evalEmbed').value });
    $('evalStatus').textContent = r.ok ? 'all gates passed' : 'a gate failed — see the table';
    $('evalOutPanel').style.display = 'block';
    $('evalOut').textContent = (r.stdout || '') + (r.stderr ? '\n\nstderr:\n' + r.stderr : '');
    if (r.summary) $('evalResults').innerHTML = evalTable(r.summary);
  } catch (e) {
    $('evalStatus').textContent = 'failed: ' + e.message;
  } finally { $('evalRun').disabled = false; }
};

/* ─────────────────────────── tutorial ───────────────────────────
   Shown once on a first visit, replayable from the "?" in the header.
   It moves you through the real tabs rather than drawing a fake tour over a
   screenshot, so by the end you have already seen the tool you will use. */

const TOUR = [
  {
    tab: 'pipeline',
    title: 'What this does',
    body: `You give it a list of companies. It reads public sources, pulls out facts that
           each cite the page they came from, throws away anything the sources do not
           support, scores the account, and tells you <b>what changed since last time</b>.
           <br><br>About four minutes to walk through. You can leave at any point.`,
  },
  {
    tab: 'pipeline',
    title: 'Eight steps, and three of them have no model in them',
    body: `Each box is one stage of a run. The blue ones use a language model; the
           <b>green ones are plain Python</b>. The model reads and extracts — the code
           decides and reports. That split is why a score can be explained.
           <br><br><b>Model check</b> below calls the models for real and tells you what came back.`,
  },
  {
    tab: 'watchlist',
    title: 'Start here: run an account',
    body: `The <b>watchlist</b> is what gets refreshed automatically every night. Hit
           <b>Run</b> on any row to do it now — it takes about a second.
           <br><br>The <b>digest</b> at the bottom is the Monday-morning view: where every
           account stands and which way it moved.`,
  },
  {
    tab: 'deals',
    title: 'Where every account stands',
    body: `A brief tells you what is true about a company. A <b>lead</b> tells you what you
           did next — stage, owner, how long it has been quiet.
           <br><br>Everything on an account's timeline is written <b>automatically</b>:
           researching an account moves it to Researched by itself, drafting an email logs
           itself. Reps lose about as much of the week to CRM data entry as to research,
           and it is the one part of the job that is fully automatable.
           <br><br><b>Needs attention</b> is the list to open first.`,
  },
  {
    tab: 'briefs',
    title: 'Read the brief',
    body: `Every fact links to the page it was read from — click through and check any of
           them. <b>Why this score</b> shows which rule fired and what it was worth.
           <br><br>Scroll to <b>Dropped by the verifier</b>. Those are claims the sources did
           not support. They are shown on purpose: knowing what was thrown away is what
           makes the rest believable.`,
  },
  {
    tab: 'briefs',
    title: 'Draft the email',
    body: `At the bottom of a brief is <b>Outreach</b>. Pick why you are writing — first
           touch, new executive, post-layoffs — and it drafts from the verified facts,
           telling you which ones it used.
           <br><br>The <b>style check</b> scores the draft for the habits that make writing
           read as generated: stock openers, filler, hedging, and whether it says anything
           specific at all. Edit the body and it re-scores as you type.`,
  },
  {
    tab: 'rules',
    title: 'The score is yours, not the model\'s',
    body: `No model produces the number. This file does. Recent funding is worth +30,
           layoffs −20, and you can change that here and save.
           <br><br>Re-run an account afterwards and the score moves. Nothing is retrained,
           nothing is hidden.`,
  },
  {
    tab: 'evaluation',
    title: 'And proof that it works',
    body: `The <b>eval</b> runs against six frozen accounts with known answers, three times
           each, and scores nine things — including whether it correctly stays silent when
           there is nothing to find.
           <br><br>Two of those accounts are traps. One has no public footprint at all. The
           other hides a <b>competitor's</b> funding round in its sources — credit that money
           to the wrong company and the whole recommendation changes.`,
  },
];

let tourStep = 0;

function renderTour() {
  const step = TOUR[tourStep];
  document.querySelector(`nav button[data-tab="${step.tab}"]`).click();

  $('tour').innerHTML = `
    <div class="tour-backdrop">
      <div class="tour-card">
        <div class="tour-step">STEP ${tourStep + 1} OF ${TOUR.length}</div>
        <h3>${step.title}</h3>
        <p>${step.body}</p>
        <div class="tour-dots">${TOUR.map((_, i) => `<i class="${i <= tourStep ? 'on' : ''}"></i>`).join('')}</div>
        <div class="tour-actions">
          <button class="ghost" id="tourSkip">Skip</button>
          <span class="spacer"></span>
          ${tourStep > 0 ? '<button class="ghost" id="tourBack">Back</button>' : ''}
          <button class="act" id="tourNext">${tourStep === TOUR.length - 1 ? 'Start using it' : 'Next'}</button>
        </div>
      </div>
    </div>`;

  $('tourSkip').onclick = endTour;
  $('tourNext').onclick = () => { tourStep += 1; tourStep >= TOUR.length ? endTour() : renderTour(); };
  if ($('tourBack')) $('tourBack').onclick = () => { tourStep -= 1; renderTour(); };
}

function startTour() { tourStep = 0; renderTour(); }

function endTour() {
  $('tour').innerHTML = '';
  try { localStorage.setItem('osint_scout_tour_done', '1'); } catch {}
  document.querySelector('nav button[data-tab="watchlist"]').click();
}

$('helpBtn').onclick = startTour;
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && $('tour').innerHTML) endTour(); });

/* ─────────────────────────── boot ─────────────────────────── */
(async function boot() {
  await loadHealth();
  await loadArchitecture();
  await loadWatchlist();
  await loadRuns();
  await loadDigest();

  let seen = true;
  try { seen = localStorage.getItem('osint_scout_tour_done') === '1'; } catch {}
  if (!seen) startTour();

  // Reattach to a run that was still going when the page was reloaded or closed.
  // The work happens server-side, so a refresh mid-run costs nothing.
  let active = null;
  try { active = JSON.parse(localStorage.getItem('osint_active_run') || 'null'); } catch {}
  if (active && active.runId) {
    document.querySelector('nav button[data-tab="watchlist"]').click();
    $('runStatus').textContent = `reattached to a run already in progress for ${active.account}…`;
    followRun(active.runId, active.account);
  }
})();
