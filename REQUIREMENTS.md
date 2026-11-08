# REQUIREMENTS.md

# 1. Périmètre fonctionnel

L'application doit permettre de gérer plusieurs exploitations agricoles indépendantes, de la conception des campagnes jusqu'à leur bilan technique et économique.

Les exigences sont classées en trois niveaux :
- P0 : indispensable au MVP.
- P1 : important, à intégrer après le socle.
- P2 : évolution future.

# 2. Gestion des organisations et exploitations

## FR-001 — Organisations [P0]
Créer, modifier et consulter une organisation.

## FR-002 — Exploitations [P0]
Une organisation peut gérer plusieurs exploitations.

## FR-003 — Utilisateurs [P0]
Inviter, désactiver et gérer les utilisateurs.

## FR-004 — Permissions [P0]
Contrôler les actions selon les rôles et les permissions.

## FR-005 — Isolation [P0]
Aucun utilisateur ne doit accéder aux données d'une organisation sans autorisation explicite.

# 3. Gestion des parcelles

## FR-010 — Champs et parcelles [P0]
Créer des champs et des parcelles.

Informations :
- Nom.
- Identifiant.
- Superficie.
- Longueur et largeur si disponibles.
- Coordonnées GPS ou géométrie.
- Type de sol.
- pH.
- Disponibilité en eau.
- Historique cultural.
- Observations.

Une parcelle peut accueillir plusieurs cycles successifs.

Des contrôles doivent empêcher les incohérences de superficie et les chevauchements non autorisés de cycles sur une même surface.

# 4. Référentiel des cultures et variétés

## FR-020 — Cultures [P0]
Gérer les espèces cultivées.

## FR-021 — Variétés [P0]
Gérer les variétés et leurs caractéristiques.

## FR-022 — Fiches techniques [P0]
Importer des PDF, images et documents.

Conserver :
- Le document original.
- Le fournisseur ou semencier.
- La date du document.
- Les informations extraites.
- Les références des pages ou sections sources.

## FR-023 — Validation des données [P0]
Les informations extraites par IA doivent être validées avant d'être considérées comme des données agronomiques de référence.

# 5. Plans de production

## FR-030 — Création manuelle [P0]
Créer un plan de production sans utiliser l'IA.

## FR-031 — Création assistée par IA [P0]
Créer un brouillon à partir :
- De la fiche technique variétale.
- De la parcelle.
- De la superficie.
- De la localisation et des conditions climatiques disponibles.
- Des dates souhaitées.
- Des contraintes et objectifs de l'utilisateur.

## FR-032 — Paramètres de plantation [P0]
Définir :
- Écartement entre lignes.
- Écartement entre plants.
- Densité.
- Nombre de plants.
- Quantité de semences.
- Taux de germination ou marge de sécurité.

Les calculs doivent distinguer densité théorique et densité réelle, en tenant compte des allées et surfaces non plantables.

## FR-033 — Calendrier cultural [P0]
Définir les phases :
- Préparation du sol.
- Semis.
- Repiquage.
- Croissance végétative.
- Floraison.
- Fructification.
- Maturation.
- Récolte.

Les phases dépendent de la culture et de la variété.

## FR-034 — Versions [P0]
Conserver les différentes versions du plan.

Les modifications doivent permettre de comparer les hypothèses initiales et les hypothèses actualisées.

## FR-035 — Validation [P0]
Un utilisateur autorisé valide le plan avant sa mise en exécution.

Aucune proposition IA ne doit automatiquement créer des tâches opérationnelles définitives.

# 6. Dimensionnement de l'irrigation

## FR-040 — Choix du système [P0]
Permettre de choisir :
- Goutte-à-goutte.
- Aspersion.
- Micro-aspersion.
- Autres systèmes configurables.

## FR-041 — Dimensionnement [P0]
Pour le goutte-à-goutte, gérer :
- Surface.
- Dimensions de la parcelle.
- Espacement des lignes.
- Espacement des goutteurs.
- Débit des goutteurs.
- Pression de fonctionnement.
- Longueur des rampes.
- Nombre de rampes.
- Débit total.
- Secteurs d'irrigation.
- Besoins de pompage.

Les calculs doivent expliciter les hypothèses hydrauliques.

Les pertes de charge, différences de niveau et contraintes de filtration doivent être prises en compte lorsqu'elles sont renseignées.

Ne pas confondre volume d'eau nécessaire par jour et débit instantané en m³/h.

