"""
InelidaMarketScanner - Générateur de rapport PDF LIVE horodaté.
Se connecte à MT5, exécute tous les scans en direct, et produit
un rapport au même format que generate_report.py.
"""
import os, sys, time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.logger_config import setup_logging
logger = setup_logging("generate_live_report", level="WARNING")

import MetaTrader5 as mt5
from fpdf import FPDF

# Importer les modules du projet
from src.config import SWEEP
from src.mt5_connector import MT5Connector
from src.sweep_detector import (
    scan_market_watch_for_sweeps, scan_market_watch_asian_ranges,
    scan_market_watch_levels, sort_events, events_to_dicts,
    asians_to_dicts,
)

UTC = timezone.utc
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_DIR, "reports")
OUTPUT_PDF = os.path.join(REPORTS_DIR, f"inelida_report_{datetime.now(UTC).strftime('%Y-%m-%d_%H%M')}.pdf")

F = 'Helvetica'; FB = 'Helvetica'; FM = 'Courier'

# ─── Helpers ────────────────────────────────────────────────────────────
def _fmt(v):
    if v is None: return "-"
    if v >= 1000: return f"{v:.2f}"
    if v >= 10: return f"{v:.4f}"
    return f"{v:.5f}"

def _session_label(h_utc):
    if 0 <= h_utc < 8: return "Asian"
    if 8 <= h_utc < 13: return "London"
    if 13 <= h_utc < 21: return "NY"
    return "Off"

def _safe(text):
    """Nettoie une string de tout Unicode non supporte par fpdf."""
    if not isinstance(text, str):
        text = str(text)
    text = text.replace(chr(8594), '->').replace(chr(8596), '<->')  # fleches
    text = text.replace(chr(10003), 'v').replace(chr(183), '.')      # check, middle dot
    text = text.replace(chr(8722), '-').replace(chr(8212), '-')       # minus, em dash
    text = text.replace(chr(8211), '-').replace(chr(160), ' ')        # en dash, nbsp
    # Virer tout autre caractere non-ASCII
    return text.encode('ascii', errors='replace').decode('ascii').replace('?', '')


def _ascii_dir(label):
    """Convertit les labels direction Unicode en ASCII pour fpdf."""
    if not label: return "-"
    label = label.replace(chr(8594), "->").replace(chr(8594), "->")
    label = label.replace(chr(8596), "<->").replace(chr(183), ".").replace(chr(8722), "-")
    return label


