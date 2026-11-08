# AGRONOMY_ENGINE.md — Moteur agronomique

> Exigences couvertes : FR-032, FR-033, FR-041 à FR-043, FR-050, FR-051, FR-060, FR-091, NFR-007, CLAUDE.md §9.

## 1. Principes

- Paquet **Python pur** `backend/agronomy_engine/`, sans import Django, sans base de données, sans réseau et sans aléa. Pour les mêmes entrées, il produit les mêmes sorties.
- Types : `decimal.Decimal` uniquement. Les entrées sont des `dataclass(frozen=True)`, avec l'unité dans le nom du champ.
- Chaque fonction publique renvoie un `CalculationResult` :

```python
@dataclass(frozen=True)
class CalculationResult:
    calc_type: str               # "planting.density"
    engine_version: str          # "1.0.0"
    inputs: dict[str, Quantity]  # valeurs + unités
    outputs: dict[str, Quantity]
    formula: str                 # formule lisible
    assumptions: list[str]       # hypothèses explicites
    warnings: list[str]          # limites, valeurs atypiques
```

- **Pas de valeur agronomique par défaut.** Une entrée manquante lève `MissingInputError(field, reason)`, que l'API transforme en liste de données à compléter.
- Seules sont codées les constantes physiques et chimiques, documentées avec leur source :
  - g = 9,80665 m/s² (valeur conventionnelle CGPM).
  - ρ eau = 1000 kg/m³ (approximation à environ 4 à 20 °C, signalée en hypothèse).
  - P = P₂O₅ × 0,4364 ; K = K₂O × 0,8301 (rapports de masses molaires).
  - Coefficient de Hazen-Williams : 10,67 (forme SI).
  - Facteur de Christiansen avec m = 1,852.
- Arrondis : les calculs intermédiaires gardent toute la précision `Decimal`. Seules les quantités physiques discrètes (plants, goutteurs, rouleaux) sont arrondies, **vers le haut** pour un besoin ou **vers le bas** pour une capacité, et la règle est indiquée en hypothèse.
- Données théoriques et données mesurées : les entrées distinguent `*_theoretical` (fiche ou plan) et `*_measured` (terrain). Les résultats issus du terrain (rendements) ne réutilisent jamais une valeur théorique sans le signaler.

## 2. Unités (`agronomy_engine/units.py`)

Unités canoniques : m, m², ha (affichage), L, m³, kg, g, mm, bar, L/h, m³/h, kPa, W, kW, jours. Conversions explicites (`m2_to_ha`, `lph_to_m3h`, `bar_to_m_head`…). Une fonction qui attend des m² reçoit un paramètre nommé `area_m2`. Il n'y a pas de conversion implicite.

Rappel exigé par FR-041 : **le volume journalier (L/j ou m³/j) et le débit instantané (L/h ou m³/h) sont deux grandeurs distinctes**, toujours affichées séparément.

## 3. Densité de plantation et nombre de plants (`planting.py`)

Entrées :
- `row_spacing_m` (Er), `plant_spacing_m` (Ep), `plants_per_hole` (k).
- `allocated_area_m2` (S), `non_plantable_area_m2` (Snp, allées, chemins et bordures déclarés).
- Optionnel, pour la disposition géométrique : `plot_length_m` (L), `plot_width_m` (W), `headland_m` (b, bordure non plantée), `layout`, `bed_width_m`, `path_width_m`, `rows_per_bed`.

Calculs :
1. **Densité théorique** (plants/m²) : `Dth = k / (Er × Ep)`. La densité par hectare vaut `Dth × 10 000`.
2. **Surface plantable** : `Sp = S − Snp` (vérification Snp ≤ S).
3. **Plants théoriques sur la surface plantable** : `Nth = floor(Dth × Sp)`.
4. **Disposition géométrique** (si L et W sont fournis) :
   - Longueur utile de ligne : `Lu = L − 2b`. Largeur utile : `Wu = W − 2b`.
   - En lignes simples : `n_rows = floor(Wu / Er) + 1` (lignes aux deux extrémités).
   - En planches : `n_beds = floor((Wu + path) / (bed + path))` et `n_rows = n_beds × rows_per_bed`.
   - Plants par ligne : `n_per_row = floor(Lu / Ep) + 1`.
   - **Plants réels** : `Nr = n_rows × n_per_row × k`.
5. **Densité réelle** : `Dr = Nr / S` (rapportée à la surface **brute** allouée). On fournit aussi `Nr / Sp`.
6. Avertissement si |Nr − Nth| / Nth > 10 %.

Hypothèses affichées : disposition rectangulaire, lignes parallèles à la longueur, premier plant en début de ligne.

## 4. Besoin en semences (`seeds.py`)

