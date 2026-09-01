// RecoverX - Day 12 Real-Time Recovery Dashboard Client Logic

let currentMerchantId = "merch_101";
let refreshInterval = null;
let refreshCountdown = 4;
let isAutoRefresh = true;

// Tab Navigation
function initTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      
      tab.classList.add('active');
      const targetId = tab.getAttribute('data-tab');
      const targetEl = document.getElementById(targetId);
      if (targetEl) targetEl.classList.add('active');
    });
  });
}

// Format INR Currency
function formatINR(val) {
  const num = parseFloat(val || 0);
  return '₹' + num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Format Timestamp
function formatTime(isoStr) {
  if (!isoStr) return '--';
  const d = new Date(isoStr);
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDate(isoStr) {
  if (!isoStr) return '--';
  const d = new Date(isoStr);
  return d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// Category Badge Helper
function getCategoryBadge(cat) {
  switch (cat) {
    case 'TEMPORARY':
      return '<span class="badge-tag badge-amber">TEMPORARY</span>';
    case 'PAYMENT_METHOD':
      return '<span class="badge-tag badge-indigo">PAYMENT_METHOD</span>';
    case 'CUSTOMER_ACTION':
      return '<span class="badge-tag badge-cyan">CUSTOMER_ACTION</span>';
    case 'HARD_FAILURE':
      return '<span class="badge-tag badge-rose">HARD_FAILURE</span>';
    default:
      return `<span class="badge-tag badge-indigo">${cat || 'UNKNOWN'}</span>`;
  }
}

// State Badge Helper
function getStateBadge(state) {
  switch (state) {
    case 'RECOVERED':
      return '<span class="badge-tag badge-green">RECOVERED</span>';
    case 'OPEN':
      return '<span class="badge-tag badge-cyan">OPEN</span>';
    case 'SCHEDULED':
      return '<span class="badge-tag badge-amber">SCHEDULED</span>';
    case 'STOPPED':
      return '<span class="badge-tag badge-rose">STOPPED</span>';
    case 'NEEDS_REVIEW':
      return '<span class="badge-tag badge-indigo">NEEDS_REVIEW</span>';
    default:
      return `<span class="badge-tag badge-amber">${state || 'PROCESSING'}</span>`;
  }
}

// Load Overview Metrics
async function loadOverview() {
  try {
    const res = await fetch(`/api/v1/dashboard/overview?merchant_id=${currentMerchantId}`);
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById('val-failed-gmv').textContent = formatINR(data.total_failed_gmv);
    document.getElementById('val-failed-count').textContent = `${data.total_failed_count} payments`;
    
    document.getElementById('val-recovered-gmv').textContent = formatINR(data.total_recovered_gmv);
    document.getElementById('val-recovered-count').textContent = `${data.total_recovered_count} recovered`;
    document.getElementById('val-incremental-gmv').textContent = `+${formatINR(data.incremental_recovery_gmv)} gain`;

    document.getElementById('val-recovery-rate').textContent = `${data.recovery_rate_pct}%`;
    document.getElementById('val-eligible-count').textContent = `of ${data.eligible_failed_count} eligible`;
    document.getElementById('val-gross-rate').textContent = `Gross: ${data.gross_recovery_rate_pct}%`;

    document.getElementById('val-recovery-time').textContent = `${data.avg_recovery_time_seconds}s`;
    document.getElementById('val-friction-score').textContent = `Friction: ${data.customer_friction_score}`;
    document.getElementById('val-open-cases').textContent = `${data.total_open_cases_count} open, ${data.total_scheduled_cases_count} sched`;

    // Render Action breakdown
    const actionContainer = document.getElementById('action-breakdown-body');
    if (actionContainer && data.action_breakdown) {
      if (data.action_breakdown.length === 0) {
        actionContainer.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">No action executions yet. Simulate a batch to view breakdown.</td></tr>';
      } else {
        actionContainer.innerHTML = data.action_breakdown.map(a => `
          <tr>
            <td><strong>${a.action_type}</strong></td>
            <td>${a.count}</td>
            <td><span class="badge-tag badge-green">${a.completed}</span></td>
            <td><strong style="color:var(--accent-primary);">${a.success_rate_pct}%</strong></td>
            <td class="font-mono" style="color:var(--recovered-green);">${formatINR(a.recovered_gmv)}</td>
          </tr>
        `).join('');
      }
    }

    // Render Category breakdown
    const catContainer = document.getElementById('category-breakdown-body');
    if (catContainer && data.category_breakdown) {
      catContainer.innerHTML = data.category_breakdown.map(c => `
        <tr>
          <td>${getCategoryBadge(c.category)}</td>
          <td>${c.failed_count}</td>
          <td><span class="badge-tag badge-green">${c.recovered_count}</span></td>
          <td><strong>${c.recovery_rate_pct}%</strong></td>
          <td class="font-mono" style="color:var(--failed-rose);">${formatINR(c.failed_gmv)}</td>
          <td class="font-mono" style="color:var(--recovered-green);">${formatINR(c.recovered_gmv)}</td>
        </tr>
      `).join('');
    }

    document.getElementById('last-updated-time').textContent = formatTime(data.last_projected_at);
  } catch (err) {
    console.error('Failed to load overview metrics:', err);
  }
}

// Load Recovery Funnel
async function loadFunnel() {
  try {
    const res = await fetch(`/api/v1/dashboard/funnel?merchant_id=${currentMerchantId}`);
    if (!res.ok) return;
    const data = await res.json();

    const container = document.getElementById('funnel-steps-container');
    if (container && data.stages) {
      container.innerHTML = data.stages.map((st, idx) => `
        <div class="funnel-step-card">
          <div class="funnel-step-num">${st.label}</div>
          <div class="funnel-step-val">${st.count}</div>
          <div class="funnel-step-gmv">${formatINR(st.gmv)}</div>
          <div class="funnel-conversion-rate">${st.conversion_rate_from_prev_pct}% conv.</div>
        </div>
      `).join('');
    }

    // Method switch matrix
    const matrixContainer = document.getElementById('method-matrix-body');
    if (matrixContainer && data.method_conversion_matrix) {
      matrixContainer.innerHTML = data.method_conversion_matrix.map(m => `
        <tr>
          <td><span class="badge-tag badge-rose">${m.from_method}</span></td>
          <td><strong>→</strong></td>
          <td><span class="badge-tag badge-indigo">${m.to_method}</span></td>
          <td>${m.attempted}</td>
          <td><span class="badge-tag badge-green">${m.recovered}</span></td>
          <td><strong style="color:var(--recovered-green);">${m.rate_pct}%</strong></td>
          <td class="font-mono">${formatINR(m.recovered_gmv)}</td>
        </tr>
      `).join('');
    }
  } catch (err) {
    console.error('Failed to load recovery funnel:', err);
  }
}

// Load Live Failed Payments
async function loadLiveFailedPayments() {
  try {
    const res = await fetch(`/api/v1/dashboard/live-failed-payments?merchant_id=${currentMerchantId}&limit=20`);
    if (!res.ok) return;
    const data = await res.json();

    const tbody = document.getElementById('failed-payments-tbody');
    if (!tbody) return;

    if (data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--text-muted); padding:30px;">No failed payments recorded yet. Click "Simulate Live Batch" to generate failures.</td></tr>';
      return;
    }

    tbody.innerHTML = data.items.map(item => `
      <tr>
        <td class="font-mono">
          <a href="#" onclick="openTransactionModal('${item.transaction_id}'); return false;" style="color:var(--accent-primary); text-decoration:none; font-weight:600;">
            ${item.external_transaction_id.substring(0, 16)}...
          </a>
        </td>
        <td>
          <div style="font-weight:600;">${item.customer_name || 'Guest'}</div>
          <div style="font-size:11px; color:var(--text-muted);">${item.customer_email_masked || '--'}</div>
        </td>
        <td class="font-mono" style="font-weight:700;">${formatINR(item.amount)}</td>
        <td><span class="badge-tag badge-indigo">${item.payment_method}</span></td>
        <td>
          <div style="font-weight:600; font-size:12px;">${item.failure_code}</div>
          <div>${getCategoryBadge(item.failure_category)}</div>
        </td>
        <td>${getStateBadge(item.recovery_state || item.status)}</td>
        <td style="text-align:center;"><strong>${item.attempt_count}</strong></td>
        <td>
          <button class="btn btn-secondary" style="padding:4px 10px; font-size:11px;" onclick="openTransactionModal('${item.transaction_id}')">
            🔍 Inspect
          </button>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    console.error('Failed to load live failed payments:', err);
  }
}

// Load Agent Decisions Feed
async function loadAgentDecisions() {
  try {
    const res = await fetch(`/api/v1/dashboard/agent-decisions?merchant_id=${currentMerchantId}&limit=20`);
    if (!res.ok) return;
    const data = await res.json();

    const container = document.getElementById('agent-decisions-feed');
    if (!container) return;

    if (data.items.length === 0) {
      container.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding:30px;">No agent decisions logged yet.</div>';
      return;
    }

    container.innerHTML = data.items.map(d => `
      <div style="background:rgba(255,255,255,0.03); border:1px solid var(--border-card); border-radius:var(--radius-md); padding:16px; margin-bottom:14px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <div style="display:flex; align-items:center; gap:10px;">
            <span class="badge-tag badge-cyan">🤖 AI AGENT</span>
            <strong class="font-mono">${d.investigation_id}</strong>
            <span style="font-size:12px; color:var(--text-muted);">Txn: ${d.external_transaction_id.substring(0, 14)}...</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px;">
            <span class="font-mono" style="font-weight:700; color:var(--recovered-green);">${formatINR(d.amount)}</span>
            <span class="badge-tag ${d.decision_status === 'RECOVERED' ? 'badge-green' : d.decision_status === 'STOPPED' ? 'badge-rose' : 'badge-amber'}">${d.decision_status}</span>
          </div>
        </div>

        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:12px; font-size:12px;">
          <div>
            <span style="color:var(--text-muted);">Selected Action:</span>
            <strong style="color:#a5b4fc;">${d.selected_action}</strong>
          </div>
          <div>
            <span style="color:var(--text-muted);">Confidence / EV:</span>
            <strong>${(parseFloat(d.confidence_score)*100).toFixed(1)}% / ${formatINR(d.expected_value)}</strong>
          </div>
        </div>

        <div style="background:rgba(0,0,0,0.25); border-radius:var(--radius-sm); padding:10px 14px; font-size:12px; margin-bottom:10px;">
          <div style="color:var(--text-secondary); margin-bottom:4px;"><strong>Decision Reasoning:</strong> ${d.decision_reasoning}</div>
          ${d.customer_explanation ? `<div style="color:#67e8f9; font-size:11px;"><strong>Customer Guidance:</strong> "${d.customer_explanation}"</div>` : ''}
        </div>

        <div style="display:flex; align-items:center; justify-content:space-between; font-size:11px; color:var(--text-muted);">
          <div style="display:flex; gap:6px; flex-wrap:wrap;">
            ${d.tool_calls_executed.map(t => `<span style="background:rgba(255,255,255,0.05); padding:2px 6px; border-radius:4px; font-family:var(--font-mono);">${t}</span>`).join('')}
          </div>
          <div>${formatTime(d.investigated_at)}</div>
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to load agent decisions:', err);
  }
}

// Load Recovery Attempts
async function loadRecoveryAttempts() {
  try {
    const res = await fetch(`/api/v1/dashboard/recovery-attempts?merchant_id=${currentMerchantId}&limit=20`);
    if (!res.ok) return;
    const data = await res.json();

    const tbody = document.getElementById('attempts-tbody');
    if (!tbody) return;

    if (data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--text-muted); padding:30px;">No recovery attempts executed yet.</td></tr>';
      return;
    }

    tbody.innerHTML = data.items.map(att => `
      <tr>
        <td class="font-mono">${att.external_transaction_id.substring(0, 14)}...</td>
        <td><span class="badge-tag badge-indigo">${att.workflow_type}</span></td>
        <td><strong>${att.action_type}</strong></td>
        <td>
          <span class="badge-tag badge-rose">${att.instrument_from || 'CARD'}</span>
          →
          <span class="badge-tag badge-green">${att.instrument_to || 'UPI'}</span>
        </td>
        <td class="font-mono">${formatINR(att.amount)}</td>
        <td>
          <span class="badge-tag ${att.status === 'COMPLETED' ? 'badge-green' : att.status === 'SCHEDULED' ? 'badge-amber' : 'badge-cyan'}">
            ${att.status}
          </span>
        </td>
        <td style="font-size:12px; color:var(--text-muted);">${formatTime(att.executed_at || att.scheduled_at || att.created_at)}</td>
      </tr>
    `).join('');
  } catch (err) {
    console.error('Failed to load recovery attempts:', err);
  }
}

// Load Model Health
async function loadModelHealth() {
  try {
    const res = await fetch(`/api/v1/dashboard/model-health?merchant_id=${currentMerchantId}`);
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById('mh-version').textContent = data.model_version;
    document.getElementById('mh-auc').textContent = (data.auc_roc * 100).toFixed(1) + '%';
    document.getElementById('mh-accuracy').textContent = (data.accuracy * 100).toFixed(1) + '%';
    document.getElementById('mh-brier').textContent = data.brier_score.toFixed(4);

    // Feature Importances
    const featContainer = document.getElementById('feature-importance-list');
    if (featContainer && data.feature_importances) {
      featContainer.innerHTML = data.feature_importances.map(f => {
        const pct = (f.importance_score * 100).toFixed(1);
        return `
          <div style="margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
              <span class="font-mono">${f.feature_name}</span>
              <strong>${pct}%</strong>
            </div>
            <div style="height:6px; background:rgba(255,255,255,0.06); border-radius:3px; overflow:hidden;">
              <div style="width:${pct}%; height:100%; background:var(--accent-gradient); border-radius:3px;"></div>
            </div>
          </div>
        `;
      }).join('');
    }

    // Score distribution
    const scoreContainer = document.getElementById('score-distribution-list');
    if (scoreContainer && data.score_distribution) {
      const maxCount = Math.max(...Object.values(data.score_distribution), 1);
      scoreContainer.innerHTML = Object.entries(data.score_distribution).map(([bin, count]) => {
        const barWidth = Math.round((count / maxCount) * 100);
        return `
          <div style="margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
              <span>Score Bin: <strong>${bin}</strong></span>
              <span class="font-mono">${count} predictions</span>
            </div>
            <div style="height:8px; background:rgba(255,255,255,0.06); border-radius:4px; overflow:hidden;">
              <div style="width:${barWidth}%; height:100%; background:var(--recovered-green); border-radius:4px;"></div>
            </div>
          </div>
        `;
      }).join('');
    }
  } catch (err) {
    console.error('Failed to load model health:', err);
  }
}

// Transaction Detail Modal
async function openTransactionModal(txnId) {
  const modal = document.getElementById('txn-modal');
  if (!modal) return;
  modal.classList.add('active');

  document.getElementById('modal-txn-id').textContent = txnId;
  const contentEl = document.getElementById('modal-timeline-content');
  contentEl.innerHTML = '<div style="text-align:center; padding:20px; color:var(--text-muted);">Loading transaction details and audit timeline...</div>';

  try {
    const res = await fetch(`/api/v1/transactions/${txnId}`);
    if (!res.ok) {
      contentEl.innerHTML = '<div style="color:var(--failed-rose);">Failed to load transaction details.</div>';
      return;
    }
    const data = await res.json();

    contentEl.innerHTML = `
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:20px; background:rgba(255,255,255,0.03); padding:16px; border-radius:var(--radius-md);">
        <div>
          <div style="font-size:11px; color:var(--text-muted);">EXTERNAL ID</div>
          <div class="font-mono" style="font-weight:700;">${data.external_transaction_id}</div>
          <div style="font-size:11px; color:var(--text-muted); margin-top:8px;">MERCHANT</div>
          <div>${data.merchant_id}</div>
        </div>
        <div>
          <div style="font-size:11px; color:var(--text-muted);">AMOUNT</div>
          <div class="font-mono" style="font-size:18px; font-weight:800; color:var(--recovered-green);">${formatINR(data.amount)}</div>
          <div style="font-size:11px; color:var(--text-muted); margin-top:8px;">CURRENT STATUS</div>
          <div>${getStateBadge(data.status)}</div>
        </div>
      </div>

      <h4 style="font-size:14px; font-weight:700; margin-bottom:12px;">Immutable Audit & Event Timeline</h4>
      <div class="timeline">
        ${(data.attempts || []).map(att => `
          <div class="timeline-item">
            <div class="timeline-dot ${att.failure_code ? 'failed' : 'success'}"></div>
            <div class="timeline-content">
              <div class="timeline-title">
                <span>Attempt #${att.attempt_number} — ${att.payment_method} (${att.gateway || 'RAZORPAY'})</span>
                <span class="timeline-time">${formatDate(att.created_at)}</span>
              </div>
              <div style="font-size:12px; color:var(--text-secondary);">
                ${att.failure_code ? `Outcome: <strong style="color:var(--failed-rose);">${att.failure_code}</strong>` : '<strong style="color:var(--recovered-green);">SUCCEEDED</strong>'}
              </div>
            </div>
          </div>
        `).join('')}
      </div>

      <div style="margin-top:20px; display:flex; gap:12px; justify-content:flex-end;">
        <button class="btn btn-primary" onclick="triggerDirectRecovery('${txnId}', 'SWITCH_TO_UPI')">
          ⚡ Execute Switch to UPI
        </button>
        <button class="btn btn-secondary" onclick="closeTransactionModal()">Close</button>
      </div>
    `;
  } catch (err) {
    console.error('Error opening transaction modal:', err);
  }
}

function closeTransactionModal() {
  const modal = document.getElementById('txn-modal');
  if (modal) modal.classList.remove('active');
}

// Trigger Quick Simulation Scenarios
async function runSimulationScenario(actionType, failureCode, paymentMethod, amount) {
  const btn = event.currentTarget;
  const originalText = btn.innerHTML;
  btn.innerHTML = '⏳ Simulating...';
  btn.disabled = true;

  try {
    // 1. Simulate failure payment
    const simRes = await fetch('/api/v1/simulator/payments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        merchant_id: currentMerchantId,
        amount: amount,
        payment_method: paymentMethod,
        target_outcome: 'FAIL',
        target_failure_code: failureCode
      })
    });
    const simData = await simRes.json();
    const txnId = simData.transaction_id;

    // 2. Investigate via AI agent
    await fetch('/api/v1/agent/investigate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transaction_id: txnId })
    });

    // 3. Execute recovery if not stop
    if (actionType !== 'STOP_RECOVERY') {
      if (actionType === 'PAYMENT_LINK' || actionType === 'CUSTOMER_NOTIFICATION') {
        await fetch('/api/v1/execution/customer/create-link', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ transaction_id: txnId, channel: 'WHATSAPP' })
        });
      } else {
        await fetch('/api/v1/execution/actions/execute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ transaction_id: txnId, action_type: actionType, force_outcome: 'SUCCESS' })
        });
      }
    }

    refreshAllData();
  } catch (err) {
    console.error('Simulation scenario error:', err);
  } finally {
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
}

