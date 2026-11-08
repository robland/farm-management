import { AuthError, NetworkError } from "@fms/sync-core";
import { beforeEach, describe, expect, it } from "vitest";

import { ApiClient } from "./client";

beforeEach(() => localStorage.clear());

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

describe("ApiClient", () => {
  it("keeps the session when the network is down (offline start)", async () => {
    localStorage.setItem("fms.refresh", "r");
    const api = new ApiClient("/api/v1", async () => { throw new TypeError("Failed to fetch"); });
    await expect(api.request("GET", "/me/")).rejects.toBeInstanceOf(NetworkError);
    expect(api.hasRefreshToken).toBe(true);
  });

  it("logs out when the server rejects the refresh token", async () => {
    localStorage.setItem("fms.refresh", "r");
    const api = new ApiClient("/api/v1", async () =>
      json({ code: "token_not_valid", message: "", details: {}, field_errors: {} }, 401));
    await expect(api.request("GET", "/me/")).rejects.toBeInstanceOf(AuthError);
    expect(api.hasRefreshToken).toBe(false);
  });

  it("refreshes the access token and retries the request after a 401", async () => {
    localStorage.setItem("fms.refresh", "r1");
    const calls: string[] = [];
    let first = true;
    const api = new ApiClient("/api/v1", async (input) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith("/auth/refresh/")) return json({ access: "a2", refresh: "r2" });
      if (first) {
        first = false;
        return json({ code: "x", message: "", details: {}, field_errors: {} }, 401);
      }
      return json({ ok: true });
    });
    await expect(api.request("GET", "/me/")).resolves.toEqual({ ok: true });
    expect(localStorage.getItem("fms.refresh")).toBe("r2");
    expect(calls.filter((c) => c.endsWith("/auth/refresh/"))).toHaveLength(2);
  });
});