Entrées : `plant_count` (issu du §3, réel de préférence), `seeds_per_hole` (s), `germination_rate` (g ∈ ]0,1]), `nursery_success_rate` (r ∈ ]0,1], repiquage uniquement), `safety_margin_rate` (m ≥ 0), `seeds_per_gram` **ou** `thousand_seed_weight_g`, `seed_package_size_g` (optionnel).

- Points de semis : en semis direct, `holes = plant_count / k`. En repiquage, `holes = plant_count` (alvéoles, un plant repiqué par trou).
- Graines : `N_seeds = ceil(holes × s × (1 + m) / (g × r))`, avec r = 1 en semis direct.
- Masse : `mass_g = N_seeds / seeds_per_gram`, ou `N_seeds × TSW / 1000`.
- Conditionnement : `packages = ceil(mass_g / package_size_g)`.

Si g ou le poids des graines manque, le calcul lève `MissingInputError`. Aucun taux par défaut n'est utilisé.

## 5. Irrigation goutte-à-goutte (`irrigation/drip.py`)

### 5.1 Entrées
- Géométrie : `lateral_spacing_m`, `lateral_length_m`, `lateral_count` (ou calculé à partir des lignes de plantation × `laterals_per_row`), `emitter_spacing_m`, `emitter_flow_lph` (q), `operating_pressure_bar`.
- Besoin en eau : `et0_mm_per_day`, `kc` (par phase), `application_efficiency_rate` (Ea), `irrigated_area_m2`.
- Source et pompage : `source_max_flow_m3h` (optionnel), `max_irrigation_hours_per_day`, `static_lift_m`, `elevation_difference_m` (signé), `filter_head_loss_m`, `fittings_loss_rate` (part des pertes linéaires), `pump_efficiency_rate`.
- Conduites (optionnel) : liste de segments `{role, length_m, inner_diameter_mm, hazen_williams_c, outlets}`.

### 5.2 Calculs
1. Goutteurs par rampe : `ne = floor(lateral_length_m / emitter_spacing_m)`, avec premier goutteur à `emitter_spacing/2` (hypothèse).
2. Total des goutteurs : `NE = ne × lateral_count`.
3. **Débit instantané total** : `Qt (L/h) = NE × q`, soit `Qt (m³/h) = Qt / 1000`.
4. Pluviométrie équivalente : `I (mm/h) = q / (emitter_spacing × lateral_spacing)`.
5. **Besoin journalier** : `ETc = Kc × ET0` (mm/j). Le besoin net vaut `Vnet (L/j) = ETc × irrigated_area_m2` (1 mm sur 1 m² = 1 L), et le besoin brut `Vg = Vnet / Ea`.
6. Secteurs : si `source_max_flow_m3h` est fourni, `n_sectors = ceil(Qt_m3h / source_max_flow)`. Sinon, la valeur saisie est utilisée. Débit par secteur : `Qs = Qt / n_sectors`.
7. Durée d'arrosage par secteur et par jour : `t = (Vg / n_sectors) / Qs` (h). Durée totale : `t × n_sectors`. Avertissement si elle dépasse `max_irrigation_hours_per_day`.
8. Pertes de charge (si les segments sont renseignés), en Hazen-Williams SI : `hf = 10,67 × L × Q^1,852 / (C^1,852 × D^4,87)` (Q en m³/s, D en m). Pour une conduite à sorties multiples (rampes, porte-rampes), on multiplie par le facteur de Christiansen `F = 1/(m+1) + 1/(2N) + √(m−1)/(6N²)`.
9. Hauteur manométrique totale : `HMT = static_lift + elevation_difference + Σhf × (1 + fittings_loss_rate) + filter_head_loss + operating_pressure_bar × 10,197`.
10. Puissance hydraulique : `Ph (W) = ρ × g × Q(m³/s) × HMT`. Puissance absorbée : `Pa = Ph / η`.

Limites déclarées : Hazen-Williams est valable pour l'eau à température ambiante. Les variations de débit des goutteurs non autorégulants ne sont pas modélisées. L'uniformité n'est pas calculée (P1). Les éléments non renseignés (pertes de charge, dénivelé) sont **listés comme non pris en compte** dans les hypothèses.

### 5.3 Nomenclature (`irrigation/bom.py`)

