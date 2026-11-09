# Tests de charge

Scénario Locust (`locustfile.py`). Chaque utilisateur virtuel est un gestionnaire d'exploitation qui suit le parcours de l'application mobile :
- connexion ;
- profil ;
- listes de parcelles et de tâches ;
- synchronisation (pull, puis push d'une modification de parcelle) ;
- saisie de dépenses avec clé d'idempotence ;
- soldes.

Entre deux actions, l'utilisateur attend de 2 à 6 s, le temps de lire ou de saisir.

## Exécution

Les tests de charge se lancent sur une **copie** ou une pile de test, jamais sur le pilote : ils créent des données fictives.

```bash
# 1. Données fictives (organisation « CHARGE — données fictives », 20 comptes, 50 parcelles)
LOAD_TEST_PASSWORD=... uv run python manage.py prepare_load_test --confirm --users 20 --parcels 50
#    (pile pilote : docker compose ... exec -e LOAD_TEST_PASSWORD=... api python manage.py ...)

# 2. Charge (dépendances du groupe « load », non installées par défaut)
LOAD_TEST_PASSWORD=... uv run --group load locust -f loadtest/locustfile.py \
  --host https://localhost:8443 --users 20 --spawn-rate 0.3 --run-time 5m --headless
```

La montée en charge est volontairement lente (0,3 utilisateur par seconde) : la connexion est limitée à 20 par minute et par adresse IP. C'est une protection contre les attaques par force brute, à conserver.

## Résultats du 9 novembre 2026

Pile pilote exécutée localement : Docker Desktop sous Windows, gunicorn avec 3 workers, Caddy et TLS. Le client de charge tournait sur la même machine. Il n'existe pas encore de cible chiffrée dans les exigences (Q36).

| Charge | Requêtes | Erreurs | Médiane | p95 | p99 | p95 `sync/pull` | p95 `sync/push` |
|---|---|---|---|---|---|---|---|
| 20 utilisateurs, 4 min | 1 138 | 0 | 41 ms | 160 ms | 330 ms | 220 ms | 140 ms |
| 60 utilisateurs, 7 min | 5 088 | 0 | 40 ms | 270 ms | 660 ms | 520 ms | 150 ms |
| 60 utilisateurs, 7 min, après la correction N+1 | 5 068 | 0 | 39 ms | 310 ms | 850 ms | 640 ms | 170 ms |

La troisième mesure portait sur une base plus chargée : environ 900 modifications de plus dans le journal de synchronisation.

Constats :
- **Aucune erreur**, y compris à 3 fois la charge d'un pilote d'une vingtaine d'utilisateurs.
- La **connexion** atteint environ 1 s au p95. C'est voulu : le hachage argon2 est coûteux par conception.
- **N+1 corrigé dans le pull de synchronisation** : chaque transaction coûtait 2 requêtes de plus (écritures, pièces jointes). On mesurait 16 requêtes pour 5 modifications et 86 pour 40. Les gestionnaires de synchronisation préchargent désormais leurs relations : transactions, tâches, comptes rendus et observations. `tests/test_query_counts.py` vérifie que le nombre de requêtes reste constant.
- **Point restant : le premier pull d'un appareil.** Depuis le curseur 0, il lit 500 entrées du journal, soit 220 modifications distinctes et 186 Ko. Il prend de 1,1 à 2,8 s. Un pull incrémental de 20 modifications prend environ 0,2 s. L'analyse (profilage de la sérialisation) n'est pas faite. Pistes : réduire la taille de la page du premier pull, ou servir un instantané initial compressé.
- Les queues de latence (p99) touchent tous les points d'accès en même temps. Elles indiquent une saturation ponctuelle des 3 workers synchrones dans cet environnement partagé. À mesurer de nouveau sur le serveur cible avant de dimensionner le nombre de workers.
