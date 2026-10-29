import type { Vaquill } from "@vaquill-ai/sdk";
import { type Tool, tool } from "ai";
import type { z } from "zod";
import { run, type ToolOptions, type ToolResult } from "./run.js";
import * as s from "./schemas.js";

type Input<T extends z.ZodType> = z.infer<T>;
/** A Vaquill tool: validated input in, a structured `ToolResult` out. */
export type VaquillTool<S extends z.ZodType> = Tool<z.infer<S>, ToolResult>;
type Ctx = { abortSignal?: AbortSignal };

// The SDK's request types are generated from the OpenAPI document, and a few of them are wider
// than the zod schemas here (for example arrays of ~150 field names). The zod schemas are the
// narrower contract, so the casts below only widen what is passed through to the SDK.
type Any = any;

const sig = (c: Ctx | undefined) => ({ signal: c?.abortSignal });

// ----------------------------------------------------------------------------------- statutes

export const searchStatutesTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.searchStatutesInput> =>
  tool({
    description:
      "Search US primary law: federal and state statutes, regulations (CFR), constitutions, court rules, Federal Register and agency material. Accepts a topic or a citation (a citation is resolved to the exact section). Returns ranked sections with actId, citation, title, jurisdiction, status and an excerpt. COSTS CREDITS on every call, scaled by what is returned, so prefer a small `limit` (default 5), filter by `state` and `corpusType`, and fetch the full text of only the one or two sections you need with getStatuteSectionText. Do not repeat a search that already answered the question.",
    inputSchema: s.searchStatutesInput,
    execute: (input: Input<typeof s.searchStatutesInput>, c: Ctx) =>
      run(client, o, () => client.statutes.search({ limit: 5, ...input } as Any, sig(c))),
  });

export const getStatuteSectionTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.getStatuteSectionInput> =>
  tool({
    description:
      "Fetch the metadata record of ONE statute, regulation or rule section by actId: citation, heading, jurisdiction, status (in force, repealed, ...), hierarchy and source link. Does not return the full text; use getStatuteSectionText for that. COSTS CREDITS per call. Use an actId from a previous search or resolve result, never a guessed one.",
    inputSchema: s.getStatuteSectionInput,
    execute: (input: Input<typeof s.getStatuteSectionInput>, c: Ctx) =>
      run(client, o, () => client.statutes.getSection(input.actId, sig(c))),
  });

export const getStatuteSectionTextTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.getStatuteSectionTextInput> =>
  tool({
    description:
      "Read the full text of ONE statute, regulation or rule section by actId. Returns the body in the requested format (plain by default), and tables or notes where the section has them. Set `pinpoint` (for example `(c)(2)`) to get only that subsection, and `asOf` for the text on a past date. COSTS CREDITS per call and long sections are large, so only fetch sections you will actually quote or analyze. If `bodyUnavailable` is true the text is not held; say so rather than guessing.",
    inputSchema: s.getStatuteSectionTextInput,
    execute: (input: Input<typeof s.getStatuteSectionTextInput>, c: Ctx) => {
      const { actId, ...query } = input;
      return run(client, o, () =>
        client.statutes.getSectionBody(actId, { format: "plain", ...query } as Any, sig(c)),
      );
    },
  });

export const resolveCitationTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.resolveCitationInput> =>
  tool({
    description:
      "Turn ONE legal citation (for example `42 U.S.C. § 1983`, `Cal. Penal Code § 187`, `12 CFR 1026.3`) into the section it names. Returns the actId, a match indicator and the section's metadata, or a clear 'not resolved' result. Use this to verify a citation exists before relying on it. COSTS CREDITS per call. For several citations use resolveCitations.",
    inputSchema: s.resolveCitationInput,
    execute: (input: Input<typeof s.resolveCitationInput>, c: Ctx) =>
      run(client, o, () => client.statutes.resolve(input as Any, sig(c))),
  });

export const resolveCitationsTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.resolveCitationsInput> =>
  tool({
    description:
      "Resolve MANY citations in one call (at most 100). Returns one result per citation in order, each with the matched actId or a not-resolved marker. COSTS CREDITS PER CITATION, so deduplicate first and send only citations you need to verify.",
    inputSchema: s.resolveCitationsInput,
    execute: (input: Input<typeof s.resolveCitationsInput>, c: Ctx) =>
      run(client, o, () => client.statutes.resolveBatch(input as Any, sig(c))),
  });

