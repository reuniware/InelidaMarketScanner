"""
Module d'analyse IA via CLI pour InelidaMarketScanner.
======================================================
Pilote un agent IA en CLI (via wexpect) pour obtenir des
analyses regulieres des donnees de marche ICT.

IMPORTANT : Une seule instance par machine.

Dependances : pip install wexpect
"""

import os
import re
import time
import logging
import subprocess
from datetime import datetime, timezone
from typing import Optional, Dict, List, Callable

logger = logging.getLogger("AIAnalyst")

UTC = timezone.utc

# ─── Configuration ──────────────────────────────────────────────────────────
AI_CLI_PATH = os.environ.get(
    "AI_CLI_PATH",
    "",
)

STARTUP_TIMEOUT = 60
RESPONSE_TIMEOUT = 300     # secondes max pour une réponse complète
IDLE_TIMEOUT = 15          # secondes sans output = réponse probablement terminée
SEND_DELAY = 3.0           # secondes d'attente après envoi avant de lire

# ─── Nettoyage des réponses ─────────────────────────────────────────────────
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
_AD_RE = re.compile(r'[│┃].*?(?:pub|ad|sponsor|advertisement).*?[│┃]\n?', re.IGNORECASE)
_AD_LINE_RE = re.compile(r'^.*?(?:pub|advertisement|sponsored).*?$', re.IGNORECASE | re.MULTILINE)
_CR_RE = re.compile(r'\r+')

# ─── Prompt formatteur ──────────────────────────────────────────────────────

def format_market_prompt(
    symbol: Optional[str] = None,
    asian_results: Optional[List[Dict]] = None,
    sweeps: Optional[List[Dict]] = None,
    levels: Optional[List[Dict]] = None,
    setups: Optional[List[Dict]] = None,
    account_info: Optional[Dict] = None,
) -> str:
    """Formate les données de marché en un prompt structuré pour l'IA.

    Returns:
        Texte du prompt en francais, pret a etre envoye a l'IA.
    """
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    lines = [
        f"=== ANALYSE DE MARCHE ICT - {now_str} UTC ===",
        "",
        "Tu es un analyste financier expert en ICT (Inner Circle Trader).",
        "Analyse les donnees ci-dessous et reponds en francais, de facon concise.",
        "PAS DE CODE. Analyse texte uniquement.",
        "",
    ]

    if symbol:
        lines.append(f"ACTIF PRINCIPAL : {symbol}")
        lines.append("")

    # ── Setups directionnels (les plus importants, en premier) ─────────
    if setups:
        active = [s for s in setups if s.get("trade_status") == "Active"
                  and s.get("trade_action") in ("BUY", "SELL")]
        waiting = [s for s in setups if s.get("trade_status") != "Active"]

        lines.append("--- SETUPS DIRECTIONNELS ---")
        if active:
            lines.append(f"TRADES ACTIFS ({len(active)}) :")
            for s in active:
                rr = f"RR={s['trade_rr1']:.1f}x" if s.get("trade_rr1") else "RR=?"
                lines.append(
                    f"  {s['symbol']}: {s['trade_action']} | "
                    f"Entry={s.get('trade_entry', '?')} | "
                    f"SL={s.get('trade_sl', '?')} | "
                    f"TP1={s.get('trade_tp1', '?')} | "
                    f"{rr} | Dir={s.get('direction_target_label', '?')}"
                )
        if waiting:
            lines.append(f"En attente ({len(waiting)}) :")
            for s in waiting[:10]:
                lines.append(
                    f"  {s['symbol']}: Dir={s.get('direction_target_label', '?')} | "
                    f"Status={s.get('trade_status', '?')}"
                )
        lines.append(f"Total setups : {len(setups)}")
        lines.append("")

    # ── Sessions asiatiques ───────────────────────────────────────────
    if asian_results:
        swept_any = [r for r in asian_results
                     if r.get("asian_high_swept") or r.get("asian_low_swept")]
        lines.append(f"--- SESSIONS ASIATIQUES ({len(asian_results)} symboles) ---")
        lines.append(f"Dont {len(swept_any)} avec sweep :")
        for r in swept_any[:25]:
            parts = []
            if r.get("asian_high_swept"):
                parts.append("AH SWEPT")
            if r.get("asian_low_swept"):
                parts.append("AL SWEPT")
            sweep_str = "+".join(parts) if parts else "-"
            fib = r.get("fib_label", "")
            lines.append(
                f"  {r['symbol']}: AH={r.get('asian_high', '?')} "
                f"AL={r.get('asian_low', '?')} Now={r.get('current_price', '?')} | "
                f"{sweep_str} | Fib={fib}"
            )
        lines.append("")

    # ── Sweeps BSL/SSL ────────────────────────────────────────────────
    if sweeps:
        lines.append(f"--- SWEEPS BSL/SSL M15 ({len(sweeps)} détectés) ---")
        for s in sweeps[:15]:
            label = s.get("sweep_label", s.get("label", "?"))
            dist = s.get("distance_pct", s.get("dist_pct", 0))
            lines.append(
                f"  {s['symbol']}: {label} Level={s.get('level', '?')} "
                f"Dist={dist:.3f}%"
            )
        lines.append("")

    # ── Niveaux daily/weekly ──────────────────────────────────────────
    if levels:
        lines.append(f"--- NIVEAUX DAILY/WEEKLY ({len(levels)} niveaux) ---")
        for l in levels[:20]:
            lt = l.get("level_type", l.get("type", "?"))
            lines.append(
                f"  {l['symbol']} ({lt}): H={l.get('level_high', '?')} "
                f"L={l.get('level_low', '?')} Now={l.get('current_price', '?')} | "
                f"{l.get('direction_target_label', '?')}"
            )
        lines.append("")

    # ── Contexte compte ───────────────────────────────────────────────
    if account_info:
        lines.append(f"--- COMPTE ---")
        lines.append(f"Balance={account_info.get('balance', '?')} "
                     f"{account_info.get('currency', '')}")
        lines.append("")

    # ── Questions ─────────────────────────────────────────────────────
    lines.extend([
        "QUESTION : Analyse ces donnees ICT et reponds en francais :",
        "1. Quels sont les 3 meilleurs setups directionnels et pourquoi ?",
        "2. Y a-t-il des contradictions (sweep des deux cotes, range trop serree) ?",
        "3. Trade prioritaire recommande avec justification SL/TP/RR.",
        "4. Les niveaux daily/weekly confirment-ils ou contredisent-ils les setups ?",
        "5. Conseil global pour la session London/NY a venir.",
        "",
        "Sois concis. Reponse en francais. Pas de code.",
    ])

    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# PILOTE IA CLI
