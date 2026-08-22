/*
=============================================================================
QUOTEX SIGNAL INTELLIGENCE PLATFORM — DASHBOARD CONTROLLER
Real-time SocketIO client, scanner card renderer, backtest controller
=============================================================================
*/

let socket = null;
let currentScannerData = [];

document.addEventListener("DOMContentLoaded", () => {
  initClock();
  initSocket();
  loadInitialScan();
  loadPaperTrades();
});

// 1. Clock & Countdown
function initClock() {
  function update() {
    const now = new Date();
    const utcStr = now.toUTCString().split(" ")[4] + " UTC";
    const clockEl = document.getElementById("utc-clock");
    if (clockEl) clockEl.textContent = utcStr;

    // Countdown to next minute boundary
    const secondsLeft = 60 - now.getUTCSeconds();
    const cdEl = document.getElementById("countdown-timer");
    if (cdEl) cdEl.textContent = `${secondsLeft}s`;
  }
  update();
  setInterval(update, 1000);
}

// 2. Real-time WebSocket
function initSocket() {
  try {
    socket = io();
    socket.on("connect", () => {
      console.log("[WebSocket] Connected to trading platform gateway");
    });
    socket.on("market_update", (data) => {
      if (data && data.results) {
        renderScanner(data.results);
      }
    });
  } catch (e) {
    console.warn("WebSocket fallback to polling:", e);
  }
}

// 3. Tab Navigation
function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c => c.style.display = "none");

  const activeBtn = Array.from(document.querySelectorAll(".tab-btn")).find(b => b.getAttribute("onclick").includes(tabId));
  if (activeBtn) activeBtn.classList.add("active");

  const targetTab = document.getElementById(`tab-${tabId}`);
  if (targetTab) targetTab.style.display = "block";

  if (tabId === "paper") loadPaperTrades();
  if (tabId === "analytics") loadAnalytics();
  if (tabId === "health") loadHealth();
}

// 4. Scanner Engine
async function loadInitialScan() {
  try {
    const res = await fetch("/api/scan");
    const json = await res.json();
    if (json.status === "success") {
      renderScanner(json.results);
    }
  } catch (err) {
    console.error("Initial scan error:", err);
  }
}

async function triggerManualScan() {
  const container = document.getElementById("scanner-cards");
  container.innerHTML = `<div style="padding: 40px; text-align: center; color: var(--cyan-accent); grid-column: 1 / -1;">
    Scanning 10 currency pairs and market structures across multiple timeframes...
  </div>`;
  await loadInitialScan();
}

function renderScanner(results) {
  currentScannerData = results;
  const container = document.getElementById("scanner-cards");
  if (!container) return;

  if (!results || results.length === 0) {
    container.innerHTML = `<div style="padding: 40px; text-align: center; color: var(--text-muted); grid-column: 1 / -1;">No active market opportunities matching risk filter criteria.</div>`;
    return;
  }

  container.innerHTML = results.map((item, idx) => {
    const isCall = item.direction === "CALL";
    const isPut = item.direction === "PUT";
    const highlightClass = isCall ? "highlight-call" : (isPut ? "highlight-put" : "");
    const badgeClass = item.direction;

    return `
      <div class="asset-card ${highlightClass}" onclick="openInspectModal(${idx})">
        <div class="card-header">
          <div class="asset-symbol">${item.name}</div>
          <div class="asset-payout">Payout ${Math.round(item.payout * 100)}%</div>
        </div>

        <div class="card-body">
          <div class="price-box">${item.current_price.toFixed(item.current_price > 100 ? 2 : 5)}</div>
          <div class="signal-badge ${badgeClass}">${item.direction} ${isCall ? '▲' : (isPut ? '▼' : '—')}</div>
        </div>

        <div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 4px;">
          Evidence Score: <strong style="color: ${item.evidence_score >= 70 ? 'var(--call-green)' : 'var(--text-primary)'};">${item.evidence_score}/100</strong>
          ${item.is_viable ? '• <span style="color: var(--call-green);">✅ Viable</span>' : ''}
        </div>

        <div class="score-bar-container">
          <div class="score-bar" style="width: ${item.evidence_score}%;"></div>
        </div>

        <div class="card-footer">
          <span>Expiry: <strong>${item.recommended_expiry / 60}m</strong></span>
          <span>Regime: <strong>${item.regime_desc}</strong></span>
        </div>
      </div>
    `;
  }).join("");
}

