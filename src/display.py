"""
Affichage console pour le scanner de marché.
Affiche un tabeleau soigné pour la watchlist, avec couleurs ANSI et
rafraichissement en place. Sans dépendance externe (pas de rich) pour rester leger.
"""

import os
import re
import sys
import time
import shutil
from typing import Dict, List

from .market_scanner import MarketScanner, TickSnapshot
from .sweep_detector import SweepEvent, AsianRangeResult


def _pad_cell(text: str, width: int, align: str = ">") -> str:
    """Pad a string containing ANSI codes to a given VISIBLE width.

    Les codes ANSI sont invisibles dans le terminal mais comptent comme des
    octets dans le padding `:>N` de Python, ce qui désaligne les colonnes
    quand les codes ont des longueurs différentes (\033[31m = 5 octets,
    \033[2m = 4 octets). Cette fonction calcule le padding sur la LARGEUR
    VISIBLE uniquement.
    """
    visible = re.sub(r"\033\[[0-9;]*[a-zA-Z]", "", text)
    pad = width - len(visible)
    if pad <= 0:
        return text
    if align == ">":
        return " " * pad + text
    if align == "<":
        return text + " " * pad
    return text


# Force l'encodage UTF-8 sur stdout/stderr pour eviter les UnicodeEncodeError
# sur les consoles Windows cp1252 (cmd, Git Bash, ancien powershell).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Couleurs ANSI (désactivées si pas un tty)
_IS_TTY = sys.stdout.isatty()
def _c(code: str) -> str:
    return code if _IS_TTY else ""

RESET = _c("\033[0m")
BOLD = _c("\033[1m")
DIM = _c("\033[2m")
RED = _c("\033[31m")
GREEN = _c("\033[32m")
YELLOW = _c("\033[33m")
BLUE = _c("\033[34m")
MAGENTA = _c("\033[35m")
CYAN = _c("\033[36m")
GRAY = _c("\033[90m")


def _supports_clear() -> bool:
    """Détecte si on peut faire un clear screen portable."""
    return os.name == "nt" or shutil.which("clear") is not None


def _clear():
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")


def _fmt_price(price: float) -> str:
    """Adapte la précision selon la valeur affichée."""
    if price >= 1000:
        return f"{price:.2f}"
    if price >= 10:
        return f"{price:.4f}"
    return f"{price:.5f}"


def _fmt_delta(delta: float, pct: float) -> str:
    """Formate un delta avec sa couleur (vert hausse, rouge baisse)."""
    if delta > 0:
        return f"{GREEN}▲ {delta:+.5f} ({pct:+.3f}%){RESET}"
    if delta < 0:
        return f"{RED}▼ {delta:+.5f} ({pct:+.3f}%){RESET}"
    return f"{GRAY}─ 0.00000 (+0.000%){RESET}"


def _fmt_spread(spread_pts: float) -> str:
    """Couleur du spread selon la valeur."""
    if spread_pts <= 10:
        return f"{GREEN}{spread_pts:6.1f}{RESET}"
    if spread_pts <= 25:
        return f"{YELLOW}{spread_pts:6.1f}{RESET}"
    return f"{RED}{spread_pts:6.1f}{RESET}"


