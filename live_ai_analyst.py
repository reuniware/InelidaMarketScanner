"""
Live AI Analyst — Analyse ICT temps réel à chaque clôture M5 via Gemini.
==========================================================================
Surveille un ou plusieurs symboles, et à chaque fermeture de bougie M5
(toutes les 5 minutes), envoie les données à Google Gemini (IA gratuite,
1500 requêtes/jour) pour une analyse concise de la situation ICT.

Utilisation :
    python live_ai_analyst.py
    python live_ai_analyst.py --symbols XAUUSD
    python live_ai_analyst.py --symbols XAUUSD EURUSD
    python live_ai_analyst.py --max-cycles 6  # test : 6 bougies = 30 min

Fonctionnement :
    1. Connexion MT5 (une fois)
    2. Pré-calcul des niveaux du jour (Asian, PDH/PDL)
    3. Boucle infinie :
       a. Attend la prochaine clôture M5 (HH:00, HH:05, HH:10...)
       b. Récupère les dernières bougies M5 + tick
       c. Formate un prompt concis
       d. Appelle l'API Gemini (gratuit)
       e. Parse la réponse pour détecter des trades haute probabilité
       f. Sauvegarde l'analyse dans ai_analyses/
    4. Ctrl+C pour arrêter proprement

Clé API Gemini (gratuite) : https://aistudio.google.com/apikey
"""

import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List

import MetaTrader5 as mt5

# Ajouter le répertoire du projet au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.ai_client import GeminiAnalyst
from src.ai_analyst import format_m5_candle_prompt, save_analysis
from src.config import resolve_watchlist, DEFAULT_WATCHLIST
from src.mt5_connector import MT5Connector

UTC = timezone.utc

# ─── Configuration ──────────────────────────────────────────────────────────
# Charger .env si présent (clé API, jamais commitée)
from src.config import load_dotenv
load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.0-flash"

if not GEMINI_API_KEY:
    print("╔" + "═" * 68 + "╗")
    print("║  CLÉ API GEMINI MANQUANTE" + " " * 42 + "║")
    print("╠" + "═" * 68 + "╣")
    print("║  Crée un fichier .env à la racine du projet avec :" + " " * 18 + "║")
    print("║" + " " * 68 + "║")
    print("║    GEMINI_API_KEY=TA_CLE_ICI" + " " * 39 + "║")
    print("║" + " " * 68 + "║")
    print("║  Clé gratuite : https://aistudio.google.com/apikey" + " " * 18 + "║")
    print("╚" + "═" * 68 + "╝")
    sys.exit(1)

M5_SECONDS = 300                     # 5 minutes en secondes
M5_LOOKBACK = 6                      # Nombre de bougies M5 à charger pour contexte
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "ai_analyses",
)
ASIAN_START_UTC = 0
ASIAN_END_UTC = 8

# ─── ANSI (couleurs console) ────────────────────────────────────────────────
_IS_TTY = sys.stdout.isatty()
def _c(code): return code if _IS_TTY else ""
BOLD = _c("\033[1m"); DIM = _c("\033[2m")
RED = _c("\033[31m"); GREEN = _c("\033[32m"); YELLOW = _c("\033[33m")
CYAN = _c("\033[36m"); MAGENTA = _c("\033[35m"); WHITE = _c("\033[97m")
BG_RED = _c("\033[41m"); BG_GREEN = _c("\033[42m"); BG_YELLOW = _c("\033[43m")
RESET = _c("\033[0m"); BELL = "\a"

# ─── Helpers ────────────────────────────────────────────────────────────────

def _fmt(p: Optional[float]) -> str:
    if p is None:
        return "-"
    if p >= 1000:
        return f"{p:.2f}"
    if p >= 10:
        return f"{p:.4f}"
    return f"{p:.5f}"