// 5. Inspect Signal Modal
function openInspectModal(idx) {
  const item = currentScannerData[idx];
  if (!item || !item.signal_details) return;

  const sig = item.signal_details;
  const modal = document.getElementById("signal-modal");
  const title = document.getElementById("modal-title");
  const body = document.getElementById("modal-body");

  title.innerHTML = `<span>${item.name}</span> — <strong>${sig.direction} (${sig.strength})</strong>`;

  const evidenceRows = (sig.evidence || []).map(e => `
    <div class="evidence-item">
      <div>
        <span class="evidence-engine">[${e.engine}]</span>
        <span style="margin-left: 8px;">${e.description}</span>
      </div>
      <span style="color: var(--call-green); font-weight: 700; font-family: var(--font-mono);">+${e.weight}pts</span>
    </div>
  `).join("");

  body.innerHTML = `
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px;">
      <div style="background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px; border: 1px solid var(--border-color);">
        <div style="font-size: 0.75rem; color: var(--text-secondary);">EVIDENCE SCORE</div>
        <div style="font-size: 1.4rem; font-weight: 700; color: var(--call-green);">${sig.evidence_score}/100</div>
      </div>
      <div style="background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px; border: 1px solid var(--border-color);">
        <div style="font-size: 0.75rem; color: var(--text-secondary);">BREAK-EVEN THRESHOLD</div>
        <div style="font-size: 1.4rem; font-weight: 700; color: var(--gold-accent);">${Math.round(sig.breakeven_probability * 100)}%</div>
      </div>
    </div>

    <h4 style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 8px;">TRACEABLE EVIDENCE REASONS</h4>
    <div class="evidence-list">
      ${evidenceRows || '<div style="color: var(--text-muted);">No directional setup trigger active.</div>'}
    </div>

    <div style="margin-top: 16px; font-size: 0.8rem; color: var(--text-secondary); border-top: 1px solid var(--border-color); padding-top: 10px;">
      Entry Price: <strong>${sig.entry_price.toFixed(5)}</strong> | Recommended Expiry: <strong>${sig.recommended_expiry / 60} min</strong>
    </div>
  `;

  modal.style.display = "flex";
}

function closeModal() {
  document.getElementById("signal-modal").style.display = "none";
}

// 6. Backtest Runner
async function runBacktest() {
  const asset = document.getElementById("bt-asset").value;
  const period = document.getElementById("bt-period").value;
  const lag = parseInt(document.getElementById("bt-lag").value);
  const payout = parseFloat(document.getElementById("bt-payout").value);

  const resultsPanel = document.getElementById("bt-results-panel");
  const metricsContainer = document.getElementById("bt-metrics-cards");

  resultsPanel.style.display = "block";
  metricsContainer.innerHTML = `<div style="color: var(--cyan-accent); padding: 20px;">Running walk-forward simulation across historical 1-minute bars with ${lag}s execution lag...</div>`;

  try {
    const res = await fetch("/api/backtest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: asset, period, execution_lag: lag, payout })
    });
    const json = await res.json();

    if (json.status === "success") {
      const r = json.report;
      metricsContainer.innerHTML = `
        <div style="background: rgba(0,0,0,0.4); padding: 14px; border-radius: 8px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.75rem; color: var(--text-secondary);">WIN RATE</div>
          <div style="font-size: 1.4rem; font-weight: 700; color: ${r.win_rate >= r.breakeven_winrate ? 'var(--call-green)' : 'var(--put-red)'};">${r.win_rate}%</div>
          <div style="font-size: 0.7rem; color: var(--text-muted);">Break-even: ${r.breakeven_winrate}%</div>
        </div>

        <div style="background: rgba(0,0,0,0.4); padding: 14px; border-radius: 8px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.75rem; color: var(--text-secondary);">EXPECTED VALUE / TRADE</div>
          <div style="font-size: 1.4rem; font-weight: 700; color: ${r.expected_value_per_trade >= 0 ? 'var(--call-green)' : 'var(--put-red)'};">${r.expected_value_per_trade >= 0 ? '+' : ''}${r.expected_value_per_trade}</div>
          <div style="font-size: 0.7rem; color: var(--text-muted);">Payout: ${Math.round(payout * 100)}%</div>
        </div>

        <div style="background: rgba(0,0,0,0.4); padding: 14px; border-radius: 8px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.75rem; color: var(--text-secondary);">TOTAL TRADES</div>
          <div style="font-size: 1.4rem; font-weight: 700;">${r.total_trades}</div>
          <div style="font-size: 0.7rem; color: var(--text-muted);">${r.wins}W / ${r.losses}L / ${r.ties}T</div>
        </div>

        <div style="background: rgba(0,0,0,0.4); padding: 14px; border-radius: 8px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.75rem; color: var(--text-secondary);">TOTAL PnL (at $10 stake)</div>
          <div style="font-size: 1.4rem; font-weight: 700; color: ${r.total_pnl >= 0 ? 'var(--call-green)' : 'var(--put-red)'};">${r.total_pnl >= 0 ? '+' : ''}$${r.total_pnl}</div>
          <div style="font-size: 0.7rem; color: var(--text-muted);">Profit Factor: ${r.profit_factor}</div>
        </div>

        <div style="background: rgba(0,0,0,0.4); padding: 14px; border-radius: 8px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.75rem; color: var(--text-secondary);">MAX LOSING STREAK</div>
          <div style="font-size: 1.4rem; font-weight: 700; color: var(--put-red);">${r.max_consecutive_losses}</div>
          <div style="font-size: 0.7rem; color: var(--text-muted);">Max Win Streak: ${r.max_consecutive_wins}</div>
        </div>
      `;
    } else {
      metricsContainer.innerHTML = `<div style="color: var(--put-red);">${json.message || 'Simulation error'}</div>`;
    }
  } catch (err) {
    metricsContainer.innerHTML = `<div style="color: var(--put-red);">Backtest API connection error: ${err}</div>`;
  }
}

