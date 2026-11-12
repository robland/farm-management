# Scénarios d'utilisation — Planification de production

Ce document décrit les parcours de planification tels qu'ils sont implémentés (FR-030 à FR-035, FR-103 à FR-105).
Il sert de référence pour la recette fonctionnelle, la formation des utilisateurs et la conception des écrans.

> Les valeurs numériques citées sont **fictives** : elles illustrent les règles du système et ne constituent pas des recommandations agronomiques.

Code concerné : `backend/apps/production_plans/`, `backend/agronomy_engine/`, `backend/apps/ai_assistant/`, `backend/apps/tasks/`.
Formules du moteur : `docs/architecture/AGRONOMY_ENGINE.md`.

## Acteurs et permissions

| Acteur (rôle par défaut) | `plans.view` | `plans.edit` | `plans.validate` | `ai.use` | `tasks.edit` |
|---|:-:|:-:|:-:|:-:|:-:|
| Administrateur d'organisation, gestionnaire d'exploitation | ✔ | ✔ | ✔ | ✔ | ✔ |
| Responsable agricole (`agri_manager`) | ✔ | ✔ | ✔ | ✔ | ✔ |
| Technicien agricole (`technician`) | ✔ | ✔ | — | ✔ | — |
| Gestionnaire financier (`finance_manager`) | ✔ | — | — | — | — |
| Ouvrier, magasinier | — | — | — | — | — |

Le technicien **prépare** les brouillons. Le responsable agricole **valide** et lance la génération des tâches.

## Préconditions communes

- Une organisation, une exploitation, des champs et des parcelles avec leur surface (`area_m2`).
- Une variété appartenant à l'organisation. Pour le pré-remplissage et l'IA : un jeu de données techniques **validé** (`TechnicalDataSet.status = validated`).
- Une campagne sur l'exploitation.
- Toutes les routes ci-dessous sont préfixées par `/api/v1/farms/{farm_id}/`.

## Cycle de vie

```
Plan        : draft ──► validated ──► in_progress ──► closed
                  └──────────────► cancelled
Version     : draft ──► validated ──► superseded
                  └──► rejected
CropCycle   : planned ──► active ──► harvested ──► closed   (ou cancelled)
```

Invariants :
- Une version **validée ne se modifie plus**. Toute évolution passe par une nouvelle version.
- **Un seul brouillon** à la fois par plan, **une seule version validée** par plan (contrainte en base).
- Les tâches ne proviennent **que** d'une version validée.
- L'IA ne valide jamais rien.

---

## S1 — Créer un plan manuellement et le valider (parcours nominal)

**Acteurs** : technicien (préparation), responsable agricole (validation).
**Objectif** : obtenir un plan validé, calculé et réservant ses parcelles, sans IA.

| # | Acteur | Action | API | Résultat attendu |
|---|---|---|---|---|
| 1 | Technicien | Crée la campagne « Saison des pluies 2027 » | `POST campaigns/` | Campagne `planned` |
| 2 | Technicien | Crée le plan « Tomate — parcelle P1 » pour la variété choisie | `POST plans/` | Plan `draft` + version 1 `draft`, origine `manual`, paramètres vides |
| 3 | Technicien | Renseigne la date de début, le rendement visé, les objectifs | `PATCH plan-versions/{id}/` | En-tête enregistré, provenance « saisie utilisateur » |
| 4 | Technicien | Affecte P1 : 2 000 m² dont 150 m² non plantables | `PUT plan-versions/{id}/allocations/` | Affectation enregistrée |
| 5 | Technicien | Pré-remplit depuis la fiche variétale | `POST plan-versions/{id}/prefill/` | Les champs vides reçoivent les valeurs validées (`filled`). Les plages documentées sont listées dans `needs_user_choice`. |
| 6 | Technicien | Complète la méthode (semis direct / repiquage), la disposition, la marge de sécurité | `PATCH plan-versions/{id}/planting-spec/` | Paramètres complets |
| 7 | Technicien | Vérifie ou ajuste les phases et leurs durées | `PUT plan-versions/{id}/phases/` | Calendrier ordonné |
| 8 | Technicien | Lance le calcul | `POST plan-versions/{id}/compute/` | `complete: true`. Résultats par parcelle : surface plantable, densité théorique et réelle, nombre de plants, semences (nombre, grammes, sachets), dates des phases |
| 9 | Responsable | Relit les résultats et leur traçabilité (formule, hypothèses, alertes) | `GET plan-versions/{id}/` | — |
| 10 | Responsable | Valide | `POST plan-versions/{id}/validate/` | Version `validated` (validée par, le…), plan `validated`, `CropCycle` créé sur P1 pour la période, date de fin déduite du calendrier si absente |

