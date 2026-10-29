import type { OperationTypes } from "./_generated/api.js";

type Ops = OperationTypes;

/** Query parameters of an operation (the `Idempotency-Key` header is handled by the client). */
export type QueryOf<K extends keyof Ops> = NonNullable<Ops[K]["query"]>;

/** JSON request body of an operation. */
export type BodyOf<K extends keyof Ops> = Ops[K]["body"];

/** JSON body of the success response (200 or 201). */
export type ResponseOf<K extends keyof Ops> = Ops[K]["response"];

/** Operation ids accepted by `QueryOf`, `BodyOf` and `ResponseOf`. */
export type OperationId = keyof Ops;

/** Log levels, lowest first. `off` silences the logger. */
export type LogLevel = "debug" | "info" | "warn" | "error" | "off";

/** Any subset of these methods is accepted; missing ones are no-ops. `console` fits. */
export interface Logger {
  debug(message: string): void;
  info(message: string): void;
  warn(message: string): void;
  error(message: string): void;
}
