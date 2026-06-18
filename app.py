"""
InelidaMarketScanner — Dashboard Streamlit

Lancement :
    streamlit run app.py

Fonctionnalités :
  - Dashboard général (stats en temps réel depuis la DB)
  - Sessions asiatiques (AH/AL + sweeps)
  - Niveaux daily/weekly (PDH/PDL, PWH/PWL)
  - Sweep events BSL/SSL
  - Scans en direct via MT5
"""

import logging
import os
import subprocess
import sys
import time
from datetime import datetime as _dt
from typing import Optional

import streamlit as st
import pandas as pd

# ─── Ajout du path racine pour les imports ──────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database import get_db
from src.config import DB as DB_CFG

# ─── Configuration page ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="InelidaMarketScanner",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Helpers ─────────────────────────────────────────────────────────────────
def _fmt_p(price: Optional[float]) -> str:
    if price is None:
        return "-"
    if price >= 1000.0:
        return f"{price:.2f}"
    if price >= 10.0:
        return f"{price:.4f}"
    return f"{price:.5f}"


def _ts(epoch: Optional[float]) -> str:
    if epoch is None:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(epoch))


def _color_swept(val: bool) -> str:
    return "✅" if val else "❌"


def _filter_logs(stderr: str) -> tuple:
    """Sépare les vraies erreurs (ERROR/CRITICAL) des logs INFO/WARNING.
    Retourne (full_log, error_lines)."""
    errors = []
    for line in stderr.split("\n"):
        if "| ERROR |" in line or "| CRITICAL |" in line:
            errors.append(line)
    return stderr, "\n".join(errors)


def _run_scan(command: str) -> tuple:
    """Lance une commande CLI et retourne (stdout, stderr_brut, code)."""
    try:
        r = subprocess.run(
            ["python", "main.py"] + command.split(),
            capture_output=True, text=True, timeout=120,
        )
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT (120s)", -1
    except Exception as e:
        return "", str(e), -1


def _show_scan_results(stdout: str, stderr: str, code: int):
    """Affiche les résultats d'un scan : erreurs filtrées + stdout + statut."""
    full_log, err_lines = _filter_logs(stderr)
    if err_lines:
        st.error(f"❌ Erreur(s) :\n{err_lines[:500]}")
    elif code != 0 and stderr:
        # Fallback : si pas d'ERROR dans stderr mais code != 0, afficher le brut
        st.error(f"❌ Échec (code {code}) :\n{stderr[:500]}")
    if full_log:
        with st.expander("📋 Logs"):
            st.code(full_log[:2000], language="")
    if stdout:
        st.text(stdout[:2000])
    if code == 0:
        st.success("✅ Scan terminé !")
        st.cache_data.clear()


# ─── Cache DB ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=10)
def load_stats() -> dict:
    db = get_db()
    db.connect()
    return db.get_statistics()


@st.cache_data(ttl=10)
def load_asian_sessions(limit: int = 200) -> pd.DataFrame:
    db = get_db()
    db.connect()
    rows = db.get_asian_sessions(limit=limit)
    if not rows:
        return pd.DataFrame()
    data = []
    for r in rows:
        data.append({
            "Symbole": r["symbol"],
            "Date": r["session_date"],
            "AH": r["asian_high"],
            "AL": r["asian_low"],
            "AH Swept": bool(r["asian_high_swept"]),
            "AL Swept": bool(r["asian_low_swept"]),
            "AH Touch": bool(r["asian_high_breached"]),
            "AL Touch": bool(r["asian_low_breached"]),
            "Swept H@": _ts(r["high_swept_at"]),
            "Swept L@": _ts(r["low_swept_at"]),
            "Session H": r["high_swept_session"] or "-",
            "Session L": r["low_swept_session"] or "-",
            "Fib Bull": r["bull_fib_swept_label"] or "-",
            "Fib Bear": r["bear_fib_swept_label"] or "-",
        })
    return pd.DataFrame(data)