**Postconditions** : la version 1 est figée ; P1 est occupée à hauteur de 2 000 m² sur la période.
**Test** : `apps/production_plans/tests/test_plans.py::test_manual_plan_full_workflow`.

---

## S2 — Pré-remplissage sans écraser les saisies

**Contexte** : le technicien a déjà saisi un écartement entre plants avant de pré-remplir.

1. Saisie manuelle de `plant_spacing_m`.
2. `POST prefill/`.
3. **Attendu** : `plant_spacing_m` est conservé ; seuls les champs vides sont remplis.
4. La fiche donne l'écartement entre lignes sous forme de plage : le champ n'est pas rempli et figure dans `needs_user_choice`. **Le système ne choisit jamais une valeur dans une plage.**
5. Une durée de phase non entière n'est pas arrondie : elle reste à saisir.

**Variante d'erreur** : la variété n'a aucun jeu de données validé → `400` « La variété n'a pas de données techniques validées. »
**Tests** : `test_user_values_are_not_overwritten_by_prefill`, `test_prefill_without_validated_data_fails`.

---

## S3 — Plan incomplet : le calcul signale ce qui manque

**Contexte** : aucun écartement saisi, aucune phase définie.

1. `POST compute/`.
2. **Attendu** : `complete: false` et une liste `missing` structurée :
   - `{"scope": "parcel:<id>", "fields": ["row_spacing_m", …]}` ;
   - `{"scope": "calendar", "fields": ["phases"]}`.
3. Aucune valeur par défaut n'est injectée.
4. `POST validate/` → `400` « Le plan est incomplet… », avec `details.missing` identique.

**Usage côté interface** : afficher la liste `missing` comme une liste de tâches de saisie, avec un lien vers chaque champ.
**Test** : `test_validation_requires_complete_plan`.

---

## S4 — Brouillon assisté par IA

**Acteurs** : technicien (`ai.use` + `plans.edit`), responsable agricole.
**Précondition** : un fournisseur IA est configuré (`GET /api/v1/ai/status/`).

| # | Action | API | Résultat attendu |
|---|---|---|---|
| 1 | Demande un brouillon : campagne, variété, parcelle, surface, surface non plantable, date de début, objectifs, contraintes | `POST ai/plan-drafts/` | Exécution `AIRun` journalisée (fournisseur, versions du prompt et du schéma, coût estimé) |
| 2 | — | — | Plan créé avec la version 1, origine `ai_draft`. Les valeurs proposées sont des **suggestions** au statut `suggested`. Les informations absentes sont listées avec une question pour chacune. |
| 3 | Chaque valeur est classée | — | **Source documentaire** (citation vérifiée dans la fiche), **recommandation IA** ou **calcul déterministe** |
| 4 | Le technicien tranche chaque suggestion | `POST ai/suggestions/{id}/decide/` avec `accept`, `reject` ou `modify` (+ `value`) | `accept` → provenance « recommandation IA acceptée ». `modify` / `reject` → provenance « saisie utilisateur ». |
| 5 | Complète les informations manquantes, puis calcule | `compute/` | Comme S1 |
| 6 | Le responsable valide | `validate/` | Comme S1 |

