import { z } from "zod";

/** Jurisdiction codes the API accepts: `federal` plus 2-letter states and territories. */
export const STATES = [
  "federal",
  "al",
  "ak",
  "as",
  "az",
  "ar",
  "ca",
  "co",
  "ct",
  "de",
  "dc",
  "fl",
  "ga",
  "gu",
  "hi",
  "id",
  "il",
  "in",
  "ia",
  "ks",
  "ky",
  "la",
  "me",
  "md",
  "ma",
  "mi",
  "mn",
  "ms",
  "mo",
  "mt",
  "ne",
  "nv",
  "nh",
  "nj",
  "nm",
  "ny",
  "nc",
  "nd",
  "mp",
  "oh",
  "ok",
  "or",
  "pa",
  "pr",
  "ri",
  "sc",
  "sd",
  "tn",
  "tx",
  "ut",
  "vt",
  "vi",
  "va",
  "wa",
  "wv",
  "wi",
  "wy",
] as const;

/** Corpus types a search can be scoped to. */
export const CORPUS_TYPES = [
  "USC",
  "CFR",
  "STATE",
  "CONSTITUTION",
  "FEDERAL_RULES",
  "FEDERAL_LOCAL_RULES",
  "STATE_CONSTITUTION",
  "STATE_RULES",
  "EXECUTIVE_ACTION",
  "REGULATION",
  "FEDERAL_REGISTER",
  "FEDERAL_REGISTER_NOTICE",
  "AGENCY_GUIDANCE",
  "SENTENCING_GUIDELINES",
  "US_TAX_TREATY",
  "STATE_AGENCY_GUIDANCE",
  "STATE_AG_OPINION",
  "STATE_REGISTER",
  "SESSION_LAW",
  "STATUTE_COMPILATION",
  "AGENCY_ADJUDICATION",
  "CFR_ANNUAL",
  "USC_ANNUAL",
] as const;

/** The corpus types `resolve` accepts as a hint. */
export const RESOLVE_CORPUS_TYPES = [
  "CONSTITUTION",
  "REGULATION",
  "STATE",
  "STATE_CONSTITUTION",
  "STATE_RULES",
] as const;

/** The corpus types the browse endpoint accepts. */
export const DIVISION_CORPUS_TYPES = [
  "USC",
  "CFR",
  "STATE",
  "REGULATION",
  "STATE_RULES",
  "CONSTITUTION",
  "STATE_CONSTITUTION",
  "FEDERAL_RULES",
] as const;

const state = z
  .enum(STATES)
  .describe(
    "Jurisdiction: `federal` for USC, CFR, the US Constitution and federal rules, or a 2-letter lowercase code such as `ca` or `ny`.",
  );

export const stateOrList = z
  .union([state, z.array(state).min(1).max(10)])
  .describe(
    "Jurisdiction filter: `federal` or a 2-letter lowercase state code, or a list of them to search several at once in ONE call.",
  );

export const corpusOrList = z
  .union([z.enum(CORPUS_TYPES), z.array(z.enum(CORPUS_TYPES)).min(1).max(10)])
  .describe(
    "Kind of law: USC (federal statutes), CFR (federal regulations), STATE (state statutes), CONSTITUTION, STATE_CONSTITUTION, STATE_RULES (court rules), REGULATION (state regulations), FEDERAL_RULES, FEDERAL_REGISTER, AGENCY_GUIDANCE, STATE_AG_OPINION, and others. Omit to search every kind.",
  );

export const actId = z
  .string()
  .min(1)
  .max(200)
  .describe(
    "Vaquill section id (`actId`), exactly as returned in a search or resolve result. Never invent one.",
  );

