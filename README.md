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
| `docs/functional/PLANNING_SCENARIOS.md` | Scénarios d'utilisation de la planification de production |
| `IMPLEMENTATION_PLAN.md` | Phases et suivi d'avancement |
| `OPEN_QUESTIONS.md` | Questions ouvertes et choix par défaut appliqués |
| `docs/operations/DEPLOYMENT.md` | Déploiement pilote, mise à jour, retour arrière, sauvegardes, surveillance |
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
docker-compose.yml       PostgreSQL 17 pour le développement (Redis réservé, profil « jobs »)
deploy/                  pile du pilote : compose.pilot.yml, Caddyfile, .env.example
scripts/                 sauvegarde (backup_db.sh) et restauration (restore_db.sh)
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
# Tests de charge (copie ou pile de test uniquement) : voir backend/loadtest/README.md

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
| `JWT_SIGNING_KEY` | Clé de signature des jetons, renouvelable séparément ; si elle est vide, la clé secrète est utilisée | `DJANGO_SECRET_KEY` |
| `FMS_REFRESH_COOKIE_SECURE` | Cookie de rafraîchissement Web limité à HTTPS (Q26) | `true` (`false` en développement) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origine publique derrière le proxy (production), par exemple `https://pilote.example.org` | — |
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

Bilan à ce stade : 836 tests backend (dont le scénario MVP complet de bout en bout, la génération du schéma OpenAPI sans avertissement, les parcours de l'interface d'administration, le cookie de rafraîchissement, les apports des membres et les emprunts), 15 tests du moteur de synchronisation, 27 tests du paquet partagé `@fms/shared`, 26 tests du client Web et 8 tests mobiles passent ; ruff, mypy et le typage TypeScript strict sont propres ; le build Web de production réussit ; `expo-doctor` ne signale aucun problème.

### Déploiement pilote

Serveur unique. Les commandes, la mise à jour, le retour arrière, les sauvegardes et la surveillance sont détaillés dans `docs/operations/DEPLOYMENT.md`.

```bash
cp deploy/.env.example deploy/.env        # domaine, e-mail ACME, secrets
docker compose -f deploy/compose.pilot.yml --env-file deploy/.env up -d --build
docker compose -f deploy/compose.pilot.yml --env-file deploy/.env run --rm backup   # sauvegarde
```