**Règles** :
- Tant qu'une suggestion reste `suggested`, la validation est **bloquée** : « N suggestion(s) IA à accepter, modifier ou rejeter. »
- Une suggestion déjà tranchée ne peut pas l'être une seconde fois.
- Une valeur présentée comme documentaire doit avoir une citation retrouvée dans le document. Sinon, elle est classée comme recommandation IA.

**Variantes d'erreur** :
- Aucun fournisseur configuré → erreur « IA indisponible », **aucun plan créé**. L'utilisateur bascule sur S1.
- Échec du fournisseur ou réponse hors schéma → `AIRun` en échec, rien n'est créé (transaction).
- Quota dépassé → refus avant tout appel au fournisseur.

**Tests** : `apps/ai_assistant/tests/test_ai.py::test_plan_draft_classifies_sources_and_requires_human_decisions`, `test_plan_draft_without_provider_creates_nothing`.

---

## S5 — Conflit d'occupation de parcelle

**Contexte** : P1 (2 000 m²) est déjà occupée à 1 500 m² par un autre plan validé sur une période qui chevauche.

1. Un second plan alloue 800 m² de P1 sur une période qui chevauche.
2. `POST validate/`.
3. **Attendu** : `400` « La parcelle P1 est déjà occupée sur cette période. », avec `details` : `occupied_m2 = 1500`, `requested_m2 = 800`, `parcel_area_m2 = 2000`.
4. La transaction est annulée : la version reste un brouillon, aucun cycle n'est créé.

**Résolutions possibles** : réduire la surface à 500 m² ou moins, décaler les dates, ou choisir une autre parcelle.
**Remarque** : les cycles `cancelled` et le plan lui-même ne comptent pas dans l'occupation.
**Test** : `test_parcel_overbooking_is_refused`.

---

## S6 — Générer les tâches opérationnelles

**Acteur** : responsable agricole (`tasks.edit`).

1. `POST tasks/generate/` avec `{"plan_version": "<id version validée>"}`.
2. **Attendu** : une tâche par phase du calendrier et par parcelle, aux dates calculées. Origine `generated`, rattachée au cycle cultural et à un lot de génération.
3. Réponse : `{"created": n, "unchanged": 0, "replanned": 0, "cancelled": 0, "kept": 0}`.
4. Les tâches peuvent ensuite être affectées (`assign/`) et suivies sur le terrain, y compris hors ligne.

**Variantes d'erreur** :
- Version en brouillon → `400` « Les tâches ne sont générées qu'à partir d'une version validée du plan. »
- Aucun cycle actif → `400`.

**Tests** : `apps/tasks/tests/test_tasks.py::test_generation_requires_validated_version`, `test_generation_from_validated_plan`.

---

## S7 — Réviser un plan validé (nouvelle version)

**Contexte** : après la validation de la v1, le semis doit être décalé de deux semaines et l'écartement réduit.

| # | Action | API | Résultat attendu |
|---|---|---|---|
| 1 | Crée une nouvelle version avec une note de changement | `POST plans/{id}/new-version/` | v2 `draft`, origine `copy`, `based_on = v1`. Sont copiés : l'en-tête, les paramètres, les affectations, les phases, les provenances (hors calculs) et le programme agronomique. |
| 2 | Modifie la date et l'écartement | `PATCH` | Seule la v2 change ; la v1 reste intacte |
| 3 | Compare | `GET plans/{id}/compare/?a=<v1>&b=<v2>` | Liste des différences par section (`header`, `planting_spec`, `allocations`, `phases`, `results`), par exemple `plant_count` avant et après |
| 4 | Calcule puis valide la v2 | `compute/`, `validate/` | v2 `validated`, v1 `superseded`, cycles mis à jour (dates, surface, version) |
| 5 | Régénère les tâches | `POST tasks/generate/` | Voir S8 |

