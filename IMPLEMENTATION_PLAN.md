# IMPLEMENTATION_PLAN.md

> Mode de travail : phases enchaînées sans interruption (décision du porteur du projet, 2026-11-08). Les ambiguïtés sont consignées dans `OPEN_QUESTIONS.md` avec le choix par défaut appliqué.
> Règle : une phase n'est close que lorsque ses tests ont été **exécutés** et réussis. L'état réel est tenu dans la section « Suivi » en fin de document.

## Vue d'ensemble

| Phase | Objectif | Dépend de |
|---|---|---|
| 0 | Socle technique (outillage, Docker, squelette Django, CI) | — |
| 1 | Authentification, multi-tenant, organisations, exploitations, champs et parcelles, audit, fondations de la synchronisation | 0 |
| 2 | Protocole de synchronisation serveur (push/pull, idempotence, conflits) | 1 |
| 3 | Référentiel végétal, fichiers, fiches techniques, données techniques validées | 1 |
| 4 | Moteur agronomique (plantation, semences, calendrier) et plans de production versionnés | 3 |
| 5 | Irrigation : dimensionnement, nomenclature, catalogue, devis | 4 |
| 6 | Programme agronomique, tâches, comptes rendus, consommations, observations | 4, 2 |
| 7 | Trésorerie : comptes, transactions, transferts, soldes, budgets | 2, 4 |
| 8 | Récolte, rendements, bilan de campagne | 6, 7 |
| 9 | Assistant IA (extraction, génération de brouillons, coûts) | 3, 4 |
| 10 | Client Web (React/TS, IndexedDB, sync-core) | 2 (puis chaque module) |
| 11 | Application mobile (Expo, SQLite) | 10 (sync-core) |
| 12 | Durcissement : RLS, E2E, performances, déploiement pilote | toutes |

La synchronisation est conçue dès la Phase 1 : UUID, `version`, `ChangeLog`, `FarmSyncState` et handlers déclarés par module. Elle est livrée côté serveur en Phase 2, puis étendue à chaque module (handlers et tests de synchronisation dans les phases 6, 7 et 8).

---

## Phase 0 — Socle technique

