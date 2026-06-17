"""
Executeur d'ordres MetaTrader 5 pour InelidaMarketScan.

Prend les Trade Ideas generees par sweep_detector.detect_asian_range_for_symbol
(meme magic number = 888001) et les envoie au broker via mt5.order_send.

Garde-fous:
  * DRY-RUN ou LIVE explicite via le flag dry_run du constructeur.
  * Detection du filling_mode du symbole (FOK vs IOC vs RETURN) avant envoi.
  * Validation lot (volume >= min_lot, aligne sur lot_step, <= max_lot).
  * Verification qu'aucune position n'est deja ouverte pour ce symbol+direction
    avec le magic 888001 (anti-double-ordre).
  * Lecture du tick ask/bid immediatement avant chaque envoi (pas de prix cache).
  * Une seule confirmation Y/N globale avant la vague d envois (sauf --yes).
  * Mapping exhaustif retcode -> message lisible.
"""

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import MetaTrader5 as mt5

from .config import MT5
from .mt5_connector import MT5Connector
from .sweep_detector import AsianRangeResult

logger = logging.getLogger("TradeExecutor")

# Magic number identifiant les ordres passes par InelidaMarketScan.
# Permet de filtrer / identifier / cleanup les positions issues du bot.
INELIDA_MAGIC: int = 888001

# Commentaire affiche dans le journal MT5 (max ~31 chars selon broker).
INELIDA_COMMENT: str = "InelidaMarketScan ICT"

# Slack de deviation max autorise entre prix-theorique et prix-execute (points).
DEFAULT_DEVIATION: int = 20


# ─── Retcode mapping ──────────────────────────────────────────────────────────
_RETCODE_LABELS: dict = {
    10004: "REQUOTE",
    10005: "REJECT",
    10006: "CANCEL",
    10007: "PLACED",
    10008: "NOT_MODIFIED",
    10009: "DONE",
    10010: "DONE_PARTIAL",
    10011: "ERROR",
    10012: "TIMEOUT",
    10013: "INVALID",
    10014: "INVALID_VOLUME",
    10015: "INVALID_PRICE",
    10016: "INVALID_STOPS",
    10017: "TRADE_DISABLED",
    10018: "MARKET_CLOSED",
    10019: "NO_MONEY",
    10020: "PRICE_CHANGED",
    10021: "PRICE_OFF",
    10022: "NO_CHANGES",
    10023: "SERVER_DISABLED",
    10024: "CLIENT_DISABLED",
    10025: "TOO_FREQUENT",
    10026: "UNKNOWN_SYMBOL",
    10027: "FROZEN",
    10028: "ORDER_CANCELLED",
    10029: "SHORT_NOT_ALLOWED",
    10030: "LONG_NOT_ALLOWED",
    10031: "LIMIT_NOT_ALLOWED",
    10032: "STOP_NOT_ALLOWED",
    10033: "STOPLOSS_TAKEPROFIT",
    10034: "LIMIT_ORDER",
    10035: "TRADE_ALLOWED",
    10036: "ROUTING_REQUIRED",
    10038: "NEW_PRICE",
    10039: "PRICE_NOT_FIXED",
    10040: "NEW_PRICE_ACCEPTED",
    10041: "NEW_PRICE_REJECTED",
    10042: "QUOTE_NOT_AVAILABLE",
    10043: "LOCKED_DAILY",
    10044: "LOCKED_ORDER",
    10045: "INVALID_FILL",
    10046: "CONNECTION_LOST",
    10047: "PRICE_NOT_AVAILABLE",
}


def _retcode_label(code: int) -> str:
    return _RETCODE_LABELS.get(code, f"CODE_{code}")