**Règles** :
- Une seconde demande `new-version/` alors qu'un brouillon existe → `400` « Un brouillon est déjà en cours pour ce plan. »
- Toute modification d'une version validée → `400` « Seul un brouillon est modifiable : créez une nouvelle version. »
- Le plan clôturé ou annulé ne peut plus être validé.

**Test** : `test_new_version_compare_and_supersede`.

---

## S8 — Régénération des tâches après révision

**Contexte** : suite de S7. Sur le terrain, la préparation du sol est **terminée**, le semis est **à faire**, et la phase « pépinière » a été retirée dans la v2.

Après `POST tasks/generate/` sur la v2 :

| Tâche existante | Situation | Traitement |
|---|---|---|
| Préparation du sol | `done` | **Conservée telle quelle** (`kept`) : l'historique réalisé n'est jamais réécrit |
| Semis | `todo`, dates modifiées | Ancienne tâche **annulée** (« Replanifiée ») et liée à une nouvelle tâche (`replanned`) |
| Croissance | `todo`, dates identiques | Rattachée à la v2 (`unchanged`) |
| Pépinière | `todo`, phase retirée | **Annulée** « Retirée du plan » (`cancelled`) |
| Tâche retirée mais `in_progress` | — | Conservée (`kept`) |

La génération peut être relancée autant de fois que nécessaire sans créer de doublons.
**Test** : `test_regeneration_keeps_history`.

---

## S9 — Retirer une parcelle lors d'une révision

1. La v2 n'affecte plus P2, qu'affectait la v1.
2. Validation de la v2.
3. **Attendu** : le cycle de P2 encore `planned` passe à `cancelled`, ce qui libère la parcelle. Un cycle déjà `active` ou récolté n'est pas annulé automatiquement.
4. Si P2 est réaffectée dans une version ultérieure, son cycle annulé redevient `planned`.

**Test** : aucun test dédié identifié ; couverture à ajouter.

---

## S10 — Contrôles d'accès et isolation

| Situation | Attendu |
|---|---|
| Un ouvrier consulte un plan | `403` (pas de `plans.view`) |
| Le gestionnaire financier modifie un brouillon | `403` |
| Le technicien valide un plan | `403` (pas de `plans.validate`) |
| Création d'un plan avec une variété d'une autre organisation | `400` « Variété introuvable. » ; aucune information n'est divulguée |
| Accès à un plan d'une autre exploitation ou d'une autre organisation | `404` |
| Deux utilisateurs modifient le même brouillon | Le second reçoit `409` (version obsolète) et doit recharger |

**Tests** : `test_permissions_on_plans`, `test_plan_requires_variety_of_own_org`, `backend/tests/tenancy/test_isolation.py`.

---

## S11 — Consultation hors ligne sur le terrain

**Acteurs** : technicien, ouvrier, sur mobile.

1. En ligne, l'application télécharge les plans, les versions, les cycles et les tâches de l'exploitation.
2. Sans réseau : consultation du plan validé, du calendrier et des tâches ; changement de statut des tâches et comptes rendus mis en file d'attente.
3. Retour du réseau : la file est synchronisée, avec des clés d'idempotence pour éviter tout doublon.

**Limite actuelle** : la **conception**, le **calcul** et la **validation** d'un plan exigent une connexion (OPEN_QUESTIONS Q7, encore ouverte).
**Test** : `apps/tasks/tests/test_tasks.py::test_offline_status_command_and_report_sync`.

---

## Couverture et points ouverts

- Les scénarios S1 à S8, S10 et S11 sont couverts par des tests automatisés.
- S9 (retrait d'une parcelle et réactivation d'un cycle) n'a pas de test dédié identifié.
- L'immuabilité d'une version validée et la règle « un seul brouillon » sont testées (`test_manual_plan_full_workflow`, `test_new_version_compare_and_supersede`).
- Le client Web n'a pas encore d'écrans de conception de plan. Ces parcours passent par l'API (`/api/v1/docs/`) ou par l'administration Django.