export const extractCitationsTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.extractCitationsInput> =>
  tool({
    description:
      "Find every statute and regulation citation inside a block of text (a brief, opinion, contract, email) and, by default, resolve each distinct one to its section. Returns the citations found, their positions and the matched actIds. COSTS CREDITS per DISTINCT citation found, so a long text with many cites is expensive; pass `resolve: false` to only list them.",
    inputSchema: s.extractCitationsInput,
    execute: (input: Input<typeof s.extractCitationsInput>, c: Ctx) =>
      run(client, o, () => client.statutes.extractCitations(input as Any, sig(c))),
  });

export const countSectionsTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.countSectionsInput> =>
  tool({
    description:
      "Count the sections that match a filter or query without returning them, for example how many sections the Texas Penal Code has or how many matches a phrase has in federal regulations. Returns a number and breakdowns. COSTS CREDITS per call. Use it to size a question before searching.",
    inputSchema: s.countSectionsInput,
    execute: (input: Input<typeof s.countSectionsInput>, c: Ctx) =>
      run(client, o, () => client.statutes.count(input as Any, sig(c))),
  });

export const listDivisionsTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.listDivisionsInput> =>
  tool({
    description:
      "Browse the structure of a body of law: list titles, chapters, parts or articles one level below the filters given (for example corpusType STATE with state `tx` lists Texas codes; adding `code` lists its chapters). Returns divisions with counts and a `nextCursor` for the next page. COSTS CREDITS per page. Use it to find where a topic lives when search is too broad.",
    inputSchema: s.listDivisionsInput,
    execute: (input: Input<typeof s.listDivisionsInput>, c: Ctx) =>
      run(client, o, () => client.statutes.listDivisions(input as Any, sig(c))),
  });

export const sectionChangesTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.sectionChangesInput> =>
  tool({
    description:
      "History of a section: the amendments, additions and removals Vaquill has observed, newest first, each with a date and change id. Use it to answer 'when did this change' or 'was this ever amended'. Not a complete legislative history from before Vaquill began tracking. COSTS CREDITS per page; `hasMore` says whether another page exists (pass the last change id as `beforeId`).",
    inputSchema: s.sectionChangesInput,
    execute: (input: Input<typeof s.sectionChangesInput>, c: Ctx) => {
      const { actId, ...query } = input;
      return run(client, o, () =>
        client.statutes.getSectionChanges(actId, { limit: 20, ...query } as Any, sig(c)),
      );
    },
  });

export const citedByTool = (client: Vaquill, o?: ToolOptions): VaquillTool<typeof s.citedByInput> =>
  tool({
    description:
      "Other sections in the corpus that cite this section (for example regulations that cite a statute). Returns citing sections with their actIds and citations. COSTS CREDITS per call. Not a case-law citator.",
    inputSchema: s.citedByInput,
    execute: (input: Input<typeof s.citedByInput>, c: Ctx) => {
      const { actId, ...query } = input;
      return run(client, o, () =>
        client.statutes.getSectionCitedBy(actId, { limit: 10, ...query } as Any, sig(c)),
      );
    },
  });

export const definitionsTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.definitionsInput> =>
  tool({
    description:
      "Defined terms that apply to a section: the definitions that govern the words it uses, with the section that defines each. COSTS CREDITS per call. Use it before interpreting a term of art in a statute.",
    inputSchema: s.definitionsInput,
    execute: (input: Input<typeof s.definitionsInput>, c: Ctx) =>
      run(client, o, () => client.statutes.getSectionDefinitions(input.actId, sig(c))),
  });

export const neighborsTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.neighborsInput> =>
  tool({
    description:
      "The sections immediately before and after this one in its code, so you can read surrounding context. Returns neighbor actIds, citations and headings (not full text). COSTS CREDITS per call.",
    inputSchema: s.neighborsInput,
    execute: (input: Input<typeof s.neighborsInput>, c: Ctx) => {
      const { actId, ...query } = input;
      return run(client, o, () =>
        client.statutes.getSectionNeighbors(actId, { limit: 3, ...query } as Any, sig(c)),
      );
    },
  });

// -------------------------------------------------------------------------------- session laws

