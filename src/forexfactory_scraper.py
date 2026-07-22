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
import re
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger("ForexFactoryScraper")

UTC = timezone.utc

# ── Cache config ───────────────────────────────────────────────────────────
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_CACHE_FILE = os.path.join(_CACHE_DIR, "forexfactory_cache.json")
_CACHE_TTL = 86400  # 24h en secondes
_RETRY_DELAY = 5  # secondes entre tentatives de rescrape

# ── Fallback: les événements du module news_calendar ──────────────────────
from src.news_calendar import MAJOR_EVENTS as _FALLBACK_EVENTS


# ── Mapping impact ForexFactory → niveau ──────────────────────────────────
# ForexFactory utilise des classes CSS: .red, .orange, .yellow
# Le flux XML peut utiliser: "High", "Medium", "Low" (texte) ou "3", "2", "1" (niveaux)
_IMPACT_MAJOR = {"red", "orange", "high", "medium", "3", "2"}
_IMPACT_MINOR = {"yellow", "green", "low", "1"}


def _ensure_cache_dir():
    """Crée le répertoire de cache si nécessaire."""
    os.makedirs(_CACHE_DIR, exist_ok=True)


def _safe_str(val, default=""):
    """Convertit une valeur en string, en évitant les erreurs d'encodage."""
    if val is None:
        return default
    try:
        return str(val).strip()
    except Exception:
        return default


def _load_cache() -> dict:
    """Charge le cache JSON. Retourne {} si absent ou expiré."""
    _ensure_cache_dir()
    if not os.path.isfile(_CACHE_FILE):
        return {}
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
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