- **Composants** : Caddy (HTTPS automatique, client Web, en-têtes de sécurité, CSP stricte), API Django sous gunicorn (fichiers statiques de l'admin servis par WhiteNoise) et PostgreSQL 17. Seul le proxy est exposé.
- **Migrations** : appliquées automatiquement avant chaque démarrage de l'API. En cas d'échec, l'ancienne version reste en place.
- **Sauvegarde** : la base et les fichiers stockés sont sauvegardés ensemble. La restauration de la base se fait en une seule transaction.
- **Session Web** : le jeton de rafraîchissement est dans un cookie `HttpOnly` (Q26). Aucun script ne peut le lire.

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
- Écrans de terrain : tâches (démarrer, terminer avec compte rendu), observations, récoltes, finances et synchronisation (réessayer ou abandonner). Toutes les saisies fonctionnent hors ligne.
- **Finances** (selon les droits) : soldes de la dernière synchronisation, saisie hors ligne d'une dépense, d'une recette ou d'un transfert (compte et catégorie en pastilles), opérations à valider avec validation ou rejet motivé (en ligne), dernières opérations. Le **membre contributeur** a son écran « Mon compte de membre » : apport, puis transfert à la trésorerie dans la limite du solde validé. Budgets, emprunts et gestion des comptes : sur le Web.
- **Campagne** : consultation hors ligne des plans validés (chiffres clés du moteur, calendrier et phase en cours, lien vers les tâches). Les brouillons sont listés sans être ouvrables : la conception se fait sur le Web (Q7).
- Dès la connexion, l'en-tête de chaque écran porte la cloche des notifications et le bouton profil.
  - La cloche ouvre l'écran Notifications, avec ses filtres, son action « Tout marquer comme lu » et des liens vers Tâches, Campagne, Finances et Synchronisation. L'historique est conservé dans la base SQLite de l'utilisateur.
  - Le bouton profil ouvre l'écran Profil (nom, contact, rôle). On peut y changer d'exploitation et s'y déconnecter, avec une confirmation s'il reste des saisies non envoyées.
- Sur le choix d'exploitation, les exploitations sont regroupées par organisation. « Créer une exploitation » est réservé aux administrateurs de l'organisation ; la création nécessite le réseau.
- Icônes : `@expo/vector-icons` (Ionicons), avec `expo-font`, qu'elle requiert.

### Client Web

- Toutes les saisies (parcelles, statuts et comptes rendus de tâches, opérations financières) sont d'abord écrites dans IndexedDB, puis envoyées par la file de synchronisation. Elles fonctionnent donc sans réseau.
- **Onglet Campagnes** (droit `plans.view`) : synthèse d'une campagne (plans, surface engagée, tâches, budget), liste des plans et frise d'occupation des parcelles. Un plan s'ouvre sur son **éditeur** s'il est en brouillon (en-tête, parcelles avec alerte d'occupation, paramètres de plantation avec l'origine de chaque valeur, calendrier, liste « À compléter » issue du calcul, suggestions de l'IA à accepter, modifier ou rejeter, pré-remplissage, calcul, validation) ou sur ses **résultats** s'il est validé (densités théorique et réelle, plants, semences, traçabilité du calcul, calendrier et tâches, versions et comparaison, nouvelle version, génération des tâches). Lecture hors ligne ; écriture en ligne avec contrôle de version (`If-Match`).
- **Onglet Finances** (remplace « Dépenses ») : vue d'ensemble (soldes validés, trésorerie par jour, semaine ou mois, résultat de campagne, opérations à valider), journal filtrable avec fiche d'opération et historique, validation, rejet, annulation et correction avec motif obligatoire, budgets par campagne (prévu, réalisé, attente, écarts), comptes, comptes de membres et emprunts, « Mon compte de membre ». Ce qui est affiché dépend des droits ; le serveur les applique.
- La synchronisation s'exécute au démarrage, au retour du réseau, chaque minute et deux secondes après une saisie, avec un seul onglet actif à la fois (Web Locks).
- Chaque élément affiche son statut local (en attente, refusé, conflit). L'onglet « Synchronisation » permet de réessayer ou d'abandonner explicitement une opération.
- Le service worker garde l'application disponible hors ligne (build de production uniquement).

### Trésorerie : apports des membres, compte principal et emprunts (Q35)

Le circuit de l'argent :
1. Un membre du groupe envoie des fonds au chef d'exploitation (hors plateforme).
2. Il ouvre son **compte de membre** (`POST …/treasury-accounts/mine/`), puis enregistre un **apport** (`kind=funding`) avec un justificatif (photo ou PDF, usage `funding_proof`).
3. Le chef d'exploitation vérifie le justificatif et **valide** l'apport. Un apport n'est jamais validé à l'enregistrement.
4. Le membre **transfère** le montant vers le **compte principal** (la trésorerie), dans la limite de son solde validé. Le transfert est validé immédiatement ; sans destination indiquée, il part vers le compte principal.
5. Le chef d'exploitation enregistre les **dépenses** depuis le compte principal ou un compte d'exploitation (caisse de terrain alimentée par transfert).

Règles :
- Chaque compte a un rôle : principal (un seul par exploitation ; le premier compte créé l'est par défaut), membre (un titulaire) ou exploitation.
- Un compte de membre ne porte ni dépense, ni recette, ni transfert entrant. Seul son titulaire y enregistre un apport ou en retire de l'argent.
- Le rôle **Membre contributeur** (droit `finance.funding.create`) ne voit que ses propres comptes, ses mouvements et ses justificatifs. Le relevé `…/treasury-accounts/members/` présente, par membre, les montants apportés, transférés et le solde.
- **Emprunts** (`…/loans/`) : le déblocage est un apport lié à l'emprunt, sur le compte principal, dans la limite du montant emprunté. Le remboursement du capital (`kind=repayment`) part du compte principal, dans la limite du capital restant dû. Les intérêts sont une dépense. `…/loans/positions/` donne les montants débloqués, remboursés et le capital restant dû.
- **Catégories** : le type « investissement » sert aux apports et aux financements. Le marqueur « dépense d'investissement » (machine, irrigation) s'applique aux catégories de dépense. Une subvention est une recette.
- **Rapports** : la trésorerie distingue les recettes, les charges de campagne, les investissements, les apports et financements, les remboursements et les transferts. **La marge de campagne n'intègre ni les apports, ni les transferts, ni les remboursements, ni les investissements.**

### Interface d'administration Django

`/admin/`, réservée au personnel de la plateforme (`is_staff`). Être administrateur d'une organisation ne donne pas accès à l'admin.

```bash
uv run python manage.py createsuperuser   # depuis backend/
```

- **Tous les modèles sont consultables** : listes avec filtres (statut, type, éléments supprimés), recherche par nom ou par identifiant exact, organisation et exploitation affichées, lignes liées sur la fiche (écritures d'une transaction, nomenclature d'une conception, articles d'un tarif, historique des statuts d'une tâche, consommation IA…).
- **Création, modification, suppression et parcours métier depuis l'admin, toujours par les services** (Q34). L'admin n'écrit jamais directement dans les tables. Il appelle le même service que l'API, avec les droits de l'organisation concernée. Les garanties restent donc les mêmes :
  - **version** : le formulaire envoie la version affichée ; une modification faite entre-temps est refusée, sans écrasement ;
  - **cohérence** : une référence d'une autre organisation ou exploitation est refusée. Les listes déroulantes d'une fiche n'offrent que celles de son exploitation ; pour une création, `?farm=<id>` (ou `?organization=<id>`) dans l'adresse filtre les listes ;
  - **traçabilité** : journal d'audit au nom du membre du personnel, et journal de synchronisation (les appareils hors ligne reçoivent les changements) ;
  - **pas de doublon** : les formulaires de saisie (parcelles, observations, comptes rendus, récoltes, transactions, solde d'ouverture) portent un identifiant généré à l'affichage. Un double clic rejoue la première saisie ;
  - **suppression** : une à une, par le service (marque de suppression pour les parcelles et champs). La suppression en masse est retirée.
- **Parcours disponibles** (actions de la liste, à appliquer aux lignes cochées) :

  | Domaine | Création / modification | Actions |
  |---|---|---|
  | Organisations | organisation (avec son administrateur), rôles et permissions, membres, invitations (jeton affiché une seule fois) | révoquer une invitation |
  | Exploitations | exploitation, membres et rôles | — |
  | Terrain | champs, parcelles, historique cultural | — |
  | Référentiels | cultures (commun ou propre), variétés, fiches techniques (envoi du PDF), jeux et éléments de données techniques | valider des éléments, valider un jeu, extraction par l'IA |
  | Catalogue | fournisseurs, articles, tarifs, prix (tarif brouillon) | — |
  | Plans | campagnes, plans, en-tête de version, spécification de plantation, affectations de parcelles, phases | préremplir, calculer, recalculer le programme, valider, nouvelle version, générer les tâches |
  | Programme agronomique | produits, fertilisations, traitements, irrigation planifiée, observations | — |
  | Irrigation | conceptions, lignes manuelles, liaison au catalogue, devis, prix des lignes | calculer, valider, nouvelle version ; émettre, décision du client |
  | Tâches | équipes, tâches, comptes rendus | changer le statut, affecter |
  | Finance | comptes (rôle principal ou exploitation), catégories (marqueur investissement), dépenses, recettes, transferts, apports sur le compte principal, emprunts, remboursements, modification d'une transaction soumise, lignes budgétaires, ventilations | valider (dont les apports des membres), rejeter, annuler, corriger (motif obligatoire), solde d'ouverture, définir le compte principal |
  | Récoltes | conversions mesurées, récoltes | annuler une récolte (motif) |
  | Synchronisation | — | résoudre un conflit |
  | IA | — | décider d'une suggestion (accepter, rejeter, modifier) |

- **Ce qui reste impossible, même pour un superutilisateur** : modifier ou supprimer une transaction validée (annulation ou correction seulement), modifier une version de plan, une conception ou un jeu de données validés, modifier un tarif actif. Les journaux (audit, synchronisation, écritures, appels IA) sont en lecture seule.
- **Comptes** : activation, nom et langue, avec audit. Seul un superutilisateur peut donner `is_staff` ou `is_superuser`. Les appareils peuvent être révoqués (téléphone perdu).
- **Droits** : chaque membre du personnel a besoin des droits Django du modèle (`view_`, `add_`, `change_`, `delete_`). Les actions demandent le droit `change_`. Sans droit, la réponse est 403. Les secrets (mot de passe haché, jeton d'invitation haché) ne sont jamais affichés.

### Ergonomie commune (Web et mobile)

- **Aucune saisie en double** : chaque bouton d'enregistrement est verrouillé pendant l'écriture. Un double clic sur « Enregistrer la dépense » crée une seule transaction. Une tâche dont le compte rendu attend l'envoi n'affiche plus « Terminer » : le serveur accepterait un second compte rendu.
- **Confirmations** : terminer une tâche (avec notes facultatives), abandonner une saisie et se déconnecter avec des saisies non envoyées demandent une confirmation. Sur le Web, Échap annule.
- **Langage clair** : l'écran Synchronisation décrit chaque saisie (« Dépense de 15 000 XAF », « Tâche : À faire → En cours ») et explique les refus du serveur. Le contenu est résumé, sans JSON brut. Les rôles et statuts sont traduits.
- **Formats français** : montants groupés à la précision de la devise, sans calcul en virgule flottante. Dates « 8 nov. 2026 », surfaces en m² avec leur équivalent en hectares.
- **Notifications (Web et mobile)** : une cloche avec un compteur de notifications non lues est présente sur tous les écrans dès la connexion, y compris le choix d'exploitation. Le panneau regroupe :
  - les problèmes de synchronisation (saisie refusée, erreur locale) ;
  - les incohérences à vérifier (conflits) ;
  - les succès (saisie enregistrée sur l'appareil, saisies envoyées, exploitation créée) ;
  - les nouvelles informations (tâches planifiées reçues à la synchronisation).

  Le panneau propose des filtres par type et l'action « Tout marquer comme lu ». L'historique est conservé dans le navigateur, par utilisateur, avec 50 notifications au plus. La file de synchronisation reste la référence.
- **Profil (Web et mobile)** : un bouton rond aux initiales ouvre le compte (nom, contact, rôle). La déconnexion s'y trouve : dans un menu sur le Web, sur l'écran Profil sur mobile.
- **Création d'exploitation (Web et mobile)** : sur l'écran de choix, regroupé par organisation, le bouton « Créer une exploitation » n'apparaît que pour les administrateurs de l'organisation (droit `org.manage`). Le formulaire est prérempli avec le pays, la devise et le fuseau de l'organisation. La création nécessite le réseau.
- **Tâches** regroupées en « En retard », « Du jour », « À venir » ; la date du jour est celle du fuseau de l'appareil.
- **Raccourcis** : une exploitation, un compte ou une parcelle unique est présélectionné.
- **Petits écrans et terrain** : sur le Web, les boutons font 44 px de haut sur téléphone et 36 px à partir de 640 px de large. Sur mobile, les zones tactiles font 48 dp. Le focus clavier est visible. Le mot de passe s'affiche ou se masque avec une icône œil. Sur mobile, les boutons répondent dès la première pression avec le clavier ouvert, et on peut tirer vers le bas pour synchroniser.
- Les libellés et le formatage sont dans `packages/shared`, testés une seule fois pour les deux clients.

## Limites connues

- Les appels IA sont synchrones : Celery n'est pas encore en place (Q24).
- Pilote sur un serveur unique, sans haute disponibilité : la perte maximale correspond aux données saisies depuis la dernière sauvegarde quotidienne. Pendant une panne, les appareils continuent de fonctionner hors ligne.
- Le stockage des fichiers est local en développement ; un stockage compatible S3 reste à configurer pour la production.
- Les ventes sont modélisées comme des recettes liées au cycle cultural (Q23).
- Le client Web couvre les écrans de terrain, les campagnes et les finances. L'irrigation, le programme agronomique et les référentiels (variétés, fiches techniques) passent encore par l'API (`/api/v1/docs/`) ou l'admin.
- Finances : les rapports renvoient leurs montants en nombres JSON (Q37) ; le magasinier ne peut pas lister les comptes (Q38) ; le rattachement au budget et l'envoi de justificatifs depuis les écrans restent à faire (Q39).
- Le scénario MVP est testé de bout en bout au niveau de l'API. Les tests d'interface (Playwright) restent à faire. Les tests de charge sont faits (`backend/loadtest/README.md`) ; le premier pull complet d'un appareil reste lent (1 à 3 s).
- Apports des membres : saisis hors ligne depuis les écrans « Mon compte de membre » (Web et mobile) et validés en ligne. Le rôle Membre contributeur ne reçoit pas de données financières par la synchronisation : son solde et ses mouvements viennent de l'API, avec le dernier état connu hors ligne.
- L'isolation entre organisations est appliquée côté serveur par le contexte de tenant. La RLS PostgreSQL n'est pas encore activée (Q27).
- Le monorepo JavaScript utilise les workspaces npm. jsdom est fixé en version 26 à la racine, car les versions récentes exigent Node 22.15 ou plus.
