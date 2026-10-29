import { Vaquill, VERSION } from "../../../dist/index.js";

const c = new Vaquill();
const r = await c.credits.balance().withResponse();
console.log(
  "esm ok",
  r.meta.status,
  typeof r.data.creditsRemaining,
  "requestId" in r.meta,
  "version",
  VERSION ?? "n/a",
);