- **Objectif** : un environnement reproductible où lint, typage et tests s'exécutent.
- **Fonctionnalités** : squelette Django `config/` (settings base/dev/test/prod via variables d'environnement), endpoint `/api/v1/health/`, OpenAPI (`/api/v1/schema/`, `/api/v1/docs/`), format d'erreur uniforme, docker-compose (postgres, redis, minio), `.env.example`, ruff, mypy, pytest, workflow CI.
- **Fichiers** : `backend/pyproject.toml`, `backend/config/*`, `backend/apps/core/*`, `docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml`, `.gitignore`, `Makefile`/`scripts/`.
- **Dépendances** : Django 5.2 LTS, DRF, drf-spectacular, simplejwt, django-filter, psycopg 3, django-environ, argon2-cffi. Outils de développement : ruff, mypy, django-stubs, djangorestframework-stubs, pytest, pytest-django, factory-boy, hypothesis.
- **Tests** : test du health check, test de chargement de la configuration, génération du schéma OpenAPI sans erreur.
- **Critères d'acceptation** : `docker compose up -d db` fonctionne, `pytest` réussit sur PostgreSQL, `ruff check`, `ruff format --check` et `mypy` sont propres.
- **Risques** : versions de dépendances (vérifiées et verrouillées par `uv.lock`), PostgreSQL sous Docker Desktop Windows.

## Phase 1 — Identité, tenancy, exploitations, parcelles

- **Objectif** : socle fonctionnel sécurisé (critères MVP 1 à 4 et 20).
- **Fonctionnalités** :
  - `users` : modèle `User` (e-mail ou téléphone), JWT (obtention, rafraîchissement, révocation), `Device`, `/me`.
  - `organizations` : Organization, OrganizationMembership, Role + RolePermission, catalogue des permissions, rôles initiaux créés à la création d'une organisation, Invitation (création, acceptation).
  - `farms` : Farm, FarmMembership, paramètres d'exploitation.
  - `core` : `TenantContext`, mixins de vue, querysets filtrés, `TenantPrimaryKeyRelatedField`, permissions DRF, `If-Match`/version, `Idempotency-Key`.
  - `audit` : AuditEvent en ajout seul.
  - `fields` : Field, Parcel (contrôles de superficie, pH, GeoJSON), suppression logique.
  - `synchronization` (fondations) : FarmSyncState, ChangeLog, service `record_change()` appelé par les services métier.
- **Fichiers** : `backend/apps/{users,organizations,farms,fields,audit,synchronization,core}/`, `backend/tests/tenancy/`.
- **Tests** : unitaires des services ; API CRUD ; **suite multi-tenant générée** (inter-organisations, inter-exploitations, rôles, références étrangères) ; concurrence optimiste (`428`, `409`) ; audit ; ChangeLog écrit à chaque modification.
- **Critères d'acceptation** : deux organisations sans fuite ; un utilisateur avec des rôles différents sur deux exploitations ; création et configuration d'une parcelle ; chaque endpoint couvert par la suite d'isolation.
- **Risques** : oubli de filtrage sur un endpoint (mitigé par le test de couverture des routes).

## Phase 2 — Synchronisation serveur

- **Objectif** : protocole push/pull idempotent avec détection des conflits (OFFLINE_SYNC §4 à §9).
- **Fonctionnalités** : `POST /sync/push`, `GET /sync/pull`, `SyncOperationReceipt`, `SyncConflict` (liste, résolution), registre de handlers par `entity_type`, fusion à trois, purge sur révocation. Premiers handlers : `fields.field`, `fields.parcel`.
- **Tests** : rejeu, réutilisation de clé, push concurrent (threads), lot partiellement refusé, fusion ou conflit, pull paginé et filtré, tombstones, isolation.
- **Critères d'acceptation** : critères MVP 17 et 18 sur les parcelles.
- **Risques** : sérialisation par exploitation (performances) : mesurée par un test de charge simple.

## Phase 3 — Référentiel végétal et fichiers

- **Fonctionnalités** : `files` (StoredFile, stockage S3/MinIO ou système de fichiers en test, URL pré-signée, détection du type MIME, contrôle d'accès) ; `crops` (Crop global ou de l'organisation) ; `varieties` (Variety, TechnicalDocument, TechnicalDataSet/Item, versionnage, validation FR-023).
- **Tests** : accès aux fichiers entre organisations, type MIME falsifié, validation unique par variété, immutabilité d'un jeu validé.
- **Critères d'acceptation** : critère MVP 5.

## Phase 4 — Moteur agronomique et plans de production

- **Fonctionnalités** : `agronomy_engine` (units, planting, seeds, calendar) ; `production_plans` (Campaign, ProductionPlan, PlanVersion, PlanAllocation, PlantingSpec, PlanPhase, FieldProvenance, CalculationResult, CropCycle) ; services : créer un brouillon, copier une version, calculer, valider (permission `plans.validate`), comparer deux versions (différence des hypothèses).
- **Tests** : cas de référence et propriétés du moteur ; une seule version validée ; immutabilité ; contrôle d'occupation des parcelles ; différence entre versions ; permissions.
- **Critères d'acceptation** : critères MVP 7 et 8 (création manuelle).

## Phase 5 — Irrigation et devis

- **Fonctionnalités** : moteur `irrigation/drip`, `bom`, `quotation` ; `inventory` (Supplier, CatalogItem, PriceList) ; `irrigation` (IrrigationDesign versionné, BomLine, Quote/QuoteLine avec prix copiés).
- **Tests** : hydraulique (valeurs de référence), distinction volume et débit, secteurs, prix copiés (une modification de la liste n'altère pas un devis émis), plusieurs fournisseurs.
- **Critères d'acceptation** : critère MVP 9.

## Phase 6 — Programme agronomique et tâches

- **Fonctionnalités** : `agronomy` (InputProduct, PlannedFertilization, PlannedPhytoIntervention, PlannedIrrigation, Observation) ; moteur `inputs` ; `tasks` (Team, Task, Assignment, StatusEvent, TaskReport, InputConsumption), génération à partir de la version validée, régénération FR-064, statut « en retard » calculé ; handlers de synchronisation (comptes rendus, observations, changement de statut).
- **Tests** : calcul des quantités selon la composition ; dose phytosanitaire sans référence d'étiquette refusée ; génération uniquement depuis une version validée ; régénération sans réécriture de l'historique ; conflits de transition.
- **Critères d'acceptation** : critères MVP 10 et 11 ; FR-082.

## Phase 7 — Trésorerie

- **Fonctionnalités** : `finance` (TreasuryAccount, Category, FinancialTransaction, LedgerEntry, Revision, Attachment, BudgetLine, BudgetAllocation), services (créer, valider, rejeter, annuler, corriger, transférer), soldes, trésorerie jour/semaine/mois, budget comparé au réalisé, triggers d'immutabilité, handlers de synchronisation (doublons probables).
- **Tests financiers** : soldes, transferts exclus des totaux, annulation et correction, arrondi XAF, idempotence, double soumission concurrente, trigger, isolation des transactions, permissions.
- **Critères d'acceptation** : critères MVP 12, 13, 14 et 19.

## Phase 8 — Récolte

- **Fonctionnalités** : `harvest` (UnitConversion, HarvestRecord, Sale), moteur `yield_`, bilan de campagne (objectif comparé au réalisé, coût par kg), handler de synchronisation.
- **Critères d'acceptation** : critère MVP 15.

## Phase 9 — Assistant IA

- **Fonctionnalités** : port `LLMProvider`, `NullProvider`, adaptateur de fournisseur (configurable), schémas Pydantic, extraction de PDF (texte par page), `ExtractionRun` → brouillon de TechnicalDataSet, `PlanGenerationRun` → brouillon de PlanVersion + AISuggestion + missing_info, vérification des citations, AIRequestLog, quotas, tâches Celery (exécution synchrone en test).
- **Tests** : un faux fournisseur déterministe ; sortie non conforme au schéma rejetée ; citation absente du document → rétrogradation ; dose phytosanitaire jamais acceptée de l'IA ; IA indisponible → la création manuelle reste possible ; aucune validation automatique.
- **Critères d'acceptation** : critère MVP 6 ; FR-100 à FR-107.

## Phase 10 — Client Web

- **Fonctionnalités** : Vite + React + TS strict + Tailwind ; `packages/shared` (types générés depuis l'OpenAPI, Zod) ; `packages/sync-core` (outbox, machine d'états, push/pull, retry, superposition) ; adaptateur Dexie ; écrans : connexion, choix d'exploitation, parcelles, plans, irrigation, tâches, finances, récoltes, conflits ; indicateurs de synchronisation.
- **Tests** : Vitest (sync-core : perte de connexion, rejeu, crash), Testing Library, Playwright hors ligne.
- **Critères d'acceptation** : critère MVP 16 (Web).

## Phase 11 — Mobile

- **Fonctionnalités** : Expo Router, adaptateur SQLite de sync-core, écrans de terrain (tâches, comptes rendus avec photos, observations, dépenses et recettes, récoltes), file de fichiers.
- **Critères d'acceptation** : critère MVP 16 (Mobile).

## Phase 12 — Durcissement et pilote

- RLS PostgreSQL, tests E2E du scénario MVP complet, tests de charge, sauvegardes et restauration, déploiement de staging, documentation d'exploitation.

---

## Suivi

| Phase | Statut | Tests exécutés | Remarques |
|---|---|---|---|
| 0 | terminée | ruff, ruff format, mypy (strict defs), pytest sur PostgreSQL 17 | Django 5.2.19 LTS, DRF 3.16.1, simplejwt 5.5.1, drf-spectacular 0.30.0 (verrouillés dans `backend/uv.lock`) |
| 1 | terminée | 130 tests : auth/appareils, organisations/rôles/invitations, exploitations/membres, champs/parcelles, audit append-only, séquence sans trou, suite d'isolation générée | Critères MVP 1 à 4 et 20 couverts côté API |
| 2 | terminée | 171 tests cumulés, dont 30 de synchronisation : rejeu, clé réutilisée, push concurrent (verrou consultatif), lot partiel, dépendances, fusion à trois, conflits, tombstones, pagination, purge, 410, révocation | Handlers : `farms.farm` (lecture), `fields.field`, `fields.parcel` |
| 3 | terminée | 30 tests : fichiers (signature MIME, quotas, permissions par usage, idempotence, isolation), cultures globales ou propres, variétés, flux complet données techniques (provenance, validation, immuabilité, versions) | Stockage fichiers local en dev/test (S3 en production : à configurer) |
| 4 | terminée | 34 tests moteur (cas de référence, propriétés hypothesis) + 9 tests plans (préremplissage, calculs, validation, versions, comparaison, réservation des parcelles, permissions) — 330 tests cumulés | Erreur d'arrondi décimale détectée et corrigée dans le nombre de plants |
| 5 | terminée | 18 tests moteur (débits, volume ≠ débit, HMT, Hazen-Williams, Christiansen, nomenclature, devis) + 8 tests API (conception, nomenclature, devis multi-fournisseurs, prix copiés, immutabilité) | Aspersion : mode paramétrique uniquement |
| 6 | terminée | 8 tests moteur intrants + 17 tests API (composition, conversions P₂O₅/K₂O, dose phyto jamais IA, génération depuis version validée, régénération sans réécriture, transitions, comptes rendus, consommations, synchronisation par commande) — 489 tests cumulés | Base de surface des doses = surface allouée (Q17) |
| 7 | terminée | 22 tests financiers (soldes validés et provisoires, idempotence et rejeu, concurrence sur la même clé, devise et précision XAF, transferts exclus des flux, annulation, correction, révisions, triggers PostgreSQL, doublon probable, budget/réalisé, solde d'ouverture, synchronisation hors ligne et commande d'annulation) + isolation des routes financières | Aucune fusion automatique ; transactions jamais supprimées |
| 8 | terminée | 3 tests moteur rendement + 6 tests API (unités mesurées obligatoires, validation, rendements brut/commercialisable, écart à l'objectif, coût/kg, marge, masquage financier sans `finance.view`, annulation logique, synchronisation idempotente) — 593 tests cumulés | Ventes modélisées comme recettes liées au cycle (Q23) |
| 9 | terminée | 9 tests (fournisseur factice déterministe) : indisponibilité et mode manuel, extraction vers un brouillon, citations vérifiées dans le PDF, éléments rejetés, sortie non conforme rejetée, erreurs fournisseur journalisées, coût estimé, quota mensuel, permission, provenance du brouillon de plan (documentaire uniquement si identique à une donnée validée), validation bloquée tant que des suggestions sont en attente — 619 tests cumulés | Appels IA synchrones (Celery non mis en place, Q24) ; adaptateur Anthropic optionnel (`uv sync --extra ai`) |
| 10 | terminée | sync-core : 15 tests Vitest (coupure et retour réseau, recul exponentiel, crash pendant l'envoi, réponse perdue, lot partiel, conflits, authentification expirée, compactage, finance jamais fusionnée, pagination, curseur expiré, rollback de page, vue locale). Web : 14 tests (validation, persistance IndexedDB après rechargement, isolation par utilisateur, rollback, connexion, saisie hors ligne, démarrage hors ligne) ; typecheck strict ; build | Workspaces npm (pnpm absent). Défaut corrigé : un démarrage hors ligne déconnectait l'utilisateur. E2E Playwright reporté en Phase 12 |
| 11 | terminée | 7 tests Vitest (stockage SQLite sur `node:sqlite` : migrations idempotentes, file conservée après redémarrage puis synchronisée, transactions imbriquées et rollback, isolation ; validation des saisies) ; typecheck TypeScript 6 strict (15 fichiers) ; `expo-doctor` 20/20 | Expo SDK 58, React Native 0.88, Expo Router ; écrans terrain : tâches, observations, récoltes, dépenses, synchronisation. Non testé sur appareil physique dans cet environnement |
| 12a — ergonomie Web et mobile | terminée | `@fms/shared` : 15 tests (montants formatés sans flottant, dates sans décalage de fuseau, libellés, opérations et erreurs en clair, regroupement des tâches, comptes rendus en attente). Web : 20 tests (+6 : double clic sur une dépense = 1 seule transaction, compte rendu confirmé avec notes et non dupliqué, Échap annule, formulaire masqué sans permission, avertissement à la déconnexion, choix d'exploitation avec rôles lisibles) ; typecheck ; build. Mobile : 7 tests, typecheck, export Android (Hermes) réussi, `expo-doctor` 20/20 | Défauts corrigés : double saisie possible (dépenses, parcelles, comptes rendus de tâches acceptés deux fois par le serveur), date du jour calculée en UTC côté Web, formulaire de dépense affiché sans `finance.transaction.create`, première pression ignorée sur mobile clavier ouvert. Non vérifié sur appareil physique ni par un utilisateur de terrain |
| 12b — révision des maquettes Web | terminée | Web : 29 tests (+9 au total) : modèle de notifications (sans doublon, limite, lecture, données stockées invalides ignorées), notifications issues de la synchronisation (envois, refus, conflits, nouvelles tâches, identifiant stable), erreur locale de synchronisation rendue visible, confirmation de saisie dans la cloche, déconnexion depuis le menu profil, cloche et profil présents sur le choix d'exploitation, création d'exploitation réservée aux administrateurs avec préremplissage. Typecheck ; build | Défaut corrigé : une erreur locale du moteur de synchronisation (IndexedDB) n'était signalée nulle part. Application mobile non modifiée à ce stade |
| 12c — révision reportée sur mobile | terminée | Logique des notifications et de la création d'exploitation déplacée dans `@fms/shared` (27 tests, dont validation et préremplissage du formulaire d'exploitation, regroupement par organisation, initiales, erreur locale de synchronisation). Web : 22 tests (7 déplacés vers le paquet partagé), typecheck. Mobile : 8 tests (+1 : décompte des saisies non envoyées toutes exploitations), typecheck strict, export Android (Hermes) complet avec la police d'icônes, `expo-doctor` 20/20 | Ajout de `@expo/vector-icons` 15.0.2 et de `expo-font` 58.0.11 (dépendance requise, détectée par `expo-doctor`). Non vérifié sur appareil ni émulateur : SDK Android absent de cette machine |
| 12c — interface d'administration | terminée | 782 tests backend au total (+82) : chaque modèle enregistré, listes, recherches, fiches et pages d'ajout affichées (paramétré sur tous les modèles) ; 13 tests CRUD (création par service avec journal de synchronisation et audit, version périmée refusée, référence d'une autre exploitation refusée, listes filtrées par exploitation, suppression logique, droits Django exigés, organisation et rôles, invitation à jeton affiché une fois, données techniques brouillon → validées, tarif brouillon puis figé) ; 7 parcours complets (plan jusqu'aux tâches générées, dépense enregistrée une seule fois malgré un double envoi, annulation avec motif obligatoire, solde d'ouverture idempotent, statut et compte rendu de tâche sans doublon, annulation de récolte, résolution de conflit) ; ruff, mypy propres | `ReadOnlyAdmin` (consultation) et `ServiceAdmin` (écritures et actions par les services, contexte plateforme, Q34). Non couvert dans l'admin : consommations d'intrants et photos des comptes rendus, brouillon de plan par l'IA (API). Conceptions d'irrigation : pages vérifiées, parcours non testé |
| 12 | en cours | Scénario MVP complet de bout en bout côté API (critères 1 à 20), réglages de production (`check --deploy`, HSTS, cookies sécurisés, secret obligatoire), nombre de requêtes constant sur les listes (NFR-004), schéma OpenAPI généré sans avertissement et validé (`--fail-on-warn --validate`) — 627 tests backend ; image Docker construite et démarrée (contrôle de santé OK) | Fait : image Docker (gunicorn, utilisateur non root), script de sauvegarde `scripts/backup_db.sh` avec vérification du dump, documentation OpenAPI complète (authentification JWT, paramètres de chemin typés, noms d'énumérations stables). Reste : RLS PostgreSQL (Q27), E2E Playwright, tests de charge, cookie `HttpOnly` (Q26), Celery si nécessaire (Q24), staging |
