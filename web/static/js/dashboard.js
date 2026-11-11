/*
=============================================================================
QUOTEX SIGNAL INTELLIGENCE PLATFORM — PRODUCTION DASHBOARD CONTROLLER
Real-time SocketIO client, mobile QR connect, audio/haptic alerts,
fail-closed diagnostics, backtesting, paper trading, and MT5 bridge visibility
=============================================================================
*/

let socket = null;
let currentScannerData = [];
let lastDiagnostics = null;
let soundEnabled = true;
let audioCtx = null;
let lastAlertedSignals = new Set();
let mobilePairingUrl = "";
let selectedTimeframe = "1m";
let scanInFlight = false;
let backtestInFlight = false;
let platformConfig = null;

document.addEventListener("DOMContentLoaded", () => {
  initSoundPreference();
  initClock();
  initSocket();
  loadPlatformConfig();
  loadInitialScan(false);
  loadPaperTrades();
  loadServerInfo();
  refreshHeaderHealth();

  // Keep header health pill synced even while sitting on scanner tab
  setInterval(refreshHeaderHealth, 30000);

  // Handle mobile screen wake-up / tab focus
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      loadInitialScan(false);
      refreshHeaderHealth();
      if (socket && !socket.connected) {
        socket.connect();
      }
    }
  });

  window.addEventListener("focus", () => {
    loadInitialScan(false);
  });

  // Keyboard shortcut: Esc to close modals
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeModal();
      closeMobileModal();
    }
  });
});

// =============================================================================
// 0. Formatting & Sanitization Helpers
// =============================================================================
function escapeHtml(val) {
  if (val === null || val === undefined) return "";
  return String(val)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatPrice(price, symbol) {
  const num = Number(price);
  if (!Number.isFinite(num) || num <= 0) return "—";
  const sym = String(symbol || "").toUpperCase();
  if (sym.includes("BTC") || sym.includes("ETH") || sym.includes("XAU") || num >= 500) {
    return num.toFixed(2);
  }
  if (sym.includes("JPY") || sym.includes("XAG") || num >= 20) {
    return num.toFixed(3);
  }
  return num.toFixed(5);
}

function formatExpiry(seconds) {
  const sec = Number(seconds);
  if (!Number.isFinite(sec) || sec <= 0) return "1m (60s)";
  if (sec % 60 === 0) {
    const mins = sec / 60;
    return `${mins}m (${sec}s)`;
  }
  return `${sec}s`;
}

function formatUtcShort(isoStr) {
  if (!isoStr) return "—";
  const dt = new Date(isoStr);
  if (Number.isNaN(dt.getTime())) return "—";
  return dt.toISOString().replace("T", " ").slice(0, 19) + " UTC";
}

function getSourceBadge(source) {
  const s = String(source || "").toLowerCase();
  if (s === "mt5_bridge") {
    return '<span class="source-pill source-mt5">MT5</span>';
  }
  if (s === "yahoo") {
    return '<span class="source-pill">YAHOO</span>';
  }
  return '<span class="source-pill">NO FEED</span>';
}

function getStatusMeta(item) {
  const reason = item.status_reason || (item.is_viable ? "emitted" : "no_setup");
  switch (reason) {
    case "emitted":
      return item.is_viable
        ? { label: "✅ Active Trade", color: "var(--call-green)", degraded: false }
        : { label: "⏸ Signal Gated", color: "var(--gold-accent)", degraded: false };
    case "unavailable_or_stale":
      return { label: "⚠ Feed Unavailable / Stale", color: "var(--put-red)", degraded: true };
    case "validator_failed":
      return { label: "⚠ Data Quality Failed", color: "var(--put-red)", degraded: true };
    case "warmup_insufficient":
      return { label: "⏳ Warmup Insufficient", color: "var(--gold-accent)", degraded: true };
    case "error":
      return { label: "⚠ Scan Error", color: "var(--put-red)", degraded: true };
    case "conflicting_evidence":
      return { label: "⚖ Mixed Confluence", color: "var(--gold-accent)", degraded: false };
    case "low_score":
      return { label: "📉 Low Conviction", color: "var(--text-muted)", degraded: false };
    case "payout_or_risk_rejected":
      return { label: "🛡 Risk / Regime Blocked", color: "var(--gold-accent)", degraded: false };
    case "no_setup":
    default:
      return { label: "⏸ Consolidation", color: "var(--text-muted)", degraded: false };
  }
}

function setLiveIndicator(mode, label) {
  const pill = document.getElementById("live-indicator");
  const textEl = document.getElementById("live-indicator-text");
  if (!pill || !textEl) return;
  pill.classList.remove("degraded", "offline");
  if (mode === "degraded") pill.classList.add("degraded");
  if (mode === "offline") pill.classList.add("offline");
  textEl.textContent = label;
}

// =============================================================================
// 1. Clock & Next Scan Countdown
// =============================================================================
function initClock() {
  function update() {
    const now = new Date();
    const utcHours = String(now.getUTCHours()).padStart(2, "0");
    const utcMins = String(now.getUTCMinutes()).padStart(2, "0");
    const utcSecs = String(now.getUTCSeconds()).padStart(2, "0");
    const utcStr = `${utcHours}:${utcMins}:${utcSecs} UTC`;
    const currentMinuteStr = `${utcHours}:${utcMins} UTC`;

    const clockEl = document.getElementById("utc-clock");
    if (clockEl) clockEl.textContent = utcStr;

    const secondsLeft = 60 - now.getUTCSeconds();
    const cdEl = document.getElementById("countdown-timer");
    if (cdEl) cdEl.textContent = `${secondsLeft}s`;

    document.querySelectorAll(".live-candle-timer").forEach(el => {
      el.textContent = `${secondsLeft}s`;
    });

    document.querySelectorAll(".live-current-minute").forEach(el => {
      el.textContent = currentMinuteStr;
    });
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
    playSignalAudio("CALL");
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
      osc.type = "sine";
      osc.frequency.setValueAtTime(523.25, now);
      osc.frequency.exponentialRampToValueAtTime(783.99, now + 0.18);
      gain.gain.setValueAtTime(0.25, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.4);
      osc.start(now);
      osc.stop(now + 0.45);
    } else if (direction === "PUT") {
      osc.type = "triangle";
      osc.frequency.setValueAtTime(659.25, now);
      osc.frequency.exponentialRampToValueAtTime(440.00, now + 0.18);
      gain.gain.setValueAtTime(0.25, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.4);
      osc.start(now);
      osc.stop(now + 0.45);
    }

    if ("vibrate" in navigator) {
      navigator.vibrate([100, 50, 100]);
    }
  } catch (e) {
    console.debug("Audio play blocked until first interaction", e);
  }
}

