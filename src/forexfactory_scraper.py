"""
ForexFactory Scraper — Récupération du calendrier économique avec cache JSON + fallback.

Stratégie hybride :
  1. Tente de scraper forexfactory.com (HTML + XML feed)
  2. Si succès → sauvegarde en cache JSON (ttl 24h)
  3. Si échec (site bloqué, Cloudflare, timeout) → fallback MAJOR_EVENTS hardcodé
  4. Les événements "rouge" (red) sont classés comme majeurs

Usage:
    from src.forexfactory_scraper import get_events_for_date
    events = get_events_for_date("2026-07-20")  # ["FOMC: FOMC Statement", ...]
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger("ForexFactoryScraper")

UTC = timezone.utc

# ── Cache config ───────────────────────────────────────────────────────────
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_CACHE_FILE = os.path.join(_CACHE_DIR, "forexfactory_cache.json")
_CACHE_TTL = 86400  # 24h en secondes

# ── Fallback: les événements du module news_calendar ──────────────────────
from src.news_calendar import MAJOR_EVENTS as _FALLBACK_EVENTS


# ── Mapping impact ForexFactory → niveau ──────────────────────────────────
# ForexFactory utilise des classes CSS: .red, .orange, .yellow
_IMPACT_MAJOR = {"red", "orange"}  # Rouge = fort impact, Orange = moyen
_IMPACT_MINOR = {"yellow", "green"}  # Jaune/vert = faible


def _ensure_cache_dir():
    """Crée le répertoire de cache si nécessaire."""
    os.makedirs(_CACHE_DIR, exist_ok=True)


def _load_cache() -> dict:
    """Charge le cache JSON. Retourne {} si absent ou expiré."""
    _ensure_cache_dir()
    if not os.path.isfile(_CACHE_FILE):
        return {}
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Vérifier TTL
        cached_at = data.get("_cached_at", 0)
        if time.time() - cached_at > _CACHE_TTL:
            logger.debug("Cache ForexFactory expiré (TTL %ds)", _CACHE_TTL)
            return {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Erreur lecture cache ForexFactory: %s", e)
        return {}


def _save_cache(data: dict):
    """Sauvegarde le cache JSON avec timestamp."""
    _ensure_cache_dir()
    data["_cached_at"] = time.time()
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("Cache ForexFactory sauvegardé: %s", _CACHE_FILE)
    except OSError as e:
        logger.warning("Impossible d'écrire le cache: %s", e)


def _scrape_forexfactory() -> Optional[dict]:
    """Tente de scraper le calendrier ForexFactory via le flux XML et HTML.

    Returns:
        Dict {date_str: [event, ...]} ou None si échec.
    """
    events_by_date = {}

    # ── Méthode 1 : RSS/XML feed ──
    try:
        import requests
        from xml.etree import ElementTree

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/xml, text/xml, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # Tentative flux XML (plus stable que le HTML)
        xml_urls = [
            "https://www.forexfactory.com/ff_calendar_thisweek.xml",
            "https://nfs.faireconomy.media/ff_calendar_thisweek.xml",
        ]

        for xml_url in xml_urls:
            try:
                resp = requests.get(xml_url, headers=headers, timeout=10)
                if resp.status_code == 200 and resp.text.strip().startswith("<"):
                    root = ElementTree.fromstring(resp.content)
                    # Le flux XML a une structure plate d'événements
                    for event_elem in root.iter("event"):
                        date_str = _parse_xml_date(event_elem)
                        impact = (event_elem.findtext("impact", "") or "").strip().lower()
                        currency = (event_elem.findtext("currency", "") or "").strip()
                        title = (event_elem.findtext("title", "") or "").strip()
                        if date_str and title and impact in _IMPACT_MAJOR:
                            label = f"{currency}: {title}" if currency else title
                            events_by_date.setdefault(date_str, []).append(label)

                    if events_by_date:
                        logger.info("ForexFactory XML: %d dates avec événements", len(events_by_date))
                        return events_by_date
            except Exception as e:
                logger.debug("Échec flux XML %s: %s", xml_url, e)
                continue

    except ImportError:
        logger.debug("requests non installé — impossible de scraper ForexFactory")
    except Exception as e:
        logger.debug("Erreur scraping ForexFactory XML: %s", e)

    # ── Méthode 2 : HTML scraping (fallback si XML échoue) ──
    try:
        import requests
        from bs4 import BeautifulSoup

        html_url = "https://www.forexfactory.com/calendar"
        resp = requests.get(html_url, headers=headers, timeout=10)

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("tr.calendar__row")
            current_date = None

            for row in rows:
                # Détecter le séparateur de date
                date_header = row.select_one("td.calendar__date")
                if date_header:
                    date_text = date_header.get_text(strip=True)
                    parsed = _parse_ff_date(date_text)
                    if parsed:
                        current_date = parsed

                if not current_date:
                    continue

                # Impact
                impact_span = row.select_one("span.impact")
                impact = ""
                if impact_span:
                    for cls in impact_span.get("class", []):
                        if cls in _IMPACT_MAJOR:
                            impact = cls
                            break

                # Devise + titre
                currency = row.select_one("td.currency")
                event = row.select_one("td.event")
                currency_text = currency.get_text(strip=True) if currency else ""
                event_text = event.get_text(strip=True) if event else ""

                if impact in _IMPACT_MAJOR and event_text:
                    label = f"{currency_text}: {event_text}" if currency_text else event_text
                    events_by_date.setdefault(current_date, []).append(label)

            if events_by_date:
                logger.info("ForexFactory HTML: %d dates avec événements", len(events_by_date))
                return events_by_date

    except ImportError:
        logger.debug("BeautifulSoup non installé — impossible de scraper HTML")
    except Exception as e:
        logger.debug("Erreur scraping ForexFactory HTML: %s", e)

    return None


def _parse_xml_date(event_elem) -> Optional[str]:
    """Parse la date depuis un élément XML d'événement."""
    try:
        # Le flux XML a souvent un timestamp Unix
        ts = event_elem.findtext("timestamp", "")
        if ts:
            dt = datetime.fromtimestamp(int(ts), tz=UTC)
            return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    return None


