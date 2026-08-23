/*
=============================================================================
QUOTEX SIGNAL INTELLIGENCE PLATFORM — PRO DASHBOARD CONTROLLER
Real-time SocketIO client, mobile QR connect, audio/haptic alerts, backtesting
=============================================================================
*/

let socket = null;
let currentScannerData = [];
let soundEnabled = true;
let audioCtx = null;
let lastAlertedSignals = new Set();
let mobilePairingUrl = "";

document.addEventListener("DOMContentLoaded", () => {
  initSoundPreference();
  initClock();
  initSocket();
  loadInitialScan();
  loadPaperTrades();
  loadServerInfo();

  // Keyboard shortcut: Esc to close modals
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeModal();
      closeMobileModal();
    }
  });
});

// =============================================================================
// 1. Clock & Next Scan Countdown
// =============================================================================
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

// =============================================================================
// 2. Audio & Haptic Notification Synthesizer (Web Audio API)
// =============================================================================
function initSoundPreference() {
  const saved = localStorage.getItem("zia_sound_enabled");
  if (saved !== null) {
    soundEnabled = saved === "true";
  }
  updateSoundUI();
}

function toggleSound() {
  soundEnabled = !soundEnabled;
  localStorage.setItem("zia_sound_enabled", soundEnabled);
  updateSoundUI();
  if (soundEnabled) {
    playSignalAudio("CALL"); // Preview chime
  }
}

function updateSoundUI() {
  const icon = document.getElementById("sound-icon");
  const text = document.getElementById("sound-text");
  if (icon && text) {
    if (soundEnabled) {
      icon.textContent = "🔔";
      text.textContent = "Alerts ON";
    } else {
      icon.textContent = "🔕";
      text.textContent = "Muted";
    }
  }
}

function playSignalAudio(direction) {
  if (!soundEnabled) return;

  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    if (!audioCtx) audioCtx = new AudioContext();
    if (audioCtx.state === "suspended") {
      audioCtx.resume();
    }

    const now = audioCtx.currentTime;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);

    if (direction === "CALL") {
      // Pleasant rising harmonic chime
      osc.type = "sine";
      osc.frequency.setValueAtTime(523.25, now); // C5
      osc.frequency.exponentialRampToValueAtTime(783.99, now + 0.18); // G5
      gain.gain.setValueAtTime(0.25, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.4);
      osc.start(now);
      osc.stop(now + 0.45);
    } else if (direction === "PUT") {
      // Clear decisive descending tone
      osc.type = "triangle";
      osc.frequency.setValueAtTime(659.25, now); // E5
      osc.frequency.exponentialRampToValueAtTime(440.00, now + 0.18); // A4
      gain.gain.setValueAtTime(0.25, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.4);
      osc.start(now);
      osc.stop(now + 0.45);
    }

    // Mobile Haptic Vibration
    if ("vibrate" in navigator) {
      navigator.vibrate([100, 50, 100]);
    }
  } catch (e) {
    console.debug("Audio play blocked by browser policy until first user interaction", e);
  }
}

// =============================================================================
// 3. Real-time WebSocket Gateway
// =============================================================================
function initSocket() {
  try {
    socket = io();
    socket.on("connect", () => {
      console.log("[WebSocket] Connected to Zia Quant Platform gateway");
    });
    socket.on("market_update", (data) => {
      if (data && data.results) {
        checkAndAlertNewSignals(data.results);
        renderScanner(data.results);
      }
    });
  } catch (e) {
    console.warn("WebSocket fallback to polling:", e);
  }
}

function checkAndAlertNewSignals(results) {
  if (!results) return;
  for (const item of results) {
    if (item.is_viable && (item.direction === "CALL" || item.direction === "PUT") && item.evidence_score >= 65) {
      const sigKey = `${item.symbol}_${item.direction}_${Math.floor(Date.now() / 60000)}`;
      if (!lastAlertedSignals.has(sigKey)) {
        lastAlertedSignals.add(sigKey);
        playSignalAudio(item.direction);
        break; // Play once per cycle
      }
    }
  }
}

// =============================================================================
// 4. Tab Navigation
// =============================================================================
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

// =============================================================================
// 5. Scanner Engine & Heatmap Rendering
// =============================================================================
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
  if (container) {
    container.innerHTML = `
      <div class="loading-state">
        <div class="spinner"></div>
        <div style="margin-top: 14px; color: var(--cyan-accent); font-weight: 600;">
          Scanning currency pairs and liquidity structures across multiple timeframes...
        </div>
      </div>
    `;
  }
  await loadInitialScan();
}

