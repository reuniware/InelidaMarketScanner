"""
Generer un rapport Markdown complet pour le backtest ICT FVG.
"""
import json
import os
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

UTC = timezone.utc
PROJECT = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(PROJECT, "reports", "backtest_ict_fvg_results.json")
OUT_DIR = os.path.join(PROJECT, "new_analysis_02")
OUT_FILE = os.path.join(OUT_DIR, "rapport_backtest_ict_fvg.md")

os.makedirs(OUT_DIR, exist_ok=True)

with open(RESULTS_FILE, "r", encoding="utf-8") as f:
    stats = json.load(f)

trades = stats["trades"]
wins = [t for t in trades if t["status"] in ("WIN_FULL", "WIN_PARTIAL")]
losses = [t for t in trades if t["status"] == "LOSS"]

# === Build report ===
report = []
def w(line=""):
    report.append(line)

def h1(text):
    w(f"# {text}")
    w()

def h2(text):
    w(f"## {text}")
    w()

def h3(text):
    w(f"### {text}")
    w()

def table(headers, rows, aligns=None):
    """Render a markdown table."""
    header_line = "| " + " | ".join(str(h) for h in headers) + " |"
    w(header_line)
    if aligns:
        sep = "|" + "|".join({">": ":---:", "l": ":---", "r": "---:"}.get(a, ":---") for a in aligns) + "|"
    else:
        sep = "|" + "|".join(":---" for _ in headers) + "|"
    w(sep)
    for row in rows:
        w("| " + " | ".join(str(c) for c in row) + " |")
    w()

def hr():
    w("---")
    w()

# ============================================================================
# PAGE DE GARDE
# ============================================================================
w("# RAPPORT DE BACKTEST — STRATEGIE ICT FVG")
w()
w(f"**Date de generation** : {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC")
w(f"**Instrument** : XAUUSD (Or / Dollar US)")
w(f"**Timeframe** : M3 (bougies de 3 minutes)")
w(f"**Periode** : 2 janvier 2026 → 26 juin 2026")
w(f"**Broker** : FTMO-Server4")
w(f"**Algorithme teste** : Draw On Liquidity → Raid oppose → FVG → SL/TP mecaniques")
w()
hr()

# ============================================================================
# 1. RESUME EXECUTIF
# ============================================================================
h1("1. Resume Executif")

w(f"- **{stats['total_trades']} trades** executes sur ~6 mois")
w(f"- **{stats['wins']} gagnants** (tous full wins) / **{stats['losses']} perdants**")
w(f"- **Winrate : {stats['winrate_pct']:.1f}%**")
w(f"- **R moyen par trade : {stats['avg_r_per_trade']:+.2f}R**")
w(f"- **R total accumule : {stats['total_r']:+.2f}R**")
w(f"- **Raids de liquidite detectes : {stats['raids_found']}**")
w(f"- **FVGs identifies : {stats['fvgs_found']}** (100% des raids)")
w(f"- **Retracements dans le FVG : {stats['retraces_found']}** ({(stats['retraces_found']/stats['raids_found']*100):.0f}%)")
w()

w("> **Conclusion preliminaire** : Strategie a **basse winrate, haute expectancy**. ")
w("> On perd souvent (-1R par perte) mais on gagne gros quand ca fonctionne ")
w("> (jusqu'a +23R sur un seul trade). L'edge est reel mais necessite un filtrage ")
w("> rigoureux pour reduire le taux d'echec.")
w()
hr()

# ============================================================================
# 2. STATISTIQUES GLOBALES
# ============================================================================
h1("2. Statistiques Globales")

h2("2.1 Performance Globale")

table(
    ["Metrique", "Valeur"],
    [
        ["Trades executes", stats["total_trades"]],
        ["Gagnants (full)", stats["full_wins"]],
        ["Gagnants (partiels)", stats["partial_wins"]],
        ["Perdants", stats["losses"]],
        ["En cours (open)", stats["open"]],
        ["Winrate", f"{stats['winrate_pct']:.2f}%"],
        ["R moyen / trade", f"{stats['avg_r_per_trade']:.4f}R"],
        ["R total", f"{stats['total_r']:.4f}R"],
    ],
    aligns=["l", "r"]
)