# ─── Récupération des données MT5 ──────────────────────────────────────
def fetch_all_data():
    """Exécute tous les scans MT5 et retourne les données structurées."""
    conn = MT5Connector()
    if not conn.initialize():
        raise RuntimeError(f"MT5 connection failed: {mt5.last_error()}")

    ti = mt5.terminal_info()
    if ti is None:
        raise RuntimeError("Impossible de récupérer les infos terminal")

    ai = mt5.account_info()
    symbols = sorted({s.name for s in mt5.symbols_get()})

    account = {
        "login": ai.login if ai else 0,
        "server": ai.server if ai else "?",
        "balance": ai.balance if ai else 0,
        "currency": ai.currency if ai else "?",
        "leverage": f"1:{ai.leverage}" if ai and ai.leverage else "?",
        "trade_allowed": bool(ti.trade_allowed) if ti else False,
        "terminal_build": ti.build if ti else 0,
        "broker": ti.name if ti else "?",
    }

    # Sweeps BSL/SSL M15
    sweep_events, scanned_sweeps = scan_market_watch_for_sweeps(
        timeframe="M15", max_symbols=200, save_to_db=False
    )
    sweep_events = sort_events(sweep_events, by_distance=True)
    sweeps_list = events_to_dicts(sweep_events[:30])

    n_bsl = sum(1 for e in sweep_events if e.sweep_label == "BSL")
    n_ssl = sum(1 for e in sweep_events if e.sweep_label == "SSL")

    # Asian session
    asian_results, scanned_asian = scan_market_watch_asian_ranges(
        timeframe="H1", max_symbols=200, save_to_db=False
    )
    asian_list = asians_to_dicts(asian_results)
    n_ah_sw = sum(1 for r in asian_results if r.asian_high_swept)
    n_al_sw = sum(1 for r in asian_results if r.asian_low_swept)
    n_both = sum(1 for r in asian_results if r.asian_high_swept and r.asian_low_swept)
    n_fib = sum(1 for r in asian_results if r.bull_fib_swept or r.bear_fib_swept)

    # Levels daily + weekly
    daily_levels, _ = scan_market_watch_levels(level_type="daily", symbols_override=scanned_asian[:100])
    weekly_levels, _ = scan_market_watch_levels(level_type="weekly", symbols_override=scanned_asian[:100])

    levels_data = []
    for l in daily_levels + weekly_levels:
        if l.high_swept and l.low_swept:
            sweep = "H+L"
        elif l.high_swept: sweep = "H"
        elif l.low_swept: sweep = "L"
        elif l.high_breached and l.low_breached: sweep = "H'+L'"
        elif l.high_breached: sweep = "H'"
        elif l.low_breached: sweep = "L'"
        else: sweep = "-"
        levels_data.append({
            "symbol": l.symbol, "type": l.level_type.capitalize(),
            "sweep": sweep,
            "direction": _ascii_dir(l.direction_target_label),
            "level_high": l.level_high, "level_low": l.level_low,
            "current": l.current_price,
        })

    n_haussier = sum(1 for l in levels_data if "AH" in l["direction"])
    n_baissier = sum(1 for l in levels_data if "AL" in l["direction"])
    n_mixte = len(levels_data) - n_haussier - n_baissier

    # Setups directionnels (from asian)
    setups_data = []
    for r in asian_results:
        if r.asian_high_swept and r.asian_low_swept:
            sweep_str = "AH+AL"
            direction = "<-> Both"
            session = f"H:{r.high_swept_session_label or '?'} / L:{r.low_swept_session_label or '?'}"
        elif r.asian_high_swept:
            sweep_str = "AH"
            direction = _ascii_dir(r.direction_target_label)
            session = r.high_swept_session_label or "?"
        elif r.asian_low_swept:
            sweep_str = "AL"
            direction = _ascii_dir(r.direction_target_label)
            session = r.low_swept_session_label or "?"
        else:
            continue  # skip no-sweep

        rr_val = r.trade_rr1 if r.trade_rr1 and r.trade_rr1 > 0 else None
        setups_data.append({
            "symbol": r.symbol, "sweep": sweep_str,
            "direction": direction, "session": session,
            "ah": r.asian_high, "al": r.asian_low,
            "current": r.current_price,
            "spread_pct": r.spread_pct,
            "rr": rr_val,
            "trade": r.trade_action,
            "plan": f"SL {_fmt(r.trade_sl)} -> TP1 {_fmt(r.trade_tp1)}" if r.trade_sl and r.trade_tp1 else "-",
            "status": r.trade_status,
            "sl": r.trade_sl, "tp1": r.trade_tp1,
            "entry": r.trade_entry,
        })

    active_setups = [s for s in setups_data if s["status"] == "Active"]
    n_active_rr1 = sum(1 for s in active_setups if s["rr"] and s["rr"] >= 1.0)

    # Tracking trades
    tracking = []
    for s in active_setups[:20]:
        tracking.append({
            "source": "Setup",
            "symbol": s["symbol"], "action": s["trade"],
            "entry": s["entry"], "sl": s["sl"], "tp1": s["tp1"],
            "tp2": None, "tp3": None,
            "rr": s["rr"] if s["rr"] else 0,
            "spread_pct": s.get("spread_pct", 0),
        })

    conn.shutdown()
    return {
        "account": account,
        "sweeps": sweeps_list,
        "sweeps_total": len(sweep_events),
        "sweeps_bsl": n_bsl,
        "sweeps_ssl": n_ssl,
        "asian_list": asian_list,
        "asian_scanned": len(scanned_asian),
        "asian_ah_swept": n_ah_sw,
        "asian_al_swept": n_al_sw,
        "asian_both": n_both,
        "asian_fib": n_fib,
        "levels_data": levels_data,
        "levels_haussier": n_haussier,
        "levels_baissier": n_baissier,
        "levels_mixte": n_mixte,
        "setups_data": setups_data,
        "active_setups": active_setups,
        "active_rr1": n_active_rr1,
        "tracking": tracking,
        "symbols_scanned": len(symbols),
    }


