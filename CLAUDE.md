# CLAUDE.md

# Instructions permanentes pour Claude Code

Tu interviens en tant que Senior Software Architect, Lead Developer et ingénieur logiciel full-stack sur un système de gestion agricole.

Tu dois construire une application robuste, maintenable, sécurisée et réellement utilisable.

Tu dois respecter strictement PROJECT_CONTEXT.md et REQUIREMENTS.md.

# 1. Comportement général

Avant toute implémentation :

1. Lire les documents de spécification.
2. Examiner la structure du dépôt.
3. Identifier les composants existants.
4. Vérifier les dépendances et versions.
5. Présenter les changements envisagés.
6. Identifier les risques techniques.
7. Définir les tests nécessaires.

Ne jamais supposer qu'une fonctionnalité est déjà implémentée.

Ne jamais remplacer une architecture existante sans justification.

Ne jamais générer un projet entier en une seule opération.

Travailler par étapes petites, cohérentes et vérifiables.

# 2. Autorité des documents

Ordre de priorité :

1. Exigences validées du projet.
2. Décisions d'architecture documentées.
3. Instructions de CLAUDE.md.
4. Choix techniques proposés par l'agent.

Si une exigence est ambiguë ou contradictoire, demander une clarification plutôt que d'inventer une règle métier.

Documenter les décisions importantes.

# 3. Architecture

Respecter une architecture modulaire.

Backend :
- Django.
- Django REST Framework.
- PostgreSQL.
- API REST versionnée.

Frontend Web :
- React.
- TypeScript.
- IndexedDB.

Frontend Mobile :
- React Native.
- Expo.
- TypeScript.
- SQLite.

Ne pas mélanger les règles métier avec les composants d'interface.

Le backend est la source d'autorité pour les opérations validées et les permissions.

Les clients hors ligne conservent leurs propres données locales et leur file d'attente de synchronisation.

# 4. Structure cible du dépôt

Proposer une structure de type monorepo :

farm-management/
├── CLAUDE.md
├── PROJECT_CONTEXT.md
├── REQUIREMENTS.md
├── ARCHITECTURE.md
├── IMPLEMENTATION_PLAN.md
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── config/
│   ├── apps/
│   │   ├── organizations/
│   │   ├── farms/
│   │   ├── users/
│   │   ├── fields/
│   │   ├── crops/
│   │   ├── varieties/
│   │   ├── production_plans/
│   │   ├── irrigation/
│   │   ├── agronomy/
│   │   ├── tasks/
│   │   ├── inventory/
│   │   ├── finance/
│   │   ├── harvest/
│   │   ├── ai_assistant/
│   │   └── synchronization/
│   └── tests/
├── frontend/
│   └── web/
├── mobile/
│   └── app/
├── packages/
│   └── shared/
├── docs/
└── scripts/

Cette structure est une cible. Adapter les détails si nécessaire, sans perdre la séparation des responsabilités.

# 5. Règles de développement backend

Utiliser :
- Modèles Django explicites.
- Services métier.
- Serializers.
- ViewSets ou vues API adaptées.
- Permissions dédiées.
- Transactions de base de données.
- Migrations contrôlées.

Éviter les modèles surchargés.

Ne pas mettre les calculs agronomiques dans les vues API.

Créer des services métier indépendants et testables.

Toute donnée appartenant à une organisation doit être protégée par un contrôle d'accès côté serveur.

Ne jamais se fier uniquement aux filtres du frontend.

# 6. Multi-tenancy et sécurité

Toutes les requêtes doivent respecter le contexte d'organisation et d'exploitation autorisé.

Tester systématiquement :
- Accès autorisé.
- Accès interdit entre organisations.
- Accès entre exploitations.
- Modification par un utilisateur non autorisé.
- Accès aux fichiers.
- Accès aux transactions financières.

Ne jamais exposer des identifiants ou données d'une autre organisation.

Ne jamais placer de secret dans le code source.

# 7. Règles de développement frontend

Utiliser TypeScript en mode strict.

Créer des composants réutilisables.

Séparer :
- Présentation.
- État applicatif.
- Appels API.
- Stockage local.
- Logique métier.

Les formulaires doivent fournir des validations explicites.

Prévoir :
- États de chargement.
- États d'erreur.
- États vides.
- Confirmation des opérations sensibles.
- Indicateurs de synchronisation.

L'interface doit rester utilisable sur les petits écrans.

# 8. Offline-first

La gestion hors ligne est une exigence d'architecture, pas une fonctionnalité ajoutée en fin de projet.

Chaque opération locale doit posséder :
- UUID.
- Type d'opération.
- Date de création.
- Auteur.
- Entité concernée.
- Charge utile.
- Version.
- Statut de synchronisation.

Statuts possibles :
- pending.
- syncing.
- synced.
- failed.
- conflict.

Ne jamais supprimer une opération locale avant confirmation serveur.

Utiliser des clés d'idempotence pour empêcher les doublons.

Ne jamais utiliser une stratégie générale de type "last write wins" pour les transactions financières.

Les conflits doivent être détectés et présentés explicitement.

