/**
 * HTTP client for the versioned REST API (/api/v1).
 *
 * The access token lives in memory only. The refresh token is kept in localStorage
 * for the MVP so that the app can resume after a reload while offline
 * (OPEN_QUESTIONS Q26: move to an HttpOnly cookie during hardening).
 */

import { AuthError, NetworkError } from "@fms/sync-core";

export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
  field_errors: Record<string, unknown>;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: ApiErrorBody,
  ) {
    super(body.message || `HTTP ${status}`);
    this.name = "ApiError";
  }
}

const REFRESH_KEY = "fms.refresh";
const DEVICE_KEY = "fms.deviceId";

export interface Session {
  userId: string;
  deviceId: string;
}

type Fetch = typeof fetch;

export class ApiClient {
  private access: string | null = null;
  private refreshing: Promise<boolean> | null = null;

  constructor(
    private readonly baseUrl = "/api/v1",
    private readonly fetchImpl: Fetch = (...args) => fetch(...args),
    private readonly storage: Storage = localStorage,
  ) {}

  get hasRefreshToken(): boolean {
    return this.storage.getItem(REFRESH_KEY) !== null;
  }

  deviceId(): string | null {
    return this.storage.getItem(DEVICE_KEY);
  }

  async login(identifier: string, password: string): Promise<Session> {
    const body = {
      identifier,
      password,
      platform: "web",
      device_label: navigator.userAgent.slice(0, 100),
      ...(this.deviceId() ? { device_id: this.deviceId() } : {}),
    };
    const data = await this.request<{ access: string; refresh: string; device_id: string;
                                      user_id: string }>("POST", "/auth/login/", body, {
      auth: false,
    });
    this.access = data.access;
    this.storage.setItem(REFRESH_KEY, data.refresh);
    this.storage.setItem(DEVICE_KEY, data.device_id);
    return { userId: data.user_id, deviceId: data.device_id };
  }

  logout(): void {
    this.access = null;
    this.storage.removeItem(REFRESH_KEY);
  }

  private async refresh(): Promise<boolean> {
    const token = this.storage.getItem(REFRESH_KEY);
    if (!token) return false;
    this.refreshing ??= (async () => {
      try {
        const data = await this.request<{ access: string; refresh?: string }>(
          "POST", "/auth/refresh/", { refresh: token }, { auth: false });
        this.access = data.access;
        if (data.refresh) this.storage.setItem(REFRESH_KEY, data.refresh);
        return true;
      } catch (error) {
        // Offline is not an expired session: keep the refresh token and report the outage,
        // so the app keeps working on local data (FR-110).
        if (error instanceof NetworkError) throw error;
        if (error instanceof ApiError) this.logout();
        return false;
      } finally {
        this.refreshing = null;
      }
    })();
    return this.refreshing;
  }

  async request<T>(
    method: string,
    path: string,
    body?: unknown,
    options: { auth?: boolean; headers?: Record<string, string>; retried?: boolean } = {},
  ): Promise<T> {
    const auth = options.auth ?? true;
    if (auth && !this.access && !(await this.refresh())) {
      throw new AuthError("Session expirée");
    }
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers: {
          "Content-Type": "application/json",
          ...(auth && this.access ? { Authorization: `Bearer ${this.access}` } : {}),
          ...options.headers,
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch {
      throw new NetworkError("Serveur injoignable");
    }
    if (response.status === 401 && auth && !options.retried) {
      this.access = null;
      if (await this.refresh()) return this.request<T>(method, path, body, { ...options, retried: true });
      throw new AuthError("Session expirée");
    }
    if (response.status === 204) return undefined as T;
    const data: unknown = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new ApiError(response.status, data as ApiErrorBody);
    }
    return data as T;
  }
}