# ─── PDF ────────────────────────────────────────────────────────────────
class InelidaReport(FPDF):
    def __init__(self, session_date, timestamp_utc):
        super().__init__(orientation='L', unit='mm', format='A4')
        self.session_date = session_date
        self.timestamp_utc = timestamp_utc
        self.set_auto_page_break(auto=True, margin=12)

    def header(self):
        if self.page_no() == 1: return
        self.set_font(FM, '', 7)
        self.set_text_color(120, 120, 120)
        self.cell(0, 4, f"InelidaMarketScanner -- Rapport du {self.session_date} -- Page {self.page_no()}", align='R')
        self.ln(5)

    def footer(self):
        self.set_y(-10); self.set_font(FM, '', 6); self.set_text_color(150, 150, 150)
        self.cell(0, 4, f"Généré le {self.timestamp_utc} | Pour vérification trades", align='C')

    def section_title(self, title):
        self.set_font(FB, 'B', 13); self.set_text_color(25, 25, 112)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(25, 25, 112)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def sub_title(self, title):
        self.set_font(FB, 'B', 10); self.set_text_color(80, 80, 80)
        self.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT"); self.ln(1)

    def table_header(self, cols, widths):
        self.set_font(FB, 'B', 7.5); self.set_fill_color(25, 25, 112); self.set_text_color(255, 255, 255)
        for i, (col, w) in enumerate(zip(cols, widths)):
            self.cell(w, 6, col, border=0, fill=True, align='C' if i > 0 else 'L')
        self.ln()

    def table_row(self, cells, widths, aligns=None, colors=None):
        self.set_font(FM, '', 6.8)
        self.set_text_color(*colors) if colors else self.set_text_color(30, 30, 30)
        if self.get_y() > self.h - 18: self.add_page()
        for i, (cell, w) in enumerate(zip(cells, widths)):
            align = aligns[i] if aligns else ('L' if i == 0 else 'C')
            self.cell(w, 5, _safe(str(cell))[:35], border=0, align=align)
        self.ln()