// 7. Paper Trading Logs
async function loadPaperTrades() {
  try {
    const res = await fetch("/api/paper-trades");
    const json = await res.json();
    const tbody = document.getElementById("paper-trades-body");
    if (!tbody) return;

    if (json.trades && json.trades.length > 0) {
      tbody.innerHTML = json.trades.map(t => {
        const pnlColor = t.pnl > 0 ? "var(--call-green)" : (t.pnl < 0 ? "var(--put-red)" : "var(--text-muted)");
        return `
          <tr>
            <td style="font-family: var(--font-mono);">${new Date(t.entry_time).toLocaleTimeString()}</td>
            <td><strong>${t.asset}</strong></td>
            <td><span class="signal-badge ${t.direction}" style="padding: 2px 8px; font-size: 0.75rem;">${t.direction}</span></td>
            <td style="font-family: var(--font-mono);">${t.entry_price.toFixed(5)}</td>
            <td style="font-family: var(--font-mono);">${t.expiry_price ? t.expiry_price.toFixed(5) : '⏳ In Trade'}</td>
            <td>$${t.stake}</td>
            <td><strong>${t.outcome}</strong></td>
            <td style="font-family: var(--font-mono); font-weight: 700; color: ${pnlColor};">${t.pnl >= 0 ? '+' : ''}$${t.pnl}</td>
          </tr>
        `;
      }).join("");
    }
  } catch (e) {
    console.error("Paper trades error:", e);
  }
}

// 8. Analytics & Health
async function loadAnalytics() {
  const container = document.getElementById("analytics-content");
  try {
    const res = await fetch("/api/analytics");
    const json = await res.json();
    const a = json.analytics;

    container.innerHTML = `
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 20px;">
        <div style="background: rgba(0,0,0,0.3); padding: 14px; border-radius: 8px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.75rem; color: var(--text-secondary);">TOTAL FORWARD TRADES</div>
          <div style="font-size: 1.4rem; font-weight: 700;">${a.total_trades}</div>
        </div>
        <div style="background: rgba(0,0,0,0.3); padding: 14px; border-radius: 8px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.75rem; color: var(--text-secondary);">FORWARD WIN RATE</div>
          <div style="font-size: 1.4rem; font-weight: 700; color: var(--call-green);">${a.win_rate}%</div>
        </div>
        <div style="background: rgba(0,0,0,0.3); padding: 14px; border-radius: 8px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.75rem; color: var(--text-secondary);">NET FORWARD PnL</div>
          <div style="font-size: 1.4rem; font-weight: 700; color: ${a.total_pnl >= 0 ? 'var(--call-green)' : 'var(--put-red)'};">$${a.total_pnl}</div>
        </div>
      </div>
    `;
  } catch (e) {
    container.textContent = "Error loading analytics";
  }
}

async function loadHealth() {
  const container = document.getElementById("health-content");
  try {
    const res = await fetch("/api/health");
    const json = await res.json();

    const checkList = Object.entries(json.diagnostics).map(([k, v]) => `
      <div style="display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid var(--border-color);">
        <span style="font-weight: 600;">${k.toUpperCase().replace('_', ' ')}</span>
        <span style="color: ${v.status === 'OK' ? 'var(--call-green)' : 'var(--gold-accent)'};">● ${v.status} (${v.detail})</span>
      </div>
    `).join("");

    container.innerHTML = `
      <div style="margin-bottom: 16px;">
        ${checkList}
      </div>
      <div style="font-size: 0.8rem; color: var(--text-muted);">
        Uptime: ${json.metrics.uptime_seconds}s | Avg Latency: ${json.metrics.average_latency_ms}ms
      </div>
    `;
  } catch (e) {
    container.textContent = "Error loading diagnostics";
  }
}