// Run Full Live Batch
async function runLiveBatchSimulation() {
  const btn = document.getElementById('btn-sim-batch');
  if (btn) {
    btn.innerHTML = '⏳ Simulating Batch...';
    btn.disabled = true;
  }

  try {
    const res = await fetch('/api/v1/dashboard/simulate-live-batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        merchant_id: currentMerchantId,
        count: 6,
        auto_investigate: true,
        auto_execute: true
      })
    });
    const data = await res.json();
    alert(`Simulation Batch Complete!\nGenerated: ${data.generated_count}\nInvestigated: ${data.investigated_count}\nRecovered: ${data.recovered_count}\nRecovered GMV: ${formatINR(data.recovered_gmv)}`);
    refreshAllData();
  } catch (err) {
    console.error('Batch simulation error:', err);
  } finally {
    if (btn) {
      btn.innerHTML = '⚡ Simulate Live Failures';
      btn.disabled = false;
    }
  }
}

// Trigger Direct Recovery from Modal
async function triggerDirectRecovery(txnId, actionType) {
  try {
    const res = await fetch('/api/v1/execution/actions/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transaction_id: txnId,
        action_type: actionType,
        force_outcome: 'SUCCESS'
      })
    });
    const data = await res.json();
    alert(`Recovery Action Executed: ${data.status} (Transaction ${data.transaction_id})`);
    closeTransactionModal();
    refreshAllData();
  } catch (err) {
    console.error('Recovery execution error:', err);
  }
}

// Refresh All Data
function refreshAllData() {
  loadOverview();
  loadFunnel();
  loadLiveFailedPayments();
  loadAgentDecisions();
  loadRecoveryAttempts();
  loadModelHealth();
  refreshCountdown = 4;
}

// Auto Refresh Timer Loop
function startRefreshLoop() {
  if (refreshInterval) clearInterval(refreshInterval);
  refreshInterval = setInterval(() => {
    if (!isAutoRefresh) return;
    refreshCountdown--;
    const countEl = document.getElementById('refresh-countdown');
    if (countEl) countEl.textContent = `${refreshCountdown}s`;
    
    if (refreshCountdown <= 0) {
      refreshAllData();
    }
  }, 1000);
}

// Initialize on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  refreshAllData();
  startRefreshLoop();

  const simBtn = document.getElementById('btn-sim-batch');
  if (simBtn) simBtn.addEventListener('click', runLiveBatchSimulation);

  const tenantSelect = document.getElementById('tenant-select');
  if (tenantSelect) {
    tenantSelect.addEventListener('change', (e) => {
      currentMerchantId = e.target.value;
      refreshAllData();
    });
  }
});