// =============================================================================
// 3. Config & Header Health Sync
// =============================================================================
async function loadPlatformConfig() {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const json = await res.json();
    if (json.status !== "success") return;
    platformConfig = json;

    const btAssetEl = document.getElementById("bt-asset");
    if (btAssetEl && Array.isArray(json.assets) && json.assets.length > 0) {
      const current = btAssetEl.value;
      btAssetEl.innerHTML = json.assets
        .map(a => `<option value="${escapeHtml(a.symbol)}">${escapeHtml(a.name)}</option>`)
        .join("");
      if (json.assets.some(a => a.symbol === current)) {
        btAssetEl.value = current;
      }
    }

    const assetCountEl = document.getElementById("asset-count");
    if (assetCountEl && Array.isArray(json.assets)) {
      assetCountEl.textContent = String(json.assets.length);
    }
  } catch (e) {
    console.debug("Config fetch skipped:", e);
  }
}

async function refreshHeaderHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) {
      setLiveIndicator("offline", "API ERROR");
      return;
    }
    const json = await res.json();
    const state = json.health_state || (json.healthy ? "healthy" : "degraded");
    const bridge = (json.diagnostics && json.diagnostics.mt5_bridge) || {};
    if (state === "healthy") {
      setLiveIndicator("ok", bridge.enabled ? "MT5 LIVE" : "LIVE FEED");
    } else if (state === "failed") {
      setLiveIndicator("offline", "SYSTEM FAILED");
    } else {
      setLiveIndicator("degraded", bridge.enabled && bridge.status !== "OK" ? "MT5 DEGRADED" : "DEGRADED");
    }
  } catch (e) {
    setLiveIndicator("offline", "OFFLINE");
  }
}

// =============================================================================
// 4. Real-time WebSocket Gateway
// =============================================================================
function initSocket() {
  try {
    if (typeof io === "undefined") {
      setLiveIndicator("degraded", "POLLING ONLY");
      return;
    }
    socket = io();
    socket.on("connect", () => {
      refreshHeaderHealth();
    });
    socket.on("disconnect", () => {
      setLiveIndicator("offline", "RECONNECTING");
    });
    socket.on("market_update", (data) => {
      if (data && Array.isArray(data.results)) {
        checkAndAlertNewSignals(data.results);
        renderScanner(data.results, data.diagnostics || null);
      }
    });
  } catch (e) {
    console.warn("WebSocket fallback to polling:", e);
    setLiveIndicator("degraded", "POLLING ONLY");
  }
}