@st.cache_data(ttl=10)
def load_level_sweeps(limit: int = 200) -> pd.DataFrame:
    db = get_db()
    db.connect()
    rows = db.get_level_sweeps(limit=limit)
    if not rows:
        return pd.DataFrame()
    data = []
    for r in rows:
        data.append({
            "Symbole": r["symbol"],
            "Type": r["level_type"],
            "Date": r["level_date"],
            "Niv. Haut": r["level_high"],
            "Niv. Bas": r["level_low"],
            "H Swept": bool(r["high_swept"]),
            "L Swept": bool(r["low_swept"]),
            "H Touch": bool(r["high_breached"]),
            "L Touch": bool(r["low_breached"]),
            "H Swept@": _ts(r["high_swept_at"]),
            "L Swept@": _ts(r["low_swept_at"]),
        })
    return pd.DataFrame(data)


@st.cache_data(ttl=10)
def load_sweep_events(limit: int = 200) -> pd.DataFrame:
    db = get_db()
    db.connect()
    rows = db.get_sweep_events(limit=limit)
    if not rows:
        return pd.DataFrame()
    data = []
    for r in rows:
        data.append({
            "Symbole": r["symbol"],
            "Label": r["sweep_label"],
            "Level": r["level"],
            "Sweep Time": _ts(r["sweep_time"]),
            "Direction": r["direction"],
            "Dist %": f"{r['distance_pct']:.2f}%" if r["distance_pct"] else "-",
        })
    return pd.DataFrame(data)


# ─── Sidebar ─────────────────────────────────────────────────────────────────
st.sidebar.title("📊 InelidaMarketScanner")
st.sidebar.caption("Dashboard de trading ICT")

page = st.sidebar.radio(
    "Navigation",
    ["🏠 Dashboard", "🌏 Sessions Asiatiques", "📈 Niveaux Daily/Weekly",
     "⚡ Sweep Events", "🗄️ Base de Données", "🔍 Scan en Direct"],
)

st.sidebar.markdown("---")
st.sidebar.markdown(f"**Fichier DB :** `{os.path.basename(DB_CFG.path)}`")

db_size = os.path.getsize(DB_CFG.path) / 1024 if os.path.exists(DB_CFG.path) else 0
st.sidebar.markdown(f"**Taille DB :** {db_size:.1f} Ko")