def build_report(data):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    now_utc = datetime.now(UTC)
    session_date = now_utc.strftime("%Y-%m-%d")
    ts_utc = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    ts_paris = (now_utc + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S CEST")
    ts_platform = datetime.now().strftime(f"%Y-%m-%d %H:%M:%S {time.tzname[0] if time.tzname else 'Local'}")

    acc = data["account"]
    pdf = InelidaReport(session_date, ts_utc)

    # ═══ PAGE DE GARDE ═══
    pdf.add_page(); pdf.ln(15)
    pdf.set_font(FB, 'B', 28); pdf.set_text_color(25, 25, 112)
    pdf.cell(0, 14, "InelidaMarketScanner", align='C', new_x="LMARGIN", new_y="NEXT"); pdf.ln(2)
    pdf.set_font(FB, 'B', 16); pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, "Rapport de Scan Complet - Tous Actifs / Tous Modes", align='C', new_x="LMARGIN", new_y="NEXT"); pdf.ln(6)
    pdf.set_draw_color(25, 25, 112); pdf.set_line_width(0.5)
    mid = pdf.w / 2; pdf.line(mid - 50, pdf.get_y(), mid + 50, pdf.get_y()); pdf.ln(8)

    pdf.set_font(FB, 'B', 11); pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 7, "Horodatages", align='C', new_x="LMARGIN", new_y="NEXT"); pdf.ln(3)
    for label, value in [
        ("Heure Plateforme (Windows)", ts_platform),
        ("Heure UTC", ts_utc), (        "Heure Paris (CEST)", ts_paris),
        ("Date de session ICT", session_date + " (UTC 00:00-08:00)"),
    ]:
        pdf.set_font(FM, '', 9); pdf.set_text_color(100, 100, 100)
        pdf.cell(65, 6, label, align='R')
        pdf.set_font(FB, 'B', 9); pdf.set_text_color(20, 20, 20)
        pdf.cell(0, 6, f"  {value}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(8)
    pdf.set_font(FB, 'B', 11); pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 7, "Compte de Trading", align='C', new_x="LMARGIN", new_y="NEXT"); pdf.ln(3)
    for line in [
        f"Broker : {acc['broker']}", f"Compte : {acc['login']} @ {acc['server']}",
        f"Balance : {acc['balance']:.2f} {acc['currency']}", f"Levier  : {acc['leverage']}",
        f"Trade autorise : {'OUI' if acc['trade_allowed'] else 'NON (scan uniquement)'}",
        f"Terminal Build : {acc['terminal_build']}",
    ]:
        pdf.set_font(FM, '', 8); pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 5, line, align='C', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)
    pdf.set_font(FB, 'B', 11); pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 7, "Résumé Global du Scan", align='C', new_x="LMARGIN", new_y="NEXT"); pdf.ln(4)
    for label, value in [
        ("Symboles scannes", f"{data['symbols_scanned']} (tous les actifs du broker)"),
        ("Sweeps BSL/SSL detectes (M15)", f"{data['sweeps_total']} ({data['sweeps_bsl']} BSL, {data['sweeps_ssl']} SSL)"),
        ("Sessions asiatiques calculees", str(data['asian_scanned'])),
        ("AH sweepes", str(data['asian_ah_swept'])), ("AL sweepes", str(data['asian_al_swept'])),
        ("Les deux sweepes", str(data['asian_both'])), ("Fibonacci sweepes", str(data['asian_fib'])),
        ("Setups directionnels (levels)", f"{len(data['levels_data'])} ({data['levels_haussier']} H, {data['levels_baissier']} B, {data['levels_mixte']} M)"),
        ("Setups avec trade actif", f"{len(data['active_setups'])} ({data['active_rr1']} avec RR >= 1.0)"),
        ("Trade principal", f"{data['active_setups'][0]['symbol']} {data['active_setups'][0]['trade']} RR {data['active_setups'][0]['rr']:.1f}x" if data['active_setups'] else "Aucun"),
    ]:
        pdf.set_font(FM, '', 8); pdf.set_text_color(100, 100, 100)
        pdf.cell(75, 5, label, align='R')
        pdf.set_font(FB, 'B', 8); pdf.set_text_color(20, 20, 20)
        pdf.cell(0, 5, f"  {value}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.set_font(FM, '', 7); pdf.set_text_color(150, 0, 0)
    pdf.cell(0, 5, "Ce rapport est conçu pour permettre une vérification a posteriori des trades.", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "Consultez la section TRADE TRACKING en fin de document pour le suivi.", align='C', new_x="LMARGIN", new_y="NEXT")

    # ═══ SECTION 1 : SWEEPS ═══
    pdf.add_page()
    pdf.section_title("1. Liquidity Sweeps BSL / SSL")
    pdf.sub_title(f"Timeframe M15 - {data['sweeps_total']} sweeps detectes sur {data['symbols_scanned']} symboles ({data['sweeps_bsl']} BSL, {data['sweeps_ssl']} SSL)")
    pdf.sub_title("Top 30 sweeps les plus proches du prix actuel (tries par distance %)")
    pdf.ln(1)

    cw = [30, 12, 24, 24, 18, 28, 42]
    pdf.table_header(["Symbole", "Label", "Niveau", "Prix Actuel", "Dist. %", "Direction ICT", "Swept At (UTC)"], cw)
    for s in data["sweeps"]:
        direction = "REVERSAL DOWN" if s.get("direction","") == "reversal_down" else "REVERSAL UP"
        color = (180, 30, 30) if "down" in s.get("direction","") else (30, 130, 30)
        swept_at = time.strftime("%Y-%m-%d %H:%M", time.gmtime(s.get("sweep_time", 0))) if s.get("sweep_time") else "-"
        pdf.table_row(
            [s.get("symbol","?"), s.get("sweep_label","?"), _fmt(s.get("level")),
             _fmt(s.get("current_price")), f"{s.get('distance_pct',0):.4f}%",
             direction, swept_at],
            cw, colors=color,
        )

    pdf.ln(4); pdf.set_font(FM, '', 7); pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4,
        "Interpretation ICT : BSL = swing haut sweepe -> reversal_down attendu. "
        "SSL = swing bas sweepé -> reversal_up attendu.\n"
        "Plus la distance % est faible, plus le niveau est proche du prix actuel - à surveiller."
    )

    # ═══ SECTION 2 : ASIAN ═══
    pdf.add_page()
    pdf.section_title("2. Session Asiatique (UTC 00:00-08:00)")
    pdf.sub_title(f"Timeframe H1 - {data['asian_scanned']} symboles scannes | AH: {data['asian_ah_swept']} | AL: {data['asian_al_swept']} | Both: {data['asian_both']} | Fib: {data['asian_fib']}")
    pdf.ln(2)

    active_trades = [a for a in data["asian_list"] if a.get("trade_status") == "Active"]
    if active_trades:
        pdf.sub_title("[ACTIF] TRADES ACTIFS (signaux ICT valides)")
        pdf.ln(1)
        tw = [24, 12, 20, 20, 20, 20, 20, 10, 10, 18, 34]
        pdf.table_header(["Symbole", "Action", "AH", "AL", "Entry", "SL", "TP1", "RR", "Spread", "Direction", "Fib"], tw)
        for t in active_trades[:15]:
            color = (180, 30, 30) if t.get("trade_action") == "SELL" else (30, 130, 30)
            sp_str = f"{t.get('spread_pct',0):.3f}%" if t.get('spread_pct', 0) > 0 else "?"
            pdf.table_row(
                [t.get("symbol","?"), t.get("trade_action","-"), _fmt(t.get("asian_high")), _fmt(t.get("asian_low")),
                 _fmt(t.get("trade_entry")), _fmt(t.get("trade_sl")), _fmt(t.get("trade_tp1")),
                 f"{t.get('trade_rr1',0):.1f}x" if t.get("trade_rr1") else "-",
                 sp_str,
                 _ascii_dir(t.get("direction_target_label","-")), t.get("fib_label","-")],
                tw, colors=color,
            )

    pdf.ln(4)
    pdf.sub_title("[TOUS] Tous les résultats asiatiques (top 30)")
    pdf.ln(1)
    aw = [24, 16, 16, 18, 18, 18, 18, 18, 12, 18, 24]
    pdf.table_header(["Symbole", "AH Swept", "AL Swept", "Direction", "AH", "AL", "Now", "Spread", "Trade", "Statut", "Plan"], aw)
    for r in data["asian_list"][:30]:
        ah_s = "SWEPT" if r.get("asian_high_swept") else "-"
        al_s = "SWEPT" if r.get("asian_low_swept") else "-"
        plan = f"SL {_fmt(r.get('trade_sl'))} -> TP1 {_fmt(r.get('trade_tp1'))}" if r.get("trade_sl") and r.get("trade_tp1") else "-"
        sp_str = f"{r.get('spread_pct',0):.3f}%" if r.get('spread_pct', 0) > 0 else "?"
        pdf.table_row(
            [r.get("symbol","?"), ah_s, al_s, _ascii_dir(r.get("direction_target_label","-")),
             _fmt(r.get("asian_high")), _fmt(r.get("asian_low")), _fmt(r.get("current_price")),
             sp_str,
             r.get("trade_action","-"), r.get("trade_status","-"), plan], aw)

    pdf.ln(4); pdf.set_font(FM, '', 7); pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4,
        "Légende Direction : -> AH = reversal haussier | -> AL = reversal baissier | "
        "<-> Both = les deux sweepees | . = confirmation en attente | - = pas de sweep"
    )

    # ═══ SECTION 3 : LEVELS ═══
    if data["levels_data"]:
        pdf.add_page()
        pdf.section_title("3. Niveaux Daily & Weekly (PDH/PDL, PWH/PWL)")
        pdf.sub_title(f"{len(data['levels_data'])} setups directionnels - {data['levels_haussier']} HAUSSIER, {data['levels_baissier']} BAISSIER, {data['levels_mixte']} MIXTE")
        pdf.ln(1)

        lw = [28, 18, 14, 22, 28, 28, 28]
        pdf.table_header(["Symbole", "Type", "Sweep", "Direction", "Niv. Haut", "Niv. Bas", "Now"], lw)
        for l in data["levels_data"][:40]:
            if "AH" in l["direction"]: color = (30, 130, 30)
            elif "AL" in l["direction"]: color = (180, 30, 30)
            else: color = (180, 150, 0)
            pdf.table_row(
                [l["symbol"], l["type"], l["sweep"], l["direction"],
                 _fmt(l["level_high"]), _fmt(l["level_low"]), _fmt(l["current"])],
                lw, colors=color)

    # ═══ SECTION 4 : SETUPS ═══
    pdf.add_page()
    pdf.section_title("4. Setups Directionnels & Trade Ideas")
    pdf.sub_title(f"{len(data['setups_data'])} setups | {len(data['active_setups'])} actifs | {data['active_rr1']} avec RR >= 1.0")
    pdf.ln(1)

    if data["active_setups"]:
        pdf.sub_title("[ACTIF] TRADES ACTIFS (ordre d'entrée immédiat)")
        pdf.ln(1)
        sw = [22, 12, 16, 22, 22, 22, 10, 12, 14, 36]
        pdf.table_header(["Symbole", "Action", "Direction", "Entry", "SL", "TP1", "RR", "Spread", "Sweep", "Plan"], sw)
        for s in data["active_setups"][:15]:
            color = (180, 30, 30) if s["trade"] == "SELL" else (30, 130, 30)
            sp_str = f"{s.get('spread_pct',0):.3f}%" if s.get('spread_pct', 0) > 0 else "?"
            pdf.table_row(
                [s["symbol"], s["trade"], s["direction"],
                 _fmt(s["entry"]), _fmt(s["sl"]), _fmt(s["tp1"]),
                 f"{s['rr']:.1f}x" if s["rr"] else "-",
                 sp_str, s["sweep"], s["plan"]],
                sw, colors=color)

    pdf.ln(3)
    pdf.sub_title("[TOUS] Tous les setups (actifs + en attente)")
    pdf.ln(1)
    uw = [22, 12, 16, 22, 22, 22, 22, 10, 16, 10]
    pdf.table_header(["Symbole", "Sweep", "Direction", "Session", "AH", "AL", "Now", "RR", "Spread", "Trade"], uw)
    for s in data["setups_data"][:30]:
        rr_str = f"{s['rr']:.1f}x" if s["rr"] else "-"
        sp_str = f"{s.get('spread_pct',0):.3f}%" if s.get('spread_pct', 0) > 0 else "?"
        pdf.table_row(
            [s["symbol"], s["sweep"], s["direction"], s["session"],
             _fmt(s["ah"]), _fmt(s["al"]), _fmt(s["current"]), rr_str, sp_str, s["trade"]], uw)

    # ═══ SECTION 5 : TRADE TRACKING ═══
    pdf.add_page()
    pdf.section_title("5. TRADE TRACKING - Suivi pour vérification gains/pertes")
    pdf.set_font(FM, '', 8); pdf.set_text_color(150, 0, 0)
    pdf.multi_cell(0, 5,
        "Cette section est conçue pour être relue demain (ou plus tard) afin de déterminer\n"
        "quels trades auraient été gagnants ou perdants. Chaque trade est listé avec son\n"
        "prix d'entrée, stop-loss, et take-profits.\n\n"
        "RÈGLES : GAGNÉ si TP1 touché sans SL d'abord | PERDU si SL touché avant TP1 | EN COURS sinon."
    )
    pdf.ln(4)

    if data["tracking"]:
        pdf.sub_title(f"[TRACK] {len(data['tracking'])} trades à tracker")
        pdf.ln(1)
        tw2 = [16, 20, 12, 22, 22, 22, 12, 14, 20, 20]
        pdf.table_header(["Source", "Symbole", "Action", "Entry", "SL", "TP1", "RR", "Spread", "Résultat*", "Vérifié le"], tw2)
        for t in data["tracking"][:20]:
            sp_str = f"{t.get('spread_pct',0):.3f}%" if t.get('spread_pct', 0) > 0 else "?"
            pdf.table_row(
                [t["source"], t["symbol"], t["action"],
                 _fmt(t["entry"]), _fmt(t["sl"]), _fmt(t["tp1"]),
                 f"{t['rr']:.1f}x" if t["rr"] else "-", sp_str,
                 "_________", "_________"], tw2)
    else:
        pdf.set_font(FM, '', 9)
        pdf.cell(0, 6, "Aucun trade actif à tracker pour le moment.", align='C')

    pdf.ln(6)
    pdf.set_font(FM, '', 7); pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 4, "* À remplir lors de la relecture : GAGNÉ / PERDU / EN COURS / BREAKEVEN", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.section_title("6. Méthodologie de Vérification")
    pdf.ln(2)
    for title, desc in [
        ("1. Prix de référence", "Le prix 'Entry' est le bid/ask au moment du scan. Les prix 'Now' sont les prix courants."),
        ("2. Délai de vérification", "Vérifier 24h après le scan. Les setups ICT asiatiques se jouent généralement dans la session London/NY du jour même ou le lendemain."),
        ("3. Gagnant/Perdant", "Comparer le prix actuel avec SL et TP1. Si TP1 touché sans SL -> GAGNÉ. Si SL touché avant TP1 -> PERDU."),
        ("4. RR minimum", "Les trades avec RR < 1.0 sont considérés comme 'spéculatifs'. Privilégier les trades avec RR >= 1.0."),
        ("5. Contexte ICT", "Un sweep BSL/SSL n'est qu'un composant. La confirmation vient du dépassement du midpoint et de la cassure de l'autre extrémité."),
    ]:
        pdf.set_font(FB, 'B', 8); pdf.set_text_color(25, 25, 112)
        pdf.cell(0, 5, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(FM, '', 7); pdf.set_text_color(70, 70, 70)
        pdf.multi_cell(0, 4, desc); pdf.ln(1)

    pdf.output(OUTPUT_PDF)
    return OUTPUT_PDF


# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

    print("=" * 70)
    print("  InelidaMarketScanner - Génération du rapport LIVE")
    print(f"  {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)
    print()

    print("[1/3] Connexion MT5 et scan en cours...")
    try:
        data = fetch_all_data()
    except Exception as e:
        print(f"[ERREUR] {e}")
        sys.exit(1)

    print(f"  {data['sweeps_total']} sweeps, {len(data['asian_list'])} asian, {len(data['levels_data'])} levels, {len(data['setups_data'])} setups")
    print(f"  {len(data['active_setups'])} trades actifs")
    print()

    print("[2/3] Génération du PDF...")
    path = build_report(data)
    size_kb = os.path.getsize(path) / 1024
    print(f"  PDF généré : {path}")
    print(f"  Taille : {size_kb:.1f} Ko")
    print()

    print("[3/3] Terminé.")
    print(f"  Rapport : {path}")
    if data["tracking"]:
        print(f"  {len(data['tracking'])} trades à tracker dans la section TRADE TRACKING")
    print()
    print("Pour vérifier demain : relis le PDF et compare avec les prix actuels.")
