/**
 * HTTP client for the versioned REST API (/api/v1).
 *
 * The access token lives in memory only. The refresh token is in an HttpOnly cookie set
 * by the server (OPEN_QUESTIONS Q26): no script can read it. localStorage only keeps a
 * non-secret marker saying that a session exists, so that the app resumes after a reload
 * while offline (FR-110) and knows when a refresh is worth trying.
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

const SESSION_KEY = "fms.session";
// Refresh token stored by versions before the cookie: sent once, then forgotten.
const LEGACY_REFRESH_KEY = "fms.refresh";
// Logout done offline: the server-side revocation of the cookie is retried later.
const PENDING_LOGOUT_KEY = "fms.pendingLogout";
const DEVICE_KEY = "fms.deviceId";
const COOKIE_TRANSPORT = { "X-FMS-Token-Transport": "cookie" };

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

  get hasSession(): boolean {
    return (
      this.storage.getItem(SESSION_KEY) !== null || this.storage.getItem(LEGACY_REFRESH_KEY) !== null
    );
  }

  deviceId(): string | null {
    return this.storage.getItem(DEVICE_KEY);
  }

  async login(identifier: string, password: string): Promise<Session> {
    if (this.storage.getItem(PENDING_LOGOUT_KEY)) await this.revokeCookie();
    const body = {
      identifier,
      password,
      platform: "web",
      device_label: navigator.userAgent.slice(0, 100),
      ...(this.deviceId() ? { device_id: this.deviceId() } : {}),
    };
    const data = await this.request<{ access: string; device_id: string; user_id: string }>(
      "POST", "/auth/login/", body, { auth: false, headers: COOKIE_TRANSPORT });
    this.access = data.access;
    this.storage.setItem(SESSION_KEY, "1");
    this.storage.removeItem(LEGACY_REFRESH_KEY);
    this.storage.setItem(DEVICE_KEY, data.device_id);
    return { userId: data.user_id, deviceId: data.device_id };
  }

  /** Ends the session on this device at once; the server revocation follows when online. */
  async logout(): Promise<void> {
    this.clearSession();
    this.storage.setItem(PENDING_LOGOUT_KEY, "1");
    await this.revokeCookie();
  }

  private clearSession(): void {
    this.access = null;
    this.storage.removeItem(SESSION_KEY);
    this.storage.removeItem(LEGACY_REFRESH_KEY);
  }

  private async revokeCookie(): Promise<void> {
    try {
      await this.request("POST", "/auth/logout/", {}, { auth: false, headers: COOKIE_TRANSPORT });
      this.storage.removeItem(PENDING_LOGOUT_KEY);
    } catch {
      // Offline: kept pending. The marker is gone, so the app never uses that cookie again.
    }
  }

  private async refresh(): Promise<boolean> {
    if (!this.hasSession) return false;
    const legacy = this.storage.getItem(LEGACY_REFRESH_KEY);
    this.refreshing ??= (async () => {
      try {
        const data = await this.request<{ access: string }>(
          "POST", "/auth/refresh/", legacy ? { refresh: legacy } : {},
          { auth: false, headers: COOKIE_TRANSPORT });
        this.access = data.access;
        this.storage.setItem(SESSION_KEY, "1");
        this.storage.removeItem(LEGACY_REFRESH_KEY);
        return true;
      } catch (error) {
        // Offline is not an expired session: keep the session and report the outage,
        // so the app keeps working on local data (FR-110).
        if (error instanceof NetworkError) throw error;
        if (error instanceof ApiError) this.clearSession();
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
