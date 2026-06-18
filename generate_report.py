"""
InelidaMarketScanner — Generateur de rapport PDF horodate.
Produit un rapport complet avec tous les scans (sweeps, asian, levels, setups)
pour permettre une verification ulterieure des trades gagnants/perdants.
"""

import os
import sys
import time
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

from fpdf import FPDF

# --- Chemins ----------------------------------------------------------------
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PDF = os.path.join(PROJECT_DIR, "inelida_report.pdf")

# --- Fuseaux horaires -------------------------------------------------------
UTC = timezone.utc
PARIS = timezone(timedelta(hours=2))  # CEST (ete) -- ajuster a +1 en hiver

PLATFORM_TZ = datetime.now().astimezone().tzinfo
PLATFORM_NAME = time.tzname[0] if time.tzname else "Local"

# --- Timestamps -------------------------------------------------------------
now_utc = datetime.now(UTC)
now_paris = now_utc.astimezone(PARIS)
now_platform = datetime.now()

TIMESTAMP_UTC = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
TIMESTAMP_PARIS = now_paris.strftime("%Y-%m-%d %H:%M:%S CEST")
TIMESTAMP_PLATFORM = now_platform.strftime(f"%Y-%m-%d %H:%M:%S {PLATFORM_NAME}")
SESSION_DATE = now_utc.strftime("%Y-%m-%d")


# ===========================================================================
# DONNEES DES SCANS (extraites du run du 18/06/2026)
# ===========================================================================

ACCOUNT_INFO = {
    "login": 541320891,
    "server": "FTMO-Server4",
    "balance": 10035.55,
    "currency": "EUR",
    "leverage": "1:30",
    "trade_allowed": False,
    "terminal_build": 5833,
    "broker": "FTMO Global Markets Ltd.",
}

SWEEPS_DATA = [
    {"symbol":"SAN","label":"BSL","level":11.91,"current":11.91,"dist_pct":0.0000,"direction":"reversal_down","swept_at":"2026-06-18 12:30"},
    {"symbol":"SAN","label":"BSL","level":11.91,"current":11.91,"dist_pct":0.0000,"direction":"reversal_down","swept_at":"2026-06-18 14:15"},
    {"symbol":"EURGBP","label":"BSL","level":0.86733,"current":0.86734,"dist_pct":0.0012,"direction":"reversal_down","swept_at":"2026-06-18 10:00"},
    {"symbol":"EURGBP","label":"BSL","level":0.86737,"current":0.86734,"dist_pct":0.0035,"direction":"reversal_down","swept_at":"2026-06-18 10:30"},
    {"symbol":"USDCNH","label":"BSL","level":6.77668,"current":6.77704,"dist_pct":0.0053,"direction":"reversal_down","swept_at":"2026-06-18 09:00"},
    {"symbol":"USDHKD","label":"BSL","level":7.83746,"current":7.83704,"dist_pct":0.0054,"direction":"reversal_down","swept_at":"2026-06-18 08:15"},
    {"symbol":"USDHKD","label":"BSL","level":7.83761,"current":7.83704,"dist_pct":0.0073,"direction":"reversal_down","swept_at":"2026-06-18 07:45"},
    {"symbol":"USDCZK","label":"BSL","level":21.1107,"current":21.1128,"dist_pct":0.0099,"direction":"reversal_down","swept_at":"2026-06-18 11:00"},
    {"symbol":"USDCZK","label":"BSL","level":21.1097,"current":21.1128,"dist_pct":0.0147,"direction":"reversal_down","swept_at":"2026-06-18 10:15"},
    {"symbol":"EURGBP","label":"BSL","level":0.86720,"current":0.86734,"dist_pct":0.0161,"direction":"reversal_down","swept_at":"2026-06-18 09:30"},
    {"symbol":"USDHUF","label":"SSL","level":307.410,"current":307.377,"dist_pct":0.0107,"direction":"reversal_up","swept_at":"2026-06-18 13:00"},
    {"symbol":"AUDUSD","label":"SSL","level":0.70109,"current":0.70143,"dist_pct":0.0485,"direction":"reversal_up","swept_at":"2026-06-18 08:00"},
    {"symbol":"GBPUSD","label":"SSL","level":1.33869,"current":1.33828,"dist_pct":0.0306,"direction":"reversal_up","swept_at":"2026-06-18 11:30"},
    {"symbol":"EURUSD","label":"SSL","level":1.14572,"current":1.14584,"dist_pct":0.0105,"direction":"reversal_up","swept_at":"2026-06-18 08:45"},
    {"symbol":"XAUUSD","label":"SSL","level":4330.45,"current":4355.20,"dist_pct":0.5714,"direction":"reversal_up","swept_at":"2026-06-18 07:00"},
    {"symbol":"XAGUSD","label":"SSL","level":33.810,"current":34.125,"dist_pct":0.9317,"direction":"reversal_up","swept_at":"2026-06-18 06:45"},
    {"symbol":"BTCUSD","label":"SSL","level":89200.0,"current":90150.0,"dist_pct":1.0650,"direction":"reversal_up","swept_at":"2026-06-18 05:30"},
    {"symbol":"USDJPY","label":"BSL","level":157.510,"current":157.432,"dist_pct":0.0495,"direction":"reversal_down","swept_at":"2026-06-18 12:00"},
    {"symbol":"NAS100","label":"SSL","level":21340.0,"current":21450.0,"dist_pct":0.5155,"direction":"reversal_up","swept_at":"2026-06-18 09:15"},
    {"symbol":"SPX500","label":"SSL","level":5990.0,"current":6012.0,"dist_pct":0.3673,"direction":"reversal_up","swept_at":"2026-06-18 08:30"},
]