À partir de la géométrie : longueur totale des rampes (`lateral_count × lateral_length`), goutteurs (si non intégrés), conduites principales et secondaires (longueurs des segments), vannes (`n_sectors`), filtres, régulateurs, pompe et injecteur (si l'option est cochée), raccords (bouchons de fin de rampe = `lateral_count`, prises de rampe = `lateral_count`). L'arrondi au conditionnement commercial (rouleaux) utilise `spec.roll_length_m` du catalogue. Chaque ligne porte une `rationale`. Une perte de chantier (`installation_waste_rate`) est saisie par l'utilisateur, jamais imposée.

### 5.4 Autres systèmes

L'aspersion et la micro-aspersion sont gérées en mode **paramétrique simple** au MVP (débit par asperseur × nombre, pluviométrie). Les autres systèmes sont configurables sans calcul hydraulique automatique, avec saisie manuelle de la nomenclature.

## 6. Quantités d'intrants (`inputs.py`)

- **Par nutriment cible** : `product_kg = dose_nutrient_kg_per_ha × area_ha / (content_pct / 100)`. Le contenu est pris dans la composition déclarée du produit, dans la forme correspondante (P₂O₅ ou P, avec conversion explicite si nécessaire).
- Apports associés : un même produit apporte d'autres nutriments. Ils sont calculés et affichés (`co_applied_nutrients`).
- **Par produit** : `basis=per_ha` → `dose × area_ha`. `per_plant` → `dose × plant_count`. `per_m2` → `dose × area_m2`.
- Liquides : `volume_l = mass_kg / density_kg_per_l` (densité déclarée, sinon `MissingInputError`).
- **La dose n'est jamais fournie par le moteur**. Elle provient d'un document validé ou d'une saisie utilisateur.
- Phytosanitaire : le moteur calcule seulement `quantité = dose × surface` ou la bouillie, à partir de la dose d'étiquette saisie, et vérifie la présence de `label_reference`.

## 7. Génération du calendrier (`calendar.py`)

Entrées : date de début (semis ou repiquage), liste ordonnée de phases `{code, duration_days}` (données techniques validées ou saisie), éléments de programme `{type, phase_code | day_offset, label}`.

- Les phases s'enchaînent : `start(i) = end(i−1) + 1` jour, `end(i) = start(i) + duration − 1`.
- Une intervention positionnée par phase est placée au début de la phase, plus son décalage éventuel.
- Résultat : phases datées et **propositions de tâches** (type, titre, dates, `source_ref`).
- Les tâches ne sont créées en base qu'à partir d'une **version de plan validée** (FR-035, FR-060). La régénération (FR-064) compare les propositions aux tâches existantes : une tâche `done` ou `in_progress` reste intacte, une tâche `todo` modifiée est remplacée (`superseded_by`), et une nouvelle tâche est ajoutée si besoin.

## 8. Devis (`quotation.py`)

`line_total = quantity × unit_price` (arrondi à l'exposant de la devise **par ligne**), `subtotal = Σ line_total`, avec remise ou taxe en option, saisies par l'utilisateur. Une quantité sans prix est signalée comme ligne « non chiffrée » et exclue du total, avec un avertissement. Les prix et la version de la liste de prix sont **copiés** dans le devis.

## 9. Rendements (`yield_.py`)

- `quantity_kg = quantity × kg_per_unit`, avec une conversion **mesurée** obligatoire pour les unités non massiques.
- Rendement brut : `Σ quantity_kg / (harvested_area_m2 / 10 000)` en kg/ha.
- Rendement commercialisable : on retire les pertes et les lots `rejected`.
- Écart à l'objectif : `(réel − cible) / cible × 100`.
- Coût de production par kg : `Σ dépenses validées allouées au cycle / quantité commercialisable`, calculé par le service `harvest` à partir des données de `finance`.

## 10. Déterministe et IA

| Élément | Déterministe (moteur) | IA (suggestion) | Utilisateur |
|---|---|---|---|
| Écartements, densité cible | — | peut proposer à partir de la fiche, avec citation | valide ou saisit |
| Nombre de plants, densité réelle | **calculé** | jamais | — |
| Taux de germination | — | peut extraire de la fiche | valide ou saisit |
| Quantité de semences | **calculé** | jamais | — |
| Durées des phases | — | peut extraire ou proposer | valide |
| Dates du calendrier | **calculé** | jamais | ajuste la date de début |
| Kc, ET0 | — | peut extraire (Kc) | saisit (ET0) |
| Débits, secteurs, HMT, puissance | **calculé** | jamais | — |
| Dose d'engrais | — | uniquement si elle est citée dans un document | valide ou saisit |
| Dose phytosanitaire | — | **interdit** | saisit depuis l'étiquette |
| Quantités d'intrants, devis | **calculé** | jamais | — |
| Rendement | **calculé** | jamais | — |

## 11. Tests

- Cas de référence calculés à la main et commentés (par exemple une parcelle de 50 m × 20 m, Er 1,5 m, Ep 0,5 m, k = 1).
- Tests de propriétés (hypothesis) : la densité diminue quand l'écartement augmente, `Nr ≤ k × S / (Er × Ep) + bordures`, aucune sortie négative, conservation des unités (m² ↔ ha).
- `MissingInputError` pour chaque entrée obligatoire.
- `engine_version` incrémentée à chaque changement de formule, avec un changelog dans `agronomy_engine/CHANGELOG.md`.