function checkAndAlertNewSignals(results) {
  if (!results) return;
  for (const item of results) {
    if (item.is_viable && (item.direction === "CALL" || item.direction === "PUT") && item.evidence_score >= 55) {
      const sigKey = `${item.symbol}_${item.direction}_${Math.floor(Date.now() / 60000)}`;
      if (!lastAlertedSignals.has(sigKey)) {
        lastAlertedSignals.add(sigKey);
        playSignalAudio(item.direction);
        break;
      }
    }
  }
}

// =============================================================================
// 5. Tab Navigation
// =============================================================================
function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c => { c.style.display = "none"; });

  const activeBtn = Array.from(document.querySelectorAll(".tab-btn")).find(b => {
    const oc = b.getAttribute("onclick") || "";
    return oc.includes(`'${tabId}'`);
  });
  if (activeBtn) activeBtn.classList.add("active");

  const targetTab = document.getElementById(`tab-${tabId}`);
  if (targetTab) targetTab.style.display = "block";

  if (tabId === "paper") loadPaperTrades();
  if (tabId === "analytics") loadAnalytics();
  if (tabId === "health") loadHealth();
}

// =============================================================================
// 6. Scanner Engine & Heatmap Rendering
// =============================================================================
function onScannerTimeframeChange() {
  const tfEl = document.getElementById("scanner-tf");
  selectedTimeframe = tfEl ? tfEl.value : "1m";
  loadInitialScan(true);
}

async function loadInitialScan(forceRefresh = false) {
  if (scanInFlight) return;
  scanInFlight = true;
  const scanBtn = document.getElementById("btn-instant-scan");
  if (scanBtn) scanBtn.disabled = true;

  try {
    const tf = selectedTimeframe || "1m";
    const url = `/api/scan?timeframe=${encodeURIComponent(tf)}${forceRefresh ? "&force_refresh=1" : ""}`;
    const res = await fetch(url);
    const json = await res.json();
    if (res.ok && json.status === "success") {
      renderScanner(json.results, json.diagnostics || null);
    } else {
      renderScannerError(json.message || `Scan failed (HTTP ${res.status})`);
    }
  } catch (err) {
    console.error("Scan request error:", err);
    renderScannerError(`Network error contacting scanner API: ${err}`);
  } finally {
    scanInFlight = false;
    if (scanBtn) scanBtn.disabled = false;
  }
}

async function triggerManualScan() {
  const container = document.getElementById("scanner-cards");
  if (container) {
    container.innerHTML = `
      <div class="loading-state">
        <div class="spinner"></div>
        <div style="margin-top: 14px; color: var(--cyan-accent); font-weight: 600;">
          Running fresh scan on ${escapeHtml(selectedTimeframe)} closed candles...
        </div>
      </div>
    `;
  }
  await loadInitialScan(true);
  await refreshHeaderHealth();
}

function renderScannerError(msg) {
  const container = document.getElementById("scanner-cards");
  if (container) {
    container.innerHTML = `<div class="loading-state" style="color: var(--put-red);">${escapeHtml(msg)}</div>`;
  }
}

function renderDiagnosticsBar(results, diagnostics) {
  const bar = document.getElementById("scanner-diagnostics-bar");
  if (!bar) return;
  lastDiagnostics = diagnostics || lastDiagnostics;
  const total = results.length;
  const viable = results.filter(r => r.is_viable).length;
  const unavailable = results.filter(r => ["unavailable_or_stale", "validator_failed", "error"].includes(r.status_reason)).length;
  const warmup = results.filter(r => r.status_reason === "warmup_insufficient").length;
  const mt5Count = results.filter(r => String(r.data_source || "").toLowerCase() === "mt5_bridge").length;
  const yahooCount = results.filter(r => String(r.data_source || "").toLowerCase() === "yahoo").length;
  const tf = (lastDiagnostics && lastDiagnostics.timeframe) || selectedTimeframe || "1m";

  bar.innerHTML = `
    <span>TF: <strong style="color: var(--cyan-accent);">${escapeHtml(tf)}</strong> • Active Signals: <strong style="color: ${viable > 0 ? 'var(--call-green)' : 'var(--text-primary)'};">${viable}/${total}</strong></span>
    <span>Sources: <strong>${mt5Count} MT5</strong> / <strong>${yahooCount} Yahoo</strong></span>
    <span>Degraded/Warmup: <strong style="color: ${(unavailable + warmup) > 0 ? 'var(--gold-accent)' : 'var(--call-green)'};">${unavailable} unavail, ${warmup} warmup</strong></span>
  `;
}

