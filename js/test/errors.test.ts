import { describe, expect, it } from "vitest";
import { makeStatusError } from "../src/errors.js";
import {
  APIStatusError,
  AuthenticationError,
  BadRequestError,
  ConflictError,
  DailyCapExceededError,
  IdempotencyInProgressError,
  IdempotencyKeyReusedError,
  IdempotencyReplayUnavailableError,
  InsufficientCreditsError,
  InternalServerError,
  NotFoundError,
  PermissionDeniedError,
  RateLimitError,
  UnprocessableEntityError,
  VaquillError,
} from "../src/index.js";
import { json, makeClient } from "./helpers.js";

const h = (extra: Record<string, string> = {}) => new Headers(extra);

describe("status mapping", () => {
  it.each([
    [400, BadRequestError],
    [401, AuthenticationError],
    [402, InsufficientCreditsError],
    [403, PermissionDeniedError],
    [404, NotFoundError],
    [409, ConflictError],
    [422, UnprocessableEntityError],
    [429, RateLimitError],
    [500, InternalServerError],
    [503, InternalServerError],
  ])("status %i", (status, cls) => {
    const e = makeStatusError(status, { detail: "x" }, h());
    expect(e).toBeInstanceOf(cls);
    expect(e).toBeInstanceOf(APIStatusError);
    expect(e).toBeInstanceOf(VaquillError);
    expect(e.status).toBe(status);
  });

  it("falls back to the base class for an unmapped status", () => {
    const e = makeStatusError(418, {}, h());
    expect(e.constructor).toBe(APIStatusError);
  });
});

describe("code mapping", () => {
  it.each([
    ["insufficient_credits", 402, InsufficientCreditsError],
    ["daily_cap_exceeded", 429, DailyCapExceededError],
    ["idempotency_key_reused", 422, IdempotencyKeyReusedError],
    ["idempotency_in_progress", 409, IdempotencyInProgressError],
    ["idempotency_replay_unavailable", 409, IdempotencyReplayUnavailableError],
  ])("%s", (code, status, cls) => {
    expect(makeStatusError(status, { code, detail: "x" }, h())).toBeInstanceOf(cls);
  });

  it("daily cap is a RateLimitError", () => {
    expect(makeStatusError(429, { code: "daily_cap_exceeded" }, h())).toBeInstanceOf(
      RateLimitError,
    );
  });

  it("an unknown code still maps by status", () => {
    const e = makeStatusError(404, { code: "brand_new_code", detail: "gone" }, h());
    expect(e).toBeInstanceOf(NotFoundError);
    expect(e.code).toBe("brand_new_code");
  });

  it("insufficient_credits maps even on an unexpected status", () => {
    expect(makeStatusError(429, { code: "insufficient_credits" }, h())).toBeInstanceOf(
      InsufficientCreditsError,
    );
  });
});

describe("envelope fields", () => {
  it("reads the full envelope", () => {
    const e = makeStatusError(
      429,
      {
        detail: "Slow down",
        code: "rate_limited",
        requestId: "req_1",
        retryable: true,
        retryAfterSeconds: 3,
        errors: [{ loc: ["body"], msg: "m", type: "t" }],
        title: "t",
      },
      h(),
    );
    expect(e.message).toBe("Slow down");
    expect(e.code).toBe("rate_limited");
    expect(e.requestId).toBe("req_1");
    expect(e.retryable).toBe(true);
    expect(e.retryAfterSeconds).toBe(3);
    expect(e.detail).toBe("Slow down");
    expect(e.errors).toHaveLength(1);
  });

  it("tolerates an old server: only detail, request id from the header", () => {
    const e = makeStatusError(500, { detail: "boom" }, h({ "x-request-id": "hdr_1" }));
    expect(e.code).toBeNull();
    expect(e.retryable).toBeNull();
    expect(e.retryAfterSeconds).toBeNull();
    expect(e.errors).toBeNull();
    expect(e.requestId).toBe("hdr_1");
  });

  it("handles an object-valued detail (section 404s) and a non-JSON body", () => {
    const e = makeStatusError(404, { detail: { message: "No such section", reason: "r" } }, h());
    expect(e.message).toBe("No such section");
    expect(e.detail).toEqual({ message: "No such section", reason: "r" });
    const t = makeStatusError(502, "<html>bad gateway</html>", h());
    expect(t.message).toBe("HTTP 502");
    expect(t.body).toBe("<html>bad gateway</html>");
  });

  it("is raised from a real response with the body attached", async () => {
    const { client } = makeClient([json(404, { detail: "nope", code: "section_not_found" })]);
    await expect(client.statutes.getSection("x")).rejects.toMatchObject({
      status: 404,
      code: "section_not_found",
      body: { detail: "nope", code: "section_not_found" },
    });
  });
});
