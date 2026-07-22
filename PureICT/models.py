"""PureICT — Dataclasses des niveaux asiatiques et FVGs."""

from dataclasses import dataclass, asdict, fields
from typing import List, Optional


# ===============================================================================
# FORMATTEUR DE PRIX
# ===============================================================================

def fmt_price(p: float) -> str:
    """Formatte un prix avec precision adaptative selon sa magnitude."""
    if p is None:
        return "-"
    if p >= 1000.0:
        return f"{p:.2f}"
    if p >= 10.0:
        return f"{p:.4f}"
    return f"{p:.5f}"


# ===============================================================================
# DATACLASSES
# ===============================================================================

@dataclass
class AsianLevels:
    """Niveaux de la session asiatique pour un symbole (comme le Pine Script).

    Champs ajoutes vs Pine Script original :
      - open_first_bar / close_last_bar : prix d'ouverture/fermeture de la session
      - high_at_epoch / low_at_epoch    : timestamp exact du AH et du AL
      - ah_swept / al_swept             : sweep ICT post-session
      - fib_up_*/fib_dn_*               : extensions Fibonacci (1.618-5.618)
      - ote_bear/bull_high/low          : zone OTE retracement 0.618-0.382
      - in_ote_bear / in_ote_bull       : prix dans la zone OTE ?
    """
    symbol: str
    session_date: str               # Date Paris de la session (YYYY-MM-DD)
    session_label: str              # "Current" / "Completed"
    is_live: bool                   # True si session en cours (AH/AL evolutifs)
    open_first_bar: float           # Prix d'ouverture de la 1ere bougie Asian
    close_last_bar: float           # Prix de fermeture de la derniere bougie
    asian_high: float               # Plus haut de la session (refHigh)
    asian_low: float                # Plus bas de la session (refLow)
    high_at_epoch: float            # Timestamp UTC de la bougie du AH
    low_at_epoch: float             # Timestamp UTC de la bougie du AL
    midpoint: float                 # (AH + AL) / 2  (midline)
    range_pips: float               # AH - AL
    range_pct: float                # (AH - AL) / Mid * 100
    bars_in_session: int            # Nombre de barres utilisees
    ah_swept: bool                  # Asian High sweepe ? (meche + rejet)
    al_swept: bool                  # Asian Low sweepe ?
    ah_swept_at: Optional[str]      # Heure UTC du sweep AH (HH:MM:SS)
    al_swept_at: Optional[str]      # Heure UTC du sweep AL
    current_price: float            # Prix actuel bid
    # FVG detection (AH/AL reclaim)
    fvg_ah: Optional[list] = None  # Liste des FVGs baissiers pres AH
    fvg_al: Optional[list] = None  # Liste des FVGs haussiers pres AL
    # Max lots calcules depuis la marge libre du compte
    max_lots: Optional[float] = None
    account_currency: str = ""
    margin_per_lot: Optional[float] = None
    # Extensions Fibonacci (calculees depuis le midpoint)
    fib_up_1618: float = 0.0
    fib_up_2618: float = 0.0
    fib_up_3618: float = 0.0
    fib_up_4618: float = 0.0
    fib_up_5618: float = 0.0
    fib_dn_1618: float = 0.0
    fib_dn_2618: float = 0.0
    fib_dn_3618: float = 0.0
    fib_dn_4618: float = 0.0
    fib_dn_5618: float = 0.0
    # OTE (Optimal Trade Entry) — retracement 0.618-0.382 du range
    ote_bear_high: float = 0.0
    ote_bear_low: float = 0.0
    ote_bull_high: float = 0.0
    ote_bull_low: float = 0.0
    in_ote_bear: bool = False
    in_ote_bull: bool = False


@dataclass
class PreviousAsianLevels:
    """Session asiatique PRECEDENTE (figee, comme les lignes var du Pine Script)."""
    symbol: str
    session_date: str
    asian_high: float
    asian_low: float
    midpoint: float
    range_pips: float
    range_pct: float
    bars_in_session: int


@dataclass
class FvgInfo:
    """Fair Value Gap detecte pres de l'AH ou de l'AL (reclaim ICT).

    Quand le prix DEPASSE l'AH (peu importe la duree) puis REVIENT
    en dessous, un FVG baissier peut se former. Quand le prix DEPASSE
    l'AL puis REVIENT au-dessus, un FVG haussier peut se former.
    """
    timeframe: str          # M1/M3/M5/M15
    direction: str          # "bearish" (pres AH) ou "bullish" (pres AL)
    zone_top: float         # Haut de la zone FVG
    zone_bottom: float      # Bas de la zone FVG
    gap_pct: float          # Taille du gap en %%
    gap_size: float         # Taille du gap en pips/points
    level_type: str         # "AH" ou "AL"
    level_price: float      # Valeur du niveau concerne
