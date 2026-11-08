# PROJECT_CONTEXT.md

# 1. Présentation du projet

## Nom de travail
Farm Management System (FMS)

## Vision

Développer une plateforme numérique de gestion agricole permettant à plusieurs exploitations indépendantes de concevoir, planifier, exécuter et analyser leurs activités agricoles.

La plateforme doit couvrir l'intégralité du cycle de production, depuis la définition des paramètres agronomiques jusqu'à la récolte et l'analyse économique.

Elle doit également intégrer un assistant d'intelligence artificielle capable de générer une première proposition de plan de production à partir des fiches techniques variétales.

L'utilisateur conserve systématiquement le contrôle des décisions agronomiques et économiques.

# 2. Objectifs principaux

1. Centraliser les informations des exploitations agricoles.
2. Concevoir des plans de production par culture et par parcelle.
3. Calculer les densités et besoins en intrants.
4. Dimensionner les systèmes d'irrigation.
5. Générer des devis prévisionnels.
6. Planifier automatiquement les opérations agricoles.
7. Suivre quotidiennement les travaux réalisés.
8. Suivre les recettes et dépenses quotidiennes.
9. Comparer les prévisions aux réalisations.
10. Mesurer les rendements et les coûts de production.
11. Exploiter l'intelligence artificielle pour assister les décisions.
12. Fonctionner avec ou sans connexion Internet.

# 3. Utilisateurs et organisations

L'application est multi-tenant.

Une organisation peut gérer plusieurs exploitations agricoles.

Chaque exploitation dispose de :
- Ses parcelles.
- Ses campagnes agricoles.
- Ses cultures.
- Ses utilisateurs.
- Ses stocks.
- Ses équipements.
- Ses finances.
- Ses documents.
- Ses opérations.

Une personne peut appartenir à plusieurs exploitations avec des rôles différents.

Capacité initiale cible : 10 à 30 utilisateurs par exploitation.

L'isolation des données entre organisations et exploitations est une exigence de sécurité fondamentale.

# 4. Utilisateurs et rôles

Rôles initiaux :
- Administrateur de l'organisation.
- Gestionnaire d'exploitation.
- Responsable agricole.
- Technicien agricole.
- Ouvrier.
- Magasinier.
- Gestionnaire financier.

Les permissions doivent être configurables et contrôlées côté backend.

# 5. Domaines fonctionnels

## A. Gestion des exploitations
Organisations, exploitations, utilisateurs, parcelles, champs et infrastructures.

## B. Gestion des cultures
Référentiel des espèces et variétés, cycles culturaux, densité, plantation, semis et récoltes.

## C. Conception des plans de production
Configuration technique, dimensionnement, programme agronomique, calendrier et budget.

## D. Irrigation
Choix du système, calculs hydrauliques, nomenclature, équipements et devis.

## E. Gestion agronomique
Irrigation, fertilisation, traitements phytosanitaires, observations et suivi des cultures.

## F. Planification
Calendrier cultural, tâches, affectations, notifications et validation des opérations.

## G. Gestion des ressources
Intrants, stocks, fournisseurs, équipements et personnel.

## H. Gestion financière
Recettes, dépenses, caisses, comptes, transferts, justificatifs et suivi budgétaire.

## I. Récolte
Quantités, qualité, rendement, pertes et ventes.

## J. Intelligence artificielle
Lecture des fiches variétales, génération assistée des plans de production et analyse des données.

# 6. Particularités du produit

## Offline-first
Les utilisateurs doivent pouvoir consulter et saisir les données opérationnelles sans Internet.

Les opérations sont enregistrées localement et synchronisées ultérieurement.

## Multi-plateforme
- Web : React et TypeScript.
- Mobile : React Native et Expo.

## Multi-tenant
L'isolation des données est obligatoire.

## IA assistée
Les propositions de l'IA ne deviennent jamais automatiquement des décisions validées.

## Traçabilité
Les opérations agricoles et financières doivent être historisées.

# 7. Architecture technique cible

Backend :
- Python.
- Django.
- Django REST Framework.
- PostgreSQL.

Frontend Web :
- React.
- TypeScript.
- Tailwind CSS.
- IndexedDB.

Frontend Mobile :
- React Native.
- Expo.
- TypeScript.
- SQLite.

Infrastructure :
- Docker.
- API REST.
- Stockage de fichiers.
- Système de synchronisation dédié.

Les choix de bibliothèques et versions doivent être documentés et vérifiés avant implémentation.

# 8. Philosophie de développement

Le logiciel doit être :
- Modulaire.
- Maintenable.
- Testable.
- Sécurisé.
- Extensible.
- Adapté aux connexions instables.
- Orienté métier agricole.

Ne pas développer toutes les fonctionnalités simultanément.

Privilégier un MVP opérationnel et cohérent avant l'ajout de fonctionnalités avancées.

# 9. Contexte agricole initial

Le premier environnement de validation sera une exploitation agricole en République du Congo.

Les cultures de référence incluent :
- Papayer.
- Pastèque.
- Haricot nain.
- Concombre.
- Piment.

Les superficies, variétés, paramètres agronomiques, monnaies et caractéristiques des exploitations doivent être configurables.

Aucune donnée agricole spécifique ne doit être codée en dur comme règle universelle.

# 10. Objectif du MVP

Permettre à un exploitant de :

1. Créer son organisation et son exploitation.
2. Créer ses parcelles.
3. Enregistrer une variété.
4. Importer sa fiche technique.
5. Générer un plan de production assisté par IA.
6. Modifier et valider le plan.
7. Dimensionner son irrigation.
8. Produire un budget prévisionnel.
9. Générer son calendrier de tâches.
10. Enregistrer les opérations réalisées.
11. Enregistrer ses recettes et dépenses.
12. Suivre sa campagne jusqu'à la récolte.

# 11. Règle fondamentale

Le plan de production est l'objet métier central du système.

Toutes les fonctionnalités agricoles doivent pouvoir être reliées à une campagne et à un plan de production lorsque cela est pertinent.