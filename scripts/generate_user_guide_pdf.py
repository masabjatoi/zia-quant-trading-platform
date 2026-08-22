"""
Complete UI & Trader's Master Manual PDF Generator for Zia
==========================================================
Detailed breakdown of every UI element, top HUD bar, countdown timer,
all 5 dashboard tabs, and exact Quotex trade execution mechanics.
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

    # Color Palette
    primary_color = colors.HexColor("#0B1B3D")
    accent_blue = colors.HexColor("#0052CC")
    accent_green = colors.HexColor("#00875A")
    accent_red = colors.HexColor("#DE350B")
    gold_color = colors.HexColor("#B78103")
    dark_gray = colors.HexColor("#172B4D")
    body_gray = colors.HexColor("#344563")
    light_bg = colors.HexColor("#F4F5F7")
    purple_bg = colors.HexColor("#EAE6FF")

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
        fontSize=10.5,
        leading=14,
        textColor=gold_color,
        alignment=TA_CENTER
    )

    h1_style = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=primary_color,
        spaceBefore=10,
        spaceAfter=4
    )

    h2_style = ParagraphStyle(
        'Heading2_Custom',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13.5,
        textColor=accent_blue,
        spaceBefore=7,
        spaceAfter=2
    )

    body_style = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=body_gray,
        alignment=TA_LEFT,
        spaceAfter=4
    )

    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=body_gray,
        leftIndent=10,
        spaceAfter=2
    )

    callout_style = ParagraphStyle(
        'Callout_Text',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=dark_gray
    )

    elements = []

    # ==================== PAGE 1 ====================
    elements.append(Paragraph("ZIA QUANT — TRADER'S UI & OPERATIONAL MANUAL", title_style))
    elements.append(Paragraph("A Complete Screen-by-Screen Guide for Zia to Trade with Precision on Quotex", subtitle_style))
    elements.append(Spacer(1, 6))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=primary_color, spaceBefore=2, spaceAfter=8))

    elements.append(Paragraph("<b>Welcome, Zia!</b> This guide explains every single button, clock, number, and tab on your dashboard so you know exactly how to use them to make consistent, disciplined trades.", body_style))
    elements.append(Spacer(1, 4))

    # SECTION 1: TOP HUD BAR
    elements.append(Paragraph("1. Top Status Bar (The Trader's HUD)", h1_style))
    elements.append(Paragraph("Across the top of your screen, there are 4 critical indicators you should always glance at:", body_style))

    hud_data = [
        [
            Paragraph("<b>TOP BAR ELEMENT</b>", ParagraphStyle('H1', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph("<b>WHAT IT SHOWS</b>", ParagraphStyle('H2', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph("<b>HOW TO USE IT IN TRADING</b>", ParagraphStyle('H3', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white))
        ],
        [
            Paragraph("<b>🕒 UTC Clock</b>", h2_style),
            Paragraph("Current Coordinated Universal Time (e.g. <code>14:30:00 UTC</code>).", body_style),
            Paragraph("Use this to know which global trading session is active (London, New York, Tokyo).", body_style)
        ],
        [
            Paragraph("<b>⏳ Next Scan Countdown</b>", h2_style),
            Paragraph("Counts down from <b>60s to 0s</b> in real-time.", body_style),
            Paragraph("<b>Crucial for entry timing!</b> When the timer hits <code>0s</code>, a new 1-minute candle opens. Enter your Quotex trade right at the start of the new candle for the best price.", body_style)
        ],
        [
            Paragraph("<b>🟢 Live Feed Pulse</b>", h2_style),
            Paragraph("Glowing green dot with <code>LIVE FEED</code> tag.", body_style),
            Paragraph("Confirms your dashboard is actively connected to the real-time market data stream via WebSockets.", body_style)
        ],
        [
            Paragraph("<b>⚡ Instant Scan Button</b>", h2_style),
            Paragraph("Green button at the top right of the cards.", body_style),
            Paragraph("Forces an immediate scan across all 10 assets without waiting for the 60-second timer.", body_style)
        ]
    ]

    hud_table = Table(hud_data, colWidths=[120, 160, 260])
    hud_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#DFE1E6")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_bg]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(hud_table)
    elements.append(Spacer(1, 8))

    # SECTION 2: TAB 1 LIVE SCANNER
    elements.append(Paragraph("2. Tab 1: Live Scanner (Opportunity Heatmap)", h1_style))
    elements.append(Paragraph("This is your main trading cockpit monitoring 10 assets. Here is what every part of an asset card means:", body_style))

    card_data = [
        [
            Paragraph("<b>CARD ELEMENT</b>", ParagraphStyle('C1', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph("<b>EXAMPLE VALUE</b>", ParagraphStyle('C2', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph("<b>TRADER'S INSTRUCTION</b>", ParagraphStyle('C3', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white))
        ],
        [
            Paragraph("<b>Asset Title & Payout</b>", h2_style),
            Paragraph("<code>EUR/USD — Payout 85%</code>", body_style),
            Paragraph("Shows the currency pair and broker payout. 85% payout requires a 54.05% win rate to break even.", body_style)
        ],
        [
            Paragraph("<b>Signal Badge</b>", h2_style),
            Paragraph("<code>CALL ▲</code> (Green)<br/><code>PUT ▼</code> (Red)<br/><code>NO_TRADE —</code> (Grey)", body_style),
            Paragraph("<b>GREEN:</b> Open Quotex, click UP/CALL.<br/><b>RED:</b> Open Quotex, click DOWN/PUT.<br/><b>GREY:</b> Sit on hands. Protect capital.", body_style)
        ],
        [
            Paragraph("<b>Price Box</b>", h2_style),
            Paragraph("<code>1.08450</code>", body_style),
            Paragraph("The current market price at the moment the signal formed.", body_style)
        ],
        [
            Paragraph("<b>Evidence Score Bar</b>", h2_style),
            Paragraph("<code>78 / 100</code>", body_style),
            Paragraph("Mathematical confidence. Scores above <b>70</b> represent high-probability setups.", body_style)
        ],
        [
            Paragraph("<b>Recommended Expiry</b>", h2_style),
            Paragraph("<code>Expiry: 3m</code> or <code>5m</code>", body_style),
            Paragraph("The exact duration to set on your Quotex timer before clicking trade.", body_style)
        ],
        [
            Paragraph("<b>Market Regime Tag</b>", h2_style),
            Paragraph("<code>BULLISH (LONDON)</code>", body_style),
            Paragraph("Tells you the active trend direction and the current trading session.", body_style)
        ],
        [
            Paragraph("<b>Card Click (Inspector)</b>", h2_style),
            Paragraph("<i>Click anywhere on card</i>", body_style),
            Paragraph("Opens the <b>Signal Evidence Modal</b> showing the exact institutional reasons why the signal fired.", body_style)
        ]
    ]

    card_table = Table(card_data, colWidths=[120, 140, 280])
    card_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#DFE1E6")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_bg]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(card_table)

    elements.append(PageBreak())

    # ==================== PAGE 2 ====================
    # SECTION 3: TAB 2 BACKTEST LAB
    elements.append(Paragraph("3. Tab 2: Backtest Lab (Testing Before Trading)", h1_style))
    elements.append(Paragraph("The Backtest Lab lets Zia simulate and audit strategies across thousands of historical candles before risking a single dollar:", body_style))
    elements.append(Paragraph("• <b>Asset & Window Selectors:</b> Choose the pair (e.g. <code>EUR/USD</code>) and period (<code>Past 5 Days</code> or <code>1 Month</code>).", bullet_style))
    elements.append(Paragraph("• <b>Execution Lag Modeling:</b> Models realistic <b>3-second delay</b> and <b>1-pip spread</b> so results mirror real execution.", bullet_style))
    elements.append(Paragraph("• <b>Metrics Audit Cards:</b> Displays <b>Win Rate</b> (vs break-even), <b>Expected Value / Trade (+EV)</b>, <b>Total P&L</b>, and <b>Max Losing Streak</b>.", bullet_style))
    elements.append(Spacer(1, 6))

    # SECTION 4: TAB 3 PAPER TRADING
    elements.append(Paragraph("4. Tab 3: Live Paper Trading Log (Zero-Risk Forward Testing)", h1_style))
    elements.append(Paragraph("The Paper Trading tab acts as Zia's automatic trading journal on live market feeds:", body_style))
    elements.append(Paragraph("• <b>Autopilot Forward Execution:</b> Whenever a signal with Evidence Score &ge; 70 fires, the bot opens a simulated $10 trade.", bullet_style))
    elements.append(Paragraph("• <b>Automatic Expiry Settlement:</b> At the exact end of the expiry (e.g. at T + 3 minutes), the bot checks the closing price, marks <b>WIN</b> (+$8.50) or <b>LOSS</b> (-$10.00), and records it in the database.", bullet_style))
    elements.append(Paragraph("• <b>Live Audit Table:</b> Shows Entry Time, Asset, Direction, Entry Price, Expiry Price, Outcome, and Net PnL.", bullet_style))
    elements.append(Spacer(1, 6))

    # SECTION 5: TAB 4 & 5 ANALYTICS & HEALTH
    elements.append(Paragraph("5. Tabs 4 & 5: Performance Analytics & System Diagnostics", h1_style))
    elements.append(Paragraph("• <b>Tab 4 (Performance Analytics):</b> Aggregates Zia's overall forward win rate, total profit/loss, profit factor, and breakdown by asset.", bullet_style))
    elements.append(Paragraph("• <b>Tab 5 (System Diagnostics):</b> Verifies that the SQLite database is healthy, market data feed is active, and shows uptime and latency.", bullet_style))
    elements.append(Spacer(1, 8))

    # SECTION 6: EXACT STEP-BY-STEP TRADING ROUTINE
    elements.append(Paragraph("6. Zia's Step-by-Step Daily Trading Routine", h1_style))

    routine_data = [
        [Paragraph("<b>STEP</b>", ParagraphStyle('R1', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
         Paragraph("<b>ACTION</b>", ParagraphStyle('R2', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
         Paragraph("<b>DETAIL</b>", ParagraphStyle('R3', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white))],
        [
            Paragraph("<b>Step 1</b>", h2_style),
            Paragraph("<b>Launch Platform</b>", body_style),
            Paragraph("Double-click <code>start.bat</code>. Browser opens to <code>http://127.0.0.1:5000</code>.", body_style)
        ],
        [
            Paragraph("<b>Step 2</b>", h2_style),
            Paragraph("<b>Watch Countdown</b>", body_style),
            Paragraph("Look at <code>⏳ Next Scan</code> countdown at top. When a new minute begins, scanner refreshes.", body_style)
        ],
        [
            Paragraph("<b>Step 3</b>", h2_style),
            Paragraph("<b>Spot Tradeable Setup</b>", body_style),
            Paragraph("Look for a card with 🟢 <b>CALL ▲</b> or 🔴 <b>PUT ▼</b> and Evidence Score &ge; 70.", body_style)
        ],
        [
            Paragraph("<b>Step 4</b>", h2_style),
            Paragraph("<b>Execute on Quotex</b>", body_style),
            Paragraph("Open Quotex tab $\rightarrow$ Select asset $\rightarrow$ Set recommended expiry (3m or 5m) $\rightarrow$ Click UP/DOWN.", body_style)
        ],
        [
            Paragraph("<b>Step 5</b>", h2_style),
            Paragraph("<b>Fixed Stake (Anti-Martingale)</b>", body_style),
            Paragraph("Trade a fixed 1% to 2% ($1–$2 per $100 balance). Never double down after a loss.", body_style)
        ]
    ]

    routine_table = Table(routine_data, colWidths=[50, 130, 360])
    routine_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#DFE1E6")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_bg]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(routine_table)
    elements.append(Spacer(1, 6))

    # FOOTER
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#DFE1E6"), spaceBefore=2, spaceAfter=4))
    elements.append(Paragraph("<i>Zia Quant Pro Edition — Built for discipline, statistical edge, and capital protection. Trade responsibly.</i>", ParagraphStyle('Footer', fontName='Helvetica-Oblique', fontSize=7.5, textColor=colors.gray, alignment=TA_CENTER)))

    doc.build(elements)

    try:
        import shutil
        shutil.copy(OUTPUT_PDF, OUTPUT_PDF_ROOT)
    except Exception:
        pass

    print(f"[SUCCESS] Complete UI Manual PDF generated at: {OUTPUT_PDF}")


if __name__ == "__main__":
    generate_pdf()
