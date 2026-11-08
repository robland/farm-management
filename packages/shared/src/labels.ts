/**
 * User-facing labels for server codes (French). They mirror the Django choices labels;
 * an unknown code is shown as-is rather than hidden (organizations can define roles).
 */

import { formatArea, formatMoney, formatNumber } from "./format";

export type LocalState = "pending" | "syncing" | "synced" | "failed" | "conflict";

export const LOCAL_STATE_LABELS: Record<LocalState, string> = {
  pending: "En attente de synchronisation",
  syncing: "Synchronisation…",
  synced: "Envoyé",
  failed: "Refusé par le serveur",
  conflict: "Conflit à résoudre",
};

/** Default roles (backend apps/organizations/permissions_catalog.py). */
export const ROLE_LABELS: Record<string, string> = {
  org_admin: "Administrateur de l'organisation",
  farm_manager: "Gestionnaire d'exploitation",
  agri_manager: "Responsable agricole",
  technician: "Technicien agricole",
  worker: "Ouvrier",
  storekeeper: "Magasinier",
  finance_manager: "Gestionnaire financier",
};

export const TASK_STATUS_LABELS: Record<string, string> = {
  todo: "À faire",
  in_progress: "En cours",
  done: "Réalisée",
  cancelled: "Annulée",
  to_verify: "À vérifier",
};

export const TRANSACTION_KIND_LABELS: Record<string, string> = {
  expense: "Dépense",
  income: "Recette",
  transfer: "Transfert",
  reversal: "Annulation",
  opening: "Solde d'ouverture",
};

export const TRANSACTION_STATUS_LABELS: Record<string, string> = {
  submitted: "En attente de validation",
  validated: "Validée",
  rejected: "Rejetée",
  reversed: "Annulée",
};

export const OBSERVATION_KIND_LABELS: Record<string, string> = {
  pest: "Ravageur", disease: "Maladie", growth: "Croissance", weather: "Météo", water: "Eau",
  other: "Autre",
};

export function label(map: Record<string, string>, code: string | null | undefined): string {
  if (!code) return "";
  return map[code] ?? code;
}

export const roleLabel = (code: string | null | undefined): string => label(ROLE_LABELS, code);

// --- Operations of the sync queue --------------------------------------------------

/** Structural subset of sync-core's LocalOperation (no dependency on the engine). */
export interface OperationLike {
  opType: "create" | "update" | "delete" | "command";
  command?: string;
  entityType: string;
  payload: Record<string, unknown>;
  lastError?: { code: string; message: string; fieldErrors?: unknown };
}

const ENTITY_NOUNS: Record<string, string> = {
  "fields.field": "champ",
  "fields.parcel": "parcelle",
  "farms.farm": "exploitation",
  "tasks.task": "tâche",
  "tasks.task_report": "compte rendu de tâche",
  "finance.transaction": "transaction",
  "finance.account": "compte de trésorerie",
  "agronomy.observation": "observation",
  "harvest.harvest_record": "récolte",
};

const VERBS: Record<OperationLike["opType"], string> = {
  create: "Nouvelle saisie",
  update: "Modification",
  delete: "Suppression",
  command: "Action",
};

const text = (value: unknown): string => (typeof value === "string" ? value : "");