export const searchStatutesInput = z.object({
  query: z
    .string()
    .min(1)
    .max(1000)
    .describe(
      "What to find. A topic ('statute of limitations for medical malpractice') or a citation ('42 U.S.C. 1983'); a citation is resolved to the exact section.",
    ),
  state: stateOrList.optional(),
  corpusType: corpusOrList.optional(),
  code: z
    .string()
    .max(100)
    .optional()
    .describe("State code id, for example `tx_pe` for the Texas Penal Code."),
  titleNumber: z.number().int().min(1).optional().describe("Title number, e.g. 42 for 42 USC."),
  chapter: z.string().max(100).optional().describe("Chapter within the title or code."),
  part: z.string().max(100).optional().describe("Part within the title or code."),
  article: z.string().max(100).optional().describe("Article within the code."),
  matchType: z
    .enum(["any", "all", "phrase", "boolean"])
    .optional()
    .describe(
      "`any` (default, best for topics), `all` (every word), `phrase` (exact phrase), `boolean` (AND/OR/NOT operators).",
    ),
  excludeRepealed: z.boolean().optional().describe("Drop repealed and otherwise dead sections."),
  yearFrom: z.number().int().min(1700).max(2100).optional().describe("Earliest enactment year."),
  yearTo: z.number().int().min(1700).max(2100).optional().describe("Latest enactment year."),
  changedSince: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/)
    .optional()
    .describe("YYYY-MM-DD. Only sections observed to change on or after this date."),
  includeBody: z
    .boolean()
    .optional()
    .describe(
      "Return full section text in each result. Large; leave off and fetch one section with getStatuteSectionText instead.",
    ),
  limit: z
    .number()
    .int()
    .min(1)
    .max(50)
    .optional()
    .describe("Results to return, 1 to 50. Default 5. Credits scale with what is returned."),
  offset: z.number().int().min(0).max(10000).optional().describe("Skip this many results."),
});

export const getStatuteSectionInput = z.object({ actId });

export const getStatuteSectionTextInput = z.object({
  actId,
  format: z
    .enum(["plain", "markdown", "operative"])
    .optional()
    .describe(
      "`plain` (default), `markdown` (keeps tables and headings), or `operative` (the operative text without notes).",
    ),
  asOf: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/)
    .optional()
    .describe("YYYY-MM-DD. Text as it stood on that date, where history exists."),
  pinpoint: z
    .string()
    .max(100)
    .optional()
    .describe("A subsection to return only, e.g. `(c)(2)`. Cuts the size of the answer."),
});

export const resolveCitationInput = z.object({
  cite: z
    .string()
    .min(1)
    .max(300)
    .describe("One citation, e.g. `42 U.S.C. § 1983`, `Cal. Penal Code § 187`, `12 CFR 1026.3`."),
  state: state.optional(),
  corpusType: z.enum(RESOLVE_CORPUS_TYPES).optional().describe("Hint for an ambiguous citation."),
});

export const resolveCitationsInput = z.object({
  citations: z
    .array(z.string().min(1).max(300))
    .min(1)
    .max(100)
    .describe("Citations to resolve, at most 100 per call. Each one costs credits."),
  state: state.optional(),
  corpusType: z.enum(RESOLVE_CORPUS_TYPES).optional().describe("Hint for ambiguous citations."),
});

export const extractCitationsInput = z.object({
  text: z
    .string()
    .min(1)
    .max(50000)
    .describe("Text (a brief, opinion, contract, email) to scan for statute and regulation cites."),
  state: z.enum(STATES.filter((s) => s !== "federal") as [string, ...string[]]).optional(),
  resolve: z
    .boolean()
    .optional()
    .describe("Resolve each distinct citation to a section (default true)."),
  includeUnresolved: z
    .boolean()
    .optional()
    .describe("Also list citations that could not be resolved (default true)."),
});

export const countSectionsInput = z.object({
  query: z.string().max(1000).optional().describe("Optional text to count matches for."),
  state: stateOrList.optional(),
  corpusType: corpusOrList.optional(),
  code: z.string().max(100).optional(),
  titleNumber: z.number().int().min(1).optional(),
  chapter: z.string().max(100).optional(),
  part: z.string().max(100).optional(),
  article: z.string().max(100).optional(),
  excludeRepealed: z.boolean().optional(),
});

