import type { RequestOptions, Transport } from "../client.js";
import type { APIPromise } from "../response.js";
import type { QueryOf, ResponseOf } from "../types.js";

export class PricingResource {
  constructor(private readonly t: Transport) {}

  /** `get_pricing`. Free: per-endpoint credit costs. */
  get(
    query?: QueryOf<"get_pricing">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_pricing">> {
    return this.t.request({ method: "GET", path: "/api/v1/api-credits/pricing", query }, options);
  }
}