def render_snapshot(
    scanner: MarketScanner,
    snapshot: Dict[str, TickSnapshot],
    show_header: bool = True,
) -> str:
    """Construit le rendu texte d'un snapshot de la watchlist."""
    lines: List[str] = []

    if show_header:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"{BOLD}{CYAN}╔══ InelidaMarketScanner ══╗{RESET}")
        lines.append(f"  {GRAY}Watchlist:{RESET} {len(scanner.symbols)} symboles  |  "
                     f"{GRAY}Rafraichissement:{RESET} ≥ {scanner.symbols and 500} ms  |  "
                     f"{GRAY}Heure UTC:{RESET} {now}")
        lines.append("")

    if not snapshot:
        lines.append(f"{YELLOW}Aucun tick reçu pour la watchlist.{RESET}")
        return "\n".join(lines)

    sym_w = max(10, max(len(s) for s in snapshot.keys()))
    header = (
        f"{BOLD}{'Symbole':<{sym_w}}  {'Bid':>12}  {'Ask':>12}  "
        f"{'Last':>12}  {'Spread(pts)':>11}  {'Δ Bid':>20}  {'Dernière MAJ':>19}{RESET}"
    )
    lines.append(header)
    lines.append(f"{GRAY}{'-' * (len(header) - len(BOLD) - len(RESET) - 0)}{RESET}")

    for sym in sorted(snapshot.keys()):
        s = snapshot[sym]
        deltas = _fmt_delta(s.bid_delta, s.bid_pct)
        last_update = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.gmtime(s.time)
        )
        lines.append(
            f"{MAGENTA}{sym:<{sym_w}}{RESET}  "
            f"{_fmt_price(s.bid):>12}  {_fmt_price(s.ask):>12}  "
            f"{DIM}{_fmt_price(s.last):>12}{RESET}  "
            f"{_fmt_spread(s.spread_points):>11}  "
            f"{deltas:>28}  "
            f"{GRAY}{last_update}{RESET}"
        )

    return "\n".join(lines)


def render_static(
    scanner: MarketScanner,
    snapshot: Dict[str, TickSnapshot],
) -> None:
    """Affiche un snapshot en place (clear + reprint) pour la console."""
    _clear()
    print(render_snapshot(scanner, snapshot, show_header=True))
    print()
    print(f"{GRAY}Ctrl+C pour quitter.{RESET}")
    sys.stdout.flush()


def render_plain(
    scanner: MarketScanner,
    snapshot: Dict[str, TickSnapshot],
) -> None:
    """Variante sans TTY : affiche une ligne par tick, préfixée du timestamp."""
    stamp = time.strftime("%H:%M:%S")
    print(f"--- {stamp} ---")
    for sym in sorted(snapshot.keys()):
        s = snapshot[sym]
        print(
            f"{sym:<10} bid={_fmt_price(s.bid):>12}  "
            f"ask={_fmt_price(s.ask):>12}  "
            f"spread={s.spread_points:6.1f}pts  "
            f"Δbid={s.bid_delta:+.5f} ({s.bid_pct:+.3f}%)"
        )
    sys.stdout.flush()


def make_display(verbose: bool = True):
    """Retourne un display_fn compatible avec scanner.watch(...)."""
    if verbose and _IS_TTY:
        return render_static
    return render_plain


# ─── Liquidity Sweeps (ICT BSL / SSL) ────────────────────────────────────────
def render_sweeps(
    events: List[SweepEvent],
    scanned_count: int = 0,
    timeframe: str = "",
) -> str:
    """Construit le rendu texte des sweeps détectés (triés par distance)."""
    lines: List[str] = []
    lines.append(f"{BOLD}{CYAN}== Liquidity Sweeps (BSL / SSL) =={RESET}")
    lines.append(f"  {GRAY}Timeframe:{RESET} {timeframe or 'n/a'}  |  "
                 f"{GRAY}Sweeps:{RESET} {len(events)}  |  "
                 f"{GRAY}Symbols scannes:{RESET} {scanned_count}")
    lines.append("")

    if not events:
        lines.append(f"{YELLOW}Aucun sweep detecte dans la fenetre etudiee.{RESET}")
        return "\n".join(lines)

    sym_w = max(10, max(len(e.symbol) for e in events))
    header = (
        f"{BOLD}{'Symbole':<{sym_w}}  {'Side':>4}  {'Level':>14}  {'Now':>14}  "
        f"{'Distance':>9}  {'Dir':>14}  {'Swept at':>16}{RESET}"
    )
    lines.append(header)
    lines.append(f"{GRAY}{'-' * (len(header) - len(BOLD) - len(RESET))}{RESET}")

    for e in events:
        side_col = f"{YELLOW}{e.sweep_label}{RESET}"
        if e.direction == "reversal_up":
            dcol = f"{GREEN}reversal_up{RESET}"
        else:
            dcol = f"{RED}reversal_down{RESET}"
        swept_at = time.strftime("%Y-%m-%d %H:%M", time.gmtime(e.sweep_time))
        lines.append(
            f"{MAGENTA}{e.symbol:<{sym_w}}{RESET}  "
            f"{_pad_cell(side_col, 4)}  "
            f"{_fmt_price(e.level):>14}  "
            f"{_fmt_price(e.current_price):>14}  "
            f"{_pad_cell(DIM + f'{e.distance_pct:>8.3f}%' + RESET, 9)}  "
            f"{_pad_cell(dcol, 14)}  "
            f"{_pad_cell(f'{GRAY}{swept_at}{RESET}', 16)}"
        )

    return "\n".join(lines)