## FR-042 — Nomenclature [P0]
Générer la liste des composants :
- Tuyaux principaux.
- Tuyaux secondaires.
- Rampes.
- Goutteurs.
- Filtres.
- Vannes.
- Régulateurs.
- Pompes.
- Injecteurs de fertilisants.
- Raccords et accessoires.

## FR-043 — Devis [P0]
Associer des prix unitaires aux composants et calculer les coûts.

Permettre plusieurs versions de devis et plusieurs fournisseurs.

Conserver les prix et hypothèses utilisés dans chaque version.

# 7. Programme agronomique

## FR-050 — Fertilisation [P0]
Planifier les apports :
- Produit.
- Composition.
- Dose.
- Unité.
- Quantité totale.
- Date ou stade cultural.
- Méthode d'application.

Les calculs doivent prendre en compte la composition réelle du fertilisant et les unités nutritionnelles.

## FR-051 — Irrigation [P0]
Définir les besoins et programmations d'irrigation.

## FR-052 — Phytosanitaire [P0]
Gérer les observations, maladies, ravageurs et interventions.

Toute recommandation de produit ou dose doit être vérifiée selon les autorisations locales et les instructions réglementaires du produit.

## FR-053 — Autres interventions [P1]
Désherbage, taille, entretien, pollinisation et autres opérations.

# 8. Calendrier et tâches

## FR-060 — Génération des tâches [P0]
Générer des tâches à partir du calendrier cultural validé.

## FR-061 — Affectation [P0]
Affecter les tâches à des utilisateurs ou équipes.

## FR-062 — Suivi [P0]
Statuts :
- À faire.
- En cours.
- Réalisée.
- En retard.
- Annulée.
- À vérifier.

## FR-063 — Compte rendu [P0]
Chaque intervention doit pouvoir enregistrer :
- Date réelle.
- Responsable.
- Quantités utilisées.
- Durée.
- Observations.
- Photos.
- Écart par rapport au plan.

## FR-064 — Ajustement [P0]
Une modification du calendrier doit permettre de réévaluer les tâches futures sans réécrire l'historique des interventions déjà réalisées.

# 9. Gestion financière

## FR-070 — Comptes de trésorerie [P0]
Créer plusieurs comptes :
- Caisse espèces.
- Compte bancaire.
- Mobile money.
- Autres comptes configurables.

## FR-071 — Dépenses [P0]
Enregistrer les dépenses quotidiennes.

Informations :
- Date.
- Montant.
- Devise.
- Catégorie.
- Description.
- Compte débité.
- Fournisseur.
- Exploitation.
- Campagne ou plan associé.
- Justificatif.
- Auteur.

## FR-072 — Recettes [P0]
Enregistrer les recettes quotidiennes.

Informations :
- Date.
- Montant.
- Devise.
- Catégorie.
- Description.
- Compte crédité.
- Client.
- Culture ou campagne associée.
- Justificatif.

## FR-073 — Transferts [P0]
Enregistrer les transferts entre comptes sans les comptabiliser comme une recette ou une dépense consolidée.

## FR-074 — Soldes [P0]
Calculer les soldes à partir des opérations validées.

## FR-075 — Budgets [P0]
Comparer :
- Budget prévu.
- Dépenses réalisées.
- Écart en valeur.
- Écart en pourcentage.

## FR-076 — Historique [P0]
Conserver les transactions et leurs modifications.

Les opérations validées ne doivent pas être supprimées définitivement. Utiliser des annulations et écritures correctives traçables.

## FR-077 — Trésorerie [P0]
Afficher les entrées, sorties et soldes par jour, semaine et mois.

## FR-078 — Exports [P1]
Exporter les journaux et synthèses financières.

Le MVP est un outil de gestion de trésorerie et non un logiciel de comptabilité générale.

# 10. Stocks et ressources

## FR-080 — Catalogue d'intrants [P1]
Semences, engrais, produits phytosanitaires et consommables.

## FR-081 — Stocks [P1]
Entrées, sorties, inventaires et seuils d'alerte.

## FR-082 — Consommations [P0]
Relier les intrants utilisés aux opérations et aux plans de production.

# 11. Récolte

## FR-090 — Enregistrement [P0]
Enregistrer chaque récolte :
- Date.
- Quantité.
- Unité.
- Parcelle.
- Culture.
- Qualité.
- Pertes.
- Responsable.

## FR-091 — Rendement [P0]
Calculer les rendements à partir des surfaces et quantités réellement récoltées.

