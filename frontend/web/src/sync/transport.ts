import {
  CursorExpiredError,
  type PullResponse,
  type PushOperation,
  type PushResult,
  type Transport,
} from "@fms/sync-core";

import { ApiError, type ApiClient } from "../api/client";

export class HttpTransport implements Transport {
  constructor(private readonly api: ApiClient) {}

  async push(deviceId: string, operations: PushOperation[]): Promise<PushResult[]> {
    const data = await this.api.request<{ results: PushResult[] }>("POST", "/sync/push/", {
      device_id: deviceId,
      client_version: "web@0.1.0",
      protocol_version: 1,
      operations,
    });
    return data.results;
  }

  async pull(farmId: string, cursor: number, limit: number): Promise<PullResponse> {
    const query = new URLSearchParams({ farm_id: farmId, cursor: String(cursor),
                                        limit: String(limit) });
    try {
      return await this.api.request<PullResponse>("GET", `/sync/pull/?${query}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 410) {
        throw new CursorExpiredError(error.message);
      }
      throw error;
    }
  }
}
