# ⚡ ZIA QUANT — Quotex Signal Intelligence Platform

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Framework: Flask](https://img.shields.io/badge/framework-Flask%20%2B%20SocketIO-green.svg)](https://flask.palletsprojects.com/)
[![Trading: Binary Options](https://img.shields.io/badge/trading-Quotex%20Signals-orange.svg)](https://quotex.com/)
[![Status: Production](https://img.shields.io/badge/status-Production%20Ready-emerald.svg)]()

> **Institutional-Grade Quantitative Research, Real-Time Market Scanner & Signal Intelligence Engine for Binary Options (Quotex).**

---

## 🌟 Executive Summary

**Zia Quant** is a quantitative trading intelligence platform built to eliminate emotional guessing in binary options trading. Unlike typical retail bots that rely on a single lagging oscillator, Zia Quant fuses **6 independent market engines** across 10 global asset streams to generate high-probability **CALL (UP)** and **PUT (DOWN)** signals with exact recommended expiry durations and mathematical proof.

---

## 🚀 Key Features

- **📡 Live Opportunity Heatmap:** Real-time 60-second multi-asset scanner monitoring Forex (`EUR/USD`, `GBP/USD`, `USD/JPY`, `AUD/USD`, `USD/CAD`, `USD/CHF`), Commodities (`Gold`, `Silver`), and 24/7 Crypto (`BTC/USD`, `ETH/USD`).
- **🧠 6 Independent Quantitative Strategy Engines:**
  1. *Smart Money Liquidity Engine* (Equal Highs/Lows & Liquidity Sweeps)
  2. *Institutional Zones Engine* (Support/Resistance Clustering, Order Blocks, Fair Value Gaps)
  3. *Market Structure Engine* (HH, HL, LH, LL, Break of Structure, Change of Character)
  4. *Technical Indicator Engine* (EMA 9/21/50/200, RSI, MACD, Bollinger Bands, ADX)
  5. *Quantitative Candle Anatomy* (Body-to-wick ratios, Pin Bars, Engulfing, Rejection Tails)
  6. *Economic Payout Gatekeeper* (Strict break-even math with margin of safety)
- **🎯 3-Tier Confidence System:** Combines evidence confluence, machine learning probability, and economic viability.
- **🛡️ Capital Protection & Risk Guardrails:** Asset cooldowns, consecutive loss circuit breakers, and abnormal move news filters.
- **🧪 Walk-Forward Backtest Lab:** Interactive browser-based simulation modeling a **3-second execution delay** and **1-pip broker spread**.
- **📝 Autopilot Paper Trading:** Automatically opens and settles simulated forward trades to audit win rate with zero real money risk.
- **📱 Telegram Alert Dispatcher:** Dispatches institutional trade alerts directly to mobile devices.
- **📄 Complete Non-Technical Trader's Manual:** Multi-page PDF guide (`Zia_Quant_User_Guide.pdf`) for plug-and-play operation.

---

## 📐 Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
                      │        ZIA QUANT REAL-TIME WEB UI            │
                      │   Dashboard / Scanner / Lab / Paper / Health │
                      └──────────────────────┬───────────────────────┘
                                             │ WebSockets (SocketIO)
                      ┌──────────────────────▼───────────────────────┐
                      │         FLASK API & SCHEDULER ENGINE         │
                      └──────┬───────────────────────┬───────────────┘
                             │                       │
              ┌──────────────▼──────────┐     ┌──────▼──────────────┐
              │ 6 QUANTITATIVE ENGINES  │     │ 3-TIER CONFIDENCE & │
              │ • Smart Money Liquidity │     │   PAYOUT GATEKEEPER │
              │ • Institutional Zones   │     │ • Evidence Score    │
              │ • Market Structure      │     │ • Break-Even Math   │
              │ • Technical Indicators  │     │ • Risk Guardrails   │
              │ • Candle Anatomy        │     └──────┬──────────────┘
              │ • Mean Reversion / MTF  │            │
              └──────────────┬──────────┘            │
                             │                       ▼
                             │            ┌─────────────────────────┐
                             │            │  OUTPUT DISPATCHERS     │
                             │            │  • Web Dashboard        │
                             │            │  • Telegram Bot Alerts  │
                             │            │  • Desktop / Terminal   │
                             ▼            └─────────────────────────┘
              ┌─────────────────────────┐
              │  MARKET DATA PROVIDER   │
              │  10 Live Global Feeds   │
              └─────────────────────────┘
```

---

## 📊 Backtest Performance Benchmark

*Simulated across 7,106 historical 1-minute bars with 3s execution delay and 1-pip broker spread:*

| Metric | Result | Benchmark | Status |
|---|:---:|:---:|:---:|
| **Win Rate** | **58.33%** | 54.05% (Break-even at 85% payout) | **+4.28% Edge** |
| **Expected Value ($EV$)** | **+$0.0792 / trade** | > $0.00 | **Positive Expectancy** |
| **Profit Factor** | **1.19** | > 1.00 | **Profitable** |
| **Monte Carlo Ruin Risk (3,000 runs)** | **0.0%** | < 5.0% | **PASSED** |

---

## ⚡ Quick Start (1-Click)

### 1. Installation
Clone the repository:
```bash
git clone https://github.com/masabjatoi/zia-quant-trading-platform.git
cd zia-quant-trading-platform
```

Double-click **`setup.bat`** *(or run manually)*:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Launch
Double-click **`start.bat`** *(or run manually)*:
```bash
python run.py
```
Open **`http://127.0.0.1:5000`** in your browser!

---

## 🛠️ Technology Stack

- **Backend:** Python 3.10+, Flask, Flask-SocketIO, SQLAlchemy, SQLite
- **Quantitative & ML:** NumPy, Pandas, Scikit-Learn, TA-Lib / TA
- **Market Data:** Yahoo Finance real-time stream + local caching
- **Frontend:** HTML5, Vanilla CSS (Dark Glassmorphism UI), Vanilla JavaScript, SocketIO Client
- **Reporting:** ReportLab (Automated PDF Generator)

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
