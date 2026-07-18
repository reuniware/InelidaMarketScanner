"""
app_ml.py — 🧠 ML Management Dashboard (Streamlit)

Interface de gestion complète du pipeline Machine Learning InelidaMarketScanner.
Permet de gérer le dataset, l'entraînement, les prédictions et la visualisation
sans écrire une seule ligne de commande.

Usage:
    streamlit run app_ml.py

Dépendances:
    pip install streamlit pandas plotly
"""

import json
import logging
import os
import sys
import time as _time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Désactiver les logs Streamlit verbeux
logging.getLogger().setLevel(logging.WARNING)

import streamlit as st

# Configuration de la page — DOIT être la première commande Streamlit
st.set_page_config(
    page_title="InelidaMarketScan — ML Dashboard",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# ─── Imports du projet ──────────────────────────────────────────────────

# Ajouter le répertoire racine au PATH pour les imports relatifs
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database import DatabaseManager, get_db
from src.diamond_scanner import DiamondScanner, DiamondResult, get_dxy_price
from src.ml_labeler import (
    label_from_db,
    label_from_csv,
    write_labeled_csv,
)
from src.ml_trainer import load_data, train, save_model, DEFAULT_PARAMS
from src.ml_predictor import MLPredictor, extract_features
from src.trade_tracker import TradeTracker
from src.config import resolve_watchlist, DEFAULT_TZ_MODE

# ─── Constantes ─────────────────────────────────────────────────────────

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inelida_market_data.db")

UTC = timezone.utc

os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# ─── Helpers ──────────────────────────────────────────────────────────────

@st.cache_resource
def _get_db():
    """Cache la connexion DB."""
    return get_db()


@st.cache_resource
def _get_tracker():
    """Cache le TradeTracker."""
    return TradeTracker()


def _list_models() -> List[str]:
    """Liste les modèles disponibles."""
    if not os.path.isdir(MODELS_DIR):
        return []
    return sorted([
        f for f in os.listdir(MODELS_DIR)
        if f.endswith(".xgb") or f.endswith(".joblib")
    ])


def _db_stats() -> Dict[str, Any]:
    """Statistiques compactes de la DB."""
    db = _get_db()
    conn = db.conn
    if conn is None:
        return {"error": "DB non disponible"}
    try:
        cur = conn.execute("SELECT COUNT(*) FROM diamond_trades")
        total = cur.fetchone()[0]
        cur = conn.execute("SELECT COUNT(*) FROM diamond_trades WHERE status='OPEN'")
        opened = cur.fetchone()[0]
        cur = conn.execute("SELECT COUNT(*) FROM diamond_trades WHERE status='CLOSED'")
        closed = cur.fetchone()[0]
        cur = conn.execute(
            "SELECT COUNT(*) FROM diamond_trades WHERE status='CLOSED' AND pnl_pips>0"
        )
        wins = cur.fetchone()[0]
        cur = conn.execute("SELECT COUNT(*) FROM diamond_trades WHERE features_json IS NOT NULL")
        with_features = cur.fetchone()[0]
        return {
            "total": total,
            "open": opened,
            "closed": closed,
            "wins": wins,
            "losses": closed - wins,
            "with_features": with_features,
        }
    except Exception as e:
        return {"error": str(e)}


@st.cache_data(ttl=5)
def _load_csv_cached(path: str) -> pd.DataFrame:
    """Charge un CSV avec cache de 5 secondes (évite les relectures sur chaque interaction)."""
    return pd.read_csv(path)


def _format_timedelta(seconds: float) -> str:
    """Formate une durée en secondes."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        return f"{seconds/60:.1f}min"
    return f"{seconds/3600:.1f}h"


def _clean_python_cache() -> List[str]:
    """Nettoie les __pycache__ et .pyc orphelins (pattern start_dashboard.bat)."""
    cleaned = []
    proj_root = os.path.dirname(os.path.abspath(__file__))
    for root, dirs, files in os.walk(proj_root):
        if '.git' in root or '.venv' in root:
            continue
        # Supprime les dossiers __pycache__
        for d in list(dirs):
            if d == '__pycache__':
                path = os.path.join(root, d)
                shutil.rmtree(path, ignore_errors=True)
                cleaned.append(path)
        # Supprime les fichiers .pyc orphelins
        for f in files:
            if f.endswith('.pyc'):
                try:
                    os.remove(os.path.join(root, f))
                except Exception:
                    pass
    return cleaned


def _kill_streamlit_on_port(port: int = 8501) -> List[str]:
    """Tue tous les processus Streamlit sur le port donné (pattern start_dashboard.bat)."""
    killed = []
    try:
        import subprocess
        result = subprocess.run(['netstat', '-ano'], capture_output=True, timeout=10, text=True)
        for line in result.stdout.splitlines():
            if f':{port}' in line and 'LISTENING' in line:
                parts = line.strip().split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    try:
                        subprocess.run(['taskkill.exe', '/f', '/pid', pid],
                                       capture_output=True, timeout=5)
                        killed.append(pid)
                    except Exception:
                        pass
    except Exception:
        pass
    # Fallback: taskkill par nom de processus
    try:
        import subprocess
        subprocess.run(['taskkill', '/F', '/IM', 'streamlit.exe'],
                       capture_output=True, timeout=5)
    except Exception:
        pass
    return killed


def _cleanup_and_restart():
    """Nettoyage complet + redémarrage Streamlit (pattern start_dashboard.bat).
    
    Étapes:
    1. Tue les processus Streamlit sur le port 8501
    2. Nettoie les caches Python (__pycache__, .pyc)
    3. Vide le cache Streamlit
    4. Redémarre avec python -B (évite bytecode obsolète)
    """
    import subprocess, shutil
    proj_root = os.path.dirname(os.path.abspath(__file__))
    
    # 1) Kill processus sur le port
    _kill_streamlit_on_port(8501)
    
    # 2) Nettoyer les caches Python
    _clean_python_cache()
    
    # 3) Vider le cache Streamlit (dossier .streamlit dans le user home)
    streamlit_cache = os.path.join(os.path.expanduser("~"), ".streamlit")
    if os.path.isdir(streamlit_cache):
        try:
            for item in os.listdir(streamlit_cache):
                item_path = os.path.join(streamlit_cache, item)
                if os.path.isfile(item_path):
                    os.remove(item_path)
        except Exception:
            pass
    
    # 4) Redémarrer avec python -B (pas de bytecode cache)
    python_exe = sys.executable
    new_env = os.environ.copy()
    new_env["PYTHONDONTWRITEBYTECODE"] = "1"  # Évite la création de __pycache__
    
    subprocess.Popen(
        [python_exe, '-B', '-m', 'streamlit', 'run',
         os.path.join(proj_root, 'app_ml.py'),
         '--server.port', '8501',
         '--server.headless', 'true',
         '--browser.gatherUsageStats', 'false'],
        cwd=proj_root,
        env=new_env,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
    )


# ─── Session state ───────────────────────────────────────────────────────

if "training_result" not in st.session_state:
    st.session_state.training_result = None
if "last_scan_results" not in st.session_state:
    st.session_state.last_scan_results = None
if "ml_predictor" not in st.session_state:
    st.session_state.ml_predictor = None


# ════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ════════════════════════════════════════════════════════════════════════

with st.sidebar:
    if os.path.isfile("logo.png"):
        st.image("logo.png", width=100)
    st.title("🧠 ML Dashboard")
    st.caption("InelidaMarketScan — Gestion du pipeline Machine Learning")

    st.divider()

    # Contexte rapide
    stats = _db_stats()
    if "error" not in stats:
        col1, col2 = st.columns(2)
        col1.metric("Trades DB", stats["total"])
        col2.metric("Fermés", stats["closed"])
        col1.metric("Gagnés", stats["wins"])
        col2.metric("Perdus", stats["losses"])
        win_rate = stats["wins"] / max(stats["closed"], 1) * 100
        st.metric("Win Rate", f"{win_rate:.0f}%",
                  delta=f"{stats['wins']-stats['losses']:+d}" if stats['closed'] > 0 else None)

    # Modèle chargé
    models = _list_models()
    st.divider()
    st.caption("🤖 Modèle actif")
    if models:
        default_model = "diamond_v1.xgb" if "diamond_v1.xgb" in models else models[0]
        selected_model = st.selectbox("Modèle", models,
                                       index=models.index(default_model) if default_model in models else 0,
                                       key="sidebar_model")
        if st.button("Charger le modèle", use_container_width=True):
            with st.spinner("Chargement..."):
                predictor = MLPredictor(os.path.join(MODELS_DIR, selected_model))
                if predictor.load():
                    st.session_state.ml_predictor = predictor
                    st.success(f"✅ {selected_model} chargé")
                else:
                    st.error("Échec du chargement")
    else:
        st.info("Aucun modèle trouvé.\nEntraîne un modèle depuis l'onglet **Training**.")

    st.divider()
    with st.expander("⚙️ Configuration"):
        st.text_input("Répertoire modèles", MODELS_DIR, disabled=True)
        st.text_input("Répertoire données", DATA_DIR, disabled=True)
        st.text_input("Base SQLite", DB_PATH, disabled=True)


# ════════════════════════════════════════════════════════════════════════
#  MAIN — TABS
# ════════════════════════════════════════════════════════════════════════

tabs = st.tabs([
    "📊 Dashboard",
    "🏷️ Labeling",
    "🏋️ Training",
    "🔮 Predictions",
    "🔍 Data Explorer",
    "📄 CSV Viewer",
    "📈 Feature Importance",
])

# ── TAB 1: DASHBOARD ──────────────────────────────────────────────────────

with tabs[0]:
    st.header("📊 Dashboard — Vue d'ensemble")

    col1, col2, col3, col4 = st.columns(4)

    # ── MT5 Status ──
    with col1:
        st.subheader("🔌 MT5")
        try:
            import MetaTrader5 as mt5
            mt5_ok = mt5.initialize()
            if mt5_ok:
                terminal = mt5.terminal_info()
                st.success(f"✅ Connecté\n{terminal.company if terminal else ''}")
                mt5.shutdown()
            else:
                st.warning("⚠️ MT5 non connecté")
        except ImportError:
            st.warning("⚠️ MetaTrader5 non installé")

    # ── DB Status ──
    with col2:
        st.subheader("🗄️ Base de données")
        if "error" not in stats:
            st.metric("Trades totaux", stats["total"])
            st.metric("Avec features ML", stats["with_features"],
                      delta=f"{stats['with_features']/max(stats['total'],1)*100:.0f}%")
        else:
            st.error(stats["error"])

    # ── Model Status ──
    with col3:
        st.subheader("🤖 Modèle ML")
        predictor = st.session_state.get("ml_predictor")
        if predictor and predictor.is_loaded:
            st.success(f"✅ Chargé\n{os.path.basename(predictor.model_path)}")
            st.metric("Features", len(predictor._feature_names or []))
        elif models:
            st.info(f"📦 {len(models)} modèle(s) dispo\nCharger depuis l'onglet Predictions")
        else:
            st.warning("Aucun modèle")

    # ── Dataset Status ──
    with col4:
        st.subheader("📊 Dataset ML")
        labeled_csv = os.path.join(DATA_DIR, "trades_labeled.csv")
        if os.path.isfile(labeled_csv):
            df_check = pd.read_csv(labeled_csv)
            st.metric("Trades labellisés", len(df_check))
            st.metric("Features", len(df_check.columns) - 1)
        else:
            st.info("Générer depuis l'onglet Labeling")

    st.divider()

    # ── Pipeline status ──
    st.subheader("🔁 État du pipeline ML")

    pipeline_steps = [
        ("1. Collecte", "scan Diamond + track save", "✅" if stats.get("total", 0) > 0 else "⏳"),
        ("2. Features", "80+ features en DB", "✅" if stats.get("with_features", 0) > 0 else "⏳"),
        ("3. CSV", "Trades labellisés", "✅" if os.path.isfile(labeled_csv) else "⏳"),
        ("4. Training", "Modèle XGBoost", "✅" if models else "⏳"),
        ("5. Prédiction", "ML% dans le scan", "✅" if models else "⏳"),
    ]

    for step, desc, status in pipeline_steps:
        cols = st.columns([1, 6, 1])
        cols[0].markdown(f"**{status}**")
        cols[1].markdown(f"**{step}** — {desc}")
        if status == "✅":
            cols[2].markdown("✅")
        else:
            cols[2].markdown(f"⏳ *à faire*")

    # ── Quick actions ──
    st.divider()
    st.subheader("⚡ Actions rapides")

    quick_col1, quick_col2, quick_col3 = st.columns(3)

    with quick_col1:
        if st.button("📊 Afficher le rapport P&L", use_container_width=True):
            with st.spinner("Chargement..."):
                tracker = _get_tracker()
                report = tracker.get_report(limit=50)
                if "error" not in report:
                    st.json({
                        "total_trades": report["total_trades"],
                        "open_trades": report["open_trades"],
                        "closed_trades": report["closed_trades"],
                        "wins": report["wins"],
                        "losses": report["losses"],
                        "win_rate": report["win_rate"],
                        "total_pnl_pips": report.get("total_pnl_pips", 0),
                        "avg_rr": report.get("avg_rr", 0),
                    })
                else:
                    st.error(report["error"])

    with quick_col2:
        if st.button("🧹 Vider le cache Streamlit", use_container_width=True):
            st.cache_resource.clear()
            st.success("✅ Cache Streamlit vidé. Clique sur Rafraîchir.")

        if st.button("🧼 Nettoyer le cache Python", use_container_width=True):
            cleaned = _clean_python_cache()
            if cleaned:
                st.success(f"✅ {len(cleaned)} dossier(s) __pycache__ nettoyé(s)")
            else:
                st.info("Aucun __pycache__ à nettoyer.")

    with quick_col3:
        if st.button("🔄 Rafraîchir", use_container_width=True):
            st.rerun()

        restart_clicked = st.button("🔄 Redémarrage complet", use_container_width=True,
                                     type="secondary")
        if restart_clicked:
            st.warning("🚀 Redémarrage en cours... La page va se déconnecter puis se reconnecter automatiquement dans ~10 secondes.")
            st.cache_resource.clear()
            _cleanup_and_restart()
            st.stop()


# ── TAB 2: LABELING ────────────────────────────────────────────────────────

with tabs[1]:
    st.header("🏷️ Labeling — Génération du dataset ML")

    st.markdown("""
    Génère un CSV de trades labellisés prêt pour l'entraînement XGBoost.
    Le fichier sera créé dans `data/trades_labeled.csv`.
    """)

    source = st.radio(
        "Source des données",
        ["db", "manual", "scan"],
        format_func=lambda x: {
            "db": "🗄️ DB — Trades fermés avec P&L",
            "manual": "📄 CSV — Fichier manuel avec outcome",
            "scan": "📡 Scan — Scan Diamond live (outcome à remplir)",
        }.get(x, x),
        horizontal=True,
    )

    output_path = st.text_input("Fichier de sortie", "data/trades_labeled.csv")

    extra_params = st.container()

    if source == "manual":
        csv_input = extra_params.text_input("CSV d'entrée", "mon_fichier.csv")
    elif source == "scan":
        symbols_input = extra_params.text_input(
            "Symboles (séparés par des espaces)",
            "EURUSD GBPUSD XAUUSD"
        )
        tz_mode = extra_params.selectbox("Fuseau horaire", ["BROKER", "UTC", "PARIS"])
        auto_track = extra_params.checkbox(
            "💾 Enregistrer les setups dans la DB pour suivi automatique",
            value=True,
            help="Après le scan, sauvegarde les setups via track save. "
                 "Plus tard, utilise 'DB — Trades fermés avec P&L' pour générer "
                 "le CSV avec outcome rempli automatiquement."
        )
    else:
        extra_params.info(
            "🗄️ Utilise les trades CLOSED de la DB TradeTracker. "
            "L'outcome (gagné/perdu) est détecté automatiquement depuis le P&L."
        )

    if st.button("🚀 Générer le CSV", type="primary", use_container_width=True):
        # Barre de progression au lieu du spinner simple
        prog = st.progress(0, text="Initialisation...")
        try:
            if source == "db":
                prog.progress(20, text="Lecture de la DB...")
                rows = label_from_db()
                if not rows:
                    st.warning("Aucun trade fermé avec P&L dans la DB.")
                    st.info("💡 Va dans l'onglet Predictions, lance un scan, puis "
                            "sauvegarde avec track save. Reviens ici après que les trades se soient fermés.")
                    st.stop()
                prog.progress(100, text="Terminé")

            elif source == "manual":
                if not csv_input:
                    st.error("Spécifie un fichier CSV d'entrée.")
                    st.stop()
                prog.progress(20, text="Lecture du CSV...")
                rows = label_from_csv(csv_input)
                prog.progress(100, text="Terminé")

            else:
                symbols = [s.strip() for s in symbols_input.split() if s.strip()]
                if not symbols:
                    symbols = resolve_watchlist()

                # ── Étape 1: Connexion MT5 ──
                prog.progress(5, text=f"🔌 Connexion MT5 ({len(symbols)} symbole(s))...")
                scanner = DiamondScanner(symbols, tz_mode=tz_mode)
                if not scanner.initialize():
                    st.error("Connexion MT5 impossible.")
                    st.stop()

                # ── Étape 2: Scan Diamond (30-60s, bloquant) ──
                prog.progress(10, text="📡 Scan Diamond en cours (téléchargement + analyse Ichimoku multi-TF)...")
                start_time = _time.time()
                try:
                    results = scanner.scan_all()
                finally:
                    scanner.shutdown()
                elapsed = _time.time() - start_time

                if not results:
                    st.error("Aucun résultat du scan.")
                    st.stop()

                prog.progress(70, text=f"✅ Scan terminé ({len(results)} résultat(s), {elapsed:.0f}s)")

                # ── Étape 3: Extraction features ──
                rows = []
                n_sym = len(results)
                for i, r in enumerate(results):
                    feats = extract_features(r)
                    rows.append(feats)
                    pct = 70 + int(20 * (i + 1) / max(n_sym, 1))
                    prog.progress(pct, text=f"📊 Extraction features: {i+1}/{n_sym}")

                # ── Étape 4: Track save ──
                if auto_track:
                    try:
                        tracker = _get_tracker()
                        active = [r for r in results if r.bias != "FLAT" and r.quality != "WAIT"]
                        if active:
                            prog.progress(92, text=f"💾 Sauvegarde {len(active)} setup(s) dans la DB...")
                            saved = tracker.save_setups(active, force=False)
                            st.success(f"💾 {saved} setup(s) enregistré(s) dans la DB pour suivi — "
                                       f"l'outcome sera rempli automatiquement quand le trade se fermera.")
                        else:
                            st.info("Aucun setup directionnel à suivre (tous WAIT/FLAT). "
                                    "Le CSV contient les features mais sans suivi auto.")
                    except Exception as e:
                        st.warning(f"⚠️ Suivi auto non disponible : {e}")

                if not rows:
                    st.error("Aucune donnée extraite.")
                    st.stop()

                path = write_labeled_csv(rows, output_path)
                st.success(f"✅ CSV généré : `{path}`")

                # Prévisualisation
                df = pd.read_csv(path)
                st.dataframe(df.head(5), use_container_width=True)
                st.caption(f"{len(df)} lignes × {len(df.columns)} colonnes")

                # Stats — ne compter que les outcomes réellement présents
                has_outcome = any("outcome" in r for r in rows)
                if has_outcome:
                    wins = sum(1 for r in rows if r.get("outcome") == 1.0)
                    losses = sum(1 for r in rows if r.get("outcome") == 0.0)
                    if wins + losses > 0:
                        col1, col2, col3 = st.columns(3)
                        col1.metric("Gagnés", wins)
                        col2.metric("Perdus", losses)
                        col3.metric("Win Rate", f"{wins/max(wins+losses,1)*100:.0f}%")
                        st.info("Prêt pour l'entraînement ! Va dans l'onglet **Training**.")
                    else:
                        st.info("📋 Les features sont prêtes. Quand les trades se fermeront, "
                                "reviens ici avec **DB — Trades fermés avec P&L** pour générer "
                                "le CSV final avec outcome automatique.")
                else:
                    st.info("📋 Les features sont prêtes (colonne 'outcome' vide). "
                            "Quand les trades se fermeront, reviens ici avec "
                            "**DB — Trades fermés avec P&L** pour générer "
                            "le CSV final avec outcome automatique.")

                prog.progress(100, text="✅ Terminé")

        except Exception as e:
            st.error(f"Erreur : {e}")


# ── TAB 3: TRAINING ────────────────────────────────────────────────────────

with tabs[2]:
    st.header("🏋️ Training — Entraînement du modèle XGBoost")

    st.markdown("""
    Entraîne un classifieur XGBoost à partir d'un CSV labellisé.
    Le modèle est sauvegardé dans `models/` et peut être utilisé immédiatement.
    """)

    col1, col2 = st.columns([3, 1])

    with col1:
        csv_path = st.text_input("Fichier CSV labellisé", "data/trades_labeled.csv")
    with col2:
        model_name = st.text_input("Nom du modèle", "diamond_v1.xgb")

    model_output = os.path.join(MODELS_DIR, model_name)

    # ── Hyperparamètres avancés ──
    with st.expander("⚙️ Hyperparamètres avancés"):
        adv_col1, adv_col2, adv_col3 = st.columns(3)
        with adv_col1:
            max_depth = st.slider("max_depth", 2, 10, 4)
            learning_rate = st.slider("learning_rate", 0.01, 0.3, 0.05, 0.01)
            n_estimators = st.slider("n_estimators", 50, 500, 200, 50)
        with adv_col2:
            subsample = st.slider("subsample", 0.5, 1.0, 0.8, 0.05)
            colsample = st.slider("colsample_bytree", 0.5, 1.0, 0.8, 0.05)
            min_child_weight = st.slider("min_child_weight", 1, 10, 3)
        with adv_col3:
            gamma = st.slider("gamma", 0.0, 1.0, 0.1, 0.05)
            reg_alpha = st.slider("reg_alpha", 0.0, 2.0, 0.5, 0.1)
            reg_lambda = st.slider("reg_lambda", 0.0, 2.0, 1.0, 0.1)
        test_size = st.slider("Test size (fraction)", 0.1, 0.4, 0.2, 0.05)

    # ── Aperçu des données (1 seule lecture via cache) ──
    if os.path.isfile(csv_path):
        df_preview_all = _load_csv_cached(csv_path)
        st.caption("Aperçu du CSV d'entraînement :")
        st.dataframe(df_preview_all.head(3), use_container_width=True)

        if "outcome" in df_preview_all.columns:
            wins = int((df_preview_all["outcome"] == 1).sum())
            losses = int((df_preview_all["outcome"] == 0).sum())
            st.caption(f"📊 {len(df_preview_all)} trades — {wins} wins, {losses} losses")
        else:
            st.caption(f"📊 {len(df_preview_all)} trades — colonne 'outcome' absente")
    else:
        st.warning("Fichier CSV introuvable. Génère-le d'abord dans l'onglet Labeling.")

    # ── Training button ──
    train_disabled = not os.path.isfile(csv_path)
    if st.button("🏋️ Lancer l'entraînement", type="primary", use_container_width=True,
                 disabled=train_disabled):
        with st.spinner("Entraînement en cours..."):
            try:
                # Charger les données
                X, y, feature_names = load_data(csv_path)
                if X is None:
                    st.error("Impossible de charger les données.")
                    st.stop()

                # Personnaliser les paramètres
                params = dict(DEFAULT_PARAMS)
                params.update({
                    "max_depth": max_depth,
                    "learning_rate": learning_rate,
                    "n_estimators": n_estimators,
                    "subsample": subsample,
                    "colsample_bytree": colsample,
                    "min_child_weight": min_child_weight,
                    "gamma": gamma,
                    "reg_alpha": reg_alpha,
                    "reg_lambda": reg_lambda,
                })

                # Entraîner avec les paramètres personnalisés (sans muter le module)
                model, feats, metrics = train(X, y, feature_names, test_size=test_size,
                                               params_override=params)
                save_model(model, feats, model_output)

                # Stocker le résultat
                st.session_state.training_result = {
                    "model_path": model_output,
                    "metrics": metrics,
                    "feature_names": feats,
                    "params": params,
                }

                st.success(f"✅ Modèle entraîné et sauvegardé : `{model_output}`")

                # Afficher les métriques
                m = metrics
                met_col1, met_col2, met_col3, met_col4 = st.columns(4)
                met_col1.metric("Accuracy", f"{m['accuracy']*100:.1f}%")
                met_col2.metric("Precision", f"{m['precision']*100:.1f}%")
                met_col3.metric("Recall", f"{m['recall']*100:.1f}%")
                met_col4.metric("F1 Score", f"{m['f1']:.3f}")
                met_col1.metric("Train set", m.get("n_train", "?"))
                met_col2.metric("Test set", m.get("n_test", "?"))
                met_col3.metric("Features", len(feats))
                met_col4.metric("Win rate (dataset)", f"{y.sum()/max(len(y),1)*100:.0f}%")

            except Exception as e:
                st.error(f"Erreur d'entraînement : {e}")
                import traceback
                st.code(traceback.format_exc())

    # ── Afficher les résultats du dernier entraînement ──
    if st.session_state.training_result:
        st.divider()
        st.subheader("📊 Dernier entraînement")
        tr = st.session_state.training_result

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Modèle", os.path.basename(tr["model_path"]))
            st.metric("Features", len(tr["feature_names"]))

        # Feature importance plot
        if os.path.isfile(tr["model_path"]):
            try:
                import joblib
                bundle = joblib.load(tr["model_path"])
                model_obj = bundle.get("model")
                if model_obj and hasattr(model_obj, "get_booster"):
                    importance = model_obj.get_booster().get_score(importance_type="gain")
                    if importance:
                        sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:15]
                        imp_df = pd.DataFrame(sorted_imp, columns=["Feature", "Gain"])
                        fig = px.bar(imp_df, x="Gain", y="Feature", orientation="h",
                                     title="Top 15 Features (par gain)",
                                     color="Gain", color_continuous_scale="Viridis")
                        fig.update_layout(height=500)
                        st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.caption(f"Feature importance non disponible : {e}")


# ── TAB 4: PREDICTIONS ────────────────────────────────────────────────────

with tabs[3]:
    st.header("🔮 Prédictions — ML% sur les symboles")

    st.markdown("""
    Lance un scan Diamond avec le modèle ML chargé.
    La colonne **ML%** affiche la probabilité de trade gagnant.
    """)

    col1, col2 = st.columns([2, 1])

    with col1:
        symbols = st.text_input(
            "Symboles (séparés par des espaces, vide=watchlist)",
            "EURUSD GBPUSD USDJPY XAUUSD"
        )
    with col2:
        tz_mode = st.selectbox("Fuseau horaire", ["BROKER", "UTC", "PARIS"],
                               key="pred_tz")

    # Modèle actif
    active_model = None
    predictor_state = st.session_state.get("ml_predictor")
    if predictor_state and predictor_state.is_loaded:
        st.success(f"🤖 Modèle chargé : `{os.path.basename(predictor_state.model_path)}`")
        active_model = predictor_state
    else:
        st.warning("Aucun modèle chargé. Les prédictions afficheront N/A.")
        col_m1, col_m2 = st.columns(2)
        models_list = _list_models()
        if models_list:
            with col_m1:
                m_choice = st.selectbox("Charger un modèle", models_list)
            with col_m2:
                if st.button("Charger", use_container_width=True):
                    pred = MLPredictor(os.path.join(MODELS_DIR, m_choice))
                    if pred.load():
                        st.session_state.ml_predictor = pred
                        st.rerun()
                    else:
                        st.error("Échec du chargement")

    if st.button("🔮 Lancer le scan prédictif", type="primary", use_container_width=True):
        prog = st.progress(0, text="Initialisation...")
        try:
            sym_list = [s.strip() for s in symbols.split() if s.strip()]
            if not sym_list:
                sym_list = resolve_watchlist()

            # ── Étape 1: Connexion MT5 ──
            prog.progress(5, text=f"🔌 Connexion MT5 ({len(sym_list)} symbole(s))...")
            scanner = DiamondScanner(sym_list, tz_mode=tz_mode)
            if not scanner.initialize():
                st.error("Connexion MT5 impossible.")
                st.stop()

            # ── Étape 2: Scan Diamond (30-60s, bloquant) ──
            prog.progress(10, text="📡 Scan Diamond en cours (téléchargement + analyse multi-TF)...")
            start_time = _time.time()
            try:
                results = scanner.scan_all()
            finally:
                scanner.shutdown()
            elapsed = _time.time() - start_time

            st.session_state.last_scan_results = results
            prog.progress(80, text=f"✅ Scan terminé ({len(results)} résultat(s), {elapsed:.0f}s)")

            # ── Étape 3: Construction tableau ──
            prog.progress(85, text="📊 Construction du tableau...")

            # Tableau des résultats
            rows_table = []
            for r in results:
                ml_pct_val = r.ml_win_pct
                ml_display = f"{ml_pct_val*100:.0f}%" if ml_pct_val is not None else "N/A"
                rows_table.append({
                    "Symbole": r.symbol,
                    "Score": r.score,
                    "Max": r.max_score,
                    "Score %": f"{r.score/max(r.max_score,1)*100:.0f}%",
                    "Biais": r.bias,
                    "Qualité": r.quality,
                    "Prix": f"{r.price:.5f}",
                    "ML%": ml_display,
                    "RR": f"{r.rr:.1f}x" if r.rr > 0 else "-",
                    "AH Swept": "✅" if r.asian_high_swept else "❌",
                    "AL Swept": "✅" if r.asian_low_swept else "❌",
                })

            df_results = pd.DataFrame(rows_table)
            st.dataframe(df_results, use_container_width=True, hide_index=True)

            # Stats sur les ML%
            ml_values = [r.ml_win_pct for r in results if r.ml_win_pct is not None]
            if ml_values:
                col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                col_s1.metric("≥ 70% (GO)", sum(1 for v in ml_values if v >= 0.7))
                col_s2.metric("60-70%", sum(1 for v in ml_values if 0.6 <= v < 0.7))
                col_s3.metric("50-60%", sum(1 for v in ml_values if 0.5 <= v < 0.6))
                col_s4.metric("< 50% (NO GO)", sum(1 for v in ml_values if v < 0.5))

                # Distribution chart
                fig = px.histogram(
                    x=[v * 100 for v in ml_values],
                    nbins=20,
                    title="Distribution des ML%",
                    labels={"x": "ML% (probabilité de gain)"},
                    color_discrete_sequence=["#00D4AA"],
                )
                fig.add_vline(x=50, line_dash="dash", line_color="red", annotation_text="50%")
                fig.add_vline(x=60, line_dash="dash", line_color="green", annotation_text="60%")
                st.plotly_chart(fig, use_container_width=True)

            prog.progress(100, text="✅ Terminé")

        except Exception as e:
            st.error(f"Erreur scan : {e}")
            import traceback
            st.code(traceback.format_exc())


# ── TAB 5: DATA EXPLORER ──────────────────────────────────────────────────

with tabs[4]:
    st.header("🔍 Data Explorer — Exploration des trades en DB")

    tracker = _get_tracker()
    report = tracker.get_report(limit=100)

    if "error" in report:
        st.error(report["error"])
    else:
        # Stats globales
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total trades", report["total_trades"])
        col2.metric("Ouverts", report["open_trades"])
        col3.metric("Fermés", report["closed_trades"])
        col4.metric("Win Rate", f"{report['win_rate']}%")

        if report.get("total_pnl_pips"):
            col1.metric("P&L total", f"{report['total_pnl_pips']:+.1f} pips")
            col2.metric("P&L moyen", f"{report['avg_pnl_pips']:+.1f} pips")
            col3.metric("RR moyen", f"{report['avg_rr']:.2f}x")

        if report.get("best_trade"):
            b = report["best_trade"]
            st.success(f"🏆 Meilleur trade : {b['symbol']} ({b['pnl_pips']:+.1f}p) — {b['reason']}")
        if report.get("worst_trade"):
            w = report["worst_trade"]
            st.error(f"💀 Pire trade : {w['symbol']} ({w['pnl_pips']:+.1f}p) — {w['reason']}")

        st.divider()

        # Tableau des trades
        if report.get("trades"):
            df_trades = pd.DataFrame(report["trades"])
            available_cols = [c for c in [
                "id", "symbol", "status", "score", "bias", "quality",
                "price", "sl", "tp", "rr", "pnl_pips", "close_reason",
                "features_json"
            ] if c in df_trades.columns]

            # Formater features_json en booléen
            if "features_json" in df_trades.columns:
                df_trades["features_json"] = df_trades["features_json"].notna().map({True: "✅", False: "❌"})
                available_cols = [c if c != "features_json" else "ML Features" for c in available_cols]
                df_trades.rename(columns={"features_json": "ML Features"}, inplace=True)

            display_df = df_trades[available_cols] if available_cols else df_trades
            st.dataframe(display_df, use_container_width=True, hide_index=True)

            # Export CSV
            csv_data = df_trades.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Exporter les trades en CSV",
                data=csv_data,
                file_name=f"trades_export_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
            )

            # Préparer le DataFrame des trades fermés pour le graphique P&L
            closed_df = df_trades[df_trades["status"] == "CLOSED"].copy() if "status" in df_trades.columns else pd.DataFrame()
        else:
            st.info("Aucun trade dans la DB.")
            closed_df = pd.DataFrame()

        # Graphique P&L si trades fermés
        if not closed_df.empty and "pnl_pips" in closed_df.columns and "close_time" in closed_df.columns:
            st.divider()
            st.subheader("📈 Évolution du P&L")
            closed_df = closed_df.dropna(subset=["pnl_pips", "close_time"])
            closed_df["close_time_dt"] = pd.to_datetime(closed_df["close_time"], unit="s")
            closed_df = closed_df.sort_values("close_time_dt")
            closed_df["cumul_pnl"] = closed_df["pnl_pips"].cumsum()

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=closed_df["close_time_dt"],
                y=closed_df["cumul_pnl"],
                mode="lines+markers",
                name="P&L cumulé",
                line=dict(color="#00D4AA", width=2),
                marker=dict(
                    color=closed_df["pnl_pips"].apply(lambda x: "green" if x > 0 else "red"),
                    size=8,
                ),
                text=closed_df.apply(
                    lambda r: f"{r['symbol']}: {r['pnl_pips']:+.1f}p", axis=1
                ),
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            fig.update_layout(
                title="P&L cumulé dans le temps",
                xaxis_title="Date",
                yaxis_title="P&L (pips)",
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)


# ── TAB 6: CSV VIEWER ────────────────────────────────────────────────────

with tabs[5]:
    st.header("📄 CSV Viewer — Visualisation des datasets ML")

    st.markdown("""
    Explore les fichiers CSV générés par le pipeline ML.
    Utilise les filtres pour analyser les features et identifier les patterns.
    """)

    # ── Sélection du fichier ──
    csv_files = sorted([
        f for f in os.listdir(DATA_DIR)
        if f.endswith(".csv") and not f.startswith(".")
    ]) if os.path.isdir(DATA_DIR) else []

    col_f1, col_f2 = st.columns([2, 3])
    with col_f1:
        if csv_files:
            selected_csv = st.selectbox("Fichier CSV", csv_files,
                                         index=csv_files.index("trades_labeled.csv")
                                         if "trades_labeled.csv" in csv_files else 0,
                                         key="csv_viewer_file")
        else:
            st.warning("Aucun fichier CSV dans `data/`. Génère-en un depuis l'onglet Labeling.")
            selected_csv = None

    if selected_csv:
        csv_path = os.path.join(DATA_DIR, selected_csv)
        file_size = os.path.getsize(csv_path) / 1024
        mod_time = datetime.fromtimestamp(os.path.getmtime(csv_path), UTC)

        with col_f2:
            st.caption(f"📁 {selected_csv}  |  {file_size:.0f} Ko  |  modifié le {mod_time.strftime('%d/%m %H:%M')}")

        df = _load_csv_cached(csv_path)

        if df.empty:
            st.error("Fichier CSV vide.")
        else:
            # ── Aperçu global ──
            col_info1, col_info2, col_info3, col_info4 = st.columns(4)
            col_info1.metric("Lignes", len(df))
            col_info2.metric("Colonnes", len(df.columns))
            # Compter les colonnes numériques
            num_cols = len(df.select_dtypes(include=[np.number]).columns)
            col_info3.metric("Colonnes numériques", num_cols)
            # Compter les valeurs manquantes totales
            total_na = int(df.isna().sum().sum())
            col_info4.metric("Valeurs manquantes", total_na,
                             delta_color="inverse")

            st.divider()

            # ── Filtres ──
            with st.expander("🔍 Filtres avancés", expanded=True):
                col_filter1, col_filter2, col_filter3 = st.columns([2, 2, 1])

                with col_filter1:
                    search_text = st.text_input("🔎 Chercher dans tout le tableau", "",
                                                 placeholder="Ex: 1.14, BULL, 40...")

                with col_filter2:
                    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
                    filter_col = st.selectbox("Colonne à filtrer", [""] + numeric_cols)

                with col_filter3:
                    filter_min = 0.0
                    filter_max = 0.0
                    if filter_col and filter_col in df.columns:
                        col_min = float(df[filter_col].min())
                        col_max = float(df[filter_col].max())
                        filter_min, filter_max = col_min, col_max
                        if col_min < col_max:
                            filter_range = st.slider(
                                "Plage de valeurs",
                                col_min, col_max,
                                (col_min, col_max),
                                key=f"csv_range_{filter_col}"
                            )
                            filter_min, filter_max = filter_range

                # Bouton réinitialiser
                if st.button("🔄 Réinitialiser les filtres", use_container_width=True):
                    st.cache_data.clear()
                    st.rerun()

            # ── Appliquer les filtres ──
            filtered = df.copy()

            # Filtre textuel
            if search_text:
                mask = filtered.astype(str).apply(
                    lambda row: row.str.contains(search_text, case=False, na=False).any(),
                    axis=1
                )
                filtered = filtered[mask]

            # Filtre numérique
            if filter_col and filter_col in filtered.columns:
                filtered = filtered[
                    (filtered[filter_col] >= filter_min) &
                    (filtered[filter_col] <= filter_max)
                ]

            st.caption(f"Affichage : {len(filtered)} / {len(df)} lignes")

            # ── Dataframe ──
            st.dataframe(filtered, use_container_width=True, hide_index=True)

            # ── Export filtré ──
            csv_bytes = filtered.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Exporter le CSV filtré",
                data=csv_bytes,
                file_name=f"filtered_{selected_csv}",
                mime="text/csv",
            )

            st.divider()

            # ── Statistiques par colonne ──
            with st.expander("📊 Statistiques descriptives", expanded=False):
                # Uniquement les colonnes numériques
                desc = filtered.describe().T
                desc["missing"] = filtered.isna().sum()
                desc["missing_pct"] = (filtered.isna().sum() / len(filtered) * 100).round(1)
                desc = desc.rename(columns={
                    "count": "Nb", "mean": "Moyenne", "std": "Écart-type",
                    "min": "Min", "25%": "25%", "50%": "50%", "75%": "75%", "max": "Max",
                })
                st.dataframe(desc, use_container_width=True)

            # ── Distribution des colonnes numériques ──
            with st.expander("📈 Distribution des features", expanded=True):
                plot_cols = filtered.select_dtypes(include=[np.number]).columns.tolist()
                # Filtrer les colonnes binaires (0/1) et trop nombreuses
                interesting = [
                    c for c in plot_cols
                    if filtered[c].nunique() > 2
                    and filtered[c].nunique() <= 50
                ][:15]  # max 15 colonnes pour éviter la surcharge

                if interesting:
                    selected_plot_col = st.selectbox(
                        "Choisir une colonne à visualiser",
                        interesting,
                        key="csv_dist_col"
                    )
                    if selected_plot_col:
                        fig = px.histogram(
                            filtered,
                            x=selected_plot_col,
                            nbins=30,
                            title=f"Distribution de {selected_plot_col}",
                            color_discrete_sequence=["#00D4AA"],
                        )
                        # Ajouter une ligne verticale pour la moyenne
                        mean_val = filtered[selected_plot_col].mean()
                        fig.add_vline(x=mean_val, line_dash="dash", line_color="red",
                                      annotation_text=f"Moy: {mean_val:.3f}")
                        fig.update_layout(height=400)
                        st.plotly_chart(fig, use_container_width=True)

                        # Box plot pour la même colonne
                        fig2 = px.box(
                            filtered,
                            y=selected_plot_col,
                            title=f"Box plot de {selected_plot_col}",
                            color_discrete_sequence=["#00D4AA"],
                        )
                        fig2.update_layout(height=250)
                        st.plotly_chart(fig2, use_container_width=True)
                else:
                    st.info("Aucune colonne intéressante à visualiser (trop de valeurs uniques ou colonnes binaires).")

            # ── Analyse des valeurs manquantes ──
            with st.expander("⚠️ Analyse des valeurs manquantes", expanded=False):
                na_counts = filtered.isna().sum()
                na_cols = na_counts[na_counts > 0]
                if not na_cols.empty:
                    na_df = pd.DataFrame({
                        "Colonne": na_cols.index,
                        "Manquants": na_cols.values,
                        "Pourcentage": (na_cols.values / len(filtered) * 100).round(1),
                    }).sort_values("Manquants", ascending=False)

                    fig_na = px.bar(
                        na_df, x="Colonne", y="Manquants",
                        title="Valeurs manquantes par colonne",
                        text_auto=True,
                        color="Manquants",
                        color_continuous_scale="Reds",
                    )
                    fig_na.update_layout(height=400)
                    st.plotly_chart(fig_na, use_container_width=True)
                    st.dataframe(na_df, use_container_width=True, hide_index=True)
                else:
                    st.success("✅ Aucune valeur manquante dans ce jeu de données.")

            # ─── Analyse des corrélations (si assez de colonnes) ──
            with st.expander("🔗 Matrice de corrélation", expanded=False):
                num_df = filtered.select_dtypes(include=[np.number])
                if num_df.shape[1] >= 3 and num_df.shape[1] <= 30:
                    corr = num_df.corr()
                    fig_corr = px.imshow(
                        corr,
                        text_auto=".2f",
                        color_continuous_scale="RdBu_r",
                        aspect="auto",
                        title="Matrice de corrélation des features numériques",
                    )
                    fig_corr.update_layout(height=700)
                    st.plotly_chart(fig_corr, use_container_width=True)
                elif num_df.shape[1] > 30:
                    st.info(f"📊 {num_df.shape[1]} colonnes numériques — trop pour une matrice lisible. "
                            f"Utilise l'onglet Feature Importance pour l'analyse ciblée.")
                else:
                    st.info("Pas assez de colonnes numériques pour une matrice de corrélation.")

            # ── Info colonnes ──
            with st.expander("📋 Liste complète des colonnes", expanded=False):
                col_info = pd.DataFrame({
                    "Colonne": df.columns,
                    "Type": df.dtypes.astype(str),
                    "Non-nuls": df.count().values,
                    "Nuls": df.isna().sum().values,
                    "Nuls %": (df.isna().sum() / len(df) * 100).round(1).values,
                    "Cardinalité": df.nunique().values,
                }).reset_index(drop=True)
                col_info.index += 1
                st.dataframe(col_info, use_container_width=True)


# ── TAB 7: FEATURE IMPORTANCE ─────────────────────────────────────────────

with tabs[6]:
    st.header("📈 Feature Importance — Analyse des features")

    st.markdown("""
    La feature importance révèle quels critères du Diamond Scanner pèsent le plus
    dans la décision du modèle. Plus le **gain** est élevé, plus la feature est importante.
    """)

    models_list = _list_models()
    if not models_list:
        st.warning("Aucun modèle trouvé. Entraîne d'abord un modèle dans l'onglet Training.")
    else:
        selected_model = st.selectbox("Modèle à analyser", models_list)
        model_path = os.path.join(MODELS_DIR, selected_model)

        try:
            import joblib
            bundle = joblib.load(model_path)
            model_obj = bundle.get("model")
            feat_names = bundle.get("feature_names", [])

            st.metric("Features dans le modèle", len(feat_names))

            if model_obj and hasattr(model_obj, "get_booster"):
                importance = model_obj.get_booster().get_score(importance_type="gain")

                # Vue Top 15
                sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)
                top_n = st.slider("Nombre de features à afficher", 5, min(50, len(sorted_imp)), 15)

                imp_df = pd.DataFrame(sorted_imp[:top_n], columns=["Feature", "Gain"])
                imp_df["Pct"] = imp_df["Gain"] / imp_df["Gain"].sum() * 100

                fig = px.bar(
                    imp_df, x="Gain", y="Feature", orientation="h",
                    title=f"Top {top_n} Features — {selected_model}",
                    color="Gain",
                    color_continuous_scale="Viridis",
                    text_auto=".0f",
                )
                fig.update_layout(height=max(400, top_n * 25))
                st.plotly_chart(fig, use_container_width=True)

                # Catégories
                st.subheader("📊 Répartition par catégorie")
                categories = {
                    "Prix & Score": ["price", "score", "score_pct", "max_score", "bias", "alignment"],
                    "Kijun": ["kj_", "d_kj"],
                    "Tenkan": ["tk_", "d_tk"],
                    "T/K Cross": ["tkx_"],
                    "Kumo": ["kumo_"],
                    "FVG": ["fvg_"],
                    "OB": ["ob_"],
                    "Sweeps": ["swept", "asian_high", "asian_low", "london"],
                    "Volume": ["vol_"],
                    "MSS": ["mss_"],
                    "Compression": ["compression"],
                    "Flat bars": ["flat_"],
                    "Conflit": ["tkx_h1_conflict"],
                }

                cat_data = []
                for cat, prefixes in categories.items():
                    total_gain = sum(
                        v for k, v in importance.items()
                        if any(k.startswith(p) or k == p for p in prefixes)
                    )
                    if total_gain > 0:
                        cat_data.append({"Catégorie": cat, "Gain total": total_gain})

                if cat_data:
                    cat_df = pd.DataFrame(cat_data).sort_values("Gain total", ascending=True)
                    fig2 = px.pie(cat_df, values="Gain total", names="Catégorie",
                                   title="Poids des catégories de features",
                                   color_discrete_sequence=px.colors.sequential.Viridis_r)
                    st.plotly_chart(fig2, use_container_width=True)

                # Table brute
                with st.expander("📋 Table brute des features"):
                    full_df = pd.DataFrame(sorted_imp, columns=["Feature", "Gain"])
                    full_df["Pct"] = full_df["Gain"] / full_df["Gain"].sum() * 100
                    full_df = full_df.reset_index(drop=True)
                    full_df.index += 1
                    st.dataframe(full_df, use_container_width=True)

        except Exception as e:
            st.error(f"Erreur de lecture du modèle : {e}")
            import traceback
            st.code(traceback.format_exc())


# ─── Footer ────────────────────────────────────────────────────────────────

st.divider()
st.caption(
    f"InelidaMarketScan ML Dashboard — {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC | "
    f"Streamlit {st.__version__} | Python {sys.version.split()[0]}"
)