def render_sweeps_plain(events: List[SweepEvent]) -> None:
    """Variante non-TTY : une ligne ASCII par sweep (compatible pipe / log)."""
    for e in events:
        if e.direction == "reversal_up":
            arrow = "UP"
            dcolor = "↑"
        else:
            arrow = "DOWN"
            dcolor = "↓"
        swept_at = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(e.sweep_time))
        print(
            f"{e.symbol:<10} {e.sweep_label} level={e.level:.5f} "
            f"now={e.current_price:.5f} dist={e.distance_pct:.3f}% "
            f"dir={arrow}({dcolor}) swept_at={swept_at}"
        )
    sys.stdout.flush()


# ─── Asian Session Range ───────────────────────────────────────────────────────
def render_asian_ranges(
    results: List[AsianRangeResult],
    scanned_count: int,
    session_date: str,
    timeframe: str,
) -> str:
    """Affiche le tableau du range asiatique + etat des sweeps post-Asian."""
    lines: List[str] = []
    lines.append(f"{BOLD}{CYAN}== Asian Session Range (UTC 00:00-08:00) y Sweeps =={RESET}")
    lines.append(
        f"  {GRAY}Session UTC:{RESET} {session_date} 00:00-08:00  |  "
        f"{GRAY}Timeframe:{RESET} {timeframe}  |  "
        f"{GRAY}Symbols scannes:{RESET} {scanned_count}"
    )
    lines.append("")

    if not results:
        lines.append(
            f"{YELLOW}Aucun range asiatique calcule pour {session_date} "
            f"(marche pas ouvert, ou pas de bougies H1 dispo).{RESET}"
        )
        return "\n".join(lines)

    sym_w = max(10, max(len(r.symbol) for r in results))
    header = (
        f"{BOLD}{'Symbole':<{sym_w}}  {'AsianHigh':>11}  {'AsianLow':>11}  "
        f"{'Now':>11}  {'AH Swp':>10}  {'AL Swp':>10}  "
        f"{'Session':>20}  {'Target':>14}  {'Fib':>14}  {'Fib Swp':>22}  {'Bars':>5}"
        f"  {'Trade':>14}  {'Plan':>26}  {'RR':>8}{RESET}"
    )
    lines.append(header)
    lines.append(
        f"{GRAY}{'-' * (len(header) - len(BOLD) - len(RESET))}{RESET}"
    )

    for r in results:
        if r.asian_high_swept:
            ah_status = f"{RED}swept{RESET}"
        elif r.asian_high_breached:
            ah_status = f"{DIM}touch{RESET}"
        else:
            ah_status = f"{GRAY}---{RESET}"

        if r.asian_low_swept:
            al_status = f"{GREEN}swept{RESET}"
        elif r.asian_low_breached:
            al_status = f"{DIM}touch{RESET}"
        else:
            al_status = f"{GRAY}---{RESET}"

        # Contrainte d'alignement : chaque cellule doit utiliser UNE SEULE paire
        # d'ANSI escape (couleur + RESET), pour que la longueur brute de la chaine
        # coloree soit constante et que le padding `:>22` produise des colonnes
        # visuellement alignees.
        if r.asian_high_swept and r.asian_low_swept:
            # Les deux swept -> DIM (gris) avec texte compile H/L
            session = (
                f"{DIM}H:{r.high_swept_session_label or '?'}/"
                f"L:{r.low_swept_session_label or '?'}{RESET}"
            )
        elif r.asian_high_swept:
            session = f"{RED}H:{r.high_swept_session_label or '?'}{RESET}"
        elif r.asian_low_swept:
            session = f"{GREEN}L:{r.low_swept_session_label or '?'}{RESET}"
        else:
            session = f"{GRAY}-{RESET}"

        if r.direction_target == "BOTH":
            target_col = f"{YELLOW}{r.direction_target_label}{RESET}"
        elif r.direction_target == "AH":
            target_col = f"{GREEN}{r.direction_target_label}{RESET}"
        elif r.direction_target == "AL":
            target_col = f"{RED}{r.direction_target_label}{RESET}"
        else:
            target_col = f"{GRAY}{r.direction_target_label}{RESET}"

        # Coloration multi-niveaux : préfixe "+" -> vert, "-" -> rouge, _DONE -> gras.
        # Cas vide : on met `—` gris pour que toutes les cellules aient la meme
        # longueur brute (couleur+placeholder+reset) et que le `:>22` reste stable.
        if r.fib_state and r.fib_state[0] == "+":
            if r.fib_state.endswith("_DONE"):
                fib_col = f"{GREEN}{BOLD}{r.fib_label}{RESET}"
            else:
                fib_col = f"{GREEN}{r.fib_label}{RESET}"
        elif r.fib_state and r.fib_state[0] == "-":
            if r.fib_state.endswith("_DONE"):
                fib_col = f"{RED}{BOLD}{r.fib_label}{RESET}"
            else:
                fib_col = f"{RED}{r.fib_label}{RESET}"
        else:
            fib_col = f"{GRAY}—{RESET}"

        # Colonne FibSwept : single-color pour stabiliser le padding `:>22`.
        if r.bull_fib_swept and r.bear_fib_swept:
            # Les deux -> YELLOW (jaune) avec compo `↑bull ↓bear` (single ANSI pair)
            fib_swept_col = (
                f"{YELLOW}\u2191{r.bull_fib_swept_label} "
                f"\u2193{r.bear_fib_swept_label}{RESET}"
            )
        elif r.bull_fib_swept:
            fib_swept_col = f"{GREEN}\u2191{r.bull_fib_swept_label}{RESET}"
        elif r.bear_fib_swept:
            fib_swept_col = f"{RED}\u2193{r.bear_fib_swept_label}{RESET}"
        else:
            fib_swept_col = f"{GRAY}\u2014{RESET}"

        lines.append(
            f"{MAGENTA}{r.symbol:<{sym_w}}{RESET}  "
            f"{_fmt_price(r.asian_high):>11}  {_fmt_price(r.asian_low):>11}  "
            f"{_fmt_price(r.current_price):>11}  "
            f"{_pad_cell(ah_status, 10)}  "
            f"{_pad_cell(al_status, 10)}  "
            f"{_pad_cell(session, 20)}  "
            f"{_pad_cell(target_col, 14)}  "
            f"{_pad_cell(fib_col, 14)}  "
            f"{_pad_cell(fib_swept_col, 22)}  "
            f"{DIM}{r.bars_checked:>5}{RESET}  "
            f"{_pad_cell(_trade_action_col(r), 14)}  "
            f"{_pad_cell(_trade_plan_col(r), 26)}  "
            f"{_pad_cell(_trade_rr_col(r), 8)}"
        )

    return "\n".join(lines)


