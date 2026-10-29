import { Vaquill } from "../../../dist/index.js";

const c = new Vaquill();
const r = await c.credits.balance().withResponse();
console.log("deno ok", r.meta.status, typeof r.data.creditsRemaining);