/** One-line title of a queued operation: "Dépense de 15 000 XAF", "Nouvelle parcelle"… */
export function describeOperation(op: OperationLike): string {
  const p = op.payload;
  if (op.command === "task.change_status") {
    return `Tâche : ${label(TASK_STATUS_LABELS, text(p.from))} → ${label(TASK_STATUS_LABELS, text(p.to))}`;
  }
  if (op.opType === "create") {
    switch (op.entityType) {
      case "fields.parcel":
        return "Nouvelle parcelle";
      case "tasks.task_report":
        return p.completion === "partial" ? "Compte rendu partiel de tâche" : "Tâche terminée";
      case "finance.transaction":
        return `${label(TRANSACTION_KIND_LABELS, text(p.kind)) || "Transaction"} de ${
          formatMoney(text(p.amount), text(p.currency))}`;
      case "agronomy.observation":
        return `Observation${p.kind ? ` : ${label(OBSERVATION_KIND_LABELS, text(p.kind)).toLowerCase()}` : ""}`;
      case "harvest.harvest_record":
        return `Récolte de ${formatNumber(text(p.quantity))} ${text(p.unit) || "kg"}`;
    }
  }
  const noun = ENTITY_NOUNS[op.entityType] ?? op.entityType;
  return `${VERBS[op.opType]} : ${noun}${op.command ? ` (${op.command})` : ""}`;
}

/** Human details of the payload, shown before abandoning an operation (never raw JSON). */
export function operationDetails(op: OperationLike): string[] {
  const p = op.payload;
  const lines: string[] = [];
  const add = (name: string, value: unknown) => {
    const v = text(value);
    if (v) lines.push(`${name} : ${v}`);
  };
  switch (op.entityType) {
    case "fields.parcel":
      add("Nom", p.name);
      add("Identifiant", p.code);
      if (text(p.area_m2)) lines.push(`Superficie : ${formatArea(text(p.area_m2))}`);
      add("pH du sol", p.soil_ph);
      break;
    case "finance.transaction":
      add("Date", p.business_date);
      add("Description", p.description);
      break;
    case "tasks.task_report":
      add("Notes", p.notes);
      break;
    case "agronomy.observation":
      add("Cible", p.target);
      if (typeof p.severity === "number") lines.push(`Gravité : ${p.severity}/5`);
      add("Notes", p.notes);
      break;
    case "harvest.harvest_record":
      add("Date", p.harvested_on);
      if (text(p.loss_quantity_kg)) lines.push(`Pertes : ${formatNumber(text(p.loss_quantity_kg))} kg`);
      break;
  }
  return lines;
}

const ERROR_MESSAGES: Record<string, string> = {
  dependency_failed: "Une saisie précédente a échoué : traitez-la d'abord.",
  author_mismatch: "Saisie faite par un autre utilisateur sur cet appareil.",
  not_found: "Donnée introuvable sur le serveur (supprimée ou inaccessible).",
  permission_denied: "Vous n'avez pas l'autorisation de faire cette opération.",
  validation_error: "Données invalides.",
  business_rule_violation: "Opération refusée par une règle de gestion.",
  version_conflict: "La donnée a été modifiée entre-temps par quelqu'un d'autre.",
  identifier_conflict: "Cet identifiant est déjà utilisé.",
  integrity_error: "Conflit temporaire sur le serveur : réessayez.",
  unknown_entity_type: "Type de saisie non pris en charge par le serveur : mettez l'application à jour.",
  idempotency_key_reused: "Saisie en double détectée par le serveur.",
};

/** Field errors from DRF ({field: [messages]}) as "field : message" lines. */
export function fieldErrorLines(fieldErrors: unknown): string[] {
  if (!fieldErrors || typeof fieldErrors !== "object" || Array.isArray(fieldErrors)) return [];
  return Object.entries(fieldErrors as Record<string, unknown>).flatMap(([field, value]) => {
    const messages = Array.isArray(value) ? value.filter((m) => typeof m === "string") : [text(value)];
    return messages.filter(Boolean).map((m) => (field === "non_field_errors" ? m : `${field} : ${m}`));
  });
}

/** Why the server refused an operation, in plain words. Server messages win (French). */
export function describeError(error: OperationLike["lastError"]): string {
  if (!error) return "";
  const base = error.message.trim() || ERROR_MESSAGES[error.code] || `Erreur : ${error.code}`;
  const fields = fieldErrorLines(error.fieldErrors);
  return fields.length ? `${base} ${fields.join(" · ")}` : base;
}