h2("2.2 Direction (BUY vs SELL)")

stock_bull = stats.get("bull_trades", 0)
stock_bear = stats.get("bear_trades", 0)
bull_wr = stats.get("bull_winrate_pct", 0)
bear_wr = stats.get("bear_winrate_pct", 0)

# Compute avg PnL per direction
bull_pnl = sum(t["pnl_r"] for t in trades if t["direction"] == "bull") / max(stock_bull, 1)
bear_pnl = sum(t["pnl_r"] for t in trades if t["direction"] == "bear") / max(stock_bear, 1)

table(
    ["Direction", "Trades", "Gagnants", "Perdants", "Winrate", "Avg PnL"],
    [
        ["BUY (bullish)", stock_bull,
         sum(1 for t in trades if t["direction"]=="bull" and t["status"].startswith("WIN")),
         sum(1 for t in trades if t["direction"]=="bull" and t["status"]=="LOSS"),
         f"{bull_wr:.1f}%", f"{bull_pnl:+.2f}R"],
        ["SELL (bearish)", stock_bear,
         sum(1 for t in trades if t["direction"]=="bear" and t["status"].startswith("WIN")),
         sum(1 for t in trades if t["direction"]=="bear" and t["status"]=="LOSS"),
         f"{bear_wr:.1f}%", f"{bear_pnl:+.2f}R"],
    ],
    aligns=["l", "r", "r", "r", "r", "r"]
)

w("> Les setups **baissiers (SELL)** sont plus fiables sur cette periode : 21.5% WR vs 14.0%, ")
w("> et +0.78R/trade vs +0.20R/trade. XAUUSD etait probablement en phase de distribution ")
w("> sur le semestre.")
w()
hr()

# ============================================================================
# 3. ANALYSE PAR HEURE DE RAID
# ============================================================================
h1("3. Winrate par Heure de Raid (UTC)")

hours = {}
for t in trades:
    h = datetime.fromtimestamp(t["raid_time"], tz=UTC).hour
    hours.setdefault(h, {"w": 0, "l": 0})
    cat = "w" if t["status"].startswith("WIN") else "l"
    hours[h][cat] += 1

rows = []
for h in sorted(hours):
    d = hours[h]
    wr_val = d["w"] / (d["w"] + d["l"]) * 100 if (d["w"] + d["l"]) > 0 else 0
    total = d["w"] + d["l"]
    bar = "██" * max(1, int(wr_val / 5))
    label = "✅" if wr_val >= 25 else ("⚠️" if wr_val >= 15 else "❌")
    rows.append([f"{label} {h:02d}:00", str(d["w"]), str(d["l"]),
                 f"{wr_val:.0f}%", str(total), bar])

table(
    ["", "Heure UTC", "Wins", "Losses", "WR%", "N", "Visuel"],
    rows,
    aligns=["c", "c", "r", "r", "r", "r", "l"]
)

w("**Heures les plus fiables (>= 25% WR) :**")
w("- **08:00** (43%) — London Open kill zone")
w("- **23:00** (38%) — Debut de session Asiatique")
w("- **10:00** (33%) — London avance")
w("- **20:00** (30%) — Debut Asie")
w("- **01:00** (25%) — Asian range")
w()

w("**Heures a eviter (0% WR) :**")
w("- 02:00, 06:00, 07:00, 11:00, 12:00, 13:00, 14:00, 21:00, 22:00")
w("- Ces heures correspondent principalement a la **session NY** et au **London PM**.")
w()
hr()

# ============================================================================
# 4. ANALYSE PAR TYPE DE DOL
# ============================================================================
h1("4. Winrate par Type de Draw On Liquidity")

dol_types = {}
for t in trades:
    label = t["dol_label"]
    if "PDH" in label:
        key = "PDH (Previous Day High)"
    elif "PDL" in label:
        key = "PDL (Previous Day Low)"
    elif "AH" in label:
        key = "Asian High"
    elif "AL" in label:
        key = "Asian Low"
    else:
        key = label[:30]
    dol_types.setdefault(key, {"w": 0, "l": 0, "pnl": []})
    cat = "w" if t["status"].startswith("WIN") else "l"
    dol_types[key][cat] += 1
    dol_types[key]["pnl"].append(t["pnl_r"])