def _parse_ff_date(date_text: str) -> Optional[str]:
    """Parse une date au format ForexFactory (ex: 'Jul 20' ou 'Jul 20, 2026')."""
    try:
        date_text = date_text.strip()
        if not date_text:
            return None
        # Ajouter l'année si non présente
        if "," not in date_text:
            date_text += f", {datetime.now(UTC).year}"
        dt = datetime.strptime(date_text, "%b %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return None


def get_events_for_date(date_str: Optional[str] = None) -> List[str]:
    """Retourne les événements majeurs pour une date donnée.

    Stratégie :
      1. Vérifier le cache JSON (TTL 24h)
      2. Si absent → scraper ForexFactory
      3. Si échec → fallback MAJOR_EVENTS hardcodé
      4. Sauvegarder le cache pour les prochains appels

    Args:
        date_str: Date "YYYY-MM-DD". Si None, utilise aujourd'hui UTC.

    Returns:
        Liste de chaînes décrivant les événements majeurs.
    """
    if date_str is None:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")

    # 1) Vérifier le cache
    cache = _load_cache()
    if date_str in cache:
        logger.debug("Cache hit pour %s: %d événements", date_str, len(cache[date_str]))
        return cache[date_str]

    # 2) Essayer de scraper
    scraped = _scrape_forexfactory()
    if scraped:
        # Fusionner avec le cache existant pour ne pas perdre les dates déjà cachées
        cache.update(scraped)
        # Sauvegarder même si la date n'a pas d'événements (weekend)
        cache.setdefault(date_str, [])
        _save_cache(cache)
        return cache[date_str]

    # 3) Fallback MAJOR_EVENTS hardcodé
    fallback = _FALLBACK_EVENTS.get(date_str, [])
    if fallback:
        logger.info("Fallback MAJOR_EVENTS pour %s: %d événements", date_str, len(fallback))
    else:
        logger.debug("Aucun événement pour %s (scraper indisponible + fallback vide)", date_str)
    # Mettre en cache même vide pour éviter de rescraper inutilement
    cache[date_str] = fallback
    _save_cache(cache)

    return fallback


def get_news_count(date_str: Optional[str] = None) -> int:
    """Retourne le nombre d'événements majeurs pour une date."""
    return len(get_events_for_date(date_str))


def is_high_news_day(date_str: Optional[str] = None) -> bool:
    """Retourne True si ≥2 événements majeurs (HIGH NEWS DAY)."""
    return get_news_count(date_str) >= 2