function buildCombinedScannerItems(results, diagnostics) {
  const base = Array.isArray(results) ? [...results] : [];
  const seen = new Set(base.map(r => r.symbol));
  const statuses = (diagnostics && diagnostics.asset_statuses) || {};
  const metaMap = {};
  if (platformConfig && Array.isArray(platformConfig.assets)) {
    for (const a of platformConfig.assets) {
      metaMap[a.symbol] = a;
    }
  }
  const tf = (diagnostics && diagnostics.timeframe) || selectedTimeframe || "1m";
  const defaultExpiry = tf === "15m" ? 900 : (tf === "5m" ? 300 : 60);

  for (const [sym, st] of Object.entries(statuses)) {
    if (seen.has(sym)) continue;
    const assetMeta = metaMap[sym] || {};
    base.push({
      symbol: sym,
      name: assetMeta.name || sym,
      category: assetMeta.category || "",
      payout: assetMeta.payout || 0.80,
      current_price: 0,
      direction: st.direction || "NO_TRADE",
      strength: "NEUTRAL",
      evidence_score: st.evidence_score || 0,
      recommended_expiry: defaultExpiry,
      is_viable: false,
      regime_desc: st.status_reason || "unavailable",
      strategies_triggered: [],
      status_reason: st.status_reason || "unavailable_or_stale",
      rejection_detail: st.detail || "Feed unavailable or insufficient closed history",
      data_source: st.source || "",
      latest_candle_time: st.latest_candle_time || null,
      signal_details: null,
    });
  }
  return base;
}

function renderScanner(results, diagnostics = null) {
  const combinedItems = buildCombinedScannerItems(results, diagnostics);
  currentScannerData = combinedItems;
  const container = document.getElementById("scanner-cards");
  if (!container) return;

  if (!combinedItems || combinedItems.length === 0) {
    renderDiagnosticsBar([], diagnostics);
    container.innerHTML = `<div class="loading-state">No active market signals or configured assets available.</div>`;
    return;
  }

  renderDiagnosticsBar(combinedItems, diagnostics);

  const assetCountEl = document.getElementById("asset-count");
  if (assetCountEl) assetCountEl.textContent = String(combinedItems.length);

  const now = new Date();
  const utcHours = String(now.getUTCHours()).padStart(2, "0");
  const utcMins = String(now.getUTCMinutes()).padStart(2, "0");
  const currentMinuteStr = `${utcHours}:${utcMins} UTC`;
  const secondsLeft = 60 - now.getUTCSeconds();

  container.innerHTML = combinedItems.map((item, idx) => {
    const isCall = item.direction === "CALL";
    const isPut = item.direction === "PUT";
    const statusMeta = getStatusMeta(item);
    const highlightClass = isCall ? "highlight-call" : (isPut ? "highlight-put" : (statusMeta.degraded ? "status-degraded" : ""));
    const badgeClass = escapeHtml(item.direction || "NO_TRADE");
    const priceText = formatPrice(item.current_price, item.symbol);
    const expiryLabel = formatExpiry(item.recommended_expiry);
    const score = Number.isFinite(Number(item.evidence_score)) ? Math.max(0, Math.min(100, Number(item.evidence_score))) : 0;

    return `
      <div class="asset-card ${highlightClass}" onclick="openInspectModal(${idx})" data-symbol="${escapeHtml(item.symbol)}">
        <div class="card-header">
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <span class="asset-symbol">${escapeHtml(item.name || item.symbol)}</span>
            ${getSourceBadge(item.data_source)}
          </div>
          <div class="asset-payout">Payout ${Math.round((item.payout || 0) * 100)}%</div>
        </div>

        <div class="card-body">
          <div class="price-box">${escapeHtml(priceText)}</div>
          <div class="signal-badge ${badgeClass}">${escapeHtml(item.direction || "NO_TRADE")} ${isCall ? "▲" : (isPut ? "▼" : "—")}</div>
        </div>

        <div style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); border-radius: 8px; padding: 6px 10px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; font-size: 0.76rem;">
          <span style="color: var(--text-secondary);">🕐 Bar: <strong class="live-current-minute" style="color: var(--cyan-accent); font-family: var(--font-mono);">${currentMinuteStr}</strong></span>
          <span style="color: ${item.is_viable ? 'var(--call-green)' : 'var(--gold-accent)'}; font-weight: 700; font-family: var(--font-mono);">⏳ <span class="live-candle-timer">${secondsLeft}s</span> left</span>
        </div>

        <div style="font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center; gap: 8px;">
          <span>Evidence: <strong style="color: ${score >= 55 ? 'var(--call-green)' : 'var(--text-primary)'};">${score}/100</strong></span>
          <span style="color: ${statusMeta.color}; font-weight: 600;">${statusMeta.label}</span>
        </div>

        <div class="score-bar-container">
          <div class="score-bar" style="width: ${score}%;"></div>
        </div>

        <div class="card-footer">
          <span>Expiry: <strong style="color: var(--call-green);">${escapeHtml(expiryLabel)}</strong></span>
          <span>Regime: <strong>${escapeHtml(item.regime_desc || "Unavailable")}</strong></span>
        </div>
      </div>
    `;
  }).join("");
}

