# agronomy_engine — journal des versions

La version du moteur (`ENGINE_VERSION`) est enregistrée avec chaque résultat de calcul. Toute modification de formule doit l'incrémenter et être décrite ici.

## 1.0.0 — 2026-11-08
- `planting.density` : densité théorique et réelle, surface plantable, disposition géométrique en lignes simples ou en planches.
- `planting.seeds` : semis direct et repiquage, masse de semences, conditionnement.
- `calendar.phases` : enchaînement des phases et propositions de tâches.
- Le nombre de plants théorique est calculé comme `floor(k × Sp / (Er × Ep))`, la division étant faite en dernier, pour éviter une erreur d'arrondi décimal.
