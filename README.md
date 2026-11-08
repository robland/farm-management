# Farm Management System (FMS)

Plateforme de gestion agricole multi-exploitations : de la conception des plans de production jusqu'à la récolte et au bilan économique, avec un fonctionnement hors ligne et un assistant IA facultatif.

> Le document est mis à jour à chaque phase de développement. L'état détaillé figure dans `IMPLEMENTATION_PLAN.md` (section « Suivi »). Les points à valider avec le porteur du projet sont dans `OPEN_QUESTIONS.md`.

## Documentation

| Document | Contenu |
|---|---|
| `PROJECT_CONTEXT.md`, `REQUIREMENTS.md` | Vision et exigences (source d'autorité) |
| `ARCHITECTURE.md` | Architecture générale et décisions techniques |
| `DATABASE_SCHEMA.md` | Modèle de données et diagrammes ERD |
| `docs/architecture/OFFLINE_SYNC.md` | Protocole hors ligne et synchronisation |
| `docs/architecture/AGRONOMY_ENGINE.md` | Formules, unités et hypothèses du moteur agronomique |
| `IMPLEMENTATION_PLAN.md` | Phases et suivi d'avancement |
| `OPEN_QUESTIONS.md` | Questions ouvertes et choix par défaut appliqués |
| `/api/v1/docs/` | Documentation interactive de l'API (OpenAPI), une fois le serveur lancé |

## Structure du dépôt

```
backend/                 API Django / DRF (Python 3.12, uv)
  agronomy_engine/       moteur de calcul déterministe (Python pur, sans Django)
  apps/                  modules métier (organisations, exploitations, parcelles, variétés,
                         plans, irrigation, agronomie, tâches, finance, récolte, IA, synchro…)
  tests/                 tests transverses (isolation multi-tenant)
packages/sync-core/      moteur de file d'attente et de synchronisation (TypeScript, partagé)
packages/shared/         libellés, formatage (montants, dates, surfaces) et règles d'affichage
                         communs au Web et au mobile (TypeScript pur, sans dépendance)
frontend/web/            client Web (React 19, TypeScript strict, Tailwind 4, IndexedDB/Dexie)
mobile/app/              application mobile (Expo SDK 58, React Native, SQLite)
docker-compose.yml       PostgreSQL 17, Redis, MinIO pour le développement
```

## Prérequis

- Python 3.12 et [uv](https://docs.astral.sh/uv/)
- Node.js 22.12 ou plus récent, et npm
- Docker (PostgreSQL de développement)

## Démarrage

```bash
# 1. Variables d'environnement (aucun secret n'est versionné)
cp .env.example .env            # puis renseigner DJANGO_SECRET_KEY

# 2. Base de données
docker compose up -d db

# 3. Backend
cd backend
uv sync                          # ajouter --extra ai pour l'adaptateur IA Anthropic
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver   # http://localhost:8000/api/v1/docs/

# 4. Client Web (autre terminal, depuis la racine du dépôt)
npm install
npm run dev --workspace web      # http://localhost:5173 (proxy /api vers le backend)
```

## Tests et qualité

```bash
# Backend (PostgreSQL de docker compose requis)
cd backend
uv run pytest                    # tests unitaires, API, permissions, multi-tenant, finance, synchro
uv run ruff check . && uv run ruff format --check .
uv run mypy apps config agronomy_engine
uv run python manage.py spectacular --fail-on-warn --validate --file openapi.yaml  # export du schéma

# TypeScript (depuis la racine)
npm run typecheck
npm test
```

Règles : les tests tournent sur un vrai PostgreSQL (pas SQLite), aucun test n'est désactivé pour faire passer la suite, et une phase n'est close qu'une fois ses tests exécutés.

## Configuration principale

| Variable | Rôle | Défaut |
|---|---|---|
| `DATABASE_URL` | Connexion PostgreSQL | `postgres://fms:fms@localhost:55432/fms` |
| `DJANGO_SECRET_KEY` | Clé secrète (obligatoire) | — |
| `JWT_ACCESS_MINUTES` / `JWT_REFRESH_DAYS` | Durée des jetons (Q16) | 15 / 30 |
| `FMS_FILE_STORAGE_ROOT` | Stockage privé des fichiers | `backend/media` |
| `FMS_AI_PROVIDER` | `null` (assistant désactivé) ou `anthropic` | `null` |
| `FMS_AI_MODEL` | Modèle utilisé par l'adaptateur | `claude-opus-5-5` |
| `FMS_AI_MONTHLY_REQUEST_LIMIT` | Quota mensuel d'appels IA par organisation | 200 |
| `ANTHROPIC_API_KEY` | Clé du fournisseur IA (si `FMS_AI_PROVIDER=anthropic`) | — |

Sans fournisseur IA, toutes les fonctions restent disponibles en saisie manuelle (FR-106).

## État d'avancement

| Phase | Contenu | État |
|---|---|---|
| 0 | Socle technique (Django 5.2 LTS, DRF, OpenAPI, Docker, CI) | ✅ |
| 1 | Authentification et appareils, organisations, rôles, invitations, exploitations, champs et parcelles, audit, isolation multi-tenant | ✅ |
| 2 | Synchronisation serveur : push/pull idempotents, fusion à trois, conflits | ✅ |
| 3 | Fichiers, cultures, variétés, fiches et données techniques validées | ✅ |
| 4 | Moteur agronomique (densités, semences, calendrier) et plans de production versionnés | ✅ |
| 5 | Irrigation goutte-à-goutte, nomenclature, catalogue, devis multi-fournisseurs | ✅ |
| 6 | Programme agronomique, observations, tâches, comptes rendus, consommations | ✅ |
| 7 | Trésorerie : comptes, dépenses et recettes, transferts, annulations, soldes, budgets | ✅ |
| 8 | Récoltes, rendements, bilan de campagne | ✅ |
| 9 | Assistant IA (extraction de fiches, brouillons de plans, coûts) | ✅ |
| 10 | Client Web hors ligne (sync-core, IndexedDB, service worker, parcelles, tâches, dépenses, synchronisation) | ✅ |
| 11 | Application mobile (Expo SDK 58, SQLite, Expo Router) | ✅ |
| 12 | Durcissement et déploiement pilote | 🚧 en cours |

Bilan à ce stade : 627 tests backend (dont le scénario MVP complet de bout en bout et la génération du schéma OpenAPI sans avertissement), 15 tests du moteur de synchronisation, 15 tests du paquet partagé `@fms/shared`, 20 tests du client Web et 7 tests mobiles passent ; ruff, mypy et le typage TypeScript strict sont propres ; le build Web de production réussit ; `expo-doctor` ne signale aucun problème.

### Application mobile

```bash
cd mobile/app
npm install          # projet autonome, hors des workspaces npm (versions React propres à Expo)
npx expo start       # puis un émulateur Android ou un « development build »
npm run typecheck
npm test
```

- L'adresse de l'API se règle dans `app.json` → `expo.extra.apiBaseUrl` (par défaut `http://10.0.2.2:8000/api/v1`, c'est-à-dire la machine hôte vue depuis l'émulateur Android).
- Le jeton de rafraîchissement, l'identifiant d'appareil et l'utilisateur courant sont dans le stockage sécurisé du système (SecureStore). La file d'opérations, les données et le profil en cache sont dans une base SQLite propre à chaque utilisateur.
- Écrans de terrain : tâches (démarrer, terminer avec compte rendu), observations, récoltes, dépenses et synchronisation (réessayer ou abandonner). Toutes les saisies fonctionnent hors ligne.

### Client Web

- Toutes les saisies (parcelles, statuts et comptes rendus de tâches, dépenses) sont d'abord écrites dans IndexedDB, puis envoyées par la file de synchronisation. Elles fonctionnent donc sans réseau.
- La synchronisation s'exécute au démarrage, au retour du réseau, chaque minute et deux secondes après une saisie, avec un seul onglet actif à la fois (Web Locks).
- Chaque élément affiche son statut local (en attente, refusé, conflit). L'onglet « Synchronisation » permet de réessayer ou d'abandonner explicitement une opération.
- Le service worker garde l'application disponible hors ligne (build de production uniquement).

### Interface d'administration Django

`/admin/`, réservée au personnel de la plateforme (`is_staff`). Être administrateur d'une organisation ne donne pas accès à l'admin.

```bash
uv run python manage.py createsuperuser   # depuis backend/
```

- **Tous les modèles sont consultables** : listes avec filtres (statut, type, éléments supprimés), recherche par nom ou par identifiant exact, organisation et exploitation affichées, lignes liées sur la fiche (écritures d'une transaction, nomenclature d'une conception, articles d'un tarif, historique des statuts d'une tâche, consommation IA…).
- **Les données métier sont en lecture seule.** Les modifications passent par les services : permissions, versions, journal d'audit et journal de synchronisation (Q28). Modifier une parcelle depuis l'admin ne serait jamais redescendu aux clients hors ligne. Une transaction financière ne se modifie pas : elle s'annule ou se corrige par l'API.
- **Seules exceptions**, toutes inscrites au journal d'audit :
  - le référentiel commun des cultures, qu'aucune API ne permet de créer. Les cultures d'une organisation restent en lecture seule ;
  - les comptes utilisateurs : activation, nom et langue. Les droits `is_staff` et `is_superuser` ne peuvent être donnés que par un superutilisateur ;
  - la révocation d'appareils (téléphone perdu), proposée comme action.
- Les secrets (mot de passe haché, jeton d'invitation haché) ne sont jamais affichés. Un membre du personnel sans droit de consultation sur un modèle reçoit un refus (403).

### Ergonomie commune (Web et mobile)

- **Aucune saisie en double** : chaque bouton d'enregistrement est verrouillé pendant l'écriture. Un double clic sur « Enregistrer la dépense » crée une seule transaction. Une tâche dont le compte rendu attend l'envoi n'affiche plus « Terminer » : le serveur accepterait un second compte rendu.
- **Confirmations** : terminer une tâche (avec notes facultatives), abandonner une saisie et se déconnecter avec des saisies non envoyées demandent une confirmation. Sur le Web, Échap annule.
- **Langage clair** : l'écran Synchronisation décrit chaque saisie (« Dépense de 15 000 XAF », « Tâche : À faire → En cours ») et explique les refus du serveur. Le contenu est résumé, sans JSON brut. Les rôles et statuts sont traduits.
- **Formats français** : montants groupés à la précision de la devise, sans calcul en virgule flottante. Dates « 8 nov. 2026 », surfaces en m² avec leur équivalent en hectares.
- **Retour après enregistrement** : un message confirme que la saisie est conservée sur l'appareil et sera envoyée.
- **Tâches** regroupées en « En retard », « Du jour », « À venir » ; la date du jour est celle du fuseau de l'appareil.
- **Raccourcis** : une exploitation, un compte ou une parcelle unique est présélectionné.
- **Petits écrans et terrain** : zones tactiles d'au moins 44 px (Web) ou 48 dp (mobile), focus clavier visible. Sur mobile, les boutons répondent dès la première pression avec le clavier ouvert, et on peut tirer vers le bas pour synchroniser.
- Les libellés et le formatage sont dans `packages/shared`, testés une seule fois pour les deux clients.

## Limites connues

- Les appels IA sont synchrones : Celery n'est pas encore en place (Q24).
- Côté Web, le jeton de rafraîchissement est stocké dans `localStorage`. Il doit passer en cookie `HttpOnly` lors du durcissement (Q26).
- Le stockage des fichiers est local en développement ; un stockage compatible S3 reste à configurer pour la production.
- Les ventes sont modélisées comme des recettes liées au cycle cultural (Q23).
- Le client Web couvre pour l'instant les écrans de terrain (parcelles, tâches, dépenses, synchronisation). La conception des plans, l'irrigation et les rapports passent par l'API (documentation `/api/v1/docs/`) en attendant leurs écrans.
- Le scénario MVP est testé de bout en bout au niveau de l'API. Les tests d'interface (Playwright) et les tests de charge restent à faire.
- L'isolation entre organisations est appliquée côté serveur par le contexte de tenant. La RLS PostgreSQL n'est pas encore activée (Q27).
- Le monorepo JavaScript utilise les workspaces npm. jsdom est fixé en version 26 à la racine, car les versions récentes exigent Node 22.15 ou plus.