SWEEPS_TOTAL = 215
SWEEPS_BSL = 122
SWEEPS_SSL = 93

ASIAN_RESULTS = [
    {"symbol":"WHEAT.c","action":"SELL","ah":612.43,"al":607.14,"current":602.51,"ah_swept":True,"al_swept":False,"direction":"-> AL","fib":"-> -1.618","fib_swept":"-","trade_status":"Active","sl":612.959,"tp1":598.581,"tp2":595.533,"tp3":590.780,"rr":0.376,"entry":602.51},
    {"symbol":"XCUUSD","action":"-","ah":640.83,"al":635.18,"current":636.74,"ah_swept":True,"al_swept":True,"direction":"<-> Both","fib":"-","fib_swept":"-","trade_status":"Wait breakout","sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,"entry":None},
    {"symbol":"XAUUSD","action":"-","ah":4370.50,"al":4330.45,"current":4355.20,"ah_swept":False,"al_swept":True,"direction":"*","fib":"-","fib_swept":"-","trade_status":"Wait breakout","sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,"entry":None},
    {"symbol":"BTCUSD","action":"-","ah":90800.0,"al":89200.0,"current":90150.0,"ah_swept":False,"al_swept":True,"direction":"*","fib":"-","fib_swept":"-","trade_status":"Wait breakout","sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,"entry":None},
    {"symbol":"XAGUSD","action":"-","ah":34.500,"al":33.810,"current":34.125,"ah_swept":False,"al_swept":True,"direction":"*","fib":"-","fib_swept":"-","trade_status":"Wait breakout","sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,"entry":None},
    {"symbol":"AUS200.cash","action":"-","ah":8984.9,"al":8911.6,"current":8872.21,"ah_swept":False,"al_swept":True,"direction":"-> AH","fib":"-","fib_swept":"-","trade_status":"Wait breakout","sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,"entry":None},
    {"symbol":"AUDUSD","action":"-","ah":0.70415,"al":0.70109,"current":0.70143,"ah_swept":False,"al_swept":True,"direction":"*","fib":"-","fib_swept":"-","trade_status":"Wait breakout","sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,"entry":None},
    {"symbol":"AUDJPY","action":"-","ah":113.068,"al":112.532,"current":113.179,"ah_swept":True,"al_swept":False,"direction":"*","fib":"-","fib_swept":"-","trade_status":"Wait breakout","sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,"entry":None},
    {"symbol":"AUDCAD","action":"-","ah":0.99270,"al":0.98822,"current":0.99142,"ah_swept":True,"al_swept":False,"direction":"-> AL","fib":"-","fib_swept":"-","trade_status":"Wait breakout","sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,"entry":None},
    {"symbol":"AVAUSD","action":"-","ah":6.79,"al":6.61,"current":6.32,"ah_swept":False,"al_swept":True,"direction":"-> AH","fib":"-> -2.0","fib_swept":"v -1.618","trade_status":"Wait breakout","sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,"entry":None},
    {"symbol":"ALGUSD","action":"-","ah":0.1014,"al":0.0950,"current":0.0989,"ah_swept":True,"al_swept":False,"direction":"-> AL","fib":"-","fib_swept":"-","trade_status":"Wait breakout","sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,"entry":None},
    {"symbol":"XLMUSD","action":"-","ah":0.2454,"al":0.2204,"current":0.2388,"ah_swept":True,"al_swept":False,"direction":"-> AL","fib":"-","fib_swept":"-","trade_status":"Wait breakout","sl":None,"tp1":None,"tp2":None,"tp3":None,"rr":None,"entry":None},
]

ASIAN_SCANNED = 167
ASIAN_AH_SWEPT = 6
ASIAN_AL_SWEPT = 12
ASIAN_BOTH_SWEPT = 1
ASIAN_FIB_SWEPT = 1

LEVELS_DATA = [
    {"symbol":"AUS200.cash","type":"Daily","sweep":"H+L","direction":"<-> Both","level_high":8982.00,"level_low":8884.90,"current":8872.21},
    {"symbol":"GOOG","type":"Daily","sweep":"L","direction":"-> AH","level_high":368.09,"level_low":360.07,"current":367.50},
    {"symbol":"TSLA","type":"Daily","sweep":"L","direction":"-> AH","level_high":405.36,"level_low":393.71,"current":400.91},
    {"symbol":"ADAUSD","type":"Weekly","sweep":"H","direction":"-> AL","level_high":0.17560,"level_low":0.15540,"current":0.16310},
    {"symbol":"AUDUSD","type":"Weekly","sweep":"H","direction":"-> AL","level_high":0.70781,"level_low":0.69789,"current":0.70143},
    {"symbol":"AVAUSD","type":"Weekly","sweep":"H+L","direction":"<-> Both","level_high":6.95,"level_low":6.29,"current":6.32},
    {"symbol":"BARUSD","type":"Weekly","sweep":"H+L","direction":"<-> Both","level_high":0.08320,"level_low":0.07683,"current":0.08041},
    {"symbol":"BNBUSD","type":"Weekly","sweep":"H","direction":"-> AL","level_high":613.71,"level_low":571.57,"current":579.92},
    {"symbol":"CHFJPY","type":"Weekly","sweep":"H+L","direction":"<-> Both","level_high":201.494,"level_low":200.313,"current":200.479},
    {"symbol":"CORN.c","type":"Weekly","sweep":"L","direction":"-> AH","level_high":423.36,"level_low":406.65,"current":416.32},
    {"symbol":"EURCZK","type":"Weekly","sweep":"L","direction":"-> AH","level_high":24.2329,"level_low":24.1102,"current":24.1963},
    {"symbol":"EURPLN","type":"Weekly","sweep":"L","direction":"-> AH","level_high":4.26124,"level_low":4.23296,"current":4.25632},
    {"symbol":"EURUSD","type":"Weekly","sweep":"H+L","direction":"<-> Both","level_high":1.15895,"level_low":1.14997,"current":1.14584},
    {"symbol":"EURUSD","type":"Daily","sweep":"L","direction":"-> AH","level_high":1.15000,"level_low":1.14572,"current":1.14584},
    {"symbol":"FDX","type":"Weekly","sweep":"H","direction":"-> AL","level_high":341.52,"level_low":318.01,"current":325.92},
    {"symbol":"FETUSD","type":"Weekly","sweep":"H","direction":"-> AL","level_high":0.21760,"level_low":0.18240,"current":0.19570},
    {"symbol":"GBPJPY","type":"Weekly","sweep":"H+L","direction":"<-> Both","level_high":215.230,"level_low":212.920,"current":213.041},
    {"symbol":"GM","type":"Weekly","sweep":"H+L","direction":"<-> Both","level_high":84.50,"level_low":78.81,"current":79.27},
    {"symbol":"GRTUSD","type":"Weekly","sweep":"H","direction":"-> AL","level_high":0.02053,"level_low":0.01841,"current":0.01932},
    {"symbol":"MCD","type":"Weekly","sweep":"H","direction":"-> AL","level_high":287.53,"level_low":276.12,"current":278.57},
    {"symbol":"META","type":"Weekly","sweep":"H","direction":"-> AL","level_high":597.52,"level_low":556.94,"current":577.15},
    {"symbol":"NZDJPY","type":"Weekly","sweep":"H+L","direction":"<-> Both","level_high":93.618,"level_low":92.539,"current":92.828},
    {"symbol":"SOYBEAN.c","type":"Weekly","sweep":"H+L","direction":"<-> Both","level_high":1125.58,"level_low":1104.58,"current":1120.35},
    {"symbol":"USDCHF","type":"Weekly","sweep":"H+L","direction":"<-> Both","level_high":0.80128,"level_low":0.79369,"current":0.80415},
    {"symbol":"USDCNH","type":"Weekly","sweep":"L","direction":"-> AH","level_high":6.79187,"level_low":6.75886,"current":6.77704},
    {"symbol":"USDHKD","type":"Weekly","sweep":"H+L","direction":"<-> Both","level_high":7.83751,"level_low":7.83280,"current":7.83704},
    {"symbol":"USDHUF","type":"Weekly","sweep":"L","direction":"-> AH","level_high":310.697,"level_low":303.333,"current":307.377},
    {"symbol":"USDMXN","type":"Weekly","sweep":"L","direction":"-> AH","level_high":17.4960,"level_low":17.1737,"current":17.3499},
    {"symbol":"USDSGD","type":"Weekly","sweep":"L","direction":"-> AH","level_high":1.29165,"level_low":1.28192,"current":1.28967},
    {"symbol":"VECUSD","type":"Weekly","sweep":"H","direction":"-> AL","level_high":0.00516,"level_low":0.00461,"current":0.00482},
    {"symbol":"WHEAT.c","type":"Weekly","sweep":"H+L","direction":"<-> Both","level_high":598.58,"level_low":572.93,"current":602.51},
    {"symbol":"WMT","type":"Weekly","sweep":"H+L","direction":"<-> Both","level_high":121.82,"level_low":117.47,"current":117.16},
    {"symbol":"XPTUSD","type":"Weekly","sweep":"H","direction":"-> AL","level_high":1793.67,"level_low":1638.18,"current":1695.07},
]

LEVELS_HAUSSIER = 9
LEVELS_BAISSIER = 10
LEVELS_MIXTE = 13

SETUPS_DATA = [
    {"symbol":"GBPJPY","sweep":"AH+AL","direction":"<-> Both","session":"H:London / L:NY","ah":213.974,"al":213.161,"current":213.068,"rr":1.2,"trade":"SELL","plan":"SL 214.055 -> TP1 211.846","status":"Active","sl":214.055,"tp1":211.846,"entry":213.068},
    {"symbol":"EURCAD","sweep":"AH+AL","direction":"<-> Both","session":"H:London / L:NY","ah":1.62510,"al":1.62093,"current":1.61949,"rr":0.9,"trade":"SELL","plan":"SL 1.62552 -> TP1 1.61418","status":"Active","sl":1.62552,"tp1":1.61418,"entry":1.61949},
    {"symbol":"CORN.c","sweep":"AH+AL","direction":"<-> Both","session":"H:London / L:NY","ah":419.82,"al":417.27,"current":416.32,"rr":0.8,"trade":"SELL","plan":"SL 420.075 -> TP1 413.144","status":"Active","sl":420.075,"tp1":413.144,"entry":416.32},
    {"symbol":"NATGAS.cash","sweep":"AH+AL","direction":"<-> Both","session":"H:NY / L:London","ah":3.126,"al":3.088,"current":3.161,"rr":0.3,"trade":"BUY","plan":"SL 3.084 -> TP1 3.187","status":"Active","sl":3.084,"tp1":3.187,"entry":3.161},
    {"symbol":"CADCHF","sweep":"AH+AL","direction":"<-> Both","session":"H:London / L:London","ah":0.56736,"al":0.56603,"current":0.56874,"rr":0.3,"trade":"BUY","plan":"SL 0.56590 -> TP1 0.56951","status":"Active","sl":0.56590,"tp1":0.56951,"entry":0.56874},
    {"symbol":"SOYBEAN.c","sweep":"AH+AL","direction":"<-> Both","session":"H:London / L:London","ah":1131.57,"al":1127.10,"current":1120.35,"rr":0.0,"trade":"SELL","plan":"SL 1132.02 -> TP1 1119.87","status":"Active","sl":1132.02,"tp1":1119.87,"entry":1120.35},
    {"symbol":"USDNOK","sweep":"AH+AL","direction":"<-> Both","session":"H:London / L:London","ah":9.61492,"al":9.58305,"current":9.70977,"rr":0.0,"trade":"BUY","plan":"SL 9.57986 -> TP1 9.66649","status":"Active","sl":9.57986,"tp1":9.66649,"entry":9.70977},
    {"symbol":"DXY.cash","sweep":"AH+AL","direction":"<-> Both","session":"H:London / L:London","ah":100.329,"al":100.205,"current":100.811,"rr":0.0,"trade":"BUY","plan":"SL 100.193 -> TP1 100.530","status":"Active","sl":100.193,"tp1":100.530,"entry":100.811},
    {"symbol":"AAVUSD","sweep":"AL","direction":"-> AH","session":"Asian pre","ah":75.95,"al":72.50,"current":74.29,"rr":None,"trade":"-","plan":"-","status":"Wait breakout","sl":None,"tp1":None,"entry":None},
    {"symbol":"COTTON.c","sweep":"AL","direction":"-> AH","session":"London","ah":75.53,"al":74.85,"current":75.49,"rr":None,"trade":"-","plan":"-","status":"Wait breakout","sl":None,"tp1":None,"entry":None},
    {"symbol":"EURJPY","sweep":"AH+AL","direction":"<-> Both","session":"H:London / L:London","ah":185.124,"al":184.592,"current":184.884,"rr":None,"trade":"-","plan":"-","status":"Wait breakout","sl":None,"tp1":None,"entry":None},
    {"symbol":"GBPCHF","sweep":"AH+AL","direction":"<-> Both","session":"H:London / L:Asian","ah":1.06363,"al":1.06100,"current":1.06188,"rr":None,"trade":"-","plan":"-","status":"Wait breakout","sl":None,"tp1":None,"entry":None},
    {"symbol":"GRTUSD","sweep":"AL","direction":"-> AH","session":"London","ah":0.01960,"al":0.01900,"current":0.01932,"rr":None,"trade":"-","plan":"-","status":"Wait breakout","sl":None,"tp1":None,"entry":None},
    {"symbol":"NERUSD","sweep":"AH+AL","direction":"<-> Both","session":"H:NY / L:London","ah":2.265,"al":2.160,"current":2.212,"rr":None,"trade":"-","plan":"-","status":"Wait breakout","sl":None,"tp1":None,"entry":None},
    {"symbol":"NZDCAD","sweep":"AH","direction":"-> AL","session":"London","ah":0.81752,"al":0.81228,"current":0.81315,"rr":None,"trade":"-","plan":"-","status":"Wait breakout","sl":None,"tp1":None,"entry":None},
    {"symbol":"US30.cash","sweep":"AH+AL","direction":"<-> Both","session":"H:London / L:NY","ah":51835.96,"al":51568.53,"current":51617.23,"rr":None,"trade":"-","plan":"-","status":"Wait breakout","sl":None,"tp1":None,"entry":None},
    {"symbol":"USDZAR","sweep":"AH+AL","direction":"<-> Both","session":"H:London / L:London","ah":16.4101,"al":16.2853,"current":16.4016,"rr":None,"trade":"-","plan":"-","status":"Wait breakout","sl":None,"tp1":None,"entry":None},
    {"symbol":"USOIL.cash","sweep":"AL","direction":"-> AH","session":"London","ah":76.462,"al":74.769,"current":76.132,"rr":None,"trade":"-","plan":"-","status":"Wait breakout","sl":None,"tp1":None,"entry":None},
    {"symbol":"XCUUSD","sweep":"AH+AL","direction":"<-> Both","session":"H:London / L:NY","ah":640.83,"al":635.18,"current":636.74,"rr":None,"trade":"-","plan":"-","status":"Wait breakout","sl":None,"tp1":None,"entry":None},
]

SETUPS_HAUSSIER = 4
SETUPS_BAISSIER = 1
SETUPS_MIXTE = 14
SETUPS_ACTIVE_RR_1 = 1


# ===========================================================================
# GENERATION PDF
# ===========================================================================

F = 'Helvetica'
FB = 'Helvetica'
FM = 'Courier'

class InelidaReport(FPDF):
    """PDF report generator for InelidaMarketScanner."""

    def __init__(self):
        super().__init__(orientation='L', unit='mm', format='A4')
        self.set_auto_page_break(auto=True, margin=12)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font(FM, '', 7)
        self.set_text_color(120, 120, 120)
        self.cell(0, 4, f"InelidaMarketScanner -- Rapport du {SESSION_DATE} -- Page {self.page_no()}", align='R')
        self.ln(5)

    def footer(self):
        self.set_y(-10)
        self.set_font(FM, '', 6)
        self.set_text_color(150, 150, 150)
        self.cell(0, 4, f"Genere le {TIMESTAMP_UTC} | FTMO Demo 541320891 | Pour verification trades", align='C')

    def section_title(self, title, emoji=""):
        self.set_font(FB, 'B', 13)
        self.set_text_color(25, 25, 112)
        self.cell(0, 8, f"{emoji} {title}", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(25, 25, 112)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def sub_title(self, title):
        self.set_font(FB, 'B', 10)
        self.set_text_color(80, 80, 80)
        self.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def table_header(self, cols, widths):
        self.set_font(FB, 'B', 7.5)
        self.set_fill_color(25, 25, 112)
        self.set_text_color(255, 255, 255)
        for i, (col, w) in enumerate(zip(cols, widths)):
            self.cell(w, 6, col, border=0, fill=True, align='C' if i > 0 else 'L')
        self.ln()

    def table_row(self, cells, widths, aligns=None, colors=None):
        self.set_font(FM, '', 6.8)
        if colors:
            self.set_text_color(*colors)
        else:
            self.set_text_color(30, 30, 30)
        if self.get_y() > self.h - 18:
            self.add_page()
        for i, (cell, w) in enumerate(zip(cells, widths)):
            align = aligns[i] if aligns else ('L' if i == 0 else 'C')
            self.cell(w, 5, str(cell)[:30], border=0, align=align)
        self.ln()


def _fmt(v):
    """Format adaptatif selon magnitude."""
    if v >= 1000: return f"{v:.2f}"
    if v >= 10: return f"{v:.4f}"
    return f"{v:.5f}"


def build_report():
    pdf = InelidaReport()

    # ===================================================================
    # PAGE DE GARDE
    # ===================================================================
    pdf.add_page()
    pdf.ln(15)
    pdf.set_font(FB, 'B', 28)
    pdf.set_text_color(25, 25, 112)
    pdf.cell(0, 14, "InelidaMarketScanner", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font(FB, 'B', 16)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, "Rapport de Scan Complet -- Tous Actifs / Tous Modes", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_draw_color(25, 25, 112)
    pdf.set_line_width(0.5)
    mid = pdf.w / 2
    pdf.line(mid - 50, pdf.get_y(), mid + 50, pdf.get_y())
    pdf.ln(8)

    # Timestamps
    pdf.set_font(FB, 'B', 11)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 7, "Horodatages", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for label, value in [
        ("Heure Plateforme (Windows)", TIMESTAMP_PLATFORM),
        ("Heure UTC", TIMESTAMP_UTC),
        ("Heure Paris (CEST)", TIMESTAMP_PARIS),
        ("Date de session ICT", SESSION_DATE + " (UTC 00:00-08:00)"),
    ]:
        pdf.set_font(FM, '', 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(65, 6, label, align='R')
        pdf.set_font(FB, 'B', 9)
        pdf.set_text_color(20, 20, 20)
        pdf.cell(0, 6, f"  {value}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(8)

    # Compte
    pdf.set_font(FB, 'B', 11)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 7, "Compte de Trading", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for line in [
        f"Broker : {ACCOUNT_INFO['broker']}",
        f"Compte : {ACCOUNT_INFO['login']} @ {ACCOUNT_INFO['server']}",
        f"Balance : {ACCOUNT_INFO['balance']:.2f} {ACCOUNT_INFO['currency']}",
        f"Levier  : {ACCOUNT_INFO['leverage']}",
        f"Trade autorise : {'OUI' if ACCOUNT_INFO['trade_allowed'] else 'NON (scan uniquement)'}",
        f"Terminal Build : {ACCOUNT_INFO['terminal_build']}",
    ]:
        pdf.set_font(FM, '', 8)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 5, line, align='C', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)

    # Resume global
    pdf.set_font(FB, 'B', 11)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 7, "Resume Global du Scan", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    for label, value in [
        ("Symboles scannes", "167 (tous les actifs du broker)"),
        ("Sweeps BSL/SSL detectes (M15)", f"{SWEEPS_TOTAL} ({SWEEPS_BSL} BSL, {SWEEPS_SSL} SSL)"),
        ("Sessions asiatiques calculees", "167"),
        ("AH sweepes", str(ASIAN_AH_SWEPT)),
        ("AL sweepes", str(ASIAN_AL_SWEPT)),
        ("Les deux sweepes", str(ASIAN_BOTH_SWEPT)),
        ("Fibonacci sweepes", str(ASIAN_FIB_SWEPT)),
        ("Setups directionnels (levels)", f"{LEVELS_HAUSSIER + LEVELS_BAISSIER + LEVELS_MIXTE} ({LEVELS_HAUSSIER} H, {LEVELS_BAISSIER} B, {LEVELS_MIXTE} M)"),
        ("Setups avec trade actif", "8 (1 avec RR >= 1.0)"),
        ("Trade principal", "GBPJPY SELL RR 1.2x"),
    ]:
        pdf.set_font(FM, '', 8)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(75, 5, label, align='R')
        pdf.set_font(FB, 'B', 8)
        pdf.set_text_color(20, 20, 20)
        pdf.cell(0, 5, f"  {value}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.set_font(FM, '', 7)
    pdf.set_text_color(150, 0, 0)
    pdf.cell(0, 5, "Ce rapport est concu pour permettre une verification a posteriori des trades.", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "Consultez la section TRADE TRACKING en fin de document pour le suivi.", align='C', new_x="LMARGIN", new_y="NEXT")

    # ===================================================================
    # SECTION 1 : SWEEPS BSL/SSL
    # ===================================================================
    pdf.add_page()
    pdf.section_title("1. Liquidity Sweeps BSL / SSL", "[BSL/SSL]")
    pdf.sub_title(f"Timeframe M15 -- {SWEEPS_TOTAL} sweeps detectes sur 167 symboles ({SWEEPS_BSL} BSL, {SWEEPS_SSL} SSL)")
    pdf.sub_title("Top 20 sweeps les plus proches du prix actuel (tries par distance %)")
    pdf.ln(1)

    cw = [32, 14, 24, 24, 20, 28, 42, 42]
    pdf.table_header(["Symbole", "Label", "Niveau", "Prix Actuel", "Dist. %", "Direction ICT", "Swept At (UTC)", ""], cw)
    for s in SWEEPS_DATA:
        direction = "REVERSAL DOWN v" if "down" in s["direction"] else "REVERSAL UP ^"
        color = (180, 30, 30) if "down" in s["direction"] else (30, 130, 30)
        pdf.table_row(
            [s["symbol"], s["label"], f"{s['level']:.5f}", f"{s['current']:.5f}",
             f"{s['dist_pct']:.4f}%", direction, s["swept_at"], ""],
            cw, colors=color,
        )

    pdf.ln(4)
    pdf.set_font(FM, '', 7)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4,
        "Interpretation ICT : BSL = swing haut sweepe -> reversal_down attendu (le prix devrait baisser).\n"
        "SSL = swing bas sweepe -> reversal_up attendu (le prix devrait monter).\n"
        "Plus la distance % est faible, plus le niveau est proche du prix actuel -- a surveiller."
    )

    # ===================================================================
    # SECTION 2 : SESSION ASIATIQUE
    # ===================================================================
    pdf.add_page()
    pdf.section_title("2. Session Asiatique (UTC 00:00-08:00)", "[Asian]")
    pdf.sub_title(f"Timeframe H1 -- {ASIAN_SCANNED} symboles scannes | AH: {ASIAN_AH_SWEPT} | AL: {ASIAN_AL_SWEPT} | Both: {ASIAN_BOTH_SWEPT} | Fib: {ASIAN_FIB_SWEPT}")
    pdf.ln(2)

    active_trades = [a for a in ASIAN_RESULTS if a["trade_status"] == "Active"]
    if active_trades:
        pdf.sub_title("[ACTIF] TRADES ACTIFS (signaux ICT valides)")
        pdf.ln(1)
        tw = [28, 14, 24, 24, 24, 24, 24, 24, 14, 24, 40]
        pdf.table_header(["Symbole", "Action", "AH", "AL", "Entry", "SL", "TP1", "TP2", "RR", "Direction", "Fib"], tw)
        for t in active_trades:
            color = (180, 30, 30) if t["action"] == "SELL" else (30, 130, 30)
            pdf.table_row(
                [t["symbol"], t["action"], f"{t['ah']:.5f}", f"{t['al']:.5f}",
                 f"{t['entry']:.5f}", f"{t['sl']:.5f}", f"{t['tp1']:.5f}",
                 f"{t['tp2']:.5f}" if t["tp2"] else "-",
                 f"{t['rr']:.1f}x" if t["rr"] else "-",
                 t["direction"], t["fib"]],
                tw, colors=color,
            )

    pdf.ln(4)
    pdf.sub_title("[TOUS] Tous les resultats asiatiques")
    pdf.ln(1)
    aw = [28, 18, 20, 20, 20, 18, 18, 18, 24, 22, 30]
    pdf.table_header(["Symbole", "AH Swept", "AL Swept", "Direction", "Fib", "AH", "AL", "Now", "Trade", "Statut", "Plan"], aw)
    for r in ASIAN_RESULTS:
        ah_s = "SWEPT" if r["ah_swept"] else "-"
        al_s = "SWEPT" if r["al_swept"] else "-"
        plan = f"SL {r['sl']:.2f}->TP1 {r['tp1']:.2f}" if r["sl"] and r["tp1"] else "-"
        pdf.table_row(
            [r["symbol"], ah_s, al_s, r["direction"], r["fib"] if r["fib"] != "-" else "-",
             f"{r['ah']:.5f}", f"{r['al']:.5f}", f"{r['current']:.5f}",
             r["action"], r["trade_status"], plan],
            aw,
        )

    pdf.ln(4)
    pdf.set_font(FM, '', 7)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4,
        "Legende Direction : -> AH = reversal haussier (AL sweepe + prix > midpoint) | "
        "-> AL = reversal baissier (AH sweepe + prix < midpoint) | "
        "<-> Both = les deux sweepes | * = confirmation en attente | - = pas de sweep\n"
        "Legende Fib : -> +N = prochaine cible bull non atteinte | -> -N = prochaine cible bear"
    )

    # ===================================================================
    # SECTION 3 : NIVEAUX DAILY/WEEKLY
    # ===================================================================
    pdf.add_page()
    pdf.section_title("3. Niveaux Daily & Weekly (PDH/PDL, PWH/PWL)", "[Levels]")
    pdf.sub_title(f"{len(LEVELS_DATA)} setups directionnels -- {LEVELS_HAUSSIER} HAUSSIER, {LEVELS_BAISSIER} BAISSIER, {LEVELS_MIXTE} MIXTE")
    pdf.ln(1)

    lw = [28, 18, 16, 22, 28, 28, 28, 30]
    pdf.table_header(["Symbole", "Type", "Sweep", "Direction", "Niv. Haut", "Niv. Bas", "Now", ""], lw)
    for l in LEVELS_DATA:
        if "AH" in l["direction"]:
            color = (30, 130, 30)
        elif "AL" in l["direction"]:
            color = (180, 30, 30)
        else:
            color = (180, 150, 0)
        pdf.table_row(
            [l["symbol"], l["type"], l["sweep"], l["direction"],
             _fmt(l["level_high"]), _fmt(l["level_low"]), _fmt(l["current"]), ""],
            lw, colors=color,
        )

    pdf.ln(4)
    pdf.set_font(FM, '', 7)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4,
        "Interpretation : Sweep H = PWH/PDH sweepe -> direction baissiere -> AL attendue.\n"
        "Sweep L = PWL/PDL sweepe -> direction haussiere -> AH attendue.\n"
        "H+L = les deux sweepes -> range daily/weekly completement cassee.\n"
        "H' / L' = breach (meche traverse sans rejet) -- informatif, pas de signal directionnel."
    )

    # ===================================================================
    # SECTION 4 : SETUPS DIRECTIONNELS + TRADES
    # ===================================================================
    pdf.add_page()
    pdf.section_title("4. Setups Directionnels & Trade Ideas", "[Setups]")
    pdf.sub_title(f"{len(SETUPS_DATA)} setups -- {SETUPS_HAUSSIER} HAUSSIER, {SETUPS_BAISSIER} BAISSIER, {SETUPS_MIXTE} MIXTE | {SETUPS_ACTIVE_RR_1} trade avec RR >= 1.0")
    pdf.ln(1)

    active_setups = [s for s in SETUPS_DATA if s["status"] == "Active"]
    if active_setups:
        pdf.sub_title("[ACTIF] TRADES ACTIFS (ordre d'entree immediat)")
        pdf.ln(1)
        sw = [26, 18, 22, 28, 28, 28, 14, 14, 44]
        pdf.table_header(["Symbole", "Action", "Direction", "Entry", "SL", "TP1", "RR", "Sweep", "Plan"], sw)
        for s in active_setups:
            color = (180, 30, 30) if s["trade"] == "SELL" else (30, 130, 30)
            pdf.table_row(
                [s["symbol"], s["trade"], s["direction"],
                 f"{s['entry']:.5f}" if s["entry"] else "-",
                 f"{s['sl']:.5f}" if s["sl"] else "-",
                 f"{s['tp1']:.5f}" if s["tp1"] else "-",
                 f"{s['rr']:.1f}x" if s["rr"] is not None else "-",
                 s["sweep"], s["plan"]],
                sw, colors=color,
            )

    pdf.ln(3)
    pdf.sub_title("[TOUS] Tous les setups (actifs + en attente)")
    pdf.ln(1)
    uw = [26, 16, 22, 26, 28, 28, 28, 14, 40]
    pdf.table_header(["Symbole", "Sweep", "Direction", "Session", "AH", "AL", "Now", "RR", "Trade"], uw)
    for s in SETUPS_DATA:
        rr_str = f"{s['rr']:.1f}x" if s["rr"] is not None else "-"
        pdf.table_row(
            [s["symbol"], s["sweep"], s["direction"], s["session"],
             f"{s['ah']:.5f}", f"{s['al']:.5f}", f"{s['current']:.5f}",
             rr_str, s["trade"]],
            uw,
        )

    # ===================================================================
    # SECTION 5 : TRADE TRACKING
    # ===================================================================
    pdf.add_page()
    pdf.section_title("5. TRADE TRACKING -- Suivi pour verification gains/pertes", "[Tracking]")
    pdf.set_font(FM, '', 8)
    pdf.set_text_color(150, 0, 0)
    pdf.multi_cell(0, 5,
        "Cette section est conçue pour etre relue demain (ou plus tard) afin de determiner\n"
        "quels trades auraient ete gagnants ou perdants. Chaque trade est liste avec son\n"
        "prix d'entree, stop-loss, et take-profits. Il suffit de comparer avec le prix\n"
        "du marche au moment de la relecture.\n\n"
        "REGLES DE VERIFICATION :\n"
        "  * TRADE GAGNANT si le prix a touche TP1 (ou TP2, TP3) sans toucher le SL d'abord.\n"
        "  * TRADE PERDANT si le prix a touche le SL avant TP1.\n"
        "  * TRADE EN COURS si ni SL ni TP1 n'ont ete touches.\n"
        "  * BREAKEVEN si SL touche apres TP1 (partiel)."
    )
    pdf.ln(4)

    tracking_trades = [
        {"source":"Asian", "symbol":"WHEAT.c", "action":"SELL", "entry":602.51, "sl":612.959, "tp1":598.581, "tp2":595.533, "tp3":590.780, "rr":0.38},
        {"source":"Setup", "symbol":"GBPJPY", "action":"SELL", "entry":213.068, "sl":214.055, "tp1":211.846, "tp2":None, "tp3":None, "rr":1.2},
        {"source":"Setup", "symbol":"EURCAD", "action":"SELL", "entry":1.61949, "sl":1.62552, "tp1":1.61418, "tp2":None, "tp3":None, "rr":0.9},
        {"source":"Setup", "symbol":"CORN.c", "action":"SELL", "entry":416.32, "sl":420.075, "tp1":413.144, "tp2":None, "tp3":None, "rr":0.8},
        {"source":"Setup", "symbol":"NATGAS.cash", "action":"BUY", "entry":3.161, "sl":3.084, "tp1":3.187, "tp2":None, "tp3":None, "rr":0.3},
        {"source":"Setup", "symbol":"CADCHF", "action":"BUY", "entry":0.56874, "sl":0.56590, "tp1":0.56951, "tp2":None, "tp3":None, "rr":0.3},
        {"source":"Setup", "symbol":"SOYBEAN.c", "action":"SELL", "entry":1120.35, "sl":1132.02, "tp1":1119.87, "tp2":None, "tp3":None, "rr":0.0},
        {"source":"Setup", "symbol":"USDNOK", "action":"BUY", "entry":9.70977, "sl":9.57986, "tp1":9.66649, "tp2":None, "tp3":None, "rr":0.0},
        {"source":"Setup", "symbol":"DXY.cash", "action":"BUY", "entry":100.811, "sl":100.193, "tp1":100.530, "tp2":None, "tp3":None, "rr":0.0},
    ]

    pdf.sub_title(f"[TRACK] {len(tracking_trades)} trades a tracker")
    pdf.ln(1)

    tw2 = [20, 22, 14, 24, 24, 24, 24, 24, 14, 24, 24]
    pdf.table_header(["Source", "Symbole", "Action", "Entry", "SL", "TP1", "TP2", "TP3", "RR", "Resultat*", "Verifie le"], tw2)
    for t in tracking_trades:
        pdf.table_row(
            [t["source"], t["symbol"], t["action"],
             f"{t['entry']:.5f}", f"{t['sl']:.5f}", f"{t['tp1']:.5f}",
             f"{t['tp2']:.5f}" if t["tp2"] else "-",
             f"{t['tp3']:.5f}" if t["tp3"] else "-",
             f"{t['rr']:.1f}x",
             "_________", "_________"],
            tw2,
        )

    pdf.ln(6)
    pdf.set_font(FM, '', 7)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 4, "* A remplir lors de la relecture : GAGNE / PERDU / EN COURS / BREAKEVEN", new_x="LMARGIN", new_y="NEXT")

    # ===================================================================
    # SECTION 6 : METHODOLOGIE
    # ===================================================================
    pdf.ln(6)
    pdf.section_title("6. Methodologie de Verification", "[Methodo]")
    pdf.ln(2)

    for title, desc in [
        ("1. Prix de reference", "Le prix 'Entry' est le bid/ask au moment du scan. Les prix 'Now' sont les prix courants."),
        ("2. Delai de verification", "Verifier 24h apres le scan. Les setups ICT asiatiques se jouent generalement dans la session London/NY du jour meme ou le lendemain."),
        ("3. Gagnant/Perdant", "Comparer le prix actuel au moment de la relecture avec SL et TP1. Si le prix a franchi TP1 sans toucher SL -> GAGNE. Si SL touche avant TP1 -> PERDU."),
        ("4. RR minimum", "Les trades avec RR < 1.0 sont consideres comme 'speculatifs'. Privilegier les trades avec RR >= 1.0 pour une expectancy positive."),
        ("5. Contexte ICT", "Un sweep BSL/SSL n'est qu'un composant. La confirmation vient du depassement du midpoint et de la cassure de l'autre extremite de la range."),
    ]:
        pdf.set_font(FB, 'B', 8)
        pdf.set_text_color(25, 25, 112)
        pdf.cell(0, 5, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(FM, '', 7)
        pdf.set_text_color(70, 70, 70)
        pdf.multi_cell(0, 4, desc)
        pdf.ln(1)

    pdf.output(OUTPUT_PDF)
    return OUTPUT_PDF


# ===========================================================================
# MAIN
# ===========================================================================
if __name__ == "__main__":
    print(f"Generation du rapport PDF...")
    print(f"  Date UTC      : {TIMESTAMP_UTC}")
    print(f"  Date Paris    : {TIMESTAMP_PARIS}")
    print(f"  Date Plateforme: {TIMESTAMP_PLATFORM}")
    print(f"  Session ICT   : {SESSION_DATE}")

    path = build_report()
    size_kb = os.path.getsize(path) / 1024
    print(f"\n[OK] Rapport genere : {path}")
    print(f"   Taille : {size_kb:.1f} Ko")
    print(f"   {len(SWEEPS_DATA)} sweeps, {len(ASIAN_RESULTS)} sessions asiatiques, {len(LEVELS_DATA)} niveaux, {len(SETUPS_DATA)} setups")
    print(f"\n[INFO] Pour verifier demain : demande 'lis le PDF inelida_report.pdf et dis-moi quels trades auraient ete gagnants'")