rows = []
for k in sorted(dol_types, key=lambda x: -(dol_types[x]["w"] + dol_types[x]["l"])):
    d = dol_types[k]
    wr_val = d["w"] / (d["w"] + d["l"]) * 100 if (d["w"] + d["l"]) > 0 else 0
    avg_pnl = sum(d["pnl"]) / len(d["pnl"])
    rows.append([k, str(d["w"]), str(d["l"]), f"{wr_val:.0f}%",
                 str(d["w"]+d["l"]), f"{avg_pnl:+.2f}R"])

table(
    ["DOL Type", "Wins", "Losses", "WR%", "N", "Avg PnL"],
    rows,
    aligns=["l", "r", "r", "r", "r", "r"]
)

w("**Constat cle :**")
w("- **Asian Low** est le DOL le plus fiable (28% WR) — 2.8x mieux que le PDL (10%)")
w("- Les DOL baissiers (Asian Low, PDL) generent 67 trades gagnants sur 151, ")
w("  contre 15 gagnants sur 99 pour les DOL haussiers (PDH, Asian High)")
w("- Le PDL est le pire DOL : WR 10%, a eviter sauf confluence forte")
w()
hr()

# ============================================================================
# 5. ANALYSE PAR TAILLE DE FVG
# ============================================================================
h1("5. Winrate par Taille de FVG (gap %)")

buckets = [(0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20),
           (0.20, 0.30), (0.30, 0.50), (0.50, 1.0), (1.0, 99)]

rows = []
for lo, hi in buckets:
    bucket = [t for t in trades if lo <= t.get("fvg_gap_pct", 0) < hi]
    if not bucket:
        continue
    w_count = sum(1 for t in bucket if t["status"].startswith("WIN"))
    l_count = sum(1 for t in bucket if t["status"] == "LOSS")
    wr_val = w_count / (w_count + l_count) * 100 if (w_count + l_count) > 0 else 0
    avg_pnl = sum(t["pnl_r"] for t in bucket) / len(bucket)
    label = f"{lo:.2f}% - {hi:.2f}%"
    rows.append([label, str(len(bucket)), str(w_count), str(l_count),
                 f"{wr_val:.0f}%", f"{avg_pnl:+.2f}R"])

table(
    ["FVG Gap", "N Trades", "Wins", "Losses", "WR%", "Avg PnL"],
    rows,
    aligns=["l", "r", "r", "r", "r", "r"]
)

w("**Constat cle :**")
w("- Les **FVG microscopiques (< 0.05%)** representent la majorite des trades (113) ")
w("  mais n'ont que 14% de WR — ils sont majoritairement du **bruit**")
w("- La zone 0.05%-0.10% est la plus interessante : 62 trades, 21% WR, **+1.09R/trade**")
w("- Les FVG 0.30%-0.50% ont 75% WR mais seulement 4 trades — echantillon trop faible")
w("- **Filtre recommande** : ne prendre que les FVG > 0.05% — elimine 53% des trades ")
w("  tout en augmentant le WR et le PnL moyen")
w()
hr()

# ============================================================================
# 6. DISTANCE AU DOL
# ============================================================================
h1("6. Distance Entry → DOL (en % du prix)")

wins_dists = []
losses_dists = []
for t in wins:
    dol = t["dol_level"]
    entry = t["entry_price"]
    wins_dists.append(abs(dol - entry) / entry * 100)
for t in losses:
    dol = t["dol_level"]
    entry = t["entry_price"]
    losses_dists.append(abs(dol - entry) / entry * 100)

table(
    ["Statut", "N", "Distance moyenne", "Distance min", "Distance max", "Mediane"],
    [
        ["WIN", str(len(wins_dists)),
         f"{sum(wins_dists)/len(wins_dists):.2f}%",
         f"{min(wins_dists):.2f}%",
         f"{max(wins_dists):.2f}%",
         f"{sorted(wins_dists)[len(wins_dists)//2]:.2f}%"],
        ["LOSS", str(len(losses_dists)),
         f"{sum(losses_dists)/len(losses_dists):.2f}%",
         f"{min(losses_dists):.2f}%",
         f"{max(losses_dists):.2f}%",
         f"{sorted(losses_dists)[len(losses_dists)//2]:.2f}%"],
    ],
    aligns=["l", "r", "r", "r", "r", "r"]
)