# ─── Retcode hints (actionable advice pour les cas courants) ────────────────────────────
# Affichés en suffixe du message broker pour aider le user à debugger
# sans avoir à googler les codes MT5.
_RETCODE_HINTS: dict = {
    10005: "REJECT : vérifier volume_min/step du symbole, ou filling_mode != FOK/IOC.",
    10006: "CANCEL : ordre annulé (dealeur, news event, freeze temporaire). Réessayer.",
    10013: "INVALID : requête mal formée (SL/TP/prix). Vérifier que SL/TP ne sont pas inversés.",
    10014: "INVALID_VOLUME : lot < volume_min ou > volume_max ou pas aligné sur lot_step.",
    10015: "INVALID_PRICE : prix tick hors plage. Tick obsolète ou symbole suspendu.",
    10016: "INVALID_STOPS : SL/TP trop proches du prix (distance min non respectée).",
    10017: "TRADE_DISABLED : trading désactivé pour ce symbole chez le broker.",
    10018: "MARKET_CLOSED : marché fermé (week-end, pause, jours fériés).",
    10019: "NO_MONEY : fonds insuffisants sur le compte MT5.",
    10024: "CLIENT_DISABLED : trading désactivé côté client (vérifier trade_allowed du compte).",
    10027: "FROZEN : 'Only position closing is allowed'. Causes probables sur FTMO prop firm : "
           "(1) daily drawdown limit atteint, (2) trade_allowed=False côté compte/terminal, "
           "(3) news event freeze, (4) weekend/session close. Debug : lancer "
           "'python main.py account' (champ trade_allowed) + 'python main.py terminal'.",
    10029: "SHORT_NOT_ALLOWED : SELL refusé (vérifier trade_mode du symbole, certains CFDS/Crypto).",
    10030: "LONG_NOT_ALLOWED : BUY refusé (idem, vérifier trade_mode du symbole).",
    10042: "QUOTE_NOT_AVAILABLE : pas de cotation récente pour ce symbole. Réessayer.",
    10043: "LOCKED_DAILY : daily lock (fin de journée). Réessayer au roll-over broker.",
    10044: "LOCKED_ORDER : ordre verrouillé par un autotrader / EA concurrent (même ordre, magic différent).",
    10046: "CONNECTION_LOST : perte de connexion broker. Reconnexion auto via MT5Connector.",
}


def _retcode_hint(code: int) -> str:
    return _RETCODE_HINTS.get(code, "")


def _filling_mode_const(filling_mode: int) -> int:
    """Map enum filling_mode (0 / 1 / 2) to mt5.ORDER_FILLING_* constant.

    mt5.symbol_info(symbol).filling_mode returns:
      SYMBOL_FILLING_FOK  = 0
      SYMBOL_FILLING_IOC  = 1
    On some brokers there's also a 'return' mode but Python's binding usually
    collapses it into FOK/IOC. We map 0/1 explicitly and FALL BACK to FOK.
    """
    if filling_mode == 0:
        return mt5.ORDER_FILLING_FOK
    if filling_mode == 1:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_FOK  # default safety


def _normalize_volume(volume: float, info) -> float:
    """Aligne `volume` sur lot_step du symbole et clamps entre min/max."""
    if volume < info.volume_min:
        volume = info.volume_min
    if volume > info.volume_max:
        volume = info.volume_max
    step = info.volume_step or 0.01
    # Round down to nearest lot_step to avoid INVALID_VOLUME.
    volume = (int(volume / step)) * step
    return round(volume, 8)


# ─── TradeDecision : un ordre a envoyer ───────────────────────────────────────
@dataclass
class TradeDecision:
    """Une instance prete a etre envoyee au broker."""
    symbol: str
    action: str              # "BUY" / "SELL"
    entry: float
    sl: float
    tp1: float
    lots: float = 0.01
    deviation: int = DEFAULT_DEVIATION
    rr: Optional[float] = None
    source: str = ""         # ex: "AsianSession_Fib_-1.618"


@dataclass
class TradeResult:
    """Resultat d'un envoi d'ordre, en DRY-RUN ou LIVE."""
    decision: TradeDecision
    status: str              # "DRY_RUN" / "FILLED" / "FAILED" / "SKIPPED"
    retcode: Optional[int] = None
    retcode_label: str = ""
    order_id: Optional[int] = None
    deal_id: Optional[int] = None
    ask: Optional[float] = None
    bid: Optional[float] = None
    message: str = ""        # Message BRUT du broker (jamais muté)
    advice: Optional[str] = None   # Indice actionnable Inelida quand retcode commun (10005/10019/10027/etc.)