# ═══════════════════════════════════════════════════════════════════════════════

class CLIAnalyst:
    """Pilote une session IA CLI pour analyser des donnees de marche.

    Utilise wexpect (PTY Windows) pour :
    1. Lancer l'agent IA dans le repertoire du projet
    2. Attendre le prompt
    3. Envoyer les donnees formatees
    4. Capturer et nettoyer la reponse
    5. Fermer proprement

    Usage :
        analyst = CLIAnalyst(project_dir=".")
        result = analyst.analyze(prompt_text)
        if result:
            print(result)
    """

    def __init__(self, project_dir: str = ".", verbose: bool = True,
                 on_progress: Optional[Callable[[str], None]] = None):
        self.project_dir = os.path.abspath(project_dir)
        self.verbose = verbose
        self.on_progress = on_progress  # callback(status: str) pour feedback live
        self._child = None
        self._start_time = 0.0

    # ─── Cycle de vie ──────────────────────────────────────────────────

    def _notify(self, msg: str) -> None:
        """Envoie une notification de progression si le callback est défini."""
        if self.on_progress:
            try:
                self.on_progress(msg)
            except Exception:
                pass

    def _spawn(self) -> bool:
        """Lance l'agent IA dans un pseudo-terminal."""
        if not AI_CLI_PATH:
            logger.warning("AI_CLI_PATH non defini - agent IA CLI non disponible")
            return False
        try:
            import wexpect
        except ImportError:
            logger.error("wexpect non installe -> pip install wexpect")
            return False

        try:
            self._child = wexpect.spawn(
                AI_CLI_PATH,
                ['--cwd', self.project_dir],
                timeout=STARTUP_TIMEOUT,
                encoding='utf-8',
                codec_errors='replace',
            )
            self._start_time = time.time()
            self._notify("Agent IA lance, attente prompt...")
            return True
        except FileNotFoundError:
            logger.error(
                "Agent IA introuvable : %s\n"
                "Verifie le chemin ou definit AI_CLI_PATH.",
                AI_CLI_PATH,
            )
            return False
        except Exception as e:
            logger.error("Erreur spawn agent IA : %s", e)
            return False

    def _wait_prompt(self, timeout: int = 15) -> bool:
        """Attend que l'agent IA soit pret (prompt affiche).

        Timeout court (15s) car si aucun pattern ne correspond,
        on tente d'envoyer le prompt quand meme.
        """
        import wexpect
        patterns = [
            r'> ',           # prompt standard
            r'\$ ',          # prompt bash
            r'>>>',          # prompt Python
            r'ready',        # message ready
            r'Ask me',       # message accueil
            r'What would',   # message accueil EN
            r'\]',           # prompt crochet
            r'type',         # "type something" ou similaire
            r'help',         # mention d'aide
            r'chat',         # mode chat
            r'\?',           # point d'interrogation
            wexpect.TIMEOUT,
        ]
        try:
            idx = self._child.expect(patterns, timeout=timeout)
            if idx == len(patterns) - 1:
                # Timeout : on capture ce que l'agent a affiche pour debug
                buf = self._child.before or ""
                preview = buf[-300:] if len(buf) > 300 else buf
                logger.warning(
                    "Prompt non detecte apres %ds. Buffer final: %s",
                    timeout, repr(preview),
                )
                self._notify("Prompt non detecte, envoi direct...")
                return True
            elapsed = time.time() - self._start_time
            logger.info("Agent IA pret (%.1fs)", elapsed)
            self._notify(f"Connecte (demarrage {elapsed:.0f}s)")
            return True
        except Exception as e:
            logger.error("Erreur attente prompt : %s", e)
            return True

    def _send(self, text: str) -> bool:
        """Envoie le prompt a l'agent IA."""
        # Nettoyer : pas de retours à la ligne dans le message
        clean = text.replace('\n', ' \\n ').replace('\r', '')
        try:
            self._child.sendline(clean)
            logger.info("Prompt envoyé (%d chars)", len(clean))
            self._notify(f"Prompt envoyé ({len(clean)} chars)")
            return True
        except Exception as e:
            logger.error("Erreur envoi : %s", e)
            return False

    def _read_response(self) -> str:
        """Lit la réponse jusqu'à idle timeout ou timeout max.

        Stratégie : on lit en continu. Si aucun nouvel output pendant
        IDLE_TIMEOUT secondes et qu'on a déjà du contenu → réponse terminée.
        Sinon, on attend RESPONSE_TIMEOUT max au total.
        """
        import wexpect
        chunks = []
        last_activity = time.time()
        start = time.time()

        while True:
            elapsed_total = time.time() - start
            elapsed_idle = time.time() - last_activity

            # Condition de sortie : idle trop long avec du contenu
            if elapsed_idle > IDLE_TIMEOUT and chunks:
                logger.info("Fin réponse (idle %.1fs)", elapsed_idle)
                break

            # Timeout max global
            if elapsed_total > RESPONSE_TIMEOUT:
                logger.warning("Timeout max atteint (%.0fs)", RESPONSE_TIMEOUT)
                break

            # Lecture avec timeout court
            try:
                idx = self._child.expect(
                    [r'.+', wexpect.TIMEOUT, wexpect.EOF],
                    timeout=min(3.0, max(0.5, RESPONSE_TIMEOUT - elapsed_total)),
                )
                if idx == 0:
                    chunk = self._child.after or ""
                    if chunk.strip():
                        chunks.append(chunk)
                        last_activity = time.time()
                elif idx == 2:  # EOF
                    logger.info("Fin réponse (EOF)")
                    break
            except wexpect.EOF:
                break
            except wexpect.TIMEOUT:
                continue
            except Exception as e:
                logger.debug("Lecture : %s", e)
                continue

        return ''.join(chunks)

    def _clean(self, text: str) -> str:
        """Nettoie la réponse : ANSI, pubs, retours chariot."""
        if not text:
            return ""
        text = _ANSI_RE.sub('', text)
        text = _AD_RE.sub('', text)
        text = _AD_LINE_RE.sub('', text)
        text = _CR_RE.sub('', text)
        # Supprimer les lignes vides multiples
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _shutdown(self):
        """Ferme proprement l'agent IA."""
        if self._child is None:
            return
        try:
            self._child.sendline('exit')
            time.sleep(2)
        except Exception:
            pass
        try:
            self._child.terminate()
        except Exception:
            pass
        self._child = None

    # ─── API publique ──────────────────────────────────────────────────

    def analyze(self, prompt: str) -> Optional[str]:
        """Envoie un prompt a l'agent IA et retourne l'analyse.

        Args:
            prompt: Texte formate (voir format_market_prompt).

        Returns:
            Analyse textuelle nettoyee, ou None si echec.
        """
        if not prompt or not prompt.strip():
            logger.error("Prompt vide.")
            return None

        if not self._spawn():
            return None

        try:
            if not self._wait_prompt():
                return None

            if not self._send(prompt):
                return None

            # Pause pour laisser l'agent IA commencer a repondre
            self._notify("Attente reponse IA...")
            time.sleep(SEND_DELAY)

            response = self._read_response()
            response = self._clean(response)

            elapsed = time.time() - self._start_time
            logger.info(
                "Analyse terminée en %.1fs (%d caractères)",
                elapsed, len(response),
            )
            elapsed = time.time() - self._start_time
            self._notify(f"Terminé ({elapsed:.0f}s, {len(response)} chars)")
            return response if response else "(réponse vide)"

        finally:
            self._shutdown()