function renderScanner(results) {
  currentScannerData = results;
  const container = document.getElementById("scanner-cards");
  if (!container) return;

  if (!results || results.length === 0) {
    container.innerHTML = `<div class="loading-state">No active market opportunities matching risk filter criteria.</div>`;
    return;
  }

  const assetCountEl = document.getElementById("asset-count");
  if (assetCountEl) assetCountEl.textContent = results.length;

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

        <div style="font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center;">
          <span>Evidence: <strong style="color: ${item.evidence_score >= 70 ? 'var(--call-green)' : 'var(--text-primary)'};">${item.evidence_score}/100</strong></span>
          ${item.is_viable ? '<span style="color: var(--call-green); font-weight: 600;">✅ Viable Setup</span>' : '<span style="color: var(--text-muted);">Filtered</span>'}
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

// =============================================================================
// 6. Inspect Signal Evidence Modal
// =============================================================================
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
        <span class="evidence-engine">${e.engine}</span>
        <span style="margin-left: 8px;">${e.description}</span>
      </div>
      <span style="color: var(--call-green); font-weight: 700; font-family: var(--font-mono);">+${e.weight}pts</span>
    </div>
  `).join("");

  body.innerHTML = `
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px;">
      <div style="background: rgba(0,0,0,0.35); padding: 14px; border-radius: 10px; border: 1px solid var(--border-color);">
        <div style="font-size: 0.72rem; color: var(--text-secondary); text-transform: uppercase;">EVIDENCE SCORE</div>
        <div style="font-size: 1.5rem; font-weight: 800; color: var(--call-green);">${sig.evidence_score}/100</div>
      </div>
      <div style="background: rgba(0,0,0,0.35); padding: 14px; border-radius: 10px; border: 1px solid var(--border-color);">
        <div style="font-size: 0.72rem; color: var(--text-secondary); text-transform: uppercase;">BREAK-EVEN WINRATE</div>
        <div style="font-size: 1.5rem; font-weight: 800; color: var(--gold-accent);">${Math.round(sig.breakeven_probability * 100)}%</div>
      </div>
    </div>

    <h4 style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 8px; text-transform: uppercase; font-weight: 700;">CONVICTION AUDIT REASONS</h4>
    <div class="evidence-list">
      ${evidenceRows || '<div style="color: var(--text-muted); padding: 10px;">No directional trigger active for this bar.</div>'}
    </div>

    <div style="margin-top: 16px; font-size: 0.8rem; color: var(--text-secondary); border-top: 1px solid var(--border-color); padding-top: 12px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
      <span>Entry Price: <strong style="color: var(--text-primary); font-family: var(--font-mono);">${sig.entry_price.toFixed(5)}</strong></span>
      <span>Recommended Expiry: <strong style="color: var(--text-primary);">${sig.recommended_expiry / 60} min</strong></span>
    </div>
  `;

  modal.style.display = "flex";
}

function closeModal() {
  const modal = document.getElementById("signal-modal");
  if (modal) modal.style.display = "none";
}

function onModalOverlayClick(e) {
  if (e.target.id === "signal-modal") {
    closeModal();
  }
}

// =============================================================================
// 7. Mobile Phone Connect & QR Pairing Modal
// =============================================================================
async function loadServerInfo() {
  try {
    const res = await fetch("/api/server-info");
    const json = await res.json();
    if (json.status === "success" && json.mobile_url) {
      mobilePairingUrl = json.mobile_url;
    }
  } catch (e) {
    mobilePairingUrl = window.location.origin;
  }
}

function openMobileModal() {
  const modal = document.getElementById("mobile-modal");
  const urlEl = document.getElementById("mobile-pairing-url");
  const qrContainer = document.getElementById("qr-code");

  const targetUrl = mobilePairingUrl || window.location.origin;
  if (urlEl) urlEl.textContent = targetUrl;

  if (qrContainer) {
    qrContainer.innerHTML = "";
    if (typeof QRCode !== "undefined") {
      new QRCode(qrContainer, {
        text: targetUrl,
        width: 170,
        height: 170,
        colorDark: "#07090e",
        colorLight: "#ffffff",
        correctLevel: QRCode.CorrectLevel.M
      });
    } else {
      qrContainer.innerHTML = `<a href="${targetUrl}" target="_blank" style="color: var(--cyan-accent);">${targetUrl}</a>`;
    }
  }

  if (modal) modal.style.display = "flex";
}

function closeMobileModal() {
  const modal = document.getElementById("mobile-modal");
  if (modal) modal.style.display = "none";
}

function onMobileModalOverlayClick(e) {
  if (e.target.id === "mobile-modal") {
    closeMobileModal();
  }
}

function copyMobileUrl() {
  const targetUrl = mobilePairingUrl || window.location.origin;
  navigator.clipboard.writeText(targetUrl).then(() => {
    const btn = document.querySelector(".btn-copy");
    if (btn) {
      const orig = btn.innerHTML;
      btn.innerHTML = "✅ Copied!";
      setTimeout(() => { btn.innerHTML = orig; }, 2000);
    }
  }).catch(() => {
    alert(`Mobile URL: ${targetUrl}`);
  });
}

// =============================================================================
// 8. Backtest Runner
// =============================================================================
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
        <div style="background: rgba(0,0,0,0.4); padding: 14px; border-radius: 10px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.72rem; color: var(--text-secondary);">WIN RATE</div>
          <div style="font-size: 1.4rem; font-weight: 700; color: ${r.win_rate >= r.breakeven_winrate ? 'var(--call-green)' : 'var(--put-red)'};">${r.win_rate}%</div>
          <div style="font-size: 0.7rem; color: var(--text-muted);">Break-even: ${r.breakeven_winrate}%</div>
        </div>

        <div style="background: rgba(0,0,0,0.4); padding: 14px; border-radius: 10px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.72rem; color: var(--text-secondary);">EXPECTED VALUE / TRADE</div>
          <div style="font-size: 1.4rem; font-weight: 700; color: ${r.expected_value_per_trade >= 0 ? 'var(--call-green)' : 'var(--put-red)'};">${r.expected_value_per_trade >= 0 ? '+' : ''}${r.expected_value_per_trade}</div>
          <div style="font-size: 0.7rem; color: var(--text-muted);">Payout: ${Math.round(payout * 100)}%</div>
        </div>

        <div style="background: rgba(0,0,0,0.4); padding: 14px; border-radius: 10px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.72rem; color: var(--text-secondary);">TOTAL TRADES</div>
          <div style="font-size: 1.4rem; font-weight: 700;">${r.total_trades}</div>
          <div style="font-size: 0.7rem; color: var(--text-muted);">${r.wins}W / ${r.losses}L / ${r.ties}T</div>
        </div>

        <div style="background: rgba(0,0,0,0.4); padding: 14px; border-radius: 10px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.72rem; color: var(--text-secondary);">TOTAL PnL (at $10 stake)</div>
          <div style="font-size: 1.4rem; font-weight: 700; color: ${r.total_pnl >= 0 ? 'var(--call-green)' : 'var(--put-red)'};">${r.total_pnl >= 0 ? '+' : ''}$${r.total_pnl}</div>
          <div style="font-size: 0.7rem; color: var(--text-muted);">Profit Factor: ${r.profit_factor}</div>
        </div>

        <div style="background: rgba(0,0,0,0.4); padding: 14px; border-radius: 10px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.72rem; color: var(--text-secondary);">MAX CONSECUTIVE LOSSES</div>
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

// =============================================================================
// 9. Paper Trading Logs
// =============================================================================
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

// =============================================================================
// 10. Analytics & Health Subsystems
// =============================================================================
async function loadAnalytics() {
  const container = document.getElementById("analytics-content");
  try {
    const res = await fetch("/api/analytics");
    const json = await res.json();
    const a = json.analytics;

    container.innerHTML = `
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 20px;">
        <div style="background: rgba(0,0,0,0.3); padding: 16px; border-radius: 10px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.72rem; color: var(--text-secondary);">TOTAL FORWARD TRADES</div>
          <div style="font-size: 1.5rem; font-weight: 800;">${a.total_trades}</div>
        </div>
        <div style="background: rgba(0,0,0,0.3); padding: 16px; border-radius: 10px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.72rem; color: var(--text-secondary);">FORWARD WIN RATE</div>
          <div style="font-size: 1.5rem; font-weight: 800; color: var(--call-green);">${a.win_rate}%</div>
        </div>
        <div style="background: rgba(0,0,0,0.3); padding: 16px; border-radius: 10px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.72rem; color: var(--text-secondary);">NET FORWARD PnL</div>
          <div style="font-size: 1.5rem; font-weight: 800; color: ${a.total_pnl >= 0 ? 'var(--call-green)' : 'var(--put-red)'};">$${a.total_pnl}</div>
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
      <div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid var(--border-color); flex-wrap: wrap; gap: 8px;">
        <span style="font-weight: 600;">${k.toUpperCase().replace(/_/g, ' ')}</span>
        <span style="color: ${v.status === 'OK' ? 'var(--call-green)' : 'var(--gold-accent)'};">● ${v.status} (${v.detail})</span>
      </div>
    `).join("");

    container.innerHTML = `
      <div style="margin-bottom: 16px;">
        ${checkList}
      </div>
      <div style="font-size: 0.8rem; color: var(--text-muted); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
        <span>Uptime: <strong>${json.metrics.uptime_seconds}s</strong></span>
        <span>Avg Latency: <strong>${json.metrics.average_latency_ms}ms</strong></span>
        <span>Mobile Link: <strong>${mobilePairingUrl || 'Active'}</strong></span>
      </div>
    `;
  } catch (e) {
    container.textContent = "Error loading diagnostics";
  }
}