def _ts(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%H:%M:%S")


def _next_m5_close() -> float:
    """Retourne l'epoch UTC de la prochaine clôture M5."""
    now = time.time()
    return ((now // M5_SECONDS) + 1) * M5_SECONDS


def _bars_to_dicts(rates_raw) -> List[dict]:
    """Convertit le ndarray MT5 en liste de dicts."""
    out = []
    for r in rates_raw:
        out.append({
            "time": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "tick_volume": int(r[5]) if len(r) > 5 else 0,
        })
    return out


def _fetch_m5_context(symbol: str, n_bars: int = M5_LOOKBACK) -> List[dict]:
    """Récupère les N dernières bougies M5 complétées pour un symbole."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, n_bars)
    if rates is None or len(rates) == 0:
        return []
    bars = _bars_to_dicts(rates)
    bars.sort(key=lambda b: b["time"])
    return bars


def _compute_daily_levels(symbol: str) -> Dict:
    """Calcule les niveaux quotidiens : Asian range + PDH/PDL.

    Returns:
        Dict avec ah, al, ah_swept, al_swept, pdh, pdl, direction.
    """
    result = {
        "ah": None, "al": None,
        "ah_swept": False, "al_swept": False,
        "pdh": None, "pdl": None,
        "direction": "-",
    }

    today = datetime.now(UTC).strftime("%Y-%m-%d")

    # ── Asian range (H1) ──────────────────────────────────────────────
    rates_h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 48)
    if rates_h1 is not None and len(rates_h1) > 0:
        asian_bars = []
        for r in rates_h1:
            dt = datetime.fromtimestamp(int(r[0]), UTC)
            if dt.strftime("%Y-%m-%d") == today:
                h = dt.hour
                if ASIAN_START_UTC <= h < ASIAN_END_UTC:
                    asian_bars.append(r)
        if len(asian_bars) >= 2:
            result["ah"] = max(float(r[2]) for r in asian_bars)
            result["al"] = min(float(r[3]) for r in asian_bars)

    # ── PDH/PDL (D1) ─────────────────────────────────────────────────
    rates_d1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 3)
    if rates_d1 is not None and len(rates_d1) >= 2:
        result["pdh"] = float(rates_d1[-2][2])  # high du jour précédent
        result["pdl"] = float(rates_d1[-2][3])  # low du jour précédent

    # ── Sweep detection (vérification rapide post-Asian) ─────────────
    if result["ah"] is not None and result["al"] is not None:
        # Vérifier si le prix actuel a déjà sweepé AH ou AL
        tick = mt5.symbol_info_tick(symbol)
        current_price = float(tick.bid) if tick else 0

        # Regarder les bougies M5 récentes pour détecter un sweep
        m5_bars = _fetch_m5_context(symbol, 30)
        for b in m5_bars:
            if not result["ah_swept"] and b["high"] > result["ah"] and b["close"] < result["ah"]:
                result["ah_swept"] = True
            if not result["al_swept"] and b["low"] < result["al"] and b["close"] > result["al"]:
                result["al_swept"] = True

        # Direction ICT
        midpoint = (result["ah"] + result["al"]) / 2
        if result["ah_swept"] and not result["al_swept"]:
            result["direction"] = "-> AL (baissier)" if current_price < midpoint else "Wait"
        elif result["al_swept"] and not result["ah_swept"]:
            result["direction"] = "-> AH (haussier)" if current_price > midpoint else "Wait"
        elif result["ah_swept"] and result["al_swept"]:
            result["direction"] = "BOTH swept (range invalidee)"
        else:
            if current_price > result["ah"]:
                result["direction"] = "Au-dessus AH (bull breakout)"
            elif current_price < result["al"]:
                result["direction"] = "Sous AL (bear breakout)"
            elif current_price > midpoint:
                result["direction"] = "Au-dessus midpoint"
            else:
                result["direction"] = "Sous midpoint"

    return result


def _identify_candle_structure(c: Dict) -> str:
    """Identifie la structure d'une bougie: bullish, bearish, doji, etc."""
    body = c["close"] - c["open"]
    wick_high = c["high"] - max(c["open"], c["close"])
    wick_low = min(c["open"], c["close"]) - c["low"]
    total_range = c["high"] - c["low"] if c["high"] != c["low"] else 0.00001

    body_pct = abs(body) / total_range * 100

    if body_pct < 10:
        return "Doji/indecis"
    if body > 0 and wick_high < body * 0.3:
        return "Bullish (fort)"
    if body > 0:
        return "Bullish"
    if body < 0 and wick_low < abs(body) * 0.3:
        return "Bearish (fort)"
    if body < 0:
        return "Bearish"
    return "Indecis"


# ─── Détection trade dans la réponse Freebuff ───────────────────────────────

# Patterns regex pour extraire un signal de trade de la réponse NL
_RE_BUY = re.compile(
    r'(?:BUY|ACHAT|LONG|achat|buy|long)\b.*?'
    r'(?:SL|STOP|stop|sl)[\s:=]*([\d.,]+).*?'
    r'(?:TP|TARGET|tp|target|cible)[\s:=]*([\d.,]+)',
    re.IGNORECASE,
)
_RE_SELL = re.compile(
    r'(?:SELL|VENTE|SHORT|sell|short|vente)\b.*?'
    r'(?:SL|STOP|stop|sl)[\s:=]*([\d.,]+).*?'
    r'(?:TP|TARGET|tp|target|cible)[\s:=]*([\d.,]+)',
    re.IGNORECASE,
)
_RE_ENTRY = re.compile(
    r'(?:ENTR(?:É|E)E|ENTRY|entr[ée]e|entry|@)\s*[:=]?\s*([\d.,]+)',
    re.IGNORECASE,
)
_RE_RR = re.compile(
    r'(?:RR|R/R|risk.?reward)[\s:=]*([\d.,]+)\s*(?:x|:1)?',
    re.IGNORECASE,
)
# Mots indiquant une forte conviction
_HIGH_CONFIDENCE = re.compile(
    r'(?:fort|strong|recommand|conseill|probable|confirment|claire?|évident)',
    re.IGNORECASE,
)


def _safe_float(s: Optional[str]) -> Optional[float]:
    """Convertit une chaîne en float de façon sécurisée (gère , et .)."""
    if not s:
        return None
    try:
        clean = s.replace(',', '.')
        # Éviter les doubles points (ex: "1.234.56")
        if clean.count('.') > 1:
            # Prendre la première occurrence comme séparateur décimal
            parts = clean.split('.')
            clean = ''.join(parts[:-1]) + '.' + parts[-1]
        return float(clean)
    except (ValueError, AttributeError):
        return None


def _parse_trade_from_analysis(response: str, symbol: str) -> Optional[Dict]:
    """Extrait un signal de trade haute probabilité de la réponse Freebuff.

    Parse le texte en langage naturel pour trouver :
    - Direction (BUY/SELL)
    - Niveau d'entrée
    - Stop Loss
    - Take Profit
    - Ratio Risque/Récompense
    - Niveau de confiance

    Returns:
        Dict avec les infos du trade, ou None si pas de signal clair.
    """
    # Chercher BUY ou SELL
    buy_match = _RE_BUY.search(response)
    sell_match = _RE_SELL.search(response)

    if not buy_match and not sell_match:
        return None

    # Déterminer la direction
    if buy_match and sell_match:
        # Les deux mentions : prendre le premier dans le texte
        buy_pos = buy_match.start()
        sell_pos = sell_match.start()
        if buy_pos < sell_pos:
            direction = "BUY"
            match = buy_match
        else:
            direction = "SELL"
            match = sell_match
    elif buy_match:
        direction = "BUY"
        match = buy_match
    else:
        direction = "SELL"
        match = sell_match

    # Extraire SL et TP (sécurisé : lastindex peut être None)
    sl_str = match.group(1) if match.group(1) else None
    tp_str = match.group(2) if match.lastindex and match.lastindex >= 2 else None
    sl = _safe_float(sl_str)
    tp = _safe_float(tp_str)

    # Chercher un prix d'entrée
    entry = None
    entry_match = _RE_ENTRY.search(response)
    if entry_match:
        entry = _safe_float(entry_match.group(1))

    # Chercher un RR
    rr = None
    rr_match = _RE_RR.search(response)
    if rr_match:
        rr = _safe_float(rr_match.group(1))

    # Niveau de confiance
    confidence = "haute" if _HIGH_CONFIDENCE.search(response) else "moyenne"

    return {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": rr,
        "confidence": confidence,
    }


def _display_trade_alert(trade: Dict, symbol: str, candle_time: str):
    """Affiche une alerte de trade bien visible avec disclaimer.

    NE TRADE JAMAIS. Affichage informatif uniquement.
    """
    direction = trade["direction"]
    bg = BG_GREEN if direction == "BUY" else BG_RED
    fg = GREEN if direction == "BUY" else RED
    arrow = "▲" if direction == "BUY" else "▼"

    bar = "━" * 58

    print()
    print(f"  {bg}{WHITE}{BOLD} {bar} {RESET}")
    print(f"  {bg}{WHITE}{BOLD}  {arrow} SIGNAL {direction} SUR {symbol} — PROBABILITÉ {trade['confidence'].upper()} {arrow}  {RESET}")
    print(f"  {bg}{WHITE}{BOLD} {bar} {RESET}")
    print(f"  {BOLD}{fg}  {'─'*54}{RESET}")

    if trade.get("entry"):
        print(f"  {BOLD}  Entrée  : {WHITE}{_fmt(trade['entry'])}{RESET}")
    else:
        print(f"  {BOLD}  Entrée  : {DIM}(prix actuel){RESET}")

    if trade.get("sl"):
        print(f"  {BOLD}  SL      : {RED}{_fmt(trade['sl'])}{RESET}")

    if trade.get("tp"):
        print(f"  {BOLD}  TP      : {GREEN}{_fmt(trade['tp'])}{RESET}")

    if trade.get("rr"):
        rr_color = GREEN if trade["rr"] >= 1.5 else YELLOW
        print(f"  {BOLD}  RR      : {rr_color}{trade['rr']:.1f}x{RESET}")

    print(f"  {BOLD}{fg}  {'─'*54}{RESET}")
    print(f"  {BG_YELLOW}{RED}{BOLD}  ⚠ PAS DE TRADING AUTO — INFORMATION SEULEMENT ⚠  {RESET}")
    print(f"  {bg}{WHITE}{BOLD} {bar} {RESET}")
    print()
    sys.stdout.flush()


# ═══════════════════════════════════════════════════════════════════════════════
# MONITEUR LIVE
# ═══════════════════════════════════════════════════════════════════════════════

class LiveM5Analyst:
    """Moniteur temps réel qui analyse chaque bougie M5 via Freebuff."""

    def __init__(
        self,
        symbols: List[str],
        max_cycles: Optional[int] = None,
    ):
        self.symbols = symbols
        self.max_cycles = max_cycles
        self.levels_cache: Dict[str, Dict] = {}
        self.cycle_count = 0
        self._running = False
        self._analyst = GeminiAnalyst(api_key=GEMINI_API_KEY, model=GEMINI_MODEL)

    # ─── Initialisation ──────────────────────────────────────────────────

    def _connect_mt5(self) -> bool:
        """Connexion MT5."""
        if not mt5.initialize():
            print("[ERREUR] Connexion MT5 impossible.")
            return False

        ti = mt5.terminal_info()
        if ti:
            print(f"  Terminal : {ti.name} (build {ti.build})")

        for sym in list(self.symbols):  # copie pour éviter skip lors du remove
            info = mt5.symbol_info(sym)
            if info is None:
                print(f"  [WARN] Symbole inconnu: {sym}")
                self.symbols.remove(sym)
            elif not info.visible:
                mt5.symbol_select(sym, True)

        return len(self.symbols) > 0

    def _init_levels(self):
        """Pré-calcule les niveaux quotidiens pour tous les symboles."""
        print("  Calcul des niveaux du jour...")
        for sym in self.symbols:
            lv = _compute_daily_levels(sym)
            self.levels_cache[sym] = lv
            if lv["ah"] is not None:
                print(f"    {sym}: AH={_fmt(lv['ah'])} AL={_fmt(lv['al'])} "
                      f"PDH={_fmt(lv['pdh'])} PDL={_fmt(lv['pdl'])} | "
                      f"{lv['direction']}")

    def _refresh_levels(self):
        """Re-calcule les niveaux (1 fois par heure)."""
        for sym in self.symbols:
            self.levels_cache[sym] = _compute_daily_levels(sym)

    # ─── Boucle principale ───────────────────────────────────────────────

    def run(self):
        """Lance la boucle de monitoring M5."""
        print()
        print("=" * 70)
        print("  LIVE AI ANALYST — ICT M5 via GEMINI (gratuit)")
        print(f"  Démarrage : {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"  Symboles  : {', '.join(self.symbols)}")
        print(f"  Sortie    : {OUTPUT_DIR}")
        print("=" * 70)
        print()

        if not self._connect_mt5():
            return

        self._init_levels()
        self._running = True
        last_level_refresh = time.time()
        self.cycle_count = 0

        try:
            while self._running:
                # ── Attendre la prochaine clôture M5 ─────────────────
                next_close = _next_m5_close()
                wait_sec = next_close - time.time()

                if wait_sec > 0:
                    nc_str = datetime.fromtimestamp(next_close, UTC).strftime("%H:%M:%S")
                    remaining = int(wait_sec)
                    while remaining > 0:
                        print(f"\r  [Attente] Prochaine clôture M5 à {nc_str} UTC "
                              f"(dans {remaining}s)...", end=" ", flush=True)
                        sleep_time = min(5, remaining)
                        time.sleep(sleep_time)
                        next_close = _next_m5_close()
                        remaining = int(next_close - time.time())
                    print()

                # ── Rafraîchir les niveaux (toutes les heures) ───────
                if time.time() - last_level_refresh > 3600:
                    print("  [Refresh] Recalcul des niveaux...")
                    self._refresh_levels()
                    last_level_refresh = time.time()

                # ── Analyser chaque symbole ──────────────────────────
                self.cycle_count += 1
                now_str = datetime.now(UTC).strftime("%H:%M:%S")
                print(f"  [{now_str}] Cycle #{self.cycle_count} — "
                      f"{len(self.symbols)} symbole(s)")

                for sym in self.symbols:
                    self._analyze_symbol(sym)

                # Limite de cycles (test)
                if self.max_cycles and self.cycle_count >= self.max_cycles:
                    print(f"\n  [STOP] {self.max_cycles} cycles atteints.")
                    break

        except KeyboardInterrupt:
            print(f"\n\n  [STOP] Interrompu après {self.cycle_count} cycles.")
        finally:
            mt5.shutdown()
            print(f"  [OK] MT5 déconnecté. Analyses dans : {OUTPUT_DIR}")

    def _analyze_symbol(self, symbol: str):
        """Analyse UN symbole via Freebuff à la clôture M5."""
        # 1. Récupérer les données
        candles = _fetch_m5_context(symbol, M5_LOOKBACK)
        if not candles or len(candles) < 2:
            print(f"    {symbol}: pas assez de données M5")
            return

        latest = candles[-1]
        recent = candles[-5:] if len(candles) >= 5 else candles

        # 2. Structure de la bougie (locale)
        structure = _identify_candle_structure(latest)

        # 3. Niveaux
        lv = self.levels_cache.get(symbol, {})

        # 4. Formater le prompt
        prompt = format_m5_candle_prompt(
            symbol=symbol,
            candle=latest,
            recent_candles=recent[:-1],  # exclure la bougie courante
            asian_high=lv.get("ah"),
            asian_low=lv.get("al"),
            asian_high_swept=lv.get("ah_swept", False),
            asian_low_swept=lv.get("al_swept", False),
            pdh=lv.get("pdh"),
            pdl=lv.get("pdl"),
            current_direction=lv.get("direction", "-"),
        )

        # 5. Afficher un résumé local
        ct = _ts(latest["time"])
        close = _fmt(latest["close"])
        print(f"    {symbol} [{ct}] {structure} Close={close}")

        # 6. Analyse Gemini (direct API, pas de Freebuff)
        t0 = time.time()
        print(f"    {symbol} [{ct}] ⟳ Envoi Gemini...", end=" ", flush=True)
        result = self._analyst.analyze(prompt)
        elapsed = time.time() - t0

        if result and result != "(réponse vide)" and "bloqué" not in result:
            lines = result.strip().split('\n')
            preview = lines[0][:100] if lines else "(vide)"
            print(f"OK ({elapsed:.0f}s) → {preview}")

            # ── Détection trade haute probabilité ────────────────────
            trade = _parse_trade_from_analysis(result, symbol)
            if trade:
                _display_trade_alert(trade, symbol, ct)

            # Sauvegarder
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filepath = save_analysis(
                f"[{symbol} M5 {ct}] {structure} Close={close}\n"
                f"Direction ICT: {lv.get('direction', '-')}\n"
                f"{'─'*50}\n\n"
                f"{result}",
                OUTPUT_DIR,
            )
            print(f"         Sauvegardé: {os.path.basename(filepath)}")
        else:
            print(f"ÉCHEC ({elapsed:.0f}s) → pas de réponse")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Live AI Analyst — Analyse ICT M5 via Freebuff (gratuit)"
    )
    parser.add_argument(
        "--symbols", nargs="*", default=None,
        help="Symboles à surveiller (défaut: XAUUSD seulement).",
    )
    parser.add_argument(
        "--max-cycles", type=int, default=None,
        help="Nombre max de cycles M5 (pour test).",
    )
    args = parser.parse_args()

    # Résolution des symboles
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols if s.strip()]
    else:
        symbols = ["XAUUSD"]  # Défaut : l'or uniquement

    if not symbols:
        print("[ERREUR] Aucun symbole spécifié.")
        return 1

    # Créer le répertoire de sortie
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Lancer le moniteur
    monitor = LiveM5Analyst(
        symbols=symbols,
        max_cycles=args.max_cycles,
    )
    monitor.run()
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[STOP] Interrompu.")
        sys.exit(130)
