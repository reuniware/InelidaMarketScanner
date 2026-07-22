# 🚀 InelidaMarketScan v1.0.1 — Première release

> **Date :** 18 juillet 2026  
> **Tag :** `v1.0.1`  
> **Statut :** Première release publique — scanner multi-TF ICT × Ichimoku automatisé

---

## 💎 Diamond Scanner — Analyse Ichimoku × ICT multi-TF

Le cœur du projet. 109 critères de scoring sur 8 timeframes (M5 → MN).

### Ichimoku complet
- **Tous les TFs :** M5, M15, M30, H1, H4, D1, W1, MN
- Kijun, Tenkan, T/Kx crosses, Kumo (position + futur + visible)
- Tenkan/Kijun flat history (mémoire institutionnelle)
- SSB proximity, Kumo flat magnets
- Alignement multi-TF (0-5)

### ICT Concepts
- **FVG** (Fair Value Gaps) — bearish & bullish, tous les TFs, % mitigation
- **OB** (Order Blocks) — détection d'impulsion, support/résistance institutionnel
- **Breaker Blocks** — OB inversés après cassure
- **MSS/BOS** (Market Structure Shift / Break of Structure) — régime BULL/BEAR/RANGE
- **HVN/LVN** — volume tick MT5, zones de haut/bas volume
- **Sweeps AH/AL** — Asian High/Low, London High/Low, double sweep
- **Reversal Pipeline** — sweep → retournement → confirmation (CHoCH, retest, FVG post-sweep)

### Smart TP & Fibonacci
- TP calculé sur niveaux réels (Kijun, FVG, OB, SSB) — pas de RR arbitraire
- Extensions Fibonacci (+2.618 base AH) et retracements (0.5, 0.618, 0.786)

### 3 Garde-fous automatiques
| Filtre | Règle | Backtest |
|:---|:---|:---:|
| **T/Kx H1 Conflit** | TKx H1 oppose au biais → WAIT | 5/5 perdants évités |
| **MFE Proxy** | Flat bars + Kumo INSIDE → downgrade | 4/4 perdants évités |
| **HIGH NEWS DAY** | ≥2 événements majeurs → downgrade BULL | 15/15 erreurs évitées |

---

## 🧲 Asian Sweep Detector

- Scan exhaustif de tous les symboles MT5 (167+)
- Détection AH/AL par session (Asian 00-08 UTC)
- Sweeps intra-Asian (M5, pas seulement H1)
- Direction cible (→ AH, → AL, ↔ Both)
- Timestamps de sweep (Swept H@, Swept L@)

---

## 📊 P&L Tracker

- `track save` — sauvegarde les setups Diamond
- `track update` — met à jour les prix en temps réel
- `track report` — rapport P&L global (win rate, P&L pips)
- `track history --id N` — historique détaillé d'un trade
- `track close --id N` — fermeture manuelle
- `--force` — sauvegarde aussi les setups WAIT (scalps manuels)
- `--sl` / `--tp` — niveaux manuels personnalisés
- Base SQLite (`diamond_trades` + `diamond_snapshots`)

---

## 🔧 Commandes CLI

```bash
# Scan Diamond complet
python main.py diamond
python main.py diamond --symbols EURUSD GBPJPY
python main.py diamond --timezone BROKER|UTC|PARIS
python main.py diamond --discord          # poste sur Discord
python main.py diamond --volume-only      # que HVN/LVN

# Scan Asian (sweeps)
python main.py asian
python main.py asian --scan-all --swept-only

# Setups, niveaux, DB
python main.py setups                     # setups actifs
python main.py levels                     # niveaux techniques
python main.py db stats                   # stats base de données
python main.py download                   # télécharger historique MT5

# P&L Tracker
python main.py track save                 # sauvegarder setups
python main.py track update               # mettre à jour prix
python main.py track report               # rapport P&L
python main.py track save --force --sl X --tp Y  # scalp manuel
```

---

## 📡 Discord Integration

- `--discord` flag sur `diamond` — poste automatiquement les résultats
- Embed formaté : DXY, tableau des symboles, setups actifs, avertissements
- Webhook via `.env` (`DISCORD_WEBHOOK_URL`)

---

## ⚙️ Configuration

- **Watchlist :** 13 symboles par défaut (forex majeurs, JPY crosses, indices US, or, DXY)
- **Timezone :** BROKER (serveur MT5) / UTC / PARIS (CEST avec DST)
- **Base de données :** SQLite (`./inelida_market_data.db`)
- **Variables d'environnement :** `INELIDA_WATCHLIST`, `DISCORD_WEBHOOK_URL`

---

## 📚 Documentation

- `GUIDE_UTILISATEUR.md` — guide complet orienté débutant
- `diamond-analysis-skill.md` — méthodologie ICT × Ichimoku
- `historique.md` — journal de bord + leçons apprises
- `tradingskills.md` — compétences de trading
- `suggested_followups.md` — suggestions d'amélioration

---

## 📦 Dépendances

- Python 3.12+
- MetaTrader5 (`pip install MetaTrader5`)
- SQLite (intégré)
- Pas de dépendances lourdes (pas de pandas, numpy, etc.)

---

## 🔜 Feuille de route

- [ ] Auto-close si MFE = 0 après 30 barres
- [ ] Corrélation DXY → XAUUSD automatique
- [ ] Score de fiabilité par type de symbole
- [ ] GitHub Actions : scan quotidien + backtest hebdo
- [ ] Interface web (Flask) pour dashboard temps réel

---

> **Total commits v1.0.1 :** ~20  
> **Fichier principal :** `src/diamond_scanner.py` (2840+ lignes, 109 critères)  
> **Backtest :** 0% win rate sans filtres → 70% avec filtres sur 15 trades  
> **Crédits :** Projet personnel — développement accéléré par IA

---

> **Reuniware Systems** — InelidaMarketScan
