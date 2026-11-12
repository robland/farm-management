import { describe, expect, it } from "vitest";

import {
  addAmounts, amountError, budgetTotals, compareAmounts, consumption, emptyTransactionForm, entryAccounts,
  financeRights, financeViews, formatPercent, normalizeBudgetRows, parseAmount, percentOf,
  sanitizeNotifications, signed, subtractAmounts, summarizeTreasury, toAmount, transactionActions,
  transactionBadges, transactionPayload, transferTargets, treasuryWindow, validateTransaction,
} from "./index";

describe("exact decimal arithmetic", () => {
  it("adds and subtracts without binary rounding", () => {
    expect(addAmounts("0.1", "0.2")).toBe("0.3");
    expect(addAmounts("1840000.0000", 212000, "85500")).toBe("2137500");
    expect(subtractAmounts("580000", "592500")).toBe("-12500");
    expect(compareAmounts("240000", "200000")).toBe(1);
    expect(signed("40000")).toBe("+40000");
    expect(signed("-12500")).toBe("-12500");
  });

  it("parses user input and rejects what is not a number", () => {
    expect(parseAmount("1 500,5")).toBe(15005000n);
    expect(parseAmount("abc")).toBeNull();
    expect(parseAmount("1.23456")).toBeNull(); // beyond NUMERIC(19, 4)
  });

  it("accepts the JSON numbers sent by the report endpoints (Q37)", () => {
    expect(toAmount(1840000)).toBe("1840000");
    expect(toAmount(-12.5)).toBe("-12.5");
    expect(toAmount(null)).toBe("0");
  });

  it("computes percentages exactly, rounded to 2 decimals", () => {
    expect(percentOf("-71500", "940000")).toBe("-7.61");
    expect(percentOf("40000", "200000")).toBe("20.00");
    expect(percentOf("-18500", "60000")).toBe("-30.83");
    expect(percentOf("1", "0")).toBeNull();
    expect(formatPercent("-7.61")).toBe("−7,61 %");
    expect(formatPercent("20.00")).toBe("+20,00 %");
    expect(formatPercent("0.00")).toBe("0,00 %");
  });

  it("checks the currency precision", () => {
    expect(amountError("35000", "XAF")).toBeUndefined();
    expect(amountError("35000.5", "XAF")).toBe("Montant entier en XAF (pas de centimes).");
    expect(amountError("12.345", "EUR")).toBe("Au plus 2 décimales en EUR.");
    expect(amountError("10,50", "EUR")).toBeUndefined();
    expect(amountError("10", "ZZZ")).toBe("Devise non prise en charge : ZZZ.");
    expect(amountError("0", "XAF")).toBe("Montant positif obligatoire.");
  });
});

describe("rights and views", () => {
  it("shows everything with finance.view", () => {
    const rights = financeRights(["finance.view", "finance.transaction.create", "finance.funding.create"]);
    expect(financeViews(rights)).toEqual(["overview", "journal", "budgets", "accounts", "member"]);
  });

  it("limits a storekeeper to their entries and a contributor to their account (Q35)", () => {
    expect(financeViews(financeRights(["finance.transaction.create"]))).toEqual(["journal"]);
    expect(financeViews(financeRights(["farm.view", "finance.funding.create"]))).toEqual(["journal", "member"]);
    expect(financeViews(financeRights(["farm.view"]))).toEqual([]);
  });

  it("offers validation actions only to validators, by status", () => {
    const validator = financeRights(["finance.transaction.validate"]);
    const clerk = financeRights(["finance.transaction.create"]);
    const submitted = { kind: "expense", status: "submitted", amount: "1" };
    const validated = { kind: "transfer", status: "validated", amount: "1" };
    expect(transactionActions(submitted, validator)).toEqual({ validate: true, reject: true, reverse: false, correct: false });
    expect(transactionActions(validated, validator)).toEqual({ validate: false, reject: false, reverse: true, correct: false });
    expect(transactionActions(submitted, clerk)).toEqual({ validate: false, reject: false, reverse: false, correct: false });
  });

  it("flags a possible duplicate while it waits for validation", () => {
    expect(transactionBadges({ kind: "expense", status: "submitted", amount: "1", possible_duplicate: true })
      .map((b) => b.label)).toEqual(["À valider", "Doublon possible"]);
  });
});

