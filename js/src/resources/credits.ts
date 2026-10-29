import type { RequestOptions, Transport } from "../client.js";
import type { APIPromise } from "../response.js";
import type { ResponseOf } from "../types.js";

export class CreditsResource {
  constructor(private readonly t: Transport) {}

  /** `get_credit_balance`. Free; derived from live credit buckets. */
  balance(options?: RequestOptions): APIPromise<ResponseOf<"get_credit_balance">> {
    return this.t.request({ method: "GET", path: "/api/v1/credits/balance" }, options);
  }
}
