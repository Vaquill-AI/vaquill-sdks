import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  signWebhook,
  unwrapWebhook,
  verifyWebhook,
  WebhookVerificationError,
} from "../src/index.js";

// Known-answer vector from the Standard Webhooks README.
const SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw";
const ID = "msg_p5jXN8AQM9LWM0D4loKWxJek";
const TS = 1614265330;
const BODY = '{"test": 2432232314}';
const SIG = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=";

const headers = (over: Record<string, string> = {}) => ({
  "webhook-id": ID,
  "webhook-timestamp": String(TS),
  "webhook-signature": SIG,
  ...over,
});

describe("Standard Webhooks", () => {
  it("signs the README vector", async () => {
    expect(await signWebhook(ID, TS, BODY, SECRET)).toBe(SIG);
  });

  it("verifies the README vector", async () => {
    await expect(verifyWebhook(BODY, headers(), SECRET, { now: TS })).resolves.toBeUndefined();
  });

  it("refuses a whsec_ secret that is not valid base64 instead of using it as text", async () => {
    await expect(verifyWebhook(BODY, headers(), "whsec_not*base64!", { now: TS })).rejects.toThrow(
      /base64/,
    );
    await expect(signWebhook(ID, TS, BODY, "whsec_not*base64!")).rejects.toThrow(/base64/);
  });

  it("accepts bytes and a Headers object", async () => {
    await verifyWebhook(new TextEncoder().encode(BODY), new Headers(headers()), SECRET, {
      now: TS,
    });
  });

  it("rejects a tampered body, id, timestamp and signature", async () => {
    // Thunks, so each rejection is awaited as it is created (eager promises reject unhandled).
    const bad = [
      () => verifyWebhook(`${BODY} `, headers(), SECRET, { now: TS }),
      () => verifyWebhook(BODY, headers({ "webhook-id": "msg_other" }), SECRET, { now: TS }),
      () =>
        verifyWebhook(BODY, headers({ "webhook-timestamp": String(TS + 1) }), SECRET, { now: TS }),
      () => verifyWebhook(BODY, headers({ "webhook-signature": "v1,AAAA" }), SECRET, { now: TS }),
      () =>
        verifyWebhook(BODY, headers(), "whsec_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", { now: TS }),
    ];
    for (const run of bad) await expect(run()).rejects.toBeInstanceOf(WebhookVerificationError);
  });

  it("enforces the 300 second tolerance in both directions", async () => {
    await expect(
      verifyWebhook(BODY, headers(), SECRET, { now: TS + 300 }),
    ).resolves.toBeUndefined();
    await expect(verifyWebhook(BODY, headers(), SECRET, { now: TS + 301 })).rejects.toThrow(
      /tolerance/,
    );
    await expect(verifyWebhook(BODY, headers(), SECRET, { now: TS - 301 })).rejects.toThrow(
      /tolerance/,
    );
    await expect(
      verifyWebhook(BODY, headers(), SECRET, { now: TS + 400, toleranceSeconds: 500 }),
    ).resolves.toBeUndefined();
  });

  it("rejects missing headers and a non-numeric timestamp", async () => {
    await expect(verifyWebhook(BODY, {}, SECRET, { now: TS })).rejects.toThrow(/Missing/);
    await expect(
      verifyWebhook(BODY, headers({ "webhook-timestamp": "abc" }), SECRET, { now: TS }),
    ).rejects.toThrow(/timestamp/);
  });

  it("accepts any listed v1 signature (rotation) and ignores other versions", async () => {
    const other = await signWebhook(ID, TS, BODY, "whsec_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
    for (const list of [`${other} ${SIG}`, `${SIG} ${other}`, `v2,xyz ${SIG}`]) {
      await verifyWebhook(BODY, headers({ "webhook-signature": list }), SECRET, { now: TS });
    }
    await expect(
      verifyWebhook(BODY, headers({ "webhook-signature": `v2,${SIG.slice(3)}` }), SECRET, {
        now: TS,
      }),
    ).rejects.toBeInstanceOf(WebhookVerificationError);
  });

  it("accepts several configured secrets (receiver-side rotation)", async () => {
    await verifyWebhook(BODY, headers(), ["whsec_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", SECRET], {
      now: TS,
    });
  });

  it("uses the UTF-8 bytes of a secret without the whsec_ prefix", async () => {
    const legacySecret = "plain-secret-value";
    const mac = createHmac("sha256", Buffer.from(legacySecret, "utf8"))
      .update(`${ID}.${TS}.${BODY}`)
      .digest("base64");
    await verifyWebhook(BODY, headers({ "webhook-signature": `v1,${mac}` }), legacySecret, {
      now: TS,
    });
  });

  it("unwraps to parsed JSON", async () => {
    expect(await unwrapWebhook(BODY, headers(), SECRET, { now: TS })).toEqual({ test: 2432232314 });
  });
});

describe("legacy X-Vaquill-Signature", () => {
  const secret = "my-endpoint-secret";
  const body = '{"event":"watch.test","firedAt":"2026-01-01T00:00:00Z"}';
  const hex = createHmac("sha256", secret).update(body).digest("hex");

  it("is refused unless allowLegacy is set", async () => {
    await expect(
      verifyWebhook(body, { "x-vaquill-signature": `sha256=${hex}` }, secret),
    ).rejects.toThrow(/Missing/);
  });

  it("verifies with allowLegacy and rejects a tampered body or signature", async () => {
    const h = { "X-Vaquill-Signature": `sha256=${hex}` };
    await verifyWebhook(body, h, secret, { allowLegacy: true });
    await expect(
      verifyWebhook(`${body}x`, h, secret, { allowLegacy: true }),
    ).rejects.toBeInstanceOf(WebhookVerificationError);
    await expect(
      verifyWebhook(body, { "x-vaquill-signature": `sha256=${"0".repeat(64)}` }, secret, {
        allowLegacy: true,
      }),
    ).rejects.toBeInstanceOf(WebhookVerificationError);
    await expect(
      verifyWebhook(body, { "x-vaquill-signature": "nonsense" }, secret, { allowLegacy: true }),
    ).rejects.toBeInstanceOf(WebhookVerificationError);
  });

  it("has no replay protection (an old delivery still verifies)", async () => {
    await verifyWebhook(body, { "x-vaquill-signature": `sha256=${hex}` }, secret, {
      allowLegacy: true,
      now: 4_000_000_000,
    });
  });

  it("is not used when Standard Webhooks headers are present but bad", async () => {
    await expect(
      verifyWebhook(body, { "webhook-id": "x", "x-vaquill-signature": `sha256=${hex}` }, secret, {
        allowLegacy: true,
      }),
    ).rejects.toThrow(/Missing/);
  });
});
