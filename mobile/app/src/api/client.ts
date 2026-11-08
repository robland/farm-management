/**
 * Mobile API client. The refresh token and device id live in the OS secure store
 * (expo-secure-store); the access token stays in memory (ARCHITECTURE.md §11).
 */

import { AuthError, NetworkError } from "@fms/sync-core";
import * as SecureStore from "expo-secure-store";

const REFRESH_KEY = "fms.refresh";
const DEVICE_KEY = "fms.deviceId";

export class ApiError extends Error {
  constructor(readonly status: number, readonly body: { code?: string; message?: string }) {
    super(body.message || `HTTP ${status}`);
    this.name = "ApiError";
  }
}

export class ApiClient {
  private access: string | null = null;
  private refreshing: Promise<boolean> | null = null;

  constructor(private readonly baseUrl: string) {}

  hasSession(): Promise<boolean> {
    return SecureStore.getItemAsync(REFRESH_KEY).then((value) => value !== null);
  }

  deviceId(): Promise<string | null> {
    return SecureStore.getItemAsync(DEVICE_KEY);
  }

  async login(identifier: string, password: string): Promise<{ userId: string; deviceId: string }> {
    const deviceId = await this.deviceId();
    const data = await this.request<{ access: string; refresh: string; device_id: string;
                                      user_id: string }>("POST", "/auth/login/", {
      identifier, password, platform: "android", device_label: "mobile",
      ...(deviceId ? { device_id: deviceId } : {}),
    }, false);
    this.access = data.access;
    await SecureStore.setItemAsync(REFRESH_KEY, data.refresh);
    await SecureStore.setItemAsync(DEVICE_KEY, data.device_id);
    return { userId: data.user_id, deviceId: data.device_id };
  }

  async logout(): Promise<void> {
    this.access = null;
    await SecureStore.deleteItemAsync(REFRESH_KEY);
  }

  private refresh(): Promise<boolean> {
    this.refreshing ??= (async () => {
      try {
        const token = await SecureStore.getItemAsync(REFRESH_KEY);
        if (!token) return false;
        const data = await this.request<{ access: string; refresh?: string }>(
          "POST", "/auth/refresh/", { refresh: token }, false);
        this.access = data.access;
        if (data.refresh) await SecureStore.setItemAsync(REFRESH_KEY, data.refresh);
        return true;
      } catch (error) {
        if (error instanceof NetworkError) throw error; // offline is not an expired session
        if (error instanceof ApiError) await this.logout();
        return false;
      } finally {
        this.refreshing = null;
      }
    })();
    return this.refreshing;
  }

  async request<T>(method: string, path: string, body?: unknown, auth = true,
                   retried = false): Promise<T> {
    if (auth && !this.access && !(await this.refresh())) throw new AuthError("Session expirée");
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: {
          "Content-Type": "application/json",
          ...(auth && this.access ? { Authorization: `Bearer ${this.access}` } : {}),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch {
      throw new NetworkError("Serveur injoignable");
    }
    if (response.status === 401 && auth && !retried) {
      this.access = null;
      if (await this.refresh()) return this.request<T>(method, path, body, auth, true);
      throw new AuthError("Session expirée");
    }
    const data: unknown = response.status === 204 ? undefined
      : await response.json().catch(() => ({}));
    if (!response.ok) throw new ApiError(response.status, (data ?? {}) as { message?: string });
    return data as T;
  }
}