// =============================================================================
// 7. Inspect Signal / Asset Diagnostic Modal
// =============================================================================
function openInspectModal(idx) {
  const item = currentScannerData[idx];
  if (!item) return;

  const modal = document.getElementById("signal-modal");
  const title = document.getElementById("modal-title");
  const body = document.getElementById("modal-body");
  const statusMeta = getStatusMeta(item);

  const now = new Date();
  const utcHours = String(now.getUTCHours()).padStart(2, "0");
  const utcMins = String(now.getUTCMinutes()).padStart(2, "0");
  const nextMin = String((now.getUTCMinutes() + 1) % 60).padStart(2, "0");
  const nextHour = String(now.getUTCMinutes() === 59 ? (now.getUTCHours() + 1) % 24 : now.getUTCHours()).padStart(2, "0");
  const secondsLeft = 60 - now.getUTCSeconds();

  const sig = item.signal_details;
  if (!sig) {
    title.innerHTML = `<span>${escapeHtml(item.name || item.symbol)}</span> — <strong>${escapeHtml(statusMeta.label)}</strong>`;
    body.innerHTML = `
      <div style="background: rgba(255, 51, 102, 0.08); border: 1px solid rgba(255, 51, 102, 0.3); border-radius: 10px; padding: 14px; margin-bottom: 14px;">
        <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">STATUS REASON</div>
        <div style="font-size: 1rem; font-weight: 700; color: ${statusMeta.color}; margin-top: 4px;">${escapeHtml(item.status_reason || "unavailable")}</div>
        <div style="font-size: 0.85rem; color: var(--text-primary); margin-top: 6px;">${escapeHtml(item.rejection_detail || item.regime_desc || "No diagnostic detail reported.")}</div>
      </div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; font-size: 0.82rem;">
        <div>Data Source: <strong>${escapeHtml(item.data_source || "none")}</strong></div>
        <div>Latest Closed Bar: <strong style="font-family: var(--font-mono);">${escapeHtml(formatUtcShort(item.latest_candle_time))}</strong></div>
        <div>Last Price: <strong style="font-family: var(--font-mono);">${escapeHtml(formatPrice(item.current_price, item.symbol))}</strong></div>
        <div>Timeframe: <strong>${escapeHtml(selectedTimeframe)}</strong></div>
      </div>
    `;
    modal.style.display = "flex";
    return;
  }

  title.innerHTML = `<span>${escapeHtml(item.name || item.symbol)}</span> — <strong>${escapeHtml(sig.direction)} (${escapeHtml(sig.strength)}) • ${escapeHtml(sig.timeframe || selectedTimeframe)}</strong>`;

  const evidenceRows = (sig.evidence || []).map(e => `
    <div class="evidence-item">
      <div>
        <span class="evidence-engine">${escapeHtml(e.engine)}</span>
        <span style="margin-left: 8px;">${escapeHtml(e.description)}</span>
      </div>
      <span style="color: var(--call-green); font-weight: 700; font-family: var(--font-mono);">+${Number(e.weight || 0)}pts</span>
    </div>
  `).join("");

  const bePct = Number.isFinite(Number(sig.breakeven_probability)) ? Math.round(sig.breakeven_probability * 100) : 0;
  const probText = sig.is_ml_active && sig.model_probability !== null && sig.model_probability !== undefined
    ? `${(Number(sig.model_probability) * 100).toFixed(1)}% (ML Calibrated)`
    : `Score ${sig.evidence_score}/100 (Uncalibrated)`;

  body.innerHTML = `
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px;">
      <div style="background: rgba(0,0,0,0.35); padding: 12px 14px; border-radius: 10px; border: 1px solid var(--border-color);">
        <div style="font-size: 0.72rem; color: var(--text-secondary); text-transform: uppercase;">EVIDENCE & CONFIDENCE</div>
        <div style="font-size: 1.3rem; font-weight: 800; color: var(--call-green);">${escapeHtml(probText)}</div>
      </div>
      <div style="background: rgba(0,0,0,0.35); padding: 12px 14px; border-radius: 10px; border: 1px solid var(--border-color);">
        <div style="font-size: 0.72rem; color: var(--text-secondary); text-transform: uppercase;">BREAK-EVEN WINRATE</div>
        <div style="font-size: 1.5rem; font-weight: 800; color: var(--gold-accent);">${bePct}%</div>
      </div>
    </div>

    <div style="background: rgba(0,230,153,0.06); border: 1px solid rgba(0,230,153,0.25); border-radius: 10px; padding: 12px 16px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
      <div>
        <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Current Bar Window</div>
        <div style="font-size: 0.95rem; font-weight: 700; color: var(--cyan-accent); font-family: var(--font-mono);">
          ${utcHours}:${utcMins}:00 UTC ➔ ${nextHour}:${nextMin}:00 UTC
        </div>
      </div>
      <div style="text-align: right;">
        <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">1m Bar Closes In</div>
        <div style="font-size: 1.3rem; font-weight: 800; color: var(--gold-accent); font-family: var(--font-mono);">
          <span class="live-candle-timer">${secondsLeft}s</span>
        </div>
      </div>
    </div>

    ${item.rejection_detail ? `<div style="font-size: 0.82rem; color: var(--gold-accent); margin-bottom: 10px;">Status Detail: <strong>${escapeHtml(item.rejection_detail)}</strong></div>` : ""}

    <h4 style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 8px; text-transform: uppercase; font-weight: 700;">CONVICTION AUDIT REASONS</h4>
    <div class="evidence-list">
      ${evidenceRows || '<div style="color: var(--text-muted); padding: 10px;">No directional confluence on this candle.</div>'}
    </div>

    <div style="margin-top: 16px; font-size: 0.8rem; color: var(--text-secondary); border-top: 1px solid var(--border-color); padding-top: 12px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
      <span>Entry Price: <strong style="color: var(--text-primary); font-family: var(--font-mono);">${escapeHtml(formatPrice(sig.entry_price, item.symbol))}</strong></span>
      <span>Source: <strong>${escapeHtml(item.data_source || "unknown")}</strong></span>
      <span>Expiry: <strong style="color: var(--call-green);">${escapeHtml(formatExpiry(item.recommended_expiry || sig.recommended_expiry))}</strong></span>
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
// 8. Mobile Phone Connect & QR Pairing Modal
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

  const isPublicHttps = window.location.protocol === "https:" || !window.location.hostname.match(/^(127\.0\.0\.1|localhost)$/);
  const targetUrl = isPublicHttps ? window.location.origin : (mobilePairingUrl || window.location.origin);
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
      qrContainer.innerHTML = `<a href="${escapeHtml(targetUrl)}" target="_blank" style="color: var(--cyan-accent);">${escapeHtml(targetUrl)}</a>`;
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
  const isPublicHttps = window.location.protocol === "https:" || !window.location.hostname.match(/^(127\.0\.0\.1|localhost)$/);
  const targetUrl = isPublicHttps ? window.location.origin : (mobilePairingUrl || window.location.origin);
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
// 9. Backtest Runner
// =============================================================================
async function runBacktest() {
  if (backtestInFlight) return;
  const asset = document.getElementById("bt-asset").value;
  const tfEl = document.getElementById("bt-timeframe");
  const timeframe = tfEl ? tfEl.value : "1m";
  const period = document.getElementById("bt-period").value;
  const lag = parseInt(document.getElementById("bt-lag").value, 10);
  const payout = parseFloat(document.getElementById("bt-payout").value);

  const runBtn = document.getElementById("btn-run-backtest");
  const resultsPanel = document.getElementById("bt-results-panel");
  const metricsContainer = document.getElementById("bt-metrics-cards");

  backtestInFlight = true;
  if (runBtn) runBtn.disabled = true;
  resultsPanel.style.display = "block";
  metricsContainer.innerHTML = `<div style="color: var(--cyan-accent); padding: 20px;">Running walk-forward simulation on ${escapeHtml(asset)} (${escapeHtml(timeframe)}) with ${lag}s execution lag...</div>`;

  try {
    const res = await fetch("/api/backtest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: asset, timeframe, period, execution_lag: lag, payout })
    });
    const json = await res.json();

    if (res.ok && json.status === "success") {
      const r = json.report;
      const prov = r.provenance || {};
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
          <div style="font-size: 0.72rem; color: var(--text-secondary);">RISK & STREAKS</div>
          <div style="font-size: 1.4rem; font-weight: 700; color: var(--put-red);">${r.max_consecutive_losses} max L</div>
          <div style="font-size: 0.7rem; color: var(--text-muted);">Max Win Streak: ${r.max_consecutive_wins}</div>
        </div>

        <div style="background: rgba(0,0,0,0.4); padding: 14px; border-radius: 10px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.72rem; color: var(--text-secondary);">PROVENANCE AUDIT</div>
          <div style="font-size: 0.88rem; font-weight: 700; color: var(--cyan-accent);">${escapeHtml(r.data_source || 'market_data')} • ${escapeHtml(prov.fill_mode || 'causal')}</div>
          <div style="font-size: 0.7rem; color: var(--text-muted);">Lag: ${prov.execution_lag_seconds ?? lag}s • Bars: ${prov.clean_candles ?? prov.raw_candles ?? prov.candles_tested ?? 'N/A'}</div>
        </div>
      `;
    } else {
      metricsContainer.innerHTML = `<div style="color: var(--put-red);">${escapeHtml(json.message || "Simulation error")}</div>`;
    }
  } catch (err) {
    metricsContainer.innerHTML = `<div style="color: var(--put-red);">Backtest API connection error: ${escapeHtml(err)}</div>`;
  } finally {
    backtestInFlight = false;
    if (runBtn) runBtn.disabled = false;
  }
}

