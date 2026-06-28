# Suggested Followups — Inelida Market Scanner

> Prochaines étapes possibles après l'implémentation des badges ELITE V1 et V2.
> Chaque suggestion est conçue pour être donnée telle quelle à l'assistant IA.

---

## 1. Tester les badges ELITE en live

> Vérifie que les badges ELITE V1 et V2 s'affichent correctement en lançant
> `live_alerts.py` en mode test (par exemple avec `--no-sound`).

```bash
# Lancer le moniteur et observer les badges
python live_alerts.py --no-sound

# Vérifier que la ligne de statut affiche :
# Setups: X | V1: Y | V2: Z | Fenetre: OUVERTE/FERMEE
```

**Ce que tu veux vérifier :**
- [ ] Les badges `[ELITE V1]` (jaune) et `[ELITE V2]` (cyan) apparaissent dans l'en-tête
- [ ] La ligne de statut montre `V1: X | V2: Y`
- [ ] Un trade peut porter les deux badges simultanément
- [ ] Le statut de la fenêtre est correct (OUVERTE entre 09:00-13:00 UTC)

---

## 2. Stats V1 vs V2 sur les 438 trades backtestés

> Analyse combien de trades parmi les 438 backtestés passent V1 uniquement,
> V2 uniquement, ou les deux.

```bash
python -c "
import json

with open('reports/backtest_all_results.json', 'r') as f:
    data = json.load(f)

ALLOWED_V1 = {'FOREX_USD', 'INDEX', 'METAL', 'FOREX_CROSS'}
ALLOWED_V2 = {'FOREX_USD', 'INDEX', 'METAL'}

v1_only = v2_only = both = neither = 0

for t in data['all_trades']:
    h = t.get('scan_hour')
    sym_type = t.get('sym_type', '')
    rr = t.get('rr', 0) or 0
    spread = t.get('spread_pct') or 0
    
    v1 = (h is not None and 9 <= h < 10) and sym_type in ALLOWED_V1 and rr >= 0.5 and spread < 0.10
    v2 = (h is not None and 9 <= h < 13) and sym_type in ALLOWED_V2 and rr >= 0.0 and spread < 0.50
    
    if v1 and v2: both += 1
    elif v1: v1_only += 1
    elif v2: v2_only += 1
    else: neither += 1

print(f'V1 uniquement: {v1_only}')
print(f'V2 uniquement: {v2_only}')
print(f'Les deux: {both}')
print(f'Aucun: {neither}')
"
```

**Résultats attendus :** La plupart des trades V1 devraient aussi passer V2
(les critères V2 sont plus larges). Certains trades V2 ne passeront pas V1
(RR trop bas, fenêtre étendue, type CROSS exclu).

---

## 3. Calcul V1 directement dans sweep_detector.py

> Ajoute un champ `is_elite_v1` dans `sweep_detector.py` pour que le calcul
> du filtre V1 soit fait en amont, comme c'est déjà le cas pour `is_elite` (v2).

**Où modifier :**
- `src/sweep_detector.py` dans la classe `AsianRangeResult` : ajouter `is_elite_v1: bool = False`
- Dans `detect_asian_range_for_symbol()` : dupliquer le bloc ELITE pour V1
- Importer `ELITE_V1` depuis `config`
- Avantage : `live_alerts.py` n'a plus besoin de recalculer les deux filtres

---

## 4. Recalcul P&L réaliste avec estimation des trades ouverts

> Recalcule le P&L total ELITE v2 en incluant une estimation conservative
> des 34 trades encore ouverts (ex: 50% considérés comme perdants).

```bash
python calc_elite_pnl.py
```

Ajouter une estimation Monte Carlo ou conservative dans le script :
- Scénario pessimiste : 50% des ouverts = perdants → winrate ~85-90%
- Scénario réaliste : 30% des ouverts = perdants → winrate ~90-93%
- Scénario optimiste : 10% des ouverts = perdants → winrate ~97%

---

## 5. Ajouter ELITE V1 et V2 dans le rapport PDF live

> Ajoute les compteurs ELITE V1/V2 dans le rapport PDF généré par
> `generate_live_report.py`, dans la section récapitulative.

**Où modifier :**
- `generate_live_report.py` : après le scan, compter les trades V1 et V2
- Ajouter une ligne dans le résumé : `Trades ELITE V1: X | V2: Y | Fenetre: OUVERTE/FERMEE`

---

## 6. Dashboard Streamlit — filtres ELITE

> Ajoute un indicateur visuel ELITE V1/V2 dans le dashboard Streamlit
> (`app.py`), avec la possibilité de filtrer les trades par badge.

**Où modifier :**
- `app.py` : ajouter des colonnes ou des filtres pour V1/V2
- Afficher les badges avec les mêmes couleurs (jaune/cyan)

---

## 7. Notifications Discord pour les trades ELITE

> Envoie une notification Discord spécifique quand un trade ELITE V1 ou V2
> est détecté, via `discord_notifier.py`.

**Où modifier :**
- `live_alerts.py` ou `auto_scan_and_post.py` : après détection d'un trade ELITE,
  envoyer un embed Discord avec le badge concerné
- Couleurs : jaune/or pour V1, cyan/bleu pour V2

---

## 8. Analyse des 34 trades ouverts — combien sont vraiment gagnants ?

> Pour chaque trade ouvert ELITE v2, vérifier manuellement sur MT5
> si le TP ou le SL a été touché depuis le dernier backtest.

```bash
python analyze_open_elite.py
```

Puis pour chaque trade identifié comme "vers SL" (>50% de progression),
vérifier sur le graphique MT5 si le SL a été touché depuis.

---

## 9. Script de scan quotidien automatisé avec rapport ELITE

> Crée un batch/script qui lance le scanner à 08:30 UTC chaque jour,
> génère un rapport PDF, et affiche un récapitulatif ELITE V1/V2.

```bash
# Idée : scheduled_scan.bat amélioré
python live_alerts.py --interval 30 --no-sound &
# Attendre 30 min, puis générer rapport
python generate_live_report.py
# Afficher le résumé ELITE
```

---

## 10. Ajouter un test unitaire pour les filtres ELITE

> Écris un test unitaire qui vérifie que les fonctions `_is_elite_trade()`
> avec `ELITE_V1` et `ELITE` config retournent les bons résultats pour
> différents cas (heure, type, RR, spread).

```bash
pytest tests/test_elite_filters.py -v
```

**Cas à tester :**
- Trade dans fenêtre V1 ET V2 → les deux badges
- Trade hors fenêtre V1 mais dans V2 → badge V2 uniquement
- Trade avec RR < 0.5 → V1 exclu, V2 accepté
- Trade FOREX_CROSS → V1 accepté, V2 exclu
- ELITE désactivé → aucun badge
- Spread > 0.50% → aucun badge
