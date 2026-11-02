/* CareerOS API dashboard — live charts & fluid motion */
(function () {
  const boot = window.__CAREEROS_BOOT__ || {};
  const history = { labels: [], tps: [], latencyAvg: [], latencyP95: [], errors: [], fixes: [] };
  const MAX_POINTS = 48;
  const animatedValues = new Map();

  const fmtMs = (v) => `${Number(v || 0).toFixed(1)} ms`;
  const fmtTps = (v) => Number(v || 0).toFixed(2);
  const fmtTime = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleTimeString();
  };
  const statusClass = (code) => {
    if (code >= 500) return 'status-error';
    if (code >= 400) return 'status-warn';
    return 'status-ok';
  };

  function tweenNumber(el, nextValue, formatter) {
    const key = el.id || el;
    const target = Number(nextValue) || 0;
    const start = animatedValues.get(key)?.current ?? target;
    const startTime = performance.now();
    const duration = 600;

    function frame(now) {
      const t = Math.min(1, (now - startTime) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const current = start + (target - start) * eased;
      animatedValues.set(key, { current: current });
      el.textContent = formatter ? formatter(current) : String(Math.round(current));
      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  function pushHistory(data) {
    const label = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const errorFix = data.errorFix || boot.errorFix || {};
    history.labels.push(label);
    history.tps.push(data.tps?.last10s ?? 0);
    history.latencyAvg.push(data.latencyMs?.avg ?? 0);
    history.latencyP95.push(data.latencyMs?.p95 ?? 0);
    history.errors.push((data.totalErrors ?? 0) + (data.clientLogErrors ?? 0));
    history.fixes.push(errorFix.totalFixesTracked ?? 0);
    if (history.labels.length > MAX_POINTS) {
      history.labels.shift();
      history.tps.shift();
      history.latencyAvg.shift();
      history.latencyP95.shift();
      history.errors.shift();
      history.fixes.shift();
    }
  }

  function gradient(ctx, c1, c2) {
    const g = ctx.createLinearGradient(0, 0, 0, 220);
    g.addColorStop(0, c1);
    g.addColorStop(1, c2);
    return g;
  }

  const chartDefaults = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 900, easing: 'easeInOutQuart' },
    plugins: {
      legend: {
        labels: { color: '#94a3b8', boxWidth: 10, font: { size: 11 } }
      }
    },
    scales: {
      x: {
        ticks: { color: '#64748b', maxTicksLimit: 6, font: { size: 10 } },
        grid: { color: 'rgba(255,255,255,0.04)' }
      },
      y: {
        ticks: { color: '#64748b', font: { size: 10 } },
        grid: { color: 'rgba(255,255,255,0.06)' },
        beginAtZero: true
      }
    }
  };

  let charts = {};

  function initCharts() {
    const tpsCtx = document.getElementById('chart-tps').getContext('2d');
    charts.tps = new Chart(tpsCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: 'TPS (10s avg)',
          data: [],
          borderColor: '#2ee59d',
          backgroundColor: (ctx) => {
            const bg = ctx.chart.ctx.createLinearGradient(0, 0, 0, 200);
            bg.addColorStop(0, 'rgba(46, 229, 157, 0.35)');
            bg.addColorStop(1, 'rgba(46, 229, 157, 0)');
            return bg;
          },
          fill: true,
          tension: 0.42,
          pointRadius: 0,
          borderWidth: 2.5
        }]
      },
      options: {
        ...chartDefaults,
        plugins: { ...chartDefaults.plugins, legend: { display: false } }
      }
    });

    const latCtx = document.getElementById('chart-latency').getContext('2d');
    charts.latency = new Chart(latCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Avg ms',
            data: [],
            borderColor: '#38bdf8',
            backgroundColor: 'rgba(56, 189, 248, 0.08)',
            tension: 0.38,
            pointRadius: 0,
            borderWidth: 2
          },
          {
            label: 'P95 ms',
            data: [],
            borderColor: '#fbbf24',
            backgroundColor: 'rgba(251, 191, 36, 0.06)',
            tension: 0.38,
            pointRadius: 0,
            borderWidth: 2
          }
        ]
      },
      options: chartDefaults
    });

    const statusCtx = document.getElementById('chart-status').getContext('2d');
    charts.status = new Chart(statusCtx, {
      type: 'doughnut',
      data: {
        labels: [],
        datasets: [{
          data: [],
          backgroundColor: ['#2ee59d', '#fbbf24', '#f87171', '#38bdf8', '#a78bfa'],
          borderWidth: 0,
          hoverOffset: 8
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { animateRotate: true, animateScale: true, duration: 800, easing: 'easeInOutQuart' },
        plugins: {
          legend: {
            position: 'bottom',
            labels: { color: '#94a3b8', boxWidth: 10, font: { size: 10 }, padding: 10 }
          }
        },
        cutout: '62%'
      }
    });

    const routesCtx = document.getElementById('chart-routes').getContext('2d');
    charts.routes = new Chart(routesCtx, {
      type: 'bar',
      data: {
        labels: [],
        datasets: [{
          label: 'Hits',
          data: [],
          backgroundColor: (ctx) => gradient(ctx.chart.ctx, 'rgba(46,229,157,0.85)', 'rgba(20,184,166,0.45)'),
          borderRadius: 8,
          borderSkipped: false
        }]
      },
      options: {
        ...chartDefaults,
        indexAxis: 'y',
        plugins: { ...chartDefaults.plugins, legend: { display: false } },
        scales: {
          x: chartDefaults.scales.x,
          y: { ...chartDefaults.scales.y, ticks: { ...chartDefaults.scales.y.ticks, maxTicksLimit: 8 } }
        }
      }
    });

    const errCtx = document.getElementById('chart-errors').getContext('2d');
    charts.errors = new Chart(errCtx, {
      type: 'bar',
      data: {
        labels: [],
        datasets: [{
          label: 'Total errors',
          data: [],
          backgroundColor: 'rgba(248, 113, 113, 0.65)',
          borderRadius: 6
        }]
      },
      options: {
        ...chartDefaults,
        plugins: { ...chartDefaults.plugins, legend: { display: false } }
      }
    });

    const efCtx = document.getElementById('chart-error-fix').getContext('2d');
    charts.errorFix = new Chart(efCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Errors',
            data: [],
            borderColor: '#f87171',
            backgroundColor: 'rgba(248, 113, 113, 0.12)',
            fill: true,
            tension: 0.35,
            pointRadius: 0,
            borderWidth: 2
          },
          {
            label: 'Fixes',
            data: [],
            borderColor: '#2ee59d',
            backgroundColor: 'rgba(46, 229, 157, 0.1)',
            fill: true,
            tension: 0.35,
            pointRadius: 0,
            borderWidth: 2
          }
        ]
      },
      options: chartDefaults
    });
  }

  function updateCharts(data) {
    charts.tps.data.labels = history.labels;
    charts.tps.data.datasets[0].data = history.tps;
    charts.tps.update('active');

    charts.latency.data.labels = history.labels;
    charts.latency.data.datasets[0].data = history.latencyAvg;
    charts.latency.data.datasets[1].data = history.latencyP95;
    charts.latency.update('active');

    const statusEntries = Object.entries(data.statusCodes || {});
    charts.status.data.labels = statusEntries.map(([code]) => code);
    charts.status.data.datasets[0].data = statusEntries.map(([, count]) => count);
    charts.status.update('active');

    const routes = (data.topRoutes || []).slice(0, 6);
    charts.routes.data.labels = routes.map((r) => r.route.replace(/^GET |^POST |^PUT |^PATCH |^DELETE /, ''));
    charts.routes.data.datasets[0].data = routes.map((r) => r.count);
    charts.routes.update('active');

    charts.errors.data.labels = history.labels.slice(-12);
    charts.errors.data.datasets[0].data = history.errors.slice(-12);
    charts.errors.update('active');

    charts.errorFix.data.labels = history.labels;
    charts.errorFix.data.datasets[0].data = history.errors;
    charts.errorFix.data.datasets[1].data = history.fixes;
    charts.errorFix.update('active');
  }

  function sourceLabel(source) {
    if (source === 'api') return 'API';
    if (source === 'client') return 'Extension';
    return 'System';
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  let toastTimer = null;

  function showToast(message, tone = 'ok') {
    const toast = document.getElementById('investigate-toast');
    toast.textContent = message;
    toast.className = `toast toast-${tone}`;
    toast.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.hidden = true;
    }, 4200);
  }

  async function copyText(text) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.left = '-9999px';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(area);
    return ok;
  }

  function showInvestigateDialog(prompt) {
    const dialog = document.getElementById('investigate-dialog');
    document.getElementById('investigate-prompt-text').value = prompt;
    if (typeof dialog.showModal === 'function') dialog.showModal();
  }

  async function investigateError(errorId, buttonEl) {
    if (!errorId) return;
    const original = buttonEl?.textContent;
    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.textContent = 'Preparing…';
    }
    try {
      const res = await fetch(`/errors/${encodeURIComponent(errorId)}/investigate`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const prompt = data.prompt || '';
      const copied = await copyText(prompt);
      if (copied) {
        showToast('Investigation prompt copied — paste into Cursor Agent', 'ok');
      } else {
        showToast('Copy failed — prompt shown below', 'warn');
      }
      showInvestigateDialog(prompt);
    } catch {
      showToast('Could not prepare investigation prompt', 'error');
    } finally {
      if (buttonEl) {
        buttonEl.disabled = false;
        buttonEl.textContent = original || 'Investigate';
      }
    }
  }

  async function investigateOpenErrors(buttonEl) {
    const original = buttonEl?.textContent;
    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.textContent = 'Preparing…';
    }
    try {
      const res = await fetch('/errors/investigate-open', { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const prompt = data.prompt || '';
      const copied = await copyText(prompt);
      showToast(
        copied
          ? `Prompt for ${data.openCount || 0} open error(s) copied — paste into Cursor Agent`
          : 'Copy failed — prompt shown below',
        copied ? 'ok' : 'warn'
      );
      showInvestigateDialog(prompt);
    } catch {
      showToast('No open errors or request failed', 'error');
    } finally {
      if (buttonEl) {
        buttonEl.disabled = false;
        buttonEl.textContent = original || 'Investigate open errors';
      }
    }
  }

  function bindInvestigateHandlers() {
    document.getElementById('error-fix-history')?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-investigate-id]');
      if (!button) return;
      investigateError(button.getAttribute('data-investigate-id'), button);
    });

    document.getElementById('investigate-open-btn')?.addEventListener('click', (event) => {
      investigateOpenErrors(event.currentTarget);
    });

    document.getElementById('investigate-copy-again')?.addEventListener('click', async () => {
      const prompt = document.getElementById('investigate-prompt-text').value;
      const copied = await copyText(prompt);
      showToast(copied ? 'Prompt copied again' : 'Copy failed', copied ? 'ok' : 'error');
    });
  }

  function seedHistoryFromBoot() {
    const seed = boot.chartSeed || {};
    const labels = seed.labels || [];
    if (!labels.length) return;
    history.labels = [...labels];
    history.errors = [...(seed.errors || [])];
    history.fixes = [...(seed.fixes || [])];
    history.tps = labels.map(() => 0);
    history.latencyAvg = labels.map(() => 0);
    history.latencyP95 = labels.map(() => 0);
  }

  function renderLogInventory(inventory) {
    const el = document.getElementById('repair-log-inventory');
    if (!el || !inventory) return;
    el.textContent =
      `Persisted inventory: ${inventory.clientLogLines ?? 0} client log lines · ` +
      `${inventory.historicalErrors ?? 0} historical errors · ` +
      `${inventory.openErrors ?? 0} open errors · ` +
      `${inventory.totalFixesTracked ?? 0} fixes recorded`;
  }

  const REPAIR_STATE_LABELS = {
    idle: 'Idle',
    reading_logs: 'Reading logs',
    creating_task: 'Creating task',
    sending_to_agent: 'Sending to agent',
    agent_working: 'Agent working',
    validating: 'Validating',
    completed: 'Completed',
    failed: 'Failed',
  };

  function renderRepairRun(run) {
    const stateEl = document.getElementById('repair-run-state');
    const detailsEl = document.getElementById('repair-run-details');
    if (!run) {
      stateEl.textContent = 'Idle';
      detailsEl.innerHTML = '<div class="empty">No manual repair run yet.</div>';
      document.getElementById('repair-logs-scanned').textContent = '—';
      document.getElementById('repair-errors-found').textContent = '—';
      document.getElementById('repair-dup-groups').textContent = '—';
      document.getElementById('repair-agent-status').textContent = '—';
      return;
    }

    const state = run.state || 'idle';
    stateEl.textContent = REPAIR_STATE_LABELS[state] || state;
    stateEl.style.color = state === 'completed' ? '#2ee59d' : state === 'failed' ? '#f87171' : '#bae6fd';

    document.getElementById('repair-logs-scanned').textContent = String(run.logEntriesScanned ?? '—');
    document.getElementById('repair-errors-found').textContent = String(run.errorsDiscovered ?? '—');
    document.getElementById('repair-dup-groups').textContent = String(run.duplicateGroups ?? '—');
    document.getElementById('repair-agent-status').textContent = run.agentRun?.status || '—';

    const skipped = (run.skipped || []).map((item) => `<li>${escapeHtml(item.reason || 'skipped')}${item.fingerprint ? ` · ${escapeHtml(item.fingerprint)}` : ''}</li>`).join('');
    const changedFiles = (run.agentRun?.changedFiles || []).map((file) => `<li>${escapeHtml(file)}</li>`).join('');
    const validationRows = (run.validation?.commands || []).map((item) =>
      `<li>${item.passed ? '✓' : '✗'} ${escapeHtml(item.command)} (exit ${item.exitCode})</li>`
    ).join('');

    detailsEl.innerHTML = `
      <div class="repair-detail-block">
        <h4>Run summary</h4>
        <ul>
          <li>State: ${escapeHtml(REPAIR_STATE_LABELS[state] || state)}</li>
          <li>Started: ${escapeHtml(run.startedAt || '—')}</li>
          <li>Completed: ${escapeHtml(run.completedAt || '—')}</li>
          ${run.message ? `<li>${escapeHtml(run.message)}</li>` : ''}
          ${run.oldestEntry ? `<li>Oldest scanned entry: ${escapeHtml(run.oldestEntry)}</li>` : ''}
          ${run.newestEntry ? `<li>Newest scanned entry: ${escapeHtml(run.newestEntry)}</li>` : ''}
          ${run.logInventory ? `<li>Persisted historical errors: ${escapeHtml(String(run.logInventory.historicalErrors ?? 0))}</li>` : ''}
          ${run.failure ? `<li>Failure: ${escapeHtml(run.failure)}</li>` : ''}
        </ul>
      </div>
      ${run.task ? `
      <div class="repair-detail-block">
        <h4>Repair task</h4>
        <ul>
          <li>${escapeHtml(run.task.title || run.task.taskId || 'task')}</li>
          <li>Occurrences: ${escapeHtml(String(run.task.occurrenceCount ?? '—'))}</li>
          <li>Endpoint: ${escapeHtml(run.task.endpoint || '—')}</li>
        </ul>
      </div>` : ''}
      ${skipped ? `<div class="repair-detail-block"><h4>Skipped</h4><ul>${skipped}</ul></div>` : ''}
      ${changedFiles ? `<div class="repair-detail-block"><h4>Changed files</h4><ul>${changedFiles}</ul></div>` : ''}
      ${run.agentRun?.diffSummary ? `<div class="repair-detail-block"><h4>Diff summary</h4><pre>${escapeHtml(run.agentRun.diffSummary)}</pre></div>` : ''}
      ${run.agentRun?.output ? `<div class="repair-detail-block"><h4>Agent output</h4><pre>${escapeHtml(run.agentRun.output)}</pre></div>` : ''}
      ${validationRows ? `<div class="repair-detail-block"><h4>Validation</h4><ul>${validationRows}</ul></div>` : ''}
    `;
  }

  function initRepairManualPanel() {
    const panel = document.getElementById('repair-manual-panel');
    const processBtn = document.getElementById('process-logs-btn');
    const demoBtn = document.getElementById('trigger-demo-error-btn');
    if (!panel || !processBtn) return;

    const enabled = Boolean(boot.server?.repairManualEnabled);
    panel.hidden = !enabled;
    if (!enabled) return;

    renderRepairRun(boot.repairRun || null);
    renderLogInventory(boot.logInventory);

    processBtn.addEventListener('click', async () => {
      processBtn.disabled = true;
      if (demoBtn) demoBtn.disabled = true;
      processBtn.textContent = 'Processing…';
      panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      renderRepairRun({ state: 'reading_logs', startedAt: new Date().toISOString() });
      const phases = ['creating_task', 'sending_to_agent', 'agent_working', 'validating'];
      let phaseIndex = 0;
      const timer = setInterval(() => {
        if (phaseIndex < phases.length) {
          renderRepairRun({ state: phases[phaseIndex++], startedAt: new Date().toISOString() });
        }
      }, 900);

      try {
        const res = await fetch('/dev/repair/process-logs', { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data);
          throw new Error(detail || `HTTP ${res.status}`);
        }
        renderRepairRun(data);
        if (data.logInventory) renderLogInventory(data.logInventory);
        if (data.errorsDiscovered === 0) {
          showToast(data.message || 'No actionable errors found — trigger a demo error first', 'warn');
        } else if (data.state === 'completed') {
          showToast('Manual repair run completed', 'ok');
        } else {
          showToast(data.failure || 'Manual repair run finished with issues', 'warn');
        }
      } catch (error) {
        showToast(error instanceof Error ? error.message : 'Repair run failed', 'error');
        renderRepairRun({ state: 'failed', failure: error instanceof Error ? error.message : 'Repair run failed' });
      } finally {
        clearInterval(timer);
        processBtn.disabled = false;
        if (demoBtn) demoBtn.disabled = false;
        processBtn.textContent = 'Process Logs & Errors';
      }
    });

    demoBtn?.addEventListener('click', async () => {
      demoBtn.disabled = true;
      try {
        const res = await fetch('/dev/demo/unhandled-scraper-error');
        const data = await res.json().catch(() => ({}));
        showToast(
          res.ok ? 'Demo error triggered' : (data.detail?.message || 'Demo backend error recorded'),
          res.ok ? 'ok' : 'warn'
        );
      } catch {
        showToast('Demo error recorded locally', 'ok');
      } finally {
        demoBtn.disabled = false;
      }
    });
  }

  function renderErrorFixPanels(errorFix) {
    if (!errorFix) return;

    tweenNumber(document.getElementById('m-fixes'), errorFix.totalFixesTracked ?? 0, (v) => String(Math.round(v)));
    tweenNumber(document.getElementById('m-open-errors'), errorFix.openErrors ?? 0, (v) => String(Math.round(v)));

    const fixRate = Number(errorFix.fixRate ?? 0);
    const pill = document.getElementById('fix-rate-pill');
    pill.textContent = `Fix rate ${fixRate.toFixed(1)}%`;
    pill.style.color = fixRate >= 80 ? '#2ee59d' : fixRate >= 50 ? '#fbbf24' : '#f87171';

    const meta = document.getElementById('error-fix-meta');
    const unresolved = errorFix.unresolvedErrors ?? 0;
    meta.textContent = `${unresolved} unresolved · ${errorFix.errorsLastHour ?? 0} errors / ${errorFix.fixesLastHour ?? 0} fixes last hour · ${errorFix.errorsLast60s ?? 0} err / ${errorFix.fixesLast60s ?? 0} fix last 60s`;

    const openBtn = document.getElementById('investigate-open-btn');
    const openCount = errorFix.openErrors ?? 0;
    if (openBtn) {
      openBtn.hidden = openCount <= 0;
      openBtn.textContent = openCount === 1 ? 'Investigate open error' : `Investigate ${openCount} open errors`;
    }

    const fixes = errorFix.recentFixes || [];
    document.getElementById('recent-fixes-list').innerHTML = fixes.length
      ? fixes.map((item) => `
          <li class="fix-item">
            <span class="fix-badge">Fixed</span>
            <strong>${item.signature || 'unknown'}</strong>
            <span>${item.message || ''}</span>
            <small>${sourceLabel(item.source)} · ${fmtTime(item.atIso)}</small>
          </li>`).join('')
      : '<li class="empty">No fixes recorded yet.</li>';

    const timeline = errorFix.history || [];
    const fixedIds = new Set(
      timeline.filter((item) => item.kind === 'fix' && item.errorId).map((item) => item.errorId)
    );
    document.getElementById('error-fix-history').innerHTML = timeline.length
      ? timeline.map((item) => `
          <article class="history-item ${item.kind}">
            <div class="history-dot" aria-hidden="true"></div>
            <div class="history-body">
              <div class="history-top">
                <span class="history-kind ${item.kind}">${item.kind === 'fix' ? 'Fix' : 'Error'}</span>
                <span class="history-source">${sourceLabel(item.source)}</span>
                <time>${fmtTime(item.atIso)}</time>
              </div>
              <strong>${escapeHtml(item.signature || 'unknown')}</strong>
              <p>${escapeHtml(item.message || '')}</p>
              ${item.statusCode ? `<small>HTTP ${item.statusCode}</small>` : ''}
              ${item.kind === 'error' && !fixedIds.has(item.id) ? `
                <button type="button" class="btn btn-investigate btn-sm" data-investigate-id="${escapeHtml(item.id)}">
                  Investigate with agent
                </button>` : ''}
            </div>
          </article>`).join('')
      : '<div class="empty">No error or fix history yet.</div>';
  }

  function renderBootPanels() {
    const stats = boot.stats || {};
    document.getElementById('tracker-stats').innerHTML = [
      ['Applications', stats.applications ?? 0],
      ['Saved jobs', stats.jobs ?? 0],
      ['Autofill sessions', stats.sessions ?? 0],
      ['Field mappings', stats.mappings ?? 0]
    ].map(([label, value]) => `
      <article class="stat-card">
        <p class="stat-label">${label}</p>
        <p class="stat-value">${value}</p>
      </article>
    `).join('');

    const profile = boot.profile || {};
    document.getElementById('profile-name').textContent = profile.name || 'No profile synced yet';
    document.getElementById('profile-email').textContent = profile.email || '—';

    const apps = boot.recentApps || [];
    document.getElementById('recent-apps').innerHTML = apps.length
      ? apps.map((a) => `
          <li>
            <strong>${a.company}</strong>
            <span>${a.role}</span>
            <small>${a.status} · ${a.time}</small>
          </li>`).join('')
      : '<li class="empty">No applications tracked yet.</li>';

    document.getElementById('meta-api').textContent = boot.apiUrl || '—';
    document.getElementById('meta-web').textContent = boot.webUrl || '—';
    document.getElementById('meta-ext').textContent = `${boot.extension?.version || '0.0.0'} · ${boot.extension?.status || '—'}`;
    document.getElementById('meta-dev').textContent = String(boot.server?.devMode ?? '—');
    document.getElementById('meta-refreshed').textContent = boot.server?.refreshed || '—';
    const webLink = document.getElementById('link-web');
    if (webLink && boot.webUrl) webLink.href = boot.webUrl;

    const logs = boot.recentLogs || [];
    document.getElementById('recent-logs').innerHTML = logs.length
      ? logs.map((e) => `
          <li class="log-${e.level}">
            <span class="log-time">${e.time}</span>
            <span class="log-source">${e.source}</span>
            <span class="log-message">${e.message}</span>
          </li>`).join('')
      : '<li class="empty">No extension logs yet.</li>';
  }

  function initFlowCanvas() {
    const canvas = document.getElementById('flow-canvas');
    const ctx = canvas.getContext('2d');
    const particles = Array.from({ length: 42 }, () => ({
      x: Math.random(),
      y: Math.random(),
      speed: 0.0004 + Math.random() * 0.0012,
      size: 1 + Math.random() * 2.2,
      alpha: 0.15 + Math.random() * 0.45
    }));

    function resize() {
      canvas.width = window.innerWidth * devicePixelRatio;
      canvas.height = window.innerHeight * devicePixelRatio;
    }
    resize();
    window.addEventListener('resize', resize);

    function draw() {
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      for (const p of particles) {
        p.x += p.speed;
        if (p.x > 1.08) {
          p.x = -0.04;
          p.y = Math.random();
        }
        const px = p.x * w;
        const py = p.y * h;
        ctx.beginPath();
        ctx.fillStyle = `rgba(46, 229, 157, ${p.alpha})`;
        ctx.arc(px, py, p.size * devicePixelRatio, 0, Math.PI * 2);
        ctx.fill();
      }
      requestAnimationFrame(draw);
    }
    draw();
  }

  async function refreshMetrics() {
    const statusEl = document.getElementById('live-status');
    try {
      const res = await fetch('/metrics', { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      statusEl.textContent = `Live · ${fmtTime(data.updatedAt)}`;
      statusEl.style.color = '';

      pushHistory(data);
      updateCharts(data);

      tweenNumber(document.getElementById('m-tps-10'), data.tps?.last10s, fmtTps);
      tweenNumber(document.getElementById('m-tps-60'), data.tps?.last60s, fmtTps);
      tweenNumber(document.getElementById('m-lat-avg'), data.latencyMs?.avg, (v) => fmtMs(v));
      tweenNumber(document.getElementById('m-lat-p95'), data.latencyMs?.p95, (v) => fmtMs(v));
      tweenNumber(document.getElementById('m-requests'), data.totalRequests, (v) => String(Math.round(v)));
      tweenNumber(document.getElementById('m-errors'), (data.totalErrors ?? 0) + (data.clientLogErrors ?? 0), (v) => String(Math.round(v)));

      renderErrorFixPanels(data.errorFix || boot.errorFix);

      const tbody = document.getElementById('recent-requests-body');
      const recent = data.recentRequests || [];
      tbody.innerHTML = recent.length
        ? recent.map((item) => `
            <tr>
              <td>${fmtTime(item.at)}</td>
              <td>${item.method}</td>
              <td>${item.path}</td>
              <td class="${statusClass(item.status)}">${item.status}</td>
              <td>${Number(item.durationMs || 0).toFixed(1)}</td>
            </tr>`).join('')
        : '<tr><td colspan="5">No requests recorded yet</td></tr>';
    } catch {
      statusEl.textContent = 'Metrics offline';
      statusEl.style.color = '#f87171';
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    seedHistoryFromBoot();
    renderBootPanels();
    renderErrorFixPanels(boot.errorFix);
    renderLogInventory(boot.logInventory);
    bindInvestigateHandlers();
    initRepairManualPanel();
    initFlowCanvas();
    if (typeof Chart !== 'undefined') {
      initCharts();
      if (history.labels.length) {
        updateCharts({
          tps: { last10s: 0, last60s: 0 },
          latencyMs: { avg: 0, p95: 0 },
          totalErrors: history.errors[history.errors.length - 1] || 0,
          errorFix: boot.errorFix,
          statusCodes: {},
          topRoutes: [],
        });
      }
      refreshMetrics();
      setInterval(refreshMetrics, 2000);
    }
  });
})();