# ─── TradeExecutor ────────────────────────────────────────────────────────────
class TradeExecutor:
    """Wrapper safe pour mt5.order_send avec garde-fous."""

    def __init__(self, dry_run: bool = False, confirm_each: bool = True):
        """
        :param dry_run:        Si True, ne touche PAS le broker. Imprime ce qui
                              serait envoye. Use pour dev/test.
        :param confirm_each:   Si True, demande Y/N interactif avant chaque
                              envoi (UX-safe). Mettre False pour batch
                              automatique avec une seule confirmation globale.
        """
        self.dry_run = dry_run
        self.confirm_each = confirm_each

    # ─── Pre-flight checks ─────────────────────────────────────────────────
    def _symbol_info_safe(self, symbol: str):
        info = mt5.symbol_info(symbol)
        if info is None:
            raise ValueError(
                f"Symbole inconnu chez le broker: {symbol}. "
                f"Verifie l'orthographe ou ajoute-le a la Market Watch."
            )
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                raise RuntimeError(
                    f"Impossible d'activer le symbole {symbol} dans Market Watch."
                )
        return info

    def _tick_price(self, symbol: str, action: str) -> float:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"Pas de tick recent pour {symbol}.")
        if action == "BUY":
            if tick.ask <= 0:
                raise RuntimeError(f"Ask invalide ({tick.ask}) pour {symbol}.")
            return float(tick.ask)
        else:
            if tick.bid <= 0:
                raise RuntimeError(f"Bid invalide ({tick.bid}) pour {symbol}.")
            return float(tick.bid)

    def _existing_position(self, symbol: str, action: str) -> bool:
        """True si une position Inelida existe deja sur ce symbol+direction."""
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return False
        wanted_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        for p in positions:
            if p.magic == INELIDA_MAGIC and p.type == wanted_type:
                return True
        return False

    # ─── Envoi ─────────────────────────────────────────────────────────────
    def execute(self, decision: TradeDecision) -> TradeResult:
        """Envoie UN ordre a partir d une TradeDecision."""
        mt5c = MT5Connector()
        if not mt5c.ensure_connected():
            return TradeResult(
                decision=decision,
                status="FAILED",
                retcode=None,
                retcode_label="NO_MT5",
                message="Impossible de se connecter a MT5.",
            )

        # Selection du symbole
        try:
            info = self._symbol_info_safe(decision.symbol)
        except (ValueError, RuntimeError) as e:
            return TradeResult(
                decision=decision,
                status="FAILED",
                message=str(e),
            )

        # Validation du lot
        lots = _normalize_volume(decision.lots, info)

        # Anti double-ordre : on skip si meme magic+symbol+direction existe deja
        if self._existing_position(decision.symbol, decision.action):
            return TradeResult(
                decision=decision,
                status="SKIPPED",
                message=(
                    f"Position Inelida deja ouverte sur {decision.symbol} "
                    f"({decision.action}). Anti-double-ordre declenche."
                ),
            )

        # Lecture du prix actuel
        try:
            price = self._tick_price(decision.symbol, decision.action)
        except RuntimeError as e:
            return TradeResult(
                decision=decision,
                status="FAILED",
                message=str(e),
            )

        # DRY-RUN : pas de broker touch
        if self.dry_run:
            return TradeResult(
                decision=decision,
                status="DRY_RUN",
                ask=price,
                bid=(
                    mt5.symbol_info_tick(decision.symbol).bid
                    if mt5.symbol_info_tick(decision.symbol) else None
                ),
                message=(
                    f"[DRY-RUN] {decision.action} {lots} lots {decision.symbol} "
                    f"@ {price:.5f}, SL {decision.sl:.5f}, TP {decision.tp1:.5f}, "
                    f"deviation {decision.deviation}, RR {decision.rr if decision.rr else '-'}."
                ),
            )

        # LIVE : construire la requete d'ordre
        filling_mode = _filling_mode_const(info.filling_mode)
        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       decision.symbol,
            "volume":       lots,
            "type": (
                mt5.ORDER_TYPE_BUY if decision.action == "BUY"
                else mt5.ORDER_TYPE_SELL
            ),
            "price":        price,
            "sl":           float(decision.sl),
            "tp":           float(decision.tp1),
            "deviation":    int(decision.deviation),
            "magic":        INELIDA_MAGIC,
            "comment":      INELIDA_COMMENT[:31],
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        # Confirmation interactive Y/N sauf si l'appelant la desactive
        if self.confirm_each:
            print(
                f"  -> {decision.action} {lots} {decision.symbol} "
                f"@ {price}, SL {decision.sl}, TP {decision.tp1} ? [y/N] ",
                end="", flush=True,
            )
            ans = (input() or "").strip().lower()
            if ans not in ("y", "yes", "o", "oui"):
                return TradeResult(
                    decision=decision,
                    status="SKIPPED",
                    ask=price,
                    message="Refuse par l'utilisateur (Y/N).",
                )

        result = mt5.order_send(request)
        if result is None:
            err = mt5.last_error()
            return TradeResult(
                decision=decision,
                status="FAILED",
                ask=price,
                message=f"order_send a renvoye None. last_error={err}",
            )

        broker_msg = getattr(result, "comment", "") or ""
        hint = _retcode_hint(result.retcode)
        return TradeResult(
            decision=decision,
            status=(
                "FILLED" if result.retcode == mt5.TRADE_RETCODE_DONE
                else "PARTIAL" if result.retcode == mt5.TRADE_RETCODE_DONE_PARTIAL
                else "FAILED"
            ),
            retcode=result.retcode,
            retcode_label=_retcode_label(result.retcode),
            order_id=getattr(result, "order", None),
            deal_id=getattr(result, "deal", None),
            ask=price,
            bid=(
                mt5.symbol_info_tick(decision.symbol).bid
                if mt5.symbol_info_tick(decision.symbol) else None
            ),
            message=broker_msg,           # brut broker, jamais muté
            advice=hint if hint else None,  # hint séparé, affiché en colonne dédiée
        )

    # ─── Batch helpers ─────────────────────────────────────────────────────
    def execute_many(
        self,
        decisions: List[TradeDecision],
        batch_confirm: bool = True,
    ) -> List[TradeResult]:
        """Envoie une liste de TradeDecision. Si batch_confirm et non-DRY-RUN,
        demande UNE confirmation Y/N globale au debut."""
        results: List[TradeResult] = []
        if not decisions:
            return results

        if batch_confirm and not self.dry_run and not self.confirm_each:
            print(
                f"\n  === BATCH CONFIRMATION ===\n"
                f"  {len(decisions)} ordre(s) a envoyer (LIVE, 0.01 lots par defaut).\n"
                f"  Continuer ? [y/N] ",
                end="", flush=True,
            )
            ans = (input() or "").strip().lower()
            if ans not in ("y", "yes", "o", "oui"):
                print("  Batch annule.")
                return [
                    TradeResult(
                        decision=d, status="SKIPPED",
                        message="Batch annule (Y/N global).",
                    ) for d in decisions
                ]

        for d in decisions:
            res = self.execute(d)
            results.append(res)
            # Petit log synthetique sur chaque resultat
            label = res.status.ljust(7)
            sym = d.symbol
            action = d.action
            if res.status == "FILLED":
                logger.info(
                    "[%s] %s %s %s @ %s, SL %s, TP %s (RR %s)",
                    label, action, d.lots, sym, res.ask, d.sl, d.tp1, d.rr,
                )
            elif res.status == "DRY_RUN":
                logger.info("[%s] %s -> %s (no broker touch).", label, sym, action)
        else:
            note = res.message or res.retcode_label
            if res.advice:
                note = f"{note}  [HINT] {res.advice}"
            logger.warning(
                "[%s] %s %s -> %s",
                label, sym, action, note,
            )
            time.sleep(0.05)   # Anti rate-limit broker
        return results


