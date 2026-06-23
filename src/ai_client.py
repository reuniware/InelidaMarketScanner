"""
Client d'analyse IA via Google Gemini (gratuit) pour InelidaMarketScanner.
=========================================================================
Utilise l'API Gemini 2.0 Flash (1500 requetes/jour gratuites).
Simple, fiable, pas de PTY, pas de processus externes.

SDK : google-genai (nouveau, remplace google-generativeai deprecie)
Cle API : https://aistudio.google.com/apikey
"""

import logging
from typing import Optional

logger = logging.getLogger("GeminiAnalyst")

# Modele par defaut (gratuit, 1500 req/jour)
DEFAULT_MODEL = "gemini-2.0-flash"

# Instructions systeme pour l'analyse de marche ICT
SYSTEM_INSTRUCTION = (
    "Tu es un analyste financier expert en ICT (Inner Circle Trader). "
    "Tu analyses des donnees de marche forex/metaux/indices en francais. "
    "Reponds de facon concise, structuree, et directe. "
    "Donne des signaux clairs (BUY/SELL) avec SL/TP/RR quand pertinent. "
    "PAS DE CODE. Analyse texte uniquement. "
    "Format attendu : direction, niveaux cles, biais court terme, risque."
)


class GeminiAnalyst:
    """Analyse de marche via l'API Google Gemini (gratuite)."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.model_name = model
        self._client = None

    # ─── Initialisation lazy ────────────────────────────────────────────

    def _ensure_client(self) -> bool:
        """Initialise le client Gemini (appele au premier analyze)."""
        if self._client is not None:
            return True

        try:
            from google import genai
        except ImportError:
            logger.error(
                "google-genai non installe → pip install google-genai"
            )
            return False

        try:
            self._client = genai.Client(api_key=self.api_key)
            logger.info("Gemini initialise (modele: %s)", self.model_name)
            return True
        except Exception as e:
            logger.error("Erreur initialisation Gemini : %s", e)
            return False

    # ─── Analyse ────────────────────────────────────────────────────────

    def analyze(self, prompt: str, max_output_tokens: int = 800) -> Optional[str]:
        """Envoie un prompt a Gemini et retourne l'analyse.

        Args:
            prompt: Texte formate avec les donnees de marche.
            max_output_tokens: Limite de tokens pour la reponse (defaut 800).

        Returns:
            Analyse textuelle, ou None si echec.
        """
        if not prompt or not prompt.strip():
            logger.error("Prompt vide.")
            return None

        if not self._ensure_client():
            return None

        try:
            from google.genai import types

            response = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.3,
                    max_output_tokens=max_output_tokens,
                    top_p=0.95,
                ),
            )

            # Extraire le texte de facon securisee
            try:
                text = response.text
                return text.strip() if text else None
            except (AttributeError, ValueError) as e:
                logger.debug("Structure reponse inattendue : %s", e)

            # Verifier si bloque par securite
            try:
                if (response.prompt_feedback
                        and response.prompt_feedback.block_reason):
                    logger.warning(
                        "Reponse bloquee (securite) : %s",
                        response.prompt_feedback.block_reason,
                    )
                    return "(bloque par le filtre de securite)"
            except AttributeError:
                pass

            return None

        except Exception as e:
            err_msg = str(e)
            if "CONSUMER_SUSPENDED" in err_msg.upper():
                logger.error(
                    "Cle API Gemini SUSPENDUE. "
                    "Cree une nouvelle cle sur https://aistudio.google.com/apikey "
                    "et mets-la dans le fichier .env (jamais dans le code)."
                )
            elif "PERMISSION_DENIED" in err_msg.upper() or "403" in err_msg:
                logger.error(
                    "Acces refuse Gemini (403). Verifie ta cle API dans le .env."
                )
            elif "429" in err_msg:
                logger.error(
                    "Quota Gemini depasse (429). Limite : 1500 requetes/jour."
                )
            else:
                logger.error("Erreur appel Gemini : %s", e)
            return None
