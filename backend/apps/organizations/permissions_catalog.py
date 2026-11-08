"""Catalogue of permission codes and the default role matrix.

Permission codes are defined in code (they are checked by the backend);
roles and their permission sets are stored per organization and are
configurable (FR-004). The default matrix below is a proposal
(OPEN_QUESTIONS Q14).
"""

from typing import TypedDict

PERMISSIONS: dict[str, str] = {
    "farm.view": "Consulter l'exploitation",
    "farm.manage": "Modifier les paramètres de l'exploitation",
    "members.view": "Consulter les membres de l'exploitation",
    "members.manage": "Gérer les membres et invitations de l'exploitation",
    "fields.view": "Consulter les champs et parcelles",
    "fields.edit": "Créer et modifier les champs et parcelles",
    "varieties.view": "Consulter le référentiel des cultures et variétés",
    "varieties.edit": "Modifier le référentiel des cultures et variétés",
    "varieties.validate": "Valider les données techniques des variétés",
    "plans.view": "Consulter les plans de production",
    "plans.edit": "Créer et modifier les brouillons de plans",
    "plans.validate": "Valider un plan de production",
    "irrigation.view": "Consulter l'irrigation et les devis",
    "irrigation.edit": "Dimensionner l'irrigation et établir des devis",
    "tasks.view": "Consulter les tâches",
    "tasks.edit": "Créer, modifier et générer les tâches",
    "tasks.assign": "Affecter les tâches",
    "tasks.report": "Rendre compte des tâches réalisées",
    "observations.view": "Consulter les observations",
    "observations.create": "Enregistrer des observations",
    "inventory.view": "Consulter le catalogue et les stocks",
    "inventory.edit": "Modifier le catalogue, fournisseurs et prix",
    "finance.view": "Consulter la trésorerie",
    "finance.transaction.create": "Saisir des recettes et dépenses",
    "finance.transaction.validate": "Valider, rejeter et annuler des transactions",
    "finance.accounts.manage": "Gérer les comptes de trésorerie",
    "finance.budget.edit": "Établir les budgets",
    "harvest.view": "Consulter les récoltes",
    "harvest.record": "Enregistrer des récoltes",
    "ai.use": "Utiliser l'assistant IA",
    "audit.view": "Consulter le journal d'audit",
}


class RoleSpec(TypedDict):
    name: str
    permissions: list[str]


_ALL = list(PERMISSIONS)
_VIEW = [p for p in PERMISSIONS if p.endswith(".view")]

DEFAULT_ROLES: dict[str, RoleSpec] = {
    "org_admin": {"name": "Administrateur de l'organisation", "permissions": _ALL},
    "farm_manager": {"name": "Gestionnaire d'exploitation", "permissions": _ALL},
    "agri_manager": {
        "name": "Responsable agricole",
        "permissions": [
            *_VIEW,
            "fields.edit",
            "varieties.edit",
            "varieties.validate",
            "plans.edit",
            "plans.validate",
            "irrigation.edit",
            "tasks.edit",
            "tasks.assign",
            "tasks.report",
            "observations.create",
            "harvest.record",
            "finance.budget.edit",
            "ai.use",
        ],
    },
    "technician": {
        "name": "Technicien agricole",
        "permissions": [
            "farm.view",
            "members.view",
            "fields.view",
            "varieties.view",
            "plans.view",
            "plans.edit",
            "irrigation.view",
            "tasks.view",
            "tasks.report",
            "observations.view",
            "observations.create",
            "inventory.view",
            "harvest.view",
            "harvest.record",
            "ai.use",
        ],
    },
    "worker": {
        "name": "Ouvrier",
        "permissions": [
            "farm.view",
            "fields.view",
            "tasks.view",
            "tasks.report",
            "observations.view",
            "observations.create",
            "harvest.view",
            "harvest.record",
        ],
    },
    "storekeeper": {
        "name": "Magasinier",
        "permissions": [
            "farm.view",
            "fields.view",
            "tasks.view",
            "inventory.view",
            "inventory.edit",
            "harvest.view",
            "finance.transaction.create",
        ],
    },
    "finance_manager": {
        "name": "Gestionnaire financier",
        "permissions": [
            "farm.view",
            "members.view",
            "plans.view",
            "irrigation.view",
            "inventory.view",
            "harvest.view",
            "finance.view",
            "finance.transaction.create",
            "finance.transaction.validate",
            "finance.accounts.manage",
            "finance.budget.edit",
            "audit.view",
        ],
    },
}


def is_valid_permission(code: str) -> bool:
    return code in PERMISSIONS
