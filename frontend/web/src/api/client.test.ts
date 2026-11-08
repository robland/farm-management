import { AuthError, NetworkError } from "@fms/sync-core";
import { beforeEach, describe, expect, it } from "vitest";

import { ApiClient } from "./client";

beforeEach(() => localStorage.clear());

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

const noContent = () => new Response(null, { status: 204 });

interface Call {
  url: string;
  headers: Record<string, string>;
  body: unknown;
}

function recorder(handler: (url: string) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({
      url,
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    return handler(url);
  };
  return { calls, fetchImpl };
}

const storedValues = () => Object.keys(localStorage).map((key) => localStorage.getItem(key));

describe("ApiClient", () => {
  it("never stores the refresh token: the server keeps it in an HttpOnly cookie", async () => {
    const { calls, fetchImpl } = recorder(() =>
      json({ access: "a1", device_id: "d1", user_id: "u1" }));
    const api = new ApiClient("/api/v1", fetchImpl);
    await api.login("awa@example.test", "secret");
    expect(calls[0]?.headers["X-FMS-Token-Transport"]).toBe("cookie");
    expect(api.hasSession).toBe(true);
    expect(localStorage.getItem("fms.refresh")).toBeNull();
    expect(storedValues()).not.toContain("a1"); // the access token stays in memory only
  });

  it("keeps the session when the network is down (offline start)", async () => {
    localStorage.setItem("fms.session", "1");
    const api = new ApiClient("/api/v1", async () => { throw new TypeError("Failed to fetch"); });
    await expect(api.request("GET", "/me/")).rejects.toBeInstanceOf(NetworkError);
    expect(api.hasSession).toBe(true);
  });

  it("ends the session when the server rejects the refresh cookie", async () => {
    localStorage.setItem("fms.session", "1");
    const api = new ApiClient("/api/v1", async () =>
      json({ code: "token_not_valid", message: "", details: {}, field_errors: {} }, 401));
    await expect(api.request("GET", "/me/")).rejects.toBeInstanceOf(AuthError);
    expect(api.hasSession).toBe(false);
  });

  it("refreshes through the cookie and retries the request after a 401", async () => {
    localStorage.setItem("fms.session", "1");
    let first = true;
    const { calls, fetchImpl } = recorder((url) => {
      if (url.endsWith("/auth/refresh/")) return json({ access: "a2" });
      if (first) {
        first = false;
        return json({ code: "x", message: "", details: {}, field_errors: {} }, 401);
      }
      return json({ ok: true });
    });
    const api = new ApiClient("/api/v1", fetchImpl);
    await expect(api.request("GET", "/me/")).resolves.toEqual({ ok: true });
    const refreshes = calls.filter((c) => c.url.endsWith("/auth/refresh/"));
    expect(refreshes).toHaveLength(2);
    expect(refreshes.every((c) => c.headers["X-FMS-Token-Transport"] === "cookie")).toBe(true);
    expect(refreshes[0]?.body).toEqual({});
  });

  it("moves a token stored by an older version to the cookie without logging out", async () => {
    localStorage.setItem("fms.refresh", "legacy-token");
    const { calls, fetchImpl } = recorder((url) =>
      url.endsWith("/auth/refresh/") ? json({ access: "a2" }) : json({ ok: true }));
    const api = new ApiClient("/api/v1", fetchImpl);
    expect(api.hasSession).toBe(true);
    await api.request("GET", "/me/");
    expect(calls[0]?.body).toEqual({ refresh: "legacy-token" });
    expect(localStorage.getItem("fms.refresh")).toBeNull();
    expect(api.hasSession).toBe(true);
  });

  it("logs out on the server, which deletes the cookie", async () => {
    localStorage.setItem("fms.session", "1");
    const { calls, fetchImpl } = recorder(() => noContent());
    const api = new ApiClient("/api/v1", fetchImpl);
    await api.logout();
    expect(api.hasSession).toBe(false);
    expect(calls.map((c) => c.url)).toEqual(["/api/v1/auth/logout/"]);
    expect(calls[0]?.headers["X-FMS-Token-Transport"]).toBe("cookie");
    expect(localStorage.getItem("fms.pendingLogout")).toBeNull();
  });

  it("retries the server logout at the next login when it happened offline", async () => {
    localStorage.setItem("fms.session", "1");
    let online = false;
    const { calls, fetchImpl } = recorder((url) => {
      if (!online) throw new TypeError("Failed to fetch");
      return url.endsWith("/auth/logout/")
        ? noContent()
        : json({ access: "a1", device_id: "d1", user_id: "u1" });
    });
    const api = new ApiClient("/api/v1", fetchImpl);
    await api.logout(); // offline: the device is logged out at once anyway
    expect(api.hasSession).toBe(false);
    expect(localStorage.getItem("fms.pendingLogout")).toBe("1");

    online = true;
    await api.login("awa@example.test", "secret");
    const urls = calls.map((c) => c.url);
    expect(urls.slice(-2)).toEqual(["/api/v1/auth/logout/", "/api/v1/auth/login/"]);
    expect(localStorage.getItem("fms.pendingLogout")).toBeNull();
  });
});