## FR-092 — Bilan [P0]
Comparer les objectifs et résultats.

# 12. Intelligence artificielle

## FR-100 — Extraction [P0]
Extraire les informations des fiches variétales.

## FR-101 — Structuration [P0]
Produire des données structurées et traçables.

## FR-102 — Génération [P0]
Proposer un brouillon de plan de production.

## FR-103 — Sources [P0]
Identifier les informations provenant de la fiche technique, les calculs déterministes et les recommandations IA.

## FR-104 — Ajustement [P0]
Permettre à l'utilisateur de modifier chaque paramètre.

## FR-105 — Validation humaine [P0]
Exiger une validation explicite.

## FR-106 — Mode dégradé [P0]
Si le service IA n'est pas disponible, la création manuelle du plan doit rester possible.

## FR-107 — Coûts IA [P1]
Tracer les appels, les coûts et les erreurs du service IA.

# 13. Fonctionnement hors ligne

## FR-110 — Consultation [P0]
Consulter les données préalablement synchronisées.

## FR-111 — Saisie [P0]
Enregistrer les tâches et observations hors ligne.

## FR-112 — Finances [P0]
Enregistrer recettes et dépenses hors ligne.

## FR-113 — Synchronisation [P0]
Synchroniser automatiquement dès que possible.

## FR-114 — Conflits [P0]
Détecter les modifications concurrentes et proposer une résolution explicite.

## FR-115 — Fichiers [P1]
Mettre les photos et justificatifs en file d'attente pour transfert ultérieur.

Chaque opération possède un UUID, une date de création, un auteur, un identifiant de synchronisation et une version.

Les API de synchronisation doivent être idempotentes.

# 14. Exigences non fonctionnelles

## NFR-001 — Sécurité
Authentification, autorisations backend, isolation multi-tenant et protection des fichiers.

## NFR-002 — Traçabilité
Journaliser les actions sensibles et financières.

## NFR-003 — Fiabilité
Ne jamais perdre une opération locale en attente de synchronisation.

## NFR-004 — Performance
Pagination, indexation et optimisation des requêtes.

## NFR-005 — Qualité
Tests unitaires, tests d'intégration et tests de bout en bout.

## NFR-006 — Ergonomie
Interface utilisable sur ordinateur, tablette et smartphone.

## NFR-007 — Unités
Utiliser des unités explicites et cohérentes : m, ha, L, m³, kg, g, mm, bar, L/h.

## NFR-008 — Internationalisation
Prévoir les formats de date, devise, langue et fuseau horaire par exploitation.

# 15. Critères d'acceptation du MVP

Le MVP est considéré comme fonctionnel lorsque :

1. Deux organisations peuvent être créées sans fuite de données.
2. Une organisation peut gérer plusieurs exploitations.
3. Un utilisateur peut accéder à plusieurs exploitations autorisées.
4. Une parcelle peut être créée et configurée.
5. Une variété peut être enregistrée avec sa fiche technique.
6. L'IA peut proposer un brouillon structuré de plan de production.
7. L'utilisateur peut modifier et valider ce plan.
8. Les paramètres de plantation sont calculés.
9. Un dimensionnement et un devis d'irrigation peuvent être générés.
10. Les opérations agricoles peuvent être planifiées.
11. Les tâches peuvent être réalisées et documentées.
12. Les recettes et dépenses peuvent être enregistrées.
13. Les soldes sont calculés correctement.
14. Les budgets prévisionnels sont comparables aux dépenses réelles.
15. Les récoltes et rendements peuvent être suivis.
16. Les principales opérations peuvent être réalisées sans Internet.
17. La synchronisation ne crée aucun doublon.
18. Les conflits de modification sont détectés.
19. Les données financières restent traçables.
20. Les tests de sécurité multi-tenant sont concluants.

# 16. Priorisation

MVP :
- Organisations et exploitations.
- Parcelles.
- Variétés et fiches techniques.
- Plans de production.
- Calculs de densité.
- Dimensionnement et devis d'irrigation.
- Programme agronomique.
- Calendrier et tâches.
- Trésorerie.
- Récolte.
- IA assistée.
- Synchronisation hors ligne.

Évolutions :
- Gestion avancée des stocks.
- Comptabilité approfondie.
- Capteurs IoT.
- Prévisions météorologiques.
- Vision par ordinateur.
- Modèles prédictifs de rendement.
- Recommandations agronomiques avancées.