describe("transaction form", () => {
  const accounts = [
    { id: "main", name: "Trésorerie", kind: "bank", role: "main", currency: "XAF", is_active: true },
    { id: "cash", name: "Caisse", kind: "cash", role: "operating", currency: "XAF", is_active: true },
    { id: "eur", name: "Euro", kind: "bank", role: "operating", currency: "EUR", is_active: true },
    { id: "mem", name: "Apports Paul", kind: "cash", role: "member", holder: "u2", currency: "XAF", is_active: true },
    { id: "old", name: "Ancienne", kind: "cash", role: "operating", currency: "XAF", is_active: false },
  ];
  const today = "2026-11-09";

  it("never offers a member account for expenses nor as a transfer target", () => {
    expect(entryAccounts(accounts).map((a) => a.id)).toEqual(["main", "cash", "eur"]);
    expect(transferTargets(accounts, "main").map((a) => a.id)).toEqual(["cash"]);
  });

  it("validates each kind with the server's rules", () => {
    const expense = { ...emptyTransactionForm("expense", today), account: "mem", amount: "10" };
    expect(validateTransaction(expense, accounts, today)).toEqual({
      account: "Un compte de membre ne sert ni aux dépenses ni aux recettes.", category: "Catégorie obligatoire.",
    });
    const transfer = { ...emptyTransactionForm("transfer", today), account: "main", to_account: "eur", amount: "10" };
    expect(validateTransaction(transfer, accounts, today).to_account).toBe("Les deux comptes doivent avoir la même devise.");
    const fromMember = { ...emptyTransactionForm("transfer", today), account: "mem", amount: "10" };
    expect(validateTransaction(fromMember, accounts, today)).toEqual({}); // to the main account, server side
    const repayment = { ...emptyTransactionForm("repayment", today), account: "cash", amount: "10",
                        business_date: "2026-11-10" };
    expect(validateTransaction(repayment, accounts, today)).toEqual({
      account: "Un remboursement part du compte principal.", loan: "Emprunt obligatoire.",
      business_date: "La date ne peut pas être dans le futur.",
    });
  });

  it("sends only the fields of the chosen kind", () => {
    const form = { ...emptyTransactionForm("transfer", today), account: "main", to_account: "cash",
                   amount: "60 000", category: "c1", campaign: "camp", description: " caisse " };
    expect(transactionPayload(form, "XAF")).toEqual({
      kind: "transfer", account: "main", to_account: "cash", amount: "60000", currency: "XAF",
      business_date: today, description: "caisse",
    });
    const expense = { ...form, kind: "expense" as const };
    expect(transactionPayload(expense, "XAF")).toMatchObject({ category: "c1", campaign: "camp" });
    expect(transactionPayload(expense, "XAF")).not.toHaveProperty("to_account");
  });
});

describe("reports", () => {
  it("totals the treasury and keeps fundings out of the campaign result", () => {
    const [xaf] = summarizeTreasury({ currencies: { XAF: { opening_balance: 1500000, periods: [
      { period_start: "2026-10-19", inflows: 0, outflows: 120000, investments: 0, fundings: 500000, repayments: 0,
        transfers: 0, opening_entries: 0, net: 380000, closing_balance: 1880000 },
      { period_start: "2026-10-26", inflows: "350000.0000", outflows: "210500", investments: 0, fundings: 0,
        repayments: 100000, transfers: 60000, opening_entries: 0, net: 39500, closing_balance: 1919500 },
    ] } } });
    expect(xaf?.totals.inflows).toBe("350000");
    expect(xaf?.totals.fundings).toBe("500000");
    expect(xaf?.closing).toBe("1919500");
    expect(xaf?.campaignResult).toBe("19500");
  });

  it("reports budget variances per currency", () => {
    const rows = normalizeBudgetRows([
      { budget_line: "a", label: "MO", category: "Main-d'œuvre", currency: "XAF", planned: 200000, actual: 240000,
        pending: 60000, variance: 40000, variance_pct: 20 },
      { budget_line: "b", label: "Engrais", category: "Engrais", currency: "XAF", planned: "150000", actual: "102000",
        pending: "48000", variance: "-48000", variance_pct: -32 },
    ]);
    expect(rows[0]?.variance_pct).toBe("20.00");
    expect(budgetTotals(rows)).toEqual([{ currency: "XAF", planned: "350000", actual: "342000", pending: "108000",
                                           variance: "-8000", variance_pct: "-2.29" }]);
    expect(consumption(rows[0]!)).toEqual({ actual: 100, pending: 0, over: true });
    expect(consumption(rows[1]!)).toEqual({ actual: 68, pending: 32, over: false });
  });

  it("chooses a report window aligned on the server's buckets", () => {
    expect(treasuryWindow("2026-11-09", "week")).toEqual({ from: "2026-09-21", to: "2026-11-09" });
    expect(treasuryWindow("2026-11-09", "month")).toEqual({ from: "2026-06-01", to: "2026-11-09" });
    expect(treasuryWindow("2026-11-09", "day")).toEqual({ from: "2026-10-27", to: "2026-11-09" });
  });
});

describe("notification targets", () => {
  it("maps the former Dépenses tab to Finances", () => {
    const [n] = sanitizeNotifications([{ id: "1", type: "info", text: "t", createdAt: "x", read: false, farmId: null,
                                         action: { label: "Voir", tab: "expenses" } }]);
    expect(n?.action?.tab).toBe("finances");
  });
});
