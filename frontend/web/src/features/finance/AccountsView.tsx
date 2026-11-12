/** Treasury accounts, members' contributions and loans (FR-070, Q35). Management is online only. */

import {
  ACCOUNT_KIND_LABELS, ACCOUNT_ROLE_LABELS, amountError, amountToString, CURRENCY_DECIMALS, type EntryKind,
  type FinanceRights, formatDate, formatMoney, isZero, label, parseAmount, todayIso, toAmount,
} from "@fms/shared";
import { type FormEvent, type ReactNode, useState } from "react";

import type { ApiClient } from "../../api/client";
import type { AccountBalance, LoanPosition, MemberStatement, TreasuryAccount } from "../../api/types";
import { useNotifications } from "../../notifications/NotificationsContext";
import { useSync } from "../../sync/SyncContext";
import { Button, Card, EmptyState, ErrorMessage, Field, Select, useBusy } from "../../ui/components";
import { errorText, type Remote, useRemote } from "./data";
import { Badge, Freshness, SignedMoney } from "./ui";

type Panel = null | "account" | "opening" | "loan";

export function AccountsView(props: {
  api: ApiClient;
  rights: FinanceRights;
  accounts: TreasuryAccount[];
  loans: Remote<LoanPosition[]>;
  defaultCurrency: string;
  onEntry: (kind: EntryKind, loan?: string) => void;
}): ReactNode {
  const { farmId, syncNow, online } = useSync();
  const { notify } = useNotifications();
  const [panel, setPanel] = useState<Panel>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const balances = useRemote<AccountBalance[]>(props.api, `/farms/${farmId}/treasury-accounts/balances/`,
                                               `fms.balances.${farmId}`);
  const members = useRemote<MemberStatement[]>(props.api, `/farms/${farmId}/treasury-accounts/members/`,
                                               `fms.members.${farmId}`);
  const balanceOf = (id: string) => (balances.data ?? []).find((b) => b.account === id);
  const farmAccounts = props.accounts.filter((a) => a.role !== "member")
    .sort((a, b) => Number(b.role === "main") - Number(a.role === "main") || Number(b.is_active) - Number(a.is_active));
  const manage = props.rights.manageAccounts;

  const done = async (text: string) => {
    notify({ type: "success", farmId, text });
    setPanel(null);
    balances.reload();
    props.loans.reload();
    await syncNow();
  };
  const call = (fn: () => Promise<unknown>, text: string) => run(async () => {
    setError(null);
    try {
      await fn();
      await done(text);
    } catch (err) {
      setError(errorText(err));
    }
  });
  const setMain = (a: TreasuryAccount) => call(
    () => props.api.request("POST", `/farms/${farmId}/treasury-accounts/${a.id}/set-main/`, {}),
    `« ${a.name} » est désormais le compte principal.`);
  const toggleActive = (a: TreasuryAccount) => call(
    () => props.api.request("PATCH", `/farms/${farmId}/treasury-accounts/${a.id}/`, { is_active: !a.is_active },
                            { headers: { "If-Match": String(a.version ?? 1) } }),
    a.is_active ? `Compte « ${a.name} » désactivé.` : `Compte « ${a.name} » réactivé.`);

  return (
    <div className="flex flex-col gap-4">
      <Freshness offline={balances.offline} error={balances.error} fetchedAt={balances.fetchedAt} onRetry={balances.reload} />
      {error && !panel && <ErrorMessage>{error}</ErrorMessage>}

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2 p-3 pb-1">
          <h3 className="font-semibold">Comptes de trésorerie</h3>
          <div className="flex flex-wrap gap-2">
            {props.rights.validate && farmAccounts.length > 0 && (
              <Button variant="secondary" disabled={!online} onClick={() => setPanel("opening")}>Saisir un solde d'ouverture</Button>
            )}
            {manage && <Button disabled={!online} onClick={() => setPanel("account")}>Nouveau compte</Button>}
          </div>
        </div>
        {panel === "account" && (
          <AccountForm busy={busy} error={error} defaultCurrency={props.defaultCurrency} first={farmAccounts.length === 0}
                       onCancel={() => setPanel(null)}
                       onSubmit={(body) => void call(() => props.api.request("POST", `/farms/${farmId}/treasury-accounts/`, body),
                                                     `Compte « ${String(body.name)} » créé.`)} />
        )}
        {panel === "opening" && (
          <OpeningForm busy={busy} error={error} accounts={farmAccounts.filter((a) => a.is_active)}
                       onCancel={() => setPanel(null)}
                       onSubmit={(body) => void call(() => props.api.request(
                         "POST", `/farms/${farmId}/treasury-accounts/opening/`, body,
                         { headers: { "Idempotency-Key": crypto.randomUUID() } }), "Solde d'ouverture enregistré.")} />
        )}
        {farmAccounts.length === 0 ? (
          <div className="p-3"><EmptyState hint={manage ? "Le premier compte créé devient le compte principal." : undefined}>
            Aucun compte de trésorerie.</EmptyState></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Comptes de trésorerie</caption>
              <thead>
                <tr className="border-b border-stone-200 text-xs text-stone-500">
                  <th scope="col" className="p-2 text-left">Compte</th>
                  <th scope="col" className="p-2 text-left">Nature</th>
                  <th scope="col" className="p-2 text-left">Rôle</th>
                  <th scope="col" className="p-2 text-right">Solde validé</th>
                  <th scope="col" className="p-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {farmAccounts.map((a) => {
                  const b = balanceOf(a.id);
                  return (
                    <tr key={a.id} className={`border-b border-stone-100 ${a.is_active ? "" : "text-stone-400"}`}>
                      <td className="p-2">
                        <span className="font-medium">{a.name}</span>{!a.is_active && <> <Badge tone="muted">Désactivé</Badge></>}
                        {(a.institution || a.account_ref) && (
                          <><br /><span className="text-xs text-stone-500">{[a.institution, a.account_ref].filter(Boolean).join(" · ")}</span></>
                        )}
                      </td>
                      <td className="p-2">{label(ACCOUNT_KIND_LABELS, a.kind)}</td>
                      <td className="p-2">{a.role === "main" ? <Badge tone="ok">Principal</Badge> : label(ACCOUNT_ROLE_LABELS, a.role)}</td>
                      <td className="p-2 text-right tabular-nums">
                        {b ? <SignedMoney amount={toAmount(b.balance)} currency={a.currency} /> : "—"}
                      </td>
                      <td className="p-2 text-right whitespace-nowrap">
                        {manage && a.role !== "main" && a.is_active && (
                          <Button variant="ghost" disabled={busy || !online} onClick={() => void setMain(a)}>Définir comme principal</Button>
                        )}
                        {manage && a.role !== "main" && (
                          <Button variant="ghost" disabled={busy || !online} onClick={() => void toggleActive(a)}>
                            {a.is_active ? "Désactiver" : "Réactiver"}
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="p-3 text-xs text-stone-500">
          Un seul compte principal par exploitation : il reçoit les apports des membres et règle les remboursements
          d'emprunt. Un compte qui a des opérations ne se supprime pas, il se désactive.
        </p>
      </Card>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2 p-3 pb-1">
          <h3 className="font-semibold">Comptes de membres</h3>
          <span className="text-xs text-stone-500">Seul le titulaire saisit un apport sur son compte.</span>
        </div>
        {(members.data ?? []).length === 0 ? (
          <p className="p-3 text-sm text-stone-500">{members.error ? "Indisponible hors ligne." : "Aucun compte de membre."}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <caption className="sr-only">Comptes de membres</caption>
              <thead>
                <tr className="border-b border-stone-200 text-xs text-stone-500">
                  <th scope="col" className="p-2 text-left">Titulaire</th>
                  <th scope="col" className="p-2 text-right">Apporté (validé)</th>
                  <th scope="col" className="p-2 text-right">En attente</th>
                  <th scope="col" className="p-2 text-right">Transféré à la trésorerie</th>
                  <th scope="col" className="p-2 text-right">Solde</th>
                </tr>
              </thead>
              <tbody>
                {(members.data ?? []).map((m) => (
                  <tr key={m.account} className="border-b border-stone-100">
                    <td className="p-2 font-medium">{m.holder_name || m.name}</td>
                    <td className="p-2 text-right">{formatMoney(toAmount(m.contributed), m.currency)}</td>
                    <td className="p-2 text-right text-amber-900">{formatMoney(toAmount(m.pending_contributions), m.currency)}</td>
                    <td className="p-2 text-right">{formatMoney(toAmount(m.transferred_to_treasury), m.currency)}</td>
                    <td className="p-2 text-right font-semibold">{formatMoney(toAmount(m.balance), m.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2 p-3 pb-1">
          <h3 className="font-semibold">Emprunts</h3>
          {manage && <Button variant="secondary" disabled={!online} onClick={() => setPanel("loan")}>Nouvel emprunt</Button>}
        </div>
        {panel === "loan" && (
          <LoanForm busy={busy} error={error} defaultCurrency={props.defaultCurrency} onCancel={() => setPanel(null)}
                    onSubmit={(body) => void call(() => props.api.request("POST", `/farms/${farmId}/loans/`, body),
                                                  `Emprunt auprès de ${String(body.lender)} enregistré.`)} />
        )}
        {(props.loans.data ?? []).length === 0 ? (
          <p className="p-3 text-sm text-stone-500">{props.loans.error ? "Indisponible hors ligne." : "Aucun emprunt."}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <caption className="sr-only">Emprunts</caption>
              <thead>
                <tr className="border-b border-stone-200 text-xs text-stone-500">
                  <th scope="col" className="p-2 text-left">Prêteur</th>
                  <th scope="col" className="p-2 text-left">Depuis le</th>
                  <th scope="col" className="p-2 text-right">Accordé</th>
                  <th scope="col" className="p-2 text-right">Débloqué</th>
                  <th scope="col" className="p-2 text-right">Remboursé</th>
                  <th scope="col" className="p-2 text-right">Reste dû</th>
                  <th scope="col" className="p-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {(props.loans.data ?? []).map((l) => (
                  <tr key={l.loan} className="border-b border-stone-100">
                    <td className="p-2 font-medium">{l.lender}</td>
                    <td className="p-2">{formatDate(l.started_on)}</td>
                    <td className="p-2 text-right">{formatMoney(toAmount(l.principal), l.currency)}</td>
                    <td className="p-2 text-right">{formatMoney(toAmount(l.disbursed), l.currency)}</td>
                    <td className="p-2 text-right">{formatMoney(toAmount(l.repaid), l.currency)}</td>
                    <td className="p-2 text-right font-semibold">{formatMoney(toAmount(l.outstanding), l.currency)}</td>
                    <td className="p-2 text-right whitespace-nowrap">
                      {props.rights.create && (
                        <>
                          <Button variant="ghost" onClick={() => props.onEntry("funding", l.loan)}>Débloquer</Button>
                          {!isZero(toAmount(l.outstanding)) && (
                            <Button variant="ghost" onClick={() => props.onEntry("repayment", l.loan)}>Rembourser</Button>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="p-3 text-xs text-stone-500">
          Reste dû = débloqué − capital remboursé (opérations validées). Les intérêts sont des dépenses. Pas encore
          d'échéancier.
        </p>
      </Card>
    </div>
  );
}

const CURRENCIES = Object.keys(CURRENCY_DECIMALS);

function AccountForm(props: { busy: boolean; error: string | null; defaultCurrency: string; first: boolean;
                              onSubmit: (body: Record<string, unknown>) => void; onCancel: () => void }): ReactNode {
  const [form, setForm] = useState({ name: "", kind: "", currency: props.defaultCurrency, institution: "", account_ref: "" });
  const [errors, setErrors] = useState<Partial<Record<keyof typeof form, string>>>({});
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const found: typeof errors = {};
    if (!form.name.trim()) found.name = "Nom obligatoire.";
    if (!form.kind) found.kind = "Nature obligatoire.";
    setErrors(found);
    if (Object.keys(found).length) return;
    props.onSubmit({ ...form, name: form.name.trim(), institution: form.institution.trim(),
                     account_ref: form.account_ref.trim(), ...(props.first ? {} : { role: "operating" }) });
  };
  return (
    <form onSubmit={submit} noValidate aria-label="Nouveau compte" className="grid gap-3 border-y border-stone-200 bg-stone-50 p-3 sm:grid-cols-3">
      <Field label="Nom" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={errors.name} />
      <Select label="Nature" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} error={errors.kind}
              options={Object.entries(ACCOUNT_KIND_LABELS).map(([value, l]) => ({ value, label: l }))} />
      <Select label="Devise" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}
              options={CURRENCIES.map((c) => ({ value: c, label: c }))} />
      <Field label="Banque ou opérateur (facultatif)" value={form.institution}
             onChange={(e) => setForm({ ...form, institution: e.target.value })} />
      <Field label="Référence (facultatif)" value={form.account_ref} hint="Derniers chiffres du compte, numéro de téléphone…"
             onChange={(e) => setForm({ ...form, account_ref: e.target.value })} />
      {props.error && <div className="sm:col-span-3"><ErrorMessage>{props.error}</ErrorMessage></div>}
      <div className="flex gap-2 sm:col-span-3">
        <Button type="submit" disabled={props.busy}>{props.busy ? "Création…" : "Créer le compte"}</Button>
        <Button variant="secondary" onClick={props.onCancel}>Annuler</Button>
      </div>
    </form>
  );
}

function OpeningForm(props: { busy: boolean; error: string | null; accounts: TreasuryAccount[];
                              onSubmit: (body: Record<string, unknown>) => void; onCancel: () => void }): ReactNode {
  const [form, setForm] = useState({ account: props.accounts[0]?.id ?? "", balance: "", business_date: todayIso() });
  const [invalid, setInvalid] = useState<string | undefined>();
  const currency = props.accounts.find((a) => a.id === form.account)?.currency ?? "XAF";
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const err = parseAmount(form.balance) === 0n ? undefined : amountError(form.balance.replace(/^-/, ""), currency);
    setInvalid(err);
    if (err) return;
    props.onSubmit({ ...form, balance: amountToString(parseAmount(form.balance) ?? 0n) });
  };
  return (
    <form onSubmit={submit} noValidate aria-label="Solde d'ouverture" className="grid gap-3 border-y border-stone-200 bg-stone-50 p-3 sm:grid-cols-3">
      <Select label="Compte" value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })}
              options={props.accounts.map((a) => ({ value: a.id, label: `${a.name} (${a.currency})` }))} />
      <Field label={`Solde constaté (${currency})`} inputMode="decimal" value={form.balance} error={invalid}
             onChange={(e) => setForm({ ...form, balance: e.target.value })} />
      <Field label="À la date du" type="date" max={todayIso()} value={form.business_date}
             onChange={(e) => setForm({ ...form, business_date: e.target.value })} />
      <p className="text-xs text-stone-500 sm:col-span-3">
        Pour démarrer avec l'argent déjà présent sur le compte. Il ne compte ni en recette ni en dépense.
      </p>
      {props.error && <div className="sm:col-span-3"><ErrorMessage>{props.error}</ErrorMessage></div>}
      <div className="flex gap-2 sm:col-span-3">
        <Button type="submit" disabled={props.busy}>{props.busy ? "Envoi…" : "Enregistrer le solde"}</Button>
        <Button variant="secondary" onClick={props.onCancel}>Annuler</Button>
      </div>
    </form>
  );
}

function LoanForm(props: { busy: boolean; error: string | null; defaultCurrency: string;
                           onSubmit: (body: Record<string, unknown>) => void; onCancel: () => void }): ReactNode {
  const [form, setForm] = useState({ lender: "", principal: "", currency: props.defaultCurrency, started_on: todayIso(), notes: "" });
  const [errors, setErrors] = useState<Partial<Record<keyof typeof form, string>>>({});
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const found: typeof errors = {};
    if (!form.lender.trim()) found.lender = "Prêteur obligatoire.";
    const amount = amountError(form.principal, form.currency);
    if (amount) found.principal = amount;
    setErrors(found);
    if (Object.keys(found).length) return;
    props.onSubmit({ ...form, lender: form.lender.trim(), notes: form.notes.trim(),
                     principal: amountToString(parseAmount(form.principal) ?? 0n) });
  };
  return (
    <form onSubmit={submit} noValidate aria-label="Nouvel emprunt" className="grid gap-3 border-y border-stone-200 bg-stone-50 p-3 sm:grid-cols-4">
      <Field label="Prêteur" value={form.lender} onChange={(e) => setForm({ ...form, lender: e.target.value })} error={errors.lender} />
      <Field label={`Montant accordé (${form.currency})`} inputMode="decimal" value={form.principal} error={errors.principal}
             onChange={(e) => setForm({ ...form, principal: e.target.value })} />
      <Select label="Devise" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}
              options={CURRENCIES.map((c) => ({ value: c, label: c }))} />
      <Field label="Date de l'accord" type="date" value={form.started_on}
             onChange={(e) => setForm({ ...form, started_on: e.target.value })} />
      <div className="sm:col-span-4">
        <Field label="Notes (facultatif)" value={form.notes} hint="Taux, durée, conditions…"
               onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </div>
      <p className="text-xs text-stone-500 sm:col-span-4">
        L'emprunt est ensuite débloqué par un apport sur le compte principal (bouton « Débloquer »).
      </p>
      {props.error && <div className="sm:col-span-4"><ErrorMessage>{props.error}</ErrorMessage></div>}
      <div className="flex gap-2 sm:col-span-4">
        <Button type="submit" disabled={props.busy}>{props.busy ? "Envoi…" : "Enregistrer l'emprunt"}</Button>
        <Button variant="secondary" onClick={props.onCancel}>Annuler</Button>
      </div>
    </form>
  );
}