export const searchSessionLawsTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.searchSessionLawsInput> =>
  tool({
    description:
      "Search US session laws: acts as enacted by a legislature in a given session (not the codified statute). Filter by `jurisdiction`, `session`, instrument type and approval dates. Returns ranked session laws with sessionLawId, title, session, approval date and status. COSTS CREDITS per page, so keep `limit` small.",
    inputSchema: s.searchSessionLawsInput,
    execute: (input: Input<typeof s.searchSessionLawsInput>, c: Ctx) =>
      run(client, o, () => client.sessionLaws.search({ limit: 5, ...input } as Any, sig(c))),
  });

export const getSessionLawTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.getSessionLawInput> =>
  tool({
    description:
      "Metadata of ONE session law by sessionLawId: title, session, approval and effective dates, instrument type, and whether its text is held. Does not return the full text. COSTS CREDITS per call. Use a sessionLawId from searchSessionLaws.",
    inputSchema: s.getSessionLawInput,
    execute: (input: Input<typeof s.getSessionLawInput>, c: Ctx) => {
      const { sessionLawId, ...query } = input;
      return run(client, o, () => client.sessionLaws.get(sessionLawId, query as Any, sig(c)));
    },
  });

// ------------------------------------------------------------------------------------ account

export const creditBalanceTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.creditBalanceInput> =>
  tool({
    description:
      "Remaining Vaquill credits for the API key, split by funding source, with the plan and next expiry. FREE: costs no credits. Check it before a large batch of paid calls.",
    inputSchema: s.creditBalanceInput,
    execute: (_input: Input<typeof s.creditBalanceInput>, c: Ctx) =>
      run(client, o, () => client.credits.balance(sig(c))),
  });

// -------------------------------------------------------------------------- watches (writes)

export const listWatchesTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.listWatchesInput> =>
  tool({
    description:
      "List the law-change alert watches on this account. FREE. Only available when writes are enabled.",
    inputSchema: s.listWatchesInput,
    execute: (input: Input<typeof s.listWatchesInput>, c: Ctx) =>
      run(client, o, () => client.watches.list(input as Any, sig(c))),
  });

export const createWatchTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.createWatchInput> =>
  tool({
    description:
      "CREATE a persistent law-change alert: Vaquill will email or POST to a webhook whenever the chosen source (or one citation within it) changes. This is a WRITE with lasting effect and sends data to the address given, so only call it when the user explicitly asked for an alert and gave the destination. Returns the watch id.",
    inputSchema: s.createWatchInput,
    execute: (input: Input<typeof s.createWatchInput>, c: Ctx) =>
      run(client, o, () => client.watches.create(input as Any, sig(c))),
  });

export const updateWatchTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.updateWatchInput> =>
  tool({
    description:
      "CHANGE an existing law-change alert (scope, destination or paused state). This is a WRITE; only call it when the user asked for that change.",
    inputSchema: s.updateWatchInput,
    execute: (input: Input<typeof s.updateWatchInput>, c: Ctx) => {
      const { watchId, ...body } = input;
      return run(client, o, () => client.watches.update(watchId, body as Any, sig(c)));
    },
  });

export const deleteWatchTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.deleteWatchInput> =>
  tool({
    description:
      "PERMANENTLY DELETE a law-change alert. Cannot be undone. Only call it when the user explicitly asked to delete that watch.",
    inputSchema: s.deleteWatchInput,
    execute: (input: Input<typeof s.deleteWatchInput>, c: Ctx) =>
      run(client, o, async () => {
        await client.watches.delete(input.watchId, sig(c));
        return { deleted: true, watchId: input.watchId };
      }),
  });

export const testWatchTool = (
  client: Vaquill,
  o?: ToolOptions,
): VaquillTool<typeof s.testWatchInput> =>
  tool({
    description:
      "SEND A TEST EVENT to the destination of an existing law-change alert (a POST to its webhook URL or an email, marked as a test delivery). FREE, but it contacts the customer's own endpoint, so only call it when the user explicitly asked to test that watch. Limited to one test per watch every 30 seconds. Returns the delivery outcome (channel and the webhook status code).",
    inputSchema: s.testWatchInput,
    execute: (input: Input<typeof s.testWatchInput>, c: Ctx) =>
      run(client, o, () => client.watches.test(input.watchId, sig(c))),
  });