if st.sidebar.button("🔄 Rafraîchir les données"):
    st.cache_data.clear()
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE : DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
if page == "🏠 Dashboard":
    st.title("🏠 Dashboard")
    stats = load_stats()

    if not stats:
        st.warning("Aucune donnée en base. Lance un scan avec la page '🔍 Scan en Direct'.")
    else:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📊 Sessions Asiatiques", stats.get("asian_total", 0))
        with col2:
            st.metric("🔴 High Sweeps", stats.get("asian_high_swept", 0))
        with col3:
            st.metric("🟢 Low Sweeps", stats.get("asian_low_swept", 0))
        with col4:
            st.metric("🏷️ Symboles suivis", stats.get("symbols_tracked", 0))

        col5, col6, col7 = st.columns(3)
        with col5:
            st.metric("⚡ Sweeps BSL/SSL", stats.get("sweep_total", 0))
        with col6:
            st.metric("⬆️ BSL", stats.get("bsl_total", 0))
        with col7:
            st.metric("⬇️ SSL", stats.get("ssl_total", 0))

        st.subheader("📅 Dernières sessions")
        if stats.get("last_dates"):
            df_dates = pd.DataFrame(stats["last_dates"])
            df_dates.columns = ["Date", "Symboles scannés"]
            st.dataframe(df_dates, use_container_width=True, hide_index=True)

        # Taux de sweep
        st.subheader("📈 Taux de sweep")
        total = stats.get("asian_total", 0) or 1
        ah_rate = stats.get("asian_high_swept", 0) / total * 100
        al_rate = stats.get("asian_low_swept", 0) / total * 100
        col_a, col_b = st.columns(2)
        col_a.metric("🏆 Taux AH Swept", f"{ah_rate:.1f}%")
        col_b.metric("🏆 Taux AL Swept", f"{al_rate:.1f}%")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE : SESSIONS ASIATIQUES
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🌏 Sessions Asiatiques":
    st.title("🌏 Sessions Asiatiques")

    df = load_asian_sessions()
    if df.empty:
        st.warning("Aucune session asiatique enregistrée.")
    else:
        # Filtres
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            symbols = ["Tous"] + sorted(df["Symbole"].unique().tolist())
            sel_sym = st.selectbox("Symbole", symbols)
        with col_f2:
            dates = ["Toutes"] + sorted(df["Date"].unique().tolist(), reverse=True)
            sel_date = st.selectbox("Date", dates)
        with col_f3:
            sweep_filter = st.selectbox(
                "Filtre Sweep",
                ["Tous", "AH Swept", "AL Swept", "Les deux swept", "Aucun sweep"],
            )

        filtered = df.copy()
        if sel_sym != "Tous":
            filtered = filtered[filtered["Symbole"] == sel_sym]
        if sel_date != "Toutes":
            filtered = filtered[filtered["Date"] == sel_date]
        if sweep_filter == "AH Swept":
            filtered = filtered[filtered["AH Swept"] == True]
        elif sweep_filter == "AL Swept":
            filtered = filtered[filtered["AL Swept"] == True]
        elif sweep_filter == "Les deux swept":
            filtered = filtered[(filtered["AH Swept"] == True) & (filtered["AL Swept"] == True)]
        elif sweep_filter == "Aucun sweep":
            filtered = filtered[(filtered["AH Swept"] == False) & (filtered["AL Swept"] == False)]

        # Styling
    def _highlight_swept(val):
        if val == True:
            return "background-color: #4CAF50; color: white"
        return ""

        styled = filtered.style.map(_highlight_swept, subset=["AH Swept", "AL Swept"])

        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            column_config={
                "AH": st.column_config.NumberColumn(format="%.5f"),
                "AL": st.column_config.NumberColumn(format="%.5f"),
            },
        )
        st.caption(f"Affichage : {len(filtered)} / {len(df)} sessions")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE : NIVEAUX DAILY / WEEKLY
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📈 Niveaux Daily/Weekly":
    st.title("📈 Niveaux Daily & Weekly")

    df = load_level_sweeps()
    if df.empty:
        st.warning("Aucun niveau daily/weekly enregistré. Lance un scan 'levels' depuis la page dédiée.")
    else:
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            types = ["Tous"] + sorted(df["Type"].unique().tolist())
            sel_type = st.selectbox("Type de niveau", types)
        with col_t2:
            syms_l = ["Tous"] + sorted(df["Symbole"].unique().tolist())
            sel_sym_l = st.selectbox("Symbole", syms_l)

        filtered = df.copy()
        if sel_type != "Tous":
            filtered = filtered[filtered["Type"] == sel_type]
        if sel_sym_l != "Tous":
            filtered = filtered[filtered["Symbole"] == sel_sym_l]

        st.dataframe(filtered, use_container_width=True, hide_index=True)
        st.caption(f"Affichage : {len(filtered)} / {len(df)} niveaux")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE : SWEEP EVENTS
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "⚡ Sweep Events":
    st.title("⚡ Sweep Events (BSL/SSL)")

    df = load_sweep_events()
    if df.empty:
        st.warning("Aucun sweep event enregistré.")
    else:
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            syms_s = ["Tous"] + sorted(df["Symbole"].unique().tolist())
            sel_sym_s = st.selectbox("Symbole", syms_s)
        with col_s2:
            labels = ["Tous"] + sorted(df["Label"].unique().tolist())
            sel_label = st.selectbox("Label", labels)

        filtered = df.copy()
        if sel_sym_s != "Tous":
            filtered = filtered[filtered["Symbole"] == sel_sym_s]
        if sel_label != "Tous":
            filtered = filtered[filtered["Label"] == sel_label]

        st.dataframe(filtered, use_container_width=True, hide_index=True)
        st.caption(f"Affichage : {len(filtered)} / {len(df)} events")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE : BASE DE DONNEES
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🗄️ Base de Données":
    st.title("🗄️ Base de Données SQLite")

    db_path = os.path.abspath(DB_CFG.path)
    st.info(f"📁 **Fichier :** `{db_path}`")

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        taille = os.path.getsize(db_path) / 1024 if os.path.exists(db_path) else 0
        st.metric("Taille", f"{taille:.1f} Ko")
    with col_d2:
        st.metric("Existe", "✅" if os.path.exists(db_path) else "❌")

    db = get_db()
    db.connect()
    cur = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [r[0] for r in cur.fetchall()]

    st.subheader("📋 Tables")
    for t in tables:
        cur2 = db.conn.execute(f"SELECT COUNT(*) FROM {t}")
        count = cur2.fetchone()[0]
        st.write(f"- **{t}** : {count} ligne(s)")

    if st.button("🗑️ Réinitialiser le cache Streamlit"):
        st.cache_data.clear()
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE : SCAN EN DIRECT
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🔍 Scan en Direct":
    st.title("🔍 Scan en Direct")
    st.warning(
        "⚠️ Nécessite MT5 lancé et connecté. Les scans peuvent prendre "
        "jusqu'à 2 minutes (surtout avec --scan-all)."
    )

    # ── Asian Scan ──────────────────────────────────────────────────────────
    with st.expander("🌏 Scan Asiatique", expanded=True):
        col_a1, col_a2, col_a3 = st.columns([2, 2, 1])
        with col_a1:
            asian_tf = st.selectbox("Timeframe", ["H1", "M15", "M30", "H4"], key="a_tf")
        with col_a2:
            asian_mode = st.radio("Mode", ["MarketWatch", "--scan-all"], key="a_mode")
        with col_a3:
            asian_date = st.date_input("Date", value=_dt.now(), key="a_date")

        if st.button("🚀 Lancer le scan asiatique", type="primary"):
            cmd = f"asian --timeframe {asian_tf} --session-date {asian_date.strftime('%Y-%m-%d')}"
            if asian_mode == "--scan-all":
                cmd += " --scan-all"
            with st.spinner(f"Scan asiatique en cours ({asian_tf})..."):
                stdout, stderr, code = _run_scan(cmd)
            _show_scan_results(stdout, stderr, code)

    # ── Levels Scan ─────────────────────────────────────────────────────────
    with st.expander("📈 Scan Daily/Weekly Levels", expanded=False):
        col_l1, col_l2 = st.columns([2, 2])
        with col_l1:
            level_type = st.radio("Type", ["daily", "weekly", "all"], key="l_type")
        with col_l2:
            level_mode = st.radio("Mode", ["MarketWatch", "--scan-all"], key="l_mode")

        if st.button("🚀 Lancer le scan levels", type="primary"):
            cmd = f"levels --type {level_type}"
            if level_mode == "--scan-all":
                cmd += " --scan-all"
            with st.spinner(f"Scan levels ({level_type}) en cours..."):
                stdout, stderr, code = _run_scan(cmd)
            _show_scan_results(stdout, stderr, code)

    # ── Sweeps Scan ─────────────────────────────────────────────────────────
    with st.expander("⚡ Scan Sweeps BSL/SSL", expanded=False):
        col_s1, col_s2 = st.columns([2, 2])
        with col_s1:
            sw_tf = st.selectbox("Timeframe", ["M15", "M5", "M30", "H1", "H4"], key="s_tf")
        with col_s2:
            sw_mode = st.radio("Mode", ["MarketWatch", "--scan-all", "--all"], key="s_mode")

        if st.button("🚀 Lancer le scan sweeps", type="primary"):
            cmd = f"sweeps --timeframe {sw_tf}"
            if sw_mode == "--scan-all":
                cmd += " --scan-all"
            elif sw_mode == "--all":
                cmd += " --all"
            with st.spinner(f"Scan sweeps ({sw_tf}) en cours..."):
                stdout, stderr, code = _run_scan(cmd)
            _show_scan_results(stdout, stderr, code)

    # ── Setups ──────────────────────────────────────────────────────────────
    with st.expander("🎯 Setups directionnels", expanded=False):
        col_u1, col_u2 = st.columns(2)
        with col_u1:
            setups_mode = st.radio("Mode", ["MarketWatch", "--scan-all"], key="u_mode")
        with col_u2:
            setups_rr = st.number_input("RR min", 0.0, 10.0, 0.0, 0.5, key="u_rr")

        if st.button("🚀 Lancer scan setups", type="primary"):
            cmd = "setups"
            if setups_mode == "--scan-all":
                cmd += " --scan-all"
            if setups_rr > 0:
                cmd += f" --rr-min {setups_rr}"
            with st.spinner("Scan setups en cours..."):
                stdout, stderr, code = _run_scan(cmd)
            _show_scan_results(stdout, stderr, code)