// =============================================================================
// 10. Paper Trading Logs
// =============================================================================
async function loadPaperTrades() {
  const tbody = document.getElementById("paper-trades-body");
  if (!tbody) return;

  try {
    const res = await fetch("/api/paper-trades");
    const json = await res.json();
    if (!res.ok) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--put-red); padding: 20px;">Failed to load paper trades (HTTP ${res.status})</td></tr>`;
      return;
    }

    if (json.trades && json.trades.length > 0) {
      tbody.innerHTML = json.trades.map(t => {
        const pnlVal = Number(t.pnl || 0);
        const pnlColor = pnlVal > 0 ? "var(--call-green)" : (pnlVal < 0 ? "var(--put-red)" : "var(--text-muted)");
        const expiryDisplay = t.expiry_price !== null && t.expiry_price !== undefined && Number(t.expiry_price) > 0
          ? formatPrice(t.expiry_price, t.asset)
          : (t.is_settled ? "N/A (Unresolved)" : "⏳ In Trade");
        const outcomeColor = t.outcome === "WIN"
          ? "var(--call-green)"
          : (t.outcome === "LOSS" ? "var(--put-red)" : "var(--gold-accent)");

        return `
          <tr title="${escapeHtml(t.settlement_detail || t.entry_source || '')}">
            <td style="font-family: var(--font-mono);">${escapeHtml(formatUtcShort(t.entry_time))}</td>
            <td><strong>${escapeHtml(t.asset)}</strong></td>
            <td><span class="signal-badge ${escapeHtml(t.direction)}" style="padding: 2px 8px; font-size: 0.75rem;">${escapeHtml(t.direction)}</span></td>
            <td style="font-family: var(--font-mono);">${escapeHtml(formatPrice(t.entry_price, t.asset))}</td>
            <td style="font-family: var(--font-mono);">${escapeHtml(expiryDisplay)}</td>
            <td>$${Number(t.stake || 0)}</td>
            <td style="color: ${outcomeColor};"><strong>${escapeHtml(t.outcome)}</strong></td>
            <td style="font-family: var(--font-mono); font-weight: 700; color: ${pnlColor};">${pnlVal >= 0 ? "+" : ""}$${pnlVal.toFixed(2)}</td>
          </tr>
        `;
      }).join("");
    } else {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 30px;">No paper trades recorded yet. Autopilot opens trades on high conviction signals.</td>
        </tr>
      `;
    }
  } catch (e) {
    console.error("Paper trades error:", e);
    tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--put-red); padding: 20px;">Error loading paper trades feed.</td></tr>`;
  }
}