# ─── Sauvegarde ──────────────────────────────────────────────────────────────

# ─── Nettoyage processus zombies ────────────────────────────────────────────

def kill_orphan_ai_cli() -> int:
    """Tue tout processus residuel d'une session IA CLI precedente.

    Sur Windows, un crash du script Python peut laisser un processus
    fantome qui bloque la prochaine analyse.

    En dernier recours, l'utilisateur peut lancer manuellement :
        taskkill /F /IM node.exe

    Returns:
        Nombre de processus tues.
    """
    killed = 0

    try:
        r = subprocess.run(
            ["taskkill", "/F", "/IM", "node.exe"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            killed += 1
            logger.info("Processus node.exe zombie tue.")
    except Exception:
        pass

    return killed


# ─── Prompt M5 temps réel ────────────────────────────────────────────────────

def format_m5_candle_prompt(
    symbol: str,
    candle: Dict,
    recent_candles: List[Dict] = None,
    asian_high: Optional[float] = None,
    asian_low: Optional[float] = None,
    asian_high_swept: bool = False,
    asian_low_swept: bool = False,
    pdh: Optional[float] = None,
    pdl: Optional[float] = None,
    current_direction: str = "-",
) -> str:
    """Formate un prompt ultra-concis pour une bougie M5.

    Args:
        symbol: Symbole tradé (ex: XAUUSD).
        candle: Dict {time, open, high, low, close, tick_volume}.
        recent_candles: 3-5 dernières bougies pour contexte.
        asian_high/low: Range asiatique du jour.
        asian_high/low_swept: Si AH/AL déjà sweepés.
        pdh/pdl: Previous Day High/Low.
        current_direction: Direction ICT actuelle.

    Returns:
        Prompt texte concis (français).
    """
    now_str = datetime.now(UTC).strftime("%H:%M")
    candle_time = datetime.fromtimestamp(candle["time"], UTC).strftime("%H:%M")

    lines = [
        f"[M5 {symbol} {candle_time}] "
        f"O={candle['open']:.5f} H={candle['high']:.5f} "
        f"L={candle['low']:.5f} C={candle['close']:.5f} "
        f"V={candle.get('tick_volume', 0)}",
    ]

    # Contexte : bougies précédentes
    if recent_candles:
        lines.append("Candles precedentes:")
        for c in recent_candles[-5:]:
            ct = datetime.fromtimestamp(c["time"], UTC).strftime("%H:%M")
            lines.append(
                f"  [{ct}] O={c['open']:.5f} H={c['high']:.5f} "
                f"L={c['low']:.5f} C={c['close']:.5f}"
            )

    # Niveaux clés
    lines.append("Niveaux:")
    if asian_high is not None and asian_low is not None:
        ah_tag = " (SWEPT)" if asian_high_swept else ""
        al_tag = " (SWEPT)" if asian_low_swept else ""
        lines.append(f"  Asian: AH={asian_high:.5f}{ah_tag} AL={asian_low:.5f}{al_tag}")
    if pdh is not None and pdl is not None:
        lines.append(f"  Daily: PDH={pdh:.5f} PDL={pdl:.5f}")
    lines.append(f"  Direction ICT: {current_direction}")

    # Question
    lines.append("")
    lines.append(
        "ANALYSE RAPIDE (3 lignes max, francais): "
        "1) Structure de la bougie (bull/bear/indecis/engulfing). "
        "2) Proximite sweep AH/AL ? "
        "3) Biais court terme (5-15 min). "
        "PAS D'OUTILS. PAS DE CODE. Une seule reponse texte."
    )

    return "\n".join(lines)


def save_analysis(analysis_text: str, output_dir: str = ".") -> str:
    """Sauvegarde l'analyse dans un fichier texte horodaté.

    Returns:
        Chemin absolu du fichier créé.
    """
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"ai_analysis_{ts}.txt"
    filepath = os.path.join(os.path.abspath(output_dir), filename)

    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"=== ANALYSE IA ===\n")
        f.write(f"Date UTC : {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Modele   : IA generique\n")
        f.write(f"{'=' * 60}\n\n")
        f.write(analysis_text)
        f.write(f"\n\n{'=' * 60}\n")
        f.write(f"Fin de l'analyse\n")

    logger.info("Analyse sauvegardée : %s", filepath)
    return filepath