def _make_headers(accept_xml: bool = False) -> dict:
    """Headers HTTP réalistes pour éviter le blocage."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "application/xml, text/xml, */*"
            if accept_xml
            else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


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

        headers = _make_headers(accept_xml=True)

        # Tentative flux XML (plus stable que le HTML)
        xml_urls = [
            "https://nfs.faireconomy.media/ff_calendar_thisweek.xml",
            "https://www.forexfactory.com/ff_calendar_thisweek.xml",
        ]

        for xml_url in xml_urls:
            try:
                resp = requests.get(xml_url, headers=headers, timeout=15)

                # Gérer rate limiting (429) avec retry
                if resp.status_code == 429:
                    logger.debug("Rate limit sur %s, attente %ds...", xml_url, _RETRY_DELAY)
                    time.sleep(_RETRY_DELAY)
                    resp = requests.get(xml_url, headers=headers, timeout=15)

                if resp.status_code == 200 and resp.text.strip().startswith("<"):
                    root = ElementTree.fromstring(resp.content)

                    # Essayer plusieurs structures XML possibles
                    # Structure 1: <event> plat (format original FF)
                    # Structure 2: <events><event>... namespace
                    # Structure 3: <channel><item>... (RSS)
                    events_found = []

                    # Parcourir récursivement tous les éléments pertinents
                    for event_elem in root.iter():
                        tag = _get_local_tag(event_elem)
                        if tag not in ("event", "item"):
                            continue

                        date_str = _parse_xml_date_v2(event_elem)
                        impact = _get_xml_impact(event_elem)
                        currency = _safe_str(event_elem.findtext("currency", ""))
                        title = _safe_str(event_elem.findtext("title", ""))

                        # Essayer aussi les attributs alternatifs
                        if not title:
                            title = _safe_str(event_elem.findtext("event", ""))
                        if not title:
                            title = _safe_str(event_elem.findtext("description", ""))

                        if date_str and title and impact in _IMPACT_MAJOR:
                            label = f"{currency}: {title}" if currency else title
                            events_by_date.setdefault(date_str, []).append(label)
                            events_found.append(label)

                    if events_found:
                        logger.info(
                            "ForexFactory XML (%s): %d dates, %d evenements",
                            xml_url.split("/")[2],
                            len(events_by_date),
                            len(events_found),
                        )
                        return events_by_date

                    # Si on a reçu le XML mais que rien n'a été parsé,
                    # log un extrait pour debug
                    logger.debug(
                        "XML parsé mais 0 events majeurs — extrait: %s",
                        resp.text[:500],
                    )

            except requests.exceptions.RequestException as e:
                logger.debug("Echec requete XML %s: %s", xml_url, e)
                continue
            except ElementTree.ParseError as e:
                logger.debug("Echec parsing XML %s: %s", xml_url, e)
                continue

    except ImportError:
        logger.debug("requests non installe — impossible de scraper ForexFactory")
    except Exception as e:
        logger.debug("Erreur scraping ForexFactory XML: %s", e)

    # ── Méthode 2 : HTML scraping (fallback si XML echoue) ──
    try:
        import requests
        from bs4 import BeautifulSoup

        headers = _make_headers(accept_xml=False)
        html_url = "https://www.forexfactory.com/calendar"
        resp = requests.get(html_url, headers=headers, timeout=15)

        if resp.status_code == 429:
            logger.debug("Rate limit sur HTML, attente %ds...", _RETRY_DELAY)
            time.sleep(_RETRY_DELAY)
            resp = requests.get(html_url, headers=headers, timeout=15)

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # Essayer plusieurs sélecteurs CSS (le site change souvent)
            selectors = [
                "tr.calendar__row",
                "tr.calendar_row",
                "tr[class*=row]",
                ".calendar__row",
                ".calendar_row",
            ]
            rows = []
            for sel in selectors:
                rows = soup.select(sel)
                if rows:
                    logger.debug("Selecteur HTML fonctionne: %s", sel)
                    break

            current_date = None

            for row in rows:
                # Détecter le séparateur de date
                date_headers = [
                    row.select_one("td.calendar__date"),
                    row.select_one("td.calendar_date"),
                    row.select_one("th.calendar__date"),
                    row.select_one("td[class*=date]"),
                ]
                date_header = next((dh for dh in date_headers if dh), None)

                if date_header:
                    date_text = date_header.get_text(strip=True)
                    parsed = _parse_ff_date(date_text)
                    if parsed:
                        current_date = parsed

                if not current_date:
                    continue

                # Impact — essayer plusieurs sélecteurs
                impact_span = (
                    row.select_one("span.impact")
                    or row.select_one("td.impact")
                    or row.select_one("td[class*=impact]")
                )
                impact = ""
                if impact_span:
                    classes = impact_span.get("class", [])
                    # Vérifier chaque classe
                    for cls in classes:
                        cls_lower = cls.lower()
                        if cls_lower in _IMPACT_MAJOR:
                            impact = cls_lower
                            break
                    # Fallback: chercher le mot "red" ou "orange" dans le texte
                    if not impact:
                        impact_text = impact_span.get_text(strip=True).lower()
                        for imp in _IMPACT_MAJOR:
                            if imp in impact_text:
                                impact = imp
                                break

                # Devise + titre
                currency = row.select_one("td.currency") or row.select_one("td[class*=currency]")
                event = row.select_one("td.event") or row.select_one("td[class*=event]")
                currency_text = _safe_str(currency.get_text(strip=True)) if currency else ""
                event_text = _safe_str(event.get_text(strip=True)) if event else ""

                if impact in _IMPACT_MAJOR and event_text:
                    label = f"{currency_text}: {event_text}" if currency_text else event_text
                    events_by_date.setdefault(current_date, []).append(label)

            if events_by_date:
                logger.info(
                    "ForexFactory HTML: %d dates avec evenements", len(events_by_date)
                )
                return events_by_date

    except ImportError:
        logger.debug("BeautifulSoup non installe — impossible de scraper HTML")
    except Exception as e:
        logger.debug("Erreur scraping ForexFactory HTML: %s", e)

    return None


def _get_local_tag(elem) -> str:
    """Extrait le nom de la balise sans namespace."""
    tag = elem.tag
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _get_xml_impact(event_elem) -> str:
    """Extrait l'impact d'un événement XML en essayant plusieurs formats."""
    # Format 1: <impact>red</impact>
    impact = _safe_str(event_elem.findtext("impact", ""), "").lower()
    if impact in _IMPACT_MAJOR or impact in _IMPACT_MINOR:
        return impact

    # Format 2: attribut impact="red"
    impact = _safe_str(event_elem.get("impact", ""), "").lower()
    if impact in _IMPACT_MAJOR or impact in _IMPACT_MINOR:
        return impact

    # Format 3: <importance>3</importance>
    importance = _safe_str(event_elem.findtext("importance", ""), "").lower()
    if importance in _IMPACT_MAJOR:
        return importance

    # Format 4: chercher dans le texte complet de l'événement
    full_text = _safe_str(event_elem.text) + " " + " ".join(
        _safe_str(child.text, "") for child in event_elem
    )
    full_text_lower = full_text.lower()
    if any(imp in full_text_lower for imp in ("high", "red", "orange")):
        return "red"

    return impact


def _parse_xml_date_v2(event_elem) -> Optional[str]:
    """Parse la date depuis un élément XML en essayant plusieurs formats."""
    # Format 1: timestamp Unix
    for field in ("timestamp", "date", "time", "epoch"):
        ts = _safe_str(event_elem.findtext(field, ""))
        if ts and ts.isdigit():
            try:
                dt = datetime.fromtimestamp(int(ts), tz=UTC)
                return dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError, OSError):
                pass

    # Format 2: attribut timestamp
    ts = _safe_str(event_elem.get("timestamp", ""))
    if ts and ts.isdigit():
        try:
            dt = datetime.fromtimestamp(int(ts), tz=UTC)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError, OSError):
            pass

    # Format 3: date formatée
    date_text = _safe_str(event_elem.findtext("date", ""))
    if date_text:
        parsed = _parse_ff_date(date_text)
        if parsed:
            return parsed

    # Format 4: <event> qui contient la date dans le titre
    title = _safe_str(event_elem.findtext("title", ""))
    if title:
        # Cherche un pattern de date comme "Jul 20" ou "2026-07-20"
        match = re.search(r"(\w{3}\s+\d{1,2})", title)
        if match:
            parsed = _parse_ff_date(match.group(1))
            if parsed:
                return parsed

    return None


def _parse_ff_date(date_text: str) -> Optional[str]:
    """Parse une date au format ForexFactory (ex: 'Jul 20' ou 'Jul 20, 2026')."""
    try:
        date_text = date_text.strip()
        if not date_text:
            return None
        # Si date déjà format YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_text):
            return date_text
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
      3. Si echec → fallback MAJOR_EVENTS hardcodé
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
        logger.debug(
            "Cache hit pour %s: %d evenements", date_str, len(cache[date_str])
        )
        return cache[date_str]

    # 2) Essayer de scraper
    scraped = _scrape_forexfactory()
    if scraped:
        cache.update(scraped)
        cache.setdefault(date_str, [])
        _save_cache(cache)
        return cache[date_str]

    # 3) Fallback MAJOR_EVENTS hardcodé
    fallback = _FALLBACK_EVENTS.get(date_str, [])
    if fallback:
        logger.info(
            "Fallback MAJOR_EVENTS pour %s: %d evenements", date_str, len(fallback)
        )
    else:
        logger.debug(
            "Aucun evenement pour %s (scraper indisponible + fallback vide)", date_str
        )
    # Mettre en cache même vide pour éviter de rescraper inutilement
    cache[date_str] = fallback
    _save_cache(cache)

    return fallback


def get_news_count(date_str: Optional[str] = None) -> int:
    """Retourne le nombre d'événements majeurs pour une date."""
    return len(get_events_for_date(date_str))


def is_high_news_day(date_str: Optional[str] = None) -> bool:
    """Retourne True si >=2 evenements majeurs (HIGH NEWS DAY)."""
    return get_news_count(date_str) >= 2
