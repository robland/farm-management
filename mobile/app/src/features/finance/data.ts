/**
 * Finance data on the phone. Accounts and transactions come from the synced local
 * database; reports and categories come from the server and are cached in SQLite, so
 * that the screens still show the last answer offline, with its date.
 */

import { fieldErrorLines } from "@fms/shared";
import { NetworkError } from "@fms/sync-core";
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../../api/client";
import { useSession } from "../../session/Session";

export interface Account {
  id: string;
  name: string;
  kind: string;
  role?: "main" | "member" | "operating";
  holder?: string | null;
  currency: string;
  is_active: boolean;
}

export interface Category {
  id: string;
  name: string;
  kind: "expense" | "income" | "investment";
  is_capex?: boolean;
  is_active?: boolean;
}

export interface Tx {
  id: string;
  kind: string;
  status: string;
  business_date: string;
  amount: string;
  currency: string;
  description: string;
  category?: string | null;
  possible_duplicate?: boolean;
  rejected_reason?: string;
  created_at?: string;
  version?: number;
  entries?: { account: string; amount: string }[];
  /** Local operations keep their creation payload: account and target. */
  account?: string;
  to_account?: string;
}

export function errorText(error: unknown): string {
  if (error instanceof NetworkError) return "Pas de réseau : cette action se fait en ligne.";
  if (error instanceof ApiError) {
    if (error.status === 403) return "Vous n'avez pas l'autorisation de faire cette opération.";
    if (error.status === 409) return "La donnée a été modifiée entre-temps : actualisez puis recommencez.";
    return [error.body.message || `Erreur ${error.status}`, ...fieldErrorLines(error.body.field_errors)].join(" ");
  }
  return error instanceof Error ? error.message : String(error);
}

export interface Remote<T> {
  data: T | null;
  fetchedAt: string | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** GET cached in the user's database; `path` null skips the request. */
export function useRemote<T>(path: string | null, key: string): Remote<T> {
  const { api, store } = useSession();
  const [state, setState] = useState<Omit<Remote<T>, "reload">>({ data: null, fetchedAt: null, error: null,
                                                                    loading: Boolean(path) });
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  useEffect(() => {
    if (!path || !store) return;
    let active = true;
    void store.getValue<{ data: T; at: string }>(key).then((cached) => {
      if (active && cached) setState((s) => (s.data ? s : { ...s, data: cached.data, fetchedAt: cached.at }));
    });
    api.request<T>("GET", path).then((data) => {
      if (!active) return;
      const at = new Date().toISOString();
      void store.setValue(key, { data, at });
      setState({ data, fetchedAt: at, error: null, loading: false });
    }).catch((error: unknown) => {
      if (active) setState((s) => ({ ...s, loading: false, error: errorText(error) }));
    });
    return () => {
      active = false;
    };
  }, [api, store, path, key, tick]);
  return { ...state, reload };
}

export function useCategories(): Category[] {
  const { farm } = useSession();
  const org = farm?.organization_id;
  const remote = useRemote<{ results: Category[] }>(org ? `/organizations/${org}/finance-categories/?page_size=200` : null,
                                                    `finance-categories.${org ?? ""}`);
  return (remote.data?.results ?? []).filter((c) => c.is_active !== false);
}