def _trade_action_col(r) -> str:
    """Colonne 'Trade' = action BUY/SELL codee par couleur (single ANSI pair)."""
    if r.trade_action == "BUY":
        return f"{GREEN}BUY{RESET}"
    if r.trade_action == "SELL":
        return f"{RED}SELL{RESET}"
    return f"{GRAY}-{RESET}"


def _trade_plan_col(r) -> str:
    """Colonne 'Plan' = 'SL price -> TP1 price' (single ANSI pair).
    - 'Active'           -> cyan, plan complet visible
    - 'Targets hit'      -> dim gray, plan deja execute
    - 'Range too tight'  -> dim gray, range insuffisante pour TR
    - 'Wait pullback' /
      'Wait breakout' /
      '-'                -> dim gray, sweep pas encore valide"""
    if r.trade_status == "Active" and r.trade_sl and r.trade_tp1:
        return (
            f"{CYAN}SL {_fmt_price(r.trade_sl)} "
            f"\u2192 TP1 {_fmt_price(r.trade_tp1)}{RESET}"
        )
    if r.trade_status == "Targets hit":
        return f"{GRAY}TP1-3 hit{RESET}"
    if r.trade_status == "Range too tight":
        return f"{GRAY}Range too tight{RESET}"
    return f"{GRAY}-{RESET}"


