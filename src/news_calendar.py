"""
News Risk Filter — Calendrier macro pour le Diamond Scanner.

Détecte les jours à risque où ≥2 événements macro majeurs sont programmés,
ce qui peut casser la corrélation DXY↔Forex et rendre les setups directionnels
non fiables (risque de range / double sweep).

Basé sur l'analyse du 17/07/2026 : 4 événements majeurs (Trump, FOMC Jefferson,
EUR CPI, UoM Sentiment) → 50% d'heures ANORMALES DXY↔EURUSD → range.

Usage:
    from src.news_calendar import get_news_risk
    count, warning_msg, is_high_risk = get_news_risk()
    if is_high_risk:
        print(warning_msg)  # "HIGH NEWS DAY — X événements majeurs: Trump, CPI, ..."
"""

from datetime import datetime, timezone
from typing import Tuple

UTC = timezone.utc

# ── Événements macro majeurs 2026 ──
# Format: "YYYY-MM-DD": ["CATEGORIE: Description", ...]
# Catégories considérées majeures pour le risque de range:
#   TRUMP  - Discours de Trump (volatilité USD + risk sentiment)
#   FOMC   - Décision taux / Minutes / Discours membres
#   CPI    - Inflation (USD ou EUR)
#   NFP    - Employment US
#   GDP    - Croissance
#   UOM    - Consumer Sentiment (si < 55 = flight to safety)
#   RETAIL - Retail Sales US
#   PMI    - PMI flash (manufacturing + services)

MAJOR_EVENTS = {
    # ── Juillet 2026 ──
    "2026-07-01": [],
    "2026-07-02": ["NFP: US Employment Report"],
    "2026-07-03": [],
    "2026-07-06": [],
    "2026-07-07": [],
    "2026-07-08": [],
    "2026-07-09": [],
    "2026-07-10": [],
    "2026-07-13": [],
    "2026-07-14": ["CPI: US CPI m/m"],
    "2026-07-15": ["RETAIL: US Retail Sales m/m"],
    "2026-07-16": [
        "FOMC: FOMC Member Musalem Speaks",
        "GDP: GBP GDP m/m",
        "RETAIL: US Core Retail Sales m/m",
        "UOM: US Philly Fed + Unemployment Claims",
    ],
    "2026-07-17": [
        "TRUMP: President Trump Speaks",
        "FOMC: FOMC Member Jefferson Speaks",
        "CPI: EUR Final CPI y/y",
        "UOM: Prelim UoM Consumer Sentiment",
        "GDP: USD Housing Starts + Building Permits",
        "GDP: USD Industrial Production m/m",
    ],
    "2026-07-20": [],
    "2026-07-21": [],
    "2026-07-22": [],
    "2026-07-23": [],
    "2026-07-24": [],
    "2026-07-27": [],
    "2026-07-28": [],
    "2026-07-29": ["FOMC: FOMC Statement + Federal Funds Rate"],
    "2026-07-30": ["GDP: US Advance GDP q/q"],
    "2026-07-31": [],

    # ── Août 2026 ── (à compléter)
    "2026-08-03": [],
    "2026-08-05": [],
    "2026-08-07": ["NFP: US Employment Report"],
    "2026-08-12": ["CPI: US CPI m/m"],
    "2026-08-14": ["RETAIL: US Retail Sales m/m"],
    "2026-08-19": ["FOMC: FOMC Meeting Minutes"],
    "2026-08-21": [],
    "2026-08-26": [],
    "2026-08-28": ["UOM: US Consumer Sentiment Final"],
    "2026-08-31": [],

    # ── Septembre 2026 ──
    "2026-09-04": ["NFP: US Employment Report"],
    "2026-09-11": ["CPI: US CPI m/m"],
    "2026-09-16": ["RETAIL: US Retail Sales m/m"],
    "2026-09-17": ["FOMC: FOMC Statement + Federal Funds Rate"],
    "2026-09-18": [],
    "2026-09-25": ["UOM: US Consumer Sentiment Final"],
    "2026-09-30": ["GDP: US Final GDP q/q"],

    # ── Octobre 2026 ──
    "2026-10-02": ["NFP: US Employment Report"],
    "2026-10-07": ["FOMC: FOMC Meeting Minutes"],
    "2026-10-13": [],
    "2026-10-14": ["CPI: US CPI m/m"],
    "2026-10-16": ["RETAIL: US Retail Sales m/m"],
    "2026-10-23": ["UOM: US Consumer Sentiment Final"],
    "2026-10-29": ["GDP: US Advance GDP q/q"],
    "2026-10-30": [],

    # ── Novembre 2026 ──
    "2026-11-05": ["FOMC: FOMC Statement + Federal Funds Rate"],
    "2026-11-06": ["NFP: US Employment Report"],
    "2026-11-11": ["CPI: US CPI m/m"],
    "2026-11-17": ["RETAIL: US Retail Sales m/m"],
    "2026-11-18": [],
    "2026-11-25": ["GDP: US Second GDP q/q", "UOM: US Consumer Sentiment Final"],
    "2026-11-26": ["FOMC: FOMC Meeting Minutes"],

    # ── Décembre 2026 ──
    "2026-12-04": ["NFP: US Employment Report"],
    "2026-12-10": ["CPI: US CPI m/m"],
    "2026-12-11": [],
    "2026-12-15": ["RETAIL: US Retail Sales m/m"],
    "2026-12-16": ["FOMC: FOMC Statement + Federal Funds Rate"],
    "2026-12-18": ["UOM: US Consumer Sentiment Final"],
    "2026-12-22": ["GDP: US Final GDP q/q"],
    "2026-12-25": [],  # Christmas
    "2026-12-31": [],
}

# Catégories considérées comme "majeures" (toutes les catégories listées)
# Chaque événement de la liste compte pour 1 dans le décompte
# Si ≥2 événements majeurs → HIGH NEWS DAY


def get_news_risk(date_str: str = None) -> Tuple[int, str, bool]:
    """Calcule le niveau de risque macro pour une date donnée.

    Args:
        date_str: Date au format "YYYY-MM-DD". Si None, utilise aujourd'hui UTC.

    Returns:
        (count, warning_msg, is_high_risk)
        - count: nombre d'événements majeurs aujourd'hui
        - warning_msg: message d'avertissement ou chaîne vide
        - is_high_risk: True si ≥2 événements majeurs (HIGH NEWS DAY)
    """
    if date_str is None:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")

    events = MAJOR_EVENTS.get(date_str, [])
    count = len(events)

    if count >= 2:
        # Formater la liste des événements pour le warning
        event_list = ", ".join(e.split(": ", 1)[0] for e in events)
        warning_msg = (
            f"HIGH NEWS DAY — {count} evenements majeurs: {event_list} — "
            f"correlation DXY/Forex risque d'etre ANORMALE, setups directionnels non fiables"
        )
        return count, warning_msg, True

    if count == 1:
        warning_msg = f"NEWS: {events[0]} — volatilite possible, confirmer les setups"
        return count, warning_msg, False

    return 0, "", False


def get_events_for_date(date_str: str = None) -> list:
    """Retourne la liste des événements pour une date donnée."""
    if date_str is None:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    return MAJOR_EVENTS.get(date_str, [])
