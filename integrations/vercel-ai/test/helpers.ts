import { createServer, type IncomingMessage, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { Vaquill } from "@vaquill-ai/sdk";

export const TEST_KEY = "vq_key_TESTKEY0123456789abcdef";

export interface Recorded {
  method: string;
  path: string;
  query: Record<string, string>;
  body: unknown;
  headers: IncomingMessage["headers"];
}

export interface Reply {
  status?: number;
  body?: unknown;
  /** Delay before answering, in ms. */
  delay?: number;
  headers?: Record<string, string>;
}

export type Handler = (req: Recorded) => Reply | undefined;

export interface Fake {
  url: string;
  requests: Recorded[];
  /** Replace the handler. The default answers 200 with `{ creditsConsumed: 1 }`. */
  handle(h: Handler): void;
  client(options?: ConstructorParameters<typeof Vaquill>[0]): Vaquill;
  close(): Promise<void>;
}

/** A local HTTP server standing in for api.vaquill.ai. Nothing here touches the network. */
export async function startFake(): Promise<Fake> {
  const requests: Recorded[] = [];
  let handler: Handler = () => undefined;
  const server: Server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => {
      const url = new URL(req.url ?? "/", "http://fake");
      const raw = Buffer.concat(chunks).toString("utf8");
      const rec: Recorded = {
        method: req.method ?? "GET",
        path: url.pathname,
        query: Object.fromEntries(url.searchParams),
        body: raw ? JSON.parse(raw) : undefined,
        headers: req.headers,
      };
      requests.push(rec);
      const reply = handler(rec) ?? { body: { creditsConsumed: 1, ok: true } };
      setTimeout(() => {
        res.writeHead(reply.status ?? 200, {
          "content-type": "application/json",
          ...reply.headers,
        });
        res.end(reply.status === 204 ? undefined : JSON.stringify(reply.body ?? {}));
      }, reply.delay ?? 0);
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return {
    url,
    requests,
    handle: (h) => {
      handler = h;
    },
    client: (options) =>
      new Vaquill({ apiKey: TEST_KEY, baseURL: url, maxRetries: 0, logLevel: "off", ...options }),
    close: () =>
      new Promise<void>((resolve) => {
        server.closeAllConnections();
        server.close(() => resolve());
      }),
  };
}

/** Calls a tool's `execute` the way the AI SDK does. */
export async function exec(tool: unknown, input: unknown, abortSignal?: AbortSignal) {
  const t = tool as {
    execute: (input: unknown, options: unknown) => Promise<unknown>;
  };
  return (await t.execute(input, {
    toolCallId: "call_1",
    messages: [],
    context: undefined,
    abortSignal,
  })) as Record<string, any>;
}