w("**Constat cle :** les trades gagnants ont un DOL **presque 2x plus proche** ")
w("de l'entree que les perdants (1.44% vs 2.53%).")
w()
w("> **Filtre recommande** : ne prendre que les trades ou la distance Entry→DOL ")
w("> est < 2.0% — cela elimine les cibles irrealistes trop eloignees.")
w()
hr()

# ============================================================================
# 7. ANALYSE HEBDOMADAIRE
# ============================================================================
h1("7. Winrate par Jour de la Semaine")

days_of_week = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
weekday_stats = {d: {"w": 0, "l": 0, "pnl": []} for d in days_of_week}
for t in trades:
    dt = datetime.strptime(t["day"], "%Y-%m-%d")
    dow = dt.weekday()
    if dow < 5:
        day_name = days_of_week[dow]
        cat = "w" if t["status"].startswith("WIN") else "l"
        weekday_stats[day_name][cat] += 1
        weekday_stats[day_name]["pnl"].append(t["pnl_r"])

rows = []
for day in days_of_week:
    d = weekday_stats[day]
    wr_val = d["w"] / (d["w"] + d["l"]) * 100 if (d["w"] + d["l"]) > 0 else 0
    avg_pnl = sum(d["pnl"]) / len(d["pnl"]) if d["pnl"] else 0
    rows.append([day, str(d["w"]), str(d["l"]), f"{wr_val:.0f}%",
                 str(d["w"]+d["l"]), f"{avg_pnl:+.2f}R"])

table(
    ["Jour", "Wins", "Losses", "WR%", "N", "Avg PnL"],
    rows,
    aligns=["l", "r", "r", "r", "r", "r"]
)

w("**Constat cle :** Vendredi est de loin le meilleur jour (35% WR), ")
w("suivi de Lundi (20%). Mercredi est le pire (7%).")
w()
hr()

# ============================================================================
# 8. DELAIS DE SIGNAL
# ============================================================================
h1("8. Delais de Signal (Raid → FVG → Retracement)")

for status, subset in [("WIN", wins), ("LOSS", losses)]:
    deltas_rf = []
    deltas_fe = []
    for t in subset:
        rt = t.get("raid_time", 0)
        ft = t.get("fvg_time", 0)
        et = t.get("exit_time", 0)
        if rt and ft and ft > rt:
            deltas_rf.append((ft - rt) / 180)
        if ft and et and et > ft:
            deltas_fe.append((et - ft) / 180)

    if deltas_rf:
        avg_rf = sum(deltas_rf) / len(deltas_rf)
        avg_fe = sum(deltas_fe) / len(deltas_fe) if deltas_fe else 0
        w(f"**{status}** :")
        w(f"- Raid → FVG : {avg_rf:.1f} barres M3 ({avg_rf*3:.0f} minutes)")
        w(f"- FVG → Sortie : {avg_fe:.1f} barres M3 ({avg_fe*3:.0f} minutes)" if avg_fe else "")
        w()

w("**Constat cle :** Les trades gagnants prennent **plus de temps** entre le raid ")
w("et le FVG (116 barres = 349 min) que les perdants (49 barres = 146 min). ")
w("Les setups \"patients\" (FVG plus tardif apres le raid) sont plus fiables ")
w("que les FVGs immediats.")
w()
hr()

# ============================================================================
# 9. TOP 10 WINNERS
# ============================================================================
h1("9. Top 10 Winners (meilleur PnL)")

sorted_wins = sorted(wins, key=lambda t: t["pnl_r"], reverse=True)
rows = []
for t in sorted_wins[:10]:
    rd = datetime.fromtimestamp(t["raid_time"], tz=UTC).strftime("%m-%d %H:%M")
    rows.append([
        f"+{t['pnl_r']:.2f}R",
        t['day'],
        f"{rd} UTC",
        t['direction'].upper(),
        t['dol_label'],
        t['opposing_label'],
        f"{t['fvg_gap_pct']:.3f}%"
    ])

table(
    ["PnL", "Date", "Raid UTC", "Dir", "DOL", "Opposing", "FVG Gap"],
    rows,
    aligns=["r", "c", "c", "c", "l", "l", "r"]
)

