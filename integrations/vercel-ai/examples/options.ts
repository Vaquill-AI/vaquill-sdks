import { Vaquill } from "@vaquill-ai/sdk";
import { createVaquillTools } from "@vaquill-ai/ai-sdk";

createVaquillTools({
  apiKey: process.env.VAQUILL_API_KEY, // default: process.env.VAQUILL_API_KEY
  client: new Vaquill(), // your own configured Vaquill client (base URL, retries, fetch)
  maxCredits: 100, // hard spend cap, default 200, Infinity to disable
  include: ["searchStatutes", "resolveCitation"], // only these tool names
  exclude: ["extractCitations"], // everything except these (applied after include)
  allowWrites: false, // expose the watch tools, default false
  maxResultChars: 60_000, // replace results larger than this with a preview, default 60000
  redact: ["internal-secret"], // extra strings to scrub from error messages
});
