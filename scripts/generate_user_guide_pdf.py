"""
Definitive Master Trader's Manual & Operational PDF Guide for Zia
================================================================
Comprehensive, multi-page handbook covering every crucial system detail,
HUD element, all 5 tabs, strategy engines, Quotex execution rules, risk management,
trading psychology, market sessions, and Telegram alert setup.
"""

from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether,
    PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PDF = PROJECT_ROOT / "Zia_Quant_User_Guide.pdf"
OUTPUT_PDF_ROOT = PROJECT_ROOT.parent / "Zia_Quant_User_Guide.pdf"


def generate_pdf():
    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    # Premium Color Palette
    primary_color = colors.HexColor("#0B1B3D")
    accent_blue = colors.HexColor("#0052CC")
    accent_green = colors.HexColor("#00875A")
    accent_red = colors.HexColor("#DE350B")
    gold_color = colors.HexColor("#B78103")
    dark_gray = colors.HexColor("#172B4D")
    body_gray = colors.HexColor("#344563")
    light_bg = colors.HexColor("#F4F5F7")
    purple_bg = colors.HexColor("#EAE6FF")
    warning_bg = colors.HexColor("#FFF0B3")

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=primary_color,
        alignment=TA_CENTER
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=gold_color,
        alignment=TA_CENTER
    )

    h1_style = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11.5,
        leading=15.5,
        textColor=primary_color,
        spaceBefore=9,
        spaceAfter=3
    )

    h2_style = ParagraphStyle(
        'Heading2_Custom',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9.5,
        leading=13,
        textColor=accent_blue,
        spaceBefore=6,
        spaceAfter=2
    )

    body_style = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=body_gray,
        alignment=TA_LEFT,
        spaceAfter=3
    )

    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=body_gray,
        leftIndent=10,
        spaceAfter=2
    )

    callout_style = ParagraphStyle(
        'Callout_Text',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11.5,
        textColor=dark_gray
    )

    elements = []

    # ==================== PAGE 1: SYSTEM OVERVIEW, LAUNCH & HUD ====================
    elements.append(Paragraph("ZIA QUANT — MASTER TRADER'S HANDBOOK", title_style))
    elements.append(Paragraph("The Complete Operational, Strategic & Risk Management Manual for Zia (Quotex Binary Options)", subtitle_style))
    elements.append(Spacer(1, 4))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=primary_color, spaceBefore=2, spaceAfter=6))

    welcome_text = (
        "<b>Welcome, Zia!</b> This manual is your complete operating guide to Zia Quant. Designed specifically for "
        "binary options trading on Quotex, this system eliminates guesswork by fusing <b>6 independent quantitative engines</b> "
        "across 10 global financial feeds. It monitors market structure, institutional liquidity, support/resistance zones, and "
        "candle dynamics to give you high-conviction <b>CALL (UP)</b> and <b>PUT (DOWN)</b> signals with exact expiry times."
    )
    elements.append(Paragraph(welcome_text, body_style))
    elements.append(Spacer(1, 3))

    # SECTION 1: 1-Click Launch
    elements.append(Paragraph("1. How to Launch and Run the System (1-Click)", h1_style))
    elements.append(Paragraph("• <b>First time setup:</b> Double-click <b><code>setup.bat</code></b>. It creates the clean <code>.venv</code> environment and installs all packages in under 1 minute.", bullet_style))
    elements.append(Paragraph("• <b>Everyday trading:</b> Double-click <b><code>start.bat</code></b>. It starts the platform and automatically opens your browser to <b><code>http://127.0.0.1:5000</code></b>.", bullet_style))
    elements.append(Paragraph("• <b>Automatic data streaming:</b> You never have to download or refresh data. The background scheduler pulls live 1-minute candles automatically every 60 seconds.", bullet_style))
    elements.append(Spacer(1, 4))

    # SECTION 2: TOP HUD BAR
    elements.append(Paragraph("2. Top Status Bar (The Trader's HUD)", h1_style))
    elements.append(Paragraph("Always glance at these 4 key indicators at the top of your dashboard:", body_style))

    hud_data = [
        [
            Paragraph("<b>TOP BAR ELEMENT</b>", ParagraphStyle('H1', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph("<b>WHAT IT SHOWS</b>", ParagraphStyle('H2', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph("<b>HOW TO USE IT IN REAL TRADING</b>", ParagraphStyle('H3', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white))
        ],
        [
            Paragraph("<b>🕒 UTC Clock</b>", h2_style),
            Paragraph("Current Coordinated Universal Time (e.g. <code>14:30:00 UTC</code>).", body_style),
            Paragraph("Quotex runs on UTC time. Use this to trade peak volume sessions (London 07:00–16:00 UTC & New York 12:00–21:00 UTC).", body_style)
        ],
        [
            Paragraph("<b>⏳ Next Scan Countdown</b>", h2_style),
            Paragraph("Counts down from <b>60s to 0s</b> in real-time.", body_style),
            Paragraph("<b>Crucial for entry timing!</b> When timer hits <code>0s</code>, a new 1-minute candle opens. Enter trades right at the candle open for the sharpest price.", body_style)
        ],
        [
            Paragraph("<b>🟢 Live Feed Pulse</b>", h2_style),
            Paragraph("Glowing green dot with <code>LIVE FEED</code> tag.", body_style),
            Paragraph("Confirms your dashboard is actively receiving live data updates over real-time WebSockets.", body_style)
        ],
        [
            Paragraph("<b>⚡ Instant Scan Button</b>", h2_style),
            Paragraph("Green button at top-right of cards.", body_style),
            Paragraph("Forces an immediate scan across all 10 assets on-demand without waiting for the 60-second clock.", body_style)
        ]
    ]

    hud_table = Table(hud_data, colWidths=[110, 160, 270])
    hud_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#DFE1E6")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_bg]),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
    ]))
    elements.append(hud_table)
    elements.append(Spacer(1, 4))

    # SECTION 3: READING SCANNER CARDS
    elements.append(Paragraph("3. Tab 1: Live Scanner (Opportunity Heatmap)", h1_style))
    elements.append(Paragraph("The main screen monitors 10 assets. Here is what every part of an asset card indicates:", body_style))

    card_data = [
        [
            Paragraph("<b>CARD ELEMENT</b>", ParagraphStyle('C1', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph("<b>EXAMPLE VALUE</b>", ParagraphStyle('C2', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph("<b>TRADER'S INSTRUCTION ON QUOTEX</b>", ParagraphStyle('C3', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white))
        ],
        [
            Paragraph("<b>Asset & Payout</b>", h2_style),
            Paragraph("<code>EUR/USD (Payout 85%)</code>", body_style),
            Paragraph("Shows pair and broker payout. <b>Only trade pairs with payout &ge; 80%.</b> (85% payout requires a 54.05% win rate to break even).", body_style)
        ],
        [
            Paragraph("<b>Signal Badge</b>", h2_style),
            Paragraph("🟢 <code>CALL ▲</code> (Green)<br/>🔴 <code>PUT ▼</code> (Red)<br/>⚪ <code>NO_TRADE —</code> (Grey)", body_style),
            Paragraph("<b>GREEN:</b> Open Quotex, select pair, click UP/CALL.<br/><b>RED:</b> Open Quotex, select pair, click DOWN/PUT.<br/><b>GREY:</b> No edge. Protect capital. Sit on hands.", body_style)
        ],
        [
            Paragraph("<b>Price Box</b>", h2_style),
            Paragraph("<code>1.08450</code>", body_style),
            Paragraph("Live spot price at the moment the signal was calculated.", body_style)
        ],
        [
            Paragraph("<b>Evidence Score</b>", h2_style),
            Paragraph("<code>78 / 100</code> (Green bar)", body_style),
            Paragraph("Mathematical confidence from all 6 engines combined. <b>Only execute trades when score is &ge; 70.</b>", body_style)
        ],
        [
            Paragraph("<b>Recommended Expiry</b>", h2_style),
            Paragraph("<code>Expiry: 3m</code> or <code>5m</code>", body_style),
            Paragraph("The exact duration to set on your Quotex timer (e.g. set timer to 3 minutes or 5 minutes).", body_style)
        ],
        [
            Paragraph("<b>Market Regime Tag</b>", h2_style),
            Paragraph("<code>BULLISH (LONDON)</code>", body_style),
            Paragraph("Tells you the active market trend direction and the active global session.", body_style)
        ],
        [
            Paragraph("<b>Evidence Modal</b>", h2_style),
            Paragraph("<i>Click anywhere on card</i>", body_style),
            Paragraph("Opens the <b>Signal Inspector Modal</b> listing the exact reasons why the trade fired (e.g. Liquidity Sweep + Pin Bar).", body_style)
        ]
    ]

    card_table = Table(card_data, colWidths=[110, 140, 290])
    card_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#DFE1E6")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_bg]),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
    ]))
    elements.append(card_table)

    elements.append(PageBreak())

    # ==================== PAGE 2: OTHER 4 TABS & 6 ENGINES ====================
    # SECTION 4: THE OTHER 4 TABS
    elements.append(Paragraph("4. Breakdown of the Other 4 Dashboard Tabs", h1_style))

    tabs_data = [
        [
            Paragraph("<b>TAB NAME</b>", ParagraphStyle('T1', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph("<b>CORE PURPOSE</b>", ParagraphStyle('T2', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph("<b>HOW ZIA USES THIS TAB</b>", ParagraphStyle('T3', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white))
        ],
        [
            Paragraph("<b>🧪 Backtest Lab</b>", h2_style),
            Paragraph("Strategy Simulator on Historical 1-Min Data.", body_style),
            Paragraph("Select an asset (e.g. <code>EUR/USD</code>), period (<code>5 Days</code>), execution delay (<code>3s</code>), and click <b>Run Simulation</b>. Audits Win Rate, Expected Value ($EV$), and Max Losing Streak before trading.", body_style)
        ],
        [
            Paragraph("<b>📝 Paper Trading</b>", h2_style),
            Paragraph("Live Forward Testing Journal ($10 Simulated Trades).", body_style),
            Paragraph("Whenever a high-conviction signal (&ge; 70) appears, the bot automatically opens a simulated trade, waits for expiry, calculates WIN/LOSS and PnL, and logs it here with $0 real risk.", body_style)
        ],
        [
            Paragraph("<b>📊 Performance Analytics</b>", h2_style),
            Paragraph("Aggregated Performance Slices & Profit Factor.", body_style),
            Paragraph("Shows Zia's overall forward win rate %, total net profit ($), profit factor, and asset-by-asset performance breakdown to see which pairs are performing best.", body_style)
        ],
        [
            Paragraph("<b>🛡️ System Diagnostics</b>", h2_style),
            Paragraph("Real-Time Technical Health & Latency Monitor.", body_style),
            Paragraph("Confirms database connectivity, live price stream status, calculation response time (<50ms), and total error count (0).", body_style)
        ]
    ]

    tabs_table = Table(tabs_data, colWidths=[120, 160, 260])
    tabs_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#DFE1E6")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_bg]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(tabs_table)
    elements.append(Spacer(1, 6))

    # SECTION 5: 6 QUANTITATIVE STRATEGY ENGINES
    elements.append(Paragraph("5. The 6 Real Market Engines Working Under the Hood", h1_style))
    elements.append(Paragraph("Zia Quant requires confluence from these 6 institutional engines before generating a signal:", body_style))

    engines_data = [
        [
            Paragraph("<b>ENGINE NAME</b>", ParagraphStyle('E1', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph("<b>WHAT IT DETECTS IN THE REAL MARKET</b>", ParagraphStyle('E2', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white))
        ],
        [
            Paragraph("<b>1. Smart Money Liquidity Engine</b>", h2_style),
            Paragraph("Identifies Equal Highs/Lows where retail traders cluster stop-losses, and catches <b>Liquidity Sweeps</b> (fake breakouts that sharply reverse back into fair value).", body_style)
        ],
        [
            Paragraph("<b>2. Institutional Zones Engine</b>", h2_style),
            Paragraph("Maps high-probability <b>Support & Resistance zones</b>, institutional <b>Order Blocks (OB)</b>, and <b>Fair Value Gaps (FVG)</b> where institutional buy/sell orders react.", body_style)
        ],
        [
            Paragraph("<b>3. Market Structure Engine</b>", h2_style),
            Paragraph("Tracks pure price swings to classify <b>Higher Highs (HH)</b>, <b>Higher Lows (HL)</b>, <b>Break of Structure (BOS)</b>, and <b>Change of Character (CHoCH)</b> to ensure you trade with the trend.", body_style)
        ],
        [
            Paragraph("<b>4. Technical Indicator Engine</b>", h2_style),
            Paragraph("Vectorized calculation of <b>EMA 9/21/50/200 alignment</b>, <b>RSI 14 momentum zones</b>, <b>MACD histogram expansion</b>, <b>Bollinger Bands</b>, and <b>ADX strength (>24)</b>.", body_style)
        ],
        [
            Paragraph("<b>5. Quantitative Candle Anatomy</b>", h2_style),
            Paragraph("Measures real-time body-to-wick ratios and identifies 14 classic patterns including <b>Pin Bars</b>, <b>Engulfing Candles</b>, and <b>Long Rejection Tails</b>.", body_style)
        ],
        [
            Paragraph("<b>6. Economic Payout Gatekeeper</b>", h2_style),
            Paragraph("Calculates break-even math: <code>P = 1 / (1 + Payout)</code>. At 85% payout, break-even is 54.05%. The bot requires at least 59.05% win probability before permitting a trade.", body_style)
        ]
    ]

    engines_table = Table(engines_data, colWidths=[150, 390])
    engines_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#DFE1E6")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_bg]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(engines_table)

    elements.append(PageBreak())

    # ==================== PAGE 3: RISK RULES, TIMING & EXECUTION ====================
    # SECTION 6: RISK RULES & ANTI-MARTINGALE
    elements.append(Paragraph("6. Strict Risk Management Rules (Protecting Capital)", h1_style))

    risk_data = [
        [Paragraph("<b>Rule 1: Fixed 1% to 2% Stake (NEVER Martingale / Never Double Down)</b><br/>"
                   "If your account balance is $100, trade a fixed <b>$1.00 to $2.00 per signal</b>. If you win, take the profit. If you lose, <b>stay at $1.00</b>. "
                   "Doubling down after a loss (Martingale) is a mathematical guarantee of wiping an account. Real quantitative trading wins through statistical edge (+EV), not reckless doubling.", callout_style)],
        [Paragraph("<b>Rule 2: Daily Stop-Loss & Target Limits</b><br/>"
                   "• <b>Daily Target:</b> Stop trading for the day after winning <b>3 to 5 trades</b>.<br/>"
                   "• <b>Daily Stop-Loss:</b> Stop trading immediately if you encounter <b>3 consecutive losses</b>. The bot's built-in circuit breaker will automatically pause signals on that pair to protect you.", callout_style)],
        [Paragraph("<b>Rule 3: Only Trade When Broker Payout is &ge; 80%</b><br/>"
                   "Quotex payouts fluctuate. If a pair drops below 80% payout (e.g. 60% or 70%), the mathematical break-even requirement spikes to 58.8%+. Skip low payout assets and stick to 80%–92% payouts.", callout_style)]
    ]
    risk_table = Table(risk_data, colWidths=[540])
    risk_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), purple_bg),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#8777D9")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(risk_table)
    elements.append(Spacer(1, 6))

    # SECTION 7: TRADING SESSIONS & WEEKEND OTC WARNING
    elements.append(Paragraph("7. Market Sessions & The Truth About Weekend OTC", h1_style))
    elements.append(Paragraph("• <b>Best Trading Hours (Monday – Friday):</b> Highest win rates occur during <b>London Session</b> (07:00–16:00 UTC) and <b>New York Session</b> (12:00–21:00 UTC) when genuine institutional volume is active.", bullet_style))
    elements.append(Paragraph("• <b>Weekend Closures:</b> Standard Forex pairs (EUR/USD, GBP/USD, USD/JPY) and Commodities (Gold/Silver) close every Friday at 21:00 UTC and reopen Sunday at 21:00 UTC.", bullet_style))
    elements.append(Paragraph("• <b>24/7 Weekend Crypto:</b> Real <b>Bitcoin (BTC/USD)</b> and <b>Ethereum (ETH/USD)</b> trade 24/7/365 with live global market liquidity.", bullet_style))
    elements.append(Paragraph("• <b>WARNING on Quotex Weekend OTC Pairs:</b> Avoid trading simulated 'OTC' pairs on weekends. OTC feeds are generated by the broker's servers rather than the real interbank market. Stick to real Forex (Mon–Fri) and real Crypto.", bullet_style))
    elements.append(Spacer(1, 6))

    # SECTION 8: STEP-BY-STEP DAILY ROUTINE
    elements.append(Paragraph("8. Zia's Step-by-Step Daily Trading Routine", h1_style))

    routine_data = [
        [Paragraph("<b>STEP</b>", ParagraphStyle('R1', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
         Paragraph("<b>WHAT TO DO</b>", ParagraphStyle('R2', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
         Paragraph("<b>EXACT EXECUTION DETAIL</b>", ParagraphStyle('R3', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white))],
        [
            Paragraph("<b>Step 1</b>", h2_style),
            Paragraph("<b>Launch Platform</b>", body_style),
            Paragraph("Double-click <code>start.bat</code>. Browser opens to <code>http://127.0.0.1:5000</code>.", body_style)
        ],
        [
            Paragraph("<b>Step 2</b>", h2_style),
            Paragraph("<b>Watch Countdown</b>", body_style),
            Paragraph("Look at <code>⏳ Next Scan</code> countdown at the top. Wait for the timer to tick down to <code>0s</code>.", body_style)
        ],
        [
            Paragraph("<b>Step 3</b>", h2_style),
            Paragraph("<b>Spot Signal</b>", body_style),
            Paragraph("Check for cards with 🟢 <b>CALL ▲ (Green)</b> or 🔴 <b>PUT ▼ (Red)</b> and Evidence Score &ge; 70.", body_style)
        ],
        [
            Paragraph("<b>Step 4</b>", h2_style),
            Paragraph("<b>Execute on Quotex</b>", body_style),
            Paragraph("Open Quotex tab $\rightarrow$ Select asset $\rightarrow$ Set recommended expiry timer (3m or 5m) $\rightarrow$ Click UP (Green) or DOWN (Red).", body_style)
        ],
        [
            Paragraph("<b>Step 5</b>", h2_style),
            Paragraph("<b>Audit in Paper Log</b>", body_style),
            Paragraph("Check the <b>📝 Paper Trading</b> tab after 3–5 minutes to review the automatically settled outcome.", body_style)
        ]
    ]

    routine_table = Table(routine_data, colWidths=[45, 120, 375])
    routine_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#DFE1E6")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_bg]),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
    ]))
    elements.append(routine_table)
    elements.append(Spacer(1, 6))

    # SECTION 9: TELEGRAM ALERTS
    elements.append(Paragraph("9. How to Enable Free Telegram Mobile Alerts (Optional)", h1_style))
    elements.append(Paragraph("1. Open Telegram $\rightarrow$ Search <b><code>@BotFather</code></b> $\rightarrow$ send <code>/newbot</code> $\rightarrow$ Copy the <b>Bot Token</b>.", bullet_style))
    elements.append(Paragraph("2. Search <b><code>@userinfobot</code></b> on Telegram $\rightarrow$ Copy your <b>Chat ID</b> number.", bullet_style))
    elements.append(Paragraph("3. Paste them into <b><code>configs/default.yaml</code></b> under <code>alerts:</code>. Every strong signal will ping Zia's phone instantly!", bullet_style))

    elements.append(Spacer(1, 4))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#DFE1E6"), spaceBefore=2, spaceAfter=4))
    elements.append(Paragraph("<i>Zia Quant Pro Edition — Built with institutional quantitative engineering. Trade with discipline.</i>", ParagraphStyle('Footer', fontName='Helvetica-Oblique', fontSize=7.5, textColor=colors.gray, alignment=TA_CENTER)))

    doc.build(elements)

    try:
        import shutil
        shutil.copy(OUTPUT_PDF, OUTPUT_PDF_ROOT)
    except Exception:
        pass

    print(f"[SUCCESS] Definitive Master Manual PDF generated at: {OUTPUT_PDF}")


if __name__ == "__main__":
    generate_pdf()