export const listDivisionsInput = z.object({
  corpusType: z
    .enum(DIVISION_CORPUS_TYPES)
    .describe("Which body of law to browse: USC, CFR, STATE, REGULATION, and so on."),
  state: z.enum(STATES).optional().describe("Required for the state corpus types."),
  titleNumber: z.number().int().min(1).optional(),
  code: z.string().max(100).optional(),
  chapter: z.string().max(100).optional(),
  part: z.string().max(100).optional(),
  article: z.string().max(100).optional(),
  subchapter: z.string().max(100).optional(),
  excludeRepealed: z.boolean().optional(),
  cursor: z.string().max(500).optional().describe("`nextCursor` from the previous page."),
});

export const sectionChangesInput = z.object({
  actId,
  limit: z.number().int().min(1).max(200).optional().describe("Changes per page. Default 20."),
  changeKind: z
    .array(z.enum(["added", "amended", "removed"]))
    .min(1)
    .optional(),
  order: z.enum(["asc", "desc"]).optional().describe("`desc` (default) is newest first."),
  beforeId: z.number().int().min(0).optional().describe("Page back from this change id."),
  sinceId: z.number().int().min(0).optional().describe("Page forward from this change id."),
});

export const citedByInput = z.object({
  actId,
  limit: z.number().int().min(1).max(100).optional().describe("Default 10."),
});

export const definitionsInput = z.object({ actId });

export const neighborsInput = z.object({
  actId,
  limit: z.number().int().min(1).max(10).optional().describe("Default 3."),
});

export const searchSessionLawsInput = z.object({
  query: z.string().min(1).max(1000),
  jurisdiction: z.enum(STATES).optional(),
  session: z.string().max(50).optional().describe("Legislative session, e.g. `2023`."),
  instrumentType: z
    .array(
      z.enum([
        "act",
        "joint_resolution",
        "concurrent_resolution",
        "resolution",
        "resolve",
        "memorial",
        "other",
      ]),
    )
    .min(1)
    .optional(),
  approvedFrom: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/)
    .optional(),
  approvedTo: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/)
    .optional(),
  limit: z.number().int().min(1).max(25).optional().describe("Default 5."),
  offset: z.number().int().min(0).max(59).optional(),
});

export const getSessionLawInput = z.object({
  sessionLawId: z
    .string()
    .min(1)
    .max(200)
    .describe("Session law id exactly as returned by searchSessionLaws."),
  jurisdiction: z.enum(STATES).optional(),
});

export const creditBalanceInput = z.object({});

export const listWatchesInput = z.object({
  limit: z.number().int().min(1).max(100).optional(),
  offset: z.number().int().min(0).optional(),
});

export const createWatchInput = z.object({
  corpusType: z
    .string()
    .min(1)
    .max(100)
    .describe(
      "Source to watch, e.g. `state`, `USC`, `CFR`, `state_regulation`, `federal_register`.",
    ),
  state: z.enum(STATES).optional().describe("Jurisdiction of the source, where it has one."),
  scope: z
    .record(z.string(), z.string())
    .optional()
    .describe("Narrow to one citation, e.g. {title: '21', part: '314'}."),
  channel: z.enum(["webhook", "email", "both"]).optional().describe("Default `webhook`."),
  emailAddress: z.string().max(320).optional().describe("Required for channel email or both."),
  webhookUrl: z.string().max(2000).optional().describe("Required for channel webhook or both."),
});

export const updateWatchInput = z.object({
  watchId: z.string().min(1).max(100),
  scope: z.record(z.string(), z.string()).optional(),
  emailAddress: z.string().max(320).optional(),
  webhookUrl: z.string().max(2000).optional(),
  isActive: z.boolean().optional().describe("false pauses the watch."),
});

export const deleteWatchInput = z.object({ watchId: z.string().min(1).max(100) });

export const testWatchInput = z.object({
  watchId: z
    .string()
    .min(1)
    .max(100)
    .describe("Watch id exactly as returned by listWatches or createWatch."),
});