def _trade_rr_col(r) -> str:
    """Colonne 'RR' = ratio risque:recompense au TP1 (single ANSI pair).
    Padding :>15 couvre '10.5×' (5+10=15 raw) ; les cellules placeholders ont
    11 raw (5+1+5) et finissent au meme offset grace a l alignement a droite."""
    if r.trade_action != "-" and r.trade_rr1 and r.trade_rr1 > 0:
        return f"{YELLOW}{r.trade_rr1:.1f}\u00d7{RESET}"
    return f"{GRAY}-{RESET}"


def render_asian_ranges_plain(results: List[AsianRangeResult]) -> None:
    """Variante non-TTY : une ligne ASCII par symbole (compatible pipe / log)."""
    for r in results:
        ah = "AH_SWEPT" if r.asian_high_swept else ("AH_BREACH" if r.asian_high_breached else "AH_---")
        al = "AL_SWEPT" if r.asian_low_swept else ("AL_BREACH" if r.asian_low_breached else "AL_---")
        session_info = ""
        if r.asian_high_swept:
            session_info += f" H@{r.high_swept_session_label}"
        if r.asian_low_swept:
            session_info += f" L@{r.low_swept_session_label}"
        h_stamp = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r.high_swept_at))
            if r.high_swept_at else "---"
        )
        l_stamp = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r.low_swept_at))
            if r.low_swept_at else "---"
        )
        bull_fib_str = (
            f" bull_fib_swept=↑{r.bull_fib_swept_label}@{r.bull_fib_swept_session_label}"
            if r.bull_fib_swept else ""
        )
        bear_fib_str = (
            f" bear_fib_swept=↓{r.bear_fib_swept_label}@{r.bear_fib_swept_session_label}"
            if r.bear_fib_swept else ""
        )
        # Trade plan block : gate sur r.trade_status pour eviter d afficher des
        # '0.00000' trompeurs sur des lignes sans trade valide (le SL/EP/TP sont
        # None dans ce cas, mais on n a pas envie de montrer 0.0 qui ressemble
        # a un vrai prix).
        if r.trade_status == "Active":
            trade_block = (
                f" TRADE={r.trade_action}/{r.trade_status} "
                f"EP={_fmt_price(r.trade_entry)} "
                f"SL={_fmt_price(r.trade_sl)} "
                f"TP1={_fmt_price(r.trade_tp1)} "
                f"TP2={_fmt_price(r.trade_tp2)} "
                f"TP3={_fmt_price(r.trade_tp3)} "
                f"RR1={(r.trade_rr1 if r.trade_rr1 is not None else 0):.2f}"
            )
        else:
            trade_block = f" TRADE={r.trade_action}/{r.trade_status} (no SL/TP)"
        print(
            f"{r.symbol:<10} {ah} {al} AH={r.asian_high:.5f} AL={r.asian_low:.5f} "
            f"now={r.current_price:.5f} AH@UTC={h_stamp} AL@UTC={l_stamp}"
            f"{session_info} TOWARD={r.direction_target_label} "
            f"FIB=({r.fib_plus_1618:.5f}/-{r.fib_minus_1618:.5f}) {r.fib_label}"
            f"{bull_fib_str}{bear_fib_str}"
            f"{trade_block}"
        )
    sys.stdout.flush()