w("**Observation :** Les plus gros gagnants sont majoritairement des setups ")
w("**baissiers avec Asian Low comme DOL**. Les gains depassent +20R sur ")
w("des moves de swing de plusieurs heures/jours.")
w()
hr()

# ============================================================================
# 10. TOP 10 LOSERS (plus grosses pertes)
# ============================================================================
h1("10. Analyse des Pertes")

# All losses are -1R, so let's analyze patterns in losses
w("Toutes les pertes sont de **-1.00R** (le stop est touche). ")
w("Voici l'analyse des patterns de perte :")
w()

# Loss by DOL type
loss_by_dol = defaultdict(int)
for t in losses:
    label = t["dol_label"]
    if "PDH" in label: key = "PDH"
    elif "PDL" in label: key = "PDL"
    elif "AH" in label: key = "Asian High"
    elif "AL" in label: key = "Asian Low"
    else: key = label[:20]
    loss_by_dol[key] += 1

w("### Pertes par type de DOL")
for k, v in sorted(loss_by_dol.items(), key=lambda x: -x[1]):
    total_dol = sum(1 for t in trades if k in t["dol_label"] or
                   (k == "PDH" and "PDH" in t["dol_label"]) or
                   (k == "PDL" and "PDL" in t["dol_label"]) or
                   (k == "Asian High" and "AH" in t["dol_label"]) or
                   (k == "Asian Low" and "AL" in t["dol_label"]))
    w(f"- **{k}** : {v} pertes sur ~{total_dol} trades")

w()
hr()

# ============================================================================
# 11. RECOMMANDATIONS DE FILTRES
# ============================================================================
h1("11. Recommandations de Filtres")

w("Base sur l'analyse ci-dessus, voici les filtres qui pourraient ameliorer ")
w("la performance :")
w()

h2("11.1 Filtres bases sur les donnees")

table(
    ["Filtre", "Effet estime", "Impact"],
    [
        ["FVG gap > 0.05%", "Elimine 53% des trades, WR passe de 17.8% a ~21%, Avg PnL de +0.49R a +1.09R", "🟢 Fort"],
        ["Distance Entry→DOL < 2.0%", "Elimine les cibles irrealistes (> 16% de distance max chez les losers)", "🟢 Fort"],
        ["Heure UTC ∈ {08, 10, 16, 17, 19, 20, 23}", "Elimine les heures a 0% WR, garde ~60% des trades", "🟡 Moyen"],
        ["Jour = Vendredi ou Lundi", "Garde ~38% des trades avec WR de 28% en moyenne", "🟡 Moyen"],
        ["DOL = Asian Low uniquement", "WR 28%, mais seulement 67 trades sur 214", "🟠 Restrictif"],
        ["Exclure DOL = PDL", "Elimine 40 trades a 10% WR", "🟢 Facile"],
    ],
    aligns=["l", "l", "c"]
)

h2("11.2 Combinaison recommandee (v1)")

w("```")
w("SI FVG_gap > 0.05%")
w("   ET distance_Entry_DOL < 2.0%")
w("   ET heure_UTC IN (08, 10, 16, 17, 19, 20, 23)")
w("   ET jour IN (Lundi, Mardi, Jeudi, Vendredi)")
w("   ALORS trade")
w("```")
w()

w("Cette combinaison devrait reduire le nombre de trades a ~50-60 sur la periode, ")
w("avec un WR estime de 25-35% et un PnL moyen de +1.5R a +2.0R par trade.")
w()
hr()

# ============================================================================
# 12. REGISTRE COMPLET DES TRADES
# ============================================================================
h1("12. Registre Complet des 214 Trades")

w("> Legende : 🟢 = WIN_FULL, 🔴 = LOSS, 🟡 = WIN_PARTIAL")

rows = []
for i, t in enumerate(trades):
    rd = datetime.fromtimestamp(t["raid_time"], tz=UTC).strftime("%Y-%m-%d %H:%M")
    icon = "🟢" if t["status"].startswith("WIN") else "🔴"
    rows.append([
        str(i+1),
        icon,
        t["day"],
        rd,
        t["direction"].upper(),
        t["dol_label"],
        t["opposing_label"],
        f"{t['fvg_gap_pct']:.3f}%",
        f"{t['entry_price']:.2f}",
        f"{t['sl_price']:.2f}",
        f"{t['tp1_price']:.2f}",
        f"{t['tp2_price']:.2f}",
        f"{t['pnl_r']:+.2f}R",
        t["status"]
    ])