// =============================================================================
// 11. Analytics & Health Subsystems
// =============================================================================
async function loadAnalytics() {
  const container = document.getElementById("analytics-content");
  if (!container) return;
  try {
    const res = await fetch("/api/analytics");
    const json = await res.json();
    const a = (json && json.analytics) || {};
    const byAssetRows = Object.entries(a.by_asset || {}).map(([sym, d]) => `
      <tr>
        <td><strong>${escapeHtml(sym)}</strong></td>
        <td>${Number(d.total || 0)}</td>
        <td>${Number(d.wins || 0)}W / ${Number(d.losses || 0)}L / ${Number(d.ties || 0)}T</td>
        <td>${Number(d.win_rate || 0)}%</td>
        <td style="font-family: var(--font-mono); color: ${Number(d.pnl) >= 0 ? 'var(--call-green)' : 'var(--put-red)'};">$${Number(d.pnl || 0).toFixed(2)}</td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); gap: 14px; margin-bottom: 20px;">
        <div style="background: rgba(0,0,0,0.3); padding: 16px; border-radius: 10px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.72rem; color: var(--text-secondary);">SETTLED TRADES</div>
          <div style="font-size: 1.5rem; font-weight: 800;">${Number(a.total_trades || 0)}</div>
          <div style="font-size: 0.72rem; color: var(--text-muted);">${Number(a.wins || 0)}W / ${Number(a.losses || 0)}L / ${Number(a.ties || 0)}T / ${Number(a.unresolved || 0)} Unres</div>
        </div>
        <div style="background: rgba(0,0,0,0.3); padding: 16px; border-radius: 10px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.72rem; color: var(--text-secondary);">DECISIVE WIN RATE</div>
          <div style="font-size: 1.5rem; font-weight: 800; color: var(--call-green);">${Number(a.win_rate || 0)}%</div>
          <div style="font-size: 0.72rem; color: var(--text-muted);">Profit Factor: ${Number(a.profit_factor || 0)}</div>
        </div>
        <div style="background: rgba(0,0,0,0.3); padding: 16px; border-radius: 10px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.72rem; color: var(--text-secondary);">NET FORWARD PnL</div>
          <div style="font-size: 1.5rem; font-weight: 800; color: ${Number(a.total_pnl || 0) >= 0 ? 'var(--call-green)' : 'var(--put-red)'};">$${Number(a.total_pnl || 0).toFixed(2)}</div>
        </div>
      </div>
      ${byAssetRows ? `
        <div class="responsive-table-wrapper">
          <table>
            <thead>
              <tr><th>Asset</th><th>Total</th><th>W / L / T</th><th>Win Rate</th><th>PnL</th></tr>
            </thead>
            <tbody>${byAssetRows}</tbody>
          </table>
        </div>` : '<div style="font-size: 0.85rem; color: var(--text-muted);">No settled asset breakdowns yet.</div>'}
    `;
  } catch (e) {
    container.textContent = "Error loading analytics";
  }
}

async function loadHealth() {
  const container = document.getElementById("health-content");
  if (!container) return;
  try {
    const res = await fetch("/api/health");
    const json = await res.json();
    const overall = String(json.health_state || "degraded").toUpperCase();
    const overallColor = overall === "HEALTHY"
      ? "var(--call-green)"
      : (overall === "FAILED" ? "var(--put-red)" : "var(--gold-accent)");

    const checkList = Object.entries(json.diagnostics || {}).map(([k, v]) => {
      const st = String(v.status || "UNKNOWN").toUpperCase();
      const color = st === "OK"
        ? "var(--call-green)"
        : ((st === "FAIL" || st === "FAILED") ? "var(--put-red)" : (st === "DISABLED" || st === "IDLE" ? "var(--text-secondary)" : "var(--gold-accent)"));
      const detail = v.detail || JSON.stringify(v);
      return `
        <div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid var(--border-color); flex-wrap: wrap; gap: 8px;">
          <span style="font-weight: 600;">${escapeHtml(k.toUpperCase().replace(/_/g, " "))}</span>
          <span style="color: ${color};">● ${escapeHtml(st)} (${escapeHtml(detail)})</span>
        </div>
      `;
    }).join("");

    const rt = json.runtime || {};
    container.innerHTML = `
      <div class="health-state-banner">
        <div>Overall State: <strong style="color: ${overallColor};">${escapeHtml(overall)}</strong></div>
        <div style="font-size: 0.78rem; color: var(--text-secondary);">Cycles: <strong>${Number(rt.cycles_total || 0)}</strong> • Consecutive Fails: <strong>${Number(rt.consecutive_failed_cycles || 0)}</strong></div>
      </div>
      <div style="margin-bottom: 16px;">
        ${checkList}
      </div>
      <div style="font-size: 0.8rem; color: var(--text-muted); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
        <span>Uptime: <strong>${Number((json.metrics || {}).uptime_seconds || 0)}s</strong></span>
        <span>Avg Latency: <strong>${Number((json.metrics || {}).average_latency_ms || 0)}ms</strong></span>
        <span>Web URL: <strong>${escapeHtml(mobilePairingUrl || window.location.origin)}</strong></span>
      </div>
    `;
  } catch (e) {
    container.textContent = "Error loading diagnostics";
  }
}
