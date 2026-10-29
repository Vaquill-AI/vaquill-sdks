import { Vaquill } from "../src/index.js";

export const KEY = "vq_key_test_0123456789abcdef";

export interface Call {
  url: URL;
  method: string;
  headers: Headers;
  body: unknown;
  signal: AbortSignal | null | undefined;
}

export function json(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

type Step = Response | Error | (() => Response | Promise<Response>);

/** A scripted `fetch`. The last step repeats. Records every call. */
export function scripted(steps: Step[]) {
  const calls: Call[] = [];
  const fn = (async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({
      url: new URL(String(input)),
      method: init?.method ?? "GET",
      headers: new Headers(init?.headers),
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      signal: init?.signal,
    });
    const step = steps[Math.min(calls.length - 1, steps.length - 1)];
    if (step instanceof Error) throw step;
    const res = typeof step === "function" ? await step() : step;
    return (res as Response).clone();
  }) as typeof fetch;
  return { fn, calls };
}

export function makeClient(steps: Step[], options: ConstructorParameters<typeof Vaquill>[0] = {}) {
  const { fn, calls } = scripted(steps);
  const client = new Vaquill({ apiKey: KEY, baseURL: "https://api.test", fetch: fn, ...options });
  return { client, calls };
}
