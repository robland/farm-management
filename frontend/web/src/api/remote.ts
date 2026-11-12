/**
 * Server data that is not synced (reports, online-only actions): the last answer is cached
 * so that a screen still shows something offline, with its date.
 */

import { fieldErrorLines } from "@fms/shared";
import { NetworkError } from "@fms/sync-core";
import { useCallback, useEffect, useState } from "react";

import { ApiError, type ApiClient } from "./client";
import type { Paginated } from "./types";

export interface Remote<T> {
  data: T | null;
  loading: boolean;
  /** Set when the last request failed; `data` may still hold an older answer. */
  error: string | null;
  offline: boolean;
  /** Time of the answer shown (cached answers keep their original time). */
  fetchedAt: string | null;
  reload: () => void;
}

function readCache<T>(key: string): { data: T; at: string } | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as { data: T; at: string }) : null;
  } catch {
    return null;
  }
}

function writeCache(key: string, data: unknown): string {
  const at = new Date().toISOString();
  try {
    localStorage.setItem(key, JSON.stringify({ data, at }));
  } catch {
    // Full or blocked storage: the screen still works online.
  }
  return at;
}

/** Plain-French reason of a failed request (server messages are already in French). */
export function errorText(error: unknown): string {
  if (error instanceof NetworkError) return "Serveur injoignable : action possible seulement en ligne.";
  if (error instanceof ApiError) {
    if (error.status === 403) return "Vous n'avez pas l'autorisation de faire cette opération.";
    if (error.status === 409) return "La donnée a été modifiée entre-temps : rechargez puis recommencez.";
    return [error.body.message || `Erreur ${error.status}`, ...fieldErrorLines(error.body.field_errors)].join(" ");
  }
  return error instanceof Error ? error.message : String(error);
}

/** GET with a cache; `path` null skips the request (missing parameter or right). */
export function useRemote<T>(api: ApiClient, path: string | null, cacheKey: string): Remote<T> {
  const [state, setState] = useState<Omit<Remote<T>, "reload">>(() => {
    const cached = path ? readCache<T>(cacheKey) : null;
    return { data: cached?.data ?? null, fetchedAt: cached?.at ?? null, loading: Boolean(path), error: null,
             offline: false };
  });
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!path) {
      setState({ data: null, fetchedAt: null, loading: false, error: null, offline: false });
      return;
    }
    let active = true;
    const cached = readCache<T>(cacheKey);
    setState((s) => ({ ...s, data: s.data ?? cached?.data ?? null, fetchedAt: s.fetchedAt ?? cached?.at ?? null,
                       loading: true }));
    api.request<T>("GET", path).then((data) => {
      if (!active) return;
      const at = writeCache(cacheKey, data);
      setState({ data, fetchedAt: at, loading: false, error: null, offline: false });
    }).catch((error: unknown) => {
      if (!active) return;
      setState((s) => ({ ...s, loading: false, offline: error instanceof NetworkError, error: errorText(error) }));
    });
    return () => {
      active = false;
    };
  }, [api, path, cacheKey, tick]);

  return { ...state, reload };
}

export const results = <T,>(page: Paginated<T> | T[] | null): T[] =>
  (Array.isArray(page) ? page : page?.results ?? []);