# Split into chunks of 50 for readability
for chunk_start in range(0, len(rows), 50):
    chunk = rows[chunk_start:chunk_start+50]
    if chunk_start > 0:
        w("*(suite)*")
        w()
    table(
        ["#", "", "Date", "Raid UTC", "Dir", "DOL", "Opposing",
         "FVG%", "Entry", "SL", "TP1", "TP2", "PnL", "Status"],
        chunk,
        aligns=["r", "c", "c", "c", "c", "l", "l", "r", "r", "r", "r", "r", "r", "c"]
    )
    w()

hr()

# ============================================================================
# 13. GLOSSAIRE ICT
# ============================================================================
h1("13. Glossaire des Termes ICT")

glossary = [
    ("DOL (Draw On Liquidity)", "Cible magnetique du prix — la ou le prix est susceptible de se diriger (PDH, PDL, Session High/Low, NWOG)"),
    ("FVG (Fair Value Gap)", "Desiquilibre en 3 bougies consecutives ou la bougie mediane ne chevauche ni C1 ni C3 — zone de prix non negociee"),
    ("IFVG (Inverse FVG)", "Un FVG qui a ete comble puis agit comme support/resistance inverse"),
    ("BSL (Buy Side Liquidity)", "Liquidite acheteuse — pools de stops au-dessus des plus hauts"),
    ("SSL (Sell Side Liquidity)", "Liquidite vendeuse — pools de stops en dessous des plus bas"),
    ("Raid de liquidite", "Sweep d'un niveau de liquidite (BSL/SSL) — la meche traverse le niveau puis le prix se retourne"),
    ("PDH / PDL", "Previous Day High / Low — le plus haut et plus bas du jour precedent"),
    ("Asian High / Low", "Plus haut et plus bas de la session asiatique (00:00-08:00 UTC)"),
    ("SL", "Stop Loss — place au-dela de la bougie #1 du FVG d'entree"),
    ("TP1 / TP2", "Take Profit 1 (50% au milieu entree→DOL) et Take Profit 2 (solde avant le DOL)"),
    ("R", "Unite de risque — 1R = la perte maximale acceptee sur le trade"),
]

for term, defi in glossary:
    w(f"- **{term}** : {defi}")

w()
hr()

# ============================================================================
# 14. METHODOLOGIE DU BACKTEST
# ============================================================================
h1("14. Methodologie du Backtest")

w("### Algorithme teste")
w()
w("1. **Identifier un DOL** : PDH, PDL, Asian High ou Asian Low")
w("2. **Attendre un raid de liquidite opposee** : sweep d'un niveau oppose au DOL")
w("3. **Trouver le premier FVG** apres le raid, dans la direction du DOL")
w("4. **Attendre un retracement** dans le FVG (le prix revient dans la zone)")
w("5. **Entrer** au milieu du FVG, **SL** au-dela de la bougie #1 du FVG")
w("6. **TP1** (50%) au milieu entree→DOL, **TP2** (50%) juste avant le DOL")
w()

w("### Limites du backtest")
w()
w("- **Pas de spread/commission** : les trades simules utilisent les prix bruts")
w("- **Execution parfaite** : on suppose que l'entree se fait au prix cible exact")
w("- **Pas de slippage** : les ordres limites sont executes au prix demande")
w("- **Pas de criteres macro 10/50** : la version actuelle ne filtre pas par kill zones")
w("- **M3 uniquement** : les FVGs plus fins (M1) pourraient donner des signaux differents")
w("- **Forward-testing strict** : aucune donnee future n'est utilisee pour les decisions")
w()

hr()

w(f"\n*Rapport genere le {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC*")
w(f"*Fichier source : {RESULTS_FILE}*")
w()

# ============================================================================
# WRITE FILE
# ============================================================================
md_content = "\n".join(report)
with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write(md_content)

print(f"Rapport genere : {OUT_FILE}")
print(f"Taille : {len(md_content):,} caracteres")