# ─── Bridge AsianRangeResult -> TradeDecision ─────────────────────────────────
def asian_to_decisions(
    results: List[AsianRangeResult],
    lots: float = 0.01,
    deviation: int = DEFAULT_DEVIATION,
    rr_min: Optional[float] = None,
) -> List[TradeDecision]:
    """Convertit la liste de resultats AsianRangeResult en TradeDecision.
    Filtre ceux dont trade_status='Active'. RR_min optionnel."""
    out: List[TradeDecision] = []
    for r in results:
        if r.trade_status != "Active":
            continue
        if r.trade_action not in ("BUY", "SELL"):
            continue
        if r.trade_entry is None or r.trade_sl is None or r.trade_tp1 is None:
            continue
        if rr_min is not None and (r.trade_rr1 is None or r.trade_rr1 < rr_min):
            continue
        out.append(TradeDecision(
            symbol=r.symbol,
            action=r.trade_action,
            entry=r.trade_entry,
            sl=r.trade_sl,
            tp1=r.trade_tp1,
            lots=lots,
            deviation=deviation,
            rr=r.trade_rr1,
            source=(
                f"AsianSession_{r.direction_target}_"
                f"{(r.fib_state or '').replace('+', 'p').replace('-', 'm')}"
            ),
        ))
    return out