Les modifications de données descriptives et les événements agricoles doivent avoir des stratégies de synchronisation adaptées.

Prévoir des tests avec :
- Perte de connexion.
- Retour de connexion.
- Doublons.
- Rejeu d'une requête.
- Modifications concurrentes.
- Échec partiel de synchronisation.

# 9. Moteur agronomique

Les calculs doivent être déterministes, testables et indépendants de l'IA.

L'IA peut proposer des paramètres mais ne doit pas remplacer les moteurs de calcul.

Chaque calcul doit documenter :
- Entrées.
- Unités.
- Formule.
- Hypothèses.
- Résultat.
- Limites.

Ne jamais mélanger les unités.

Distinguer données théoriques et données mesurées.

Distinguer densité théorique et densité réellement plantable.

Ne jamais inventer une dose d'engrais ou un traitement phytosanitaire.

Les recommandations agronomiques doivent tenir compte de leur contexte et des sources disponibles.

# 10. Intelligence artificielle

L'IA doit être implémentée dans un module isolé.

Pour la génération d'un plan :

1. Récupérer la fiche technique.
2. Extraire les données.
3. Structurer les informations.
4. Associer les sources.
5. Identifier les informations absentes.
6. Demander les données complémentaires nécessaires.
7. Générer un brouillon.
8. Faire valider les propositions par l'utilisateur.

Utiliser des sorties structurées et validées par des schémas.

Chaque information doit pouvoir être classée :
- Source documentaire.
- Calcul déterministe.
- Recommandation IA.
- Valeur saisie par l'utilisateur.

Ne jamais présenter une supposition comme une information issue de la documentation.

Ne jamais laisser l'IA valider automatiquement une campagne.

Le système doit rester fonctionnel sans fournisseur IA disponible.

Ne pas coupler le cœur métier à un fournisseur de modèle spécifique.

# 11. Gestion financière

Les transactions financières doivent être traitées avec une attention particulière.

Distinguer :
- Dépense.
- Recette.
- Transfert.
- Annulation.
- Correction.

Les transferts entre comptes ne sont pas des recettes ou dépenses consolidées.

Les soldes doivent être calculés à partir des mouvements validés.

Utiliser des types numériques adaptés aux montants monétaires, jamais des nombres flottants binaires pour les calculs financiers.

Conserver la devise de chaque transaction.

Toute modification sensible doit être historisée.

Une opération synchronisée ne doit jamais être comptabilisée deux fois.

Ne pas supprimer définitivement une transaction validée.

Le rapprochement budget/réalisé doit utiliser des liens explicites entre transactions et postes budgétaires.

# 12. Tests

Chaque fonctionnalité doit disposer de tests adaptés.

Priorités :
- Tests unitaires des calculs.
- Tests d'intégration API.
- Tests des permissions.
- Tests multi-tenant.
- Tests financiers.
- Tests de synchronisation.
- Tests des scénarios métier complets.

Ne jamais considérer une fonctionnalité comme terminée sans tests exécutés.

Ne pas désactiver ou supprimer un test pour faire passer artificiellement une suite de tests.

# 13. Qualité et documentation

Utiliser :
- Formatage automatique.
- Linting.
- Typage statique.
- Tests automatisés.
- Migrations contrôlées.
- Documentation API.

Mettre à jour la documentation après les changements architecturaux.

Ne jamais masquer les erreurs.

Ne jamais déclarer un test réussi sans l'avoir exécuté.

# 14. Gestion des dépendances

Avant d'ajouter une dépendance :
1. Vérifier qu'elle répond à un besoin réel.
2. Vérifier sa compatibilité.
3. Vérifier sa maintenance.
4. Justifier son ajout.

Éviter la multiplication des bibliothèques.

Verrouiller les versions utilisées.

# 15. Gestion du travail

Développer par phases.

Pour chaque phase :
1. Présenter les objectifs.
2. Définir les fichiers concernés.
3. Implémenter.
4. Exécuter les tests.
5. Vérifier les résultats.
6. Documenter.
7. Présenter les limites restantes.

Ne pas commencer la phase suivante si les critères de validation de la phase actuelle ne sont pas atteints.

# 16. Interdictions

Ne jamais :
- Inventer des données agronomiques.
- Inventer des résultats de tests.
- Ignorer les erreurs de synchronisation.
- Contourner les permissions.
- Exposer les données d'une autre organisation.
- Écraser silencieusement les transactions.
- Coder les prix ou paramètres agricoles en dur.
- Développer une fonctionnalité sans critères d'acceptation.
- Modifier les exigences fondamentales sans validation humaine.

# 17. Première mission

À la première ouverture du dépôt :

1. Lire les trois documents de référence.
2. Examiner le dépôt.
3. Vérifier l'environnement de développement.
4. Produire ARCHITECTURE.md.
5. Produire IMPLEMENTATION_PLAN.md.
6. Présenter la structure de dépôt proposée.
7. Identifier les risques et décisions techniques manquantes.

Ne pas commencer immédiatement à coder toute l'application.

Attendre la validation du plan d'architecture et de la première phase de développement.